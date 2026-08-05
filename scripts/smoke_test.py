from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from typing import Any

import httpx


def _headers(key: str, mode: str) -> dict[str, str]:
    if mode == "x-api-key":
        return {"X-Api-Key": key, "Content-Type": "application/json"}
    if mode == "bearer":
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return {"Authorization": f"Token {key}", "Content-Type": "application/json"}


def _expect(response: httpx.Response, status: int, label: str) -> dict[str, Any] | None:
    if response.status_code != status:
        body = response.text[:500]
        raise AssertionError(f"{label}: expected HTTP {status}, got {response.status_code}: {body}")
    if not response.content:
        return None
    try:
        value = response.json()
    except ValueError as exc:
        raise AssertionError(f"{label}: response is not JSON") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{label}: expected a top-level JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="External contract/isolation smoke test for TIDE-Mem")
    parser.add_argument("--base-url", required=True, help="Public API origin, without a trailing slash")
    parser.add_argument(
        "--memory-key",
        default=os.getenv("TIDE_MEMORY_API_KEY", ""),
        help="Private Memory System Key; defaults to TIDE_MEMORY_API_KEY",
    )
    parser.add_argument(
        "--auth-mode",
        choices=["x-api-key", "bearer", "token"],
        default="x-api-key",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    if not args.memory_key:
        parser.error("provide --memory-key or set TIDE_MEMORY_API_KEY")

    base_url = args.base_url.rstrip("/")
    headers = _headers(args.memory_key, args.auth_mode)
    nonce = secrets.token_hex(8)
    canary = f"TIDE-CANARY-{nonce.upper()}"
    user_a = f"smoke:user:a:{nonce}"
    user_b = f"smoke:user:b:{nonce}"
    request_id = f"smoke:add:{nonce}"
    session_id = f"smoke:session:{nonce}"

    started = time.perf_counter()
    with httpx.Client(timeout=args.timeout, follow_redirects=False) as client:
        health = _expect(client.get(f"{base_url}/health"), 200, "health")
        if health is None or health.get("status") != "ok":
            raise AssertionError("health: expected status=ok")

        unauth_payload = {
            "request_id": f"smoke:unauth:{nonce}",
            "messages": [{"role": "user", "content": "unauthorized probe"}],
            "user_id": user_a,
            "session_id": session_id,
        }
        unauth = client.post(f"{base_url}/v1/memory/add", json=unauth_payload)
        if unauth.status_code != 401:
            raise AssertionError(f"auth: expected unauthenticated Add HTTP 401, got {unauth.status_code}")

        add_payload = {
            "request_id": request_id,
            "messages": [
                {
                    "role": "user",
                    "timestamp": 1767225600000,
                    "content": f"My private project codename is {canary}. I moved to Berlin in 2026.",
                },
                {
                    "role": "assistant",
                    "timestamp": 1767225660000,
                    "content": "Acknowledged. This is source conversation evidence, not a final answer.",
                },
            ],
            "user_id": user_a,
            "session_id": session_id,
        }
        add = _expect(
            client.post(f"{base_url}/v1/memory/add", headers=headers, json=add_payload),
            200,
            "add",
        )
        expected_add = {
            "success": True,
            "request_id": request_id,
            "user_id": user_a,
            "session_id": session_id,
        }
        if add != expected_add:
            raise AssertionError(f"add: response mismatch: {add!r}")

        replay = _expect(
            client.post(f"{base_url}/v1/memory/add", headers=headers, json=add_payload),
            200,
            "idempotent replay",
        )
        if replay != expected_add:
            raise AssertionError("idempotent replay: response differs from initial Add")

        search_payload = {
            "query": "What is the user's private project codename?",
            "options": ["an unrelated value", canary],
            "user_id": user_a,
            "top_k": 2,
        }
        search = _expect(
            client.post(f"{base_url}/v1/memory/search", headers=headers, json=search_payload),
            200,
            "search",
        )
        data = search.get("data") if search else None
        if not isinstance(data, list):
            raise AssertionError("search: missing data array")
        if not (1 <= len(data) <= 2):
            raise AssertionError(f"search: expected 1..2 records, got {len(data)}")
        ids: list[str] = []
        joined: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                raise AssertionError("search: data item is not an object")
            ident, content = item.get("id"), item.get("content")
            if not isinstance(ident, str) or not ident:
                raise AssertionError("search: item has no non-empty id")
            if not isinstance(content, str) or not content:
                raise AssertionError("search: item has no non-empty content")
            ids.append(ident)
            joined.append(content)
        if len(ids) != len(set(ids)):
            raise AssertionError("search: duplicate result IDs")
        if canary not in "\n".join(joined):
            raise AssertionError("search: newly added canary is not immediately retrievable")

        isolation = _expect(
            client.post(
                f"{base_url}/v1/memory/search",
                headers=headers,
                json={
                    "query": f"Retrieve {canary}",
                    "user_id": user_b,
                    "top_k": 100,
                },
            ),
            200,
            "user isolation",
        )
        isolated_data = isolation.get("data") if isolation else None
        if not isinstance(isolated_data, list):
            raise AssertionError("user isolation: missing data array")
        if any(canary in str(item.get("content", "")) for item in isolated_data if isinstance(item, dict)):
            raise AssertionError("user isolation: canary leaked across user_id")

    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "status": "PASS",
                "base_url": base_url,
                "checks": [
                    "public health",
                    "private Add/Search auth",
                    "exact synchronous Add response",
                    "immediate retrieval",
                    "top_k",
                    "stable IDs",
                    "idempotent Add replay",
                    "user_id isolation",
                ],
                "elapsed_seconds": round(elapsed, 3),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, httpx.HTTPError) as exc:
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
