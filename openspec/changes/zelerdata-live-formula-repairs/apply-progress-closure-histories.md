# Closure preparation: returns and source-gated histories

Task 7.4 discovery/verification preparation, September 14, 2026. Consumed
`/tmp/zeler-closure-status.json`: apply ready, repo-local OpenSpec, final verify
blocked by pending tasks. This executor shares the root's active attempt and
has not acquired or settled another attempt. Global tasks/artifacts and runtime
state were not modified. No executable defect has yet been established in this
scope; no implementation or new tests were added.

## Exact evidence already executed

The dedicated loopback Mongo at port 27028 answered `hello` with
`isWritablePrimary=true` and `setName=rs0` immediately before these commands.
Both commands explicitly override ambient MONGO_URI with that isolated target.

```bash
MONGO_URI='mongodb://127.0.0.1:27028/zeler_layered_test?replicaSet=rs0&directConnection=true' uv run pytest modules/sheets/tests/test_devoluciones_reconciliation.py modules/sheets/tests/test_devoluciones_operation_composition.py tests/test_devoluciones_guarded_regressions.py tests/integration/test_devoluciones_fencing_transactions.py modules/sheets/tests/test_source_gated_read_model_writers.py modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py modules/sheets/tests/test_formula_handlers_remaining_phase4.py -o addopts='' -q
```

**335 passed in 1.57s**, no skips. Output:
`/tmp/zeler-closure-histories-tests.log`.

```bash
MONGO_URI='mongodb://127.0.0.1:27028/zeler_layered_test?replicaSet=rs0&directConnection=true' uv run pytest tests/operations/test_zelerdata_read_model_reconcile.py tests/operations/test_devoluciones_classify_legacy_claims.py modules/sheets/tests/test_devoluciones_runner.py modules/sheets/tests/test_formula_item_history_recovery.py modules/sheets/tests/test_formula_recovery_history_projection.py -o addopts='' -q
```

**265 passed in 38.50s**, no skips. Output:
`/tmp/zeler-closure-histories-operations-tests.log`.

These 600 passing cases cover productive V2 returns, explicit positive quantity,
verified safe exclusions, ambiguous/missing source facts, source fingerprint
drift, stale lease owners, actual guarded publication and transaction fencing,
source-bound observed history recovery, complete/incomplete stock/catalog
intervals, withdrawal detail flattening and bounded output, and renewal of a
settled return proof. Controlled positives are not production observations.

Protected `test_stock_time_forward_*_rs0.py` checks are optional additional
runtime-operation validation if that forward engine becomes necessary. They
must run with MONGO_URI absent and an explicit loopback ZELER_RS0_TEST_URI; the
commands above do not exercise or claim those separate protected operations.

## Prepared read-only runtime inspection

Script: `/tmp/zeler-closure-historical-inspect.py`. Syntax checked and executed
successfully against an empty isolated test database via stdin. It uses only
reads, `plan_stock_time_metrics_reconcile`, and
`run_source_gated_read_model_import(..., dry_run=True)`.

Root should upload it to the approved VM and execute from the worker's `/app`
working directory, using stdin so the runtime `infra` package resolves:

```bash
sudo docker compose --file /opt/zeler-platform/docker-compose.yml \
  exec -T --workdir /app sheets-worker /app/.venv/bin/python - \
  < /tmp/zeler-closure-historical-inspect.py
```

It outputs only aggregate counts, dates, bounded classifications and booleans:

- Claims classified by productive/basis state and membership in the original
  range; seller-wide guard blockers; candidate positive days without source IDs.
- Marker range/validity, live operation presence, completed run corresponding to
  the marker, settled range certification/readback counts, observed renewal
  preconditions and refresh configuration boolean.
- Recent completed run ranges, without run IDs or fingerprints.
- Source inventory/coverage/basis/planned counts and current target counts for
  stock-time, catalog-time and withdrawal histories.

This is a read-only prerequisite snapshot, not a mutation or standalone
certification. The inspection never calls marker renewal or run advancement.
An eligible boolean does not prove the scheduler is actually running: root must
also observe runtime component health and successive marker renewals.

## Original-range operations and guard boundaries

Keep Sheet B3/B4 at August 15–September 11. Their closed UTC interpretation is
`[2026-08-15T00:00Z, 2026-09-12T00:00Z)`. CLI date-to is inclusive; direct
source-gated planner arguments are already half-open. Do not substitute a
recent fixture date for the original case. If a verified positive exists on
another day, add its evidence as a supplementary control with its own date.

Read-only claims classifier, from the same approved container context:

```bash
/app/.venv/bin/python -m infra.operations.devoluciones_classify_legacy_claims \
  --seller-id 82453304 --date-from 2026-08-15 --date-to 2026-09-11 \
  --confirm-approved-runtime
```

Claims-first remote-source acquisition dry-run for the original case:

```bash
/app/.venv/bin/python -m infra.operations.zelerdata_read_model_reconcile \
  --seller-id 82453304 --date-from 2026-08-15 --date-to 2026-09-11 \
  --read-model devoluciones --dry-run --confirm-approved-runtime \
  --emit-phase2-contract
```

Large dry-run ranges use sequential ten-day slices with shared source accounting;
choose an outer command timeout that accommodates that implementation. Do not
replace the focused mode with `--read-model all`, broad order hydration, or an
unpaced manual source loop. Source attempts and failure categories remain
bounded/sanitized by the existing operation.

A successful guarded write, if root's current authorization and fresh source
proof support that exact seller/range, uses the same command with
`--write --confirm-production-write` replacing `--dry-run`. It owns the existing
lease, persists the snapshot, revalidates source fingerprint/age, and publishes
through the joint guard. It is not a read-only operation and was not run here.

The previous recorded result was a current-range positive fixture, 1/1/1, blocked
from publication by eleven older unclassified `returns` rows. Revalidate that
finding before acting. `_reject_historical_non_productive_devoluciones_rows`
is intentionally seller-wide and its regressions explicitly preserve older
rows. There is no existing command authorizing deletion, manual productive
flags, or bypass of that guard. If authoritative old sources remain inaccessible,
the current positive return is a blocked recovery, not legitimate absence.
Historical remediation must use authoritative source re-acquisition; otherwise
return the concrete contract/source blocker to root before proposing code.

## Renewal needed for ninety-minute closure

DEVOLUCIONES has a 30-minute joint marker lease. One focused write cannot by
itself prove stable 90-minute availability. The existing refresh runner renews
only a marker associated with a completed quota run whose contiguous windows,
range and readback still satisfy certification. Observe the run range enclosing
the original formula, renewal eligibility, refresh component readiness and
actual renewals during warm-up. `timer_active` from the older timer-status helper
is campaign acceptance evidence, not proof of current renewal or range coverage.

If no suitable completed run exists, the existing quota authorization/advancement
workflow must be concretely scoped by root using the documented authorization,
cohort, half-open range and release fingerprints. Do not create a run, edit its
state/authority file, or activate a timer from this inspection. Complete needed
operational work before starting the 90-minute no-deployment observation window.

## Distinguishing correct absence from broken recovery

| Observed condition | Classification and next step |
| --- | --- |
| Complete authoritative inventory has no relevant returns, or returns are excluded by the tested strict V2 absence rules | Proven empty result only after a valid enclosing joint proof; record source coverage and exclusion counts. |
| Current-range positive source exists but local rows/marker are missing, stale or blocked by historical guard | Actual unresolved recovery; cannot certify as absence. Retain failure reason and repair through the existing guarded path. |
| Broker/auth/rate-limit/transport error prevents source inventory | Inconclusive acquisition, not historical absence. Fix the dependency or retry within existing controls before classifying. |
| Historical source has no baseline at/before the interval start, or events start later | Uncovered interval; retain explicit DATA_UNAVAILABLE and pair with controlled complete-history positive tests. Never extend the first observed state backward. |
| A complete source history exists but target metrics are absent/stale | Recoverable projection gap, not legitimate absence; prepare a source-authorized writer operation. |
| Target history/withdrawal collection is empty | Insufficient evidence by itself. Inspect canonical source inventory and coverage; do not report zero historical activity merely from zero target rows. |

TIEMPOSTOCKACTIVO and SEMANASCONSTOCK require stock interval coverage;
CATALOGOTIEMPO requires catalog state history; RETIROS requires actual withdrawal
records. Current catalog snapshots, observed stockout baselines, and current
status/price snapshots cannot manufacture those full intervals or withdrawals.
The existing source-gated routines may inspect current platform collections
named `item_history_projection`, `meli_item_events` and `withdrawal_records`;
this does not authorize accessing a legacy database or importing legacy data.
The stock-time CLI is dry-run-only and rejects `--write`, even with confirmation
flags. Do not improvise a write by calling its private functions directly.

## Completion accounting

This preparation provides local positive/negative and guard evidence for task
7.4 and applicable 5.1 checks. Production outputs from the prepared script,
remote source dry-runs, any necessary guarded operation and 35-case readback are
still required before root can close 7.4/5.2. No full-change SDD pass is claimed.
Rollback boundary: only this new preparation note and the temporary read-only
inspection script; no product implementation or production state changed.

## Fresh runtime findings supplied by root

Root ran the read-only script at 19:40:22 UTC. Output is retained in
`/tmp/zeler-closure-historical-proof.json`:

- Eleven unclassified historical return claims remain outside the original
  August 15–September 11 interval. One locally canonical positive exists on
  August 15. This is a real current-range recovery obligation, not empty data.
- The only completed quota run covers June 1–June 11 exclusive, with five
  expected/persisted/complete claims and zero missing. Its existing marker is
  stale and does not cover the original case. Renewal preconditions for that
  June range pass, but refresh is disabled. Enabling renewal alone cannot widen
  the proof to August–September.
- All three historical source inventories and planned/target row counts are
  zero; coverage is false and basis observed_only. Stock planning returns
  source_history_incomplete. These prove an uncovered source interval, not zero
  business activity; pair explicit unavailability with the controlled positives.

Prepared `/tmp/zeler-closure-returns-source-plan.py` groups the guard-blocking
claim IDs privately in memory into exact verified UTC days. It emits only day
bounds, counts and existing focused dry-run arguments, retaining the original
Sheet date range. Run it by stdin in the worker, then run its source dry-runs
sequentially after gateway readiness is restored. No remote source acquisition
or production write was performed by this executor.

Refresh audit found that changing the whole loop from 900 to 60 seconds would
also replan six models and create moving one-hour order/question windows each
minute. At startup after the daily threshold, daily seven-day and (on Monday)
weekly ninety-day work is also due. Return advancement requires its own flag
and an existing authorized run; renewal runs even with advancement disabled.
DLQ archival and precalculated warming have separate enable flags. A faster
inventory heartbeat therefore needs separation from the existing broad cadence
within the same supervisor, not an unqualified interval override.
