# Feature: atomic-event-claim-lease

Workflow: ODD. The user explicitly chose direct ODD slices over SDD for this
contract change (2026-09-17), overriding the AGENTS.md SDD default.

## Goal

Make event duplicate suppression atomic so that two concurrent deliveries of the
same idempotency key cannot both run the external side effects. Measured defect
(task 2.1 of `zelerdata-pilot-reliable-sync`,
`modules/sheets/tests/test_consumer_broker_delivery.py::test_concurrent_duplicate_deliveries_do_not_double_apply`):
with production prefetch (10), two copies of one event in flight both pass
`is_duplicate` before either marks the key, producing two Google Sheets appends
with a single `processed_events` marker.

## Design (decided): D2 — claim/lease as a mutex in front of the completed marker

`processed_events` keeps meaning **completed**. A new, separate, short-lived
collection `processed_event_claims` is an exclusive lease per scoped key. That
keeps the DLQ reconciler (`infra/operations/sheets_dlq_reconcile.py` classifies
an active key as `already_applied` and closes it terminally), the runbooks and
the 48 h retention untouched. D1 (an `in_progress` state inside
`processed_events`) was rejected for that reason.

New primitive, additive and inert until adopted:
`core/src/zeler_platform_core/events/claims.py`.

```python
class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"      # this delivery owns the lease; run the side effects
    COMPLETED = "completed"  # a completed marker exists; skip the side effects
    TIMED_OUT = "timed_out"  # another owner holds the lease; retry later


class EventClaimStore:
    def __init__(self, claims, completed: IdempotencyStore, *,
                 lease: timedelta = timedelta(seconds=120),
                 wait: timedelta = timedelta(seconds=30),
                 poll: timedelta = timedelta(milliseconds=250),
                 now_fn=None) -> None: ...

    async def claim(self, key, *, module_id, consumer_id=None,
                    owner_token, lease=None, wait=None) -> ClaimOutcome: ...
    async def complete(self, key, *, module_id, consumer_id=None,
                       owner_token) -> bool: ...
    async def release(self, key, *, module_id, consumer_id=None,
                      owner_token) -> bool: ...
```

`_id` reuses the existing scoped rule
(`scoped_processed_event_id(key, scope_id)`, `scope_id = consumer_id or module_id`),
so claim identity follows exactly the marker identity.

### `claim` sequence (order matters)

1. `completed.is_duplicate(key, module_id=..., consumer_id=...)` -> if true,
   return `COMPLETED` (also covers the legacy unscoped document rules).
2. Atomic lease acquire: `find_one_and_update({"_id": scoped,
   "expires_at": {"$lte": now}}, {"$set": {idempotency_key, module_id,
   consumer_id, owner_token, claimed_at, expires_at = now + lease}},
   upsert=True, return_document=AFTER)`. A live lease does not match the filter,
   so the upsert collides on `_id` and raises `DuplicateKeyError` -> `BUSY`.
3. Re-check the completed marker. This closes the window where another owner
   completed between steps 1 and 2: if it now reports duplicate, release the own
   claim and return `COMPLETED`.
4. Return `CLAIMED`.

On `BUSY`, poll every `poll` until `wait` elapses, repeating the same sequence:
return `COMPLETED` or `CLAIMED` as soon as either is reachable, otherwise
`TIMED_OUT`. `BUSY` is never returned to callers. The loop also carries a
deterministic attempt budget (`max(1, ceil(wait / poll)) + 1`) so an injected
clock that never advances can still only return `TIMED_OUT`, never hang.

### `complete`

1. Ownership check **without** deleting:
   `find_one({"_id": scoped, "owner_token": owner_token})`. If it is `None` the
   lease was lost, so return `False` and write **no** marker. That fences a
   stalled owner out.
2. `completed.mark_processed(key, module_id=..., consumer_id=...)` while the
   claim document is still present, so any concurrent claimant collides on
   acquire and then observes the completed marker at the top of its loop.
3. Best-effort `delete_one({"_id": scoped, "owner_token": owner_token})` after
   the marker write, ignoring the result: a crash or failure here leaves the
   claim to the TTL index while the marker already suppresses duplicates.
4. Return the marker result (a colliding marker is still a success).

Do not reorder steps 2 and 3. The first implementation released the lease
before writing the marker; an independent verification showed that a concurrent
claimant could acquire inside that gap and re-run the side effects. Marker first
closes it.

Crash between 2 and 3 loses only the lease cleanup, so the redelivery is already
suppressed. There is no window in which a lost lease can write a completed
marker.

### `release`

`delete_one({"_id": scoped, "owner_token": owner_token})`; returns whether the
lease was still owned. Called when the handler fails so the broker retry can
re-acquire immediately instead of waiting for the lease to expire.

### Residual risk (explicit, not hidden)

Exactly-once against a non-transactional external writer (Google Sheets append)
is not achievable. Two things remain after the fix, and both are deliberate:

- A lease that genuinely expires while its owner is still running can still let a
  second owner acquire and run the side effects, and the previous owner can still
  write the marker when it finishes (the ownership fence checks the token, not
  the expiry, precisely so a real completion is not discarded). The lease (120 s)
  is two orders of magnitude above the observed handler duration, which removes
  the measured concurrent-duplicate window while keeping crash recovery fast.
- A worker that crashes after the external append but before the marker write
  still re-appends on redelivery. That is today's at-least-once boundary and is
  unchanged by this feature.

## Non-goals

- No change to `processed_events` schema, indexes, retention or reader semantics.
- No change to the DLQ reconciler's `already_applied` meaning.
- No new external side-effect idempotency (Google Sheets append stays as is).
- No gateway/bootstrap/publicador work: they do not use the shared store.

## Slices (each ≤400 authored lines, gate-green, TDD)

### S1 — core primitive and its infrastructure (additive, inert)

- `core/src/zeler_platform_core/events/claims.py` (new).
- `core/src/zeler_platform_core/events/__init__.py` (export).
- `core/tests/test_event_claims.py` (new): contract, atomic acquire under a real
  duplicate-key collision, expiry reclaim, owner fencing on `complete` and
  `release`, wait-then-claim, `TIMED_OUT`, legacy unscoped marker handling.
- `infra/mongo/schemas/processed_event_claims.json` (new) and
  `infra/mongo/indexes/processed_event_claims.json` (new, TTL on `expires_at`).
- `tests/test_mongo_schemas_placeholder.py` (add the new file to the expected,
  active, non-placeholder sets).

Allowed edit surfaces: the files listed above only.

### S2 — Sheets adoption

As built: the handler body is not duplicated. A `_ClaimHandle`/`_EventGate` pair
expresses the delivery gate; `_LegacyEventGate` wraps the injected idempotency
store (unchanged check-then-act semantics for existing doubles) and
`_EventClaimGate` wraps `EventClaimStore` with a fresh `owner_token` per
delivery and `consumer_id = "zeler.sheets.events"`. `SheetsEventHandler` selects
the legacy gate only when `event_claim_store is None`, and `run()` wires the real
store over `processed_event_claims` + `processed_events`. A new retryable
`EventClaimTimeoutError` is handled in `_handle_message` through the existing
retry-delay path with `DEFAULT_EVENT_CLAIM_RETRY_DELAY_MS = 1000`.

Hardening after independent verification: the marker cleanup is best-effort
against `PyMongoError`; a lost lease (`complete() -> False`) is visible through
`logger.warning("worker.event_claim.lost_lease", ...)` instead of a silent ack;
a failing `release()` can no longer mask the original exception; and
`EventClaimTimeoutError` is classified as `transient_timeout` in `_dlq_class`.

Allowed edit surfaces: `modules/sheets/src/zeler_sheets/consumer.py`,
`modules/sheets/tests/**`.

### S3 — Repricer and Autoreply adoption

As built: the generic gate lives in
`core/src/zeler_platform_core/events/claim_gate.py` (`ClaimHandle`, `EventGate`,
`LegacyEventGate`, `EventClaimGate`, `EventClaimTimeoutError`), the Sheets
consumer imports it under its existing private aliases, and Repricer and
Autoreply mirror the Sheets adoption: claim before any read, terminal outcomes
(`set_price`/`no_action`; `no_match`/`answered`) complete exactly once through a
lost-lease warning helper, Repricer's non-terminal `item_missing`/`rule_missing`
release so a redelivery can re-run, any exception releases without masking, each
consumer retries `EventClaimTimeoutError` through its retry-delay path before the
`RuntimeError` branch, and each `run()` wires the real store over
`processed_event_claims` + `processed_events` with a wiring test.

### S4 — Ops and documentation coherence

As built: `tests/operations/test_sheets_dlq_reconcile.py` proves a live claim
lease is never classified `already_applied` and that `processed_event_claims` is
not an authority in `EVIDENCE_ORDER`; `docs/ops/sheets-dlq-reconciliation.md`
states that rule for operators. No `docs/lessons/README.md` entry yet: the
document's own rule is to add it once the fix has production evidence.

Deploy prerequisite: `infra/mongo/indexes/processed_event_claims.json` and its
schema must be applied where the module runs, in the same separately authorized
rollout step used for any other schema/index change. Without the TTL index,
expired leases linger on disk; the reclaim filter still works because it compares
`expires_at`, but the cleanup does not.

## Verification per slice

- Focused `uv run pytest` for the touched tests, plus `uv run ruff check`,
  `uv run ruff format --check` and `uv run mypy` on touched files.
- S2 additionally runs the disposable-broker suite:
  `uv run pytest modules/sheets/tests/test_consumer_broker_delivery.py -o addopts=''`
  with RabbitMQ on `127.0.0.1:5673` and Mongo replica set on `127.0.0.1:27028`.

## Rollback

Each slice is additive. S1 rolls back by deleting the new module, tests and
infra files. S2/S3 roll back by removing the claim store argument, which restores
the previous check-then-act path; the claim collection then goes unused.

## Delivery shape

S1 measured 763 authored lines (`claims.py` 239, `test_event_claims.py` 553,
infra 25) and S2 measured ~720 whitespace-insensitive lines (`consumer.py` +170
real edits plus re-indentation, `test_consumer_broker_delivery.py` 525,
`test_sheets_run_entry.py` +25). Both are above the 400-line review guard.
Because each primitive and its proof are one cohesive unit, split each slice at
delivery time rather than separating the proof from the code:

- PR1: `claims.py`, the `__init__.py` export and the contract tests.
- PR2 (chained): `infra/mongo/{schemas,indexes}/processed_event_claims.json`,
  the schema inventory entry, and the concurrency/expiry/wait tests.
- PR3 (chained): the Sheets gate, the handler flow, the retry branch and
  `run()` wiring, with the unit suites it touches.
- PR4 (chained): the broker evidence file `test_consumer_broker_delivery.py`,
  which is the end-to-end assertion that PR3 is real.

## Task list

- [x] S1.1 Write the failing claim-store tests (real Mongo collision, expiry,
  fencing, wait). RED observed: `ModuleNotFoundError: No module named
  'zeler_platform_core.events.claims'`.
- [x] S1.2 Implement `EventClaimStore` to GREEN. `uv run pytest
  core/tests/test_event_claims.py -o addopts=''` -> 16 passed.
- [x] S1.3 Add the schema, the TTL index and the schema-inventory test entry;
  `uv run pytest tests/test_mongo_schemas_placeholder.py -o addopts=''` -> 1 passed.
- [x] S1.4 Independent verification found two defects and both are fixed: the
  release-before-marker window in `complete` (now marker-before-delete) and a
  poll loop that could hang on a frozen injected clock (now attempt-bounded).
  Focused re-run by the orchestrator: 27 passed
  (`test_event_claims.py` + `test_event_idempotency.py`), schema inventory passed;
  Ruff, format and mypy clean; `core/tests` suite 358 passed.
- [x] S2.1 Turn the concurrent-duplicate broker probe GREEN through the handler.
  RED baseline: `1 failed, 3 passed` with
  `AssertionError: concurrent duplicates must not double-append / assert 2 == 1`.
  GREEN: `4 passed`, stable in 10 consecutive runs after the probe's own two
  ordering waits were corrected (wait on the handler delivery, not the append;
  compare outcome multisets, because the marker lands before the first handler
  returns).
- [x] S2.2 Wire `run()` and guard it: `test_sheets_run_entry.py` now asserts the
  real `_EventClaimGate` and both collections, so dropping the wiring fails.
- [x] S2.3 Independent verification of the handler flow; the four limits it
  found are fixed (best-effort cleanup, lost-lease warning, non-masking release,
  `transient_timeout` classification) with RED->GREEN tests.
- [x] S3.1 Adopt the claim flow in Repricer and Autoreply with tests. S3a moved
  the gate to core and adopted it in Repricer (`core/tests/test_event_claim_gate.py`
  10 passed, `modules/repricer/tests` 115 passed); S3b adopted it in Autoreply and
  added Repricer lost-lease parity (`modules/autoreply/tests` 73 passed,
  `modules/repricer/tests` 117 passed).
- [x] S4.1 Prove DLQ reconciler semantics and record ops/docs evidence: claim
  leases are not application evidence
  (`tests/operations/test_sheets_dlq_reconcile.py` 62 passed) and the operator
  rule is in `docs/ops/sheets-dlq-reconciliation.md`.
- [x] S4.2 Record the result in the pilot change for task 2.1.

Final candidate evidence for the whole feature (S1-S4), against the final tree
with `MONGO_URI` on the disposable loopback replica set:

- Full repository suite: **5383 passed, 9 skipped, 0 failed, 0 errors** in 5m35s.
  The 9 skips are the documented protective `ZELER_RS0_TEST_URI` refusals plus one
  GCE contract skip.
- `uv run mypy .`: **Success, 604 source files, no issues.** The root mypy gate
  is green, not merely the touched files.
- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check`: exit 0.
- Module suites on the way: core event tests 37 passed, operations DLQ reconciler
  62 passed, Repricer 117 passed, Autoreply 73 passed, broker probe 4 passed.
