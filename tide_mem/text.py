from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable

_TOKEN_RE = re.compile(r"[\w][\w'’-]*", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|[A-Z]{2,}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_from_ms(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def stable_id(*parts: object, prefix: str = "mem") -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def truncate(value: str, max_chars: int) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(value)]


def unique_preserve(values: Iterable[str], *, casefold: bool = True) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_space(str(value))
        if not cleaned:
            continue
        key = cleaned.casefold() if casefold else cleaned
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def fts_query(value: str, max_terms: int = 24) -> str:
    # FTS5's unicode tokenizer has no English stemming. Add a deliberately
    # small set of morphology variants so natural query wording such as
    # ``play``/``playing`` and ``move``/``moved`` reaches the same evidence.
    # Prefix matches retain exact entity spellings while covering suffixes.
    expanded: list[str] = []
    for term in unique_preserve(tokenize(value)):
        expanded.append(term)
        if len(term) >= 5 and term.endswith("ies"):
            expanded.append(f"{term[:-3]}y")
        elif len(term) >= 5 and term.endswith("ing"):
            root = term[:-3]
            expanded.extend([root, f"{root}e"])
            if len(root) >= 3 and root[-1] == root[-2]:
                expanded.append(root[:-1])
        elif len(term) >= 4 and term.endswith("ed"):
            root = term[:-2]
            expanded.extend([root, term[:-1]])
            if len(root) >= 3 and root[-1] == root[-2]:
                expanded.append(root[:-1])
        elif len(term) >= 5 and term.endswith("es"):
            expanded.extend([term[:-2], term[:-1]])
        elif len(term) >= 5 and term.endswith("s"):
            expanded.append(term[:-1])

    terms = unique_preserve(expanded)[:max_terms]
    safe = [term.replace('"', '""') for term in terms if len(term) > 1 or term.isdigit()]
    return " OR ".join(f'"{term}"*' if len(term) >= 3 else f'"{term}"' for term in safe)


def split_sentences(value: str, max_sentences: int = 24) -> list[str]:
    pieces = [normalize_space(piece) for piece in _SENTENCE_RE.split(value)]
    return [piece for piece in pieces if piece][:max_sentences]


def heuristic_entities(value: str, max_entities: int = 16) -> list[str]:
    return unique_preserve(_ENTITY_RE.findall(value))[:max_entities]


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def jaccard(a: str, b: str) -> float:
    left, right = set(tokenize(a)), set(tokenize(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
