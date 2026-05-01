# Pilot runbook — fulldock

## Pre-flight checks

- Verify gateway `/health`, fulldock API `/health`, and fulldock worker `/health` return 200.
- Verify `meli_accounts` contains seller `82453304` with `status="active"`.
- Verify RabbitMQ queues and DLX bindings exist for `fulldock.events` and `fulldock.events.dlq`.
- Run `python -m tests.operations.preflight --module fulldock --seller 82453304` against fakes/approved target before live execution.

## Setup

- Seed the pilot `fulldock_inventory_rules` entry for seller `82453304`.
- Confirm stock-location write scope is present before any live write.

## Trigger

- Publish a stock/location test event for seller `82453304` to the fulldock routing key.

## Evidence of success

- `fulldock_inventory_rules`/history shows one idempotent stock-location action for seller `82453304`.
- Gateway audit log records the write and DLQ depth remains zero.

## Evidence of broken

- Stock-location update fails, worker health flips red, or `worker.message.dlq` appears.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Revert the stock-location pilot change and disable the pilot rule.
