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

min_free_kib=$((MIN_FREE_GIB * 1024 * 1024))

free_root_kib() {
  df -Pk / | awk 'NR == 2 {print $4}'
}

require_free_space() {
  local free_kib=$1
  (( free_kib >= min_free_kib ))
}

print_usage() {
  echo "Root filesystem usage:"
  df -h /
}

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
cat > /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh << 'SCRIPT'
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
SCRIPT
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
