# Coverage and Returns Assessment

Scope: remaining task 5.1 verification. No executable changes, production calls, or data mutations were performed during this assessment. Task 5.1 remains open for source/live evidence.

## Executed Evidence

Each command used an explicit `MONGO_URI` pointing to the verified development replica set on loopback port 27028. Recovery fixtures independently create disposable databases on that port.

| Command (`uv run pytest`, followed by paths/options below) | Result |
| --- | --- |
| `modules/sheets/tests/test_devoluciones_reconciliation.py modules/sheets/tests/test_devoluciones_runner.py modules/sheets/tests/test_formula_handlers_quality_calculator.py modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py -o addopts= -q` | 296 passed, 1.32s |
| `modules/sheets/tests/test_devoluciones_operation_composition.py -o addopts= -q` | 12 passed, 0.31s |
| `modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py modules/sheets/tests/test_formula_handlers_remaining_phase4.py -k 'catalog or inventory_refresh_wait or expired_inventory or quality_projection_roundtrips' -o addopts= -q` | 185 passed, 367 deselected, 24.92s |
| `core/tests/test_devoluciones_readiness.py core/tests/test_devoluciones_runs.py -o addopts= -q` | 17 passed, 0.02s |

Total: **510 passing focused cases**, zero failures. No additional RED defect was reproduced; no further implementation is justified by these results alone.

The fixed-database transaction tests in `tests/integration/test_devoluciones_fencing_transactions.py` were intentionally left to the concurrently running root verification suite, avoiding cross-run interference. The root must record their actual result.

## Formula Assessment

| Formula | Verified local behavior | Remaining evidence |
| --- | --- | --- |
| CALIDAD | Valid score retained beside unavailable sibling; wrong identity, future and 15-minute-old acquisition rejected; expired enumeration remains visible; real Mongo projection validators pass | Live source availability and full-sweep timing |
| CATALOGO | Individual data survives missing sales windows; interval recovery and inventory recovery do not starve known records; historical percentages require actual observations | Recovered live windows and competition coverage |
| CATALOGOBUYBOX | Prior unit 5.1a separately proved preserved siblings, dependency refresh, ownership and lease fencing | Deployed worker and spreadsheet recertification |
| CATALOGO_COMPLETO | Current owned products retained independently of stale/missing siblings; unrelated products excluded; missing membership remains explicit | Actual product source gaps and current membership |
| OBTENER_CATALOGO | Same source guarantees with its three-column contract; complete empty inventory distinguished from incomplete data | Same live coverage evidence |
| PUBLICACIONESDESCUIDADAS | Actual paused/full/out-of-stock eligibility, observed pause basis, supplied withdrawal fields and verified inventory fallback | Live coverage and authoritative withdrawal data; absent fields remain legitimate `NA` |
| DEVOLUCIONES | Quantity and owner ambiguity fail closed; joint proof is revalidated; fingerprint drift blocks renewal; leases fence writes and concurrent root operations | Production source certification remains blocked; no guard bypass or fabricated quantity |

## Expiry Interpretation

Existing accelerated-clock tests include a 17-minute inventory sweep, ensuring completion does not restart cooldown, extend enumeration freshness, or schedule autonomous scans. Expired enumeration retains independently current rows with a visible warning. These tests prove truthful expiry handling, not sustainable acquisition throughput for the production inventory.

The orchestrator supplied a 03:16 runtime observation at inventory offset 440. One offset/time sample does not establish sweep throughput or completion duration. Compare acquisition start, per-batch cuts, final offset and first-batch expiry before considering scheduler changes; TTL has not been expanded.

The orchestrator also reported noncanonical historical returns blocking prewrite certification and a dry source issue. Those are supplied operational findings, not independently rechecked here. Local passing tests cannot turn that blocked live fixture into a successful repair.
