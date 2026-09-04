#!/usr/bin/env sh
set -eu
umask 077
ENV_FILE="${ENV_FILE:-.env.production}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-backups/aastha_${STAMP}.dump}"
mkdir -p "$(dirname "$OUT")"
if [ ! -f "$ENV_FILE" ]; then echo "Missing $ENV_FILE" >&2; exit 1; fi
set -a; . "$ENV_FILE"; set +a
printf 'Creating PostgreSQL backup: %s\n' "$OUT"
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT"
test -s "$OUT"
chmod 600 "$OUT"
printf 'Verifying backup catalog...\n'
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T db \
  pg_restore -l "/backups/$(basename "$OUT")" >/dev/null
printf 'Backup verified: %s\n' "$OUT"
