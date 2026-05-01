# Pilot runbook — repricer

## Pre-flight checks

- Verify gateway `/health`, repricer API `/health`, and repricer worker `/health` return 200.
- Verify `meli_accounts` contains seller `82453304` with `status="active"`.
- Verify RabbitMQ queues and DLX bindings exist for `repricer.events` and `repricer.events.dlq`.
- Run `python -m tests.operations.preflight --module repricer --seller 82453304` against fakes/approved target before live execution.

## Setup

- Seed one active `repricer_rules` document for seller `82453304` and the pilot item.
- Confirm validators are current with `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.

## Trigger

- Publish an `items.price_updated` event for seller `82453304` to `meli.events` routing key `items.price_updated`.

## Evidence of success

- `repricer_history` contains one new idempotent decision for seller `82453304`.
- Gateway audit log records the proxied Meli item update and DLQ depth remains zero.

## Evidence of broken

- `repricer_history` has an error outcome, gateway returns non-2xx, or `worker.message.dlq` appears.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable the pilot `repricer_rules` document and drain/retry the module queue.
