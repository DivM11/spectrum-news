"""Namespaced cache with TTL (search results, article analyses).

Single responsibility: keyed JSON storage with expiry, over the shared
SQLAlchemy store (SQLite file or Postgres URL — same as db.py).
Key *derivation* for each domain lives in the helpers below, so call sites
never hand-roll hashes (DRY). Cache access never raises — a broken cache
must not break a run.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import NamedTuple

from sqlalchemy import delete, select

from . import db as db_mod
from . import schema

SEARCH_NS = "search"
ANALYSIS_NS = "analysis"


class CacheKey(NamedTuple):
    namespace: str
    key: str


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def search_key(topic: str, category: str, country: str,
               search_model: str, max_articles: int,
               allowed_domains: list[str] | None = None) -> CacheKey:
    """Identity of one Search run's gathered articles (case/whitespace-insensitive)."""
    return CacheKey(SEARCH_NS, _hash({
        "topic": _norm(topic),
        "category": _norm(category),
        "country": _norm(country),
        "search_model": (search_model or "").strip(),
        "max_articles": int(max_articles),
        "allowed_domains": sorted({_norm(d) for d in (allowed_domains or []) if _norm(d)}),
    }))


def analysis_key(article: dict, model: str, temperature: float) -> CacheKey:
    """Identity of one Article Analysis: content + rating model + temperature."""
    article = article or {}
    return CacheKey(ANALYSIS_NS, _hash({
        "url": (article.get("url") or "").strip().lower().rstrip("/"),
        "title": (article.get("title") or "").strip(),
        "content": article.get("content") or article.get("snippet") or "",
        "model": (model or "").strip(),
        "temperature": float(temperature),
    }))


def get(db_url: str, cache_key: CacheKey, ttl_seconds: int):
    """Fresh cached value, or None on miss/expiry/error."""
    if ttl_seconds <= 0:
        return None
    try:
        engine = db_mod.engine_for(db_url)
        db_mod.init_db(db_url)
        with engine.connect() as conn:
            row = conn.execute(
                select(schema.cache_entries.c.response, schema.cache_entries.c.created_at)
                .where(schema.cache_entries.c.namespace == cache_key.namespace,
                       schema.cache_entries.c.key == cache_key.key)
            ).first()
        if not row:
            return None
        if time.time() - row[1] > ttl_seconds:
            return None
        return json.loads(row[0])
    except Exception:
        return None


def put(db_url: str, cache_key: CacheKey, value) -> None:
    """Store a JSON-serializable value. Never raises."""
    try:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        engine = db_mod.engine_for(db_url)
        db_mod.init_db(db_url)
        insert = (pg_insert if engine.dialect.name == "postgresql" else sqlite_insert)
        with engine.begin() as conn:
            conn.execute(
                insert(schema.cache_entries)
                .values(namespace=cache_key.namespace, key=cache_key.key,
                        response=json.dumps(value), created_at=time.time())
                .on_conflict_do_update(
                    index_elements=["namespace", "key"],
                    set_={"response": json.dumps(value), "created_at": time.time()},
                )
            )
    except Exception:
        pass


def clear(db_url: str, namespace: str | None = None) -> int:
    """Delete entries (one namespace, or all when None). Returns rows removed."""
    try:
        engine = db_mod.engine_for(db_url)
        db_mod.init_db(db_url)
        with engine.begin() as conn:
            stmt = delete(schema.cache_entries)
            if namespace is not None:
                stmt = stmt.where(schema.cache_entries.c.namespace == namespace)
            result = conn.execute(stmt)
            return result.rowcount or 0
    except Exception:
        return 0
