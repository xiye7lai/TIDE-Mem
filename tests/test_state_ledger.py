from __future__ import annotations

from dataclasses import asdict


def test_newer_state_is_marked_current(client, auth_headers):
    llm = client.app.state.llm
    observed_hints = []

    async def extract(messages, session_id, state_hints=None):
        observed_hints.append(state_hints or [])
        text = messages[0].content
        is_new = "Berlin" in text
        return {
            "memory_cards": [
                {
                    "kind": "state_update",
                    "content": text,
                    "entities": ["Berlin" if is_new else "Paris"],
                    "keywords": ["home", "city"],
                    "event_time": "2026-02-01T00:00:00Z" if is_new else "2025-01-01T00:00:00Z",
                    "state_key": "profile.home_city",
                    "change_type": "set",
                    "source_message_indexes": [0],
                    "confidence": 1.0,
                }
            ],
            "session_summary": [],
        }

    async def plan(query, options):
        from tide_mem.llm import QueryPlan

        return QueryPlan(
            question_type="update",
            subqueries=[query, "home city Paris Berlin"],
            entities=["Paris", "Berlin"],
            time_terms=[],
            coverage_slots=["current home city"],
            prefer_latest=True,
            needs_multiple_evidence=False,
        )

    llm.extract_memories = extract
    llm.plan_query = plan

    for request_id, text in [
        ("old-home", "I live in Paris."),
        ("new-home", "I moved to Berlin."),
    ]:
        response = client.post(
            "/v1/memory/add",
            json={
                "request_id": request_id,
                "user_id": "temporal-user",
                "session_id": request_id,
                "messages": [{"role": "user", "content": text}],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200

    assert observed_hints[0] == []
    assert any(
        item.get("state_key") == "profile.home_city"
        for item in observed_hints[1]
    )

    results = client.post(
        "/v1/memory/search",
        json={
            "query": "Where do I currently live?",
            "user_id": "temporal-user",
            "top_k": 10,
        },
        headers=auth_headers,
    ).json()["data"]
    assert results
    berlin_position = next(i for i, item in enumerate(results) if "Berlin" in item["content"])
    paris_position = next(i for i, item in enumerate(results) if "Paris" in item["content"])
    assert berlin_position < paris_position
