"""LangGraph rebuild of the Search-run pipeline. Same behavior, durable substrate.

Nodes reuse the existing search/sources/analyzer/db/cache functions as their
implementations (no prompt or logic changes in this phase):

  plan -> check_search_cache ->[hit]--> profile -> analyze -> persist -> END
                             ->[miss]-> fetch --^

fetch/analyze parallelize with internal ThreadPools: Send fan-out of sync I/O
nodes would execute serially in-process, so pools preserve the parallel
behavior the pipeline always had. Checkpoints (SQLite dev / Postgres prod)
make crashed runs resumable by thread id.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Iterator, TypedDict

from langgraph.graph import END, START, StateGraph

from . import analyzer as analyzer_mod
from . import cache as cache_mod
from . import db as db_mod
from . import search as search_mod
from . import tracing as tracing_mod


class RunState(TypedDict, total=False):
    topic: str
    category: str
    country: str
    model: str
    search_model: str
    base_url: str
    api_key: str
    max_articles: int
    results_per_query: int
    temperature: float
    db_url: str
    cache_ttl: int
    use_cache: bool
    allowed_domains: list
    queries: list
    articles: list
    profiled: list
    results: list
    run_id: int
    search_cache_hit: bool


def default_search_query(query: str, spec: search_mod.SearchSpec) -> list[dict]:
    return search_mod._run_one(
        query, max_results=spec.results_per_query, api_key=spec.api_key,
        search_model=spec.search_model, base_url=spec.base_url,
        allowed_domains=spec.domains())


@contextmanager
def checkpointer(db_url: str) -> Iterator:
    """Checkpointer matching the store, as a context manager.

    MemorySaver for bare in-memory SQLite; SqliteSaver file otherwise;
    PostgresSaver (with setup) for Postgres URLs.
    """
    url = db_mod.resolve_url(db_url)
    if url.startswith("sqlite:"):
        path = url[len("sqlite:///"):]
        if not path or path == ":memory:":
            from langgraph.checkpoint.memory import MemorySaver
            yield MemorySaver()
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver
            with SqliteSaver.from_conn_string(path) as saver:
                yield saver
    else:
        from langgraph.checkpoint.postgres import PostgresSaver
        with PostgresSaver.from_conn_string(pg_conninfo_for(url)) as saver:
            try:
                saver.setup()
            except Exception:
                pass
            yield saver


def pg_conninfo_for(db_url: str) -> str:
    """SQLAlchemy Postgres URL -> psycopg conninfo (offline-testable)."""
    return db_mod.resolve_url(db_url).replace("postgresql+psycopg://", "postgresql://", 1)


def build_graph(search_query_fn=None, analyze_fn=None):
    """Compile the run graph. Both worker fns injectable for tests/demos."""
    search_query_fn = search_query_fn or default_search_query
    analyze_fn = analyze_fn or analyzer_mod.analyze_article

    @tracing_mod.observe("plan")
    def plan(state: RunState) -> dict:
        return {"queries": search_mod.build_queries(
            state["topic"], state["category"], state.get("country", ""))}

    @tracing_mod.observe("check_search_cache")
    def check_search_cache(state: RunState) -> dict:
        if not state.get("use_cache", True):
            return {"articles": [], "search_cache_hit": False}
        spec = _spec_from(state)
        hit = cache_mod.get(state["db_url"], cache_mod.search_key(
            spec.topic, spec.category, spec.country, spec.search_model,
            spec.max_articles, spec.domains()), state.get("cache_ttl", 3600))
        return {"articles": hit or [], "search_cache_hit": hit is not None}

    def _route_cache(state: RunState) -> str:
        return "hit" if state.get("articles") else "fetch"

    @tracing_mod.observe("fetch")
    def fetch(state: RunState) -> dict:
        spec = _spec_from(state)
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(state.get("queries", []))))) as pool:
            batches = list(pool.map(lambda q: _safe_query(search_query_fn, q, spec),
                                    state.get("queries", [])))
        merged = [a for batch in batches for a in batch if a.get("url")]
        articles = search_mod.dedupe(merged)[:spec.max_articles]
        if state.get("use_cache", True):
            cache_mod.put(state["db_url"], cache_mod.search_key(
                spec.topic, spec.category, spec.country, spec.search_model,
                spec.max_articles, spec.domains()), articles)
        return {"articles": articles}

    @tracing_mod.observe("profile")
    def profile(state: RunState) -> dict:
        return {"profiled": [
            {"article": a, "profile": sources_profile(a)}
            for a in state.get("articles", [])]}

    @tracing_mod.observe("analyze")
    def analyze(state: RunState) -> dict:
        items = state.get("profiled", [])
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(items)))) as pool:
            results = list(pool.map(
                lambda item: _analyze_one(analyze_fn, state, item), items))
        results.sort(key=lambda r: float(r["analysis"].get("bias_score", 0)))
        return {"results": results}

    @tracing_mod.observe("persist")
    def persist(state: RunState) -> dict:
        db_url = state["db_url"]
        db_mod.init_db(db_url)
        run_id = db_mod.create_run(db_url, state["topic"], state["category"],
                                   state.get("country", ""), state["model"],
                                   allowed_domains=state.get("allowed_domains") or [])
        for r in state.get("results", []):
            aid = db_mod.insert_article(db_url, run_id, r["article"])
            db_mod.insert_analysis(db_url, aid, r["analysis"], r["profile"])
        return {"run_id": run_id}

    graph = StateGraph(RunState)
    graph.add_node("plan", plan)
    graph.add_node("check_search_cache", check_search_cache)
    graph.add_node("fetch", fetch)
    graph.add_node("profile", profile)
    graph.add_node("analyze", analyze)
    graph.add_node("persist", persist)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "check_search_cache")
    graph.add_conditional_edges("check_search_cache", _route_cache,
                               {"hit": "profile", "fetch": "fetch"})
    graph.add_edge("fetch", "profile")
    graph.add_edge("profile", "analyze")
    graph.add_edge("analyze", "persist")
    graph.add_edge("persist", END)
    return graph


def _spec_from(state: RunState) -> search_mod.SearchSpec:
    return search_mod.SearchSpec(
        topic=state["topic"], category=state["category"],
        country=state.get("country", ""),
        max_articles=state.get("max_articles", 9),
        results_per_query=state.get("results_per_query", 5),
        search_model=state.get("search_model", ""),
        base_url=state.get("base_url", "https://openrouter.ai/api/v1"),
        api_key=state.get("api_key", ""),
        allowed_domains=state.get("allowed_domains") or [])


def _safe_query(search_query_fn, query: str, spec: search_mod.SearchSpec) -> list[dict]:
    try:
        return search_query_fn(query, spec) or []
    except Exception:
        return []


def sources_profile(article: dict) -> dict:
    from . import sources as sources_mod
    return sources_mod.source_profile(article.get("url", ""))


def _analyze_one(analyze_fn, state: RunState, item: dict) -> dict:
    article = item["article"]
    akey = cache_mod.analysis_key(article, state["model"], state.get("temperature", 0.2))
    analysis = (cache_mod.get(state["db_url"], akey, state.get("cache_ttl", 3600))
                if state.get("use_cache", True) else None)
    cached = analysis is not None
    if analysis is None:
        try:
            analysis = analyze_fn(article, state["model"], state.get("api_key", ""),
                                  temperature=state.get("temperature", 0.2))
        except Exception:
            # One bad article must not abort the run; degrade visibly.
            analysis = analyzer_mod.heuristic_analysis(article)
            analysis["verdict"] += " (LLM analysis failed; heuristic fallback)"
        if state.get("use_cache", True):
            cache_mod.put(state["db_url"], akey, analysis)
    return {"article": article, "profile": item["profile"],
            "analysis": analysis, "cached": cached}


def run_to_completion(graph, state: RunState, thread_id: str = "") -> dict:
    """Invoke with a resumable thread id; returns the final state."""
    return graph.invoke(state, config={"configurable": {"thread_id": thread_id or f"run-{uuid.uuid4().hex[:12]}"}})
