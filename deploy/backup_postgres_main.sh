#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/tmkd/Desktop/tmkd/FindexHub"
BACKUP_DIR="$PROJECT_DIR/deploy/backups"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/findex_main_${TS}.sql.gz"

mkdir -p "$BACKUP_DIR"

docker exec findex-prod-postgres-1 \
  pg_dump -U findex_user -d findex \
  | gzip > "$OUT"

find "$BACKUP_DIR" -type f -name "findex_main_*.sql.gz" -mtime +14 -delete

echo "backup created: $OUT"
