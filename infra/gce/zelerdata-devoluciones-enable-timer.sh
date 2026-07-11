#!/usr/bin/env bash
set -euo pipefail

PLATFORM_ROOT=${ZELER_PLATFORM_ROOT:-/opt/zeler-platform}
PYTHON_BIN=${ZELER_PYTHON_BIN:-/usr/bin/python3}
SYSTEMCTL_BIN=${ZELER_SYSTEMCTL_BIN:-/usr/bin/systemctl}
CAMPAIGN_STATE_FILE=${ZELERDATA_DEVOLUCIONES_CAMPAIGN_STATE_FILE:-/var/lib/zeler-platform/zelerdata-devoluciones-campaign.json}
SERVICE_NAME=zelerdata-devoluciones-reconcile.service
service_environment=$(mktemp)
confirmed_environment=$(mktemp)
cleanup() {
  rm -f "$service_environment" "$confirmed_environment"
}
trap cleanup EXIT

if ! "$SYSTEMCTL_BIN" show "$SERVICE_NAME" --property=Environment --value \
  > "$service_environment"; then
  echo "ERROR: DEVOLUCIONES service campaign configuration is unavailable." >&2
  exit 1
fi

if ! PYTHONPATH="$PLATFORM_ROOT" "$PYTHON_BIN" \
  -m infra.operations.zelerdata_campaign_state require-accepted \
  --state-file "$CAMPAIGN_STATE_FILE" \
  --service-environment-file "$service_environment" >/dev/null 2>&1; then
  echo "ERROR: DEVOLUCIONES timing campaign is not durably accepted." >&2
  exit 1
fi

if ! "$SYSTEMCTL_BIN" show "$SERVICE_NAME" --property=Environment --value \
  > "$confirmed_environment" || ! cmp -s "$service_environment" "$confirmed_environment"; then
  echo "ERROR: DEVOLUCIONES service campaign configuration changed during preflight." >&2
  exit 1
fi

"$SYSTEMCTL_BIN" enable --now zelerdata-devoluciones-reconcile.timer
echo "DEVOLUCIONES timer enabled after durable campaign acceptance."
