#!/usr/bin/env bash
# zeler-platform-secrets.sh — installed at /opt/zeler-platform/zeler-platform-secrets.sh
#
# Systemd oneshot (Before=docker.service):
#   Fetches 9 secrets from Secret Manager via the VM-attached SA (metadata-server token)
#   and writes per-service env files under /opt/zeler-platform/env/<service>.env
#   with mode 0600, owner root.
#
# Services covered (12 env files):
#   mongo, caddy, gateway,
#   repricer-api, repricer-worker,
#   sheets-api, sheets-worker,
#   publicador-api,
#   autoreply-api, autoreply-worker,
#   fulldock-api, fulldock-worker

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
MELI_CLIENT_ID=$(s meli-client-id)
MELI_CLIENT_SECRET=$(s meli-client-secret)
GOOGLE_CLIENT_ID=$(s google-oauth-client-id)
GOOGLE_CLIENT_SECRET=$(s google-oauth-client-secret)
MONGO_ADMIN_USER=$(s mongo-admin-user)
MONGO_ADMIN_PASSWORD=$(s mongo-admin-password)
GATEWAY_INTERNAL_TOKEN=$(s gateway-internal-token)

echo "All secrets fetched."

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MONGO_DB=zeler_platform_prod
GOOGLE_CLOUD_PROJECT=zeler-platform-dev
KMS_PROJECT_ID=zeler-platform-dev
KMS_LOCATION=us-central1
KMS_KEYRING=zeler-platform

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
# gateway — BASE + Meli OAuth + KMS keys + internal gateway token
# ---------------------------------------------------------------------------
write gateway \
  "${BASE[@]}" \
  "MELI_CLIENT_ID=$MELI_CLIENT_ID" \
  "MELI_CLIENT_SECRET=$MELI_CLIENT_SECRET" \
  "MELI_REDIRECT_URI=https://gateway.zeler.ai/oauth/callback" \
  "KMS_MELI_TOKENS_KEY=meli-tokens" \
  "KMS_PLATFORM_JWT_KEY=platform-jwt" \
  "GATEWAY_TOKEN=$GATEWAY_INTERNAL_TOKEN"

# ---------------------------------------------------------------------------
# Module APIs that only need BASE (+ gateway token for proxy calls)
# ---------------------------------------------------------------------------
for svc in repricer-api publicador-api autoreply-api fulldock-api; do
  write "$svc" \
    "${BASE[@]}" \
    "GATEWAY_BASE_URL=http://gateway:8080" \
    "GATEWAY_TOKEN=$GATEWAY_INTERNAL_TOKEN"
done

# ---------------------------------------------------------------------------
# sheets-api + sheets-worker — BASE + Google OAuth + KMS google-tokens
# ---------------------------------------------------------------------------
for svc in sheets-api sheets-worker; do
  write "$svc" \
    "${BASE[@]}" \
    "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_CLIENT_ID" \
    "GOOGLE_OAUTH_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET" \
    "GOOGLE_OAUTH_REDIRECT_URI=https://sheets.zeler.ai/oauth/google/callback" \
    "KMS_GOOGLE_TOKENS_KEY=google-tokens" \
    "GATEWAY_BASE_URL=http://gateway:8080" \
    "GATEWAY_TOKEN=$GATEWAY_INTERNAL_TOKEN"
done

# ---------------------------------------------------------------------------
# Workers that call gateway proxy
# ---------------------------------------------------------------------------
for svc in repricer-worker autoreply-worker fulldock-worker; do
  write "$svc" \
    "${BASE[@]}" \
    "GATEWAY_BASE_URL=http://gateway:8080" \
    "GATEWAY_TOKEN=$GATEWAY_INTERNAL_TOKEN"
done

echo "All env files written to $ENV_DIR"
