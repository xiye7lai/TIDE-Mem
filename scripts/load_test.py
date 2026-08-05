from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class Result:
    ok: bool
    latency: float
    status: int


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


async def run_phase(name: str, coroutines: list, concurrency: int) -> tuple[list[Result], float]:
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(coro):
        async with semaphore:
            return await coro

    started = time.perf_counter()
    results = await asyncio.gather(*(guarded(coro) for coro in coroutines))
    return results, time.perf_counter() - started


async def main_async(args) -> int:
    base = args.base_url.rstrip("/")
    headers = {"X-Api-Key": args.memory_key, "Content-Type": "application/json"}
    nonce = secrets.token_hex(6)
    users = [f"load:user:{nonce}:{i}" for i in range(args.records)]

    limits = httpx.Limits(max_connections=max(args.add_concurrency, args.search_concurrency) * 2)
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        async def add_one(i: int, user_id: str) -> Result:
            payload = {
                "request_id": f"load:add:{nonce}:{i}",
                "user_id": user_id,
                "session_id": f"load:session:{nonce}:{i}",
                "messages": [
                    {
                        "role": "user",
                        "timestamp": 1767225600000 + i,
                        "content": f"Synthetic load fact {i}: constellation token LOAD-{nonce}-{i}.",
                    }
                ],
            }
            start = time.perf_counter()
            try:
                response = await client.post(f"{base}/v1/memory/add", headers=headers, json=payload)
                ok = response.status_code == 200 and response.json().get("success") is True
                return Result(ok, time.perf_counter() - start, response.status_code)
            except httpx.HTTPError:
                return Result(False, time.perf_counter() - start, 0)

        add_results, add_elapsed = await run_phase(
            "add",
            [add_one(i, user_id) for i, user_id in enumerate(users)],
            args.add_concurrency,
        )

        async def search_one(i: int, user_id: str) -> Result:
            payload = {
                "query": f"What is synthetic load fact {i}?",
                "user_id": user_id,
                "top_k": 10,
            }
            start = time.perf_counter()
            try:
                response = await client.post(f"{base}/v1/memory/search", headers=headers, json=payload)
                body = response.json() if response.content else {}
                ok = response.status_code == 200 and isinstance(body.get("data"), list)
                return Result(ok, time.perf_counter() - start, response.status_code)
            except (httpx.HTTPError, ValueError):
                return Result(False, time.perf_counter() - start, 0)

        search_results, search_elapsed = await run_phase(
            "search",
            [search_one(i, user_id) for i, user_id in enumerate(users)],
            args.search_concurrency,
        )

    def summary(results: list[Result], elapsed: float) -> dict:
        latencies = [result.latency for result in results]
        return {
            "requests": len(results),
            "successes": sum(result.ok for result in results),
            "wall_seconds": round(elapsed, 3),
            "throughput_rps": round(len(results) / elapsed, 3) if elapsed else 0,
            "latency_p50_seconds": round(statistics.median(latencies), 3) if latencies else 0,
            "latency_p95_seconds": round(percentile(latencies, 0.95), 3),
            "latency_max_seconds": round(max(latencies), 3) if latencies else 0,
            "status_counts": {
                str(code): sum(result.status == code for result in results)
                for code in sorted({result.status for result in results})
            },
        }

    report = {
        "warning": "Synthetic transport/database test. API-mode results depend on provider quota and latency.",
        "base_url": base,
        "add_concurrency": args.add_concurrency,
        "search_concurrency": args.search_concurrency,
        "add": summary(add_results, add_elapsed),
        "search": summary(search_results, search_elapsed),
    }
    print(json.dumps(report, indent=2))
    return 0 if all(result.ok for result in [*add_results, *search_results]) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic concurrent load test")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--memory-key", default=os.getenv("TIDE_MEMORY_API_KEY", ""))
    parser.add_argument("--records", type=int, default=64)
    parser.add_argument("--add-concurrency", type=int, default=16)
    parser.add_argument("--search-concurrency", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=1200.0)
    args = parser.parse_args()
    if not args.memory_key:
        parser.error("provide --memory-key or set TIDE_MEMORY_API_KEY")
    if args.records < 1 or args.add_concurrency < 1 or args.search_concurrency < 1:
        parser.error("records and concurrency values must be positive")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
