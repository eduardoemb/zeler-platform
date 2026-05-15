# AGENTS.md

## Project identity

This repository is `zeler-platform`.

Do not treat `zeler-core` as the active project for this repo. References to
`zeler-core` are legacy/migration context only and must not be used as canonical
paths for new work.

`zeler-platform` is the canonical backend/platform for the Zeler products. It
works together with the existing frontend repository `zeler-app` at
`/Users/eduardoramirez/Documents/repositorios/zeler-app`; do not create a new
frontend when product UI work is requested unless the user explicitly asks for
one.

## Skill registry

Skill registry lives at `/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md`.

## Project rules

- TDD strict: every non-trivial change starts with a failing test.
- Conventional commits only.
- No AI attribution in commits or pull requests.
- Never commit without being asked.
- Never print secrets, tokens, connection strings, OAuth codes, cookies, or raw
  production environment values.
- Never run local Docker builds. Use Cloud Build for production images only when
  the user explicitly authorizes build/deploy work.
- Do not mutate `../zeler-core` artifacts from this repository unless the user explicitly asks for cross-repo migration/decommission work.
- Prefer local `sdd/zeler-platform-greenfield/` artifacts as the source of truth for platform design, specs, tasks, and verification notes.
- For substantial product changes, use SDD (`/sdd-new`, `/sdd-ff`, `/sdd-apply`,
  `/sdd-verify`, `/sdd-archive`) instead of ad-hoc implementation.

## Stack summary

Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP.

- HTTP services/jobs target Cloud Run.
- Always-on AMQP consumers may run on GCE VMs with Docker.
- MongoDB targets are local Docker for development and the documented production MongoDB deployment path; older Atlas mentions in SDD/tasks may be historical or superseded.
- Secrets/crypto use GCP Secret Manager and KMS where applicable.

Production currently runs in GCP project `zeler-platform-dev`, VM
`platform-vm`, zone `us-central1-a`, with Docker Compose-managed services and
Artifact Registry images. Production Mongo must not be queried from the local
assistant environment; validate or repair production Mongo only from the
approved VM/VPC/runtime-container context, using sanitized output and without
printing `MONGO_URI` or credentials.

The team also operates the connected production surfaces through available CLI
access where configured: GCP, Vercel, GitHub, and related tooling. Use those
tools carefully and prefer narrowly scoped deploys/restarts over broad changes.

## Repo layout

- `gateway/` — FastAPI gateway, OAuth/proxy/webhook/internal token surfaces.
- `core/` — shared domain models, read-only repositories, events, and auth utilities.
- `modules/` — platform modules (`repricer`, `sheets`, `publicador`, `autoreply`, `fulldock`).
- `bootstrap/` — one-shot bootstrap jobs.
- `infra/` — MongoDB, RabbitMQ, Docker/GCE/GCP runbooks and deploy helpers.
- `tests/` — cross-package integration tests.

## Connected repositories and product parity

`zeler-app` is the active web UI for the platform. Product UI work should adapt
screens into that existing app and use the platform module-admin token flow,
linked seller context, and live API URLs. Current live app deployment is hosted
at `https://app.zeler.ai`.

Product parity work is being planned product by product from legacy repositories.
Treat those repos as functional references, not as runtime dependencies or
canonical infrastructure:

- `../sheetsellerappindividual` — legacy SheetSeller product. The add-on under
  `addon/` is the reference for Google Workspace / Google Sheets formula
  behavior. Old Mongo/GCP services are historical.
- `../repricer-meli` — legacy EasyReprice/Repricer product. Use the Next/FastAPI
  implementation as the main product reference; old React/Flask surfaces are
  historical unless explicitly requested. Amazon and deprecated automatic
  non-catalog repricing are out of the current parity scope unless the user
  reopens them.
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

## Live integration notes

- Pilot seller used for operational smoke tests: `82453304`.
- Existing `zeler-app` route surfaces include `/accounts`, `/bootstrap/[jobId]`,
  `/repricer/rules`, `/sheets/config`, `/publicador/drafts`,
  `/autoreply/templates`, and `/fulldock/rules`.
- `zeler-app` uses a server-side broker secret and gateway token broker flow for
  module-admin JWTs. Never expose broker secrets as `NEXT_PUBLIC_*`.
- `module_registry._id = "zeler-app"` must remain enabled/scoped for the seller
  and module admin scopes when live UI calls module APIs.
- For authenticated UI smoke, use a real `app.zeler.ai` session and a legitimately
  linked MercadoLibre seller; do not bypass OAuth or copy/reassign tokens by hand.

## SDD design

See `sdd/zeler-platform-greenfield/design.md`.

Related local artifacts:

- `sdd/zeler-platform-greenfield/spec.md`
- `sdd/zeler-platform-greenfield/tasks.md`
- `sdd/zeler-platform-greenfield/verify-report*.md`
