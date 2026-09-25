# Verification: account-link bootstrap dispatch

Date: 2026-09-25. Scope: local verification, first production rollout, rollback,
and the account-stage correction before runtime activation.

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

## First production rollout and rollback

- The verified dispatcher image was built at commit `6d8ad7641ad3663182265059566e202f7108db83`
  and started on `platform-vm`. Its RabbitMQ and Mongo readiness checks passed;
  the durable `accounts.linked` binding had one consumer.
- The verified gateway fix was deployed after the worker. A controlled recovery
  for the linked test seller published one event. The worker dispatched one
  Cloud Run execution with the expected seller and job arguments.
- The `zeler-bootstrap` execution failed in its first `accounts` stage. OAuth
  stores the seller ID as an integer, while that stage searched for a string and
  attempted an incomplete account upsert. The production Mongo validator
  rejected the attempted insert. The execution ended with `Completed=False`
  and `NonZeroExitCode` after its retries.
- The worker was stopped and removed. The prior gateway running digest,
  Compose file, secrets script, module registry routing keys, and job-level IAM
  were restored. The original services passed health/readiness and capacity
  checks without restarts or OOM. The durable queue and failed job were kept.
- Focused regression tests now cover integer and string account IDs and reject
  missing linked accounts without insertion. A disposable local Mongo replica
  set with the checked-in account validator confirmed that the corrected stage
  updates the integer account while preserving its token fields.

## Correction checks

- The complete `uv run pytest -q --disable-warnings --tb=short` suite passed
  against a disposable loopback Mongo replica-set database with direct
  connection; nine expected skips remained.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, and
  `git diff --check` passed after the correction.

## Remaining runtime gate

Runtime activation requires a new verified `zeler-bootstrap` Job image from the
authorized `main` commit, a separately authorized Job image rollout, and one
controlled retry of the test seller. Do not restore the dispatcher until the
Job image includes this fix.
Inspect the prior failed execution and job state before retrying; a Cloud Run
API timeout after server acceptance can make the outcome ambiguous.
