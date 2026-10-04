# Spectrum News 📰

AI + open-source powered fact-checking and bias highlighting — Ground News-style spectrum, AI does the checking.

User picks **Topic + Category** (+ optional **Country**) → parallel web search → **MBFC ratings + popularity** per outlet → **configurable OpenRouter rating model** scores factuality/bias + summary → **left→right spectrum view**, persisted in SQLite (dev) or Postgres (prod).

## Quickstart (uv)

```powershell
pip install uv
uv sync
copy .env.example .env   # add OPENROUTER_API_KEY (optional — works keyless via DDG + heuristic)
uv run streamlit run app.py
```

Extra search backend (keyless fallback): `uv pip install "ddgs>=8.0"` or `uv sync --extra search` — add `[search]` handling if needed.

## Docker

```powershell
docker compose up --build
# open http://localhost:8501
```

## Prod (single VPS, Postgres + backups)

```powershell
copy .env.example .env   # set OPENROUTER_API_KEY + POSTGRES_PASSWORD
docker compose -f docker-compose.prod.yml up --build -d
# app: http://<host>:8501, data in Postgres (pgdata volume), nightly dumps in pgbackups volume
```

Migrate the local SQLite history once: `uv run python scripts/import_sqlite.py --from data/spectrum.db --to "postgresql+psycopg://spectrum:<pw>@<host>:5432/spectrum"`.
Schema changes go through Alembic: `uv run alembic upgrade head` (also runs automatically in the prod container).

Kill-the-box drill: `docker compose -f docker-compose.prod.yml down -v`, `up -d db`, then
`docker compose -f docker-compose.prod.yml exec -T db pg_restore -U spectrum -d spectrum -c < pgbackups/spectrum-<latest>.dump`
(copy the dump out first: `docker compose -f docker-compose.prod.yml cp backup:/backups/<file> ./`).

## Deploy to Google Cloud

Phase-by-phase runbook (Cloud Run + self-hosted Postgres on GCE, no Cloud SQL): [`docs/deploy/google-cloud.md`](docs/deploy/google-cloud.md).

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```

## Layout

- `app.py` — Streamlit UI (preset chips, rating/search-model config, outlet allowlist, warm button, spectrum view, history)
- `src/spectrum_news/` — `config`, `db` (SQLAlchemy: SQLite dev / Postgres prod), `graph` (LangGraph run graph + checkpoints), `tracing` (optional Langfuse), `evals` (judge scoring), `search` (OpenRouter web_search→DDG, parallel), `cache` (namespaced TTL cache: search + analyses), `sources` (MBFC CSV + Tranco/curated popularity), `analyzer` (OpenRouter strict-JSON + heuristic fallback), `pipeline` (run entry over the graph)
- `data/mbfc_ratings.csv` — curated outlet ratings (extend via PR)
- `.scratch/spectrum-news/` — spec + tracer tickets (local issue tracker)
- `docs/adr/` — stack, search, source-profile decisions
