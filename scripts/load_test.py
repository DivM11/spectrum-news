"""Concurrency proof: N parallel runs against fakes, JSON report.

No network, no keys: exercises the uncached-run semaphore and the cache
bypass path. Exit 1 when the observed concurrency exceeds the limit or any
run fails — CI-hookable.

Usage:
  uv run python scripts/load_test.py --users 20 --limit 4
  uv run python scripts/load_test.py --users 20 --limit 4 --db postgresql+psycopg://...
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spectrum_news import pipeline  # noqa: E402

_lock = threading.Lock()
_current = 0
_max_seen = 0


def _tracked_sleep(seconds: float) -> None:
    global _current, _max_seen
    with _lock:
        _current += 1
        _max_seen = max(_max_seen, _current)
    try:
        time.sleep(seconds)
    finally:
        with _lock:
            _current -= 1


def fake_search_query(query, spec):
    # Same URL for every query variant -> dedupe yields exactly one article
    # per run, so analyze entries == concurrent gated runs.
    time.sleep(0.2)
    return [{"url": "https://x.com/load", "outlet": "x.com",
             "title": query, "snippet": "s", "content": "s", "published": ""}]


def fake_analyze(article, model, key="", temperature=0.2):
    _tracked_sleep(0.2)
    return {"factuality_score": 60, "bias_label": "Center", "bias_score": 0.0,
            "summary": "s", "key_claims": [], "loaded_phrases": [],
            "verdict": "mixed"}


def one_run(i: int, db_url: str, limit: int) -> float:
    start = time.monotonic()
    out = pipeline.run_search(f"load topic {i}", "Tech", "", model="m",
                              search_model="m", db_url=db_url,
                              max_concurrent_uncached_runs=limit,
                              search_query_fn=fake_search_query,
                              analyze_fn=fake_analyze)
    assert out["results"], f"run {i} produced nothing"
    return (time.monotonic() - start) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--db", default="")
    args = parser.parse_args()

    tmp = None
    db_url = args.db
    if not db_url:
        tmp = tempfile.TemporaryDirectory()
        db_url = os.path.join(tmp.name, "load.db")
    try:
        with ThreadPoolExecutor(max_workers=args.users) as pool:
            durations = list(pool.map(lambda i: one_run(i, db_url, args.limit),
                                      range(args.users)))
    finally:
        if tmp is not None:
            tmp.cleanup()
    report = {
        "users": args.users,
        "limit": args.limit,
        "runs_ok": len(durations),
        "p95_ms": round(statistics.quantiles(durations, n=100)[94], 1),
        "max_concurrent_observed": _max_seen,
    }
    print(json.dumps(report, indent=2))
    if _max_seen > args.limit:
        print(f"FAIL: concurrency {_max_seen} exceeded limit {args.limit}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
