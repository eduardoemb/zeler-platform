# Pilot runbook — repricer

## Pre-flight

- Verify worker process is running: `docker compose ps repricer-worker`.
- Verify API health returns 200: `curl https://repricer.zeler.ai/health`.
- Verify gateway health returns 200: `curl https://gateway.zeler.ai/health`.
- Verify `meli_accounts` has seller `82453304` with `status="active"` and non-expired tokens.
- Verify RabbitMQ topology: `python -m infra.rabbitmq.readiness --rabbitmq-url=$RABBITMQ_URL --read-only`.
- Verify Mongo validators: `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.
- Verify repricer rules/config documentation exists for the pilot item.

## Setup

Insert exactly one active repricer rule for an item owned by seller `82453304`:

```javascript
db.repricer_rules.insertOne({
  _id: "pilot-82453304-<test_item>",
  seller_id: "82453304",
  item_id: "<test_item>",
  strategy: "min_price",
  min_price: 10000,
  max_price: 20000,
  active: true
})
```

## Trigger

Publish an `items.price_updated` event to the `meli.events` exchange using `gateway/cli/replay.py`:

```bash
python gateway/cli/replay.py --exchange meli.events --routing-key items.price_updated --json '{"event_id":"pilot-repricer-82453304","event_type":"items.price_updated","seller_id":"82453304","resource":"/items/<test_item>"}'
```

Alternatively, wait for a real Meli webhook for the same item.

## Verify success

- `db.repricer_history.findOne({seller_id: "82453304"}, {sort: {applied_at: -1}})` shows the latest decision.
- Gateway audit log has the proxied Meli price update.
- Worker logs include `worker.message.ack` for `pilot-repricer-82453304`.

## Verify broken

- `db.repricer_history.find({seller_id: "82453304", outcome: "error"})` is non-empty.
- DLQ depth is `>0` or logs contain `worker.message.dlq`.
- Gateway returns non-200 for the proxied Meli call.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Delete the pilot rule: `db.repricer_rules.deleteOne({_id: "pilot-82453304-<test_item>"})`.
- Re-run health and DLQ checks before resuming.
