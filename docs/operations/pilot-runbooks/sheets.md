# Pilot runbook — sheets

## Pre-flight checks

- Verify gateway `/health`, sheets API `/health`, and sheets worker `/health` return 200.
- Verify `meli_accounts` contains seller `82453304` with `status="active"`.
- Verify RabbitMQ queues and DLX bindings exist for `sheets.events` and `sheets.events.dlq`.
- Run `python -m tests.operations.preflight --module sheets --seller 82453304` against fakes/approved target before live execution.

## Setup

- Seed the pilot `sheets_exports` configuration for seller `82453304`.
- Confirm spreadsheet credentials and Mongo validators are ready.

## Trigger

- Publish an inventory/catalog sync event for seller `82453304` to the sheets routing key.

## Evidence of success

- `sheets_exports` contains one completed export/sync record for seller `82453304`.
- Gateway audit log records expected read calls and DLQ depth remains zero.

## Evidence of broken

- Export status is failed, sheets worker health flips red, or `worker.message.dlq` appears.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Disable the pilot `sheets_exports` config and remove any test spreadsheet output.
