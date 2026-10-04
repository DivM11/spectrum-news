"""Initial schema: search_runs, articles, analyses, cache_entries.

Revision ID: 0001
Revises:
Create Date: 2026-09-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("country", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("outlet", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("published", sa.Text(), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["run_id"], ["search_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_articles_run_id", "articles", ["run_id"])
    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("factuality_score", sa.Float(), nullable=False, server_default="50"),
        sa.Column("bias_label", sa.String(32), nullable=False, server_default="Center"),
        sa.Column("bias_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_claims", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("loaded_phrases", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verdict", sa.Text(), nullable=False, server_default=""),
        sa.Column("mbfc_factuality", sa.String(64), nullable=False, server_default="Unknown"),
        sa.Column("mbfc_bias", sa.String(64), nullable=False, server_default="Unknown"),
        sa.Column("popularity_rank", sa.Integer(), nullable=False, server_default="999999"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyses_article_id", "analyses", ["article_id"])
    op.create_table(
        "cache_entries",
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("namespace", "key", name="pk_cache_entries"),
    )


def downgrade() -> None:
    op.drop_table("cache_entries")
    op.drop_index("ix_analyses_article_id", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_articles_run_id", table_name="articles")
    op.drop_table("articles")
    op.drop_table("search_runs")
