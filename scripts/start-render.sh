#!/bin/sh
# Render free plan start command: no pre-deploy step, so migrate first, then serve.
# (A script because Render passes dockerCommand quotes through literally.)
set -e
alembic upgrade head
export PUBLIC_URL="${PUBLIC_URL:-$RENDER_EXTERNAL_URL}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips='*'
