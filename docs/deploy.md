# Platform GCE VM Deploy — Operator Runbook

> **Stack**: Ubuntu 22.04 LTS · Docker Compose · Caddy auto-TLS · MongoDB 7.0 RS  
> **VM**: `platform-vm` · Zone: `us-central1-a` · Project: `zeler-platform-dev`  
> **Domain**: `zeler.ai` · DNS: Squarespace · 5 public subdomains

---

## 1. Initial Provisioning (idempotent)

Run all commands from your local terminal with `gcloud` authenticated as project owner.  
Each command is idempotent — safe to re-run if interrupted.

```bash
PROJECT=zeler-platform-dev
REGION=us-central1
ZONE=us-central1-a
SA=platform-vm-sa@${PROJECT}.iam.gserviceaccount.com

# Reserve static IP
gcloud compute addresses create platform-vm-ip --region=$REGION --project=$PROJECT

# Create service account
gcloud iam service-accounts create platform-vm-sa \
  --display-name="Platform VM SA" --project=$PROJECT

# IAM — KMS access for meli-tokens and google-tokens
for KEY in meli-tokens google-tokens; do
  gcloud kms keys add-iam-policy-binding $KEY \
    --keyring=zeler-platform --location=$REGION \
    --member="serviceAccount:$SA" \
    --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
    --project=$PROJECT
done

# IAM — project-level roles
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role=roles/artifactregistry.reader
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role=roles/logging.logWriter
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role=roles/monitoring.metricWriter

# Enable Sheets API
gcloud services enable sheets.googleapis.com --project=$PROJECT

# Create KMS key google-tokens (meli-tokens already exists)
gcloud kms keys create google-tokens \
  --keyring=zeler-platform --location=$REGION \
  --purpose=encryption --project=$PROJECT

# Create Artifact Registry repo
gcloud artifacts repositories create zeler-platform \
  --repository-format=docker --location=$REGION --project=$PROJECT

# Create persistent data disk for Mongo
gcloud compute disks create zeler-mongo-data \
  --size=50GB --type=pd-balanced --zone=$ZONE --project=$PROJECT

# Create VM with startup script
gcloud compute instances create platform-vm \
  --zone=$ZONE \
  --machine-type=e2-medium \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --boot-disk-type=pd-balanced \
  --disk=name=zeler-mongo-data,device-name=mongo-data,mode=rw,boot=no \
  --address=platform-vm-ip \
  --service-account=$SA \
  --scopes=cloud-platform \
  --tags=platform-vm,http-server,https-server \
  --metadata-from-file=startup-script=infra/gce/platform-vm-startup.sh \
  --project=$PROJECT

# Firewall rules
gcloud compute firewall-rules create allow-platform-https \
  --allow tcp:443 --target-tags=platform-vm \
  --source-ranges=0.0.0.0/0 --project=$PROJECT
gcloud compute firewall-rules create allow-platform-http \
  --allow tcp:80 --target-tags=platform-vm \
  --source-ranges=0.0.0.0/0 --project=$PROJECT
gcloud compute firewall-rules create allow-platform-ssh \
  --allow tcp:22 --target-tags=platform-vm \
  --source-ranges=35.235.240.0/20 --project=$PROJECT  # IAP only
```

### Verify provisioning

```bash
# IP reserved
gcloud compute addresses describe platform-vm-ip --region=$REGION --project=$PROJECT

# VM running
gcloud compute instances describe platform-vm --zone=$ZONE \
  --format="value(status)" --project=$PROJECT  # → RUNNING

# SSH via IAP
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT

# Inside VM — verify startup complete
test -f /opt/zeler-platform/.startup-complete && echo OK
df -h /var/lib/zeler-mongo          # mounted disk ≥40 GB available
docker --version
docker compose version
```

---

## 2. Image Build & Push (Cloud Build — NEVER local)

**Important**: Always use Cloud Build. Never `docker build` locally on Mac.

```bash
AR=us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform
TAG=rollout-v1

build() {
  local svc=$1 dockerfile=$2
  gcloud builds submit \
    --tag "$AR/$svc:$TAG" \
    --config=- <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  args: ['build', '-f', '$dockerfile', '-t', '$AR/$svc:$TAG', '.']
images: ['$AR/$svc:$TAG']
EOF
}

# Sequential (add & after each to parallelize if build quota allows)
build gateway           gateway/Dockerfile
build repricer-api      modules/repricer/Dockerfile.api
build repricer-worker   modules/repricer/Dockerfile.worker
build sheets-api        modules/sheets/Dockerfile.api
build sheets-worker     modules/sheets/Dockerfile.worker
build autoreply-api     modules/autoreply/Dockerfile.api
build autoreply-worker  modules/autoreply/Dockerfile.worker
build publicador-api    modules/publicador/Dockerfile.api
```

**Parallel one-liner** (use when quota > 10 concurrent builds):

```bash
for svc_df in \
  "gateway:gateway/Dockerfile" \
  "repricer-api:modules/repricer/Dockerfile.api" \
  "repricer-worker:modules/repricer/Dockerfile.worker" \
  "sheets-api:modules/sheets/Dockerfile.api" \
  "sheets-worker:modules/sheets/Dockerfile.worker" \
  "autoreply-api:modules/autoreply/Dockerfile.api" \
  "autoreply-worker:modules/autoreply/Dockerfile.worker" \
  "publicador-api:modules/publicador/Dockerfile.api"
do
  svc="${svc_df%%:*}"; dockerfile="${svc_df##*:}"
  build "$svc" "$dockerfile" &
done
wait
echo "All builds complete"
```

### Verify images

```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform \
  --project=$PROJECT
# Expect 10 images all tagged rollout-v1
```

---

## 3. First-Time Mongo Cutover (10 ordered steps)

⚠️ **Window**: ~15–30 min downtime. Coordinate with team. PC Mongo MUST remain running on standby for ≥7 days post-cutover.

### Step 1 — Pre-cutover parity snapshot (on PC)

```bash
# Verify PC Mongo is healthy
uv run python infra/mongo/smoke_prod.py  # must exit 0

# Capture per-collection counts
mongosh "$MONGO_URI" --quiet --eval '
db.getMongo().getDBs().databases.forEach(d => {
  if (!["admin","config","local"].includes(d.name)) {
    db.getSiblingDB(d.name).getCollectionNames().forEach(c =>
      print(d.name + "." + c + "=" + db.getSiblingDB(d.name)[c].countDocuments({}))
    )
  }
})' > parity_pc.txt
cat parity_pc.txt
```

### Step 2 — Stop writers (keep reads alive)

Stop gateway and all workers **on PC**. Reads (Meli webhooks via PC-local URLs) can still flow briefly.

### Step 3 — Dump (on PC)

```bash
mongodump --uri="$MONGO_URI" --archive=zeler_platform_prod.archive --gzip
sha256sum zeler_platform_prod.archive > zeler_platform_prod.archive.sha256
ls -lh zeler_platform_prod.archive  # must be > 0 bytes
```

### Step 4 — Transfer to VM

```bash
gcloud compute scp --tunnel-through-iap --zone=us-central1-a \
  zeler_platform_prod.archive \
  zeler_platform_prod.archive.sha256 \
  platform-vm:/tmp/ --project=$PROJECT
```

### Step 5 — Verify integrity on VM

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sha256sum -c /tmp/zeler_platform_prod.archive.sha256"
# Must print: zeler_platform_prod.archive: OK
```

### Step 6 — Start Mongo only + write env files

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT << 'EOF'
# Copy compose file and Caddyfile to /opt/zeler-platform/
# (if not already deployed via git pull / scp)
sudo systemctl start zeler-platform-secrets.service
sudo systemctl status zeler-platform-secrets.service  # must show active (exited)
cd /opt/zeler-platform && sudo docker compose up -d mongo
# Wait for healthcheck
sudo docker compose ps
EOF
```

### Step 7 — Init replica set (first boot only)

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="docker exec zeler-platform-mongo-1 \
    mongosh --quiet --eval 'rs.initiate({_id:\"rs0\",members:[{_id:0,host:\"mongo:27017\"}]})'"
# Verify: rs.status().myState == 1
```

### Step 8 — Restore dump

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="docker exec -i zeler-platform-mongo-1 \
    mongorestore \
    --uri='\$MONGO_URI' \
    --archive=/tmp/zeler_platform_prod.archive \
    --gzip \
    --drop"
```

### Step 9 — Post-restore parity check

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="docker exec zeler-platform-mongo-1 mongosh --quiet --eval '
db.getMongo().getDBs().databases.forEach(d => {
  if ([\"admin\",\"config\",\"local\"].includes(d.name)) return;
  db.getSiblingDB(d.name).getCollectionNames().forEach(c =>
    print(d.name + \".\" + c + \"=\" + db.getSiblingDB(d.name)[c].countDocuments({}))
  )
})' > /tmp/parity_vm.txt && diff /tmp/parity_pc.txt /tmp/parity_vm.txt"
# Must produce empty diff
```

### Step 10 — Apply Mongo validators and check drift

Run validators after the restore and before the traffic flip/startup. The apply step is
non-destructive for document data; it updates collection validators and idempotent indexes.

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && \
    python -m infra.mongo.apply_validators --mongo-uri=\"$MONGO_URI\" && \
    python -m infra.mongo.drift_check --mongo-uri=\"$MONGO_URI\""
```

Expected output: `apply_validators` reports created/applied/unchanged collections, and
`drift_check` exits 0 with each collection status `applied`. If drift is reported, do not
start writers; inspect the reported collection and re-run after correcting the schema or live
validator.

Equivalent local commands when already inside the deployment shell:

```bash
python -m infra.mongo.apply_validators --mongo-uri="$MONGO_URI"
python -m infra.mongo.drift_check --mongo-uri="$MONGO_URI"
```

Rollback: validators do not mutate document data. If a validator must be removed, run a guarded
`collMod` setting `validator: {}` for the affected collection, then restore the previous schema
file and re-run the drift check.

### Step 11 — Start full stack

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && sudo docker compose up -d"
```

---

## 4. Google OAuth Setup (Sheets pass-2)

Sheets API boots in pass-1 with placeholder OAuth credentials and returns HTTP 503 on `/oauth/google/authorize`. Complete pass-2 after VM is running:

1. **GCP Console → APIs & Services → Credentials → Create OAuth Client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: `https://sheets.zeler.ai/oauth/google/callback`
   - Click **Create**; copy **Client ID** and **Client Secret**

2. **Update secrets**:
   ```bash
   printf "<client_id>" | gcloud secrets versions add google-oauth-client-id \
     --data-file=- --project=$PROJECT
   printf "<client_secret>" | gcloud secrets versions add google-oauth-client-secret \
     --data-file=- --project=$PROJECT
   ```

3. **Restart secrets + sheets**:
   ```bash
   gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
     --command="sudo systemctl restart zeler-platform-secrets.service && \
       cd /opt/zeler-platform && sudo docker compose up -d sheets-api sheets-worker"
   ```

4. **Verify pass-2**:
   ```bash
   curl -sI "https://sheets.zeler.ai/oauth/google/authorize?seller_id=test"
   # Must return HTTP 302 with Location: accounts.google.com
   ```

---

## 5. Re-deploy a Single Service

```bash
TAG=rollout-v2  # or whatever new tag was built

gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && \
    sudo docker compose pull <service> && \
    sudo docker compose up -d --no-deps <service>"
```

For env-only changes (no new image):

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sudo systemctl restart zeler-platform-secrets.service && \
    cd /opt/zeler-platform && sudo docker compose up -d --force-recreate <service>"
```

---

## 5b. Bootstrap Cloud Run Job rollout

`zeler-bootstrap` is deployed by Cloud Build from `infra/cloudbuild/bootstrap-job.yaml`. Before
submitting the build, export a sanitized binding contract for preflight:

```bash
export CLOUD_RUN_SECRET_BINDINGS_EXPORT='{
  "jobs": {
    "zeler-bootstrap": {
      "env": {
        "ZELER_ENV": "prod",
        "BOOTSTRAP_MONGO_DB": "zeler_platform_prod",
        "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.zeler.ai",
        "BOOTSTRAP_GATEWAY_PATH_PREFIX": "/proxy/meli",
        "BOOTSTRAP_MODULE_ID": "bootstrap",
        "BOOTSTRAP_RABBITMQ_EXCHANGE": "meli.events"
      },
      "secrets": {
        "BOOTSTRAP_MONGO_URI": "mongo-uri-prod:latest",
        "BOOTSTRAP_RABBITMQ_URL": "cloudamqp-url:latest"
      },
      "vpc_connector": "projects/zeler-platform-dev/locations/us-central1/connectors/zeler-platform-serverless",
      "vpc_egress": "private-ranges-only",
      "service_account": "zeler-bootstrap-runtime@zeler-platform-dev.iam.gserviceaccount.com",
      "iam_prerequisites": [
        "roles/secretmanager.secretAccessor",
        "roles/vpcaccess.user",
        "roles/cloudkms.signerVerifier"
      ]
    }
  }
}'
uv run python -m infra.deploy.preflight
```

Rollout checklist:

1. Create/confirm Secret Manager secrets `mongo-uri-prod` and `cloudamqp-url`; do not print values.
2. Create/confirm `zeler-bootstrap-runtime` and grant Secret Manager accessor, VPC connector use,
   and KMS signer/verifier on `platform-jwt`.
3. Confirm Serverless VPC connector and egress mode. The default is `private-ranges-only`; use
   `all-traffic` only with intentional NAT/private routing.
4. Confirm Mongo is published on the VM private IP only (`MONGO_PRIVATE_BIND_IP=<vm-internal-ip>`
   in `/opt/zeler-platform/.env`) and firewall allows TCP 27017 only from the Serverless VPC
   Access connector range.
5. Confirm `module_registry` contains enabled module `bootstrap` with GET proxy scopes.
6. Run preflight above, then deploy with Cloud Build.
7. Execute one dry-run and one controlled seller job before broad use.

Rollback: redeploy the previous bootstrap job image/config. If only bindings changed, restore the
previous `CLOUD_RUN_SECRET_BINDINGS_EXPORT`/substitution values and redeploy the job without
running live bootstrap execution.

---

## 5c. zeler-app live integration runtime config + VM-only validation

This checklist connects the existing Vercel `zeler-app` deployment to the live platform APIs for
seller `82453304`. Do not create another frontend. Do not query production Mongo from local.
Mongo registry validation and updater execution must happen from GCP project `zeler-platform-dev`,
VM `platform-vm`, zone `us-central1-a`, using the deployed runtime env files only.

### Runtime env contract

Configure the app runtime with these server env values:

| Runtime | Variable | Value / source |
|---------|----------|----------------|
| `zeler-app` | `ZELER_GATEWAY_URL` | `https://gateway.zeler.ai` |
| `zeler-app` | `REPRICER_API_URL` | `https://repricer.zeler.ai` |
| `zeler-app` | `SHEETS_API_URL` | `https://sheets.zeler.ai` |
| `zeler-app` | `PUBLICADOR_API_URL` | `https://publicador.zeler.ai` |
| `zeler-app` | `AUTOREPLY_API_URL` | `https://autoreply.zeler.ai` |
| `gateway` | `OAUTH_SUCCESS_URL` | `https://app.zeler.ai/accounts/linked` |
| `zeler-app` + `gateway` | `ZELER_APP_BROKER_SECRET` | Secret Manager secret `zeler-app-broker-secret`; values must match exactly. |
| `gateway` updater context | `ZELER_APP_ALLOWED_PLATFORM_USER_IDS` | Optional comma-separated platform-user rollout allowlist for `module_registry._id="zeler-app"`; use sanitized IDs only in operator logs. |

`ZELER_APP_BROKER_SECRET` is server-only. Never configure it as `NEXT_PUBLIC_*`, never print it,
and never paste it into local shells. The gateway receives it through
`infra/gce/zeler-platform-secrets.sh`; Vercel/hosting receives the same secret through its encrypted
runtime secret store.

`OAUTH_SUCCESS_URL` is not secret, but it is runtime-critical: without it, the gateway falls back to
the local default `https://app.zeler.local/accounts/linked` after a successful MercadoLibre OAuth
callback. Production gateway env must set it to the live app linked-accounts route above before an
operator runs the OAuth account-linking smoke.

`zeler-app` must send the authenticated server-derived `platform_user_id` in the signed
`/internal/tokens/issue` JSON body when requesting `module_admin` tokens. The gateway authorizes that
user against `allowed_platform_user_ids` and an active linked `meli_accounts` seller. Deprecated
`allowed_seller_ids` remains only as a rollout fallback for old signed requests that do not include
`platform_user_id`; if a signed request includes a non-allowed user, the seller fallback must not grant
access.

### Create or rotate the broker secret

Run from a local operator shell only to add a secret version; do not echo the value back:

```bash
PROJECT=zeler-platform-dev
printf '<new-broker-secret>' | gcloud secrets versions add zeler-app-broker-secret \
  --data-file=- --project=$PROJECT
```

Then refresh the gateway env on the VM:

```bash
ZONE=us-central1-a
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sudo systemctl restart zeler-platform-secrets.service && \
    cd /opt/zeler-platform && sudo docker compose up -d --force-recreate gateway"
```

### VM-only registry updater and validation

Do not print MONGO_URI. Use the gateway runtime env file on the VM and run the idempotent updater
from `/opt/zeler-platform`:

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=us-central1-a \
  --project=zeler-platform-dev --command="cd /opt/zeler-platform && \
    sudo python3 - <<'PY'
import os

from infra.mongo.operations.ensure_zeler_app_admin_client import main

with open('/opt/zeler-platform/env/gateway.env', encoding='utf-8') as env_file:
    for line in env_file:
        if not line.strip() or line.startswith('#') or '=' not in line:
            continue
        key, value = line.rstrip('\n').split('=', 1)
        os.environ[key] = value

main()
PY"
```

Expected output: `zeler-app admin client updated`. The updater reads
`ZELER_APP_ALLOWED_PLATFORM_USER_IDS` when present, otherwise preserves the existing platform-user
allowlist. It also preserves the deprecated `allowed_seller_ids` fallback for rollout compatibility.
The command must not print `MONGO_URI` or any secret value.

Validate the registry document shape from the same VM/VPC boundary without exposing secrets:

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=us-central1-a \
  --project=zeler-platform-dev --command="cd /opt/zeler-platform && \
    sudo python3 - <<'PY'
import os
import json

from pymongo import MongoClient

with open('/opt/zeler-platform/env/gateway.env', encoding='utf-8') as env_file:
    for line in env_file:
        if not line.strip() or line.startswith('#') or '=' not in line:
            continue
        key, value = line.rstrip('\n').split('=', 1)
        os.environ[key] = value

client = MongoClient(os.environ['MONGO_URI'])
try:
    doc = client.get_default_database()['module_registry'].find_one({'_id': 'zeler-app'}) or {}
    print(json.dumps({
        '_id': doc.get('_id'),
        'status': doc.get('status'),
        'allowed_platform_user_ids': doc.get('allowed_platform_user_ids'),
        'allowed_seller_ids': doc.get('allowed_seller_ids'),
        'allowed_meli_scopes': doc.get('allowed_meli_scopes'),
    }, sort_keys=True))
finally:
    client.close()
PY"
```

Expected JSON contains `_id: "zeler-app"`, `status: "enabled"`, an
`allowed_platform_user_ids` list, deprecated `allowed_seller_ids: [82453304]` only while the rollout
fallback is needed, and exactly `admin:repricer`, `admin:sheets`, `admin:publicador`, and
`admin:autoreply`.
Fulldock is intentionally decommissioned and must not appear as `admin:fulldock`.

### Safe smoke sequence for seller `82453304`

1. Public health, read-only:
   ```bash
   for s in gateway repricer sheets publicador autoreply; do
     curl -fsS "https://${s}.zeler.ai/health" >/dev/null && echo "$s OK"
   done
   ```
2. Open `zeler-app` with a real authenticated app session and the pilot seller selected. If the UI
   needs manual browser auth, record that blocker rather than inventing a session.
3. Smoke these routes for seller `82453304`: `/accounts`, `/bootstrap/<known-job-id>`,
   `/repricer/catalog`, `/sheets/config`, `/publicador/drafts`, `/autoreply/templates`.
   Valid results are data, an explicit empty state, or a clearly documented
   account-linking/data blocker. `/fulldock/rules` should remain unavailable because Fulldock is retired.
4. Do not run create/update/delete module actions during smoke unless a separate rollout plan
   explicitly authorizes that mutation.
5. Check gateway/module logs for 401/403/412 spikes and token issuance audit events. Do not print
   bearer tokens or broker secrets.

Rollback: disable `_id="zeler-app"` in `module_registry`, rotate/revoke `zeler-app-broker-secret`,
or restore the previous Vercel runtime env and redeploy the app.

---

## 6. Rollback

### Rollback a bad image

Edit `/opt/zeler-platform/docker-compose.yml` on the VM, change the image tag for the affected service back to the previous tag (e.g. `rollout-v1`), then:

```bash
cd /opt/zeler-platform && sudo docker compose up -d --no-deps <service>
```

### Rollback via env override (faster, no file edit)

```bash
cd /opt/zeler-platform && \
  sudo IMAGE_TAG=rollout-v1 docker compose up -d --no-deps <service>
```

### Full VM loss (within 7-day PC retention window)

1. Re-provision VM using §1 gcloud commands (idempotent).
2. Restore from retained PC dump (see §3, Steps 6–10).

### Full VM loss (GCS backup available)

```bash
# On VM, after Mongo starts:
gsutil cp gs://zeler-platform-backups/mongo/<date>/backup.archive.gz - \
  | docker exec -i zeler-platform-mongo-1 mongorestore --archive --gzip --drop
```

### Bad OAuth secret → revert secret version

```bash
gcloud secrets versions disable <bad-version-id> \
  --secret=google-oauth-client-id --project=$PROJECT
sudo systemctl restart zeler-platform-secrets.service
cd /opt/zeler-platform && sudo docker compose up -d sheets-api sheets-worker
```

---

## 7. Adding a New Secret

1. Create the secret in Secret Manager:
   ```bash
   printf "<value>" | gcloud secrets create <secret-name> \
     --data-file=- --project=$PROJECT
   ```

2. Grant the VM SA access (if not already covered by project-level accessor role):
   ```bash
   gcloud secrets add-iam-policy-binding <secret-name> \
     --member="serviceAccount:$SA" \
     --role=roles/secretmanager.secretAccessor \
     --project=$PROJECT
   ```

3. Add the secret fetch + env var write to `infra/gce/zeler-platform-secrets.sh`.

4. Add the key to the relevant `infra/gce/env-templates/<service>.env.template`.

5. Deploy updated script to VM:
   ```bash
   gcloud compute scp --tunnel-through-iap --zone=$ZONE \
     infra/gce/zeler-platform-secrets.sh \
     platform-vm:/opt/zeler-platform/zeler-platform-secrets.sh \
     --project=$PROJECT
   sudo chmod +x /opt/zeler-platform/zeler-platform-secrets.sh
   ```

6. Restart secrets service + affected containers.

---

## 8. Smoke Test Checklist

Run after every deploy or cutover. All must pass before marking the deploy stable.

### HTTPS health checks (TLS cert must be valid, not self-signed)

```bash
for s in gateway sheets repricer publicador autoreply; do
  echo -n "=== $s: "
  curl -fsSI "https://${s}.zeler.ai/health" | head -1 || echo "FAIL"
done
```

Expected: `HTTP/2 200` for all 5 active subdomains.

### Container state (10 active containers, all running)

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && \
    sudo docker compose ps --format json | \
    python3 -c \"import sys,json; data=json.load(sys.stdin) if isinstance(json.load(open('/dev/stdin')), list) else []; print(f'{len(data)} containers')\" || \
    sudo docker compose ps"
```

### Worker consumer logs (confirm queues bound)

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT << 'EOF'
for w in repricer-worker sheets-worker autoreply-worker; do
  echo "=== $w ==="; sudo docker logs "$w" --tail 20 2>&1 | grep -iE "consumer|started|bound" || echo "NO MATCH"
done
EOF
```

### Mongo internal-only (must be unreachable from outside VM)

```bash
VM_IP=$(gcloud compute addresses describe platform-vm-ip --region=$REGION \
  --format="value(address)" --project=$PROJECT)
nc -zv "$VM_IP" 27017 && echo "FAIL: mongo exposed" || echo "OK: mongo internal-only"
```

### Mongo replica set health (from inside VM)

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sudo docker exec zeler-platform-mongo-1 \
    mongosh --quiet --eval 'rs.status().myState'"
# Must return 1 (PRIMARY)
```

### Mongo validator drift smoke

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && \
    python -m infra.mongo.apply_validators --mongo-uri=\"$MONGO_URI\" && \
    python -m infra.mongo.drift_check --mongo-uri=\"$MONGO_URI\""
```

Expected: validator apply is idempotent and drift check exits 0 with `applied` for committed
schema-backed collections.

---

## 9. Failure Tree

| Symptom | Likely Cause | First Action |
|---------|-------------|--------------|
| Container won't start | Secret not found / env file missing | `sudo cat /opt/zeler-platform/env/<service>.env`; check `journalctl -u zeler-platform-secrets.service` |
| `curl https://<sub>.zeler.ai` → connection refused | DNS not propagated OR caddy not running | `dig +short <sub>.zeler.ai`; `sudo docker ps \| grep caddy` |
| Caddy TLS error / self-signed cert | Port 80 blocked (HTTP-01 challenge fails) | Check `allow-platform-http` firewall rule exists; check caddy logs `sudo docker logs caddy` |
| Mongo not healthy | UID permission error on `/var/lib/zeler-mongo` | `sudo ls -la /var/lib/zeler-mongo`; `sudo chown -R 999:999 /var/lib/zeler-mongo`; restart mongo |
| Worker logs show auth error calling gateway | Minted JWT/KMS auth failure or wrong `GATEWAY_BASE_URL` | Check worker KMS env (`KMS_PROJECT_ID`, `KMS_LOCATION`, `KMS_KEYRING`, JWT key), gateway logs for JWT validation errors, and the worker `GATEWAY_BASE_URL` |
| Sheets OAuth returns 503 | Pass-1 placeholder creds still active | Complete §4 pass-2 steps |
| Sheets OAuth returns 500 | Real creds set but redirect URI mismatch | Verify `https://sheets.zeler.ai/oauth/google/callback` in GCP OAuth client |
| VM unreachable via SSH | IAP firewall rule missing or VM not RUNNING | Check firewall `allow-platform-ssh`; `gcloud compute instances describe platform-vm` |
| Memory OOM / container killed | `e2-medium` (4 GB) saturated | `sudo free -h`; scale to `e2-standard-2`: `gcloud compute instances stop platform-vm && gcloud compute instances set-machine-type platform-vm --machine-type=e2-standard-2 --zone=$ZONE && gcloud compute instances start platform-vm` |
| Image pull fails | SA missing Artifact Registry reader | Re-apply `roles/artifactregistry.reader` (see §1); `gcloud auth configure-docker us-central1-docker.pkg.dev` |

---

## DNS A Records — Squarespace

Add the following A records in Squarespace DNS panel for `zeler.ai`.  
Use **TTL 300** during cutover; raise to **3600** once TLS is verified stable.

```
gateway.zeler.ai     A  <vm-static-ip>
sheets.zeler.ai      A  <vm-static-ip>
repricer.zeler.ai    A  <vm-static-ip>
publicador.zeler.ai  A  <vm-static-ip>
autoreply.zeler.ai   A  <vm-static-ip>
```

`fulldock.zeler.ai` is intentionally omitted because Fulldock is decommissioned.

Get the static IP:

```bash
gcloud compute addresses describe platform-vm-ip \
  --region=us-central1 --format="value(address)" --project=zeler-platform-dev
```

## Meli OAuth Redirect URI Update

In [Meli Developers Console](https://developers.mercadolibre.com.ar/):
1. Select your app → **Editar app**
2. Under **URIs de redirección**, update to: `https://gateway.zeler.ai/oauth/callback`
3. Save changes

Verify:
```bash
curl -sI "https://gateway.zeler.ai/oauth/authorize?seller_id=test"
# Must return 302 with Location containing gateway.zeler.ai%2Foauth%2Fcallback
```
