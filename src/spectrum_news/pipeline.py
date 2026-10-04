"""Run entry: thin wrapper over the LangGraph run graph. Highest test seam."""
from __future__ import annotations

import uuid

from . import graph as graph_mod
from . import search as search_mod


def run_search(topic: str, category: str, country: str = "", model: str = "google/gemini-2.5-flash-lite",
               search_model: str | None = None,
               max_articles: int = 9, temperature: float = 0.2, db_url: str = "data/spectrum.db",
               openrouter_key: str = "", base_url: str = "https://openrouter.ai/api/v1",
               allowed_domains: list[str] | None = None,
               cache_ttl_seconds: int = 3600, use_cache: bool = True,
               search_query_fn=None, analyze_fn=None) -> dict:
    """Full Search run. Worker fns injectable for tests/demos.

    search_query_fn protocol: (query, SearchSpec) -> articles.
    analyze_fn protocol: (article, model, api_key, temperature) -> analysis.
    """
    search_model = search_model or model
    graph = graph_mod.build_graph(search_query_fn=search_query_fn, analyze_fn=analyze_fn)
    # Fresh thread per call: checkpoints record the run (crash-resumable via the
    # graph API), but a repeat call always re-executes instead of replaying.
    thread_id = f"run-{uuid.uuid4().hex[:12]}"
    with graph_mod.checkpointer(db_url) as cp:
        final = graph.compile(checkpointer=cp).invoke({
        "topic": topic, "category": category, "country": country or "",
        "model": model, "search_model": search_model,
        "max_articles": max_articles, "temperature": temperature,
        "db_url": db_url, "api_key": openrouter_key, "base_url": base_url,
        "allowed_domains": search_mod.normalize_domains(allowed_domains),
        "cache_ttl": cache_ttl_seconds, "use_cache": use_cache,
    }, config={"configurable": {"thread_id": thread_id}})
    return {"run_id": final.get("run_id"), "topic": topic, "category": category,
            "country": country, "model": model, "search_model": search_model,
            "allowed_domains": search_mod.normalize_domains(allowed_domains),
            "search_cache_hit": final.get("search_cache_hit", False),
            "results": final.get("results", [])}
