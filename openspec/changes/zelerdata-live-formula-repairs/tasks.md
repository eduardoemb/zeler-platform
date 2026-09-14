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
