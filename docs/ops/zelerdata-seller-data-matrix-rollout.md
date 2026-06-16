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

## Read-model freshness checklist

| Area | Required proof |
|---|---|
| Matrix item formulas | `item_formula_rows` marker covers the formula request time. |
| Matrix order/sales dependencies | `orders` marker covers the formula request time or requested `fecha_final`. |
| Shipment labels/costs | `shipments` marker covers the formula request time. |
| Return claims | `claims` marker covers requested `fecha_final`; `DEVOLUCIONES` also requires `orders`. |
| Item status history | `item_status_states` marker covers the formula request time. |
| Questions | `questions` marker is `fresh` or `reconciled` through the requested range. |
| Catalog product snapshots | `catalog_product_snapshots` marker covers the formula request time. |
| Catalog buybox | `catalog_buybox_snapshots` marker covers the formula request time. |
| Stockout rows | `stockout_snapshots` marker covers the formula request time. |
| Stock time metrics | `stock_time_metrics` marker covers requested `fecha_final`. |
| Price history | `price_history_snapshots` marker covers the formula request time. |
| Catalog time metrics | `catalog_time_metrics` marker covers requested `fecha_final`. |
| Full withdrawals | `full_withdrawals` marker covers requested `fecha_final`. |

For formulas governed by this checklist, if a marker is missing, stale, failed,
or outside the requested range, the Formula API must return stable
`DATA_UNAVAILABLE`.

## Rollback

Rollback is domain-safe: disable the affected read-model marker or revert the
domain handler/runtime exposure so the formula returns `DATA_UNAVAILABLE` again.
Do not delete persisted read-model collections during rollback; preserving data
allows investigation and a later reconciliation replay.

## Safety boundaries

- No production Mongo validation from local assistant context.
- No formula-time MercadoLibre calls.
- Do not bypass OAuth or manually patch seller data.
- Keep rollout evidence sanitized: counts, marker states, and timestamps only.
