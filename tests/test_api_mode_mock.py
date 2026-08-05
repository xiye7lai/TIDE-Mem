from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from tide_mem.api import create_app
from tide_mem.config import Settings


def test_full_api_mode_chain_with_mocked_gpt4o_mini(tmp_path):
    settings = replace(
        Settings.from_env(),
        db_path=tmp_path / "api-mode.sqlite3",
        memory_api_key="memory-key",
        require_auth=True,
        llm_mode="api",
        llm_api_key="mock-provider-key",
        llm_required=True,
        llm_max_retries=0,
        rerank_candidate_limit=20,
    )
    app = create_app(settings)
    asyncio.run(app.state.llm._client.aclose())

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        user = payload["messages"][1]["content"]
        assert payload["model"] == "gpt-4o-mini"
        assert payload["temperature"] == 0
        if "memory-writing component" in system:
            body = {
                "memory_cards": [
                    {
                        "kind": "state_update",
                        "content": "The user moved from Paris to Berlin in February 2026.",
                        "entities": ["Paris", "Berlin"],
                        "keywords": ["moved", "home city"],
                        "event_time": "2026-02-01T00:00:00Z",
                        "state_key": "profile.home_city",
                        "change_type": "set",
                        "source_message_indexes": [0],
                        "confidence": 1.0,
                    }
                ],
                "session_summary": [],
            }
        elif "evidence-retrieval planner" in system:
            body = {
                "question_type": "update",
                "subqueries": ["current home city", "moved Berlin Paris"],
                "entities": ["Berlin", "Paris"],
                "time_terms": ["February 2026"],
                "coverage_slots": ["latest residence"],
                "prefer_latest": True,
                "needs_multiple_evidence": False,
            }
        elif "rank memory evidence" in system:
            match = re.search(r"Candidates: (\[.*\])\n\nReturn JSON:", user, re.S)
            assert match is not None
            candidates = json.loads(match.group(1))
            body = {
                "ranked": [
                    {"id": candidate["id"], "score": max(0.1, 1.0 - index * 0.1)}
                    for index, candidate in enumerate(candidates)
                ]
            }
        else:
            raise AssertionError(f"unexpected prompt: {system[:80]}")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(body)}}]},
        )

    app.state.llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        headers = {"X-Api-Key": "memory-key"}
        add = client.post(
            "/v1/memory/add",
            headers=headers,
            json={
                "request_id": "api-mode-add",
                "user_id": "api-user",
                "session_id": "api-session",
                "messages": [
                    {
                        "role": "user",
                        "content": "I moved from Paris to Berlin in February 2026.",
                        "timestamp": 1770000000000,
                    }
                ],
            },
        )
        assert add.status_code == 200
        search = client.post(
            "/v1/memory/search",
            headers=headers,
            json={
                "query": "Where does the user currently live?",
                "user_id": "api-user",
                "top_k": 10,
            },
        )
        assert search.status_code == 200
        data = search.json()["data"]
        assert data
        assert "Berlin" in data[0]["content"]
