# ADR 0007 — Agents on LangGraph, Langfuse Cloud, Postgres on VPS

Date: 2026-09-26
Status: accepted (see `.scratch/deployment/research.md` for sources)

## Context

v0.1 is a plain-code pipeline (search → profile → analyze) on SQLite + Streamlit.
Production needs: agent rebuild, monitoring/visibility, LLM-as-judge evals,
10-20 parallel users on a single VPS + Docker, OpenRouter + DB.

## Decision

1. **LangGraph** for the agent rebuild (MIT, provider-neutral, durable
   Postgres checkpoints, time-travel). Rejected ADK: GCP gravity (deploy,
   sessions, tracing) buys nothing on a plain VPS and complicates model
   swapping via OpenRouter.
2. **Langfuse Cloud** (free tier) for tracing + evals. Rejected self-hosted
   Langfuse (Postgres + ClickHouse + Redis + S3 too heavy for one small box)
   and Phoenix (Elastic license, client-side evals). Self-host path stays open
   — same SDK, new base URL.
3. **Postgres in compose** for app data + LangGraph checkpoints. Rejected
   staying on SQLite (writer contention, no pgvector path) and buckets
   (no blobs exist — rows only).

## Consequences

- One `docker-compose.yml`: app + Postgres (+ pg_dump sidecar/cron).
- Judge evals run nightly on sampled runs, scored separately for trajectory
  vs final response.
- If trace volume or retention outgrows Cloud free tier, migrate Langfuse to
  self-hosted without app changes.
