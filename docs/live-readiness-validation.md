# Live Readiness Validation Runbook

## Non-destructive readiness validation

This runbook is for sandbox/live **validation only**. The tooling below is designed to report `safe_to_execute` and `read_only` explicitly and must not mutate RabbitMQ, MongoDB, Meli, or production data.

## Safety model

- `python -m infra.rabbitmq.readiness` reads `infra/rabbitmq/definitions.json` and, optionally, a RabbitMQ management export JSON file.
- `python -m infra.mongo.readiness` reads local `infra/mongo/schemas/*.json` and `infra/mongo/indexes/*.json`; optional live mode only calls read-only Mongo metadata APIs (`listCollections`, `listIndexes`).
- Do not run `infra/mongo/apply_validators.py` as part of readiness validation; that script performs `collMod` / index application and belongs to an explicit deployment step.
- Do not import RabbitMQ definitions during readiness validation; import/apply operations are deployment steps and require operator approval.

## Required environment variables

Offline mode requires no credentials.

Optional sandbox/live checks:

- `RabbitMQ_MANAGEMENT_EXPORT`: path to a JSON export from RabbitMQ Management UI/API. Generate it outside this tool, then pass it as `--management-export "$RabbitMQ_MANAGEMENT_EXPORT"`.
- `MONGO_URI`: MongoDB URI for the target database. The readiness tool uses it in read-only metadata mode only.

## Sandbox validation sequence

1. Run local/offline validation first:
   ```bash
   python -m infra.rabbitmq.readiness --definitions infra/rabbitmq/definitions.json
   python -m infra.mongo.readiness --schemas-dir infra/mongo/schemas --indexes-dir infra/mongo/indexes
   ```
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
5. Review `safe_to_execute: true`, `read_only: true`, `mutations_attempted: 0`, and any `fail` findings before production deployment.

## Production validation sequence

Repeat the sandbox sequence with production exports/URI only in an approved change window. These checks are read-only, but production credentials still require normal operational handling.

## What this runbook does not do

- It does not create exchanges, queues, bindings, validators, collections, or indexes.
- It does not import RabbitMQ definitions.
- It does not call `collMod`, `createIndex`, `drop`, or data import commands.
- It does not connect to Meli or validate live Meli OAuth scopes.
