"""Measure database-backed limiter latency under concurrent writes.

Run only against a disposable/staging database with the Phase 2 migrations applied:
    DATABASE_URL=postgresql+psycopg://... python -m scripts.benchmark_rate_limit
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import statistics
from time import perf_counter
import uuid

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.rate_limit import POLICIES, consume_rate_limit


def main() -> None:
    parser = argparse.ArgumentParser(description="Rate-limit database contention benchmark")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--limit", type=int, default=1_000_000)
    parser.add_argument("--window-seconds", type=int, default=3600)
    args = parser.parse_args()
    if min(args.requests, args.workers, args.limit, args.window_seconds) < 1:
        parser.error("all numeric arguments must be positive")

    POLICIES["read"] = (args.limit, args.window_seconds)
    identity = f"benchmark:{uuid.uuid4()}"
    latencies: list[float] = []

    def hit(_: int) -> bool:
        started = perf_counter()
        with SessionLocal() as db:
            allowed, _ = consume_rate_limit(db, "read", identity)
        latencies.append(perf_counter() - started)
        return allowed

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        allowed = sum(pool.map(hit, range(args.requests)))
    elapsed = perf_counter() - started
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print(f"Requests: {args.requests}; workers: {args.workers}; allowed: {allowed}")
    print(f"Elapsed: {elapsed:.3f}s; throughput: {args.requests / elapsed:.1f} req/s")
    print(
        "Latency: "
        f"median={statistics.median(ordered) * 1000:.1f}ms; "
        f"p95={p95 * 1000:.1f}ms; max={max(ordered) * 1000:.1f}ms"
    )


if __name__ == "__main__":
    main()
