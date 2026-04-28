# AGENTS.md

## Project identity

This repository is `zeler-platform`.

Do not treat `zeler-core` as the active project for this repo. References to
`zeler-core` are legacy/migration context only and must not be used as canonical
paths for new work.

## Skill registry

Skill registry lives at `/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md`.

## Project rules

- TDD strict: every non-trivial change starts with a failing test.
- Conventional commits only.
- No AI attribution in commits or pull requests.
- Never commit without being asked.
- Do not mutate `../zeler-core` artifacts from this repository unless the user explicitly asks for cross-repo migration/decommission work.
- Prefer local `sdd/zeler-platform-greenfield/` artifacts as the source of truth for platform design, specs, tasks, and verification notes.

## Stack summary

Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP.

- HTTP services/jobs target Cloud Run.
- Always-on AMQP consumers may run on GCE VMs with Docker.
- MongoDB targets are local Docker for development and the documented production MongoDB deployment path; older Atlas mentions in SDD/tasks may be historical or superseded.
- Secrets/crypto use GCP Secret Manager and KMS where applicable.

## Repo layout

- `gateway/` — FastAPI gateway, OAuth/proxy/webhook/internal token surfaces.
- `core/` — shared domain models, read-only repositories, events, and auth utilities.
- `modules/` — platform modules (`repricer`, `sheets`, `publicador`, `autoreply`, `fulldock`).
- `bootstrap/` — one-shot bootstrap jobs.
- `infra/` — MongoDB, RabbitMQ, Docker/GCE/GCP runbooks and deploy helpers.
- `tests/` — cross-package integration tests.

## SDD design

See `sdd/zeler-platform-greenfield/design.md`.

Related local artifacts:

- `sdd/zeler-platform-greenfield/spec.md`
- `sdd/zeler-platform-greenfield/tasks.md`
- `sdd/zeler-platform-greenfield/verify-report*.md`
