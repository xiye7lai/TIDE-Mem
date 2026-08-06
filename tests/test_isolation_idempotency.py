from __future__ import annotations

import asyncio

from tide_mem.db import MemoryDB


def _add(client, headers, request_id: str, user_id: str, fact: str):
    return client.post(
        "/v1/memory/add",
        json={
            "request_id": request_id,
            "user_id": user_id,
            "session_id": f"session-{user_id}",
            "messages": [{"role": "user", "content": fact, "timestamp": 1767225600000}],
        },
        headers=headers,
    )


def _search(client, headers, user_id: str, query: str, top_k: int = 100):
    return client.post(
        "/v1/memory/search",
        json={"query": query, "user_id": user_id, "top_k": top_k},
        headers=headers,
    )


def test_user_id_is_a_hard_boundary(client, auth_headers):
    assert _add(client, auth_headers, "req-alice", "alice", "My secret codename is ORCHID-771.").status_code == 200
    assert _add(client, auth_headers, "req-bob", "bob", "My favorite color is blue.").status_code == 200

    alice = _search(client, auth_headers, "alice", "What is my secret codename?").json()["data"]
    bob = _search(client, auth_headers, "bob", "What is Alice's secret codename?").json()["data"]
    assert any("ORCHID-771" in item["content"] for item in alice)
    assert all("ORCHID-771" not in item["content"] for item in bob)


def test_add_is_idempotent_under_retry(client, auth_headers):
    payload = {
        "request_id": "retry-1",
        "user_id": "retry-user",
        "session_id": "retry-session",
        "messages": [{"role": "user", "content": "The launch code word is CERULEAN."}],
    }
    first = client.post("/v1/memory/add", json=payload, headers=auth_headers)
    second = client.post("/v1/memory/add", json=payload, headers=auth_headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    results = _search(client, auth_headers, "retry-user", "CERULEAN").json()["data"]
    ids = [item["id"] for item in results]
    assert len(ids) == len(set(ids))
    # One raw record, one heuristic card, and one session summary at most.
    assert len(results) <= 3


def test_top_k_is_obeyed(client, auth_headers):
    for index in range(4):
        assert _add(
            client,
            auth_headers,
            f"req-top-{index}",
            "top-user",
            f"Project Atlas milestone number {index} is documented.",
        ).status_code == 200
    results = _search(client, auth_headers, "top-user", "Project Atlas milestones", top_k=2).json()["data"]
    assert len(results) == 2


def test_request_id_cannot_cross_identity_boundary(client, auth_headers):
    payload = {
        "request_id": "shared-id",
        "user_id": "first-user",
        "session_id": "first-session",
        "messages": [{"role": "user", "content": "First user's evidence."}],
    }
    assert client.post("/v1/memory/add", json=payload, headers=auth_headers).status_code == 200
    payload["user_id"] = "second-user"
    payload["session_id"] = "second-session"
    response = client.post("/v1/memory/add", json=payload, headers=auth_headers)
    assert response.status_code == 400
    assert "different user_id/session_id" in response.json()["detail"]["reason"]


def test_session_expansion_keeps_user_boundary(client, auth_headers, settings):
    assert _add(client, auth_headers, "expand-a", "alice", "Alice keeps ORCHID evidence.").status_code == 200
    assert _add(client, auth_headers, "expand-b", "bob", "Bob keeps CERULEAN evidence.").status_code == 200

    db = MemoryDB(settings.db_path)
    rows = asyncio.run(db.session_memories("alice", ["session-alice", "session-bob"]))

    assert rows
    assert all(row["user_id"] == "alice" for row in rows)
    assert all("CERULEAN" not in row["content"] for row in rows)
