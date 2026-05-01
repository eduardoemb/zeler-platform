# Pilot runbook — publicador

## Pre-flight

- Verify worker process is not required for request-driven publicador, and API service is running.
- Verify API health returns 200: `curl https://publicador.zeler.ai/health`.
- Verify gateway health returns 200.
- Verify `meli_accounts` has seller `82453304` with `status="active"` and non-expired tokens.
- Verify RabbitMQ topology: `python -m infra.rabbitmq.readiness --rabbitmq-url=$RABBITMQ_URL --read-only`.
- Verify Mongo validators: `python -m infra.mongo.drift_check --mongo-uri=$MONGO_URI`.
- Verify publicador templates/category/export docs exist.

## Setup

Ensure `OPENAI_API_KEY` is configured. If not configured, `Stub503LLM` returns HTTP 503 with `code="llm_not_configured"`; that proves routing is wired but does not publish.

## Trigger

Create a draft, generate content, then publish:

```bash
curl -X POST https://publicador.zeler.ai/publicador/drafts -H 'Content-Type: application/json' -d '{"seller_id":"82453304","title":"Pilot item","category_id":"MLA123","price":10000}'
curl -X POST https://publicador.zeler.ai/publicador/drafts/<draft_id>/generate
curl -X POST https://publicador.zeler.ai/publicador/drafts/<draft_id>/publish
```

## Verify success

- `db.publicador_drafts.findOne({seller_id: "82453304"})` has the draft.
- `db.publicador_history.findOne({seller_id: "82453304", outcome: "published"})` has a Meli `item_id`.
- Gateway audit log shows `POST /items` returning 200/201.

## Verify broken

- 503 with `code="llm_not_configured"` means the stub is still in use.
- `db.publicador_history.find({seller_id: "82453304", outcome: "failed"})` contains Meli error payloads.

## Rollback

- Pause seller `82453304` using `docs/runbooks/account-kill-switch.md`.
- Delete or archive the pilot draft from `publicador_drafts`.
