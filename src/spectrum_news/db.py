"""SQLite persistence: search_runs, articles, analyses. WAL mode, stdlib only."""
from __future__ import annotations

import os
import sqlite3
import time


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS search_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,
  category TEXT NOT NULL,
  country TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  outlet TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  snippet TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  published TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  factuality_score REAL NOT NULL DEFAULT 50,
  bias_label TEXT NOT NULL DEFAULT 'Center',
  bias_score REAL NOT NULL DEFAULT 0,
  summary TEXT NOT NULL DEFAULT '',
  key_claims TEXT NOT NULL DEFAULT '',
  loaded_phrases TEXT NOT NULL DEFAULT '',
  verdict TEXT NOT NULL DEFAULT '',
  mbfc_factuality TEXT NOT NULL DEFAULT 'Unknown',
  mbfc_bias TEXT NOT NULL DEFAULT 'Unknown',
  popularity_rank INTEGER NOT NULL DEFAULT 999999
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_run(db_path: str, topic: str, category: str, country: str, model: str) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO search_runs (topic, category, country, model, created_at) VALUES (?,?,?,?,?)",
            (topic, category, country, model, time.time()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def insert_article(db_path: str, run_id: int, article: dict) -> int:
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO articles (run_id, url, outlet, title, snippet, content, published) VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                article.get("url", ""),
                article.get("outlet", ""),
                article.get("title", ""),
                article.get("snippet", ""),
                article.get("content", article.get("snippet", "")),
                article.get("published", ""),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def insert_analysis(db_path: str, article_id: int, analysis: dict, profile: dict) -> int:
    import json

    def _dump(v):
        return v if isinstance(v, str) else json.dumps(v or [])

    conn = connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO analyses
            (article_id, factuality_score, bias_label, bias_score, summary,
             key_claims, loaded_phrases, verdict,
             mbfc_factuality, mbfc_bias, popularity_rank)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                article_id,
                float(analysis.get("factuality_score", 50)),
                analysis.get("bias_label", "Center"),
                float(analysis.get("bias_score", 0)),
                analysis.get("summary", ""),
                _dump(analysis.get("key_claims", [])),
                _dump(analysis.get("loaded_phrases", [])),
                analysis.get("verdict", ""),
                profile.get("mbfc_factuality", "Unknown"),
                profile.get("mbfc_bias", "Unknown"),
                int(profile.get("popularity_rank", 999999)),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_runs(db_path: str, limit: int = 20) -> list[dict]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM search_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_run_evidence(db_path: str, run_id: int) -> list[dict]:
    """Joined article + analysis rows for one run, ordered by bias_score."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """SELECT a.url, a.outlet, a.title, a.snippet, a.published,
                      an.factuality_score, an.bias_label, an.bias_score, an.summary,
                      an.key_claims, an.loaded_phrases, an.verdict,
                      an.mbfc_factuality, an.mbfc_bias, an.popularity_rank
               FROM articles a JOIN analyses an ON an.article_id = a.id
               WHERE a.run_id = ? ORDER BY an.bias_score ASC""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
