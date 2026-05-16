# Operations pilot runbook — Publicador

## Pre-flight checks

- Live validation is allowed only after explicit approval and only for pilot seller `82453304`.
- Use an authenticated zeler-app session or approved VM/VPC/runtime container; never use local production Mongo access.
- Verify gateway and Publicador API health from approved VM/VPC/runtime context.
- Verify `zeler-app` admin client and Publicador scopes are enabled for seller `82453304` with sanitized output.
- Verify live config fails closed if `PUBLICADOR_API_URL` or gateway settings are absent, local, or legacy.
- Verify no unrelated Fulldock/decommission workspace changes are part of the candidate deploy revision.

## Setup

- Select only pilot `publicador_drafts` records for seller `82453304` from approved VM/VPC/runtime tooling with sanitized output.
- Authentication must flow through zeler-app broker/module-admin credentials for `admin:publicador`; do not copy credential material into terminal output, screenshots, tickets, or docs.
- Output must be sanitized: route, seller id, status class, and high-level outcome only.

## Trigger

- Route smoke every Publicador parity route from `docs/runbooks/pilot-publicador.md`.
- Confirm each route renders data, an explicit empty state, or a safe blocked state.
- Confirm module-admin requests are seller-scoped and no static browser-visible Publicador credential is used.
- If publish smoke is executed, confirm paused stock-zero behavior and seller-scoped event/history recording with sanitized evidence only.

## Evidence of success

- Sanitized route matrix shows data, empty state, or safe blocked state for pilot seller `82453304`.
- Sanitized `publicador_drafts`/event/history summary proves seller-scoped reads and writes without exposing production environment values.
- Published pilot checks, if executed, prove paused stock-zero behavior through gateway/proxy.

## Evidence of broken

- Missing live API config, local fallback, legacy runtime target, unauthenticated browser session, or unsafe workspace contamination blocks smoke/deploy.
- Non-2xx publish, missing seller-scoped event/history, unsanitized output, or OAuth bypass attempt fails the smoke.

## Rollback

- Disable Publicador navigation/scope for the pilot seller or redeploy the previous revision for zeler-app if route safety regresses.
- Redeploy the previous image for the Publicador API if backend hardening or publish behavior regresses.
- Mark pilot artifacts as rolled back from approved VM/VPC/runtime context and keep sanitized before/after evidence.
