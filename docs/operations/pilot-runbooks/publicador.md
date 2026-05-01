# Pilot runbook — publicador

## Pre-flight checks

- Verify gateway `/health` and publicador API `/health` return 200.
- Verify `meli_accounts` contains seller `82453304` with `status="active"`.
- Verify RabbitMQ topology is applied even though publicador is API-led.
- Run `python -m tests.operations.preflight --module publicador --seller 82453304` against fakes/approved target before live execution.

## Setup

- Create a pilot `publicador_drafts` record for seller `82453304` or use the HTTP draft endpoint.
- Confirm `LISTING_LLM`/`OPENAI_API_KEY` posture is intentional; `llm_not_configured` is acceptable only for diagnostics.

## Trigger

- POST `/publicador/drafts/{draft_id}/publish` with a valid module JWT for seller `82453304`.

## Evidence of success

- `publicador_history` contains a published row for seller `82453304` or an intentional `llm_not_configured` diagnostic is captured before publish.
- Gateway audit log records the proxied Meli publish request when publish is executed.

## Evidence of broken

- Publish returns non-2xx, `publicador_history` is missing, or gateway proxy errors are present.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Delete/mark test drafts and published pilot artifacts as rolled back.
