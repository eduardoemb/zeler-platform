# Pilot runbook — Publicador

## Safety contract

- Execute live checks only with explicit approval, pilot seller `82453304`, and an authenticated `https://app.zeler.ai` session or approved VM/VPC/runtime container.
- Use the zeler-app broker/module-admin flow for `admin:publicador`; do not paste credentials into commands, tickets, screenshots, or logs.
- Production Mongo validation must run only from approved VM/VPC/runtime context and must emit sanitized counts/status summaries, never connection details.
- Stop if unrelated Fulldock/decommission workspace changes would be included in a deploy, commit, or smoke revision.

## Pre-flight

- Confirm the committed revision is Publicador-only and all Batch 8 regression tests passed or blockers are documented.
- Confirm gateway and Publicador API health from the approved runtime context.
- Confirm `module_registry._id = "zeler-app"` is enabled for pilot seller `82453304` and `admin:publicador` scope using sanitized output.
- Confirm `PUBLICADOR_API_URL` and gateway settings point at live Zeler surfaces and fail closed if absent/local/legacy.

## Smoke route matrix

Open the Publicador routes from the real app session and record only sanitized route/status/outcome evidence:

- `/publicador/dashboard`
- `/publicador/products/new`
- `/publicador/products/new/assets`
- `/publicador/products/new/generate`
- `/publicador/products/new/taxonomy`
- `/publicador/publications`
- `/publicador/publications/<publication_id>`
- `/publicador/publications/<publication_id>/approval`
- `/publicador/publications/<publication_id>/process`
- `/publicador/publications/<publication_id>/validation`
- `/publicador/publications/<publication_id>/publish-review`
- `/publicador/publications/<publication_id>/catalog`
- `/publicador/batches`
- `/publicador/batches/new`
- `/publicador/batches/<batch_id>`
- `/publicador/suggestions`
- `/publicador/logs`
- `/publicador/statistics`
- `/publicador/settings`

Acceptable result per route: data rendered, explicit empty state, or safe blocked state that names the missing configuration/permission without exposing credentials.

## Publish smoke guardrails

- Only publish a deliberately prepared pilot draft for seller `82453304`.
- Expected publish payload remains paused with available quantity `0`.
- Evidence must be sanitized: route, operation, HTTP status class, draft/publication identifier category, and whether the seller-scoped history/event was recorded.
- Do not run ad-hoc local scripts against production data; use approved runtime tooling only.

## Rollback

- Disable the Publicador UI entry point for the affected seller/module scope or redeploy the previous revision if route safety regresses.
- Redeploy the previous image for the Publicador API if publish/config hardening regresses.
- Pause or archive pilot artifacts for seller `82453304` using approved runtime operations with sanitized evidence.
- Re-run the route matrix after rollback and attach sanitized before/after status.
