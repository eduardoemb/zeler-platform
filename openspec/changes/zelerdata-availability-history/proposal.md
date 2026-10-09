# Proposal: ZelerData Availability History

## Intent

`ZELERDATA_TIEMPOSTOCKACTIVO` and `ZELERDATA_SEMANASCONSTOCK` answer
`DATA_UNAVAILABLE` because `sheets_stock_time_metrics` is empty and its legacy
sources do not exist in production. Accumulate a platform-owned availability log
from now on and compute both formulas from it at read time, as the legacy
SheetSeller endpoints did (`/publications/tiempodisponible`, `/publications/weeks`).
Plan: `docs/sheets/zelerdata-time-metrics-plan.md`, section 3.

## Scope

- New append-only collection `sheets_item_availability_transitions`: one row per
  publication or variation each time `available = status active and stock > 0`
  changes. Core model, exported validator and indexes.
- The writer runs where every accepted item observation already records its
  stockout snapshot (`event_persistence.py`: events, inventory sweep and item
  recovery). Idempotent under retries and repeated observations.
- Both handlers read the log instead of `sheets_stock_time_metrics`, in the
  seller's time zone, clipped to now. No precalculation and no reconciled marker.
- A range that starts before a series' first row shows
  `Sin histórico antes de <fecha hora>` instead of an invented value; current state is
  never presented as history (decision of 2026-09-24).

## Boundaries

Out of scope: `CATALOGOTIEMPO`, the winning-time column of `CATALOGO` and
`RETIROS` (another session), the stock-time forward machinery (plan section 2),
and any build, deployment or production change. Formula names, signatures and
visible headers stay; `sheets_stock_time_metrics` and its importer stay untouched.
