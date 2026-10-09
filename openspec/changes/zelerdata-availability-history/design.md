# Design: ZelerData Availability History

## Storage

`sheets_item_availability_transitions` is append-only. Each row has `seller_id`,
`item_id`, `variation_id` (null for a publication without variations), `sku`,
`available`, `status`, `available_quantity`, `observed_at`, `source` and
`schema_version`. `_id` is `<seller>:<item>:<variation or ->:<observed_at>`, so
retrying one observation hits the same key. One compound index
`(seller_id, item_id, variation_id, observed_at)` serves both the writer's
"latest row of this series" lookup and the reader's ordered scan.

## Variations

The legacy add-on kept one history per SKU. A SKU can be missing, ambiguous or
renamed, so a series is keyed by Mercado Libre's identity instead: the
publication, or each of its variations when it has any. A variation is
available when the publication is `active` and that variation's
`available_quantity` is above zero. The row carries the SKU seen at that change,
and the reader shows the newest one. A rename without an availability change
keeps showing the old SKU until the next change (accepted limitation).

## Writer

`record_availability_observation` runs right after `record_stockout_observation`
in `_refresh_item_read_models` (events) and `project_acquired_item_history`
(inventory sweep and item recovery). For each series it reads the latest row and
inserts one only when there is none or `available` changed. An observation not
newer than the latest row is ignored, so reordering never rewrites the past. A
duplicate `_id` is a retried observation and counts as already written. Two
concurrent observations can at worst leave one stale row that the next
observation corrects; precision is the observation cycle, not the minute.

## Reader

Both handlers first require the existing observed-only marker of
`item_status_states` to certify a read at "now" (the same heartbeat that gates
`TIEMPOACTIVA`). It proves the observation pipeline is alive; a change-only log
cannot prove that by itself because it is silent while nothing changes. A failed
gate raises `DATA_UNAVAILABLE` without recovery (the model is not recoverable).

Rows are the current publications in `items` (projected to title, permalink and
variation IDs), one per variation when present. The seller's transitions are
streamed once, keeping per series only the first observation, the state at the
start of the window, the changes inside it and the newest SKU.

The range runs from local midnight of `fecha_inicial` to local midnight after
`fecha_final` in `seller_timezone`, clipped to now.

- `TIEMPOSTOCKACTIVO`: hours available, hours in the range and the percentage,
  as numbers with two decimals. Covered only if the series' first row is at or
  before the range start; otherwise `TIEMPO ACTIVA` shows
  `Sin histórico antes de <fecha hora>` (or `Sin histórico`) and the rest `NA`.
- `SEMANASCONSTOCK`: one column per ISO week touched by the range, headed
  `<año ISO> - <semana>` as in the legacy add-on. A week shows the state at its
  end (clipped to the range end and now): `Con stock` or `Sin stock`. A week
  with no earlier row shows the coverage message; a week that has not started
  shows `NA`.

The scan reads every transition of the seller once per call. At production scale
(about 10³ to 10⁴ rows) that is cheap; a seller with millions of rows would need
a pre-aggregated opening state.

## Rollout

Apply the new validator and index (`infra/mongo/apply_validators.py`) before the
new `sheets-api` and `sheets-worker` images, so the first insert meets the
validator. Rollback: the previous images ignore the collection; keep it.
