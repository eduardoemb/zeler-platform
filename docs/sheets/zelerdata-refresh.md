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

### Observed-only read models

Four models are *observed history*: `shipments`, `price_history_snapshots`,
`stockout_snapshots` and `item_status_states`. Their truth is what the platform
actually observed, so no source reconciliation can certify them: a range can be
complete from the source and still carry no observation for an item the seller
never changed.

The same cycle therefore renews one heartbeat marker per model and seller from
`zeler_sheets.observed_read_model_markers`. The marker records the newest and
oldest observation the loop audited, is published with
`coverage_basis=observed_only` and `source=zelerdata_observed_read_model`, and
expires after two refresh cycles. Consequences:

- A stopped refresh loop still fails the formulas closed, because the marker
  expires.
- A model with no observation, or whose newest observation is older than the
  daily sweep horizon (7 days), is never certified.
- An already-productive reconciled claim is never downgraded by the heartbeat.

### Durable shipment fields

A shipment receiver address and a settled seller cost are immutable history.
Once observed, a non-empty value is served for every later read; the reader does
not re-require a recent observation, because the reserved quota cannot refresh a
multi-year shipment history every 15 minutes. When a field is absent the reader
serves `NA` for that row and requests background recovery instead of failing the
whole table. A field Mercado Libre itself declared unavailable is served as `NA`
without a permanent recovery loop.

### DEVOLUCIONES inside the loop

DEVOLUCIONES used to be driven by its own systemd timer
(`zelerdata-devoluciones-reconcile.timer`), which was disabled after the 2026-08-25
run failed with `quota_run_advancement_failed`. Per Q2-b/Q7-a that trigger moved
into this loop, so one loop owns operational freshness.

Each cycle calls `zeler_sheets.devoluciones_runner.advance_due_devoluciones_run`
once per seller. The runner only *advances* an already-authorized run: the run
must exist for that seller, be in an advanceable state (`authorized` or
`active`), still be unexpired, and be past its own `not_before`. It never creates,
re-authorizes, or widens a run; creating the run stays an explicit operator
action (`infra.operations.devoluciones_quota_authorize`). The real advancement
keeps the existing lease, 10-day window bound, and readback guarantees.

The absorbed trigger is off by default (`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=false`).
Turn it on only after an operator-authorized run exists for the pilot.

#### Renewing a settled marker

The quota finalize publishes the `devoluciones` marker once, when the last window
settles. Nothing re-runs it until the next authorized run, but the marker only
leases for 30 minutes, so a proven range still has to be renewed between
authorizations.

The fast `orders` sweep shares that lease but never rewrites the claims-derived
returns the proof covers, so it acquires with `invalidate_readiness=false`,
exactly like the `orders.*` event handler. Only a `claims.*` acquisition
withdraws the proof, because only that acquisition can change what the proof
certifies.

`renew_devoluciones_marker_if_proven` closes that hole. It only reads Mongo: it
requires the marker to carry a `proof_fingerprint`, finds the settled `completed`
run named by `revision`, recomputes the finalize fingerprint from the run
windows, and republishes the marker with a fresh 30-minute lease only when the
recomputed proof matches the stored fingerprint. It never calls Mercado Libre
and never widens coverage; a changed proof, a missing run, or an open marker is
refused, so an unproven range can never be made productive.

The renewal is **not** gated by `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED`. That
flag gates source work only; the renewal is a local read and runs every cycle
for every refresh seller, which is what carries a settled proof across the
30-minute lease.

## Precalculated heavy formulas

A Sheets custom function cannot exceed the caller's 30 second budget, and the
five formulas that walk the whole catalog legitimately reach 20-27 seconds on
the pilot. Per Q3-b/Q8-a/Q16 the refresh cycle now precalculates those results in
the worker and the sheet call becomes a bounded document read.

The precalculated set is closed and explicit: `ZELERDATA_CATALOGO`,
`ZELERDATA_CATALOGOBUYBOX`, `ZELERDATA_CATALOGO_COMPLETO`, `ZELERDATA_CALIDAD`
and `ZELERDATA_DASHBOARD`. Detail formulas stay on demand because their cost is
per row and their arguments are unbounded.

Each entry is keyed by seller, formula and the *canonical* argument map, so two
spellings of the same call share one entry and a different argument can never
read another caller's result. A result is served only while its `valid_until`
is in the future, the same window the freshness markers use. When the flag is
off, when no entry exists, or when the entry expired, the call falls back to the
existing on-demand path: the sheet degrades to today's behavior instead of
serving a stale table as current. A formula whose productive data is unavailable
is never cached, so no empty or partial table is ever published as the real
answer.

## Configuration

All knobs are runtime environment variables on the Sheets worker. Refresh
arrives disabled and must be enabled explicitly.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZELERDATA_REFRESH_ENABLED` | `false` | Kill switch. Set `true` to enable the loop. |
| `ZELERDATA_REFRESH_SELLERS` | — | Required numeric allowlist when enabled. |
| `ZELERDATA_REFRESH_INTERVAL_SECONDS` | `900` | Fast-cycle interval. |
| `ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE` | `180` | Reserved acquisition budget. |
| `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED` | `false` | Advance an already-authorized DEVOLUCIONES run from this loop. |
| `ZELERDATA_PRECALCULATED_FORMULAS_ENABLED` | `false` | Precalculate the heavy aggregate formulas during the refresh cycle. |

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
- DEVOLUCIONES stays inside the operator authorization boundary: the loop never
  creates or expands coverage, and the legacy systemd timer is superseded.

## Verification

```bash
uv run pytest modules/sheets/tests/test_zelerdata_refresh.py \
  modules/sheets/tests/test_zelerdata_recovery_pacing.py \
  tests/test_gce_compose_contract.py
```

Deployment: build and deploy the Sheets worker image, then set
`ZELERDATA_REFRESH_ENABLED=true` on the worker and confirm
`zelerdata_refresh` reports a healthy component status.
