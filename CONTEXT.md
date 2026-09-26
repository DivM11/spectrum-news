# CONTEXT.md — Spectrum News glossary

Ubiquitous language for the AI fact-checking and bias-highlighting service.
Implementation details live in specs/ADRs, never here.

## Glossary

- **Topic**: free-text subject the user wants checked (e.g. "central bank rate hike"). Contrasts with Category (a fixed bucket).
- **Category**: primary fixed bucket: Politics, Science, Tech, Economics, Climate/Disasters. Selected via UI, drives default queries.
- **Country filter**: secondary facet (e.g. US, IN, UK). Narrows Topic search, never replaces Category.
- **Search run**: one parallel fan-out of web queries for a (Topic, Category, Country) triple. Produces raw Articles.
- **Article**: a single fetched news item: URL, outlet name, title, snippet/content, published date. Raw input to analysis.
- **Outlet / Source**: the publisher of an Article (e.g. bbc.com). Has Source Profile data independent of any single Article.
- **Source Profile**: outlet-level facts: MBFC factual-reporting rating, MBFC bias rating, popularity rank. Cached, not LLM-generated.
- **MBFC rating**: Media Bias/Fact Check factuality + bias label for an Outlet (e.g. High factuality, Left-Center bias). Curated dataset, looked up by domain.
- **Popularity rank**: trust-weighted traffic rank for an Outlet (lower = more visited). Derived from Tranco-style list + curated fallback.
- **Article Analysis**: per-Article LLM output: factuality score (0-100), bias label + bias score (-3..+3), summary, key claims, verdict.
- **Factuality score**: 0-100 LLM estimate of how well an Article's verifiable claims hold up. Not a truth certificate.
- **Bias label / Bias score**: Left (-3) … Center (0) … Right (+3) lean of an Article's framing, plus loaded-language flags. Distinct from Outlet's MBFC bias.
- **Spectrum view**: UI comparison of Article Analyses for one Search run, grouped/ordered by Bias score so left/center/right coverage is visible at a glance.
- **Rating model**: the OpenRouter model ID used for Article Analysis. User-configurable from the sidebar (e.g. `google/gemini-2.5-flash-lite`).
- **Evidence set**: the collection of Articles + Source Profiles for one Search run that the Spectrum view compares.
