#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh.
#   scripts/restore.sh <backup_dir> [database] [bucket]
# Defaults restore over the live database "app" and bucket from S3_BUCKET; pass a different
# database / bucket to restore side by side (e.g. to verify a backup) without touching live data.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: scripts/restore.sh <backup_dir> [database] [bucket]}"
DB="${2:-app}"
SRC_ABS="$(cd "$SRC" && pwd)"

docker compose exec -T postgres psql -U app -d postgres -qc "CREATE DATABASE \"$DB\"" 2>/dev/null || true
docker compose exec -T postgres pg_restore -U app -d "$DB" --clean --if-exists --no-owner < "$SRC/db.dump"
docker compose run --rm --no-deps ${3:+-e S3_BUCKET="$3"} -v "$SRC_ABS/objects:/backup:ro" api python -m app.backup restore /backup
echo "restored $SRC into database $DB${3:+, bucket $3}"
