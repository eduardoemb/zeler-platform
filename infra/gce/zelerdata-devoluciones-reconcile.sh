#!/usr/bin/env bash
set -euo pipefail
umask 077

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}
DOCKER_BIN=${ZELER_DOCKER_BIN:-/usr/bin/docker}
LOGGER_BIN=${ZELER_LOGGER_BIN:-/usr/bin/logger}
TIMEOUT_BIN=${ZELER_TIMEOUT_BIN:-/usr/bin/timeout}
RUN_ID=${ZELERDATA_DEVOLUCIONES_RUN_ID:-}

log_failure() {
  "$LOGGER_BIN" \
    --priority daemon.err \
    --tag zelerdata-devoluciones-reconcile \
    "event=$1 diagnostics=sanitized" || true
}

if [[ ! "$RUN_ID" =~ ^[0-9a-f]{64}$ ]]; then
  log_failure quota_run_authority_invalid
  exit 64
fi

if [[ ! -d "$PLATFORM_ROOT" || ! -f "$COMPOSE_FILE" ]]; then
  log_failure runtime_path_missing
  exit 66
fi

cd "$PLATFORM_ROOT"
exec "$TIMEOUT_BIN" --signal=TERM --kill-after=30s 175s \
  "$DOCKER_BIN" compose --file "$COMPOSE_FILE" exec -T --workdir /app \
  sheets-worker /app/.venv/bin/python \
  -m infra.operations.devoluciones_quota_advance \
  --run-id "$RUN_ID"
