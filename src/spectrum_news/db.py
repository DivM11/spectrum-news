"""Persistence over SQLAlchemy (SQLite file or Postgres URL).

`db_url` in every function accepts either a filesystem path (SQLite) or a
full SQLAlchemy URL (e.g. ``postgresql+psycopg://…``). One code path, two
dialects — no backend branches at call sites.
"""
from __future__ import annotations

import os
import time

from sqlalchemy import create_engine, desc, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from . import schema


_ENGINES: dict[str, Engine] = {}
_INITIALIZED: set[str] = set()


def resolve_url(db_path_or_url: str) -> str:
    """Filesystem path -> ``sqlite:///`` URL; full URL passes through."""
    s = (db_path_or_url or "").strip()
    if "://" in s:
        return s
    path = os.path.abspath(s or "data/spectrum.db")
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return f"sqlite:///{path}"


def engine_for(db_path_or_url: str) -> Engine:
    url = resolve_url(db_path_or_url)
    engine = _ENGINES.get(url)
    if engine is None:
        kwargs: dict = {}
        if url.startswith("sqlite:"):
            # Short transactions + threads: open/close per use, never hold locks.
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = NullPool
        engine = create_engine(url, pool_pre_ping=True, **kwargs)
        if url.startswith("sqlite:"):
            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA foreign_keys=ON;")
                cur.close()
        _ENGINES[url] = engine
    return engine


def init_db(db_path_or_url: str) -> None:
    engine = engine_for(db_path_or_url)
    url = str(engine.url)
    if url in _INITIALIZED:
        return
    schema.metadata.create_all(engine)
    # One-time cleanup of the pre-SQLAlchemy single-purpose table.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS search_cache"))
    _INITIALIZED.add(url)


def dispose_all() -> None:
    """Close pooled connections and forget engines (tests, shutdown)."""
    for engine in _ENGINES.values():
        try:
            engine.dispose()
        except Exception:
            pass
    _ENGINES.clear()
    _INITIALIZED.clear()


def create_run(db_url: str, topic: str, category: str, country: str, model: str,
               allowed_domains: list | None = None) -> int:
    import json
    engine = engine_for(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            schema.search_runs.insert().values(
                topic=topic, category=category, country=country,
                model=model, allowed_domains=json.dumps(allowed_domains or []),
                created_at=time.time(),
            )
        )
        return int(result.inserted_primary_key[0])


def insert_article(db_url: str, run_id: int, article: dict) -> int:
    engine = engine_for(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            schema.articles.insert().values(
                run_id=run_id,
                url=article.get("url", ""),
                outlet=article.get("outlet", ""),
                title=article.get("title", ""),
                snippet=article.get("snippet", ""),
                content=article.get("content", article.get("snippet", "")),
                published=article.get("published", ""),
            )
        )
        return int(result.inserted_primary_key[0])


def insert_analysis(db_url: str, article_id: int, analysis: dict, profile: dict) -> int:
    import json

    def _dump(v):
        return v if isinstance(v, str) else json.dumps(v or [])

    engine = engine_for(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            schema.analyses.insert().values(
                article_id=article_id,
                factuality_score=float(analysis.get("factuality_score", 50)),
                bias_label=analysis.get("bias_label", "Center"),
                bias_score=float(analysis.get("bias_score", 0)),
                summary=analysis.get("summary", ""),
                key_claims=_dump(analysis.get("key_claims", [])),
                loaded_phrases=_dump(analysis.get("loaded_phrases", [])),
                verdict=analysis.get("verdict", ""),
                mbfc_factuality=profile.get("mbfc_factuality", "Unknown"),
                mbfc_bias=profile.get("mbfc_bias", "Unknown"),
                popularity_rank=int(profile.get("popularity_rank", 999999)),
            )
        )
        return int(result.inserted_primary_key[0])


def list_runs(db_url: str, limit: int = 20) -> list[dict]:
    engine = engine_for(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            select(schema.search_runs)
            .order_by(desc(schema.search_runs.c.id))
            .limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


def fetch_run_evidence(db_url: str, run_id: int) -> list[dict]:
    """Joined article + analysis rows for one run, ordered by bias_score."""
    engine = engine_for(db_url)
    a = schema.articles
    an = schema.analyses
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                a.c.url, a.c.outlet, a.c.title, a.c.snippet, a.c.published,
                an.c.factuality_score, an.c.bias_label, an.c.bias_score,
                an.c.summary, an.c.key_claims, an.c.loaded_phrases, an.c.verdict,
                an.c.mbfc_factuality, an.c.mbfc_bias, an.c.popularity_rank,
            )
            .select_from(a.join(an, an.c.article_id == a.c.id))
            .where(a.c.run_id == run_id)
            .order_by(an.c.bias_score.asc())
        ).mappings().all()
        return [dict(r) for r in rows]
