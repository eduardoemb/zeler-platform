# Apply Progress: Buybox Partial Recovery

Mode: Strict TDD. Task 5.1a completed; task 5.1's broader returns/coverage verification remains open. No production mutations or deployment occurred in this unit.

## TDD Cycle Evidence

| Task | Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- | --- |
| 5.1a | 66 buybox/catalog tests passed | Two mixed-batch Mongo tests returned zero snapshots, losing the valid sibling | Per-resource validation preserved two snapshots with recovered dependency, one with HTTP 503 | Wrong-owner detail and revoked-lease cases passed without unauthorized snapshots or attempt completion | Ruff formatting; all 70 focused tests passed |

## Work Unit Evidence

Command (with explicit isolated Mongo environment on loopback port 27028):

```sh
uv run pytest modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_formula_buybox_partial_recovery.py -k 'buybox or catalog_product_worker' -o addopts= -q
```

Result: exit 0, **70 passed, 363 deselected in 20.81s**. Ruff check and format-check passed for the worker and both test files.

Runtime harness: real isolated Mongo, production queue/worker/enrichment/persistence, separate discovery/detail fakes. Four cases verify available dependencies, HTTP 503, foreign-owner resources and lease revocation. Source fakes exercise permission separation; external production behavior remains pending deployment.

Rollback boundary: the per-resource buybox participation/freshness block in `recovery_worker.py`, its dedicated test file, and the existing expired-source test's new recovery expectation. No schema or persisted-format changes.

## Result Semantics

Whole-batch seller ownership preflight remains mandatory. A stale owned item is reacquired once under the existing job lease; its canonical source is revalidated before competition acquisition. Fresh nonparticipants fail locally. `_finish_catalog_batch` joins sibling writes and retains existing failure/retry classification. No source-wide freshness marker is fabricated and TTL remains unchanged.

Affected runtime image: Sheets worker. Existing API/other unit changes have independent image requirements. Live returns reconciliation and its noncanonical-source blocker were not modified.
