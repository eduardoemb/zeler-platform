#!/usr/bin/env bash
set -euo pipefail
umask 077

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}
APPROVED_SELLER_ID=82453304
CONFIGURED_SELLER_ID=${ZELERDATA_DEVOLUCIONES_SELLER_ID:-}
SELLER_ID=$APPROVED_SELLER_ID
ACCEPTED_RANGE_START=2026-06-01
ACCEPTED_BASELINE_THROUGH=2026-07-09
RANGE_START=${ZELERDATA_DEVOLUCIONES_RANGE_START:-2026-06-01}
ACCEPTED_THROUGH=${ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH:-2026-07-09}
CLOSED_DATE_TO=$(/usr/bin/date -u -d "yesterday" +%F)
OUTPUT_FILE=$(/usr/bin/mktemp)
MAX_ATTEMPTS=2

cleanup() {
  /usr/bin/rm -f "$OUTPUT_FILE"
}

log_event() {
  local priority=$1
  local event=$2
  /usr/bin/logger \
    --priority "$priority" \
    --tag zelerdata-devoluciones-reconcile \
    "event=$event diagnostics=sanitized"
}

valid_utc_date() {
  local value=$1
  [[ "$value" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] &&
    [[ "$(/usr/bin/date -u -d "$value" +%F 2>/dev/null)" == "$value" ]]
}

trap cleanup EXIT

if [[ "$CONFIGURED_SELLER_ID" != "$APPROVED_SELLER_ID" ]]; then
  log_event daemon.err runtime_seller_invalid
  exit 64
fi

if ! valid_utc_date "$RANGE_START" ||
  ! valid_utc_date "$ACCEPTED_THROUGH" ||
  [[ "$RANGE_START" > "$ACCEPTED_THROUGH" ]] ||
  [[ "$RANGE_START" > "$ACCEPTED_RANGE_START" ]] ||
  [[ "$ACCEPTED_THROUGH" < "$ACCEPTED_BASELINE_THROUGH" ]] ||
  [[ "$ACCEPTED_THROUGH" > "$CLOSED_DATE_TO" ]]; then
  log_event daemon.err runtime_config_invalid
  exit 64
fi

if [[ ! -d "$PLATFORM_ROOT" || ! -f "$COMPOSE_FILE" ]]; then
  log_event daemon.err runtime_path_missing
  exit 66
fi

cd "$PLATFORM_ROOT"

attempt=1
while ((attempt <= MAX_ATTEMPTS)); do
  if /usr/bin/timeout --signal=TERM --kill-after=30s 3m \
    /usr/bin/docker compose --file "$COMPOSE_FILE" exec -T --workdir /app sheets-worker \
      /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
      --seller-id "$SELLER_ID" \
      --date-from "$RANGE_START" \
      --date-to "$CLOSED_DATE_TO" \
      --write \
      --confirm-approved-runtime \
      --confirm-production-write >"$OUTPUT_FILE" 2>&1; then
    log_event daemon.info reconciliation_succeeded
    exit 0
  else
    status=$?
  fi

  if ((attempt == MAX_ATTEMPTS)); then
    log_event daemon.err reconciliation_failed
    exit "$status"
  fi

  log_event daemon.warning reconciliation_retry_scheduled
  /usr/bin/sleep 60
  ((attempt += 1))
done
