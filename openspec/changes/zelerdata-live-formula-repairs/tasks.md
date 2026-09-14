# Tasks: ZelerData Live Formula Repairs

## Review Workload Forecast

Estimated changed lines: 700–1200 across five independently reviewable units.
Delivery strategy: ask-on-risk.
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Repository/user instructions authorize implementation in the selected checkout without unnecessary VCS decisions. Execute bounded units; no chain strategy or size exception is attributed to the user. Subsequent user authorization covers commits and push to selected main, builds and scoped deployments as recorded in `docs/zelerdata-live-formula-repairs.md`. PR and branch operations remain unrequested. Subdivide any oversized unit before implementation.

### Work Units

Commands run from repository root. Each command is run RED before implementation, then GREEN afterward.

| Unit | Focused command | Runtime harness | Rollback boundary |
| --- | --- | --- | --- |
| 1 Outputs/codes | `uv run pytest modules/sheets/tests/test_formula_handlers_core.py modules/sheets/tests/test_formula_handlers_orders_questions.py modules/sheets/tests/test_formula_read_models.py` | Five changed formulas, mixed vectors | Rendering/identity changes |
| 2 Intervals | `uv run pytest modules/sheets/tests/test_formula_read_models.py modules/sheets/tests/test_formula_recovery.py` | Successive catalog history chunks | Gap planner |
| 3 Shipments | `uv run pytest modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py modules/sheets/tests/test_formula_recovery.py` | ENVIOS pending→usable | Shipment scoped reader |
| 4 Item histories | `uv run pytest modules/sheets/tests/test_formula_handlers_remaining_phase4.py modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py modules/sheets/tests/test_formula_read_models.py` | Three histories after recovery/expiry | Resource fallbacks |
| 5 Operations/coverage | `uv run pytest modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_formula_handlers_quality_calculator.py` | Returns fixture and catalog/quality sweep | Scoped image rollback; preserve valid observations |

## 1. Output correctness

- [x] 1.1 RED: extend unit-1 tests for absent answers/sales, zero, SKU-less sold/unsold items, transition versus first-paused-observation dates, ambiguity/repeated vectors, and equivalent codes.
- [x] 1.2 GREEN: update `modules/sheets/src/zeler_sheets/formulas/handlers_orders_questions.py`, `modules/sheets/src/zeler_sheets/formulas/handlers_core.py`, and `modules/sheets/src/zeler_sheets/formulas/read_models.py`; document observed-change dates without historical inference. Run unit 1.

## 2. Historical interval convergence

- [x] 2.1 RED: extend unit-2 tests for successive 365-day coverage, overlaps, true gaps, invalid proofs, and stable acquisition keys.
- [x] 2.2 GREEN: repair `modules/sheets/src/zeler_sheets/formulas/read_models.py` gap selection without weakening proofs. Run unit 2.

## 3. Shipment scope

- [x] 3.1 RED: extend unit-3 tests for complete order windows, expired global/current owned shipment evidence, wrong ownership, missing IDs, and closed/cancelled filtering.
- [x] 3.2 GREEN: update `modules/sheets/src/zeler_sheets/formulas/handlers_item_shipping_catalog.py` and scoped reads in `modules/sheets/src/zeler_sheets/formulas/read_models.py`. Run unit 3.

## 4. Item-derived histories

- [x] 4.1 RED: extend unit-4 tests for source/state mismatches, stale→acquired→usable, incomplete membership, and no fabricated intervals.
- [x] 4.2 GREEN: update `modules/sheets/src/zeler_sheets/formulas/read_models.py`, `modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py`, and `modules/sheets/src/zeler_sheets/formulas/handlers_returns_histories_withdrawals.py`. Run unit 4.
- [x] 4.3 Live RED/GREEN: connect real worker acquisition to existing guarded history writers before formula projection; exercise actual worker and readers against Mongo. See `apply-progress-unit4-live.md`.

## 5. Operational verification

- [ ] 5.1 RED/GREEN: verify returns lease/fingerprint rejection and successful reconciliation; measure catalog/quality sweep expiry before any scheduler repair, preserving available siblings.
- [x] 5.1a RED/GREEN: fix per-resource buybox acquisition in `modules/sheets/src/zeler_sheets/formulas/recovery_worker.py`; verify available, transient, foreign-owner and lost-lease dependencies in `modules/sheets/tests/test_formula_buybox_partial_recovery.py`.
- [ ] 5.2 Use `infra/operations/zelerdata_read_model_reconcile.py` (read-only) through approved runtime context for bounded returns reconciliation; record evidence in `docs/zelerdata-live-formula-repairs.md`.
- [x] 5.3 Run all four repository gates against verified isolated Mongo; report pre-existing failures separately. Refactor only with affected checks rerun. Evidence: 4539 passed/9 skipped, protected Mongo 8 passed separately, Ruff check/format and mypy 532 files pass.
- [ ] 5.4 Prepare exact-main image provenance, rollback and scoped deployment; obtain missing commit authorization only after concrete changes/checks.
- [ ] 5.5 Repeat 24 primary/11 supplemental Sheet cases with profile 19; update 15 diagnoses with initial/recovered/expired results, sources, deployed identity, and unresolved positive-fixture gaps. Run independent SDD verification.
- [x] 5.5a September 14: execute/read all 35 original Sheet cases, update/read back 24 diagnosis rows, compare source values, and prove the selected history expiry/recovery cycle. Evidence: `docs/sheets/zelerdata-live-retest-20260914.md`. Partial inventory/catalog coverage and unavailable positive fixtures remain explicit; this does not close 5.5 or independent final verification.


## 6. Layered recovery (approved September 14)

Delivery: bounded implementation units in the selected checkout. Prior user
authorization for commits/push to selected main, builds and scoped deployment is
recorded in docs/zelerdata-live-formula-repairs.md and remains valid. No branch
or worktree operation is needed. Preserve unrelated untracked user work.

- [x] 6.1 RED/GREEN: basic acquisition, enrichment integrity, scoped projection reads.
- [x] 6.2 RED/GREEN: fair shared pacing and HTTP deadlines excluding quota waits.
- [x] 6.2a Live correction: sustain competing lanes across every inventory batch and prevent fixed-window bursts while preserving 180 requests/minute. Isolated final suite: 4609 passed/9 skipped, protected Mongo: 8 passed; Ruff check/format and mypy 541 files passed. Independent pacing/caller/lifecycle: 41 passed. Worker runtime verification remains in 6.6.
- [x] 6.3 RED/GREEN: claim lanes, leases, quota deferral and supervised lifecycle.
- [x] 6.4 RED/GREEN: admission/reserved slot and independent formula recovery intents.
- [x] 6.5 Accelerated 1900-item workload, all isolated-Mongo gates, independent local implementation verification. Final suite:4606 passed/9 skipped; protected Mongo:8 passed; Ruff/mypy541 passed. Full runtime/change verification remains in6.6.
- [ ] 6.6 Exact-source worker/API delivery, two live inventory cycles and 35-case retest.
- [ ] 6.7 Live full-inventory read correction: preserve source-bound snapshot checks while avoiding repeated full-source transfers/fingerprints within catalog resolution; omit unusable historical-sales reads and bound covered windows. Strict RED/GREEN, independent scoped review, all repository gates and affected image/UI verification.

## 7. Full closure approved September 14

Delivery decision: existing selected-main work-unit commits, no PR/branch/worktree
administration. This explicit user/repository workflow takes precedence over
the skill's generic chained-PR requirement. Split gateway lifecycle, formula
corrections and evidence into independently reviewable behavior units; keep
regressions with each implementation. Do not compress code to meet a line limit.

- [x] 7.1 RED/GREEN gateway readiness connection reuse, concurrent creation, reconnect/cancellation/shutdown and recovery after initial failure. Inspect Sheets probe cleanup; fix only reproduced defects.
- [x] 7.2 Independent gateway verification, root gates, exact-source gateway build/deploy, broker readiness and connection-count stability; establish exact AMQP rejection cause with sanitized evidence.
- [ ] 7.3 Full-size 35-way formula reproduction/profile; bounded fixes and regression evidence for persistent processing and inventory expiry.
- [ ] 7.4 Returns/historical completion through existing guarded operations, including positive/negative combined evidence and no invented coverage; close applicable 5.1/5.2 obligations.
- [ ] 7.5 Final repository gates, independent local verification, exact-source affected image delivery and warm-up.
- [ ] 7.6 Three simultaneous 35-case rounds and 90 continuous production minutes satisfying the closure specification; update/read back all 24 diagnoses and complete evidence matrix.
- [ ] 7.7 Independent final SDD verification, reconciled task evidence, archive only after accepted verification, and runtime/main image comparison.

### 7.4a May 14 UTC membership correction

- [x] RED: reproduce complete search inventory 4 / in-range readback 3, exact UTC
  start/end, invalid/missing/contradictory hydrated timestamps, retained inventory
  identity/fingerprint and final source-membership drift.
- [x] GREEN: classify only proven hydrated outside-window candidates, retain full
  source and exclusion evidence, report the bounded counter, and preserve all
  existing acquisition, write, historical-guard and publication contracts.
- [x] Verify focused source/reconcile regressions and real isolated Mongo
  readback; parent runs full gates and reviews exact affected release separately.

## 9. Concurrent item read acquisition correction

- [x] 9.1 Prove realistic concurrent 1900-item/19 MB reads repeat acquisition;
  implement application-owned sharing only while identical reads are in flight.
- [x] 9.2 Verify per-request freshness/full receipts, seller/database/key isolation,
  mutable result isolation, cancellation/failure/shutdown cleanup and fresh reads
  after completion; run focused checks and independent review.
- [ ] 9.3 Run full gates and authorized runtime recertification under whole-sheet
  load; retain all existing freshness, deadline and 90-minute acceptance criteria.

### 7.4b Truthful chunked return readback

- [x] RED/GREEN: prove real missing/complete/unknown per-window Mongo readbacks,
  reject expected-identity overlap, and preserve exact physical-attempt counters
  and bounded outside-membership evidence in large dry-run ranges.

## 10. Economic enrichment tag-order correction

- [x] 10.1 Reproduce old persisted hash invalidation on tag reorder; share canonical tag-set matching across base backfill, incoming events and listing fee bases. Preserve old observations; reject real basis changes and malformed tags. Focused local regressions pass.
- [ ] 10.2 Independently review the localized correction and run final repository gates; runtime verification requires the separately authorized affected worker/API images. Do not claim existing expired observations have become fresh.

## 12. Preserve projections after partial acquisition failure

- [x] 12.1 Strict RED/GREEN: two joined sub-batches persist valid sources; one raises an ordinary exception. Project persisted sources under existing lease checks before propagating the failure, without cursor success. Cover lost lease, cancellation and projection-error chaining.
- [ ] 12.2 Independent review and final repository gates; verify affected worker behavior after separately authorized delivery. No live causality claim from the local reproduction.
