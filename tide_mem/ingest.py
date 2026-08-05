from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from .db import MemoryDB
from .llm import LLMClient
from .models import AddRequest, AddResponse
from .text import (
    heuristic_entities,
    iso_from_ms,
    json_dumps,
    normalize_space,
    stable_id,
    truncate,
    unique_preserve,
    utc_now_iso,
)

LOGGER = logging.getLogger(__name__)


class IdempotencyConflict(ValueError):
    """A request_id was replayed with a different identity boundary."""

_STATE_KEY_RE = re.compile(r"[^a-z0-9_.:/-]+")
_ALLOWED_CHANGE = {"set", "append", "cancel", "complete", "none"}


def _parse_event_time(value: Any) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw or raw.lower() in {"null", "none", "unknown"}:
        return None, None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat().replace("+00:00", "Z"), int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return None, None


def _clean_strings(value: Any, limit: int, item_chars: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique_preserve(truncate(str(item), item_chars) for item in value)[:limit]


def _source_indexes(value: Any, message_count: int) -> list[int]:
    if not isinstance(value, list):
        return []
    output: list[int] = []
    for item in value:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < message_count and index not in output:
            output.append(index)
    return output


def _normalize_state_key(value: Any) -> str | None:
    if value is None:
        return None
    raw = normalize_space(str(value)).casefold()
    if not raw or raw in {"null", "none", "unknown"}:
        return None
    normalized = _STATE_KEY_RE.sub("_", raw).strip("_")
    return normalized[:160] or None


class IngestionService:
    def __init__(self, db: MemoryDB, llm: LLMClient) -> None:
        self.db = db
        self.llm = llm

    async def add(self, request: AddRequest) -> AddResponse:
        # Fast idempotency path for evaluator retries. The transactional check in
        # insert_bundle remains authoritative under concurrent duplicate calls.
        existing = await self.db.request_identity(request.request_id)
        if existing is not None:
            if existing != (request.user_id, request.session_id):
                raise IdempotencyConflict(
                    "request_id already belongs to a different user_id/session_id"
                )
            return AddResponse(
                request_id=request.request_id,
                user_id=request.user_id,
                session_id=request.session_id,
            )

        state_hints = await self.db.current_states(request.user_id)
        extraction = await self.llm.extract_memories(
            request.messages,
            request.session_id,
            state_hints=state_hints,
        )
        records = self._build_records(request, extraction)
        inserted = await self.db.insert_bundle(
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
            records=records,
        )
        if not inserted:
            existing = await self.db.request_identity(request.request_id)
            if existing != (request.user_id, request.session_id):
                raise IdempotencyConflict(
                    "concurrent request_id replay crossed an identity boundary"
                )
        LOGGER.info(
            "persisted request_id=%s user_hash=%s session_hash=%s records=%d",
            request.request_id,
            stable_id(request.user_id, prefix="usr")[-10:],
            stable_id(request.session_id, prefix="ses")[-10:],
            len(records),
        )
        return AddResponse(
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    def _build_records(self, request: AddRequest, extraction: dict[str, Any]) -> list[dict[str, Any]]:
        created_at = utc_now_iso()
        now_ms = int(time.time() * 1000)
        records: list[dict[str, Any]] = []

        # Immutable raw evidence is the provenance anchor. Semantic cards can fail
        # gracefully without losing the original conversation evidence.
        for index, message in enumerate(request.messages):
            timestamp_iso = iso_from_ms(message.timestamp)
            source = (
                f"[Raw conversation evidence | session={request.session_id} | "
                f"message={index} | timestamp={timestamp_iso or 'unknown'}]\n"
                f"{message.role}: {message.content}"
            )
            entities = heuristic_entities(message.content)
            searchable = " ".join([message.content, *entities, request.session_id, message.role])
            ordering_ms = message.timestamp if message.timestamp is not None else now_ms + index
            records.append(
                {
                    "id": stable_id(request.request_id, "raw", index),
                    "kind": "raw_episode",
                    "role": message.role,
                    "content": source,
                    "searchable_text": searchable,
                    "timestamp_ms": message.timestamp,
                    "event_time": timestamp_iso,
                    "event_time_ms": message.timestamp,
                    "ordering_ms": ordering_ms,
                    "created_at": created_at,
                    "entities_json": json_dumps(entities),
                    "keywords_json": "[]",
                    "state_key": None,
                    "change_type": "none",
                    "is_current": False,
                    "source_indices_json": json_dumps([index]),
                }
            )

        # Overlapping two-message windows preserve local dialogue adjacency for
        # pronouns, answers, corrections, and speaker attribution without replacing
        # the verbatim per-message records.
        for right in range(1, len(request.messages)):
            left = right - 1
            left_message = request.messages[left]
            right_message = request.messages[right]
            window_content = (
                f"[Raw conversation adjacency evidence | session={request.session_id} | "
                f"messages={left},{right}]\n"
                f"{left_message.role}: {truncate(left_message.content, 780)}\n"
                f"{right_message.role}: {truncate(right_message.content, 780)}"
            )
            window_entities = heuristic_entities(
                f"{left_message.content} {right_message.content}"
            )
            timestamps = [
                value
                for value in (left_message.timestamp, right_message.timestamp)
                if value is not None
            ]
            window_timestamp = max(timestamps) if timestamps else None
            records.append(
                {
                    "id": stable_id(request.request_id, "window", left, right),
                    "kind": "raw_window",
                    "role": None,
                    "content": window_content,
                    "searchable_text": " ".join(
                        [
                            left_message.content,
                            right_message.content,
                            *window_entities,
                            request.session_id,
                        ]
                    ),
                    "timestamp_ms": window_timestamp,
                    "event_time": iso_from_ms(window_timestamp),
                    "event_time_ms": window_timestamp,
                    "ordering_ms": window_timestamp or now_ms + right,
                    "created_at": created_at,
                    "entities_json": json_dumps(window_entities),
                    "keywords_json": "[]",
                    "state_key": None,
                    "change_type": "none",
                    "is_current": False,
                    "source_indices_json": json_dumps([left, right]),
                }
            )

        cards = extraction.get("memory_cards", []) if isinstance(extraction, dict) else []
        if not isinstance(cards, list):
            cards = []
        for card_index, card in enumerate(cards[: self.llm.settings.max_cards_per_add]):
            if not isinstance(card, dict):
                continue
            content = truncate(normalize_space(str(card.get("content", ""))), 1600)
            if not content:
                continue
            indices = _source_indexes(card.get("source_message_indexes"), len(request.messages))
            entities = _clean_strings(card.get("entities"), 20)
            keywords = _clean_strings(card.get("keywords"), 24)
            event_time, event_time_ms = _parse_event_time(card.get("event_time"))
            source_timestamps = [
                request.messages[i].timestamp
                for i in indices
                if request.messages[i].timestamp is not None
            ]
            ordering_ms = event_time_ms or (max(source_timestamps) if source_timestamps else now_ms + card_index)
            state_key = _normalize_state_key(card.get("state_key"))
            change_type = str(card.get("change_type", "none")).casefold()
            if change_type not in _ALLOWED_CHANGE:
                change_type = "none"
            if not state_key:
                change_type = "none" if change_type in {"set", "cancel", "complete"} else change_type
            kind = re.sub(r"[^a-z0-9_-]+", "_", str(card.get("kind", "other")).casefold())[:40]
            evidence = (
                f"[Structured memory evidence | session={request.session_id} | "
                f"source_messages={indices or 'unspecified'} | event_time={event_time or 'unknown'}]\n"
                f"{content}"
            )
            source_text = " ".join(request.messages[i].content for i in indices)
            searchable = " ".join([content, *entities, *keywords, source_text, request.session_id])
            records.append(
                {
                    "id": stable_id(request.request_id, "card", card_index, content),
                    "kind": f"card_{kind or 'other'}",
                    "role": None,
                    "content": evidence,
                    "searchable_text": searchable,
                    "timestamp_ms": max(source_timestamps) if source_timestamps else None,
                    "event_time": event_time,
                    "event_time_ms": event_time_ms,
                    "ordering_ms": ordering_ms,
                    "created_at": created_at,
                    "entities_json": json_dumps(entities),
                    "keywords_json": json_dumps(keywords),
                    "state_key": state_key,
                    "change_type": change_type,
                    "is_current": bool(state_key and change_type in {"set", "cancel", "complete"}),
                    "source_indices_json": json_dumps(indices),
                }
            )

        summaries = extraction.get("session_summary", []) if isinstance(extraction, dict) else []
        if not isinstance(summaries, list):
            summaries = []
        for summary_index, summary in enumerate(summaries[: self.llm.settings.max_summary_cards_per_add]):
            if not isinstance(summary, dict):
                continue
            content = truncate(normalize_space(str(summary.get("content", ""))), 1800)
            if not content:
                continue
            indices = _source_indexes(summary.get("source_message_indexes"), len(request.messages))
            entities = _clean_strings(summary.get("entities"), 24)
            keywords = _clean_strings(summary.get("keywords"), 30)
            source_timestamps = [
                request.messages[i].timestamp
                for i in indices
                if request.messages[i].timestamp is not None
            ]
            ordering_ms = max(source_timestamps) if source_timestamps else now_ms + summary_index
            evidence = (
                f"[Session evidence summary | session={request.session_id} | "
                f"source_messages={indices or 'all'}]\n{content}"
            )
            records.append(
                {
                    "id": stable_id(request.request_id, "summary", summary_index, content),
                    "kind": "session_summary",
                    "role": None,
                    "content": evidence,
                    "searchable_text": " ".join([content, *entities, *keywords, request.session_id]),
                    "timestamp_ms": max(source_timestamps) if source_timestamps else None,
                    "event_time": None,
                    "event_time_ms": None,
                    "ordering_ms": ordering_ms,
                    "created_at": created_at,
                    "entities_json": json_dumps(entities),
                    "keywords_json": json_dumps(keywords),
                    "state_key": None,
                    "change_type": "none",
                    "is_current": False,
                    "source_indices_json": json_dumps(indices),
                }
            )

        return records
