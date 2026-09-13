# Apply Progress — Unit 4: Item-derived histories

Status: complete for tasks 4.1–4.2; independent verification and live deployment remain with the orchestrator. Strict TDD. No commits, builds, deployments, global freshness writes, or production database mutations were performed by this unit.

## Behavior

- Preserve productive global history guards and existing successful legacy reads.
- On unavailable guards, TIEMPOACTIVA and selected PRECIOHISTORICO resolve owned, recently acquired item sources using the existing item resolution path and source fingerprint/row-count proof. Missing source evidence requests the existing item recovery route.
- TIEMPOACTIVA additionally requires corresponding status and exact observation time; unavailable vector positions remain explicit. Paused publications retain `NA`. Future interval starts are rejected.
- PRECIOHISTORICO requires its newest price/status to match the acquired source. Unchanged prices deliberately retain their original historical timestamp; no new historical entry is invented. Unselected history still requires global authority.
- TIEMPOSINSTOCK binds each snapshot to an acquired item's quantity, stock state, status and observation time. Missing snapshots or expired membership produce a visible unavailable row and bounded item/inventory recovery. Future stockout starts are rejected.
- `resolve_item_history_sources` rechecks source evidence even when item-row global authority succeeds. It does not manufacture a global history proof.

## TDD Cycle Evidence

| Task | Safety net | RED | GREEN | Triangulation / refactor |
| --- | --- | --- | --- | --- |
| 4.1–4.2 scoped fallback | 124 pre-existing handler/read-model tests passed | New test file: 10 failures on valid acquired sources and explicit gaps | 10 new tests passed | Active/paused, unchanged price timestamp, stock mismatch and expired membership |
| 4.1–4.2 recovery route | Existing checks retained | 3 failures asserting stale source errors target `item_formula_rows` | Same 3 passed | Updated legacy error-routing expectations without relaxing productive guards |
| 4.1–4.2 interval integrity | Previous new tests passed | 2 failures on future active/stockout starts | Both passed | Wrong-owner and fingerprint rejection; Mongo writer/expiry integration; formatting/types verified |

## Work Unit Evidence

| Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest -q modules/sheets/tests/test_formula_item_history_recovery.py modules/sheets/tests/test_formula_handlers_remaining_phase4.py modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py modules/sheets/tests/test_formula_read_models.py` — exit 0, 143 passed |
| New regressions | `uv run pytest modules/sheets/tests/test_formula_item_history_recovery.py -ra` — exit 0, 19 passed, no skips |
| Runtime harness | `test_history_real_mongo_observation_writers_and_expiry` uses dedicated loopback Mongo port 27028, asserts writable PRIMARY, writes into a unique disposable database, invokes the real price/stock observation writers and all three formula dispatchers, then verifies expiry rejects the scope without global marker writes. Passed. The temporary database is removed afterward. This is not a live Sheets certification. |
| Static checks | Scoped Ruff passed. Mypy for read_models, both changed handlers and the new test file passed: 4 files, no issues. |
| Rollback boundary | Revert `resolve_item_history_sources` only in shared read_models; revert changes to handlers_remaining_phase4 and handlers_returns_histories_withdrawals; remove test_formula_item_history_recovery and restore only unit-4 expectation changes in the two legacy test files. Preserve other units' edits to read_models. |

## Delivery / limitations

The cohesive implementation and its source-integrity/runtime tests exceed 400 changed lines. Do not compress tests or code to satisfy a presentation budget. Review can separate the status fallback from stock/price fallback with the common source helper; no branch or PR strategy has been chosen or executed.

No claim is made that absent historical intervals have been recovered, or that production has this code. Worker acquisition throughput and live source availability remain operational verification concerns. The test harness proves real Mongo persistence and formula behavior; the orchestrator owns deployed-version and Google Sheets verification.
