#!/usr/bin/env sh
set -eu
ENV_FILE="${ENV_FILE:-.env.production}"
python scripts/preflight.py --env-file "$ENV_FILE"
set -a; . "$ENV_FILE"; set +a
COMPOSE="docker compose --env-file $ENV_FILE -f docker-compose.prod.yml"
$COMPOSE build
$COMPOSE up -d db
printf 'Waiting for PostgreSQL readiness...\n'
i=0
until $COMPOSE exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -lt 30 ] || { echo "Database did not become ready" >&2; exit 1; }; sleep 2
done
# Back up only when the CRM schema already exists (upgrade/redeploy path).
EXISTING="$($COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT to_regclass('core.organizations') IS NOT NULL" 2>/dev/null || true)"
if [ "$EXISTING" = "t" ]; then
  printf 'Existing CRM database detected; taking pre-migration backup.\n'
  ENV_FILE="$ENV_FILE" scripts/backup.sh
else
  printf 'Fresh database detected; validating one-time bootstrap credentials.\n'
  python scripts/preflight.py --env-file "$ENV_FILE" --require-bootstrap
fi
$COMPOSE up -d
$COMPOSE ps
printf '\nDeployment containers started. Run the smoke test before staff access:\n'
printf 'python scripts/smoke_uat.py --base-url http://localhost:%s --username <uat-user> --password <password>\n' "${CRM_HTTP_PORT:-8080}"
