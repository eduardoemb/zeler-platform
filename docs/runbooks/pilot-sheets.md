# Pilot runbook — sheets

## Pre-flight

- Verify worker process is running: `docker compose ps sheets-worker`.
- Verify API health returns 200: `curl https://sheets.zeler.ai/health`.
- Verify gateway health returns 200.
- Verify `meli_accounts` has seller `82453304` with `status="active"` and non-expired tokens.
- Verify RabbitMQ topology: `python -m infra.rabbitmq.readiness --rabbitmq-url=$RABBITMQ_URL --read-only`.
- Verify Mongo validators: `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.
- Verify Google OAuth and sheets export configuration docs exist.

## Setup

Complete Google OAuth for seller `82453304`:

```text
https://sheets.zeler.ai/oauth/google/authorize?seller_id=82453304
```

Then configure the export:

```javascript
db.sheets_exports.insertOne({_id: "pilot-82453304-events", seller_id: "82453304", enabled: true, spreadsheet_id: "<spreadsheet_id>", worksheet_name: "Events"})
```

## Trigger

Publish an `items.updated` event for an item owned by `82453304` using `gateway/cli/replay.py`, or wait for the real Meli webhook.

## Verify success

- Operator visually confirms a new row in the configured Google Sheet.
- `db.processed_events.findOne({seller_id: "82453304"})` has a new entry.
- Worker logs include `worker.message.ack`.

## Verify broken

- Worker logs include `worker.message.dlq`.
- `db.sheets_exports.findOne({seller_id: "82453304"}).last_sync_status === "error"`.
- Gateway returns non-200 while fetching the resource.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable export: `db.sheets_exports.updateOne({_id: "pilot-82453304-events"}, {$set: {enabled: false}})`.
