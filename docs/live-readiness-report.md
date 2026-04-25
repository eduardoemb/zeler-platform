# Live/Deploy Readiness Report

- timestamp_utc: 2026-04-25T03:27:57Z
- scope: live/deploy readiness advancement for new `zeler-platform` only
- baseline_commit: `20c672f`
- branch: `main`
- gcp_project: `zeler-platform-dev`
- gcp_project_number: `721178147108`
- gcp_lifecycle_state: `ACTIVE`
- gcloud_account: `eduardoramirez@comercializadoraemb.com.mx`
- default_region_used: `us-central1`
- destructive_legacy_actions_attempted: 0
- live_writes_attempted: 46 RabbitMQ topology writes after target confirmation
- deploy_attempted: false
- build_attempted: false

## Safety confirmation

- No legacy repos were touched.
- No legacy services, VMs, OAuth apps, databases, or infra were stopped, deleted, archived, revoked, dropped, or destroyed.
- No `zeler-core` SDD artifacts were read or modified.
- No secret values were printed. Secret payload access was limited to command env injection for the `cloudamqp-url` Secret Manager entry in project `zeler-platform-dev`.
- Docker was not built locally; Cloud Build remains the only allowed container build path.
- No Cloud Run `--set-env-vars` command was used.

## Commands run and outcomes

| Command | Outcome |
|---|---|
| `git status --short && git branch --show-current` | PASS — branch `main`; working tree was clean before changes. |
| `gcloud config get-value account && gcloud config get-value project` | PASS — account and project available; reauth blocker cleared. |
| `gcloud projects describe zeler-platform-dev --format='value(projectId,projectNumber,lifecycleState)'` | PASS — project `zeler-platform-dev`, number `721178147108`, state `ACTIVE`. |
| `gcloud secrets list --project=zeler-platform-dev --format='value(name,replication.policy)'` | PASS — secrets found: `cloudamqp-url`, `meli-client-id`, `meli-client-secret`; no Mongo secret found. |
| `gcloud run jobs list --project=zeler-platform-dev --region=us-central1` | PASS — no Cloud Run jobs currently exist. |
| `gcloud run services list --project=zeler-platform-dev --region=us-central1` | PASS — no Cloud Run services currently exist. |
| `gcloud artifacts repositories list --project=zeler-platform-dev --location=us-central1` | PASS — no Artifact Registry repository was listed in `us-central1`. |
| `uv run python -m infra.deploy.preflight --format json` | BEFORE: `ok=false`; `missing_env_groups=7`, `missing_repo_files=0`, `gcloud_failures=0`. |
| Preflight with inferred env (`cloudamqp-url`, `GOOGLE_CLOUD_PROJECT=zeler-platform-dev`, `CLOUD_RUN_REGION=us-central1`) | AFTER: `ok=false`; `missing_env_groups=4`, `missing_repo_files=0`, `gcloud_failures=0`. Remaining blockers: `MONGO_URI`, `RabbitMQ_MANAGEMENT_EXPORT`, `MODULE_REGISTRY_EXPORT`, `CLOUD_RUN_SECRET_BINDINGS_EXPORT`. |
| `uv run python -m infra.mongo.readiness --schemas-dir infra/mongo/schemas --indexes-dir infra/mongo/indexes --format json` | PASS — offline Mongo readiness: 27 schema files, 24 index files, 53 indexes, 1 seed doc, 0 file errors. |
| `uv run python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json --format json` | PASS — offline RabbitMQ readiness: 6 exchanges, 35 queues, 10 bindings expected. |
| RabbitMQ management export via CloudAMQP API | PASS — read-only export succeeded using `cloudamqp-url`; host recorded as `woodpecker.rmq.cloudamqp.com`; secret payload was not printed. |
| `uv run python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json --management-export /tmp/zeler-platform-rabbitmq-export.json --format json` | BEFORE APPLY: drift found — missing 6 exchanges, 35 queues, 10 bindings. |
| RabbitMQ topology apply via management API | PARTIAL first attempt — 6 exchanges and 1 DLQ created, then queue creation failed because `x-delivery-limit` is invalid for CloudAMQP classic queues. |
| RabbitMQ topology config fix + re-apply | PASS — corrected topology applied idempotently: 6 exchanges PUT, 35 queues PUT, 10 bindings POST. |
| RabbitMQ export comparison after apply | PASS — missing exchanges `0`, missing queues `0`, missing bindings `0`. |
| `gcloud run jobs describe zeler-bootstrap --project=zeler-platform-dev --region=us-central1` | BLOCKED/ABSENT — job does not exist yet. |

## Preflight summary

Deployment preflight command: `uv run python -m infra.deploy.preflight`. It prints only present/missing status and sanitized gcloud availability; it never prints secret values.

### Before inference

- `ok`: false
- `gcloud_failures`: 0
- `missing_repo_files`: 0
- `missing_env_groups`: 7

### After safe inference

- Inferred from gcloud/repo/docs:
  - project: `zeler-platform-dev`
  - region: `us-central1`
  - RabbitMQ URL: Secret Manager secret `cloudamqp-url` (payload not printed)
- `ok`: false
- `gcloud_failures`: 0
- `missing_repo_files`: 0
- `missing_env_groups`: 4
- Remaining missing env/export groups:
  - `MONGO_URI`
  - `RabbitMQ_MANAGEMENT_EXPORT` (export generated only as local `/tmp` evidence, not an operator-provided persistent export)
  - `MODULE_REGISTRY_EXPORT`
  - `CLOUD_RUN_SECRET_BINDINGS_EXPORT`

## Live writes / mutations attempted

Target: CloudAMQP broker referenced by Secret Manager secret `cloudamqp-url` in GCP project `zeler-platform-dev`.

| Mutation type | Count | Result |
|---|---:|---|
| Exchange PUT | 12 total attempts (6 first pass + 6 idempotent re-apply) | PASS |
| Queue PUT | 36 total attempts (1 first pass + 35 corrected re-apply) | PASS after config fix |
| Binding POST | 10 | PASS |
| Mongo mutations | 0 | Skipped — no target-confirmed Mongo URI/secret exists. |
| Cloud Run deploy/build mutations | 0 | Skipped — deploy bindings and Artifact Registry repo are not ready. |

Net topology now present in RabbitMQ readiness terms: 6 expected exchanges, 35 expected queues, 10 expected bindings, with 0 missing.

## Repository/config changes

- `infra/rabbitmq/topology.py` — removed unsupported `x-delivery-limit` from classic queue declarations.
- `infra/rabbitmq/definitions.json` — regenerated/updated expected definitions to match CloudAMQP classic queue compatibility.
- `infra/rabbitmq/readiness.py` — normalizes RabbitMQ management's implicit `x-queue-type=classic` argument so read-only drift checks do not false-fail.
- `tests/test_rabbitmq_topology.py` — added a regression test forbidding `x-delivery-limit` in expected classic queue arguments.
- `tests/test_live_readiness_validation.py` — added a regression test for management export normalization.
- `docs/live-readiness-report.md` — updated with this session's sanitized commands, results, live mutations, blockers, and next steps.

## Actions skipped and reasons

| Action | Reason |
|---|---|
| Mongo read-only live metadata validation | Skipped because no Secret Manager secret or env var for `MONGO_URI` exists in `zeler-platform-dev`. |
| Mongo validator/index/seed apply | Skipped because target confirmation is impossible without a new-platform Mongo URI. |
| Module registry live export comparison | Skipped because Mongo target is unavailable and `MODULE_REGISTRY_EXPORT` is missing. |
| Cloud Build / Cloud Run deploy | Skipped because no Artifact Registry repo was listed, `zeler-bootstrap` does not exist yet, and required runtime secret/env bindings are incomplete (`BOOTSTRAP_MONGO_URI`, `BOOTSTRAP_GATEWAY_BASE_URL`, `BOOTSTRAP_GATEWAY_TOKEN`, `BOOTSTRAP_RABBITMQ_URL`). |
| Local Docker build | Skipped intentionally; Mac local image builds are forbidden for this deploy path. |

## Deploy readiness evaluation

- Cloud Build config exists only for `bootstrap` (`infra/cloudbuild/bootstrap-job.yaml`) and correctly uses `--update-env-vars`.
- `bootstrap/Dockerfile` exists.
- Project APIs include Cloud Build, Cloud Run, Secret Manager, KMS, Artifact Registry, Compute, VPC Access, and observability APIs.
- Missing before deploy:
  - Artifact Registry repository `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform` or an updated image target.
  - Secret/env binding export for Cloud Run jobs/services.
  - Target-confirmed Mongo URI secret.
  - Bootstrap runtime bindings listed above.

## Gates

- RED evidence: `uv run pytest tests/test_rabbitmq_topology.py -q` failed before removing `x-delivery-limit`.
- RED evidence: `uv run pytest tests/test_live_readiness_validation.py::test_rabbitmq_readiness_accepts_management_default_classic_queue_type -q` failed before readiness normalization.
- GREEN focused: `uv run pytest tests/test_live_readiness_validation.py::test_rabbitmq_readiness_accepts_management_default_classic_queue_type tests/test_live_readiness_validation.py::test_rabbitmq_readiness_detects_missing_binding_from_management_export tests/test_rabbitmq_topology.py -q` passed (`5 passed`).
- Full gates are recorded in the final assistant summary.

## Current status

`PARTIAL`: gcloud auth is healthy, Secret Manager discovery succeeded, RabbitMQ topology was applied to the new-platform CloudAMQP target and verified. Mongo live readiness/apply and Cloud Run deploy remain blocked by missing Mongo/secret-binding/deploy infrastructure inputs.

## Next recommended steps

1. Add a target-confirmed `MONGO_URI` Secret Manager secret for new `zeler-platform` only, then run read-only Mongo readiness before any apply.
2. Add a persistent Cloud Run Secret/env binding export for `zeler-bootstrap` and future services/jobs.
3. Create or confirm the Artifact Registry repository referenced by `infra/cloudbuild/bootstrap-job.yaml`.
4. Re-run preflight with `MONGO_URI`, `CLOUDAMQP_URL`, `MODULE_REGISTRY_EXPORT`, `RabbitMQ_MANAGEMENT_EXPORT`, `GOOGLE_CLOUD_PROJECT`, `CLOUD_RUN_REGION`, and `CLOUD_RUN_SECRET_BINDINGS_EXPORT` present.
5. Only then deploy `zeler-bootstrap` through Cloud Build.
