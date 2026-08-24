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
PUBLIC_EVIDENCE_FILE=
PRIVATE_SAMPLE_FILE=
EVIDENCE_PUBLISHED=0
FINAL_STATUS_CLASS=evidence_invalid

cleanup() {
  if [[ -n "$OUTPUT_FILE" || -n "$PUBLIC_EVIDENCE_FILE" || -n "$PRIVATE_SAMPLE_FILE" ]]; then
    "$RM_BIN" -f \
      ${OUTPUT_FILE:+"$OUTPUT_FILE"} \
      ${PUBLIC_EVIDENCE_FILE:+"$PUBLIC_EVIDENCE_FILE"} \
      ${PRIVATE_SAMPLE_FILE:+"$PRIVATE_SAMPLE_FILE"}
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
  done < "$PUBLIC_EVIDENCE_FILE"
  [[ "$line_count" == "1" ]] || return 65
  if ! "$LOGGER_BIN" \
    --priority daemon.info \
    --tag zelerdata-devoluciones-reconcile \
    "event=scheduled_run evidence=$selected_line"; then
    write_public_evidence publication_failed
    local disqualification_status=0
    persist_direct_failure 0 >/dev/null 2>&1 || disqualification_status=$?
    selected_line=$(<"$PUBLIC_EVIDENCE_FILE")
    printf '%s\n' "$selected_line"
    EVIDENCE_PUBLISHED=1
    [[ "$disqualification_status" == "0" ]] || return "$disqualification_status"
    return 72
  fi
  printf '%s\n' "$selected_line"
  EVIDENCE_PUBLISHED=1
}

public_evidence_line() {
  local status_class=$1
  printf '%s\n' \
    "{\"stage\":\"scheduled\",\"status_class\":\"$status_class\",\"counters\":{}}"
}

private_failure_line() {
  local duration=${1:-0}
  local campaign
  campaign=$(safe_campaign_id)
  printf '%s\n' \
    "{\"campaign_disqualified\":true,\"campaign_id\":\"$campaign\",\"duration_seconds\":$duration,\"outcome\":\"failure\",\"read_model_fingerprint_hash\":null,\"source_fingerprint_hash\":null}"
}

write_public_evidence() {
  public_evidence_line "$1" > "$PUBLIC_EVIDENCE_FILE"
}

write_private_failure() {
  private_failure_line "${1:-0}" > "$PRIVATE_SAMPLE_FILE"
}

persist_campaign_state() {
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.operations.zelerdata_campaign_state record \
    --state-file "$CAMPAIGN_STATE_FILE" \
    --evidence-file "$PRIVATE_SAMPLE_FILE" 2>/dev/null
}

persist_direct_failure() {
  private_failure_line "${1:-0}" | PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.operations.zelerdata_campaign_state record-stdin \
    --state-file "$CAMPAIGN_STATE_FILE" 2>/dev/null
}

emit_direct_public() {
  local evidence_line
  evidence_line=$(public_evidence_line "$1")
  "$LOGGER_BIN" \
    --priority daemon.info \
    --tag zelerdata-devoluciones-reconcile \
    "event=scheduled_run evidence=$evidence_line" >/dev/null 2>&1 || true
  printf '%s\n' "$evidence_line"
  EVIDENCE_PUBLISHED=1
}

finalize() {
  local status=$?
  trap - EXIT
  set +e
  if [[ "$EVIDENCE_PUBLISHED" == "0" ]]; then
    if [[ -n "$PUBLIC_EVIDENCE_FILE" ]]; then
      write_public_evidence "$FINAL_STATUS_CLASS"
      if [[ -n "$PRIVATE_SAMPLE_FILE" ]]; then
        write_private_failure 0
        persist_campaign_state >/dev/null 2>&1 || true
      fi
      publish_scheduled_evidence || true
    else
      emit_direct_public "$FINAL_STATUS_CLASS"
    fi
  fi
  cleanup
  return "$status"
}

trap finalize EXIT
if ! OUTPUT_FILE=$("$MKTEMP_BIN"); then
  FINAL_STATUS_CLASS=tooling_failed
  persist_direct_failure 0 >/dev/null 2>&1 || exit $?
  emit_direct_public tooling_failed
  exit 73
fi
if ! PUBLIC_EVIDENCE_FILE=$("$MKTEMP_BIN"); then
  FINAL_STATUS_CLASS=tooling_failed
  persist_direct_failure 0 >/dev/null 2>&1 || exit $?
  emit_direct_public tooling_failed
  exit 73
fi
if ! PRIVATE_SAMPLE_FILE=$("$MKTEMP_BIN"); then
  FINAL_STATUS_CLASS=tooling_failed
  persist_direct_failure 0 >/dev/null 2>&1 || exit $?
  write_public_evidence tooling_failed
  publish_scheduled_evidence || true
  exit 73
fi
CLOSED_DATE_TO=$("$DATE_BIN" -u -d "yesterday" +%F)

if [[ "$CONFIGURED_SELLER_ID" != "$APPROVED_SELLER_ID" ]]; then
  FINAL_STATUS_CLASS=evidence_invalid
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
  FINAL_STATUS_CLASS=evidence_invalid
  log_event daemon.err runtime_config_invalid
  exit 64
fi

if [[ ! -d "$PLATFORM_ROOT" || ! -f "$COMPOSE_FILE" ]]; then
  FINAL_STATUS_CLASS=process_failed
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
    --confirm-production-write \
    --private-scheduled-transport > "$OUTPUT_FILE" 2>&1; then
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
  --wrapper-duration-seconds "$wrapper_duration" \
  --private-output "$PRIVATE_SAMPLE_FILE" > "$PUBLIC_EVIDENCE_FILE" 2>/dev/null; then
  evidence_status=0
else
  evidence_status=$?
fi

if [[ ! -s "$PUBLIC_EVIDENCE_FILE" || ! -s "$PRIVATE_SAMPLE_FILE" ]]; then
  write_public_evidence evidence_invalid
  write_private_failure "$wrapper_duration"
  evidence_status=65
fi

if persist_campaign_state; then
  campaign_status=0
else
  campaign_status=$?
fi
if [[ "$campaign_status" != "0" ]]; then
  write_public_evidence state_failed
  evidence_status=$campaign_status
fi

if publish_scheduled_evidence; then
  publish_status=0
else
  publish_status=$?
fi
if [[ "$publish_status" != "0" ]]; then
  evidence_status=$publish_status
fi

if [[ "$process_status" == "0" && "$evidence_status" == "0" ]]; then
  FINAL_STATUS_CLASS=success
  log_event daemon.info reconciliation_succeeded
  exit 0
fi

FINAL_STATUS_CLASS=process_failed
log_event daemon.err reconciliation_failed
if [[ "$evidence_status" != "0" ]]; then
  exit "$evidence_status"
fi
exit "$process_status"
