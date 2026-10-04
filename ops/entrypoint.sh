#!/bin/sh
# Prod entrypoint: migrate, then run the app's command.
set -e
if [ -n "${DATABASE_URL:-}" ]; then
  uv run alembic upgrade head
fi
exec "$@"
