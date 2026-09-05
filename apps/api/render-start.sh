#!/bin/sh
set -eu

alembic upgrade head
python -m app.seed
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --workers "${API_WORKERS:-1}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
