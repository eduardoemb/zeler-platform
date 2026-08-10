# AGENTS.md

## Project identity

This repository is `zeler-platform`: the canonical backend, data, workers, and
cloud/runtime platform for the Zeler product suite.

It works together with the active frontend repository `zeler-app` at
`/Users/eduardoramirez/Documents/repositorios/zeler-app`. Do not create a new
frontend for product UI work unless the user explicitly asks for one.

Do not treat `zeler-core` as the active project for this repo. References to
`zeler-core` are legacy/migration context only and must not be used as canonical
paths for new work.

## Current platform objective

The goal is a functional Zeler platform where `zeler-app` is the unified visual
interface and `zeler-platform` owns product APIs, sellers/accounts, auth, events,
workers, persistence, and runtime operations.

Current state from code/docs review:

- The platform is materially integrated: `zeler-app` calls live platform/module
  APIs through server-side clients and module-admin JWTs.
- The active products are `repricer`, `sheets`, `publicador`, and `autoreply`.
- Fulldock is retired and must remain unavailable unless explicitly reactivated.
- The remaining gap is not basic wiring; it is operational confidence: live
  smoke tests, stale-doc cleanup, runtime config verification, and finishing any
  product-specific stubs/follow-ups.

## Skill registry

Skill registry lives at
`/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md`.

## Project rules

- TDD strict: every non-trivial change starts with a failing test.
- Conventional commits only.
- No AI attribution in commits or pull requests.
- Never commit without being asked.
- Never print secrets, tokens, connection strings, OAuth codes, cookies, or raw
  production environment values.
- Never run local Docker builds. Use Cloud Build for production images only when
  the user explicitly authorizes build/deploy work.
- Do not mutate `../zeler-core` artifacts from this repository unless the user
  explicitly asks for cross-repo migration/decommission work.
- Prefer local `sdd/zeler-platform-greenfield/` artifacts as the source of truth
  for platform design, specs, tasks, and verification notes.
- For substantial product changes, use SDD (`/sdd-new`, `/sdd-ff`, `/sdd-apply`,
  `/sdd-verify`, `/sdd-archive`) instead of ad-hoc implementation.
- Worktree and branch administration is user-owned. Agents must not create,
  remove, switch, or require a Git worktree unless the user explicitly requests
  that operation.
- Work in the checkout and branch selected by the user. Before editing, inspect
  the working tree and preserve unrelated changes; never stash, discard, move,
  or combine existing work without explicit user approval.

## Stack summary

Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP.

- HTTP services/jobs target Cloud Run where applicable.
- Always-on APIs/workers currently run through VM Docker Compose in production.
- MongoDB targets are local Docker for development and the documented production
  MongoDB deployment path; older Atlas mentions in SDD/tasks may be historical
  or superseded.
- Secrets/crypto use GCP Secret Manager and KMS where applicable.
- Root quality gates: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv run mypy .`.

Production currently runs in GCP project `zeler-platform-dev`, VM
`platform-vm`, zone `us-central1-a`, with Docker Compose-managed services,
MongoDB, Caddy, and Artifact Registry images. Production Mongo must not be
queried from the local assistant environment; validate or repair production
Mongo only from the approved VM/VPC/runtime-container context, using sanitized
output and without printing `MONGO_URI` or credentials.

The team also operates connected production surfaces through available CLI
access where configured: GCP, Vercel, GitHub, and related tooling. Use those
tools carefully and prefer narrowly scoped deploys/restarts over broad changes.

## Architecture map

| Area | Canonical location | Notes |
| --- | --- | --- |
| Gateway/API edge | `gateway/` | FastAPI app for OAuth, webhooks, proxy, internal token broker, health, readiness, and observability. |
| Shared platform core | `core/` | Pydantic models, read repositories, Mongo schema export, event/idempotency helpers, auth/JWT/KMS utilities. |
| Product modules | `modules/` | Product APIs and workers for `repricer`, `sheets`, `publicador`, and `autoreply`. |
| Bootstrap jobs | `bootstrap/` | One-shot bootstrap/runtime setup jobs and status surfaces. |
| Infrastructure | `infra/` | Mongo validators/indexes/seeds, RabbitMQ topology, Docker/GCE/GCP runbooks and deploy helpers. |
| Cross-package tests | `tests/` | Integration, e2e, and platform-level contract tests. |
| Frontend | `../zeler-app` | Next.js UI for accounts, bootstrap, and product management screens. |

## Backend service boundaries

- `gateway/` owns platform entrypoints: MercadoLibre OAuth, token issuance and
  refresh, module proxying, webhook ingestion, health/readiness, metrics, and
  internal broker APIs.
- Modules should call MercadoLibre through the gateway/proxy path by default.
  Direct Meli calls are exceptional and guarded by repository checks.
- Product modules own product-specific APIs and workers. Shared seller/account,
  auth, events, and persistence contracts belong in `core/`.
- `bootstrap/` is for one-shot environment/account setup, not long-running
  product behavior.

## Frontend integration contract (`zeler-app`)

`zeler-app` is the active web UI, deployed at `https://app.zeler.ai`.

Expected integration model:

- Server-side env vars define live API URLs:
  `ZELER_GATEWAY_URL`, `REPRICER_API_URL`, `SHEETS_API_URL`,
  `PUBLICADOR_API_URL`, and `AUTOREPLY_API_URL`.
- `ZELER_APP_BROKER_SECRET` is server-only. Never expose it as `NEXT_PUBLIC_*`.
- `zeler-app` signs broker requests and calls gateway `/internal/tokens/issue`
  to mint short-lived `module_admin` JWTs.
- Module API calls use those JWTs and retry once on `401`.
- UI requests require a real linked/inactive-aware seller context; do not bypass
  OAuth or manually copy/reassign tokens.
- `module_registry._id = "zeler-app"` must remain enabled/scoped for the active
  seller and include all active admin scopes: `admin:repricer`, `admin:sheets`,
  `admin:publicador`, and `admin:autoreply`.

Known active app surfaces include:

- `/accounts`
- `/bootstrap/[jobId]`
- `/repricer/catalog`
- `/sheets/config`
- `/publicador/*` management routes, including drafts/publications-related views
- `/autoreply/*` management routes, including dashboard/questions/conversations,
  claims/config/templates-related views

## Product modules and parity status

| Product | Platform backend | App surface | Current status |
| --- | --- | --- | --- |
| Repricer | `modules/repricer/` | `/repricer/catalog` and related repricer views | Implemented for catalog/rules, limits, allies, bulk jobs, reports, monitoring, and worker processing. Prefer `/repricer/catalog`; older `/repricer/rules` references are stale. |
| Sheets | `modules/sheets/` | `/sheets/config` | Implemented for exports, sync jobs, extension tokens, formulas, and Google OAuth-sensitive configuration. Runtime credentials must be verified carefully. |
| Publicador | `modules/publicador/` | `/publicador/*` | Broadly implemented for drafts, publications, taxonomy, assets, AI, batches, suggestions, logs, stats, and settings. AI/provider features may fail closed or stub if provider config is missing. |
| Autoreply | `modules/autoreply/` | `/autoreply/*` | Implemented for dashboard/questions/conversations/claims read surfaces, config, templates, and worker reply flows. Some action surfaces may still be stubbed or incomplete. |
| Fulldock | Archive/decommission references only | none | Retired. Do not add routes, env vars, registry scopes, workers, or runtime config unless a future explicit reactivation restores the full module. |

## Legacy product references

Product parity work is planned product by product from legacy repositories.
Treat those repos as functional references, not runtime dependencies or canonical
infrastructure:

- `../sheetsellerappindividual` — legacy SheetSeller product. The add-on under
  `addon/` is the reference for Google Workspace / Google Sheets formula
  behavior. Old Mongo/GCP services are historical.
- `../repricer-meli` — legacy EasyReprice/Repricer product. Use the Next/FastAPI
  implementation as the main product reference; old React/Flask surfaces are
  historical unless explicitly requested. Amazon and deprecated automatic
  non-catalog repricing are out of current parity scope unless the user reopens
  them.
- `../Autoreplyia` — legacy Autoreply product. Use `backend-new/` and
  `frontend-new/` as the canonical product reference; `backend/` and `frontend/`
  are historical/deprecated.

When adapting legacy products:

- Do not recreate old standalone frontends.
- Do not depend on old Mongo databases or old GCP projects as sources of truth.
- Rebuild product state on `zeler-platform` collections/models and expose it via
  module APIs.
- Keep `zeler-app` responsible for management, configuration, operator-facing UI,
  and seller/account selection.
- Keep product-specific workers/event processing in `zeler-platform`.

## Cloud, database, and events

- GCP project: `zeler-platform-dev`.
- Production VM: `platform-vm` in `us-central1-a`.
- Runtime model: Docker Compose-managed gateway, module APIs, workers, MongoDB,
  and Caddy, with Artifact Registry images.
- Bootstrap/deploy path may use Cloud Build and Cloud Run Job configs where
  documented.
- MongoDB schema ownership lives in `core/models` plus validators/indexes/seeds
  under `infra/mongo/`.
- RabbitMQ uses the `meli.events` topic exchange with product workers consuming
  routing keys and DLQ/retry behavior.
- Prefer deploy/runbooks in `docs/deploy.md`, `infra/gce/`, and `infra/mongo/`
  over older readiness notes when docs conflict.

## Live integration notes

- Pilot seller used for operational smoke tests: `82453304`.
- For authenticated UI smoke, use a real `app.zeler.ai` session and a
  legitimately linked MercadoLibre seller.
- Do not bypass OAuth, manually copy tokens, or patch production data from local
  context.
- If `docs/live-readiness-validation.md` conflicts with deploy seeds about
  `zeler-app` scopes, prefer `docs/deploy.md` and
  `infra/mongo/seeds/module_registry.admin_clients.json`.

## Known risks and gaps

- Live operational state must be verified from the approved runtime context; code
  and docs alone do not prove production health.
- Some older docs still mention stale Repricer routes or incomplete registry
  scopes.
- Publicador AI paths depend on provider/runtime configuration and may fail
  closed if not configured.
- Autoreply has broad UI/API coverage, but some claims/messages/actions surfaces
  may still be read-only, stubbed, or incomplete.
- Bootstrap has known follow-ups around retry, drift reports, alerting, and
  reconciliation.

## SDD design

See `sdd/zeler-platform-greenfield/design.md`.

Related local artifacts:

- `sdd/zeler-platform-greenfield/spec.md`
- `sdd/zeler-platform-greenfield/tasks.md`
- `sdd/zeler-platform-greenfield/verify-report*.md`
