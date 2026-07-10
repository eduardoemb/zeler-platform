#!/usr/bin/env bash
set -euo pipefail

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}

cd "$PLATFORM_ROOT"

run_topology() {
  /usr/bin/docker compose --file "$COMPOSE_FILE" run --rm --no-deps -T \
    --user 0:0 \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --entrypoint /app/.venv/bin/python \
    sheets-worker -m infra.rabbitmq.sheets_devoluciones_topology "$@"
}

command=${1:-}
if [[ "$command" == "bind-claims" && " $* " == *" --execute "* ]]; then
  set +e
  run_topology "$@"
  status=$?
  set -e
  if (( status != 0 )); then
    run_topology rollback --execute --failure-triggered || true
  fi
  exit "$status"
fi

run_topology "$@"
