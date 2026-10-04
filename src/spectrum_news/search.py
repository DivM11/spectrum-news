"""Parallel web search via an OpenRouter web-search model, DDG fallback.

Primary path calls OpenRouter chat completions with the ``openrouter:web_search``
server tool, asking the model to return gathered articles as strict JSON.
Normalized Article dicts throughout.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class SearchSpec:
    """Everything one fan-out search needs. New search options extend this
    type instead of rippling through every search_fn signature (fakes incl.)."""
    topic: str
    category: str
    country: str = ""
    max_articles: int = 12
    results_per_query: int = 5
    search_model: str = "deepseek/deepseek-v4-flash"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    allowed_domains: list[str] | None = field(default=None)

    def domains(self) -> list[str]:
        return normalize_domains(self.allowed_domains)

SEARCH_PROMPT = """You have live web search. Find {n} recent news articles about the QUERY below,
covering DIFFERENT outlets and perspectives (left, center, right, international if relevant).

QUERY: {query}

Return STRICT JSON only (no markdown fences, no commentary): a JSON array where each item is
{{"url": "<canonical article url>", "title": "<headline>", "snippet": "<1-2 sentence excerpt>",
"published": "<date if known, else empty string>"}}.
Prefer full article URLs over homepages. At most {n} items."""


def build_queries(topic: str, category: str, country: str) -> list[str]:
    topic = (topic or "").strip()
    country = (country or "").strip()
    base = f"{topic} {category}".strip()
    queries = [base, f"{base} latest news", f"{base} analysis different perspectives"]
    if country:
        queries = [f"{q} {country}" for q in queries]
    # de-dupe, drop empties
    seen, out = set(), []
    for q in queries:
        q = " ".join(q.split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:3]


def outlet_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or url


def normalize(url: str, title: str, snippet: str, published: str = "") -> dict:
    url = (url or "").strip()
    return {
        "url": url,
        "outlet": outlet_of(url),
        "title": (title or "").strip() or url,
        "snippet": (snippet or "").strip(),
        "content": (snippet or "").strip(),
        "published": (published or "").strip(),
    }


def dedupe(articles: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in articles:
        key = (a.get("url") or "").strip().lower().rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _strip_fences(s: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", (s or "").strip(), flags=re.MULTILINE).strip()


def parse_articles(s: str) -> list[dict]:
    """Lenient parse of the search model's JSON: bare array or {"articles": [...]}."""
    text = _strip_fences(s)
    data = None
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                return []
    if isinstance(data, dict):
        data = data.get("articles", [])
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if not isinstance(it, dict) or not it.get("url"):
            continue
        out.append(
            normalize(it.get("url", ""), it.get("title", ""),
                      it.get("snippet", it.get("content", "")),
                      str(it.get("published", it.get("published_date", ""))))
        )
    return out


def normalize_domains(domains: list[str] | None) -> list[str]:
    """Lowercase/strip/dedupe/sort outlet domains. Single home for this shape."""
    return sorted({(d or "").strip().lower() for d in (domains or []) if (d or "").strip()})


def _openrouter_search(query: str, *, model: str, api_key: str,
                       base_url: str, max_results: int, timeout: int = 90,
                       allowed_domains: list[str] | None = None) -> list[dict]:
    import requests

    tool_params: dict = {"max_results": max_results, "max_total_results": max_results}
    domains = normalize_domains(allowed_domains)
    if domains:
        tool_params["allowed_domains"] = domains
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": SEARCH_PROMPT.format(query=query, n=max_results)},
            ],
            "tools": [{"type": "openrouter:web_search", "parameters": tool_params}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return parse_articles(content)


def _ddg_search(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []  # search extra not installed
    out = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            out.append(normalize(r.get("href", ""), r.get("title", ""), r.get("body", "")))
    return out


def _run_one(query: str, *, max_results: int, api_key: str,
             search_model: str, base_url: str,
             allowed_domains: list[str] | None = None) -> list[dict]:
    if api_key:
        try:
            found = _openrouter_search(query, model=search_model, api_key=api_key,
                                       base_url=base_url, max_results=max_results,
                                       allowed_domains=allowed_domains)
            if found:
                return found
        except Exception:
            pass  # fall through to DDG
    try:
        return _ddg_search(query, max_results)
    except Exception:
        return []


def fanout_search(spec: SearchSpec) -> list[dict]:
    queries = build_queries(spec.topic, spec.category, spec.country)
    if not queries:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(queries))) as pool:
        batches = list(pool.map(
            lambda q: _run_one(q, max_results=spec.results_per_query, api_key=spec.api_key,
                               search_model=spec.search_model, base_url=spec.base_url,
                               allowed_domains=spec.domains()),
            queries,
        ))
    merged = [a for batch in batches for a in batch if a.get("url")]
    return dedupe(merged)[:spec.max_articles]
