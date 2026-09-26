# Spectrum News 📰

AI + open-source powered fact-checking and bias highlighting — Ground News-style spectrum, AI does the checking.

User picks **Topic + Category** (+ optional **Country**) → parallel web search → **MBFC ratings + popularity** per outlet → **configurable OpenRouter rating model** scores factuality/bias + summary → **left→right spectrum view**, persisted in SQLite.

## Quickstart (uv)

```powershell
pip install uv
uv sync
copy .env.example .env   # add OPENROUTER_API_KEY + TAVILY_API_KEY (optional — works keyless via DDG + heuristic)
uv run streamlit run app.py
```

Extra search backend (keyless fallback): `uv pip install "ddgs>=8.0"` or `uv sync --extra search` — add `[search]` handling if needed.

## Docker

```powershell
docker compose up --build
# open http://localhost:8501
```

## Tests

```powershell
uv run python -m unittest discover -s tests -v
```

## Layout

- `app.py` — Streamlit UI (sidebar rating-model config, spectrum view, history)
- `src/spectrum_news/` — `config`, `db` (SQLite), `search` (Tavily→DDG, parallel), `sources` (MBFC CSV + Tranco/curated popularity), `analyzer` (OpenRouter strict-JSON + heuristic fallback), `pipeline` (orchestrator)
- `data/mbfc_ratings.csv` — curated outlet ratings (extend via PR)
- `.scratch/spectrum-news/` — spec + tracer tickets (local issue tracker)
- `docs/adr/` — stack, search, source-profile decisions
