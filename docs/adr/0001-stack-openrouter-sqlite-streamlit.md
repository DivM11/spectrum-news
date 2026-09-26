# ADR 0001 — OpenRouter + SQLite + Streamlit + uv + Docker

Date: 2026-09-26
Status: accepted

## Context

Need an LLM provider, persistence, frontend, and reproducible builds for a solo/small-team fact-checking service. Candidates: direct OpenAI/Anthropic SDKs vs OpenRouter gateway; Postgres vs SQLite; Next.js/React vs Streamlit; pip vs uv; bare deploy vs Docker.

## Decision

- LLM via **OpenRouter** (single gateway, configurable `RATING_MODEL`, OpenAI-compatible API).
- Persistence via **SQLite** (`sqlite3` stdlib, WAL mode, file at `data/spectrum.db`).
- Frontend via **Streamlit** (Python-only, sidebar config, fast spectrum UI).
- Build/deps via **uv** (`pyproject.toml` + `uv.lock`).
- Ship via **Docker** (`Dockerfile` + `docker-compose.yml`).

## Consequences

- No vendor lock to one lab; model swap = env var change.
- Zero DB ops; single-file DB, easy backup. Concurrent writes limited — acceptable for this workload (reads dominate, writes are per-run inserts).
- Streamlit limits custom frontend polish but maximizes velocity.
