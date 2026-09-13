# Apply Progress: Unit 1

Mode: Strict TDD. Tasks 1.1–1.2 implemented in the selected checkout; no commit, build, deployment, or production mutation performed by this unit.

## TDD Cycle Evidence

| Behavior | Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- | --- |
| Missing question/sale values | 139 existing tests passed | Two changed-contract tests failed on empty strings | Both passed after normalization | Answered/no-header question, same-day zero, repeated misses | Focused suite passed |
| Inventory ambiguity | Same baseline | Conflicting-code vector returned final variation | Cell-local ambiguity passed | Equivalent codes, unique sibling, repeated pair, missing pair | Ruff formatting; suite passed |
| SKU absence and observed dates | Same baseline | Null normalization and SKU-less product test failed | Both passed after scoped fixes | Null/empty/zero/literal None, invalid dates, paused baseline, no date fallback | Suite passed |
| Non-sales exclusion | Above green state | Cancelled SKU-less/SKU product case and three no-sale scalar cases failed | Passed after cancelled/canceled and quantity checks | Positive sale remains excluded/counts today; quantity zero does not | Suite passed |

## Work Unit Evidence

All pytest invocations explicitly set `MONGO_URI` to the orchestrator-verified loopback replica set on port 27028, database `zeler_formula_repairs_test`; inherited targets were not used.

Focused command:

```sh
uv run pytest modules/sheets/tests/test_formula_handlers_core.py modules/sheets/tests/test_formula_handlers_orders_questions.py modules/sheets/tests/test_formula_read_models.py modules/sheets/tests/test_formula_sku_absence.py -o addopts= -q
```

Result: exit 0, **151 passed in 0.38s**. Ruff check and format-check on both handler files and three unit-owned test files passed. Full repository gates belong to final verification.

Runtime harness: dispatcher and existing HTTP harnesses are included in the focused suite; live spreadsheet recertification remains task 5.5 after authorized deployment. Local tests do not establish deployed behavior.

Rollback boundary: CODIGOML handler; PRODUCTOSINVENTA/PREGUNTAS/DIASDESDEULTIMAVENTA logic; only `normalize_sku` in shared `read_models.py`; corresponding tests. Preserve concurrent changes to other read-model methods.

## Clarified Semantics

`last_status_change_at` includes first paused observations in the existing producer. Valid values are rendered with `change_date_basis=observed_status_change`; no historical transition is inferred and no fallback date is fabricated. Design/spec/tasks were aligned with the orchestrator's confirmed interpretation. `NA` still represents absent or invalid dates.
