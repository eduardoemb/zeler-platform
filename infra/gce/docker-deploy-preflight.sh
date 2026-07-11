#!/usr/bin/env bash
# Preflight guard before docker compose pull on platform-vm.

set -euo pipefail

MIN_FREE_GIB=${MIN_FREE_GIB:-5}
MAINTENANCE_SCRIPT=${MAINTENANCE_SCRIPT:-/opt/zeler-platform/docker-maintenance.sh}
PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
SHEETS_ROLLBACK_PREFLIGHT=${SHEETS_ROLLBACK_PREFLIGHT:-0}
PROHIBITED_OLD_SHEETS_API_DIGEST=sha256:8da8ab2b0b092825e6b3f362ea92e375a52e25a7a3cb78c2af0828844ddb00b6
GCLOUD_BIN=${ZELER_GCLOUD_BIN:-/usr/bin/gcloud}
DOCKER_BIN=${ZELER_DOCKER_BIN:-/usr/bin/docker}
PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}
ROLLBACK_PROOF_FILE=${SHEETS_ROLLBACK_PROOF_FILE:-/var/lib/zeler-platform/sheets-rollback-release-proof.json}

min_free_kib=$((MIN_FREE_GIB * 1024 * 1024))

free_root_kib() {
  df -Pk / | awk 'NR == 2 {print $4}'
}

require_free_space() {
  local free_kib=$1
  (( free_kib >= min_free_kib ))
}

require_digest() {
  local label=$1
  local value=$2
  if [[ ! "$value" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "ERROR: $label digest is missing or invalid." >&2
    exit 1
  fi
}

verify_sheets_rollback_attestation() {
  require_digest "candidate API" "${SHEETS_CANDIDATE_API_DIGEST:-}"
  require_digest "candidate worker" "${SHEETS_CANDIDATE_WORKER_DIGEST:-}"
  require_digest "prior worker" "${SHEETS_PRIOR_WORKER_DIGEST:-}"
  require_digest "prior gateway" "${SHEETS_PRIOR_GATEWAY_DIGEST:-}"
  local image_ref=${SHEETS_ROLLBACK_API_IMAGE_REF:-}
  local source_commit=${SHEETS_ROLLBACK_SOURCE_COMMIT:-}
  local connected_repository=${SHEETS_ROLLBACK_CONNECTED_REPOSITORY:-}
  if [[ ! "$image_ref" =~ ^[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]]; then
    echo "ERROR: rollback-compatible API Artifact Registry image reference is invalid." >&2
    exit 1
  fi
  local rollback_digest=${image_ref##*@}
  require_digest "rollback-compatible API" "$rollback_digest"

  if [[ "$rollback_digest" == "$PROHIBITED_OLD_SHEETS_API_DIGEST" ]]; then
    echo "ERROR: prohibited old 8/4 Sheets API rollback target." >&2
    exit 1
  fi
  if [[ ! "$source_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: rollback-compatible API source commit is invalid." >&2
    exit 1
  fi
  local artifact_file build_file config_file probe_file build_id image_id gcloud_project_id gcloud_project_number
  gcloud_project_id=$("$GCLOUD_BIN" config get-value project 2>/dev/null)
  if [[ ! "$gcloud_project_id" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
    echo "ERROR: trusted gcloud project id is missing or invalid." >&2
    exit 1
  fi
  gcloud_project_number=$("$GCLOUD_BIN" projects describe "$gcloud_project_id" --format='value(projectNumber)')
  if [[ ! "$gcloud_project_number" =~ ^[0-9]+$ ]]; then
    echo "ERROR: trusted gcloud project number is missing or invalid." >&2
    exit 1
  fi
  artifact_file=$(mktemp)
  build_file=$(mktemp)
  config_file=$(mktemp)
  probe_file=$(mktemp)
  trap 'rm -f "$artifact_file" "$build_file" "$config_file" "$probe_file"' RETURN
  rm -f "$ROLLBACK_PROOF_FILE"
  "$GCLOUD_BIN" artifacts docker images describe "$image_ref" \
    --show-provenance --format=json > "$artifact_file"
  build_id=$(PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.deploy.sheets_rollback extract-build-id \
    --artifact-provenance "$artifact_file" --image-ref "$image_ref")
  "$GCLOUD_BIN" builds describe "$build_id" --format=json > "$build_file"
  if [[ -n "$connected_repository" ]]; then
    PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
      verify-gcloud \
      --artifact-provenance "$artifact_file" \
      --build "$build_file" \
      --image-ref "$image_ref" \
      --source-commit "$source_commit" \
      --expected-project-id "$gcloud_project_id" \
      --expected-project-number "$gcloud_project_number" \
      --connected-repository "$connected_repository"
  else
    PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
      verify-gcloud \
      --artifact-provenance "$artifact_file" \
      --build "$build_file" \
      --image-ref "$image_ref" \
      --source-commit "$source_commit" \
      --expected-project-id "$gcloud_project_id" \
      --expected-project-number "$gcloud_project_number"
  fi

  "$DOCKER_BIN" pull "$image_ref" >/dev/null
  image_id=$("$DOCKER_BIN" image inspect "$image_ref" --format '{{.Id}}')
  "$DOCKER_BIN" image inspect "$image_ref" --format '{{json .Config}}' > "$config_file"
  "$DOCKER_BIN" run --rm --network none --entrypoint /app/.venv/bin/python "$image_ref" -c \
    'import json; from zeler_platform_core.runtime.manifest import validate_manifest; from zeler_platform_core.runtime.registration import module_registration_document,module_registration_fingerprint; from zeler_sheets.app import make_app; manifest=validate_manifest("/app/modules/sheets/manifest.yaml"); document=module_registration_document(manifest); print(json.dumps({"entrypoint_import":callable(make_app),"module_id":manifest.module_id,"registry_fingerprint":module_registration_fingerprint(document),"scope_count":len(document["allowed_meli_scopes"]),"routing_key_count":len(document["routing_keys"])},sort_keys=True,separators=(",",":")))' \
    > "$probe_file"
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.sheets_rollback \
    verify-image-contract \
    --image-config "$config_file" \
    --probe "$probe_file" \
    --image-ref "$image_ref" \
    --image-id "$image_id" \
    --source-commit "$source_commit" \
    --proof-out "$ROLLBACK_PROOF_FILE"

  echo "Sheets rollback attestation passed: exact 11 scopes/5 routing keys."
  echo "candidate/prior runtime digests: verified"
  echo "External Artifact Registry and Cloud Build provenance: verified"
  echo "Pulled digest image config and no-secret runtime contract probe: verified"
}

print_usage() {
  echo "Root filesystem usage:"
  df -h /
}

if [[ "$SHEETS_ROLLBACK_PREFLIGHT" == "1" ]]; then
  verify_sheets_rollback_attestation
fi

free_kib=$(free_root_kib)
print_usage

if require_free_space "$free_kib"; then
  echo "Preflight passed: root filesystem has at least ${MIN_FREE_GIB}GiB free."
  exit 0
fi

echo "Preflight warning: root filesystem has less than ${MIN_FREE_GIB}GiB free."
echo "Running safe Docker maintenance before docker compose pull."

if [[ ! -x "$MAINTENANCE_SCRIPT" ]]; then
  echo "ERROR: maintenance script is missing or not executable: $MAINTENANCE_SCRIPT" >&2
  exit 1
fi

"$MAINTENANCE_SCRIPT"

free_kib=$(free_root_kib)
print_usage

if require_free_space "$free_kib"; then
  echo "Preflight passed after cleanup: root filesystem has at least ${MIN_FREE_GIB}GiB free."
  exit 0
fi

echo "ERROR: root filesystem still has less than ${MIN_FREE_GIB}GiB free after safe cleanup." >&2
echo "Resize the platform-vm boot disk to 50GB only after cleanup cannot maintain the deploy margin." >&2
exit 1
