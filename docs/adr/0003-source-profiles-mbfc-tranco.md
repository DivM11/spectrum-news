# ADR 0003 — Source profiles: curated MBFC CSV + Tranco-style popularity

Date: 2026-09-26
Status: accepted

## Context

Need per-outlet MBFC factuality/bias + popularity that is trusted and consistent. MBFC has no official API; popularity APIs (SimilarWeb/Alexa) are keyed/commercial.

## Decision

- **MBFC**: curated `data/mbfc_ratings.csv` (domain, factuality, bias) seeded from public MBFC labels for ~40 major outlets; exact-domain + registrable-domain lookup; `Unknown` fallback. Documented refresh path (manual PR).
- **Popularity**: Tranco-style rank via optional `data/tranco.csv` (`domain,rank`); curated fallback scores in `sources.py` when file absent. Lower rank = more visited.
- Both lookups are pure functions, no network at request time.

## Consequences

- Consistent, offline, testable. Coverage limited to curated list — unknown outlets degrade gracefully to Unknown/mid-rank.
- Future: swap in full Tranco dump or MBFC scraper behind same interface.
