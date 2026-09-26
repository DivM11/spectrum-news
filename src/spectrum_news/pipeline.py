"""Pipeline: search -> source profiles -> analyze -> persist. Highest test seam."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import analyzer as analyzer_mod
from . import db as db_mod
from . import search as search_mod
from . import sources as sources_mod


def run_search(topic: str, category: str, country: str = "", model: str = "openai/gpt-4o-mini",
               max_articles: int = 9, temperature: float = 0.2, db_path: str = "data/spectrum.db",
               tavily_key: str = "", openrouter_key: str = "",
               search_fn=None, analyze_fn=None) -> dict:
    """Full Search run. search_fn/analyze_fn injectable for tests/demos."""
    search_fn = search_fn or search_mod.fanout_search
    analyze_fn = analyze_fn or analyzer_mod.analyze_article

    articles = search_fn(topic, category, country, max_articles=max_articles, tavily_key=tavily_key) \
        if "max_articles" in getattr(search_fn, "__code__", None).co_varnames else \
        search_fn(topic, category, country)

    articles = (articles or [])[:max_articles]

    db_mod.init_db(db_path)
    run_id = db_mod.create_run(db_path, topic, category, country or "", model)

    def _analyze(article: dict) -> dict:
        profile = sources_mod.source_profile(article.get("url", ""))
        try:
            analysis = analyze_fn(article, model, openrouter_key, temperature=temperature) \
                if "temperature" in getattr(analyze_fn, "__code__", None).co_varnames else \
                analyze_fn(article, model, openrouter_key)
        except TypeError:
            analysis = analyze_fn(article, model)
        return {"article": article, "profile": profile, "analysis": analysis}

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(articles)))) as pool:
        results = list(pool.map(_analyze, articles)) if articles else []

    for r in results:
        aid = db_mod.insert_article(db_path, run_id, r["article"])
        db_mod.insert_analysis(db_path, aid, r["analysis"], r["profile"])

    results.sort(key=lambda r: float(r["analysis"].get("bias_score", 0)))
    return {"run_id": run_id, "topic": topic, "category": category,
            "country": country, "model": model, "results": results}
