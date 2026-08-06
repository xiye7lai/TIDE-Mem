"""Run public, local retrieval proxies against a TIDE-Mem Add/Search API.

The output is deliberately labelled as a proxy. It is useful for ablations and
regression checks, but it is not an Agent Memory Challenge leaderboard score.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, TypeVar

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tide_mem.text import stable_id


DEFAULT_KS = (1, 3, 5, 10, 30, 50, 100)
MAX_ADD_MESSAGES = 20
MAX_ADD_WORDS = 2_000
_SOURCE_HEADER_RE = re.compile(r"session=([^|\]]+)")
_SOURCE_INDEX_RE = re.compile(r"source_messages=(\[[^\]]*\])")
T = TypeVar("T")
R = TypeVar("R")


@dataclass(slots=True)
class EvalCase:
    ident: str
    question: str
    gold_answer: Any
    gold_evidence: set[str]
    user_id: str
    category: str
    speaker_1: str = "user"
    speaker_2: str = "assistant"


@dataclass(slots=True)
class AddJob:
    request_id: str
    user_id: str
    session_id: str
    messages: list[dict[str, Any]]

    def payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "messages": self.messages,
        }


@dataclass(slots=True)
class EvidenceIndex:
    """Map returned memory records back to public benchmark evidence units."""

    memory_units: dict[str, set[str]] = field(default_factory=dict)
    session_units: dict[str, list[str]] = field(default_factory=dict)
    session_level: bool = False

    def add_session(
        self,
        request_id: str,
        session_id: str,
        source_units: Iterable[str],
    ) -> None:
        units = [str(unit) for unit in source_units]
        self.session_units[session_id] = units
        for index, unit in enumerate(units):
            raw_id = stable_id(request_id, "raw", index)
            self.memory_units[raw_id] = {unit}
            if index:
                window_id = stable_id(request_id, "window", index - 1, index)
                self.memory_units[window_id] = {units[index - 1], unit}

    def resolve(self, item: dict[str, Any]) -> set[str]:
        ident = str(item.get("id", ""))
        if ident in self.memory_units:
            return self.memory_units[ident]

        content = str(item.get("content", ""))
        session_match = _SOURCE_HEADER_RE.search(content)
        if not session_match:
            return set()
        session_id = session_match.group(1).strip()
        units = self.session_units.get(session_id, [])
        if not units:
            return set()
        if self.session_level:
            return {units[0]}

        # Structured cards retain exact source indexes. Broad summaries whose
        # header says "all" are intentionally not credited by this conservative
        # message-level proxy.
        index_match = _SOURCE_INDEX_RE.search(content)
        if not index_match:
            return set()
        try:
            indexes = json.loads(index_match.group(1))
        except json.JSONDecodeError:
            return set()
        return {
            units[index]
            for index in indexes
            if isinstance(index, int) and 0 <= index < len(units)
        }


class MemoryAPI:
    def __init__(
        self,
        base_url: str,
        memory_key: str | None,
        timeout_seconds: float,
    ) -> None:
        headers = {"X-Api-Key": memory_key} if memory_key else {}
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
        )
        self.add_seconds: list[float] = []
        self.search_seconds: list[float] = []

    async def __aenter__(self) -> "MemoryAPI":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def health(self) -> None:
        response = await self.client.get("/health")
        response.raise_for_status()

    async def add(self, job: AddJob) -> None:
        started = time.perf_counter()
        response = await self.client.post("/v1/memory/add", json=job.payload())
        self.add_seconds.append(time.perf_counter() - started)
        response.raise_for_status()

    async def search(self, case: EvalCase, top_k: int) -> list[dict[str, Any]]:
        started = time.perf_counter()
        response = await self.client.post(
            "/v1/memory/search",
            json={"query": case.question, "user_id": case.user_id, "top_k": top_k},
        )
        self.search_seconds.append(time.perf_counter() - started)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Search response must contain a data array")
        return [item for item in data if isinstance(item, dict)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(value)
    return rows


def evidence_units(values: Any) -> set[str]:
    """Normalize public evidence labels, including semicolon-packed IDs."""

    if not isinstance(values, list):
        values = [values]
    units: set[str] = set()
    for value in values:
        units.update(
            part.strip()
            for part in str(value).split(";")
            if part.strip()
        )
    return units


def read_json_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return value


def timestamp_ms(value: Any, fallback_index: int = 0) -> int:
    """Parse public benchmark timestamps, preserving order on unknown formats."""

    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000

    raw = str(value or "").strip()
    if raw:
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
        formats = (
            "%I:%M %p on %d %B, %Y",
            "%Y/%m/%d (%a) %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d %B %Y",
            "%B %d, %Y",
        )
        if parsed is None:
            for format_string in formats:
                try:
                    parsed = datetime.strptime(raw, format_string)
                    break
                except ValueError:
                    continue
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)

    # Deterministic fallback used only when the public file has an unknown date
    # spelling. It keeps session order but does not pretend to recover the date.
    return 946684800000 + fallback_index * 86_400_000


def chunk_messages(
    messages: list[dict[str, Any]],
    source_units: list[str],
    max_messages: int = MAX_ADD_MESSAGES,
    max_words: int = MAX_ADD_WORDS,
) -> list[tuple[list[dict[str, Any]], list[str]]]:
    """Match the public evaluator's bounded synchronous Add payloads."""

    if len(messages) != len(source_units):
        raise ValueError("messages and source evidence units must align")

    expanded: list[tuple[dict[str, Any], str]] = []
    for message, source_unit in zip(messages, source_units):
        content = str(message.get("content", ""))
        words = content.split()
        if len(words) <= max_words:
            expanded.append((message, source_unit))
            continue

        # Oversized individual messages are split at sentence boundaries when
        # possible, then at a bounded word boundary as a deterministic fallback.
        sentences = re.split(r"(?<=[.!?])\s+", content)
        fragments: list[str] = []
        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            sentence_words = sentence.split()
            while len(sentence_words) > max_words:
                if current:
                    fragments.append(" ".join(current))
                    current = []
                    current_words = 0
                fragments.append(" ".join(sentence_words[:max_words]))
                sentence_words = sentence_words[max_words:]
            if current and current_words + len(sentence_words) > max_words:
                fragments.append(" ".join(current))
                current = []
                current_words = 0
            current.extend(sentence_words)
            current_words += len(sentence_words)
        if current:
            fragments.append(" ".join(current))
        for fragment in fragments:
            split_message = dict(message)
            split_message["content"] = fragment
            expanded.append((split_message, source_unit))

    chunks: list[tuple[list[dict[str, Any]], list[str]]] = []
    chunk_messages_: list[dict[str, Any]] = []
    chunk_units: list[str] = []
    chunk_words = 0
    for message, source_unit in expanded:
        word_count = len(str(message.get("content", "")).split())
        if chunk_messages_ and (
            len(chunk_messages_) >= max_messages or chunk_words + word_count > max_words
        ):
            chunks.append((chunk_messages_, chunk_units))
            chunk_messages_, chunk_units, chunk_words = [], [], 0
        chunk_messages_.append(message)
        chunk_units.append(source_unit)
        chunk_words += word_count
    if chunk_messages_:
        chunks.append((chunk_messages_, chunk_units))
    return chunks


def append_chunked_jobs(
    jobs: list[AddJob],
    evidence: EvidenceIndex,
    *,
    base_request_id: str,
    base_session_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    source_units: list[str],
) -> None:
    chunks = chunk_messages(messages, source_units)
    for chunk_index, (chunk, chunk_units) in enumerate(chunks, start=1):
        if len(chunks) == 1:
            request_id = base_request_id
            session_id = base_session_id
        else:
            request_id = f"{base_request_id}:chunk:{chunk_index}"
            session_id = f"{base_session_id}:chunk:{chunk_index}"
        jobs.append(AddJob(request_id, user_id, session_id, chunk))
        evidence.add_session(request_id, session_id, chunk_units)


def locomo_inputs(
    conversations: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    namespace: str,
    include_multimodal: bool,
    limit: int | None,
) -> tuple[list[EvalCase], list[AddJob], EvidenceIndex]:
    selected_questions = [
        item
        for item in questions
        if include_multimodal or not bool(item.get("is_multi_modality"))
    ]
    if limit is not None:
        selected_questions = selected_questions[:limit]
    selected_samples = {str(item["sample_id"]) for item in selected_questions}
    conversation_map = {str(item["sample_id"]): item for item in conversations}
    missing = selected_samples - set(conversation_map)
    if missing:
        raise ValueError(f"missing LoCoMo conversations: {sorted(missing)[:3]}")

    cases: list[EvalCase] = []
    for item in selected_questions:
        sample_id = str(item["sample_id"])
        cases.append(
            EvalCase(
                ident=str(item["qa_id"]),
                question=str(item["question"]),
                gold_answer=item.get("answer", []),
                gold_evidence=evidence_units(item.get("evidence", [])),
                user_id=f"{namespace}:locomo:{sample_id}",
                category=str(item.get("category", "unknown")),
                speaker_1=str(item.get("speaker_a", "speaker 1")),
                speaker_2=str(item.get("speaker_b", "speaker 2")),
            )
        )

    jobs: list[AddJob] = []
    evidence = EvidenceIndex(session_level=False)
    for sample_id in sorted(selected_samples):
        conversation = conversation_map[sample_id]
        user_id = f"{namespace}:locomo:{sample_id}"
        for fallback_index, session in enumerate(conversation.get("sessions", [])):
            session_index = int(session.get("session_index", fallback_index + 1))
            session_id = f"{namespace}:locomo:{sample_id}:s{session_index}"
            request_id = f"{namespace}:locomo:{sample_id}:add:{session_index}"
            base_timestamp = timestamp_ms(session.get("date_time"), fallback_index)
            source_units: list[str] = []
            messages: list[dict[str, Any]] = []
            for message_index, message in enumerate(session.get("messages", [])):
                source_units.append(str(message["dia_id"]))
                speaker = str(message.get("speaker") or message.get("role") or "unknown")
                content = f"{speaker}: {str(message.get('text', '')).strip()}"
                if include_multimodal and message.get("blip_caption"):
                    content += f"\nImage description: {message['blip_caption']}"
                messages.append(
                    {
                        "role": str(message.get("role") or "user"),
                        "content": content,
                        "timestamp": base_timestamp + message_index,
                    }
                )
            if not messages:
                continue
            append_chunked_jobs(
                jobs,
                evidence,
                base_request_id=request_id,
                base_session_id=session_id,
                user_id=user_id,
                messages=messages,
                source_units=source_units,
            )
    return cases, jobs, evidence


def longmemeval_inputs(
    items: list[dict[str, Any]],
    namespace: str,
    limit: int | None,
) -> tuple[list[EvalCase], list[AddJob], EvidenceIndex]:
    if limit is not None:
        items = items[:limit]
    cases: list[EvalCase] = []
    jobs: list[AddJob] = []
    evidence = EvidenceIndex(session_level=True)
    for item_index, item in enumerate(items):
        ident = str(item["question_id"])
        user_id = f"{namespace}:longmemeval:{ident}"
        answer_sessions = {str(value) for value in item.get("answer_session_ids", [])}
        cases.append(
            EvalCase(
                ident=ident,
                question=str(item["question"]),
                gold_answer=item.get("answer", ""),
                gold_evidence=answer_sessions,
                user_id=user_id,
                category=str(item.get("question_type", "unknown")),
            )
        )
        session_ids = item.get("haystack_session_ids", [])
        dates = item.get("haystack_dates", [])
        sessions = item.get("haystack_sessions", [])
        if not (len(session_ids) == len(dates) == len(sessions)):
            raise ValueError(f"LongMemEval {ident} has misaligned session fields")
        for session_index, (source_session_id, date, turns) in enumerate(
            zip(session_ids, dates, sessions)
        ):
            session_id = f"{namespace}:lme:{ident}:s{session_index}"
            request_id = f"{namespace}:lme:{ident}:add:{session_index}"
            base_timestamp = timestamp_ms(date, item_index * 1000 + session_index)
            messages = [
                {
                    "role": str(turn.get("role") or "user"),
                    "content": str(turn.get("content", "")).strip(),
                    "timestamp": base_timestamp + turn_index,
                }
                for turn_index, turn in enumerate(turns)
                if str(turn.get("content", "")).strip()
            ]
            if not messages:
                continue
            # Session-level evaluation maps every record in a session to the
            # original public session ID.
            append_chunked_jobs(
                jobs,
                evidence,
                base_request_id=request_id,
                base_session_id=session_id,
                user_id=user_id,
                messages=messages,
                source_units=[str(source_session_id)] * len(messages),
            )
    return cases, jobs, evidence


async def map_limited(
    items: Iterable[T],
    concurrency: int,
    worker: Callable[[T], Awaitable[R]],
) -> list[R]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(item: T) -> R:
        async with semaphore:
            return await worker(item)

    return await asyncio.gather(*(run(item) for item in items))


def metrics_for_case(
    ranked_units: list[set[str]],
    gold: set[str],
    ks: Iterable[int],
) -> dict[str, float] | None:
    if not gold:
        return None
    metrics: dict[str, float] = {}
    first_relevant_rank: int | None = None
    for rank, units in enumerate(ranked_units, start=1):
        if units & gold:
            first_relevant_rank = rank
            break
    metrics["mrr"] = 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank

    for k in ks:
        found: set[str] = set()
        gains: list[int] = []
        for units in ranked_units[:k]:
            new_units = (units & gold) - found
            gains.append(1 if new_units else 0)
            found.update(new_units)
        dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
        ideal_count = min(k, len(gold))
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        metrics[f"recall_any@{k}"] = float(bool(found))
        metrics[f"recall_all@{k}"] = float(gold <= found)
        metrics[f"evidence_recall@{k}"] = len(found) / len(gold)
        metrics[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    return metrics


def average_metrics(rows: Iterable[dict[str, float] | None]) -> dict[str, float]:
    values: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row is None:
            continue
        for name, value in row.items():
            values[name].append(value)
    return {name: round(statistics.fmean(items), 6) for name, items in sorted(values.items())}


def timing_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "p50_seconds": 0.0, "p95_seconds": 0.0}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
        return ordered[index]

    return {
        "count": len(values),
        "p50_seconds": round(percentile(0.50), 6),
        "p95_seconds": round(percentile(0.95), 6),
    }


def write_outputs(
    output_dir: Path,
    dataset: str,
    cases: list[EvalCase],
    search_results: list[list[dict[str, Any]]],
    evidence: EvidenceIndex,
    ks: tuple[int, ...],
    api: MemoryAPI,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    context_records: list[dict[str, Any]] = []
    by_category: defaultdict[str, list[dict[str, float] | None]] = defaultdict(list)

    for case, items in zip(cases, search_results):
        ranked_units = [evidence.resolve(item) for item in items]
        metrics = metrics_for_case(ranked_units, case.gold_evidence, ks)
        by_category[case.category].append(metrics)
        records.append(
            {
                "id": case.ident,
                "category": case.category,
                "question": case.question,
                "gold_evidence": sorted(case.gold_evidence),
                "retrieved": [
                    {
                        "rank": rank,
                        "id": item.get("id"),
                        "score": item.get("score"),
                        "evidence_units": sorted(units),
                        "content": item.get("content", ""),
                    }
                    for rank, (item, units) in enumerate(zip(items, ranked_units), start=1)
                ],
                "proxy_metrics": metrics,
            }
        )
        context_records.append(
            {
                "id": case.ident,
                "speaker_1_name": case.speaker_1,
                "speaker_1_memories": [str(item.get("content", "")) for item in items],
                "speaker_2_name": case.speaker_2,
                "speaker_2_memories": [],
                "question": case.question,
                "gold_answer": case.gold_answer,
            }
        )

    with (output_dir / "retrieval.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (output_dir / "answer_input.jsonl").open("w", encoding="utf-8") as handle:
        for record in context_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    valid_count = sum(record["proxy_metrics"] is not None for record in records)
    summary = {
        "score_kind": "proxy_public_retrieval",
        "official_leaderboard_score": None,
        "warning": (
            "Local public-data retrieval proxy only; this is not an official "
            "Agent Memory Challenge score."
        ),
        "dataset": dataset,
        "question_count": len(cases),
        "scored_question_count": valid_count,
        "skipped_without_evidence": len(cases) - valid_count,
        "ks": list(ks),
        "aggregate": average_metrics(record["proxy_metrics"] for record in records),
        "by_category": {
            category: average_metrics(rows) for category, rows in sorted(by_category.items())
        },
        "latency": {
            "add": timing_summary(api.add_seconds),
            "search": timing_summary(api.search_seconds),
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_ks(raw: str, top_k: int) -> tuple[int, ...]:
    values = sorted({int(value.strip()) for value in raw.split(",") if value.strip()})
    if not values or values[0] < 1:
        raise ValueError("--ks must contain positive integers")
    if values[-1] > top_k:
        raise ValueError("every --ks value must be <= --top-k")
    return tuple(values)


async def run(args: argparse.Namespace) -> None:
    ks = parse_ks(args.ks, args.top_k)
    if args.dataset == "locomo":
        cases, jobs, evidence = locomo_inputs(
            read_jsonl(args.conversations),
            read_jsonl(args.questions),
            args.namespace,
            args.include_multimodal,
            args.limit,
        )
        dataset_name = "LoCoMo-Refined-public"
    else:
        cases, jobs, evidence = longmemeval_inputs(
            read_json_array(args.data),
            args.namespace,
            args.limit,
        )
        dataset_name = "LongMemEval-public"

    if not cases:
        raise SystemExit("No evaluation cases matched the selected filters")
    memory_key = os.getenv(args.memory_key_env) if args.memory_key_env else None
    async with MemoryAPI(args.base_url, memory_key, args.timeout_seconds) as api:
        await api.health()
        await map_limited(jobs, args.add_concurrency, api.add)
        search_results = await map_limited(
            cases,
            args.search_concurrency,
            lambda case: api.search(case, args.top_k),
        )
        write_outputs(args.output_dir, dataset_name, cases, search_results, evidence, ks, api)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Run a clearly labelled local retrieval proxy on public benchmark data. "
            "No Agent Memory Challenge key is required."
        )
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default="http://127.0.0.1:8000")
    common.add_argument("--output-dir", type=Path, required=True)
    common.add_argument("--top-k", type=int, default=100)
    common.add_argument("--ks", default=",".join(str(value) for value in DEFAULT_KS))
    common.add_argument("--limit", type=int)
    common.add_argument("--namespace", default="proxy-v1")
    common.add_argument("--add-concurrency", type=int, default=4)
    common.add_argument("--search-concurrency", type=int, default=8)
    common.add_argument("--timeout-seconds", type=float, default=180.0)
    common.add_argument("--memory-key-env", default="TIDE_MEMORY_API_KEY")

    commands = root.add_subparsers(dest="dataset", required=True)
    locomo = commands.add_parser("locomo", parents=[common])
    locomo.add_argument("--conversations", type=Path, required=True)
    locomo.add_argument("--questions", type=Path, required=True)
    locomo.add_argument(
        "--include-multimodal",
        action="store_true",
        help="include caption-backed multimodal questions in the otherwise textual proxy",
    )
    longmem = commands.add_parser("longmemeval", parents=[common])
    longmem.add_argument("--data", type=Path, required=True)
    return root


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
