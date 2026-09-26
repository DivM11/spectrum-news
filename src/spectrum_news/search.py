"""Parallel web search: Tavily primary, DuckDuckGo fallback. Normalized Article dicts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse


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


def _tavily_search(query: str, api_key: str, max_results: int) -> list[dict]:
    import requests

    resp = requests.post(
        "https://api.tavily.com/search",
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=20,
    )
    # Tavily actually expects x-api-key header; support both
    if resp.status_code in (401, 403):
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": max_results},
            headers={"x-api-key": api_key},
            timeout=20,
        )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("results", data if isinstance(data, list) else [])
    out = []
    for it in items if isinstance(items, list) else []:
        out.append(
            normalize(
                it.get("url", ""),
                it.get("title", ""),
                it.get("content", it.get("snippet", "")),
                str(it.get("published_date", it.get("published", ""))),
            )
        )
    return out


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


def _run_one(query: str, max_results: int, tavily_key: str) -> list[dict]:
    if tavily_key:
        try:
            found = _tavily_search(query, tavily_key, max_results)
            if found:
                return found
        except Exception:
            pass  # fall through to DDG
    try:
        return _ddg_search(query, max_results)
    except Exception:
        return []


def fanout_search(topic: str, category: str, country: str = "",
                  max_results_per_query: int = 5, tavily_key: str = "",
                  max_articles: int = 12) -> list[dict]:
    queries = build_queries(topic, category, country)
    if not queries:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(queries))) as pool:
        batches = list(pool.map(lambda q: _run_one(q, max_results_per_query, tavily_key), queries))
    merged = [a for batch in batches for a in batch if a.get("url")]
    return dedupe(merged)[:max_articles]
