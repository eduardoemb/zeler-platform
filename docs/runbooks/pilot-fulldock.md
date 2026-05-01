# Pilot runbook — fulldock

## Pre-flight

- Verify worker process is running: `docker compose ps fulldock-worker`.
- Verify API health returns 200: `curl https://fulldock.zeler.ai/health`.
- Verify gateway health returns 200.
- Verify `meli_accounts` has seller `82453304` with `status="active"` and non-expired tokens.
- Verify RabbitMQ topology: `python -m infra.rabbitmq.readiness --rabbitmq-url=$RABBITMQ_URL --read-only`.
- Verify Mongo validators: `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.
- Confirm seller `82453304` has Meli Full enabled and OAuth scope for `PUT /items/*/stock_locations`.

## Setup

```javascript
db.fulldock_inventory_rules.insertOne({_id: "pilot-82453304-stock", seller_id: "82453304", item_id: "<item_id>", enabled: true, target_location_id: "<target_location_id>", target_quantity: 10})
```

## Trigger

Emit an `items.updated` or `shipments.updated` event for the item using `gateway/cli/replay.py`, or wait for the real Meli webhook.

## Verify success

- `db.fulldock_history.findOne({seller_id: "82453304", outcome: "updated"})` exists.
- Gateway audit log shows `PUT /items/<id>/stock_locations` returning 200.
- Worker logs include `worker.message.ack`.

## Verify broken

- `db.fulldock_history.findOne({seller_id: "82453304", outcome: "malformed_resource"})` exists.
- Gateway audit log has 403 from Meli, usually missing OAuth scope.
- DLQ entry exists.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable pilot rule: `db.fulldock_inventory_rules.updateOne({_id: "pilot-82453304-stock"}, {$set: {enabled: false}})`.
