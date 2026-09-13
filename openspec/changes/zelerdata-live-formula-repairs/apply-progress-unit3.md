# Apply Progress: Unit 3 — Shipment Scope

Status: tasks 3.1–3.2 complete; production deployment and spreadsheet certification remain with unit 5.

Mode: Strict TDD. Selected checkout only; no commits or VCS administration. Unit boundary is shipment handler plus its tests, approximately 341 authored changed lines.

## Implementation

- ENVIOSMERCADOENVIOS proves its complete 30-day order interval before deriving shipment IDs. A recent seven-day marker is insufficient.
- A productive global shipment marker remains accepted. Otherwise only same-seller rows with a recent, non-future `formula_observed_at`, nonempty status, and owned order relation are usable.
- Missing shipment rows retain known order/item fields with four explicit `DATA_UNAVAILABLE` cells and explicit shipment-ID recovery. Unknown productive order linkage requests order-ID recovery separately; mixed gaps use existing additional recoveries.
- Proven empty order windows need no unrelated shipment marker. Cancelled/never-paid/no-shipping orders do not create irrecoverable label requests. Closed labels and requested status filters remain respected, including cancelled labels.
- No read-model helper, schema, TTL, public signature, or queue protocol changed.

## TDD Cycle Evidence

| Task | Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- | --- |
| 3.1 | 49 existing tests passed; explicit full-range order fixtures preserved the baseline | 9 new failing cases and 1 existing passing control before production edits | 58 passed after scoped reader/partial-result implementation | Added actual worker/Mongo recovery plus absent order-relation rejection; final 60 handler cases passed | Ruff formatting/imports and type annotations; rerun passed |
| 3.2 | Same 49-test baseline | Range bypass, missing global marker, hidden linkage, status-filter cases reproduced | Actual pending formula → worker acquisition → usable formula passed | Missing/expired/future/foreign/no-status/no-order observations, two filters, non-paid/no-shipping controls | Mypy and Ruff passed for both affected files |

## Work Unit Evidence

| Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py -q`: exit 0, 60 passed. |
| Integration harness | `test_envios_worker_recovers_owned_label_without_global_shipment_marker`: verified loopback port 27028 PRIMARY; initial four unavailable fields, owned relationship acquisition, then quantity 2 and `ready_to_ship`; no global shipment marker was written. Random database removed afterward. Dedicated Mongo absence skips explicitly in CI, following existing test convention. |
| Broader controls | Handler plus recovery suite: 488 passed, one expired-buybox assertion failed while another unit changed that test/worker concurrently. The running test had the old expectation of no item refresh. Current source expects refresh; focused rerun below passed. No unit-3 changes were made to buybox code or tests. |
| Affected rerun | `uv run pytest 'modules/sheets/tests/test_formula_recovery.py::test_buybox_explicit_item_recovery_is_owned_fresh_and_source_bound[expired]' modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py -q`: exit 0, 61 passed. |
| Static checks | `uv run mypy` for both affected files: no issues. Ruff check and format check passed. |
| Rollback boundary | `modules/sheets/src/zeler_sheets/formulas/handlers_item_shipping_catalog.py` shipment-related hunks and corresponding tests only. Preserve catalog/other concurrent work. |

## Remaining Verification

The parent must run final repository gates after concurrent units settle and repeat the actual spreadsheet scenario after an authorized image deployment. Controlled gateway acquisition with real Mongo is integration evidence, not production certification.
