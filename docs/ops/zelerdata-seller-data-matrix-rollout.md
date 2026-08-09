# ZelerData Seller Data matrix rollout

This rollout covers the freshness-gated Seller Data domains added or repaired by
the matrix work: questions, item/shipping/catalog, returns/histories/withdrawals,
quality, calculator, and remaining Phase 4 read models. The read-model freshness
contract for these domains is explicit: they are
available only from local, seller-scoped read models. When a listed marker is
missing or stale, the corresponding freshness-gated formula must return
`DATA_UNAVAILABLE` instead of guessed values.

Pre-existing core/order formulas such as `ZELERDATA_ORDENES`,
`ZELERDATA_VENTASTOTALES`, and `ZELERDATA_DASHBOARD` still read local item/order
collections, but this checklist does not claim they are centrally
freshness-gated yet. Treat that as a separate hardening slice if the rollout
contract expands later.

## Quick path

1. Deploy the formula/runtime code and Mongo validators/indexes together.
2. From the approved VM/VPC/runtime context, validate `sheets_read_model_freshness`
   markers for each productive read model before announcing availability.
3. Run a small authenticated formula smoke with sanitized output; do not query or
   print production Mongo values from the local assistant environment.
4. For `PREGUNTAS`, `PREGUNTASKPI`, `DEVOLUCIONES`, `CATALOGO_COMPLETO`, and
   `CATALOGOBUYBOX`, use dry-run first and require explicit write authorization
   before publishing reconciliation markers.

## Missing-formula reconciliation chain

This rollout depends on the final chained PR sequence for
`zelerdata-missing-formula-read-models`:

| PR | Boundary |
|---|---|
| #107 | Foundation/safety: dry-run default, explicit write confirmation, sanitized output, and fail-closed marker semantics. |
| #109 | Questions/KPI: historical `questions` reconciliation for `PREGUNTAS` and `PREGUNTASKPI`. |
| #111 | Claims/returns: `claims` plus `orders` reconciliation for `DEVOLUCIONES`, with explicit `returned_quantity` only. |
| #114 | Catalog readiness: source/SLA contracts and marker publication for catalog product and buybox snapshots. |
| #115 | Catalog writes: product snapshots from `/products/{catalog_product_id}` and buybox snapshots from `/items/{item_id}/price_to_win?version=v2`. |
| Final docs/verification PR | Runtime-only runbook, sanitized smoke intent, rollback notes, and root quality-gate evidence. |

The chain strategy is stacked-to-main. Each PR should remain reviewable on its
own boundary; this rollout doc does not authorize production execution.

## Read-model freshness checklist

| Area | Required proof |
|---|---|
| Matrix item formulas | `item_formula_rows` marker covers the formula request time. |
| Matrix order/sales dependencies | `orders` marker covers the formula request time or requested `fecha_final`. |
| Shipment labels/costs | `shipments` marker covers the formula request time. |
| Return claims | `claims` marker covers requested `fecha_final`; `DEVOLUCIONES` also requires approved/reconciled `orders` scope and explicit `returned_quantity`. |
| Item status history | `item_status_states` marker covers the formula request time. |
| Questions | `questions` marker is historically `reconciled` through the requested range; event-only freshness does not unlock `PREGUNTAS` or `PREGUNTASKPI`. |
| Catalog product snapshots | `catalog_product_snapshots` marker covers the formula request time and is sourced from scoped item rows with `catalog_product_id` via `/products/{catalog_product_id}`. |
| Catalog buybox | `catalog_buybox_snapshots` marker covers the formula request time and is sourced from scoped item rows via `/items/{item_id}/price_to_win?version=v2`. |
| Stockout rows | `stockout_snapshots` marker covers the formula request time. |
| Stock time metrics | `stock_time_metrics` marker covers requested `fecha_final`. |
| Price history | `price_history_snapshots` marker covers the formula request time. |
| Catalog time metrics | `catalog_time_metrics` marker covers requested `fecha_final`. |
| Full withdrawals | `full_withdrawals` marker covers requested `fecha_final`. |

For formulas governed by this checklist, if a marker is missing, stale, failed,
or outside the requested range, the Formula API must return stable
`DATA_UNAVAILABLE`.

## Unwired read-model guidance

The status command reports all 17 read models, but the matrix gates only the
formulas wired to a marker. An unwired model is one whose marker no formula
consumes yet; treat its state as informative, not as an availability claim.

- Do not announce a domain as available until its formula is wired to the
  marker and passes the authenticated smoke.
- When an unwired model is missing, stale, or failed, no formula is blocked
  yet; leave the model fail-closed so the wiring slice inherits a clean state.
- After wiring, use the status report's `action_recommended` as the repair
  signal: `re_run_reconcile` for missing, stale, failed, or malformed markers;
  `await_lease` for a missing `questions` marker.
- Markers alone never make a formula live; formula readiness requires the
  wired gate to prove the requested seller scope.

Run the read-only status command from the approved runtime to inspect
per-seller markers: `python -m infra.operations.zelerdata_read_model_status
--seller-id <seller> --confirm-approved-runtime [--readiness]`.

## Rollback

Rollback is domain-safe and marker-first: stop active reconciliation runs, mark
the affected read-model freshness marker `stale` or `failed` from the approved
runtime, then rerun corrected reconciliation when ready. Do not delete persisted
read-model collections during rollback; preserving data allows investigation and
a later reconciliation replay. Formulas remain `DATA_UNAVAILABLE` until complete
`reconciled` markers exist for the requested scope.

## Smoke evidence

Use pilot seller `82453304` only as the known operational smoke seller. Smoke
notes may include the command shape, bounded seller/range description,
read-model names, marker states, and aggregate counters. They must not include
secrets, tokens, OAuth codes, cookies, connection strings, raw production env
values, raw Mongo documents, raw payloads, buyer/address PII, or raw production
data values.

## Safety boundaries

- No production Mongo validation from local assistant context.
- Production validation or repair must run only from the approved VM/VPC/runtime-container context.
- No formula-time MercadoLibre calls.
- Do not bypass OAuth or manually patch seller data.
- Keep rollout evidence sanitized: counts, marker states, and timestamps only.
