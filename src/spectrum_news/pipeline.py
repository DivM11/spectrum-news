"""Run entry: thin wrapper over the LangGraph run graph. Highest test seam."""
from __future__ import annotations

import contextlib
import threading
import uuid

from . import cache as cache_mod
from . import graph as graph_mod
from . import search as search_mod
from . import tracing as tracing_mod

_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


def _uncached_slot(limit: int) -> contextlib.AbstractContextManager:
    """Bound concurrent uncached runs; cached hits bypass entirely."""
    sem = _SEMAPHORES.get(limit)
    if sem is None:
        sem = _SEMAPHORES[limit] = threading.BoundedSemaphore(max(1, limit))
    return sem


def run_search(topic: str, category: str, country: str = "", model: str = "google/gemini-2.5-flash-lite",
               search_model: str | None = None,
               max_articles: int = 9, temperature: float = 0.2, db_url: str = "data/spectrum.db",
               openrouter_key: str = "", base_url: str = "https://openrouter.ai/api/v1",
               allowed_domains: list[str] | None = None,
               cache_ttl_seconds: int = 3600, use_cache: bool = True,
               max_concurrent_uncached_runs: int = 4,
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

    @tracing_mod.observe("search-run")
    def _invoke():
        with graph_mod.checkpointer(db_url) as cp:
            return graph.compile(checkpointer=cp).invoke({
                "topic": topic, "category": category, "country": country or "",
                "model": model, "search_model": search_model,
                "max_articles": max_articles, "temperature": temperature,
                "db_url": db_url, "api_key": openrouter_key, "base_url": base_url,
                "allowed_domains": search_mod.normalize_domains(allowed_domains),
                "cache_ttl": cache_ttl_seconds, "use_cache": use_cache,
            }, config={"configurable": {"thread_id": thread_id}})

    # Peek at the search cache up front: cache hits skip the semaphore so
    # interactive repeat traffic never queues behind fresh LLM work.
    peek_key = cache_mod.search_key(topic, category, country or "", search_model,
                                    max_articles,
                                    search_mod.normalize_domains(allowed_domains))
    peek_hit = use_cache and cache_mod.get(db_url, peek_key, cache_ttl_seconds) is not None
    gate = (contextlib.nullcontext() if peek_hit
            else _uncached_slot(max_concurrent_uncached_runs))
    with gate:
        final = _invoke()
    return {"run_id": final.get("run_id"), "topic": topic, "category": category,
            "country": country, "model": model, "search_model": search_model,
            "allowed_domains": search_mod.normalize_domains(allowed_domains),
            "search_cache_hit": final.get("search_cache_hit", False),
            "results": final.get("results", [])}
