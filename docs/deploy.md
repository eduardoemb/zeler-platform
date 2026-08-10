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
df -h /                             # boot disk has deploy margin
systemctl is-enabled zeler-docker-maintenance.timer
docker --version
docker compose version
```

---

## 2. Image Build & Push (Cloud Build — NEVER local)

**Important**: Always use Cloud Build. Never `docker build` locally on Mac.

Build from the connected repository at one exact commit already present in
`main`. Never submit the local checkout as `.`: doing so can upload the wrong
branch or uncommitted files. A tag is only human-readable build metadata; the
resulting `repo@sha256:...` reference is the deployment authority.

### Build one affected service

```bash
PROJECT=zeler-platform-dev
BUILD_REGION=us-central1
CONNECTION=zeler-platform-github
REPOSITORY=zeler-platform
REPOSITORY_RESOURCE="projects/${PROJECT}/locations/${BUILD_REGION}/connections/${CONNECTION}/repositories/${REPOSITORY}"
AR="${BUILD_REGION}-docker.pkg.dev/${PROJECT}/zeler-platform"

# Select only the service affected by the merged change.
SERVICE=sheets-worker
DOCKERFILE=modules/sheets/Dockerfile.worker

git fetch origin main
SOURCE_COMMIT=$(git rev-parse origin/main)
test "${#SOURCE_COMMIT}" -eq 40

TAG="${SERVICE}-${SOURCE_COMMIT:0:7}-$(date -u +%Y%m%dT%H%M%SZ)"
TAGGED_IMAGE="${AR}/${SERVICE}:${TAG}"
BUILD_TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/zeler-cloudbuild-${SERVICE}.XXXXXX")
BUILD_CONFIG="${BUILD_TEMP_DIR}/cloudbuild.yaml"
PROVENANCE_FILE="${BUILD_TEMP_DIR}/provenance.json"
BUILD_FILE="${BUILD_TEMP_DIR}/build.json"
IMAGE_MAP_FILE="${BUILD_TEMP_DIR}/image_to_commit.json"
trap 'rm -rf "$BUILD_TEMP_DIR"' EXIT

cat > "$BUILD_CONFIG" <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  args: ['build', '-f', '${DOCKERFILE}', '-t', '${TAGGED_IMAGE}', '.']
images: ['${TAGGED_IMAGE}']
EOF

BUILD_ID=$(gcloud builds submit "$REPOSITORY_RESOURCE" \
  --revision="$SOURCE_COMMIT" \
  --config="$BUILD_CONFIG" \
  --project="$PROJECT" \
  --region="$BUILD_REGION" \
  --async \
  --format='value(id)')

gcloud builds log "$BUILD_ID" \
  --project="$PROJECT" \
  --region="$BUILD_REGION" \
  --stream

test "$(gcloud builds describe "$BUILD_ID" \
  --project="$PROJECT" \
  --region="$BUILD_REGION" \
  --format='value(status)')" = "SUCCESS"
```

Choose the Dockerfile from this map:

| Service | Dockerfile |
| --- | --- |
| `gateway` | `gateway/Dockerfile` |
| `repricer-api` | `modules/repricer/Dockerfile.api` |
| `repricer-worker` | `modules/repricer/Dockerfile.worker` |
| `sheets-api` | `modules/sheets/Dockerfile.api` |
| `sheets-worker` | `modules/sheets/Dockerfile.worker` |
| `autoreply-api` | `modules/autoreply/Dockerfile.api` |
| `autoreply-worker` | `modules/autoreply/Dockerfile.worker` |
| `publicador-api` | `modules/publicador/Dockerfile.api` |

Do not build every service by default. Shared runtime or dependency changes may
affect more than one image; name and build each affected service explicitly.

### Resolve and verify the immutable image

```bash
DIGEST=$(gcloud artifacts docker images describe "$TAGGED_IMAGE" \
  --project="$PROJECT" \
  --format='value(image_summary.digest)')
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || { echo "Invalid image digest" >&2; exit 1; }

IMAGE_REF="${AR}/${SERVICE}@${DIGEST}"
printf 'BUILD_ID=%s\nSOURCE_COMMIT=%s\nIMAGE_REF=%s\n' \
  "$BUILD_ID" "$SOURCE_COMMIT" "$IMAGE_REF"

gcloud builds describe "$BUILD_ID" \
  --project="$PROJECT" \
  --region="$BUILD_REGION" \
  --format='yaml(status,source.connectedRepository.repository,source.connectedRepository.revision,results.images)'

gcloud artifacts docker images describe "$IMAGE_REF" \
  --project="$PROJECT" \
  --show-provenance \
  --format=json > "$PROVENANCE_FILE"

gcloud builds describe "$BUILD_ID" \
  --project="$PROJECT" \
  --region="$BUILD_REGION" \
  --format=json > "$BUILD_FILE"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
PYTHONPATH=. python3 -m infra.deploy.provenance_check verify-image \
  --image-ref="$IMAGE_REF" \
  --artifact-file="$PROVENANCE_FILE" \
  --build-file="$BUILD_FILE" \
  --source-commit="$SOURCE_COMMIT" \
  --connected-repository="$REPOSITORY_RESOURCE" \
  --expected-project-id="$PROJECT" \
  --expected-project-number="$PROJECT_NUMBER" \
  --map-out="$IMAGE_MAP_FILE"
```

Before deployment, record the successful `BUILD_ID`, exact 40-character
`SOURCE_COMMIT`, and immutable `IMAGE_REF`. Refuse a build whose connected
repository, revision, subject digest, or status does not match those values.

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

## 5a. platform-vm root disk guardrails

`platform-vm` keeps the boot disk at **20GB** for now. Do not resize it yet: the active
policy is deploy preflight, safe Docker cleanup, Docker log rotation, a daily maintenance
timer, and alerts. Resize the boot disk to **50GB** only if cleanup cannot maintain at
least **5GiB** free on `/` or repeated pulls keep exhausting the margin.

When applying this to an already-running VM, plan a maintenance window after the daemon
config change: existing containers may need `docker compose up -d --force-recreate <service>`
to pick up the new Docker log driver and log limits. New containers get the limits automatically.

Safety rules:

- Mongo data lives on the separate persistent disk mounted at `/var/lib/zeler-mongo`.
- Safe cleanup may remove stopped containers, unused images, and builder cache older than 72 hours.
- **Never prune Docker volumes** and never prune volumes during root-disk maintenance.
- The deploy preflight must run before every `docker compose pull` on the VM.
- Docker daemon log rotation is installed through `/etc/docker/daemon.json` (`local`, `max-size=50m`, `max-file=5`).
- `zeler-docker-maintenance.timer` runs the safe maintenance script daily; daily is intentional because failed pulls can fill the small boot disk quickly.
- Configure Cloud Monitoring root filesystem alerts at 80% warning and 90% critical.

### Opt-in immutable-digest provenance gate (`REQUIRE_DIGEST_BINDING`)

The deploy preflight can refuse every moving `image:` tag before any pull. Set
`REQUIRE_DIGEST_BINDING=1` on `platform-vm` to enable it; the flag defaults to
`0`, so current behavior is unchanged until an operator opts in.

Quick path (dry-run, read-only):

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sudo REQUIRE_DIGEST_BINDING=1 /opt/zeler-platform/docker-deploy-preflight.sh --dry-run"
```

Expected: fails closed while `infra/gce/docker-compose.yml` still uses moving
tags (`gateway:rollout-v5`, `mongo:7.0`, ...); no pull, no Docker maintenance,
no runtime mutation. `--dry-run` skips the Sheets rollback attestation pull and
the maintenance script; the binding check itself is read-only.

Behavior when enabled:

| Step | Result |
|------|--------|
| Any compose `image:` is not `repo@sha256:<64 hex>` | Refused **before** any pull; preflight exits non-zero |
| Every compose image is digest-pinned | SLSA v1 subject/build/commit verified per image; `image_to_commit.json` written |
| Ambiguous/forged provenance, build mismatch, or subprocess failure | Fail closed before pull |

Evidence file `/var/lib/zeler-platform/image_to_commit.json`:

```json
{"schema_version": 1, "images": {"us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:<hex>": {"digest": "sha256:<hex>", "build_id": "<cloud-build>", "source_commit": "<40 hex>"}}}
```

**Moving tags are metadata only.** Tags such as `rollout-v5` document intent
for humans; they are never deploy authority. Digest pinning per deploy is an
operator work unit (Lane B): obtain `repo@sha256:...` plus `build_id` and
`source_commit` from `gcloud artifacts docker images describe ... --show-provenance`
and the matching Cloud Build record, then update the compose `image:` lines.
The verifier lives in `infra/deploy/provenance_check.py` and reuses the same
single-subject SLSA v1 binding as the Sheets rollback attestation, so
provenance interpretation never drifts between the two gates.

---

## 5. Re-deploy a Single Service

Deploy only after separate user authorization. Run the build steps locally,
then connect to `platform-vm` and execute this section inside the VM. The
previous **running** digest is the rollback authority; it may differ from the
image currently written in Compose.

```bash
COMPOSE_FILE=/opt/zeler-platform/docker-compose.yml
SERVICE=sheets-worker
SOURCE_COMMIT=REPLACE_WITH_EXACT_40_CHARACTER_MAIN_COMMIT
NEW_IMAGE=REPLACE_WITH_ARTIFACT_REGISTRY_REPOSITORY_AT_SHA256_DIGEST

[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] \
  || { echo "SOURCE_COMMIT must be a full commit" >&2; exit 1; }
[[ "$NEW_IMAGE" =~ ^[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo "NEW_IMAGE must be pinned by digest" >&2; exit 1; }

sudo /opt/zeler-platform/docker-deploy-preflight.sh

CONTAINER_ID=$(sudo docker compose --file "$COMPOSE_FILE" ps -q "$SERVICE")
test -n "$CONTAINER_ID"
PRIOR_IMAGE=$(sudo docker inspect "$CONTAINER_ID" --format '{{.Config.Image}}')
[[ "$PRIOR_IMAGE" =~ ^[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo "Running rollback image is not pinned by digest" >&2; exit 1; }

BACKUP="${COMPOSE_FILE}.pre-${SERVICE}-${SOURCE_COMMIT:0:7}"
sudo cp -p "$COMPOSE_FILE" "$BACKUP"

CURRENT_CONFIG_IMAGE=$(sudo docker compose --file "$COMPOSE_FILE" config --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' \
    "$SERVICE")

sudo python3 - "$COMPOSE_FILE" "$CURRENT_CONFIG_IMAGE" "$NEW_IMAGE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    raise SystemExit("expected exactly one Compose image replacement")
path.write_text(text.replace(old, new, 1))
PY

RENDERED_IMAGE=$(sudo docker compose --file "$COMPOSE_FILE" config --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' \
    "$SERVICE")
test "$RENDERED_IMAGE" = "$NEW_IMAGE"

sudo docker compose --file "$COMPOSE_FILE" pull "$SERVICE"
sudo docker compose --file "$COMPOSE_FILE" up -d --no-deps "$SERVICE"
```

The preflight requires at least 5GiB free on `/`. If the margin is lower, it
runs safe Docker maintenance and re-checks before pulling images. Do not declare
success from `Started`; prove the running digest and health:

```bash
CONTAINER_ID=$(sudo docker compose --file "$COMPOSE_FILE" ps -q "$SERVICE")
RUNNING_IMAGE=$(sudo docker inspect "$CONTAINER_ID" --format '{{.Config.Image}}')
test "$RUNNING_IMAGE" = "$NEW_IMAGE"

for attempt in $(seq 1 12); do
  RUNTIME_STATUS=$(sudo docker inspect "$CONTAINER_ID" \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
  test "$RUNTIME_STATUS" = "healthy" && break
  sleep 5
done
test "$RUNTIME_STATUS" = "healthy"

sudo docker compose --file "$COMPOSE_FILE" ps "$SERVICE"
```

Run the service-specific smoke from section 8. If deployment, health, or smoke
fails, replace `NEW_IMAGE` with the recorded `PRIOR_IMAGE`, recreate only the
same service, and verify the rollback digest and health:

```bash
sudo python3 - "$COMPOSE_FILE" "$NEW_IMAGE" "$PRIOR_IMAGE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    raise SystemExit("expected exactly one Compose rollback replacement")
path.write_text(text.replace(old, new, 1))
PY

sudo docker compose --file "$COMPOSE_FILE" up -d --no-deps "$SERVICE"
sudo docker compose --file "$COMPOSE_FILE" ps "$SERVICE"
```

The Compose backup preserves the pre-deploy file for investigation, but it is
not automatically the runtime rollback target. Use the recorded running digest.

Manual safe cleanup, if an operator needs to run it outside the timer:

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="sudo /opt/zeler-platform/docker-maintenance.sh"
```

This cleanup only prunes stopped containers, unused images, and builder cache older than the retention window. Default retention is 72h/3 days and can be overridden with `DOCKER_PRUNE_UNTIL` for a one-off run.

Never prune Docker volumes. Never prune volumes. Do not run `docker volume prune`, and do not run Docker system prune with volume cleanup. Mongo data lives on `/var/lib/zeler-mongo`.

Recommended alerting: configure Cloud Monitoring policies on `platform-vm` root filesystem usage with warning at 80% and critical at 90%, so operators clean up or investigate before deploy pulls hit the 5GiB preflight floor.

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
user against an active linked `meli_accounts` seller owned by that `platform_user_id`. Deprecated
`allowed_seller_ids` remains only as a rollout fallback for old signed requests that do not include
`platform_user_id`; signed requests with `platform_user_id` must not use the seller fallback.

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

Expected output: `zeler-app admin client updated`. The updater removes any stale
`allowed_platform_user_ids` field and preserves only the deprecated `allowed_seller_ids` fallback for
rollout compatibility. The command must not print `MONGO_URI` or any secret value.

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
        'has_allowed_platform_user_ids': 'allowed_platform_user_ids' in doc,
        'allowed_seller_ids': doc.get('allowed_seller_ids'),
        'allowed_meli_scopes': doc.get('allowed_meli_scopes'),
    }, sort_keys=True))
finally:
    client.close()
PY"
```

Expected JSON contains `_id: "zeler-app"`, `status: "enabled"`, deprecated
`allowed_seller_ids: [82453304]` only while the rollout fallback is needed,
`has_allowed_platform_user_ids: false`, and exactly `admin:repricer`, `admin:sheets`, `admin:publicador`, and
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

## 5d. ZELERDATA DEVOLUCIONES ordered rollout and scheduled reconciliation

This runbook is for the approved pilot seller `82453304`. It preserves one
exact, non-unioned closed range from 2026-06-01 through the previous closed UTC
day. The accepted production interval is exactly
`[2026-06-01T00:00:00Z, 2026-07-10T00:00:00Z)` for the initial rollout. The
scheduled job then extends the same enclosing range; it never replaces it with
a yesterday-only marker.

> **WU8 rollout-gate correction (2026-07-10):** The first exact dry-run was
> rejected before reconciliation because its command omitted the required
> runtime confirmation. Every reviewed dry-run and authorized-write command
> below now includes exactly one `--confirm-approved-runtime`. Rollback also
> works when the worker environment omits `MONGO_DB`: it derives the database
> name from the default database in `MONGO_URI`. This does not require a new
> secret or a manual host edit, and sanitized topology output never prints the
> URI or derived database name.

### 1. Pre-mutation gates

Stop immediately unless the approved target, seller, image digest, indexes,
worker environment, and topology plan are all confirmed with sanitized output.
The Sheets module must retain `motor`, and its worker image must contain the
frozen `/app/.venv/bin/python` interpreter and reconciliation module. The
runtime requires these exact gateway scopes:

- `GET /post-purchase/v1/claims/search`
- `GET /post-purchase/v1/claims/*`
- `GET /post-purchase/v2/claims/*/returns`
- `GET /orders/*`

Build production images only through the approved Cloud Build path. Never
install packages while the reconciliation service is running. If the rollback-compatible
API image came from a Cloud Build v2 connected repository, pass the expected repository
resource through `SHEETS_ROLLBACK_CONNECTED_REPOSITORY`; preflight then requires
`source.connectedRepository.repository` to match that resource and
`source.connectedRepository.revision` to match the approved commit.

### 2. Install artifacts without activation

From an approved checkout, copy these files to a temporary directory on the VM:

- `infra/gce/zelerdata-devoluciones-reconcile.sh`
- `infra/gce/zelerdata-devoluciones-enable-timer.sh`
- `infra/gce/sheets-rollback-execute.sh`
- `infra/gce/zelerdata-devoluciones-topology.sh`
- `infra/gce/systemd/zelerdata-devoluciones-reconcile.service`
- `infra/gce/systemd/zelerdata-devoluciones-reconcile.timer`
- `infra/gce/systemd/zelerdata-devoluciones-reconcile-alert.service`

Then install the exact reviewed artifacts:

```bash
sudo install -m 0755 /tmp/zelerdata-devoluciones-topology.sh \
  /opt/zeler-platform/zelerdata-devoluciones-topology.sh
sudo install -m 0755 /tmp/zelerdata-devoluciones-reconcile.sh \
  /opt/zeler-platform/zelerdata-devoluciones-reconcile.sh
sudo install -m 0755 /tmp/zelerdata-devoluciones-enable-timer.sh \
  /opt/zeler-platform/zelerdata-devoluciones-enable-timer.sh
sudo install -m 0755 /tmp/sheets-rollback-execute.sh \
  /opt/zeler-platform/sheets-rollback-execute.sh
sudo install -m 0644 /tmp/zelerdata-devoluciones-reconcile.service \
  /etc/systemd/system/zelerdata-devoluciones-reconcile.service
sudo install -m 0644 /tmp/zelerdata-devoluciones-reconcile.timer \
  /etc/systemd/system/zelerdata-devoluciones-reconcile.timer
sudo install -m 0644 /tmp/zelerdata-devoluciones-reconcile-alert.service \
  /etc/systemd/system/zelerdata-devoluciones-reconcile-alert.service
sudo systemctl daemon-reload
sudo systemctl is-enabled zelerdata-devoluciones-reconcile.timer || true
```

The expected pre-acceptance state is `disabled`. Do not start or enable the
timer in this step. The checked-in service defaults are seller `82453304`,
historical range start `2026-06-01`, and accepted-through date `2026-07-09`.
An optional `/etc/zeler-platform/zelerdata-devoluciones-reconcile.env` may
override only reviewed, non-secret range configuration. Overrides may widen
coverage earlier or advance the accepted-through date; they cannot move the
accepted start later or the baseline accepted end earlier. Invalid or open
ranges fail with a sanitized `runtime_config_invalid` journal event.
The environment file cannot override the approved seller: systemd reapplies
`82453304` after loading it, and the wrapper validates the value before running.

### 3. Deploy and order the topology cutover

Apply the reviewed schemas/indexes and deploy the approved image before
topology mutation. Run the topology sequence in this order:

```bash
sudo /opt/zeler-platform/zelerdata-devoluciones-topology.sh plan
cd /opt/zeler-platform
sudo docker compose stop sheets-worker
sudo /opt/zeler-platform/zelerdata-devoluciones-topology.sh prestart --execute
sudo docker compose up -d sheets-worker
sudo docker compose ps sheets-worker
sudo /opt/zeler-platform/zelerdata-devoluciones-topology.sh bind-claims --execute
```

The required order is `plan` → stopped-worker `prestart --execute` → worker
health/passive claims consumer → `bind-claims --execute`. Do not bind claims if
the worker health gate fails. The topology wrapper never depends on a host
virtualenv. It runs the packaged `infra.rabbitmq` module through an exact
`docker compose run --rm --no-deps -T` one-shot using the frozen worker
interpreter; therefore `prestart` remains runnable while the long-lived worker
is stopped. The sudo-controlled ephemeral topology one-shot adds `--user 0:0`
only so its process can open the root-owned host Docker socket needed for
worker health/stop gates. This is the entire privilege boundary: the persistent
worker remains `appuser` (UID 1001) and receives neither a root user override nor
`privileged` mode. The persistent worker never mounts the Docker socket. Topology
output and failures remain sanitized; the wrapper never enables shell tracing or
prints environment values.

### 4. Run the dry-run and authorized write gates

Use only the frozen worker runtime. The dry-run confirms the approved runtime
but omits the production-write confirmation:

```bash
sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
  exec -T --workdir /app sheets-worker \
  /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id 82453304 --date-from 2026-06-01 --date-to 2026-07-09 \
  --dry-run --confirm-approved-runtime
```

Review the sanitized dry-run result. Only after it passes, run the same command
with all write gates:

```bash
sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
  exec -T --workdir /app sheets-worker \
  /app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id 82453304 --date-from 2026-06-01 --date-to 2026-07-09 \
  --write --confirm-approved-runtime --confirm-production-write
```

### Acceptance gate

Do not activate scheduling until every item below passes:

1. Sanitized reconciliation evidence reports
   `expected/persisted/complete/missing = 9/9/9/0` for the exact initial
   interval.
2. The database contains one exact non-unioned `devoluciones` marker enclosing
   the accepted interval with a 30-minute marker lease. Never combine disjoint
   markers or infer broader coverage.
3. Dispatcher-equivalent formula proof succeeds for the exact accepted dates.
4. Capture either an authenticated app/formula smoke or sanitized operator
   evidence containing timestamp, seller, exact formula/date inputs, result,
   no-error state, and request/correlation ID. If neither path is available,
   record `OPERATOR_EVIDENCE_PENDING`; do not hang and do not pass acceptance.

Enable the timer LAST, only after all four acceptance checks pass:

```bash
sudo /opt/zeler-platform/zelerdata-devoluciones-enable-timer.sh
```

The timer runs every 10 minutes with at most one minute of random delay. Each invocation uses one
single scheduled attempt with a 175-second shell stop and one continuous source-call recorder,
followed by an `OnFailure` alert. This keeps successful renewal inside the 30-minute marker
lease while providing natural catch-up after downtime through `Persistent=true`.
Every run re-verifies 2026-06-01 through the previous closed UTC day, so it
must not shrink accepted coverage.

### Monitoring

Use sanitized systemd evidence; never print environment files or credentials:

```bash
sudo systemctl list-timers zelerdata-devoluciones-reconcile.timer
sudo systemctl status zelerdata-devoluciones-reconcile.timer --no-pager
sudo journalctl -u zelerdata-devoluciones-reconcile.service \
  -u zelerdata-devoluciones-reconcile-alert.service --since "30 minutes ago" \
  --no-pager
```

Alert on `DEVOLUCIONES_RECONCILIATION_FAILED`, `runtime_config_invalid`,
`runtime_path_missing`, or the absence of a successful renewal before the
30-minute marker lease expires.

### Failure-conditional rollback

This is a **failure-conditional rollback**. Never roll back a successful
release automatically. If and only if deployment, topology, write, formula, or
timer acceptance fails:

1. Run `sudo /opt/zeler-platform/sheets-rollback-execute.sh` with the approved
   prior worker/gateway `repo@sha256` references and either the verified candidate
   API or externally attested rollback-compatible API reference.
2. The executor disables the timer, stales readiness, unbinds claims, restores
   worker/source images, verifies Artifact Registry/Cloud Build provenance when
   API rollback is requested, starts the exact Compose image, checks the running
   RepoDigest, and requires healthy exact 11/5 registration.
3. If safe provenance/image/health is unavailable, the executor stops
   `sheets-api` and fails closed. It never starts the old 8/4 writer.
4. Retain verified idempotent claim/order facts; do not delete proven data.

---

## 6. Rollback

### Rollback a bad image

Use the exact `PRIOR_IMAGE=repo@sha256:...` captured from the running container
before deployment. Follow the failure path in section 5 to replace the candidate
digest in Compose, recreate only the affected service, and verify that the
running image and health returned to the prior values.

Do not roll back by tag, do not assume the pre-deploy Compose file matches the
previous running container, and do not use an `IMAGE_TAG` override unless the
Compose file explicitly consumes that variable. Tags and backups are supporting
evidence; the recorded prior running digest is the rollback authority.

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

After a narrow service deploy, run the container binding/health checks from
section 5 plus the relevant service smoke below. After a platform cutover or a
shared-runtime change, run the full checklist. Never mark a deploy stable from
container startup alone.

### HTTPS health checks (TLS cert must be valid, not self-signed)

```bash
for s in gateway sheets repricer publicador autoreply; do
  echo -n "=== $s: "
  curl -fsSI "https://${s}.zeler.ai/health" | head -1 || echo "FAIL"
done
```

Expected: `HTTP/2 200` for all 5 active subdomains.

### Container state

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command="cd /opt/zeler-platform && sudo docker compose ps"
```

Every deployed service must be `Up` and services with healthchecks must be
`healthy`. For a narrow deploy, verify at least the affected service and its
direct dependency boundary.

### Worker consumer logs (confirm queues bound)

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT << 'EOF'
for w in repricer-worker sheets-worker autoreply-worker; do
  echo "=== $w ==="
  sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
    logs --tail 20 "$w" 2>&1 | grep -iE "consumer|started|bound" || echo "NO MATCH"
done
EOF
```

### VM-only sanitized ZELERDATA flag check

Do not print secret values or raw env files. From the approved VM/runtime context only, verify the
Sheets worker has the freshness flags set by printing key names with present/missing status only:

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT \
  --command='for k in ZELERDATA_ENRICHMENT_ENABLED ZELERDATA_SALE_PRICE_ENABLED ZELERDATA_LISTING_FIXED_FEE_ENABLED; do
    sudo grep -q "^${k}=true$" /opt/zeler-platform/env/sheets-worker.env \
      && printf "%s=set\n" "$k" \
      || printf "%s=missing\n" "$k"
  done'
```

Expected keys:

- `ZELERDATA_ENRICHMENT_ENABLED=true`
- `ZELERDATA_SALE_PRICE_ENABLED=true`
- `ZELERDATA_LISTING_FIXED_FEE_ENABLED=true`

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
