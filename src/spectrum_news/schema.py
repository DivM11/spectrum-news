"""Shared table definitions. Single source of truth for db.py, cache.py, and Alembic.

Dialect-neutral types only (works on SQLite and Postgres without branches).
"""
from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, Integer, MetaData, PrimaryKeyConstraint, String, Table, Text

metadata = MetaData()

search_runs = Table(
    "search_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("topic", Text, nullable=False),
    Column("category", Text, nullable=False, default=""),
    Column("country", Text, nullable=False, default=""),
    Column("model", Text, nullable=False, default=""),
    Column("created_at", Float, nullable=False),
)

articles = Table(
    "articles",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("search_runs.id", ondelete="CASCADE"),
           nullable=False, index=True),
    Column("url", Text, nullable=False, default=""),
    Column("outlet", Text, nullable=False, default=""),
    Column("title", Text, nullable=False, default=""),
    Column("snippet", Text, nullable=False, default=""),
    Column("content", Text, nullable=False, default=""),
    Column("published", Text, nullable=False, default=""),
)

analyses = Table(
    "analyses",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("article_id", Integer, ForeignKey("articles.id", ondelete="CASCADE"),
           nullable=False, index=True),
    Column("factuality_score", Float, nullable=False, default=50),
    Column("bias_label", String(32), nullable=False, default="Center"),
    Column("bias_score", Float, nullable=False, default=0),
    Column("summary", Text, nullable=False, default=""),
    Column("key_claims", Text, nullable=False, default="[]"),
    Column("loaded_phrases", Text, nullable=False, default="[]"),
    Column("verdict", Text, nullable=False, default=""),
    Column("mbfc_factuality", String(64), nullable=False, default="Unknown"),
    Column("mbfc_bias", String(64), nullable=False, default="Unknown"),
    Column("popularity_rank", Integer, nullable=False, default=999999),
)

cache_entries = Table(
    "cache_entries",
    metadata,
    Column("namespace", String(64), nullable=False),
    Column("key", String(128), nullable=False),
    Column("response", Text, nullable=False),
    Column("created_at", Float, nullable=False),
    PrimaryKeyConstraint("namespace", "key", name="pk_cache_entries"),
)

TABLES_IN_LOAD_ORDER = ["search_runs", "articles", "analyses", "cache_entries"]
