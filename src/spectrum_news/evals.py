"""Nightly LLM-as-judge evals. Trajectory (deterministic) + final (judge model).

Trajectory checks need no network: required keys, score ranges, and whether
fetched outlets honored the run's allowlist. Final-response scoring asks a
stronger judge model to rate each analysis for plausibility as strict JSON.
"""
from __future__ import annotations

import json

REQUIRED_ANALYSIS_KEYS = ("factuality_score", "bias_label", "bias_score",
                          "summary", "key_claims", "loaded_phrases", "verdict")

JUDGE_PROMPT = """You audit an AI news analysis for plausibility. Score STRICT JSON only:
{{"factuality_plausibility": <0-100>, "bias_plausibility": <0-100>, "rationale": "<1 sentence>"}}
100 = fully plausible given the article text; 0 = contradictory or baseless.

ARTICLE:
Title: {title}
Outlet: {outlet}
Snippet: {snippet}

ANALYSIS UNDER AUDIT:
{analysis}
"""


def trajectory_score(run: dict, evidence: list[dict]) -> dict:
    """0-100 + per-check detail. Pure function (no network)."""
    checks: dict[str, bool] = {}
    if not evidence:
        return {"score": 0.0, "checks": {"has_articles": False}}
    checks["has_articles"] = True
    checks["analyses_have_keys"] = all(
        all(k in (r.get("analysis") or {}) for k in REQUIRED_ANALYSIS_KEYS)
        for r in evidence)
    checks["scores_in_range"] = all(
        0 <= float((r.get("analysis") or {}).get("factuality_score", -1)) <= 100
        and -3 <= float((r.get("analysis") or {}).get("bias_score", 99)) <= 3
        for r in evidence)
    try:
        allowed = set(json.loads(run.get("allowed_domains") or "[]"))
    except Exception:
        allowed = set()
    if allowed:
        from urllib.parse import urlparse

        def _host(u: str) -> str:
            try:
                h = urlparse(u).hostname or ""
                return h[4:] if h.startswith("www.") else h
            except Exception:
                return ""

        checks["domains_honored"] = all(
            any(_host(r.get("article", {}).get("url", "")).endswith(d) for d in allowed)
            for r in evidence)
    else:
        checks["domains_honored"] = True
    passed = sum(1 for v in checks.values() if v)
    return {"score": 100.0 * passed / max(1, len(checks)), "checks": checks}


def judge_final(article: dict, analysis: dict, *, model: str, api_key: str,
                base_url: str, timeout: int = 90) -> dict:
    """Ask the judge model to score one analysis. Returns plausibility dict."""
    import requests

    from . import analyzer as analyzer_mod

    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": JUDGE_PROMPT.format(
                    title=article.get("title", ""), outlet=article.get("outlet", ""),
                    snippet=article.get("snippet", ""),
                    analysis=json.dumps(analysis)[:2000])},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    parsed = analyzer_mod.parse_json_lenient(resp.json()["choices"][0]["message"]["content"])
    if not isinstance(parsed, dict):
        return {"factuality_plausibility": 0, "bias_plausibility": 0,
                "rationale": "judge returned unparseable output"}
    return {
        "factuality_plausibility": float(max(0, min(100, float(parsed.get("factuality_plausibility", 0))))),
        "bias_plausibility": float(max(0, min(100, float(parsed.get("bias_plausibility", 0))))),
        "rationale": str(parsed.get("rationale", ""))[:300],
    }


def evaluate_run(db_url: str, run: dict, *, model: str, api_key: str,
                 base_url: str, judge_llm: bool = True) -> dict:
    """Full evaluation of one run: trajectory always, judge optionally."""
    from . import db as db_mod

    rows = db_mod.fetch_run_evidence(db_url, run["id"])
    evidence = [{
        "article": {"url": r["url"], "outlet": r["outlet"], "title": r["title"],
                    "snippet": r["snippet"], "published": r["published"]},
        "analysis": {"factuality_score": r["factuality_score"], "bias_label": r["bias_label"],
                     "bias_score": r["bias_score"], "summary": r["summary"],
                     "key_claims": r["key_claims"], "loaded_phrases": r["loaded_phrases"],
                     "verdict": r["verdict"]},
    } for r in rows]
    traj = trajectory_score(run, evidence)
    finals = []
    if judge_llm and evidence:
        for r in evidence:
            finals.append(judge_final(r["article"], r["analysis"], model=model,
                                      api_key=api_key, base_url=base_url))
    avg_final = (sum(f["factuality_plausibility"] + f["bias_plausibility"] for f in finals)
                 / max(1, 2 * len(finals))) if finals else None
    return {"run_id": run["id"], "topic": run.get("topic", ""),
            "trajectory": traj, "finals": finals, "avg_final": avg_final}
