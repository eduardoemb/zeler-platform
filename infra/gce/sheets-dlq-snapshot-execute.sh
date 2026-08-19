#!/usr/bin/env bash
set -uo pipefail
umask 077

EXIT_USAGE=2
EXIT_CONFIG=4
EXIT_INTERNAL=70
EXIT_TOKEN_CLEANUP_FAIL=75
TOKEN_DIRECTORY=/var/lib/zeler-platform/sheets-dlq-snapshot
DOCKER_BIN=/usr/bin/docker # SHEETS_DLQ_SNAPSHOT_EXEC_DOCKER_BIN

if [[ "$#" -ne 0 ]]; then
  exit "$EXIT_USAGE"
fi

if [[ "${SHEETS_DLQ_SNAPSHOT_EXEC_SANITIZED:-}" != "1" ]]; then
  if IFS= read -r -t 0.01 _unused_input; then
    exit "$EXIT_USAGE"
  fi
  exec /usr/bin/env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/root \
    DOCKER_HOST=unix:///var/run/docker.sock \
    SHEETS_DLQ_SNAPSHOT_EXEC_SANITIZED=1 \
    "$0"
fi
unset SHEETS_DLQ_SNAPSHOT_EXEC_SANITIZED _unused_input

[[ "$(/usr/bin/id -u)" == "0" ]] || exit "$EXIT_CONFIG"
[[ -d "$TOKEN_DIRECTORY" && ! -L "$TOKEN_DIRECTORY" ]] || exit "$EXIT_CONFIG"
[[ "$(/usr/bin/stat -c '%u:%a:%F' "$TOKEN_DIRECTORY")" == "0:700:directory" ]] || exit "$EXIT_CONFIG"

TOKEN_FILE=$(/usr/bin/mktemp "$TOKEN_DIRECTORY/execute.XXXXXXXX") || exit "$EXIT_INTERNAL"

cleanup() {
  local original_exit=$?
  local cleanup_failed=0

  trap - EXIT HUP INT TERM
  if [[ -n "${TOKEN_FILE:-}" ]]; then
    /bin/rm -f -- "$TOKEN_FILE" >/dev/null 2>&1 || cleanup_failed=1
  fi
  unset TOKEN_FILE TOKEN_SHA256 EXEC_RUN_ID
  unset SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID
  unset SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST
  unset SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE
  if ((original_exit == 0 && cleanup_failed != 0)); then
    exit "$EXIT_TOKEN_CLEANUP_FAIL"
  fi
  exit "$original_exit"
}

trap cleanup EXIT
trap 'exit 143' HUP INT TERM

/usr/bin/openssl rand -out "$TOKEN_FILE" 32 || exit "$EXIT_INTERNAL"
[[ "$(/usr/bin/stat -c '%u:%a:%F:%s' "$TOKEN_FILE")" == "0:600:regular file:32" ]] || exit "$EXIT_CONFIG"
unset TOKEN

EXEC_RUN_ID=$(/usr/bin/openssl rand -hex 16) || exit "$EXIT_INTERNAL"
TOKEN_SHA256=$(/usr/bin/sha256sum "$TOKEN_FILE") || exit "$EXIT_INTERNAL"
TOKEN_SHA256=${TOKEN_SHA256%% *}
SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST=$(printf '%s\n%s\n%s\n%s' \
  "$EXEC_RUN_ID" "$TOKEN_SHA256" zeler.sheets.events.dlq 24 | /usr/bin/sha256sum) || exit "$EXIT_INTERNAL"
SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST=${SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST%% *}
SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID=$EXEC_RUN_ID
SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE=$TOKEN_FILE
export SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID
export SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST
export SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE

for exported_name in $(compgen -e); do
  case "$exported_name" in
    PATH|HOME|DOCKER_HOST|SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID|SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST|SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE) ;;
    *) # shellcheck disable=SC2163
      export -n "$exported_name" ;;
  esac
done

/usr/bin/env -i \
  PATH="$PATH" \
  HOME="$HOME" \
  DOCKER_HOST="$DOCKER_HOST" \
  SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID="$SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID" \
  SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST="$SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST" \
  SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE="$SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE" \
  "$DOCKER_BIN" compose \
  --project-name zeler-platform \
  --project-directory /opt/zeler-platform \
  --file /opt/zeler-platform/docker-compose.yml \
  exec -T --user 0:0 --workdir /app \
  -e SHEETS_DLQ_SNAPSHOT_EXEC_RUN_ID \
  -e SHEETS_DLQ_SNAPSHOT_EXEC_DIGEST \
  -e SHEETS_DLQ_SNAPSHOT_EXEC_TOKEN_FILE \
  sheets-worker /app/.venv/bin/python -m infra.operations.sheets_dlq_snapshot_execute
