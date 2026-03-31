#!/usr/bin/env bash
# scripts/s3_backup.sh
# Weekly S3 backup for all JENNI databases.
# Cron: 0 2 * * 0 (Sunday 02:00)
#
# Syncs data/databases/ to a dated path:
#   s3://project-jenni-data/databases/backups/YYYY-MM-DD/
#
# Logs completion or failure to jenni_query_log via scripts/log_backup.py.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_DIR="$PROJECT_DIR/data/databases"
DATESTAMP="$(date +%Y-%m-%d)"
S3_DEST="s3://project-jenni-data/databases/backups/${DATESTAMP}/"
LOG_PY="$PROJECT_DIR/scripts/log_backup.py"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
LOGFILE="$PROJECT_DIR/logs/s3_backup.log"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOGFILE"; }

log "Starting backup → $S3_DEST"

START_S=$(date +%s)
ERROR_MSG=""

aws s3 sync "$DB_DIR/" "$S3_DEST" \
    --exclude "*.db-shm" \
    --exclude "*.db-wal" \
    2>&1 | tee -a "$LOGFILE" \
    || { ERROR_MSG="aws s3 sync failed (exit $?)"; }

END_S=$(date +%s)
LATENCY_MS=$(( (END_S - START_S) * 1000 ))

if [ -z "$ERROR_MSG" ]; then
    log "Backup complete in ${LATENCY_MS}ms"
    "$PYTHON" "$LOG_PY" \
        --status ok \
        --latency "$LATENCY_MS" \
        --dest "$S3_DEST" \
        2>&1 | tee -a "$LOGFILE"
else
    log "Backup FAILED: $ERROR_MSG"
    "$PYTHON" "$LOG_PY" \
        --status failed \
        --latency "$LATENCY_MS" \
        --dest "$S3_DEST" \
        --error "$ERROR_MSG" \
        2>&1 | tee -a "$LOGFILE"
    exit 1
fi
