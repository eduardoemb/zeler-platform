# Pilot runbook — autoreply

## Pre-flight

- Verify worker process is running: `docker compose ps autoreply-worker`.
- Verify API health returns 200: `curl https://autoreply.zeler.ai/health`.
- Verify gateway health returns 200.
- Verify `meli_accounts` has seller `82453304` with `status="active"` and non-expired tokens.
- Verify RabbitMQ topology: `python -m infra.rabbitmq.readiness --rabbitmq-url=$RABBITMQ_URL --read-only`.
- Verify Mongo validators: `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.
- Verify autoreply template docs and moderation policy exist.

## Setup

```javascript
db.autoreply_templates.insertOne({_id: "pilot-82453304-envio", seller_id: "82453304", match_type: "keyword", pattern: "envío", answer_text: "Hacemos envíos a todo el país.", enabled: true})
```

## Trigger

Ask a real question on a live listing of seller `82453304` containing the keyword `envío` via Meli's UI.

## Verify success

- `db.autoreply_history.findOne({seller_id: "82453304", outcome: "answered"})` exists.
- Gateway audit log shows `POST /answers` returning 200/201.
- Worker logs include `worker.message.ack`.

## Verify broken

- `db.autoreply_history.findOne({seller_id: "82453304", outcome: "no_match"})` exists for the test question.
- DLQ entry exists or gateway audit log shows non-2xx.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable template: `db.autoreply_templates.updateOne({_id: "pilot-82453304-envio"}, {$set: {enabled: false}})`.
