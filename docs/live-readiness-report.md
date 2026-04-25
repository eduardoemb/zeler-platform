# Live/Deploy Readiness Report

- timestamp_utc: 2026-04-25T02:19:14Z
- scope: live/deploy readiness advancement for new `zeler-platform` only
- baseline_commit: `8444011` (`docs(infra): record readiness validation status`)
- branch: `main`
- destructive_legacy_actions_attempted: 0
- live_writes_attempted: 0
- deploy_attempted: false
- build_attempted: false

## Safety confirmation

- No legacy repos were touched.
- No legacy services, VMs, OAuth apps, databases, or infra were stopped, deleted, archived, revoked, dropped, or destroyed.
- No `zeler-core` SDD artifacts were read or modified.
- No secret values were printed; only presence/absence and safe resource names were recorded.

## Repository tooling inspected

| Area | Finding | Readiness impact |
|---|---|---|
| Cloud Run / Cloud Build | `infra/cloudbuild/bootstrap-job.yaml` exists for Cloud Run Job `zeler-bootstrap`; `bootstrap/Dockerfile` exists. | Build/deploy path exists for bootstrap job only. No gateway/module service Cloud Run configs were found in this pass. |
| Cloud Build env mutation | The bootstrap job config used `--set-env-vars=ZELER_ENV=prod`. | Updated to `--update-env-vars=ZELER_ENV=prod` so future deploys do not replace all Cloud Run env vars. |
| Dockerfiles | `bootstrap/Dockerfile` exists. | Build should use Cloud Build, not local Docker, to avoid Mac arm64 image issues. |
| Terraform | No Terraform files were found in this repo. | Infrastructure provisioning cannot be advanced from local Terraform in this repo. |
| Mongo apply tooling | `infra/mongo/apply_validators.py` can create collections, apply validators, and create indexes from `infra/mongo/schemas` + `infra/mongo/indexes`. | Mutating Mongo apply is available, but skipped because no target-confirmed `MONGO_URI` is present. |
| Mongo readiness tooling | `infra/mongo/readiness.py` supports offline and read-only live metadata validation. | Offline validation passed; live validation skipped without `MONGO_URI`. |
| RabbitMQ topology tooling | `infra/rabbitmq/amqp_setup.py` generates `infra/rabbitmq/definitions.json`; `infra/runbooks/amqp-setup.md` documents import via `rabbitmqadmin import`. | Topology generation/import path exists, but no live RabbitMQ URL/export is present. |
| Deployment preflight | `infra/deploy/preflight.py` checks gcloud, required env-var groups, and required repo files without printing secret values. | Run before any Cloud Run deploy or live apply; it exits non-zero while auth/env/binding blockers remain. |
| Secrets docs/config | No deploy-time Secret Manager binding script/config was found. | Deploy remains blocked until secret names/env contract are specified for each service/job. |

## Local environment and CLI target detection

Only non-secret status was recorded.

| Check | Result |
|---|---|
| `gcloud config get-value project` | `zeler-platform-dev` |
| Active gcloud account | `eduardoramirez@comercializadoraemb.com.mx` |
| `gcloud projects describe zeler-platform-dev` | BLOCKED — local gcloud credentials require reauthentication (`cannot prompt during non-interactive execution`). |
| Cloud Run services/jobs list | Not reliable in this session because token refresh is blocked by gcloud reauthentication. |
| Artifact Registry repositories list | Not reliable in this session because token refresh is blocked by gcloud reauthentication. |
| Secret Manager names list | Not reliable in this session because token refresh is blocked by gcloud reauthentication. |
| Docker daemon | Available (`29.2.1`), but no local image build was run. |
| `MONGO_URI` | Missing |
| `RABBITMQ_URL` / `CLOUDAMQP_URL` | Missing |
| `RabbitMQ_MANAGEMENT_EXPORT` | Missing |
| `MODULE_REGISTRY_EXPORT` | Missing |
| GCP project env vars (`GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT`, `GCLOUD_PROJECT`, `PROJECT_ID`) | Missing |
| Region env vars (`CLOUD_RUN_REGION`, `REGION`) | Missing |

## Commands run and outcomes

| Command | Outcome |
|---|---|
| `git status --short && git branch --show-current` | PASS — branch `main`; no pre-existing working-tree changes were reported. |
| `gcloud config get-value project` | PASS — configured project is `zeler-platform-dev`. |
| `gcloud auth list --filter=status:ACTIVE --format='value(account)'` | PASS — active account detected. |
| `gcloud projects describe zeler-platform-dev --format='value(projectId,projectNumber,lifecycleState)'` | BLOCKED — gcloud needs interactive reauthentication. |
| Safe env-presence probe via `uv run python` | PASS — required live inputs are missing; no secret values printed. |
| `docker version --format '{{.Server.Version}}'` | PASS — Docker daemon available. |
| `uv run python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json --format json` | PASS — offline RabbitMQ topology validation completed; 6 exchanges, 35 queues, 10 bindings expected; no local drift. |
| `uv run python -m infra.mongo.readiness --schemas-dir infra/mongo/schemas --indexes-dir infra/mongo/indexes --format json` | PASS — offline Mongo readiness completed; 27 schema files, 24 index files, 53 index definitions, 1 seed doc; no local file errors. |
| `uv run pytest tests/test_bootstrap_job_packaging.py -q` | RED as intended after adding guard against `--set-env-vars`; proved existing Cloud Build config was unsafe for env preservation. |
| `uv run pytest tests/test_bootstrap_job_packaging.py tests/test_live_readiness_validation.py tests/test_rabbitmq_topology.py tests/test_mongo_schemas_placeholder.py -q` | PASS — 14 focused readiness tests passed after Cloud Build config fix. |

## Readiness results

### RabbitMQ offline dry-run

- mode: `offline`
- safe_to_execute: `true`
- read_only: `true`
- mutations_attempted: `0`
- expected_exchanges: `6`
- expected_queues: `35`
- expected_bindings: `10`
- missing_exchanges: `0`
- missing_queues: `0`
- missing_bindings: `0`
- finding: `[pass] definitions — Expected topology definition is internally readable; no drift detected.`

### Mongo offline dry-run

- mode: `offline`
- safe_to_execute: `true`
- read_only: `true`
- live_target_checked: `false`
- mutations_attempted: `0`
- schema_files: `27`
- active_schema_files: `27`
- schema_file_errors: `0`
- index_files: `24`
- index_definitions: `53`
- index_file_errors: `0`
- seed_files: `1`
- seed_documents: `1`
- seed_file_errors: `0`
- module_registry_admin_clients: `1`
- module_registry_scope_mismatches: `0`
- module_registry_export_docs_checked: `0`
- module_registry_missing_admin_clients: `0`
- module_registry_export_scope_mismatches: `0`
- finding: `[pass] local-files — Schema and index files are readable; no drift detected in selected mode.`

## Actions applied

### Repository/config changes

- Updated `infra/cloudbuild/bootstrap-job.yaml` to use `--update-env-vars=ZELER_ENV=prod` instead of `--set-env-vars=ZELER_ENV=prod`.
- Added a regression assertion in `tests/test_bootstrap_job_packaging.py` so bootstrap Cloud Build packaging fails if `--set-env-vars` returns.
- Updated this report with live/deploy readiness checks and blockers.

### Live writes / deploys

None. The configured project name is correct for dev (`zeler-platform-dev`), but gcloud cannot refresh credentials non-interactively in this session, and no target-confirmed Mongo/RabbitMQ credentials are present.

## Actions skipped and reasons

| Action | Reason |
|---|---|
| Mongo validator/index/seed apply | Skipped because `MONGO_URI` is missing. Without a URI, target confirmation is impossible. |
| Mongo read-only live metadata validation | Skipped because `MONGO_URI` is missing. |
| RabbitMQ topology import/apply | Skipped because `RABBITMQ_URL` / `CLOUDAMQP_URL` are missing and no target-confirmed management endpoint/export is present. |
| RabbitMQ management export comparison | Skipped because `RabbitMQ_MANAGEMENT_EXPORT` is missing. |
| Module registry export comparison | Skipped because `MODULE_REGISTRY_EXPORT` is missing. |
| Cloud Run build/deploy | Skipped because gcloud requires reauthentication and service/job secret/env bindings are not fully specified. |
| Local Docker build | Skipped intentionally; Cloud Run images should be built through Cloud Build, not local Mac Docker. |

## Next operator commands

Run these after confirming the target is the new `zeler-platform` dev/sandbox environment, not legacy.

### 0. Deployment preflight

The deployment preflight prints only present/missing status and sanitized gcloud availability; it never prints secret values.

```bash
uv run python -m infra.deploy.preflight
```

Expected current result: non-zero until gcloud auth, Mongo/RabbitMQ/GCP env vars, RabbitMQ/module-registry exports, and Cloud Run Secret Manager/env binding export are present.

### 1. Reauthenticate gcloud

```bash
gcloud auth login
gcloud config set project zeler-platform-dev
gcloud projects describe zeler-platform-dev --format='value(projectId,projectNumber,lifecycleState)'
```

### 2. Confirm deploy prerequisites

```bash
gcloud services list --enabled --format='value(config.name)'
gcloud artifacts repositories list --location=us-central1 --format='value(name,format)'
gcloud secrets list --format='value(name)'
gcloud run jobs describe zeler-bootstrap --region=us-central1 \
  --format='yaml(metadata.name,status.conditions,status.latestCreatedExecution.name)'
```

### 3. Mongo live validation/apply sequence

```bash
export MONGO_URI='mongodb://.../zeler_platform_dev_or_zeler_platform?authSource=...'

# Read-only validation first.
uv run python -m infra.mongo.readiness \
  --schemas-dir infra/mongo/schemas \
  --indexes-dir infra/mongo/indexes \
  --mongo-uri "$MONGO_URI"

# Mutating apply only after the URI database name and host are confirmed as zeler-platform.
uv run python -m infra.mongo.apply_validators
```

### 4. RabbitMQ export/import sequence

```bash
export RabbitMQ_MANAGEMENT_EXPORT=/path/to/zeler-platform-rabbitmq-export.json
uv run python -m infra.rabbitmq.readiness \
  --definitions infra/rabbitmq/definitions.json \
  --management-export "$RabbitMQ_MANAGEMENT_EXPORT"

# Mutating import only after target vhost/host is confirmed as zeler-platform.
rabbitmqadmin import infra/rabbitmq/definitions.json
```

### 5. Bootstrap Cloud Run Job deploy sequence

Use Cloud Build, not local Docker:

```bash
gcloud builds submit --config infra/cloudbuild/bootstrap-job.yaml .
gcloud run jobs describe zeler-bootstrap --region=us-central1 \
  --format='yaml(metadata.name,status.conditions,status.latestCreatedExecution.name)'
```

Before running it, add/verify the missing Secret Manager/env bindings expected by `zeler_bootstrap`; this repo currently has the job package but not a complete secret-binding runbook.

## Current status

`PARTIAL`: local repo readiness advanced and an unsafe Cloud Run env-var deployment flag was fixed. Live Mongo/RabbitMQ apply and Cloud Run deploy remain blocked by missing target credentials/exports and gcloud reauthentication.
