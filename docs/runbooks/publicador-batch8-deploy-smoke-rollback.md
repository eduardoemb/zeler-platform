# Publicador Batch 8 — deploy, smoke, rollback

## Scope

This runbook covers Publicador parity Batch 8 only: config fail-closed checks, safe deploy preparation, route smoke, sanitized evidence, and rollback. It must not include unrelated Fulldock/decommission work.

## Required gates before deploy

- Backend Publicador regression tests and Batch 8 hardening tests are green, or unrelated failures are documented separately.
- zeler-app Publicador tests are green, including live config safety and smoke checklist contracts.
- Candidate commits contain Publicador-only changes. Stop if unrelated Fulldock/decommission files would be staged, deployed, or pushed.
- Runtime validation is performed from an authenticated zeler-app session or approved VM/VPC/runtime container only.

## Config fail-closed contract

- Publicador API mode requires live gateway proxy configuration and a server-side module gateway credential available only to the runtime.
- `PUBLICADOR_API_URL` must point at the live Publicador API base for zeler-app; missing, local, or legacy values must block the route/action.
- MercadoLibre access must go through gateway/proxy and module-admin/server-token flow.
- Evidence must be sanitized and must never include credential values, cookies, OAuth codes, or production environment values.

## Smoke route matrix

Use pilot seller `82453304`; replace placeholder IDs only with legitimate pilot records from the approved runtime context.

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

Expected result: each route renders data, explicit empty state, or safe blocked state. Record only sanitized status/outcome.

## Deploy preparation

- Backend image publication, if needed, must use Cloud Build or the existing deployment workflow; never run local Docker builds.
- zeler-app deploy must use the existing Vercel/project workflow and server-only broker/module-admin configuration.
- If deploy cannot be performed from a committed Publicador-only revision, stop and report the blocker instead of deploying.

## Rollback

- zeler-app: redeploy the previous revision or disable the Publicador route/module scope for the pilot seller if UI config safety regresses.
- Publicador API: redeploy the previous image if backend gateway config, publish paused stock-zero behavior, or sanitized logging regresses.
- Pilot data: mark pilot records as rolled back or paused from approved VM/VPC/runtime context with sanitized evidence.
- After rollback, re-run the smoke route matrix and compare sanitized before/after outcomes.
