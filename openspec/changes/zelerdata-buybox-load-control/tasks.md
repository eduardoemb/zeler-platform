# Tasks: ZelerData Buybox Load Control

## Review workload forecast

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

The change is one cohesive worker/queue/reconciliation unit in the selected checkout. No PR is requested.

## Work units

- [x] 1.1 RED: extend `modules/sheets/tests/test_formula_recovery.py` for optional offers 404, overlapping and concurrent buybox admission, and guarded legacy reconciliation.
- [x] 1.2 GREEN: update `modules/sheets/src/zeler_sheets/formulas/recovery_worker.py`, `recovery.py`, and `recovery_reconcile.py` to satisfy those scenarios.
- [x] 1.3 Add the fixed-model operator CLI and a scoped runbook; verify dry-run behavior against isolated Mongo.
- [x] 1.4 Run focused tests and all repository quality gates; record runtime and rollback evidence in a verify report.

Focused test: `uv run pytest -q modules/sheets/tests/test_formula_recovery.py -k 'buybox or catalog_admission or catalog_intents or catalog_reconciliation'`.
Runtime harness: isolated Mongo on loopback port 27028 for queue transactions and CLI dry run.
Rollback boundary: only the Sheets API/worker images and guarded buybox job mutation; preserve old jobs and snapshots.
