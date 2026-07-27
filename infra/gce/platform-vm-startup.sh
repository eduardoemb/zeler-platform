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
# 6d. DEVOLUCIONES closed-window reconciliation (installed, not enabled)
# -------------------------------------------------------------------------
RECONCILE_WRAPPER_B64='IyEvdXNyL2Jpbi9lbnYgYmFzaApzZXQgLWV1byBwaXBlZmFpbAp1bWFzayAwNzcKClBMQVRGT1JNX1JPT1Q9JHtaRUxFUl9QTEFURk9STV9ST09UOi0vb3B0L3plbGVyLXBsYXRmb3JtfQpDT01QT1NFX0ZJTEU9JHtaRUxFUl9DT01QT1NFX0ZJTEU6LSRQTEFURk9STV9ST09UL2RvY2tlci1jb21wb3NlLnltbH0KREFURV9CSU49JHtaRUxFUl9EQVRFX0JJTjotL3Vzci9iaW4vZGF0ZX0KRE9DS0VSX0JJTj0ke1pFTEVSX0RPQ0tFUl9CSU46LS91c3IvYmluL2RvY2tlcn0KTE9HR0VSX0JJTj0ke1pFTEVSX0xPR0dFUl9CSU46LS91c3IvYmluL2xvZ2dlcn0KTUtURU1QX0JJTj0ke1pFTEVSX01LVEVNUF9CSU46LS91c3IvYmluL21rdGVtcH0KUFlUSE9OX0JJTj0ke1pFTEVSX1BZVEhPTl9CSU46LS91c3IvYmluL3B5dGhvbjN9ClJNX0JJTj0ke1pFTEVSX1JNX0JJTjotL3Vzci9iaW4vcm19ClRJTUVPVVRfQklOPSR7WkVMRVJfVElNRU9VVF9CSU46LS91c3IvYmluL3RpbWVvdXR9CkFQUFJPVkVEX1NFTExFUl9JRD04MjQ1MzMwNApDT05GSUdVUkVEX1NFTExFUl9JRD0ke1pFTEVSREFUQV9ERVZPTFVDSU9ORVNfU0VMTEVSX0lEOi19ClNFTExFUl9JRD0kQVBQUk9WRURfU0VMTEVSX0lECkFDQ0VQVEVEX1JBTkdFX1NUQVJUPTIwMjYtMDYtMDEKQUNDRVBURURfQkFTRUxJTkVfVEhST1VHSD0yMDI2LTA3LTA5ClJBTkdFX1NUQVJUPSR7WkVMRVJEQVRBX0RFVk9MVUNJT05FU19SQU5HRV9TVEFSVDotMjAyNi0wNi0wMX0KQUNDRVBURURfVEhST1VHSD0ke1pFTEVSREFUQV9ERVZPTFVDSU9ORVNfQUNDRVBURURfVEhST1VHSDotMjAyNi0wNy0wOX0KQ0FNUEFJR05fSUQ9JHtaRUxFUkRBVEFfREVWT0xVQ0lPTkVTX0NBTVBBSUdOX0lEOi19CkNBTVBBSUdOX1NUQVRFX0ZJTEU9JHtaRUxFUkRBVEFfREVWT0xVQ0lPTkVTX0NBTVBBSUdOX1NUQVRFX0ZJTEU6LS92YXIvbGliL3plbGVyLXBsYXRmb3JtL3plbGVyZGF0YS1kZXZvbHVjaW9uZXMtY2FtcGFpZ24uanNvbn0KT1VUUFVUX0ZJTEU9ClBVQkxJQ19FVklERU5DRV9GSUxFPQpQUklWQVRFX1NBTVBMRV9GSUxFPQpFVklERU5DRV9QVUJMSVNIRUQ9MApGSU5BTF9TVEFUVVNfQ0xBU1M9ZXZpZGVuY2VfaW52YWxpZAoKY2xlYW51cCgpIHsKICBpZiBbWyAtbiAiJE9VVFBVVF9GSUxFIiB8fCAtbiAiJFBVQkxJQ19FVklERU5DRV9GSUxFIiB8fCAtbiAiJFBSSVZBVEVfU0FNUExFX0ZJTEUiIF1dOyB0aGVuCiAgICAiJFJNX0JJTiIgLWYgXAogICAgICAke09VVFBVVF9GSUxFOisiJE9VVFBVVF9GSUxFIn0gXAogICAgICAke1BVQkxJQ19FVklERU5DRV9GSUxFOisiJFBVQkxJQ19FVklERU5DRV9GSUxFIn0gXAogICAgICAke1BSSVZBVEVfU0FNUExFX0ZJTEU6KyIkUFJJVkFURV9TQU1QTEVfRklMRSJ9CiAgZmkKfQoKbG9nX2V2ZW50KCkgewogIGxvY2FsIHByaW9yaXR5PSQxCiAgbG9jYWwgZXZlbnQ9JDIKICAiJExPR0dFUl9CSU4iIFwKICAgIC0tcHJpb3JpdHkgIiRwcmlvcml0eSIgXAogICAgLS10YWcgemVsZXJkYXRhLWRldm9sdWNpb25lcy1yZWNvbmNpbGUgXAogICAgImV2ZW50PSRldmVudCBkaWFnbm9zdGljcz1zYW5pdGl6ZWQiIHx8IHRydWUKfQoKdmFsaWRfdXRjX2RhdGUoKSB7CiAgbG9jYWwgdmFsdWU9JDEKICBbWyAiJHZhbHVlIiA9fiBeWzAtOV17NH0tWzAtOV17Mn0tWzAtOV17Mn0kIF1dICYmCiAgICBbWyAiJCgiJERBVEVfQklOIiAtdSAtZCAiJHZhbHVlIiArJUYgMj4vZGV2L251bGwpIiA9PSAiJHZhbHVlIiBdXQp9CgpzYWZlX2NhbXBhaWduX2lkKCkgewogIGlmIFtbICIkQ0FNUEFJR05fSUQiID1+IF5bQS1aYS16MC05Ll8tXXsxLDY0fSQgXV07IHRoZW4KICAgIHByaW50ZiAnJXMnICIkQ0FNUEFJR05fSUQiCiAgZWxzZQogICAgcHJpbnRmICclcycgaW52YWxpZC1jYW1wYWlnbgogIGZpCn0KCnB1Ymxpc2hfc2NoZWR1bGVkX2V2aWRlbmNlKCkgewogIGxvY2FsIGV2aWRlbmNlX2xpbmUKICBsb2NhbCBsaW5lX2NvdW50PTAKICBsb2NhbCBzZWxlY3RlZF9saW5lPQogIHdoaWxlIElGUz0gcmVhZCAtciBldmlkZW5jZV9saW5lOyBkbwogICAgW1sgLW4gIiRldmlkZW5jZV9saW5lIiBdXSB8fCBjb250aW51ZQogICAgKChsaW5lX2NvdW50ICs9IDEpKQogICAgc2VsZWN0ZWRfbGluZT0kZXZpZGVuY2VfbGluZQogIGRvbmUgPCAiJFBVQkxJQ19FVklERU5DRV9GSUxFIgogIFtbICIkbGluZV9jb3VudCIgPT0gIjEiIF1dIHx8IHJldHVybiA2NQogIGlmICEgIiRMT0dHRVJfQklOIiBcCiAgICAtLXByaW9yaXR5IGRhZW1vbi5pbmZvIFwKICAgIC0tdGFnIHplbGVyZGF0YS1kZXZvbHVjaW9uZXMtcmVjb25jaWxlIFwKICAgICJldmVudD1zY2hlZHVsZWRfcnVuIGV2aWRlbmNlPSRzZWxlY3RlZF9saW5lIjsgdGhlbgogICAgd3JpdGVfcHVibGljX2V2aWRlbmNlIHB1YmxpY2F0aW9uX2ZhaWxlZAogICAgbG9jYWwgZGlzcXVhbGlmaWNhdGlvbl9zdGF0dXM9MAogICAgcGVyc2lzdF9kaXJlY3RfZmFpbHVyZSAwID4vZGV2L251bGwgMj4mMSB8fCBkaXNxdWFsaWZpY2F0aW9uX3N0YXR1cz0kPwogICAgc2VsZWN0ZWRfbGluZT0kKDwiJFBVQkxJQ19FVklERU5DRV9GSUxFIikKICAgIHByaW50ZiAnJXNcbicgIiRzZWxlY3RlZF9saW5lIgogICAgRVZJREVOQ0VfUFVCTElTSEVEPTEKICAgIFtbICIkZGlzcXVhbGlmaWNhdGlvbl9zdGF0dXMiID09ICIwIiBdXSB8fCByZXR1cm4gIiRkaXNxdWFsaWZpY2F0aW9uX3N0YXR1cyIKICAgIHJldHVybiA3MgogIGZpCiAgcHJpbnRmICclc1xuJyAiJHNlbGVjdGVkX2xpbmUiCiAgRVZJREVOQ0VfUFVCTElTSEVEPTEKfQoKcHVibGljX2V2aWRlbmNlX2xpbmUoKSB7CiAgbG9jYWwgc3RhdHVzX2NsYXNzPSQxCiAgcHJpbnRmICclc1xuJyBcCiAgICAie1wic3RhZ2VcIjpcInNjaGVkdWxlZFwiLFwic3RhdHVzX2NsYXNzXCI6XCIkc3RhdHVzX2NsYXNzXCIsXCJjb3VudGVyc1wiOnt9fSIKfQoKcHJpdmF0ZV9mYWlsdXJlX2xpbmUoKSB7CiAgbG9jYWwgZHVyYXRpb249JHsxOi0wfQogIGxvY2FsIGNhbXBhaWduCiAgY2FtcGFpZ249JChzYWZlX2NhbXBhaWduX2lkKQogIHByaW50ZiAnJXNcbicgXAogICAgIntcImNhbXBhaWduX2Rpc3F1YWxpZmllZFwiOnRydWUsXCJjYW1wYWlnbl9pZFwiOlwiJGNhbXBhaWduXCIsXCJkdXJhdGlvbl9zZWNvbmRzXCI6JGR1cmF0aW9uLFwib3V0Y29tZVwiOlwiZmFpbHVyZVwiLFwicmVhZF9tb2RlbF9maW5nZXJwcmludF9oYXNoXCI6bnVsbCxcInNvdXJjZV9maW5nZXJwcmludF9oYXNoXCI6bnVsbH0iCn0KCndyaXRlX3B1YmxpY19ldmlkZW5jZSgpIHsKICBwdWJsaWNfZXZpZGVuY2VfbGluZSAiJDEiID4gIiRQVUJMSUNfRVZJREVOQ0VfRklMRSIKfQoKd3JpdGVfcHJpdmF0ZV9mYWlsdXJlKCkgewogIHByaXZhdGVfZmFpbHVyZV9saW5lICIkezE6LTB9IiA+ICIkUFJJVkFURV9TQU1QTEVfRklMRSIKfQoKcGVyc2lzdF9jYW1wYWlnbl9zdGF0ZSgpIHsKICBQWVRIT05QQVRIPSIkUExBVEZPUk1fUk9PVCIgIiRQWVRIT05fQklOIiBcCiAgICAtbSBpbmZyYS5vcGVyYXRpb25zLnplbGVyZGF0YV9jYW1wYWlnbl9zdGF0ZSByZWNvcmQgXAogICAgLS1zdGF0ZS1maWxlICIkQ0FNUEFJR05fU1RBVEVfRklMRSIgXAogICAgLS1ldmlkZW5jZS1maWxlICIkUFJJVkFURV9TQU1QTEVfRklMRSIgMj4vZGV2L251bGwKfQoKcGVyc2lzdF9kaXJlY3RfZmFpbHVyZSgpIHsKICBwcml2YXRlX2ZhaWx1cmVfbGluZSAiJHsxOi0wfSIgfCBQWVRIT05QQVRIPSIkUExBVEZPUk1fUk9PVCIgIiRQWVRIT05fQklOIiBcCiAgICAtbSBpbmZyYS5vcGVyYXRpb25zLnplbGVyZGF0YV9jYW1wYWlnbl9zdGF0ZSByZWNvcmQtc3RkaW4gXAogICAgLS1zdGF0ZS1maWxlICIkQ0FNUEFJR05fU1RBVEVfRklMRSIgMj4vZGV2L251bGwKfQoKZW1pdF9kaXJlY3RfcHVibGljKCkgewogIGxvY2FsIGV2aWRlbmNlX2xpbmUKICBldmlkZW5jZV9saW5lPSQocHVibGljX2V2aWRlbmNlX2xpbmUgIiQxIikKICAiJExPR0dFUl9CSU4iIFwKICAgIC0tcHJpb3JpdHkgZGFlbW9uLmluZm8gXAogICAgLS10YWcgemVsZXJkYXRhLWRldm9sdWNpb25lcy1yZWNvbmNpbGUgXAogICAgImV2ZW50PXNjaGVkdWxlZF9ydW4gZXZpZGVuY2U9JGV2aWRlbmNlX2xpbmUiID4vZGV2L251bGwgMj4mMSB8fCB0cnVlCiAgcHJpbnRmICclc1xuJyAiJGV2aWRlbmNlX2xpbmUiCiAgRVZJREVOQ0VfUFVCTElTSEVEPTEKfQoKZmluYWxpemUoKSB7CiAgbG9jYWwgc3RhdHVzPSQ/CiAgdHJhcCAtIEVYSVQKICBzZXQgK2UKICBpZiBbWyAiJEVWSURFTkNFX1BVQkxJU0hFRCIgPT0gIjAiIF1dOyB0aGVuCiAgICBpZiBbWyAtbiAiJFBVQkxJQ19FVklERU5DRV9GSUxFIiBdXTsgdGhlbgogICAgICB3cml0ZV9wdWJsaWNfZXZpZGVuY2UgIiRGSU5BTF9TVEFUVVNfQ0xBU1MiCiAgICAgIGlmIFtbIC1uICIkUFJJVkFURV9TQU1QTEVfRklMRSIgXV07IHRoZW4KICAgICAgICB3cml0ZV9wcml2YXRlX2ZhaWx1cmUgMAogICAgICAgIHBlcnNpc3RfY2FtcGFpZ25fc3RhdGUgPi9kZXYvbnVsbCAyPiYxIHx8IHRydWUKICAgICAgZmkKICAgICAgcHVibGlzaF9zY2hlZHVsZWRfZXZpZGVuY2UgfHwgdHJ1ZQogICAgZWxzZQogICAgICBlbWl0X2RpcmVjdF9wdWJsaWMgIiRGSU5BTF9TVEFUVVNfQ0xBU1MiCiAgICBmaQogIGZpCiAgY2xlYW51cAogIHJldHVybiAiJHN0YXR1cyIKfQoKdHJhcCBmaW5hbGl6ZSBFWElUCmlmICEgT1VUUFVUX0ZJTEU9JCgiJE1LVEVNUF9CSU4iKTsgdGhlbgogIEZJTkFMX1NUQVRVU19DTEFTUz10b29saW5nX2ZhaWxlZAogIHBlcnNpc3RfZGlyZWN0X2ZhaWx1cmUgMCA+L2Rldi9udWxsIDI+JjEgfHwgZXhpdCAkPwogIGVtaXRfZGlyZWN0X3B1YmxpYyB0b29saW5nX2ZhaWxlZAogIGV4aXQgNzMKZmkKaWYgISBQVUJMSUNfRVZJREVOQ0VfRklMRT0kKCIkTUtURU1QX0JJTiIpOyB0aGVuCiAgRklOQUxfU1RBVFVTX0NMQVNTPXRvb2xpbmdfZmFpbGVkCiAgcGVyc2lzdF9kaXJlY3RfZmFpbHVyZSAwID4vZGV2L251bGwgMj4mMSB8fCBleGl0ICQ/CiAgZW1pdF9kaXJlY3RfcHVibGljIHRvb2xpbmdfZmFpbGVkCiAgZXhpdCA3MwpmaQppZiAhIFBSSVZBVEVfU0FNUExFX0ZJTEU9JCgiJE1LVEVNUF9CSU4iKTsgdGhlbgogIEZJTkFMX1NUQVRVU19DTEFTUz10b29saW5nX2ZhaWxlZAogIHBlcnNpc3RfZGlyZWN0X2ZhaWx1cmUgMCA+L2Rldi9udWxsIDI+JjEgfHwgZXhpdCAkPwogIHdyaXRlX3B1YmxpY19ldmlkZW5jZSB0b29saW5nX2ZhaWxlZAogIHB1Ymxpc2hfc2NoZWR1bGVkX2V2aWRlbmNlIHx8IHRydWUKICBleGl0IDczCmZpCkNMT1NFRF9EQVRFX1RPPSQoIiREQVRFX0JJTiIgLXUgLWQgInllc3RlcmRheSIgKyVGKQoKaWYgW1sgIiRDT05GSUdVUkVEX1NFTExFUl9JRCIgIT0gIiRBUFBST1ZFRF9TRUxMRVJfSUQiIF1dOyB0aGVuCiAgRklOQUxfU1RBVFVTX0NMQVNTPWV2aWRlbmNlX2ludmFsaWQKICBsb2dfZXZlbnQgZGFlbW9uLmVyciBydW50aW1lX3NlbGxlcl9pbnZhbGlkCiAgZXhpdCA2NApmaQoKaWYgISB2YWxpZF91dGNfZGF0ZSAiJFJBTkdFX1NUQVJUIiB8fAogICEgdmFsaWRfdXRjX2RhdGUgIiRBQ0NFUFRFRF9USFJPVUdIIiB8fAogIFtbICIkUkFOR0VfU1RBUlQiID4gIiRBQ0NFUFRFRF9USFJPVUdIIiBdXSB8fAogIFtbICIkUkFOR0VfU1RBUlQiID4gIiRBQ0NFUFRFRF9SQU5HRV9TVEFSVCIgXV0gfHwKICBbWyAiJEFDQ0VQVEVEX1RIUk9VR0giIDwgIiRBQ0NFUFRFRF9CQVNFTElORV9USFJPVUdIIiBdXSB8fAogIFtbICIkQUNDRVBURURfVEhST1VHSCIgPiAiJENMT1NFRF9EQVRFX1RPIiBdXSB8fAogIFtbICEgIiRDQU1QQUlHTl9JRCIgPX4gXltBLVphLXowLTkuXy1dezEsNjR9JCBdXTsgdGhlbgogIEZJTkFMX1NUQVRVU19DTEFTUz1ldmlkZW5jZV9pbnZhbGlkCiAgbG9nX2V2ZW50IGRhZW1vbi5lcnIgcnVudGltZV9jb25maWdfaW52YWxpZAogIGV4aXQgNjQKZmkKCmlmIFtbICEgLWQgIiRQTEFURk9STV9ST09UIiB8fCAhIC1mICIkQ09NUE9TRV9GSUxFIiBdXTsgdGhlbgogIEZJTkFMX1NUQVRVU19DTEFTUz1wcm9jZXNzX2ZhaWxlZAogIGxvZ19ldmVudCBkYWVtb24uZXJyIHJ1bnRpbWVfcGF0aF9taXNzaW5nCiAgZXhpdCA2NgpmaQoKY2QgIiRQTEFURk9STV9ST09UIgpzdGFydGVkX2Vwb2NoPSQoIiREQVRFX0JJTiIgKyVzKQoKaWYgIiRUSU1FT1VUX0JJTiIgLS1zaWduYWw9VEVSTSAtLWtpbGwtYWZ0ZXI9MzBzIDE3NXMgXAogICIkRE9DS0VSX0JJTiIgY29tcG9zZSAtLWZpbGUgIiRDT01QT1NFX0ZJTEUiIGV4ZWMgLVQgLS13b3JrZGlyIC9hcHAgXAogICAgLS1lbnYgIlpFTEVSREFUQV9ERVZPTFVDSU9ORVNfQ0FNUEFJR05fSUQ9JENBTVBBSUdOX0lEIiBzaGVldHMtd29ya2VyIFwKICAgIC9hcHAvLnZlbnYvYmluL3B5dGhvbiAtbSBpbmZyYS5vcGVyYXRpb25zLnplbGVyZGF0YV9yZWFkX21vZGVsX3JlY29uY2lsZSBcCiAgICAtLXNlbGxlci1pZCAiJFNFTExFUl9JRCIgXAogICAgLS1kYXRlLWZyb20gIiRSQU5HRV9TVEFSVCIgXAogICAgLS1kYXRlLXRvICIkQ0xPU0VEX0RBVEVfVE8iIFwKICAgIC0tcmVhZC1tb2RlbCBkZXZvbHVjaW9uZXMgXAogICAgLS13cml0ZSBcCiAgICAtLWNvbmZpcm0tYXBwcm92ZWQtcnVudGltZSBcCiAgICAtLWNvbmZpcm0tcHJvZHVjdGlvbi13cml0ZSBcCiAgICAtLXByaXZhdGUtc2NoZWR1bGVkLXRyYW5zcG9ydCA+ICIkT1VUUFVUX0ZJTEUiIDI+JjE7IHRoZW4KICBwcm9jZXNzX3N0YXR1cz0wCmVsc2UKICBwcm9jZXNzX3N0YXR1cz0kPwpmaQoKZmluaXNoZWRfZXBvY2g9JCgiJERBVEVfQklOIiArJXMpCndyYXBwZXJfZHVyYXRpb249JCgoZmluaXNoZWRfZXBvY2ggLSBzdGFydGVkX2Vwb2NoKSkKaWYgUFlUSE9OUEFUSD0iJFBMQVRGT1JNX1JPT1QiICIkUFlUSE9OX0JJTiIgXAogIC1tIGluZnJhLm9wZXJhdGlvbnMuemVsZXJkYXRhX3NjaGVkdWxlZF9ldmlkZW5jZSBcCiAgLS1pbnB1dCAiJE9VVFBVVF9GSUxFIiBcCiAgLS1jYW1wYWlnbi1pZCAiJENBTVBBSUdOX0lEIiBcCiAgLS1wcm9jZXNzLXN0YXR1cyAiJHByb2Nlc3Nfc3RhdHVzIiBcCiAgLS13cmFwcGVyLWR1cmF0aW9uLXNlY29uZHMgIiR3cmFwcGVyX2R1cmF0aW9uIiBcCiAgLS1wcml2YXRlLW91dHB1dCAiJFBSSVZBVEVfU0FNUExFX0ZJTEUiID4gIiRQVUJMSUNfRVZJREVOQ0VfRklMRSIgMj4vZGV2L251bGw7IHRoZW4KICBldmlkZW5jZV9zdGF0dXM9MAplbHNlCiAgZXZpZGVuY2Vfc3RhdHVzPSQ/CmZpCgppZiBbWyAhIC1zICIkUFVCTElDX0VWSURFTkNFX0ZJTEUiIHx8ICEgLXMgIiRQUklWQVRFX1NBTVBMRV9GSUxFIiBdXTsgdGhlbgogIHdyaXRlX3B1YmxpY19ldmlkZW5jZSBldmlkZW5jZV9pbnZhbGlkCiAgd3JpdGVfcHJpdmF0ZV9mYWlsdXJlICIkd3JhcHBlcl9kdXJhdGlvbiIKICBldmlkZW5jZV9zdGF0dXM9NjUKZmkKCmlmIHBlcnNpc3RfY2FtcGFpZ25fc3RhdGU7IHRoZW4KICBjYW1wYWlnbl9zdGF0dXM9MAplbHNlCiAgY2FtcGFpZ25fc3RhdHVzPSQ/CmZpCmlmIFtbICIkY2FtcGFpZ25fc3RhdHVzIiAhPSAiMCIgXV07IHRoZW4KICB3cml0ZV9wdWJsaWNfZXZpZGVuY2Ugc3RhdGVfZmFpbGVkCiAgZXZpZGVuY2Vfc3RhdHVzPSRjYW1wYWlnbl9zdGF0dXMKZmkKCmlmIHB1Ymxpc2hfc2NoZWR1bGVkX2V2aWRlbmNlOyB0aGVuCiAgcHVibGlzaF9zdGF0dXM9MAplbHNlCiAgcHVibGlzaF9zdGF0dXM9JD8KZmkKaWYgW1sgIiRwdWJsaXNoX3N0YXR1cyIgIT0gIjAiIF1dOyB0aGVuCiAgZXZpZGVuY2Vfc3RhdHVzPSRwdWJsaXNoX3N0YXR1cwpmaQoKaWYgW1sgIiRwcm9jZXNzX3N0YXR1cyIgPT0gIjAiICYmICIkZXZpZGVuY2Vfc3RhdHVzIiA9PSAiMCIgXV07IHRoZW4KICBGSU5BTF9TVEFUVVNfQ0xBU1M9c3VjY2VzcwogIGxvZ19ldmVudCBkYWVtb24uaW5mbyByZWNvbmNpbGlhdGlvbl9zdWNjZWVkZWQKICBleGl0IDAKZmkKCkZJTkFMX1NUQVRVU19DTEFTUz1wcm9jZXNzX2ZhaWxlZApsb2dfZXZlbnQgZGFlbW9uLmVyciByZWNvbmNpbGlhdGlvbl9mYWlsZWQKaWYgW1sgIiRldmlkZW5jZV9zdGF0dXMiICE9ICIwIiBdXTsgdGhlbgogIGV4aXQgIiRldmlkZW5jZV9zdGF0dXMiCmZpCmV4aXQgIiRwcm9jZXNzX3N0YXR1cyIK'
printf '%s' "$RECONCILE_WRAPPER_B64" | base64 --decode > /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh
unset RECONCILE_WRAPPER_B64
chmod 0755 /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh

cat > /etc/systemd/system/zelerdata-devoluciones-reconcile.service << 'UNIT'
[Unit]
Description=Renew the enclosing closed UTC range for ZELERDATA DEVOLUCIONES
Wants=network-online.target
Requires=docker.service
After=docker.service network-online.target
OnFailure=zelerdata-devoluciones-reconcile-alert.service

[Service]
Type=oneshot
WorkingDirectory=/opt/zeler-platform
Environment=ZELERDATA_DEVOLUCIONES_RANGE_START=2026-06-01
Environment=ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH=2026-07-09
Environment=ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID=candidate-r8-initial
EnvironmentFile=-/etc/zeler-platform/zelerdata-devoluciones-reconcile.env
Environment=ZELERDATA_DEVOLUCIONES_SELLER_ID=82453304
ExecStart=/opt/zeler-platform/zelerdata-devoluciones-reconcile.sh
TimeoutStartSec=8m
Restart=no
StandardOutput=journal
StandardError=journal
SyslogIdentifier=zelerdata-devoluciones-reconcile
UNIT

cat > /etc/systemd/system/zelerdata-devoluciones-reconcile.timer << 'UNIT'
[Unit]
Description=Renew closed-range ZELERDATA DEVOLUCIONES readiness before its lease expires

[Timer]
OnCalendar=*-*-* *:00,10,20,30,40,50:00 UTC
RandomizedDelaySec=1m
AccuracySec=30s
Persistent=true
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
