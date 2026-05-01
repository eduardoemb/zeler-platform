# Pilot runbook — autoreply

## Pre-flight checks

- Verify gateway `/health`, autoreply API `/health`, and autoreply worker `/health` return 200.
- Verify `meli_accounts` contains seller `82453304` with `status="active"`.
- Verify RabbitMQ queues and DLX bindings exist for `autoreply.events` and `autoreply.events.dlq`.
- Run `python -m tests.operations.preflight --module autoreply --seller 82453304` against fakes/approved target before live execution.

## Setup

- Seed the pilot `autoreply_templates` entry for seller `82453304`.
- Confirm messaging scopes are enabled for the pilot seller.

## Trigger

- Publish a fake question/message event for seller `82453304` to the autoreply routing key.

## Evidence of success

- `autoreply_templates`/reply history show one response decision for seller `82453304`.
- Gateway audit log records the reply call and DLQ depth remains zero.

## Evidence of broken

- Reply status is failed, worker health flips red, or `worker.message.dlq` appears.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable pilot `autoreply_templates` and drain/retry the module queue.
