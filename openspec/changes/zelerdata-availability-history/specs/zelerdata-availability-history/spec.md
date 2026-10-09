# ZelerData Availability History

## Requirements

### Change-only log

For each accepted item observation, the platform MUST append one
`sheets_item_availability_transitions` row per publication (or per variation
when the publication has variations) only when it has no earlier row or its
`available = status active and available_quantity > 0` differs from the latest
row. Repeated observations, retries and observations not newer than the latest
row MUST NOT add rows. An observation without a stock value MUST NOT add a row.

### Read-time metrics

`ZELERDATA_TIEMPOSTOCKACTIVO` MUST report, per row, the available hours, the
hours in the requested range and their percentage. `ZELERDATA_SEMANASCONSTOCK`
MUST report, per ISO week of the range, `Con stock` or `Sin stock` from the
state at the end of that week. Both MUST use the seller's time zone and MUST NOT
count time after now.

### No invented history

A row whose first observation is after the requested range start MUST show
`Sin histórico antes de <fecha hora>` (or `Sin histórico` when it has no row) and
MUST NOT present the current state as history. A week with no earlier
observation MUST show the same message; a week that has not started MUST show
`NA`.

### Freshness

Both formulas MUST answer `DATA_UNAVAILABLE` unless the observed-only
`item_status_states` marker certifies a read at now, and MUST NOT request formula
recovery for this history.
