#!/bin/sh
# Back up the contact-message database from the running container.
# Usage:   sh scripts/backup.sh [backup-dir]       (default: ./backups, keeps 30 days)
# Cron:    0 3 * * * cd /path/to/papiamentu-pa-bo && sh scripts/backup.sh >> backups/backup.log 2>&1
set -eu
export MSYS_NO_PATHCONV=1  # stop Git Bash on Windows from rewriting container paths

DIR="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y-%m-%d_%H%M)"
TMP=/data/backup-tmp.sqlite3
mkdir -p "$DIR"

docker compose exec -T web flask backup "$TMP"
docker compose cp "web:$TMP" "$DIR/papiamentu-$STAMP.sqlite3"
docker compose exec -T web rm -f "$TMP"

find "$DIR" -name 'papiamentu-*.sqlite3' -mtime +"$KEEP_DAYS" -delete
echo "$(date +%Y-%m-%dT%H:%M:%S) backup -> $DIR/papiamentu-$STAMP.sqlite3"
