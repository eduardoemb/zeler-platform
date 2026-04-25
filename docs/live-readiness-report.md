# Live/Sandbox Readiness Report

- timestamp_utc: 2026-04-25T02:15:49Z
- scope: non-destructive readiness advancement for `zeler-platform`
- verified_head: `caca9cc`
- branch: `main`
- mutations_attempted: 0
- destructive_actions_attempted: 0
- deploy_attempted: false
- build_attempted: false

## Commands Run

| Command | Outcome |
|---|---|
| `git status --short && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD` | PASS — working tree initially clean, branch `main`, HEAD `caca9cc`. |
| `uv run python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json` | PASS — offline/read-only RabbitMQ validation completed with no missing local topology elements. |
| `uv run python -m infra.mongo.readiness --schemas-dir infra/mongo/schemas --indexes-dir infra/mongo/indexes` | PASS — offline/read-only Mongo schema/index/seed validation completed with zero local file errors and zero admin-client scope mismatches. |
| `python - <<'PY' ...` | NON-BLOCKING TOOLING MISS — system `python` is not on PATH in this shell. Re-run used `uv run python`. |
| `uv run python - <<'PY' ...` | PASS — readiness input presence checked without printing secret values. |

## Readiness Results

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

## Live/Sandbox Inputs

Only presence/absence was checked; no secret values were printed.

| Input | Required for | Status |
|---|---|---|
| `RabbitMQ_MANAGEMENT_EXPORT` | RabbitMQ management export comparison | Missing |
| `MONGO_URI` | Mongo read-only live metadata validation | Missing |
| `MODULE_REGISTRY_EXPORT` | module_registry export comparison | Missing |

Because all optional live/sandbox inputs are missing, no live/sandbox checks were run. This is not a failure of the readiness tooling; it means operator-provided read-only inputs are still needed.

## Next Approved Operator Commands

Run these only after the operator confirms the inputs point to the intended sandbox/live target. Do not print secret values in logs.

```bash
export RabbitMQ_MANAGEMENT_EXPORT=/path/to/rabbitmq-management-export.json
uv run python -m infra.rabbitmq.readiness \
  --definitions infra/rabbitmq/definitions.json \
  --management-export "$RabbitMQ_MANAGEMENT_EXPORT"
```

```bash
export MONGO_URI='mongodb://.../zeler_platform'
uv run python -m infra.mongo.readiness \
  --schemas-dir infra/mongo/schemas \
  --indexes-dir infra/mongo/indexes \
  --mongo-uri "$MONGO_URI"
```

```bash
export MODULE_REGISTRY_EXPORT=/path/to/module-registry-export.json
uv run python -m infra.mongo.readiness \
  --schemas-dir infra/mongo/schemas \
  --indexes-dir infra/mongo/indexes \
  --module-registry-export "$MODULE_REGISTRY_EXPORT"
```

## Explicit Non-Destructive Confirmation

- mutations_attempted: `0`
- no RabbitMQ imports or topology mutations attempted
- no Mongo `collMod`, `createIndex`, `drop`, data import, insert, or upsert attempted
- no module_registry seed apply attempted
- no GitHub, OAuth app, Cloud Run, VM, service, or database mutation attempted
- no deploy attempted
- no build attempted

## Risks

- Live/sandbox drift remains unknown until operator supplies `RabbitMQ_MANAGEMENT_EXPORT`, `MONGO_URI`, and/or `MODULE_REGISTRY_EXPORT`.
- `MONGO_URI` must be target-confirmed before running read-only metadata validation; a wrong URI could validate the wrong database even without mutation.
- Readiness validates presence/drift only; validator/index application and module_registry seed application remain separate mutating deployment/operator steps requiring explicit approval.
