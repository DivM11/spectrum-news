"""OpenRouter analyzer: factuality + bias + summary as strict JSON. Heuristic fallback."""
from __future__ import annotations

import json
import re

PROMPT = """You are a news fact-checking and bias-analysis assistant. Analyze the ARTICLE below.

Return STRICT JSON only (no markdown fences, no commentary) with exactly these keys:
{{
  "factuality_score": <0-100 number, how well verifiable claims hold up>,
  "bias_label": "<Far-Left|Left|Lean-Left|Center|Lean-Right|Right|Far-Right>",
  "bias_score": <-3..+3 number, negative=left, positive=right>,
  "summary": "<2-3 sentence neutral summary>",
  "key_claims": ["<claim 1>", "<claim 2>"],
  "loaded_phrases": ["<phrase with framing, if any>"],
  "verdict": "<1 sentence: supported / mixed / contested / unverifiable>"
}}

Be cautious: thin snippets -> lower factuality, verdict 'unverifiable'. Distinguish outlet reputation from this article's framing.

ARTICLE:
Title: {title}
Outlet: {outlet}
URL: {url}
Content:
{text}
"""


def heuristic_analysis(article: dict) -> dict:
    text = f"{article.get('title', '')} {article.get('snippet', '')} {article.get('content', '')}"
    lowered = text.lower()
    left_hits = sum(w in lowered for w in ("progressive", "justice", "equity", "climate crisis", "far-right"))
    right_hits = sum(w in lowered for w in ("freedom", "patriot", "woke", "socialist", "far-left"))
    score = max(-3, min(3, right_hits - left_hits))
    label = { -3: "Far-Left", -2: "Left", -1: "Lean-Left", 0: "Center",
              1: "Lean-Right", 2: "Right", 3: "Far-Right" }[score]
    thin = len(text.split()) < 40
    return {
        "factuality_score": 45 if thin else 60,
        "bias_label": label,
        "bias_score": float(score),
        "summary": (article.get("snippet", "") or article.get("title", ""))[:400],
        "key_claims": [article.get("title", "")] if article.get("title") else [],
        "loaded_phrases": [],
        "verdict": "unverifiable — thin snippet, open the source" if thin else "mixed — verify against additional outlets",
    }


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()


def parse_json_lenient(s: str) -> dict | None:
    try:
        return json.loads(_strip_fences(s))
    except Exception:
        pass
    m = re.search(r"\{.*\}", _strip_fences(s), flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def sanitize(parsed: dict | None, article: dict) -> dict:
    base = heuristic_analysis(article)
    if not isinstance(parsed, dict):
        return base
    try:
        out = dict(base)
        out["factuality_score"] = float(max(0, min(100, float(parsed.get("factuality_score", base["factuality_score"])))))
        out["bias_score"] = float(max(-3, min(3, float(parsed.get("bias_score", base["bias_score"])))))
        out["bias_label"] = str(parsed.get("bias_label", base["bias_label"]))
        out["summary"] = str(parsed.get("summary", base["summary"]))[:1200]
        out["key_claims"] = list(parsed.get("key_claims", base["key_claims"]))[:8]
        out["loaded_phrases"] = list(parsed.get("loaded_phrases", base["loaded_phrases"]))[:8]
        out["verdict"] = str(parsed.get("verdict", base["verdict"]))[:500]
        return out
    except Exception:
        return base


def analyze_article(article: dict, model: str, api_key: str = "",
                    base_url: str = "https://openrouter.ai/api/v1",
                    temperature: float = 0.2, timeout: int = 60) -> dict:
    if not api_key:
        out = heuristic_analysis(article)
        out["verdict"] += " (heuristic: set OPENROUTER_API_KEY for LLM analysis)"
        return out
    import requests

    text = (article.get("content") or article.get("snippet") or "")[:4000]
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model or "openai/gpt-4o-mini",
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": PROMPT.format(
                    title=article.get("title", ""), outlet=article.get("outlet", ""),
                    url=article.get("url", ""), text=text)},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return heuristic_analysis(article)
    parsed = parse_json_lenient(content)
    return sanitize(parsed, article)
