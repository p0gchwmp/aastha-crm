#!/usr/bin/env sh
set -eu
ENV_FILE="${ENV_FILE:-.env.production}"
DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -s "$DUMP" ]; then echo "Usage: $0 backups/file.dump" >&2; exit 2; fi
case "$DUMP" in backups/*) ;; *) echo "Restore verification expects a dump under backups/ (mounted into the DB container)." >&2; exit 2;; esac
set -a; . "$ENV_FILE"; set +a
COMPOSE="docker compose --env-file $ENV_FILE -f docker-compose.prod.yml"
TEST_DB="aastha_restore_verify_$(date -u +%Y%m%d%H%M%S)"
cleanup(){ $COMPOSE exec -T db dropdb -U "$POSTGRES_USER" --if-exists "$TEST_DB" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
printf 'Creating temporary restore database: %s\n' "$TEST_DB"
$COMPOSE exec -T db createdb -U "$POSTGRES_USER" "$TEST_DB"
$COMPOSE exec -T db pg_restore -U "$POSTGRES_USER" -d "$TEST_DB" --no-owner "/backups/$(basename "$DUMP")"
ORG_COUNT="$($COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$TEST_DB" -Atqc 'SELECT count(*) FROM core.organizations')"
ALEMBIC="$($COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$TEST_DB" -Atqc 'SELECT version_num FROM alembic_version')"
printf 'Restore verification PASSED: organizations=%s, alembic=%s\n' "$ORG_COUNT" "$ALEMBIC"
