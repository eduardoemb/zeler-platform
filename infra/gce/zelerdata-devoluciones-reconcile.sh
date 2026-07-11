#!/usr/bin/env bash
set -euo pipefail
umask 077

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}
DATE_BIN=${ZELER_DATE_BIN:-/usr/bin/date}
DOCKER_BIN=${ZELER_DOCKER_BIN:-/usr/bin/docker}
LOGGER_BIN=${ZELER_LOGGER_BIN:-/usr/bin/logger}
MKTEMP_BIN=${ZELER_MKTEMP_BIN:-/usr/bin/mktemp}
PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}
RM_BIN=${ZELER_RM_BIN:-/usr/bin/rm}
TIMEOUT_BIN=${ZELER_TIMEOUT_BIN:-/usr/bin/timeout}
APPROVED_SELLER_ID=82453304
CONFIGURED_SELLER_ID=${ZELERDATA_DEVOLUCIONES_SELLER_ID:-}
SELLER_ID=$APPROVED_SELLER_ID
ACCEPTED_RANGE_START=2026-06-01
ACCEPTED_BASELINE_THROUGH=2026-07-09
RANGE_START=${ZELERDATA_DEVOLUCIONES_RANGE_START:-2026-06-01}
ACCEPTED_THROUGH=${ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH:-2026-07-09}
CAMPAIGN_ID=${ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID:-}
CAMPAIGN_STATE_FILE=${ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE:-/var/lib/zeler-platform/zelerdata-devoluciones-campaign.json}
OUTPUT_FILE=
EVIDENCE_FILE=
EVIDENCE_PUBLISHED=0
FINAL_REASON=runtime_unhandled_failure

cleanup() {
  if [[ -n "$OUTPUT_FILE" || -n "$EVIDENCE_FILE" ]]; then
    "$RM_BIN" -f ${OUTPUT_FILE:+"$OUTPUT_FILE"} ${EVIDENCE_FILE:+"$EVIDENCE_FILE"}
  fi
}

log_event() {
  local priority=$1
  local event=$2
  "$LOGGER_BIN" \
    --priority "$priority" \
    --tag zelerdata-devoluciones-reconcile \
    "event=$event diagnostics=sanitized" || true
}

valid_utc_date() {
  local value=$1
  [[ "$value" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] &&
    [[ "$("$DATE_BIN" -u -d "$value" +%F 2>/dev/null)" == "$value" ]]
}

safe_campaign_id() {
  if [[ "$CAMPAIGN_ID" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
    printf '%s' "$CAMPAIGN_ID"
  else
    printf '%s' invalid-campaign
  fi
}

publish_scheduled_evidence() {
  local evidence_line
  local line_count=0
  local selected_line=
  while IFS= read -r evidence_line; do
    [[ -n "$evidence_line" ]] || continue
    ((line_count += 1))
    selected_line=$evidence_line
  done < "$EVIDENCE_FILE"
  [[ "$line_count" == "1" ]] || return 65
  if ! "$LOGGER_BIN" \
    --priority daemon.info \
    --tag zelerdata-devoluciones-reconcile \
    "event=scheduled_run evidence=$selected_line"; then
    return 72
  fi
  printf '%s\n' "$selected_line"
  EVIDENCE_PUBLISHED=1
}

fallback_evidence_line() {
  local reason=$1
  local duration=${2:-0}
  local campaign
  campaign=$(safe_campaign_id)
  printf '%s\n' \
    "{\"campaign_disqualified\":true,\"campaign_id\":\"$campaign\",\"counters\":{\"O\":null,\"P\":null,\"R\":null,\"T\":null},\"duration_seconds\":$duration,\"event\":\"zelerdata_devoluciones_scheduled_run\",\"outcome\":\"failure\",\"physical_attempts\":null,\"read_model_fingerprint_hash\":null,\"reason\":\"$reason\",\"reset_required\":true,\"schema_version\":1,\"source_fingerprint_hash\":null}"
}

write_fallback_evidence() {
  local reason=$1
  local duration=${2:-0}
  fallback_evidence_line "$reason" "$duration" > "$EVIDENCE_FILE"
}

persist_campaign_state() {
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.operations.zelerdata_campaign_state record \
    --state-file "$CAMPAIGN_STATE_FILE" \
    --evidence-file "$EVIDENCE_FILE" 2>/dev/null
}

persist_campaign_state_line() {
  local evidence_line=$1
  printf '%s\n' "$evidence_line" | PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.operations.zelerdata_campaign_state record-stdin \
    --state-file "$CAMPAIGN_STATE_FILE" 2>/dev/null
}

emit_minimal_disqualification() {
  local reason=$1
  local duration=${2:-0}
  local use_journal=${3:-1}
  local evidence_line
  evidence_line=$(fallback_evidence_line "$reason" "$duration")
  persist_campaign_state_line "$evidence_line" >/dev/null 2>&1 || true
  if [[ "$use_journal" == "1" ]]; then
    if ! "$LOGGER_BIN" \
      --priority daemon.info \
      --tag zelerdata-devoluciones-reconcile \
      "event=scheduled_run evidence=$evidence_line"; then
      evidence_line=$(fallback_evidence_line journald_failed "$duration")
      persist_campaign_state_line "$evidence_line" >/dev/null 2>&1 || true
    fi
  fi
  printf '%s\n' "$evidence_line"
  EVIDENCE_PUBLISHED=1
}

finalize() {
  local status=$?
  trap - EXIT
  set +e
  if [[ "$EVIDENCE_PUBLISHED" == "0" && -n "$EVIDENCE_FILE" ]]; then
    write_fallback_evidence "$FINAL_REASON" 0
    persist_campaign_state >/dev/null 2>&1 || true
    if ! publish_scheduled_evidence; then
      emit_minimal_disqualification journald_failed 0 0
    fi
  fi
  cleanup
  return "$status"
}

trap finalize EXIT
if ! OUTPUT_FILE=$("$MKTEMP_BIN"); then
  FINAL_REASON=mktemp_failed
  emit_minimal_disqualification mktemp_failed 0
  exit 73
fi
if ! EVIDENCE_FILE=$("$MKTEMP_BIN"); then
  FINAL_REASON=mktemp_failed
  emit_minimal_disqualification mktemp_failed 0
  exit 73
fi
CLOSED_DATE_TO=$("$DATE_BIN" -u -d "yesterday" +%F)

if [[ "$CONFIGURED_SELLER_ID" != "$APPROVED_SELLER_ID" ]]; then
  FINAL_REASON=runtime_seller_invalid
  log_event daemon.err runtime_seller_invalid
  exit 64
fi

if ! valid_utc_date "$RANGE_START" ||
  ! valid_utc_date "$ACCEPTED_THROUGH" ||
  [[ "$RANGE_START" > "$ACCEPTED_THROUGH" ]] ||
  [[ "$RANGE_START" > "$ACCEPTED_RANGE_START" ]] ||
  [[ "$ACCEPTED_THROUGH" < "$ACCEPTED_BASELINE_THROUGH" ]] ||
  [[ "$ACCEPTED_THROUGH" > "$CLOSED_DATE_TO" ]] ||
  [[ ! "$CAMPAIGN_ID" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
  FINAL_REASON=runtime_config_invalid
  log_event daemon.err runtime_config_invalid
  exit 64
fi

if [[ ! -d "$PLATFORM_ROOT" || ! -f "$COMPOSE_FILE" ]]; then
  FINAL_REASON=runtime_path_missing
  log_event daemon.err runtime_path_missing
  exit 66
fi

cd "$PLATFORM_ROOT"
started_epoch=$("$DATE_BIN" +%s)

if "$TIMEOUT_BIN" --signal=TERM --kill-after=30s 175s \
  "$DOCKER_BIN" compose --file "$COMPOSE_FILE" exec -T --workdir /app \
    --env "ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID=$CAMPAIGN_ID" sheets-worker \
    /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
    --seller-id "$SELLER_ID" \
    --date-from "$RANGE_START" \
    --date-to "$CLOSED_DATE_TO" \
    --read-model devoluciones \
    --write \
    --confirm-approved-runtime \
    --confirm-production-write > "$OUTPUT_FILE" 2>&1; then
  process_status=0
else
  process_status=$?
fi

finished_epoch=$("$DATE_BIN" +%s)
wrapper_duration=$((finished_epoch - started_epoch))
if PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
  -m infra.operations.zelerdata_scheduled_evidence \
  --input "$OUTPUT_FILE" \
  --campaign-id "$CAMPAIGN_ID" \
  --process-status "$process_status" \
  --wrapper-duration-seconds "$wrapper_duration" > "$EVIDENCE_FILE" 2>/dev/null; then
  evidence_status=0
else
  evidence_status=$?
fi

if [[ ! -s "$EVIDENCE_FILE" ]]; then
  write_fallback_evidence evidence_invalid "$wrapper_duration"
  evidence_status=65
fi

if persist_campaign_state; then
  campaign_status=0
else
  campaign_status=$?
fi
if [[ "$campaign_status" != "0" ]]; then
  write_fallback_evidence state_writer_failed "$wrapper_duration"
  evidence_status=$campaign_status
fi

if publish_scheduled_evidence; then
  publish_status=0
else
  publish_status=$?
fi
if [[ "$publish_status" != "0" ]]; then
  emit_minimal_disqualification journald_failed "$wrapper_duration" 0
  evidence_status=$publish_status
fi

if [[ "$process_status" == "0" && "$evidence_status" == "0" ]]; then
  FINAL_REASON=reconciliation_succeeded
  log_event daemon.info reconciliation_succeeded
  exit 0
fi

FINAL_REASON=reconciliation_failed
log_event daemon.err reconciliation_failed
if [[ "$evidence_status" != "0" ]]; then
  exit "$evidence_status"
fi
exit "$process_status"
