#!/usr/bin/env sh
set -eu
ENV_FILE="${ENV_FILE:-.env.production}"
DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -s "$DUMP" ]; then echo "Usage: $0 backups/file.dump" >&2; exit 2; fi
if [ "${CONFIRM_RESTORE:-}" != "YES_RESTORE_AASTHA" ]; then
  echo "Restore blocked. Set CONFIRM_RESTORE=YES_RESTORE_AASTHA after confirming a current backup exists." >&2
  exit 3
fi
set -a; . "$ENV_FILE"; set +a
printf 'Restoring %s into %s...\n' "$DUMP" "$POSTGRES_DB"
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T db \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < "$DUMP"
printf 'Restore complete. Run health/UAT checks before reopening clinic access.\n'
