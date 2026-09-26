# Domain docs — single context

Single-context layout:

- `CONTEXT.md` at repo root: glossary only, no implementation details.
- `docs/adr/` at repo root: Architecture Decision Records for hard-to-reverse, surprising, tradeoff decisions.

Consumer rules:

- Read `CONTEXT.md` before writing specs, tickets, or code; use its canonical terms.
- Respect ADRs in the area you touch; do not contradict them without a new ADR.
- Update `CONTEXT.md` inline when a term is resolved during design.
- Offer ADRs sparingly (hard-to-reverse + surprising + real tradeoff).
