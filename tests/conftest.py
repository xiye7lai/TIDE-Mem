from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tide_mem.api import create_app
from tide_mem.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    base = Settings.from_env()
    return replace(
        base,
        db_path=tmp_path / "test.sqlite3",
        memory_api_key="test-memory-key",
        require_auth=True,
        llm_mode="heuristic",
        llm_required=False,
        llm_max_retries=0,
        ttl_cleanup_interval_seconds=3600,
        retrieval_candidate_limit=100,
        rerank_candidate_limit=0,
    )


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"X-Api-Key": "test-memory-key"}
