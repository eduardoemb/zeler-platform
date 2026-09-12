# AGENTS.md

## Project identity

This repository is `zeler-platform`: the canonical backend, data, workers, and
cloud/runtime platform for the Zeler product suite.

It works together with the active frontend repository `../zeler-app`. Check that
the checkout exists before accessing it. Do not create a new frontend for product
UI work unless the user explicitly asks for one.

Do not treat `zeler-core` as the active project for this repo. References to
`zeler-core` are legacy/migration context only and must not be used as canonical
paths for new work.

## Current platform objective

The goal is a functional Zeler platform where `zeler-app` is the unified visual
interface and `zeler-platform` owns product APIs, sellers/accounts, auth, events,
workers, persistence, and runtime operations.

The active products are `repricer`, `sheets`, `publicador`, and `autoreply`.
Their display names are ZelerPricing, ZelerData, ZelerListings, and ZelerSupport,
respectively. Module IDs remain stable API, registry, event and runtime contracts;
display-name changes do not authorize renaming them.
Fulldock is retired and must remain unavailable unless explicitly reactivated.
For integration or runtime assessments, consult the relevant implementation,
verification notes under `sdd/zeler-platform-greenfield/`, and deployment
runbooks. Code and historical notes alone do not prove current production health.

## Skill registry

Skill registry lives at `.atl/skill-registry.md`, relative to this checkout.

## Project rules

- TDD strict: every non-trivial change to executable behavior starts with a
  failing test. For documentation and instructions, verify coherence, references,
  and applicable examples instead.
- Before planning or changing an area's behavior, consult
  `docs/lessons/README.md`: read **Quick path**, search its active index by area
  and keywords, and read matching entries. Reuse session readings while they
  remain current; editorial-only changes do not require this lookup. Search
  Engram when needed prior-work or runtime context is missing from the session.
  If Engram is unavailable, report the limitation and continue when local
  evidence is sufficient. Apply proven paths, avoid failed paths, and record
  only durable learnings when work ends. Runtime memories are leads to verify,
  not evidence of current health.
- Conventional commits only.
- No AI attribution in commits or pull requests.
- Never commit without being asked.
- Never print secrets, tokens, connection strings, OAuth codes, cookies, or raw
  production environment values.
- Never run local Docker builds. Use Cloud Build for production images only when
  the user explicitly authorizes the build. Build authorization does not authorize
  deployment.
- At the end of a session that produces or confirms runtime-affecting changes
  merged into `main`, determine which service images are affected and compare
  the intended `main` commit with the deployed image/source commit when runtime
  evidence is available. If an image is stale or must be rebuilt, explicitly
  recommend a new Cloud Build image for the affected service and name the
  required runtime verification. Building and deploying remain separate actions
  that require explicit user authorization; never perform either action solely
  because drift was detected. If deployment evidence is unavailable, recommend
  verifying image drift instead of assuming the runtime is current.
- Do not mutate `../zeler-core` artifacts from this repository unless the user
  explicitly asks for cross-repo migration/decommission work.
- Prefer local `sdd/zeler-platform-greenfield/` artifacts as the source of truth
  for the original platform design. For an individual change, use its selected
  artifacts, including `openspec/changes/<change>/` when applicable; do not
  substitute a different change's or store's copy.
- For substantial product changes, use SDD (`/sdd-new`, `/sdd-ff`, `/sdd-apply`,
  `/sdd-verify`, `/sdd-archive`) instead of ad-hoc implementation. This includes
  changes to contracts, persistence, service boundaries, or product workflows.
  Questions, documentation-only changes, and localized fixes preserving those
  contracts and boundaries do not require the full SDD workflow.
- Worktree and branch administration is user-owned. Agents must not create,
  remove, switch, or require a Git worktree unless the user explicitly requests
  that operation.
- Work in the checkout and branch selected by the user. Before editing, inspect
  the working tree and preserve unrelated changes; never stash, discard, move,
  or combine existing work without explicit user approval.
- Complete authorized implementation and verification in the selected checkout
  without stopping to request permission for commits, branch/worktree operations,
  builds, or deployments that are not needed for that work. Request authorization
  only when such an operation is necessary and not already authorized. Continue
  independent authorized work while a required decision is pending. Completion
  includes fixing failures caused by the change and rerunning affected checks;
  report any unresolved blockers without claiming the task is complete.

## Stack summary

Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP.

- Install the workspace with `uv sync --all-packages`. Package implementations
  live in `<package>/src/` and focused tests in `<package>/tests/`.
- HTTP services/jobs target Cloud Run where applicable.
- Always-on APIs/workers currently run through VM Docker Compose in production.
- MongoDB targets are local Docker for development and the documented production
  MongoDB deployment path; older Atlas mentions in SDD/tasks may be historical
  or superseded.
- Secrets/crypto use GCP Secret Manager and KMS where applicable.
- Root quality gates: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv run mypy .`.
  Run focused checks during implementation and all four gates when code changes
  are complete. Repeat checks when changes, failures, or invalidated evidence
  justify it. Preserve independent final SDD verification when applicable.
  Documentation-only tasks require documentation validation, not the code suite.
- CI also runs `uv run python -m infra.lint.check_direct_meli .` and
  `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check`.
  Run these for gateway/Meli access changes and schema/model changes respectively.
  CI's current mypy job covers selected files, so green CI does not establish
  that full-repository mypy passed. Report pre-existing failures separately from
  regressions; do not silently reduce the required checks.
- Tests that access Mongo must use a verified development/test target:
  `conftest.py` accepts the environment's `MONGO_URI`, so do not assume the full
  suite is isolated or uses disposable data. Never use production for local tests.

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
| Google Sheets add-on | `modules/sheets/apps_script/sheetseller/` | Active Apps Script source; management UI remains in `zeler-app`. Publication has its own operator runbook. |

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

## Product modules

| Product | Platform backend | App surface | Area-specific guidance |
| --- | --- | --- | --- |
| Repricer | `modules/repricer/` | `/repricer/catalog` | Prefer `/repricer/catalog`; older `/repricer/rules` references are stale. |
| Sheets | `modules/sheets/` | `/sheets/config` | Verify Google OAuth-sensitive runtime configuration when assessing live integration. |
| Publicador | `modules/publicador/` | `/publicador/*` | Verify provider configuration and actual behavior before claiming AI features work. |
| Autoreply | `modules/autoreply/` | `/autoreply/*` | Verify action behavior; read surfaces alone do not prove claims/messages/actions are implemented. |
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
- MongoDB schema ownership lives in `core/src/zeler_platform_core/models/` plus validators/indexes/seeds
  under `infra/mongo/`.
- RabbitMQ uses the `meli.events` topic exchange with product workers consuming
  routing keys and DLQ/retry behavior.
- Prefer deploy/runbooks in `docs/deploy.md`, `infra/gce/`, and `infra/mongo/`
  over older readiness notes when docs conflict.

## Build, deploy, and runtime inspection

- For build/deploy work, read the applicable sections of `docs/deploy.md` and
  deployment lessons. Confirm project, VM, zone, authorized commit and affected
  services; do not assume other VMs share `platform-vm`'s configuration.
- Build from the connected repository at an exact authorized commit present in
  `main`, not an uploaded local checkout. Use one deployable image per Cloud
  Build with `options.requestedVerifyOption: VERIFIED`. Verify successful build,
  repository, source commit and immutable digest; record build ID, full commit
  and `repo@sha256:...`. Tags alone are not deployment authority.
- Each deployment proposal names services, target images, bounded cleanup if
  needed, verification and compatible rollback. One approval covers that explicit
  scope; ask only for an expansion. Build permission remains separate. Prepare
  the proposal completely before requesting any missing authorization.
- A health/capacity inspection is read-only: check free bytes and inodes on `/`
  and `/var/lib/zeler-mongo`, the Mongo mount, available memory, Docker usage,
  service health, restart counts and OOM flags. Use sanitized, narrowly selected
  output. Inspection does not authorize cleanup, downloads, restarts or repairs.
- Require at least 5 GiB free on `/` before every image download, including
  rollback attestation, and recheck after downloads. This is a minimum; assess
  pull headroom. Mongo disk and memory need separate measurements, not an invented
  numeric threshold. Do not assume a fixed boot-disk size or resize automatically.
- Use `infra/gce/docker-deploy-preflight.sh --dry-run` for capacity checks; add
  `REQUIRE_DIGEST_BINDING=1` for selected image-reference checks. It does not attest provenance or rollback compatibility.
  Normal preflight can download attestation images or write evidence; cleanup
  additionally requires approved `ALLOW_DOCKER_MAINTENANCE=1`. Never prune Docker
  volumes. Preserve a compatible, retrievable rollback before authorized cleanup.
- Record the previous running image's immutable identity, not merely the Compose
  tag. Verify rollback compatibility with schemas, registry scopes and topology.
  Replace exactly the intended service image, deploy narrowly, and follow the
  product runbook's migration/dependency order. Do not run broad Compose restarts.
- Verify the running digest, container health, dependency readiness and affected
  product behavior. Gateway `/health` is liveness; `/ready` checks dependencies.
  Workers require consumer/component readiness, not old startup log messages.
  Observe again after the service's settling window; outer timeouts must exceed
  Docker stop grace. Repeat health and capacity checks after deploy or rollback.
- Treat validator application as a separately scoped rollout mutation, never as
  a read-only health check. Drift detection alone does not authorize repair.
- Report measured evidence and unresolved failures. Container startup, HTTP 200
  alone, or a completed command is not proof of a stable deployment.

## Live integration notes

- Pilot seller used for operational smoke tests: `82453304`.
- For authenticated UI smoke, use a real `app.zeler.ai` session and a
  legitimately linked MercadoLibre seller.
- Do not bypass OAuth, manually copy tokens, or patch production data from local
  context.
- If `docs/live-readiness-validation.md` conflicts with deploy seeds about
  `zeler-app` scopes, prefer `docs/deploy.md` and
  `infra/mongo/seeds/module_registry.admin_clients.json`.

## SDD design

Use `sdd/zeler-platform-greenfield/design.md` for platform design work. Consult
the related artifacts below for the change or verification question at hand;
they are not mandatory reading for unrelated tasks.

Related local artifacts:

- `sdd/zeler-platform-greenfield/spec.md`
- `sdd/zeler-platform-greenfield/tasks.md`
- `sdd/zeler-platform-greenfield/verify-report*.md`
