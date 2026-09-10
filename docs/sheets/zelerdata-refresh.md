# ZelerData scheduled refresh

The scheduled refresh keeps ZelerData read models productive without waiting for
a user to recalculate a formula. It never calls Mercado Libre on the formula
path: it plans bounded recovery work onto the existing durable queue, and the
Sheets recovery worker performs the acquisition and publishes the freshness
marker.

This is the first of the four agreed deliveries, in this order:

1. Scheduled refresh (this document)
2. Precalculated heavy formulas
3. Devoluciones reconciliation
4. Alerts and cleanup

## How it works

`zeler_sheets.formulas.refresh` holds the whole cycle:

- `ZelerDataRefreshPlanner` turns one seller and one mode into bounded
  `RecoveryRequest`s. It never acquires data.
- `MongoSellerExplorer` reads the refreshable sellers from `meli_accounts`.
- `ZelerDataRefreshSupervisor` runs a cycle on an interval and survives a single
  seller or model failure without stopping the loop.
- `reconciled_marker` builds the freshness marker, so the two-cycle validity is
  defined in one place.

`zeler_sheets.formulas.pacing` reserves part of the gateway budget so background
acquisition cannot starve interactive formula queries.

## Refresh modes

| Mode | Window | Cadence |
| --- | --- | --- |
| `fast` | 1 hour | every interval (default 15 minutes) |
| `daily` | 7 days | once per day, at or after `03:00` UTC |
| `full` | 90 days | once per week, on Monday at or after `03:00` UTC |

Every mode re-plans the whole enabled model set; only the window changes. The
daily and weekly sweeps re-read the ranges the fast sweep deliberately skips, so
slow-moving history is still covered without paying that cost every 15 minutes.

`RecoveryRequest` caps a single range at 90 days, which is why `full` uses 90.

## Freshness validity

A reconciled marker stays valid for `MARKER_VALIDITY` (30 minutes), which is two
refresh cycles. One missed or slow cycle therefore does not turn a healthy read
model into a visible `DATA_UNAVAILABLE` result.

## Configuration

All knobs are runtime environment variables on the Sheets worker. Refresh
arrives disabled and must be enabled explicitly.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZELERDATA_REFRESH_ENABLED` | `false` | Kill switch. Set `true` to enable the loop. |
| `ZELERDATA_REFRESH_SELLERS` | — | Required numeric allowlist when enabled. |
| `ZELERDATA_REFRESH_INTERVAL_SECONDS` | `900` | Fast-cycle interval. |
| `ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE` | `180` | Reserved acquisition budget. |

Refresh also requires `ZELERDATA_FORMULA_RECOVERY_ENABLED=true`, because it plans
work for the recovery worker rather than acquiring data itself. Enabling refresh
without recovery fails startup instead of running a loop that can never finish a
job.

The gateway allows 600 requests per minute per module and seller. The default
reservation leaves roughly 30% to acquisition (`180`) and the rest to interactive
queries, which is the split agreed after a production write aborted with
`retry_after=22s` under an unqualified budget.

## Safety properties

- Closed by default: with no seller allowlist, no work is planned.
- No formula-path latency: refresh only inserts queue documents; acquisition
  stays in the existing worker.
- Bounded failure isolation: one failing seller or one rejected model does not
  stop the rest of the cycle.
- Explicit stop: the loop is a co-resident poller in the worker, so it stops with
  the worker and can be disabled without a deploy by setting the flag.

## Verification

```bash
uv run pytest modules/sheets/tests/test_zelerdata_refresh.py \
  modules/sheets/tests/test_zelerdata_recovery_pacing.py \
  tests/test_gce_compose_contract.py
```

Deployment: build and deploy the Sheets worker image, then set
`ZELERDATA_REFRESH_ENABLED=true` on the worker and confirm
`zelerdata_refresh` reports a healthy component status.
