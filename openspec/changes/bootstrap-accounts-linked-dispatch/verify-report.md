# Verification: account-link bootstrap dispatch

Date: 2026-09-25. Scope: local implementation and verification; production
rollout remains pending.

## Requirements and evidence

| Requirement | Evidence | Result |
| --- | --- | --- |
| Durable `accounts.linked` destination | Topology and registry contract tests; local RabbitMQ binding with mandatory gateway publication | Pass |
| One dispatch for a pending job | Real OAuth emitter, validated local Mongo, real RabbitMQ consumer, and fake Cloud Run client; duplicate delivery and relink checks | Pass |
| Bounded failure and dead letter | Consumer/dispatcher focused tests for retry, exhausted attempts, invalid messages, and lock release | Pass |
| Worker readiness | Local process smoke confirmed RabbitMQ/Mongo health and clean shutdown | Pass |
| Cloud Run argument contract | HTTP mock verifies `containerOverrides[].args` contains seller and job IDs | Pass |

## Checks

- `uv run pytest -q --disable-warnings` passed against a disposable local Mongo
  replica-set database; nine expected skips (eight protected stock-time tests
  requiring a different isolated configuration, one Caddy case with no keys).
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy .`
  passed.
- Schema export check, direct-Meli lint, shell syntax check, and
  `git diff --check` passed.
- The local OAuth-to-dispatch smoke used the checked-in Mongo job validator and
  verified one job claim and a released concurrency slot. The Cloud Run call
  was simulated; no production execution was started.

## Runtime gate

The dispatcher image has not been built or deployed. The job-level Cloud Run
permission, production binding/registry update, gateway image rollout, and
controlled seller execution still need explicit authorization and runtime
verification. A Cloud Run API timeout after server acceptance can leave the
outcome ambiguous; inspect the affected job and execution before manual replay.
