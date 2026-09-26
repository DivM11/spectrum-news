# ADR 0005 — Default models: Gemini Flash-Lite for rating, DeepSeek Flash for search

Date: 2026-09-26
Status: accepted

## Context

`gpt-4o-mini` ($0.15/$0.60 per 1M) was the default for both roles, and the
`anthropic/claude-3.5-haiku` sidebar preset no longer exists on OpenRouter.
Live pricing (OpenRouter `/models`, 458 models) shows equal-or-better
capability at 2-6x lower cost. The two roles need different strengths:
rating needs judgment + strict JSON; search needs tool calling + extraction.

## Decision

- Rating default: **`google/gemini-2.5-flash-lite`** ($0.10/$0.40, 1M ctx) —
  strongest cheap instruction/JSON discipline for bias/factuality analysis.
- Search default: **`deepseek/deepseek-v4-flash`** ($0.05/$0.09, 1M ctx) —
  cheapest model with proven tool-use quality; search is extract-and-list,
  not judgment, so the judgment premium is wasted there.
- Rejected the ultra-cheap tier (`mistral-nemo`, `gpt-oss-20b`, 8b Llamas,
  ~$0.02/1M): weak JSON/tool discipline risks empty article lists and sloppy
  bias labels — a visible failure of the app's core promise.
- Presets: rating adds `claude-haiku-4.5` (premium option, replaces the dead
  `claude-3.5-haiku` ID); search adds `qwen3.7-flash` (cheapest fallback).

## Consequences

- Estimated ~$0.009 → ~$0.004 per 9-article run; model cost stays negligible
  next to the `web_search` tool execution fee (engine-dependent, model-invariant).
- Real validation is behavioral: run the same topic under two rating models
  (the cache makes this cheap) and compare spectrum outputs before locking in.
