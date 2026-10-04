# ADR 0006 — v0.1 UI/design choices (grilled 2026-09-26)

Date: 2026-09-26
Status: accepted

Grilled with the user (`grill-with-docs`); alternatives considered and rejected noted.

## Decision

1. **Cache warming is lazy, not eager.** A "Load USA defaults" button warms the
   cache on explicit click. Rejected: warming all 5 categories at startup
   (slow boot + surprise API cost on every deploy/restart).
2. **Default prompts are fixed chips, not editable text.** One click per
   Category fills the Topic input with a curated USA-focused prompt.
   Rejected: editable preset text (more flexibility, but chips are faster and
   keep cache-hit rates high since queries stay canonical).
3. **Outlet filter is an allowlist with an explicit `All` default.** Empty
   mental model avoided: `All` selected = unrestricted; picking outlets
   restricts the Search run via the `allowed_domains` web-search parameter.
   Rejected: blocklist (harder to reason about, weaker cache keys).
4. **Native widgets + tooltips, not custom cards.** Keep `st.metric` (with
   `help=` hover text for factuality/bias/MBFC/popularity) and fix the
   oversized-MBFC complaint with pastel-minimal CSS that shrinks metric type.
   Rejected: full custom HTML cards (prettier, but brittle selectors and more
   code to maintain for v0.1).

## Consequences

- Cache keys now include the outlet allowlist (same query, different outlets
  = different entries).
- Country default becomes USA to match the default prompts.
