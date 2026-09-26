# ADR 0004 — Search via OpenRouter web-search model, DuckDuckGo fallback

Date: 2026-09-26
Status: accepted
Supersedes: 0002 (Tavily primary removed — one fewer vendor, one fewer key).

## Context

Search runs need live web results. Previously Tavily was the primary with DDG
fallback, but operating two keyed providers adds cost and key management.
OpenRouter now offers the `openrouter:web_search` server tool (the old
`plugins: [{id: "web"}]` / `:online` variants are deprecated), which gives any
tool-calling model grounded, cited search — so the same OpenRouter key and
model family can do both gathering and analysis.

## Decision

- Primary: **OpenRouter chat completions** with
  `tools: [{type: "openrouter:web_search", parameters: {max_results, max_total_results}}]`,
  using a dedicated **Search model** (`SEARCH_MODEL`, default `openai/gpt-4o-mini`),
  prompted to return gathered articles as strict JSON (`url, title, snippet, published`).
- The Search model requires tool-calling support; sidebar + env configurable
  independently of the Rating model.
- Fallback: **DuckDuckGo** (`ddgs`, keyless) when no OpenRouter key or on search failure.
- Keep **parallel fan-out** (3 query variants, `ThreadPoolExecutor`) + normalize/dedupe.

## Consequences

- Single provider/key for search + analysis; no Tavily dependency or key.
- Search quality now depends on the chosen Search model's tool use + JSON discipline —
  lenient parsing + DDG fallback absorb failures.
- Server-tool search calls are billed per engine use; `max_total_results` caps cost.
