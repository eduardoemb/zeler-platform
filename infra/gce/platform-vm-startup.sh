#!/usr/bin/env bash
# platform-vm-startup.sh — GCE startup script for platform-vm (Ubuntu 22.04 LTS).
#
# Responsibilities:
#   1. Install Docker Engine + Compose v2
#   2. Configure Docker daemon log rotation
#   3. Format & mount persistent data disk at /var/lib/zeler-mongo (ext4, nofail fstab)
#   4. Chown /var/lib/zeler-mongo to UID 999:999 (mongo container user)
#   5. Install Google Cloud Ops Agent (logging + metrics)
#   6. Authenticate Docker to Artifact Registry (us-central1)
#   7. Create /opt/zeler-platform/ directory layout
#   8. Install safe Docker root-disk maintenance scripts + timer
#   9. Install the explicit DEVOLUCIONES topology wrapper without executing it
#   10. Write & enable the zeler-platform-secrets.service systemd unit
#   11. Write the secrets helper script to /opt/zeler-platform/
#   12. Touch /opt/zeler-platform/.startup-complete as a readiness sentinel
#
# Idempotent: safe to re-run on re-provision (each step checks before acting).
# Logs appended to /var/log/platform-startup.log.

set -euo pipefail
exec > >(tee -a /var/log/platform-startup.log) 2>&1

echo "=== platform-vm-startup.sh started at $(date -u) ==="

# -------------------------------------------------------------------------
# 1. System packages
# -------------------------------------------------------------------------
apt-get update -y
apt-get install -y ca-certificates curl gnupg jq lsb-release

# -------------------------------------------------------------------------
# 2. Docker Engine + Compose v2
# -------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable docker
  systemctl start docker
  echo "Docker installed: $(docker --version)"
else
  echo "Docker already installed: $(docker --version)"
fi

# -------------------------------------------------------------------------
# 2b. Docker daemon log rotation
# -------------------------------------------------------------------------
mkdir -p /etc/docker
DAEMON_JSON_TMP=$(mktemp)
if [[ -s /etc/docker/daemon.json ]] && jq empty /etc/docker/daemon.json >/dev/null 2>&1; then
  jq '. + {"log-driver": "local", "log-opts": {"max-size": "50m", "max-file": "5"}}' \
    /etc/docker/daemon.json > "$DAEMON_JSON_TMP"
else
  cat > "$DAEMON_JSON_TMP" << 'JSON'
{
  "log-driver": "local",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON
fi
if ! cmp -s "$DAEMON_JSON_TMP" /etc/docker/daemon.json; then
  install -m 0644 "$DAEMON_JSON_TMP" /etc/docker/daemon.json
  systemctl restart docker
  echo "Docker daemon log rotation configured in /etc/docker/daemon.json"
else
  echo "Docker daemon log rotation already configured in /etc/docker/daemon.json"
fi
rm -f "$DAEMON_JSON_TMP"

# -------------------------------------------------------------------------
# 3. Persistent data disk — format (if blank) + mount
# -------------------------------------------------------------------------
DEVICE=/dev/disk/by-id/google-mongo-data
MOUNT_POINT=/var/lib/zeler-mongo

# Wait up to 30 s for the device symlink to appear
for _i in $(seq 1 30); do
  [[ -e "$DEVICE" ]] && break
  echo "Waiting for device $DEVICE … attempt $_i"
  sleep 1
done

if [[ ! -e "$DEVICE" ]]; then
  echo "WARNING: device $DEVICE not found after 30 s — skipping disk setup"
else
  if ! blkid "$DEVICE" >/dev/null 2>&1; then
    echo "Formatting $DEVICE as ext4"
    mkfs.ext4 -F "$DEVICE"
  else
    echo "Device $DEVICE already formatted: $(blkid -s TYPE -o value "$DEVICE")"
  fi

  mkdir -p "$MOUNT_POINT"

  UUID=$(blkid -s UUID -o value "$DEVICE")
  if ! grep -q "$UUID" /etc/fstab; then
    echo "UUID=$UUID $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab
    echo "Added fstab entry for UUID=$UUID"
  fi
  mount -a

  # Mongo container runs as UID 999 — ensure ownership before first boot
  chown -R 999:999 "$MOUNT_POINT"
  echo "Mounted $MOUNT_POINT and chowned to 999:999"
fi

# -------------------------------------------------------------------------
# 4. Google Cloud Ops Agent
# -------------------------------------------------------------------------
if ! systemctl is-active --quiet google-cloud-ops-agent 2>/dev/null; then
  curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
  bash add-google-cloud-ops-agent-repo.sh --also-install
  echo "Ops Agent installed"
else
  echo "Ops Agent already running"
fi

# -------------------------------------------------------------------------
# 5. Auth Docker to Artifact Registry
# -------------------------------------------------------------------------
gcloud auth configure-docker us-central1-docker.pkg.dev --quiet
echo "Docker authenticated to Artifact Registry"

# -------------------------------------------------------------------------
# 6. /opt/zeler-platform/ layout
# -------------------------------------------------------------------------
mkdir -p /opt/zeler-platform/{env,caddy_data,caddy_config,mongo-keyfiles}
chmod 700 /opt/zeler-platform/env
echo "Directory layout created under /opt/zeler-platform/"

# -------------------------------------------------------------------------
# 6a. Ops Agent classified-log config (validate, install, restart safely)
# -------------------------------------------------------------------------
cat > /opt/zeler-platform/ops-agent-config.yaml << 'OPSAGENT'
# Google Cloud Ops Agent classified-log configuration for platform-vm.
#
# Two pipelines:
#   - gateway_classified: tails Docker container logs (the gateway emits
#     structlog JSON via container stdout -> Docker json-file driver), parses
#     the per-line JSON payload, and routes it to the custom Cloud Logging log
#     `zeler-platform/gateway-classified`.
#   - caddy_classified: tails the same Docker json-file logs, which carry
#     Caddy's JSON access logs (Caddy logs to container stdout), parses them,
#     and routes the result to the custom Cloud Logging log
#     `zeler-platform/caddy-classified`.
#
# Installed by infra/gce/platform-vm-startup.sh using a validate -> install ->
# restart sequence that keeps the prior config when validation fails.

receivers:
  docker_container_logs:
    type: files
    include_paths:
      - /var/lib/docker/containers/*/*-json.log
  caddy_logs:
    type: files
    include_paths:
      - /var/lib/docker/containers/*/*-json.log

processors:
  docker_logs_parse_json:
    type: parse_json
    parse_from: log
  caddy_logs_parse_json:
    type: parse_json
    parse_from: log
  caddy_logs_redact:
    type: modify_fields
    fields:
      jsonPayload.request.headers:
        map_values: {}
        map_values_exclusive: true
      jsonPayload.request.uri:
        map_values: {}
        map_values_exclusive: true
      jsonPayload.resp_headers:
        map_values: {}
        map_values_exclusive: true

exporters:
  gateway_classified_logging:
    type: google_cloud_logging
    log_type: zeler-platform/gateway-classified
  caddy_classified_logging:
    type: google_cloud_logging
    log_type: zeler-platform/caddy-classified

service:
  pipelines:
    gateway_classified:
      receivers:
        - docker_container_logs
      processors:
        - docker_logs_parse_json
      exporters:
        - gateway_classified_logging
    caddy_classified:
      receivers:
        - caddy_logs
      processors:
        - caddy_logs_parse_json
        - caddy_logs_redact
      exporters:
        - caddy_classified_logging
OPSAGENT
if command -v ops-agent-ctl >/dev/null 2>&1; then
  mkdir -p /etc/google-cloud-ops-agent
  if ops-agent-ctl validate-config /opt/zeler-platform/ops-agent-config.yaml; then
    install -m 0644 /opt/zeler-platform/ops-agent-config.yaml /etc/google-cloud-ops-agent/config.yaml
    systemctl restart google-cloud-ops-agent
    echo "Ops Agent classified-log config validated and applied"
  else
    echo "WARNING: Ops Agent config validation failed; prior config kept" >&2
  fi
else
  echo "WARNING: ops-agent-ctl not found; classified-log config not applied" >&2
fi

# -------------------------------------------------------------------------
# 6b. Safe Docker root-disk maintenance scripts + timer
# -------------------------------------------------------------------------
cat > /opt/zeler-platform/docker-maintenance.sh << 'SCRIPT'
#!/usr/bin/env bash
# Safe Docker root-disk maintenance for platform-vm.
# Mongo data lives on /var/lib/zeler-mongo; Docker volumes are intentionally untouched.

set -euo pipefail

DOCKER_PRUNE_UNTIL=${DOCKER_PRUNE_UNTIL:-72h}

echo "=== zeler docker maintenance started at $(date -u) ==="
echo "Root filesystem usage before cleanup:"
df -h /

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed; nothing to clean."
  exit 0
fi

echo "Docker disk usage before cleanup:"
docker system df || true

echo "Pruning stopped containers older than $DOCKER_PRUNE_UNTIL"
docker container prune --force --filter "until=$DOCKER_PRUNE_UNTIL"

echo "Pruning unused images older than $DOCKER_PRUNE_UNTIL"
docker image prune -af --filter "until=$DOCKER_PRUNE_UNTIL"

echo "Pruning builder cache older than $DOCKER_PRUNE_UNTIL"
docker builder prune -af --filter "until=$DOCKER_PRUNE_UNTIL"

echo "Docker disk usage after cleanup:"
docker system df || true
echo "Root filesystem usage after cleanup:"
df -h /
echo "=== zeler docker maintenance completed at $(date -u) ==="
SCRIPT

cat > /opt/zeler-platform/docker-deploy-preflight.sh << 'SCRIPT'
#!/usr/bin/env bash
# Preflight guard before docker compose pull on platform-vm.

set -euo pipefail

MIN_FREE_GIB=${MIN_FREE_GIB:-5}
ALLOW_DOCKER_MAINTENANCE=${ALLOW_DOCKER_MAINTENANCE:-0}
MAINTENANCE_SCRIPT=${MAINTENANCE_SCRIPT:-/opt/zeler-platform/docker-maintenance.sh}
PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
SHEETS_ROLLBACK_PREFLIGHT=${SHEETS_ROLLBACK_PREFLIGHT:-0}
REQUIRE_DIGEST_BINDING=${REQUIRE_DIGEST_BINDING:-0}
DIGEST_BINDING_SERVICES=${DIGEST_BINDING_SERVICES:-}
PROHIBITED_OLD_SHEETS_API_DIGEST=sha256:8da8ab2b0b092825e6b3f362ea92e375a52e25a7a3cb78c2af0828844ddb00b6
GCLOUD_BIN=${ZELER_GCLOUD_BIN:-/snap/bin/gcloud}
DOCKER_BIN=${ZELER_DOCKER_BIN:-/usr/bin/docker}
PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}
ROLLBACK_PROOF_FILE=${SHEETS_ROLLBACK_PROOF_FILE:-/var/lib/zeler-platform/sheets-rollback-release-proof.json}
COMPOSE_FILE=${ZELER_COMPOSE_FILE:-$PLATFORM_ROOT/docker-compose.yml}
if [[ ! -f "$COMPOSE_FILE" ]]; then
  COMPOSE_FILE="$(cd "$(dirname "$0")" && pwd)/docker-compose.yml"
fi
IMAGE_TO_COMMIT_FILE=${IMAGE_TO_COMMIT_FILE:-/var/lib/zeler-platform/image_to_commit.json}
ZELER_BUILD_REGION=${ZELER_BUILD_REGION:-us-central1}
if [[ "$ZELER_BUILD_REGION" != "global" && ! "$ZELER_BUILD_REGION" =~ ^[a-z]+(-[a-z]+)+[0-9]+$ ]]; then
  echo "ERROR: ZELER_BUILD_REGION must be a valid regional Cloud Build location." >&2
  exit 1
fi

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

digest_binding_service_args=()
if [[ -n "$DIGEST_BINDING_SERVICES" ]]; then
  if [[ ! "$DIGEST_BINDING_SERVICES" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*(,[A-Za-z0-9][A-Za-z0-9_.-]*)*$ ]]; then
    echo "ERROR: DIGEST_BINDING_SERVICES must be a comma-separated list of Compose service names." >&2
    exit 1
  fi
  IFS=, read -r -a digest_binding_services <<< "$DIGEST_BINDING_SERVICES"
  for digest_binding_service in "${digest_binding_services[@]}"; do
    digest_binding_service_args+=(--service "$digest_binding_service")
  done
fi

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
  "$GCLOUD_BIN" builds describe "$build_id" --region="$ZELER_BUILD_REGION" --format=json > "$build_file"
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

  echo "Sheets rollback attestation passed: exact registration contract verified."
  echo "candidate/prior runtime digests: verified"
  echo "External Artifact Registry and Cloud Build provenance: verified"
  echo "Pulled digest image config and no-secret runtime contract probe: verified"
}

verify_digest_binding() {
  # Opt-in immutable-digest provenance gate: refuses any moving image: tag
  # BEFORE any pull, then verifies each pinned image against one successful
  # SLSA v1 subject/build/commit and writes image_to_commit.json evidence.
  local image_ref build_id gcloud_project_id gcloud_project_number temp_dir image_list
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: compose file is missing: $COMPOSE_FILE" >&2
    exit 1
  fi
  echo "Refusing any moving image tag before pull (REQUIRE_DIGEST_BINDING=1)."
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.provenance_check \
    check-compose --compose-file "$COMPOSE_FILE" "${digest_binding_service_args[@]}"
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
  temp_dir=$(mktemp -d)
  image_list=$(mktemp)
  trap 'rm -rf "$temp_dir" "$image_list"' RETURN
  rm -f "$IMAGE_TO_COMMIT_FILE"
  PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
    -m infra.deploy.provenance_check list-images --compose-file "$COMPOSE_FILE" \
    "${digest_binding_service_args[@]}" > "$image_list"
  while IFS= read -r image_ref; do
    [[ -n "$image_ref" ]] || continue
    "$GCLOUD_BIN" artifacts docker images describe "$image_ref" \
      --show-provenance --format=json > "$temp_dir/artifact.json"
    build_id=$(PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
      -m infra.deploy.provenance_check extract-build-id \
      --artifact-file "$temp_dir/artifact.json" --image-ref "$image_ref")
    "$GCLOUD_BIN" builds describe "$build_id" --region="$ZELER_BUILD_REGION" --format=json > "$temp_dir/build.json"
    PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" -m infra.deploy.provenance_check \
      verify-image \
      --image-ref "$image_ref" \
      --artifact-file "$temp_dir/artifact.json" \
      --build-file "$temp_dir/build.json" \
      --expected-project-id "$gcloud_project_id" \
      --expected-project-number "$gcloud_project_number" \
      --map-out "$IMAGE_TO_COMMIT_FILE"
  done < "$image_list"
  echo "Immutable image provenance binding: verified for every compose image."
  echo "image_to_commit.json: $IMAGE_TO_COMMIT_FILE"
}

print_usage() {
  echo "Root filesystem usage:"
  df -h /
}

ensure_capacity() {
  local free_kib
  free_kib=$(free_root_kib)
  print_usage
  if require_free_space "$free_kib"; then
    echo "Capacity passed: root filesystem has at least ${MIN_FREE_GIB}GiB free."
    return
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "dry-run: root filesystem has less than ${MIN_FREE_GIB}GiB free."
    echo "dry-run: Docker maintenance skipped."
    exit 1
  fi
  if [[ "$ALLOW_DOCKER_MAINTENANCE" != "1" ]]; then
    echo "ERROR: insufficient space; cleanup requires explicit ALLOW_DOCKER_MAINTENANCE=1 authorization." >&2
    exit 1
  fi
  if [[ ! -x "$MAINTENANCE_SCRIPT" ]]; then
    echo "ERROR: maintenance script is missing or not executable: $MAINTENANCE_SCRIPT" >&2
    exit 1
  fi
  echo "Running authorized Docker maintenance before any image pull."
  "$MAINTENANCE_SCRIPT"
  free_kib=$(free_root_kib)
  print_usage
  if ! require_free_space "$free_kib"; then
    echo "ERROR: root filesystem still has less than ${MIN_FREE_GIB}GiB free after cleanup." >&2
    echo "Review disk capacity if cleanup cannot maintain the margin; do not assume a 50GB resize is still needed." >&2
    exit 1
  fi
}

# Capacity must precede attestation: that gate can download a rollback image.
ensure_capacity

if [[ "$REQUIRE_DIGEST_BINDING" == "1" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
      -m infra.deploy.provenance_check check-compose \
      --compose-file "$COMPOSE_FILE" "${digest_binding_service_args[@]}"
    echo "dry-run: selected image references checked; provenance not verified (no evidence written)."
  else
    verify_digest_binding
  fi
fi

if [[ "$SHEETS_ROLLBACK_PREFLIGHT" == "1" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "dry-run: Sheets rollback attestation skipped (it would pull images)."
  else
    verify_sheets_rollback_attestation
    # A successful download may consume the space needed by the deployment pull.
    ensure_capacity
  fi
fi

echo "Preflight passed for the selected mode; dry-run is not deployment approval."
SCRIPT

chmod 0755 /opt/zeler-platform/docker-maintenance.sh /opt/zeler-platform/docker-deploy-preflight.sh

cat > /etc/systemd/system/zeler-docker-maintenance.service << 'UNIT'
[Unit]
Description=Safe Zeler Docker root-disk maintenance
Wants=docker.service
After=docker.service

[Service]
Type=oneshot
ExecStart=/opt/zeler-platform/docker-maintenance.sh
User=root
Group=root
UNIT

cat > /etc/systemd/system/zeler-docker-maintenance.timer << 'UNIT'
[Unit]
Description=Run safe Zeler Docker root-disk maintenance daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1800

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now zeler-docker-maintenance.timer
echo "Safe Docker maintenance scripts and zeler-docker-maintenance.timer installed"

# -------------------------------------------------------------------------
# 6c. Explicit DEVOLUCIONES topology wrapper (installation only)
# -------------------------------------------------------------------------
cat > /opt/zeler-platform/zelerdata-devoluciones-topology.sh << 'SCRIPT'
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
SCRIPT
chmod 0755 /opt/zeler-platform/zelerdata-devoluciones-topology.sh
echo "Installed zelerdata-devoluciones-topology.sh; no topology command was executed"

# -------------------------------------------------------------------------
# 6d. DEVOLUCIONES quota-window reconciliation (installed, not enabled)
# -------------------------------------------------------------------------
RECONCILE_WRAPPER_B64='IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgLWV1byBwaXBlZmFpbAp1bWFzayAwNzcKClBMQVRGT1JNX1JPT1Q9JHtaRUxFUl9QTEFURk9STV9ST09UOi0vb3B0L3plbGVyLXBsYXRmb3JtfQpDT01QT1NFX0ZJTEU9JHtaRUxFUl9DT01QT1NFX0ZJTEU6LSRQTEFURk9STV9ST09UL2RvY2tlci1jb21wb3NlLnltbH0KRE9DS0VSX0JJTj0ke1pFTEVSX0RPQ0tFUl9CSU46LS91c3IvYmluL2RvY2tlcn0KTE9HR0VSX0JJTj0ke1pFTEVSX0xPR0dFUl9CSU46LS91c3IvYmluL2xvZ2dlcn0KVElNRU9VVF9CSU49JHtaRUxFUl9USU1FT1VUX0JJTjotL3Vzci9iaW4vdGltZW91dH0KUlVOX0lEPSR7WkVMRVJEQVRBX0RFVk9MVUNJT05FU19SVU5fSUQ6LX0KCmxvZ19mYWlsdXJlKCkgewogICIkTE9HR0VSX0JJTiIgXAogICAgLS1wcmlvcml0eSBkYWVtb24uZXJyIFwKICAgIC0tdGFnIHplbGVyZGF0YS1kZXZvbHVjaW9uZXMtcmVjb25jaWxlIFwKICAgICJldmVudD0kMSBkaWFnbm9zdGljcz1zYW5pdGl6ZWQiIHx8IHRydWUKfQoKaWYgW1sgISAiJFJVTl9JRCIgPX4gXlswLTlhLWZdezY0fSQgXV07IHRoZW4KICBsb2dfZmFpbHVyZSBxdW90YV9ydW5fYXV0aG9yaXR5X2ludmFsaWQKICBleGl0IDY0CmZpCgppZiBbWyAhIC1kICIkUExBVEZPUk1fUk9PVCIgfHwgISAtZiAiJENPTVBPU0VfRklMRSIgXV07IHRoZW4KICBsb2dfZmFpbHVyZSBydW50aW1lX3BhdGhfbWlzc2luZwogIGV4aXQgNjYKZmkKCmNkICIkUExBVEZPUk1fUk9PVCIKZXhlYyAiJFRJTUVPVVRfQklOIiAtLXNpZ25hbD1URVJNIC0ta2lsbC1hZnRlcj0zMHMgMTc1cyBcCiAgIiRET0NLRVJfQklOIiBjb21wb3NlIC0tZmlsZSAiJENPTVBPU0VfRklMRSIgZXhlYyAtVCAtLXdvcmtkaXIgL2FwcCBcCiAgc2hlZXRzLXdvcmtlciAvYXBwLy52ZW52L2Jpbi9weXRob24gXAogIC1tIGluZnJhLm9wZXJhdGlvbnMuZGV2b2x1Y2lvbmVzX3F1b3RhX2FkdmFuY2UgXAogIC0tcnVuLWlkICIkUlVOX0lEIgo='
printf '%s' "$RECONCILE_WRAPPER_B64" | base64 --decode > /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh
unset RECONCILE_WRAPPER_B64
chmod 0755 /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh

cat > /etc/systemd/system/zelerdata-devoluciones-reconcile.service << 'UNIT'
[Unit]
Description=Advance one authorized ZELERDATA DEVOLUCIONES quota window
Wants=network-online.target
Requires=docker.service
After=docker.service network-online.target
OnFailure=zelerdata-devoluciones-reconcile-alert.service

[Service]
Type=oneshot
WorkingDirectory=/opt/zeler-platform
# The operator-owned run ID is mandatory. This unit never creates authority.
EnvironmentFile=/etc/zeler-platform/zelerdata-devoluciones-quota-run.env
ExecStart=/opt/zeler-platform/zelerdata-devoluciones-reconcile.sh
TimeoutStartSec=8m
Restart=no
StandardOutput=journal
StandardError=journal
SyslogIdentifier=zelerdata-devoluciones-reconcile
UNIT

cat > /etc/systemd/system/zelerdata-devoluciones-reconcile.timer << 'UNIT'
[Unit]
Description=Advance authorized ZELERDATA DEVOLUCIONES quota windows

[Timer]
OnUnitInactiveSec=10m
RandomizedDelaySec=119s
AccuracySec=1s
Unit=zelerdata-devoluciones-reconcile.service

[Install]
WantedBy=timers.target
UNIT

cat > /etc/systemd/system/zelerdata-devoluciones-reconcile-alert.service << 'UNIT'
[Unit]
Description=Emit a sanitized alert for failed ZELERDATA DEVOLUCIONES reconciliation

[Service]
Type=oneshot
ExecStart=/usr/bin/logger --priority daemon.err --tag zelerdata-devoluciones-alert "DEVOLUCIONES_RECONCILIATION_FAILED; inspect with journalctl -u zelerdata-devoluciones-reconcile.service"
StandardOutput=journal
StandardError=journal
SyslogIdentifier=zelerdata-devoluciones-alert
UNIT

systemctl daemon-reload
echo "Installed DEVOLUCIONES reconciliation wrapper, units, and alert; timer remains disabled"

# -------------------------------------------------------------------------
# 6e. Sheets DLQ snapshot execution authority (installation only)
# -------------------------------------------------------------------------
install -d -o root -g root -m 0700 /var/lib/zeler-platform/sheets-dlq-snapshot
SHEETS_DLQ_WRAPPER_SOURCE=$(mktemp)
cat > "$SHEETS_DLQ_WRAPPER_SOURCE" << 'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
umask 077

EXIT_USAGE=2
EXIT_CONFIG=4
EXIT_MESSAGE_OR_CANCELLED=6
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
trap 'exit "$EXIT_MESSAGE_OR_CANCELLED"' HUP INT TERM

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
SCRIPT
install -o root -g root -m 0755 "$SHEETS_DLQ_WRAPPER_SOURCE" /opt/zeler-platform/sheets-dlq-snapshot-execute.sh
rm -f "$SHEETS_DLQ_WRAPPER_SOURCE"
unset SHEETS_DLQ_WRAPPER_SOURCE
echo "Installed sheets-dlq-snapshot-execute.sh; no snapshot was executed"

# -------------------------------------------------------------------------
# 7. Systemd unit: zeler-platform-secrets.service
# -------------------------------------------------------------------------
cat > /etc/systemd/system/zeler-platform-secrets.service << 'UNIT'
[Unit]
Description=Materialize Zeler platform per-service env files from Secret Manager
Wants=network-online.target
After=network-online.target
Before=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/zeler-platform/zeler-platform-secrets.sh
User=root
Group=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable zeler-platform-secrets.service
echo "Systemd unit zeler-platform-secrets.service installed and enabled"

# -------------------------------------------------------------------------
# 8. Sentinel
# -------------------------------------------------------------------------
touch /opt/zeler-platform/.startup-complete
echo "=== platform-vm-startup.sh completed at $(date -u) ==="
