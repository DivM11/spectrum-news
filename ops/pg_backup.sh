#!/bin/sh
# Nightly pg_dump loop (runs as the `backup` sidecar). Prunes dumps older than BACKUP_KEEP_DAYS.
set -eu
: "${BACKUP_INTERVAL_SECONDS:=86400}"
: "${BACKUP_KEEP_DAYS:=7}"
mkdir -p /backups

until pg_isready -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" -q; do sleep 2; done

while true; do
  stamp=$(date -u +%F-%H%M%S)
  if pg_dump -Fc -f "/backups/spectrum-${stamp}.dump"; then
    echo "backup ok: spectrum-${stamp}.dump"
  else
    echo "backup FAILED: spectrum-${stamp}.dump" >&2
  fi
  find /backups -name 'spectrum-*.dump' -mtime +"$BACKUP_KEEP_DAYS" -delete || true
  sleep "$BACKUP_INTERVAL_SECONDS"
done
