# ADR 0002 — Search providers: Tavily primary, DuckDuckGo fallback, parallel fan-out

Date: 2026-09-26
Status: superseded by 0004 on 2026-09-26 (Tavily dropped; OpenRouter web-search model is the primary).

## Context

Search run must gather diverse outlets quickly. Options: Tavily (AI-optimized), Serper/Brave (Google-like, keyed), DuckDuckGo Instant Answer (keyless but thin), direct RSS.

## Decision

- Primary: **Tavily** (`TAVILY_API_KEY`) — search + extract, good snippets.
- Fallback: **DuckDuckGo** (no key, `ddgs` package) when Tavily key missing or fails.
- **Parallel fan-out**: 3 query variants per (Topic, Category, Country) executed concurrently via `ThreadPoolExecutor`.
- Normalize to common `Article` dict; dedupe by URL.

## Consequences

- Works keyless out of the box (DDG), upgrades with Tavily key.
- DDG snippets are shorter — analyzer must tolerate thin content.
- Parallelism bounded (max 3-6 workers) to respect rate limits.
