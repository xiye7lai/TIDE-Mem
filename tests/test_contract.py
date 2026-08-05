from __future__ import annotations


def _payload(request_id: str, user_id: str = "user-a", session_id: str = "session-1") -> dict:
    return {
        "request_id": request_id,
        "user_id": user_id,
        "session_id": session_id,
        "messages": [
            {
                "role": "user",
                "timestamp": 1767225600000,
                "content": "My name is Ada Lovelace and I prefer analytical engines.",
            },
            {
                "role": "assistant",
                "timestamp": 1767225660000,
                "content": "I will remember your preference for analytical engines.",
            },
        ],
    }


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_is_required(client):
    response = client.post("/v1/memory/add", json=_payload("req-auth"))
    assert response.status_code == 401
    assert "reason" in response.json()["detail"]


def test_add_contract_and_search_contract(client, auth_headers):
    payload = _payload("req-1")
    response = client.post("/v1/memory/add", json=payload, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "request_id": "req-1",
        "user_id": "user-a",
        "session_id": "session-1",
    }

    search = client.post(
        "/v1/memory/search",
        json={
            "query": "What kind of engine does Ada prefer?",
            "options": ["steam engine", "analytical engine"],
            "user_id": "user-a",
            "top_k": 10,
        },
        headers=auth_headers,
    )
    assert search.status_code == 200
    body = search.json()
    assert isinstance(body["data"], list)
    assert 1 <= len(body["data"]) <= 10
    assert all({"id", "content"}.issubset(item) for item in body["data"])
    assert "analytical" in " ".join(item["content"] for item in body["data"]).lower()


def test_validation_is_strict(client, auth_headers):
    response = client.post(
        "/v1/memory/add",
        json={"request_id": "x", "messages": [], "user_id": "u", "session_id": "s"},
        headers=auth_headers,
    )
    assert response.status_code == 422

    response = client.post(
        "/v1/memory/search",
        json={"query": "q", "user_id": "u", "top_k": 0},
        headers=auth_headers,
    )
    assert response.status_code == 422
