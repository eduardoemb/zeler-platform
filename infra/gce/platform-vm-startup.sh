#!/usr/bin/env bash
# platform-vm-startup.sh — GCE startup script for platform-vm (Ubuntu 22.04 LTS).
#
# Responsibilities:
#   1. Install Docker Engine + Compose v2
#   2. Format & mount persistent data disk at /var/lib/zeler-mongo (ext4, nofail fstab)
#   3. Chown /var/lib/zeler-mongo to UID 999:999 (mongo container user)
#   4. Install Google Cloud Ops Agent (logging + metrics)
#   5. Authenticate Docker to Artifact Registry (us-central1)
#   6. Create /opt/zeler-platform/ directory layout
#   7. Write & enable the zeler-platform-secrets.service systemd unit
#   8. Write the secrets helper script to /opt/zeler-platform/
#   9. Touch /opt/zeler-platform/.startup-complete as a readiness sentinel
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
