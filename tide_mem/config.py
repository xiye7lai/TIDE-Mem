from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    value = int(raw) if raw is not None else default
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    version: str
    db_path: Path
    memory_api_key: str
    require_auth: bool
    llm_mode: str
    llm_api_base: str
    llm_api_key: str
    llm_model: str
    enforce_gpt4o_mini: bool
    llm_required: bool
    llm_timeout_seconds: int
    llm_max_concurrency: int
    llm_max_retries: int
    max_cards_per_add: int
    max_summary_cards_per_add: int
    retrieval_candidate_limit: int
    rerank_candidate_limit: int
    memory_view: str
    temporal_boost: bool
    returned_content_max_chars: int
    ttl_days: int
    ttl_cleanup_interval_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        model = os.getenv("TIDE_LLM_MODEL", "gpt-4o-mini").strip()
        enforce = _bool("TIDE_ENFORCE_GPT4O_MINI", True)
        if enforce and model != "gpt-4o-mini":
            raise ValueError(
                "Agent Memory Challenge 2026 requires gpt-4o-mini for Add/Search; "
                "set TIDE_LLM_MODEL=gpt-4o-mini."
            )

        mode = os.getenv("TIDE_LLM_MODE", "api").strip().lower()
        if mode not in {"api", "heuristic"}:
            raise ValueError("TIDE_LLM_MODE must be 'api' or 'heuristic'")

        memory_view = os.getenv("TIDE_MEMORY_VIEW", "full").strip().lower()
        if memory_view not in {"full", "raw", "cards"}:
            raise ValueError("TIDE_MEMORY_VIEW must be 'full', 'raw', or 'cards'")

        db_path = Path(os.getenv("TIDE_DB_PATH", "/data/tide_mem.sqlite3"))
        return cls(
            app_name="TIDE-Mem",
            version="0.1.0-amc2026",
            db_path=db_path,
            memory_api_key=os.getenv("TIDE_MEMORY_API_KEY", ""),
            # The Academic code-submission platform starts this container behind
            # its own evaluator boundary and does not issue a Memory System Key.
            # Standalone operators can still opt into X-Api-Key authentication.
            require_auth=_bool("TIDE_REQUIRE_AUTH", False),
            llm_mode=mode,
            llm_api_base=os.getenv("TIDE_LLM_API_BASE", "https://api.openai.com/v1").rstrip("/"),
            llm_api_key=os.getenv("TIDE_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            llm_model=model,
            enforce_gpt4o_mini=enforce,
            llm_required=_bool("TIDE_LLM_REQUIRED", True),
            llm_timeout_seconds=_int("TIDE_LLM_TIMEOUT_SECONDS", 120, 10),
            llm_max_concurrency=_int("TIDE_LLM_MAX_CONCURRENCY", 16, 1),
            llm_max_retries=_int("TIDE_LLM_MAX_RETRIES", 5, 0),
            max_cards_per_add=_int("TIDE_MAX_CARDS_PER_ADD", 24, 1),
            max_summary_cards_per_add=_int("TIDE_MAX_SUMMARY_CARDS_PER_ADD", 4, 0),
            retrieval_candidate_limit=_int("TIDE_RETRIEVAL_CANDIDATE_LIMIT", 220, 20),
            rerank_candidate_limit=_int("TIDE_RERANK_CANDIDATE_LIMIT", 80, 0),
            memory_view=memory_view,
            temporal_boost=_bool("TIDE_TEMPORAL_BOOST", True),
            returned_content_max_chars=_int("TIDE_RETURNED_CONTENT_MAX_CHARS", 1800, 256),
            ttl_days=_int("TIDE_TTL_DAYS", 30, 1),
            ttl_cleanup_interval_seconds=_int("TIDE_TTL_CLEANUP_INTERVAL_SECONDS", 21600, 300),
            log_level=os.getenv("TIDE_LOG_LEVEL", "INFO").upper(),
        )

    def ensure_runtime_ready(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.require_auth and not self.memory_api_key:
            raise RuntimeError("TIDE_MEMORY_API_KEY is required when TIDE_REQUIRE_AUTH=true")
        if self.llm_mode == "api" and self.llm_required and not self.llm_api_key:
            raise RuntimeError("TIDE_LLM_API_KEY (or OPENAI_API_KEY) is required in API mode")
