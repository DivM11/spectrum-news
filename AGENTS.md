# Agent skills

### Issue tracker

Local markdown tracker under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Secrets -- .env is off-limits

NEVER read, touch, edit, cat, grep, glob, or otherwise access `.env` (or any `.env.*`
file except `.env.example`). It holds the real API key (`OPENROUTER_API_KEY`). Use `.env.example` for schema/defaults. Exclude `.env` from
all searches (e.g. grep with `--exclude-dot-env` equivalents / never pass it to
Read/Grep/Glob). If you need a value, ask the user or read process env; do not
echo secrets to output, logs, or commits.

### Domain docs

Single-context (`CONTEXT.md` + `docs/adr/`). See `docs/agents/domain.md`.
