#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}
DOCKER_BIN=${ZELER_DOCKER_BIN:-/usr/bin/docker}
PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}
SYSTEMCTL_BIN=${ZELER_SYSTEMCTL_BIN:-/usr/bin/systemctl}
TOPOLOGY_BIN=${ZELER_TOPOLOGY_BIN:-$PLATFORM_ROOT/zelerdata-devoluciones-topology.sh}
PREFLIGHT_BIN=${ZELER_PREFLIGHT_BIN:-$PLATFORM_ROOT/docker-deploy-preflight.sh}
API_ROLLBACK_REQUESTED=${SHEETS_API_ROLLBACK_REQUESTED:-1}
ROLLBACK_PROOF_FILE=${SHEETS_ROLLBACK_PROOF_FILE:-/var/lib/zeler-platform/sheets-rollback-release-proof.json}
PROHIBITED_OLD_SHEETS_API_DIGEST=sha256:8da8ab2b0b092825e6b3f362ea92e375a52e25a7a3cb78c2af0828844ddb00b6
PRIOR_GATEWAY_IMAGE=${SHEETS_PRIOR_GATEWAY_IMAGE_REF:-}
PRIOR_WORKER_IMAGE=${SHEETS_PRIOR_WORKER_IMAGE_REF:-}
if [[ "$API_ROLLBACK_REQUESTED" == "1" ]]; then
  SELECTED_API_IMAGE=${SHEETS_ROLLBACK_API_IMAGE_REF:-}
  SELECTED_SOURCE_COMMIT=${SHEETS_ROLLBACK_SOURCE_COMMIT:-}
else
  SELECTED_API_IMAGE=${SHEETS_CANDIDATE_API_IMAGE_REF:-}
  SELECTED_SOURCE_COMMIT=${SHEETS_CANDIDATE_SOURCE_COMMIT:-}
fi

override_file=$(mktemp) || exit 1
repo_digests_file=$(mktemp) || { rm -f "$override_file"; exit 1; }
health_file=$(mktemp) || { rm -f "$override_file" "$repo_digests_file"; exit 1; }
FAIL_CLOSED_ACTIVE=0

cleanup() {
  rm -f "$override_file" "$repo_digests_file" "$health_file"
}

fail_closed() {
  local status=${1:-1}
  if [[ "$FAIL_CLOSED_ACTIVE" == "1" ]]; then
    exit "$status"
  fi
  FAIL_CLOSED_ACTIVE=1
  trap - ERR
  set +e
  "$SYSTEMCTL_BIN" disable --now zelerdata-devoluciones-reconcile.timer >/dev/null 2>&1 || true
  "$TOPOLOGY_BIN" rollback --execute --failure-triggered >/dev/null 2>&1 || true
  "$DOCKER_BIN" compose --file "$COMPOSE_FILE" stop sheets-api >/dev/null 2>&1 || true
  echo "ERROR: Sheets rollback failed closed; timer off, readiness stale, claims unbound, API unavailable." >&2
  cleanup
  exit "$status"
}

rollback_error() {
  local status=$?
  fail_closed "$status"
}

trap cleanup EXIT
trap rollback_error ERR

require_image_ref() {
  local value=$1
  [[ "$value" =~ ^[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || fail_closed 1
  [[ "${value##*@}" != "$PROHIBITED_OLD_SHEETS_API_DIGEST" ]] || fail_closed 1
}

"$SYSTEMCTL_BIN" disable --now zelerdata-devoluciones-reconcile.timer || fail_closed $?
"$TOPOLOGY_BIN" rollback --execute --failure-triggered || fail_closed $?

require_image_ref "$SELECTED_API_IMAGE"
require_image_ref "$PRIOR_GATEWAY_IMAGE"
require_image_ref "$PRIOR_WORKER_IMAGE"
[[ "$SELECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail_closed 1

SHEETS_ROLLBACK_PREFLIGHT=1 \
SHEETS_ROLLBACK_API_IMAGE_REF="$SELECTED_API_IMAGE" \
SHEETS_ROLLBACK_SOURCE_COMMIT="$SELECTED_SOURCE_COMMIT" \
SHEETS_ROLLBACK_PROOF_FILE="$ROLLBACK_PROOF_FILE" \
  "$PREFLIGHT_BIN" || fail_closed $?
expected_image_id=$("$DOCKER_BIN" image inspect "$SELECTED_API_IMAGE" --format '{{.Id}}') || fail_closed $?
PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
  verify-release-proof \
  --proof "$ROLLBACK_PROOF_FILE" \
  --image-ref "$SELECTED_API_IMAGE" \
  --image-id "$expected_image_id" \
  --source-commit "$SELECTED_SOURCE_COMMIT" >/dev/null || fail_closed $?

cat > "$override_file" <<YAML
services:
  gateway:
    image: $PRIOR_GATEWAY_IMAGE
  sheets-worker:
    image: $PRIOR_WORKER_IMAGE
  sheets-api:
    image: $SELECTED_API_IMAGE
YAML

"$DOCKER_BIN" compose --file "$COMPOSE_FILE" --file "$override_file" up -d gateway sheets-worker || fail_closed $?
"$DOCKER_BIN" compose --file "$COMPOSE_FILE" --file "$override_file" up -d sheets-api || fail_closed $?
verify_running_api() {
  local container_id expected_image_id container_image_id
  container_id=$("$DOCKER_BIN" compose --file "$COMPOSE_FILE" --file "$override_file" ps -q sheets-api) || fail_closed $?
  [[ -n "$container_id" ]] || fail_closed 1
  expected_image_id=$("$DOCKER_BIN" image inspect "$SELECTED_API_IMAGE" --format '{{.Id}}') || fail_closed $?
  container_image_id=$("$DOCKER_BIN" inspect "$container_id" --format '{{.Image}}') || fail_closed $?
  "$DOCKER_BIN" image inspect "$expected_image_id" --format '{{json .RepoDigests}}' \
    > "$repo_digests_file" || fail_closed $?
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
    verify-running-binding \
    --repo-digests "$repo_digests_file" \
    --image-ref "$SELECTED_API_IMAGE" \
    --container-image-id "$container_image_id" \
    --expected-image-id "$expected_image_id" >/dev/null || fail_closed $?
  "$DOCKER_BIN" compose --file "$COMPOSE_FILE" --file "$override_file" exec -T sheets-api \
    /app/.venv/bin/python -c \
    'import os,urllib.request; port=os.environ.get("PORT","8080"); print(urllib.request.urlopen(f"http://127.0.0.1:{port}/health",timeout=5).read().decode())' \
    > "$health_file" || fail_closed $?
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
    verify-runtime \
    --repo-digests "$repo_digests_file" \
    --health "$health_file" \
    --image-ref "$SELECTED_API_IMAGE" >/dev/null || fail_closed $?
  grep -q 'registry_fingerprint_match' "$health_file" || fail_closed $?
}
verify_running_api
"$DOCKER_BIN" compose --file "$COMPOSE_FILE" --file "$override_file" restart sheets-api || fail_closed $?
verify_running_api

echo "Sheets rollback completed: timer off, claims unbound, exact image object/RepoDigest and restart 11/5 health verified."
