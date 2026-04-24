#!/usr/bin/env bash
set -euo pipefail

# zeler-platform Mongo daily backup → GCS
# Deployed to Eduardo's on-prem server; runs via cron per D13.
# See infra/mongo/backup/README.md for install instructions.

: "${MONGO_URI:?MONGO_URI is required}"
: "${GCS_BUCKET:?GCS_BUCKET is required}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

DATE_DIR="$(date -u +%Y%m%d)"
TIMESTAMP="$(date -u +%H%M%S)"
OBJECT_PATH="gs://${GCS_BUCKET}/mongo/${DATE_DIR}/backup-${TIMESTAMP}.archive.gz"

echo "[mongodump_cron] Starting backup → ${OBJECT_PATH}"

mongodump --uri="${MONGO_URI}" --archive --gzip \
  | gsutil cp - "${OBJECT_PATH}"

echo "[mongodump_cron] Upload complete. Pruning older than ${RETENTION_DAYS} days."

# Retention cleanup: list objects under mongo/ older than RETENTION_DAYS and delete.
# Uses gsutil ls -l output; parses date column. Simple and robust for our volume.
CUTOFF_EPOCH="$(date -u -d "${RETENTION_DAYS} days ago" +%s 2>/dev/null || date -u -v-"${RETENTION_DAYS}"d +%s)"

gsutil ls -l "gs://${GCS_BUCKET}/mongo/**" 2>/dev/null \
  | awk 'NF>=3 && $1 ~ /^[0-9]+$/ { print $2, $3 }' \
  | while read -r iso_date object; do
      obj_epoch="$(date -u -d "${iso_date}" +%s 2>/dev/null || true)"
      if [ -n "${obj_epoch}" ] && [ "${obj_epoch}" -lt "${CUTOFF_EPOCH}" ]; then
        echo "[mongodump_cron] Deleting aged object: ${object}"
        gsutil rm "${object}" || echo "[mongodump_cron] WARN: failed to delete ${object}"
      fi
    done

echo "[mongodump_cron] Done."
