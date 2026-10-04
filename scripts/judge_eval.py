"""Nightly judge job: sample recent runs, score trajectory + final response.

Writes a JSON report (stdout or --out). Exits 1 when avg final score drops
below --min-score, so cron/CI can alert on it.

Usage:
  uv run python scripts/judge_eval.py --db "$DATABASE_URL" --sample 10
  uv run python scripts/judge_eval.py --no-llm          # trajectory only, offline
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spectrum_news import db as db_mod  # noqa: E402
from spectrum_news import evals as evals_mod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("DATABASE_URL", "data/spectrum.db"))
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "google/gemini-2.5-flash"))
    parser.add_argument("--min-score", type=float, default=60.0)
    parser.add_argument("--no-llm", action="store_true", help="trajectory checks only")
    parser.add_argument("--out", default="", help="report path (default: stdout)")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not args.no_llm and not api_key:
        print("OPENROUTER_API_KEY missing; rerun with --no-llm for trajectory-only mode.",
              file=sys.stderr)
        return 2

    runs = db_mod.list_runs(args.db, limit=args.sample)
    report = {"runs": [], "avg_trajectory": None, "avg_final": None}
    for run in runs:
        report["runs"].append(evals_mod.evaluate_run(
            args.db, run, model=args.judge_model, api_key=api_key,
            base_url=base_url, judge_llm=not args.no_llm))
    if report["runs"]:
        report["avg_trajectory"] = sum(r["trajectory"]["score"] for r in report["runs"]) / len(report["runs"])
        finals = [r["avg_final"] for r in report["runs"] if r["avg_final"] is not None]
        report["avg_final"] = sum(finals) / len(finals) if finals else None

    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)

    if report["avg_final"] is not None and report["avg_final"] < args.min_score:
        print(f"ALERT: avg final {report['avg_final']:.1f} < --min-score {args.min_score}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
