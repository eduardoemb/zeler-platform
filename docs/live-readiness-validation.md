# Live Readiness Validation Runbook

## Non-destructive readiness validation

This runbook is for sandbox/live **validation only**. The tooling below is designed to report `safe_to_execute` and `read_only` explicitly and must not mutate RabbitMQ, MongoDB, Meli, or production data.

## Safety model

- `python -m infra.rabbitmq.readiness` reads `infra/rabbitmq/definitions.json` and, optionally, a RabbitMQ management export JSON file.
- `python -m infra.mongo.readiness` reads local `infra/mongo/schemas/*.json`, `infra/mongo/indexes/*.json`, and `infra/mongo/seeds/*.json`; optional live mode only calls read-only Mongo metadata APIs (`listCollections`, `listIndexes`).
- Module registry seed readiness validates `infra/mongo/seeds/module_registry.admin_clients.json` as a local JSON contract and can compare expected admin clients against a separately exported `module_registry` JSON file. The readiness command is read-only: it never inserts, upserts, imports, or repairs seed data.
- Do not run `infra/mongo/apply_validators.py` as part of readiness validation; that script performs `collMod` / index application and belongs to an explicit deployment step.
- Do not apply module_registry seeds as part of readiness validation; seed application is a separate manual/deployment step with explicit operator approval.
- Do not import RabbitMQ definitions during readiness validation; import/apply operations are deployment steps and require operator approval.

## Required environment variables

Offline mode requires no credentials.

Optional sandbox/live checks:

- `RabbitMQ_MANAGEMENT_EXPORT`: path to a JSON export from RabbitMQ Management UI/API. Generate it outside this tool, then pass it as `--management-export "$RabbitMQ_MANAGEMENT_EXPORT"`.
- `MONGO_URI`: MongoDB URI for the target database. The readiness tool uses it in read-only metadata mode only.
- `MODULE_REGISTRY_EXPORT`: optional path to a read-only export of live/sandbox `module_registry` documents. Generate it outside the readiness tool, then pass it as `--module-registry-export "$MODULE_REGISTRY_EXPORT"`.

## Sandbox validation sequence

1. Run local/offline validation first:
   ```bash
   python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json
   python -m infra.mongo.readiness --schemas-dir infra/mongo/schemas --indexes-dir infra/mongo/indexes
   ```
   This validates the local `module_registry.admin_clients.json` seed shape, including the `zeler-app` admin client and its `admin:repricer` scope.
2. Export RabbitMQ definitions from the sandbox management console/API into a file.
3. Compare expected topology against the export:
   ```bash
   python -m infra.rabbitmq.readiness \
     --definitions infra/rabbitmq/definitions.json \
     --management-export "$RabbitMQ_MANAGEMENT_EXPORT"
   ```
4. Run read-only Mongo metadata validation only after the operator confirms the URI points at sandbox:
   ```bash
   python -m infra.mongo.readiness \
     --schemas-dir infra/mongo/schemas \
     --indexes-dir infra/mongo/indexes \
     --mongo-uri "$MONGO_URI"
   ```
5. Optionally compare a sandbox/live `module_registry` export against the local admin-client seed contract:
   ```bash
   python -m infra.mongo.readiness \
     --schemas-dir infra/mongo/schemas \
     --indexes-dir infra/mongo/indexes \
     --module-registry-export "$MODULE_REGISTRY_EXPORT"
   ```
6. Review `safe_to_execute: true`, `read_only: true`, `mutations_attempted: 0`, and any `fail` findings before production deployment.

## Manual module_registry seed apply / verify

Readiness only proves that the seed file is well-formed and, when an export is supplied, that expected read-only docs are present. To apply the admin-client seed in a sandbox/live database, use a separate approved operation outside the readiness command:

1. Confirm the target database and change window.
2. Review `infra/mongo/seeds/module_registry.admin_clients.json` and verify it contains `_id="zeler-app"`, `status="enabled"`, and only the intended `allowed_meli_scopes` (`admin:repricer`).
3. Apply the seed with the team's approved Mongo import/upsert procedure. This is intentionally not implemented by `infra.mongo.readiness`.
4. Export or query `module_registry` read-only after the apply step and re-run readiness with `--module-registry-export "$MODULE_REGISTRY_EXPORT"`.
5. Treat missing `zeler-app` or scope mismatch findings as a failed bootstrap; do not proceed to zeler-app admin-token smoke checks until corrected by an explicit apply step.

## Production validation sequence

Repeat the sandbox sequence with production exports/URI only in an approved change window. These checks are read-only, but production credentials still require normal operational handling.

## What this runbook does not do

- It does not create exchanges, queues, bindings, validators, collections, or indexes.
- It does not import RabbitMQ definitions.
- It does not call `collMod`, `createIndex`, `drop`, or data import commands.
- It does not apply module registry seeds, insert `zeler-app`, or upsert `allowed_meli_scopes`.
- It does not connect to Meli or validate live Meli OAuth scopes.
