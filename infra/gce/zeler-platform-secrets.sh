#!/usr/bin/env bash
# zeler-platform-secrets.sh — installed at /opt/zeler-platform/zeler-platform-secrets.sh
#
# Systemd oneshot (Before=docker.service):
#   Fetches 12 secrets from Secret Manager via the VM-attached SA (metadata-server token)
#   and writes per-service env files under /opt/zeler-platform/env/<service>.env
#   with mode 0600, owner root.
#
# Services covered (12 env files):
#   mongo, caddy, gateway,
#   repricer-api, repricer-worker,
#   sheets-api, sheets-worker,
#   publicador-api,
#   autoreply-api, autoreply-worker,

set -euo pipefail

ENV_DIR=/opt/zeler-platform/env

# umask 077 → new files get mode 600 automatically
umask 077
mkdir -p "$ENV_DIR"

# Helper: fetch secret from Secret Manager
s() { gcloud secrets versions access latest --secret="$1"; }

# ---------------------------------------------------------------------------
# Fetch all secrets upfront so any failure aborts before any file is written
# ---------------------------------------------------------------------------
echo "Fetching secrets from Secret Manager …"

MONGO_URI=$(s mongo-uri-prod)
RABBITMQ_URL=$(s cloudamqp-url)
RABBITMQ_MANAGEMENT_URL=$(s cloudamqp-management-url)
MELI_CLIENT_ID=$(s meli-client-id)
MELI_CLIENT_SECRET=$(s meli-client-secret)
GOOGLE_CLIENT_ID=$(s google-oauth-client-id)
GOOGLE_CLIENT_SECRET=$(s google-oauth-client-secret)
MONGO_ADMIN_USER=$(s mongo-admin-user)
MONGO_ADMIN_PASSWORD=$(s mongo-admin-password)
ZELER_APP_BROKER_SECRET=$(s zeler-app-broker-secret)
EXTENSION_TOKEN_PEPPER=$(s extension-token-pepper)
MELI_ALLOWED_IPS=$(s meli-allowed-ips)

echo "All secrets fetched."

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MONGO_DB=zeler_platform_prod
GOOGLE_CLOUD_PROJECT=zeler-platform-dev
KMS_PROJECT_ID=zeler-platform-dev
KMS_LOCATION=us-central1
KMS_KEYRING=zeler-platform
GATEWAY_PROXY_BASE_URL=http://gateway:8080/proxy/meli
GATEWAY_SERVICE_ROOT_URL=http://gateway:8080
SHEETS_API_SERVICE_ROOT_URL=http://sheets-api:8080

# ---------------------------------------------------------------------------
# write <service> <KEY=VALUE> …
# ---------------------------------------------------------------------------
write() {
  local svc="$1"
  shift
  local f="$ENV_DIR/$svc.env"
  printf '%s\n' "$@" > "$f"
  chmod 600 "$f"
  echo "Written: $f"
}

# Shared BASE variables injected into most services
BASE=(
  "MONGO_URI=$MONGO_URI"
  "MONGO_DB=$MONGO_DB"
  "RABBITMQ_URL=$RABBITMQ_URL"
  "GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT"
  "KMS_PROJECT_ID=$KMS_PROJECT_ID"
  "KMS_LOCATION=$KMS_LOCATION"
  "KMS_KEYRING=$KMS_KEYRING"
)

# ---------------------------------------------------------------------------
# mongo — init credentials only (no BASE, mongo doesn't need app env)
# ---------------------------------------------------------------------------
write mongo \
  "MONGO_INITDB_ROOT_USERNAME=$MONGO_ADMIN_USER" \
  "MONGO_INITDB_ROOT_PASSWORD=$MONGO_ADMIN_PASSWORD"

# ---------------------------------------------------------------------------
# caddy — no runtime secrets; empty file placeholder
# ---------------------------------------------------------------------------
write caddy \
  "# Caddy has no runtime secrets — this file is a placeholder"

# ---------------------------------------------------------------------------
# gateway — BASE + Meli OAuth + KMS keys + proxy policy
# ---------------------------------------------------------------------------
write gateway \
  "${BASE[@]}" \
  "MELI_CLIENT_ID=$MELI_CLIENT_ID" \
  "MELI_CLIENT_SECRET=$MELI_CLIENT_SECRET" \
  "MELI_REDIRECT_URI=https://gateway.zeler.ai/oauth/callback" \
  "OAUTH_SUCCESS_URL=https://app.zeler.ai/accounts/linked" \
  "KMS_MELI_TOKENS_KEY=meli-tokens" \
  "KMS_PLATFORM_JWT_KEY=platform-jwt" \
  "ZELER_APP_BROKER_SECRET=$ZELER_APP_BROKER_SECRET" \
  "MELI_ALLOWED_IPS=$MELI_ALLOWED_IPS"

# ---------------------------------------------------------------------------
# Module APIs that only need BASE plus the gateway endpoint
# ---------------------------------------------------------------------------
for svc in repricer-api publicador-api autoreply-api; do
  write "$svc" \
    "${BASE[@]}" \
    "GATEWAY_BASE_URL=$GATEWAY_PROXY_BASE_URL"
done

# ---------------------------------------------------------------------------
# sheets-api — BASE + Google OAuth + KMS google-tokens + extension token pepper
# ---------------------------------------------------------------------------
write sheets-api \
  "${BASE[@]}" \
  "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_CLIENT_ID" \
  "GOOGLE_OAUTH_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET" \
  "GOOGLE_OAUTH_REDIRECT_URI=https://sheets.zeler.ai/oauth/google/callback" \
  "EXTENSION_TOKEN_PEPPER=$EXTENSION_TOKEN_PEPPER" \
  "KMS_GOOGLE_TOKENS_KEY=google-tokens" \
  "GATEWAY_BASE_URL=$GATEWAY_PROXY_BASE_URL"

# ---------------------------------------------------------------------------
# sheets-worker — BASE + Google OAuth + KMS google-tokens
# ---------------------------------------------------------------------------
write sheets-worker \
  "${BASE[@]}" \
  "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_CLIENT_ID" \
  "GOOGLE_OAUTH_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET" \
  "GOOGLE_OAUTH_REDIRECT_URI=https://sheets.zeler.ai/oauth/google/callback" \
  "KMS_GOOGLE_TOKENS_KEY=google-tokens" \
  "GATEWAY_BASE_URL=$GATEWAY_PROXY_BASE_URL" \
  "RABBITMQ_MANAGEMENT_URL=$RABBITMQ_MANAGEMENT_URL" \
  "GATEWAY_URL=$GATEWAY_SERVICE_ROOT_URL" \
  "SHEETS_URL=$SHEETS_API_SERVICE_ROOT_URL" \
  "SHEETS_SYNC_JOBS_POLLER_ENABLED=true" \
  "ZELERDATA_ENRICHMENT_ENABLED=true" \
  "ZELERDATA_SALE_PRICE_ENABLED=true" \
  "ZELERDATA_LISTING_FIXED_FEE_ENABLED=true"

# ---------------------------------------------------------------------------
# Workers that call gateway proxy with minted JWT/KMS auth
# ---------------------------------------------------------------------------
for svc in repricer-worker autoreply-worker; do
  write "$svc" \
    "${BASE[@]}" \
    "GATEWAY_BASE_URL=$GATEWAY_PROXY_BASE_URL"
done

echo "All env files written to $ENV_DIR"
