#!/usr/bin/env bash
# Back up the compose deployment: Postgres (pg_dump custom format) + every stored object.
#   scripts/backup.sh [out_dir]        default: backups/<timestamp>
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-backups/$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT/objects"
OUT_ABS="$(cd "$OUT" && pwd)"

docker compose exec -T postgres pg_dump -U app -Fc app > "$OUT/db.dump"
docker compose run --rm --no-deps -v "$OUT_ABS/objects:/backup" api python -m app.backup dump /backup
echo "backup written to $OUT ($(du -sh "$OUT" | cut -f1))"
