"""Pipeline: search -> source profiles -> analyze -> persist. Highest test seam."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import analyzer as analyzer_mod
from . import cache as cache_mod
from . import db as db_mod
from . import search as search_mod
from . import sources as sources_mod


def run_search(topic: str, category: str, country: str = "", model: str = "google/gemini-2.5-flash-lite",
               search_model: str | None = None,
               max_articles: int = 9, temperature: float = 0.2, db_url: str = "data/spectrum.db",
               openrouter_key: str = "", base_url: str = "https://openrouter.ai/api/v1",
               allowed_domains: list[str] | None = None,
               cache_ttl_seconds: int = 3600, use_cache: bool = True,
               search_fn=None, analyze_fn=None) -> dict:
    """Full Search run. search_fn/analyze_fn injectable for tests/demos.

    search_fn protocol: (topic, category, country, max_articles, api_key, search_model,
                         base_url, allowed_domains).
    analyze_fn protocol: (article, model, api_key, temperature) -> analysis.
    """
    search_fn = search_fn or search_mod.fanout_search
    analyze_fn = analyze_fn or analyzer_mod.analyze_article
    search_model = search_model or model
    domains = search_mod.normalize_domains(allowed_domains)

    skey = cache_mod.search_key(topic, category, country or "", search_model, max_articles, domains)
    articles = cache_mod.get(db_url, skey, cache_ttl_seconds) if use_cache else None
    search_cache_hit = articles is not None
    if articles is None:
        articles = search_fn(topic, category, country, max_articles=max_articles,
                             api_key=openrouter_key, search_model=search_model,
                             base_url=base_url, allowed_domains=domains)
        if use_cache:
            cache_mod.put(db_url, skey, articles or [])
    articles = (articles or [])[:max_articles]

    db_mod.init_db(db_url)
    run_id = db_mod.create_run(db_url, topic, category, country or "", model)

    def _analyze(article: dict) -> dict:
        profile = sources_mod.source_profile(article.get("url", ""))
        akey = cache_mod.analysis_key(article, model, temperature)
        analysis = cache_mod.get(db_url, akey, cache_ttl_seconds) if use_cache else None
        cached = analysis is not None
        if analysis is None:
            try:
                analysis = analyze_fn(article, model, openrouter_key, temperature=temperature)
            except Exception:
                # One bad article must not abort the run; degrade visibly.
                analysis = analyzer_mod.heuristic_analysis(article)
                analysis["verdict"] += " (LLM analysis failed; heuristic fallback)"
            if use_cache:
                cache_mod.put(db_url, akey, analysis)
        return {"article": article, "profile": profile, "analysis": analysis, "cached": cached}

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(articles)))) as pool:
        results = list(pool.map(_analyze, articles)) if articles else []

    for r in results:
        aid = db_mod.insert_article(db_url, run_id, r["article"])
        db_mod.insert_analysis(db_url, aid, r["analysis"], r["profile"])

    results.sort(key=lambda r: float(r["analysis"].get("bias_score", 0)))
    return {"run_id": run_id, "topic": topic, "category": category,
            "country": country, "model": model, "search_model": search_model,
            "allowed_domains": domains,
            "search_cache_hit": search_cache_hit, "results": results}
