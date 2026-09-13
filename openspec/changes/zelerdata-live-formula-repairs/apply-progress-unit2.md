# Apply Progress: Unit 2 — Historical Interval Convergence

Status: complete for tasks 2.1–2.2; live deployment and spreadsheet verification remain with unit 5.

Mode: Strict TDD. Scope: existing checkout only, no commit/branch operations. This independent unit remains below the 400-line authored review budget; no PR strategy is attributed to the user.

## Implementation

- Catalog reads choose their recent acquired cut from valid current and retained proofs, preserving it when a historical acquisition replaces the top-level marker.
- Recovery advances through the earliest actual uncovered gap, stopping at the next proven interval or 90 days.
- Coverage checks use the injected read clock. Expired historical proofs remain useful; invalidated markers withdraw all proofs.
- Malformed proof dates no longer trigger a naive/aware datetime sorting exception.
- No freshness duration, persistence schema, or public formula argument changed.

## TDD Cycle Evidence

| Task | Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- | --- |
| 2.1 | 26 existing read-model tests passed | New test file: 4 failed, 4 passed before production edits; repeated first chunk, wrong gap, unstable midnight cut, malformed-date exception | Initial 8 new tests passed | Added expired live-tail and actual Mongo/worker convergence tests; both passed | Ruff formatting; 36 focused tests passed afterward |
| 2.2 | Same 26-test baseline | Same reproduced failures drove bounded planner changes | 526 tests passed in read-model/recovery/remaining-handler suite at its initial 8-case snapshot | Final 10 new cases include real Mongo queue/worker publication across four distinct requests | Ruff check passed; no behavioral refactor needed |

## Work Unit Evidence

| Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest modules/sheets/tests/test_catalog_recovery_gaps.py modules/sheets/tests/test_formula_read_models.py -q`: exit 0, 36 passed after formatting. |
| Broader controls | `uv run pytest modules/sheets/tests/test_catalog_recovery_gaps.py modules/sheets/tests/test_formula_read_models.py modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_formula_handlers_remaining_phase4.py -q`: exit 0, 526 passed at collection time before two final triangulation cases were added. Explicit isolated local Mongo was configured. |
| Runtime harness | `test_catalog_planner_and_worker_converge_with_persisted_interval_proofs`: exit 0 against verified PRIMARY at loopback port 27028; four distinct acquired order intervals completed, persisted proof union covered 365 days, no recovery remained. Dedicated random database removed afterward. Gateway source was controlled authoritative-empty data; this is integration evidence, not production certification. |
| Static checks | Ruff check and formatting passed for the new test file and affected repository file. |
| Rollback boundary | Revert only catalog planner/proof-sort hunks in `formulas/read_models.py` plus `test_catalog_recovery_gaps.py`; preserve concurrent SKU and other work. |

## Files

- `modules/sheets/src/zeler_sheets/formulas/read_models.py`: catalog coverage and interval helpers only.
- `modules/sheets/tests/test_catalog_recovery_gaps.py`: 10 regression/integration cases.

## Remaining Limitations

Production acquisition throughput and source completeness are not established by these tests. Post-deploy Sheets results and image provenance remain required. No code was committed or deployed by this unit.

The dedicated-Mongo test now follows the existing recovery fixture convention: explicitly skip when loopback port 27028 is unavailable, validate PRIMARY when present, and clean up only after a successful connection. All 10 new cases passed again after this portability correction.
