"""Namespaced SQLite cache with TTL (search results, article analyses).

Single responsibility: keyed JSON storage with expiry. Key *derivation* for each
domain lives in the helpers below, so call sites never hand-roll hashes (DRY).
Cache access never raises — a broken cache must not break a run.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from typing import NamedTuple

SEARCH_NS = "search"
ANALYSIS_NS = "analysis"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
  namespace TEXT NOT NULL,
  key TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (namespace, key)
);
DROP TABLE IF EXISTS search_cache;
"""


class CacheKey(NamedTuple):
    namespace: str
    key: str


def ensure_table(db_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def search_key(topic: str, category: str, country: str,
               search_model: str, max_articles: int) -> CacheKey:
    """Identity of one Search run's gathered articles (case/whitespace-insensitive)."""
    return CacheKey(SEARCH_NS, _hash({
        "topic": _norm(topic),
        "category": _norm(category),
        "country": _norm(country),
        "search_model": (search_model or "").strip(),
        "max_articles": int(max_articles),
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


def _connect(db_path: str) -> sqlite3.Connection:
    ensure_table(db_path)
    return sqlite3.connect(db_path)


def get(db_path: str, cache_key: CacheKey, ttl_seconds: int):
    """Fresh cached value, or None on miss/expiry/error."""
    if ttl_seconds <= 0:
        return None
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT response, created_at FROM cache_entries WHERE namespace = ? AND key = ?",
                (cache_key.namespace, cache_key.key),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        if time.time() - row[1] > ttl_seconds:
            return None
        return json.loads(row[0])
    except Exception:
        return None


def put(db_path: str, cache_key: CacheKey, value) -> None:
    """Store a JSON-serializable value. Never raises."""
    try:
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache_entries (namespace, key, response, created_at)"
                " VALUES (?,?,?,?)",
                (cache_key.namespace, cache_key.key, json.dumps(value), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def clear(db_path: str, namespace: str | None = None) -> int:
    """Delete entries (one namespace, or all when None). Returns rows removed."""
    try:
        conn = _connect(db_path)
        try:
            if namespace is None:
                cur = conn.execute("DELETE FROM cache_entries")
            else:
                cur = conn.execute("DELETE FROM cache_entries WHERE namespace = ?", (namespace,))
            conn.commit()
            return cur.rowcount or 0
        finally:
            conn.close()
    except Exception:
        return 0
