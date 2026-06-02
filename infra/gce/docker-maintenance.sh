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
