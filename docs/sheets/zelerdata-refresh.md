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

### Spaced item and catalog sweeps

Item rows and catalog snapshots have no freshness marker, and none is
published (see the item readiness rules in `zelerdata-formulas.md`). Their
readers check how recent each acquisition is: the inventory enumeration and
each publication's base row must be at most 15 minutes old, a catalog product
snapshot at most 4 hours old, and quality, cost fields and a buybox snapshot
at most 24 hours old (buybox is served as cached after 15 minutes). Quality
and costs stay valid across base re-syncs only while their basis matches. A
daily sweep would therefore keep the item formulas `OK` only for minutes a day.

Since L-021, the every-cycle bulk planner is off
(`ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED=false`). Two whole-seller sweeps can
instead be enabled on their own spacing. A spaced sweep is never planned while
a sweep of the same model is pending or running, so a pass cannot restart before
it finishes:

| Sweep | Flag | Interval | Interval starts at |
| --- | --- | --- | --- |
| Base inventory (`item_formula_rows`) | `ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED` | `ZELERDATA_INVENTORY_REFRESH_MINUTES` (10) | the previous discovery, or the end of a pass that failed before discovering |
| Catalog products (`catalog_product_snapshots`) | `ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED` | `ZELERDATA_CATALOG_REFRESH_HOURS` (3) | the end of the previous pass |

- The inventory is checked every 30 seconds and the catalog every refresh cycle.
  The inventory sweep acquires base fields only (one discovery plus 20-ID
  batches, about 115 calls for 1,900 publications). Quality, costs and
  promotions still come from formula-triggered recovery.
- An inventory pass re-observes every publication. A buybox acquisition is valid
  only if it is newer than its item's last observation, and buybox persistence
  fails if the item changes during the chunk. The inventory therefore waits while
  a buybox job has made progress in the last two leases (20 minutes). This was
  the probable source of the September buybox `source_incomplete` failures,
  when every-cycle bulk sweeps ran alongside buybox jobs.
- Buybox is never scheduled. Keeping roughly 900 publications within 15 minutes
  would require about 150 sustained requests per minute, which L-021 rules out.
  `CATALOGOBUYBOX` and `CATALOGO` remain on demand and serve a snapshot for up
  to 24 hours, so one on-demand pass covers a day of reads.
- Bulk and spaced sweeps are mutually exclusive; enabling both fails startup.

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
Turn it on only after an operator-authorized run exists for the pilot, or to run
the ordinary tail below.

#### Ordinary tail while history on link is off (2026-10-07)

A seller in certificate mode (`coverage_mode=active`, the pilot since
2026-10-02) is read only through `sheets_devoluciones_certificates`. Only an
acquisition extends them. Until 2026-10-07 the only automatic acquisition was
the history pilot's incremental claims run, so pausing the pilot froze coverage
at its last run (2026-10-06T06:52Z) and every current DEVOLUCIONES range
returned `DATA_UNAVAILABLE`. The legacy marker that expired at 07:22Z was
written by that run's finalize; nothing renews it in certificate mode, and the
reader does not use it there.

Same principle as L-036: a paused pilot must not hold ordinary work. With
`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=true` and
`ZELERDATA_HISTORY_ON_LINK_ENABLED` off, each cycle:

1. ignores `onboarding:` runs, which the paused plan cannot authorize;
2. advances any other due run, as before;
3. otherwise admits one ordinary run (`authorization_id=refresh-tail:v1`) from
   the newest certificate's `date_to` in the current epoch up to the last UTC
   midnight at least one hour old, capped at one 10-day window;
4. acquires it through the ordinary runtime gateway with the existing
   per-window physical attempt ledger and finalizes it in the same invocation,
   publishing its certificate.

Finalizing at once matters: a one-window run expires 1,070 s after admission,
but the next cycle arrives only after the cycle's own work plus 900 s. The
finalize step is a local readback with no source calls.

The admission day is part of the run identity, so a failed or expired tail is
retried at most once per UTC day. A longer gap catches up one 10-day window per
cycle. The tail never starts without certified coverage and never re-acquires a
stale interval; those remain operator runs. With history on link on, nothing
changes: the pilot owns the incremental run. DEVOLUCIONES therefore answers
ranges that end on the previous UTC day or earlier. A range that includes today
needs coverage up to tomorrow 00:00 UTC and stays unavailable by design.

##### Pre-v2 rows in the tail window (2026-10-08)

The tail for 2026-06-11..06-21 certified its only window (9 claims), but its
final readback counted a tenth `returns` row in the pre-v2 format (no
`productive` or `return_quantity_basis`). The v2 acquisition rewrites only
claims its inventory reports, so the row stayed, the run failed, and the next
day's retry failed the same way. Relaxing the readback alone does not help:
publishing the certificate and every certified read run
`verify_devoluciones_read_model`, which rejects any non-canonical row in range.

After its source revalidation, each tail window now moves this seller's
non-canonical `returns` rows in the window that the inventory does not report to
`sheets_devoluciones_claim_quarantine`. Each row is archived byte for byte with
its SHA-256, run, window, source fingerprint, and the source exclusion if any,
and is removed in the same fenced transaction. A canonical v2 row the source
omits is not moved; the run still fails closed. Operator and pilot runs share
the window executor without this step and keep failing on any non-canonical row.
Restoring an archived row blocks the range again.

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
run named by `revision`, and re-certifies the settled range from the run
windows. When the range still proves itself complete it republishes the marker
with a fresh 30-minute lease. It never calls Mercado Libre and never widens
coverage.

Certification is deliberately **not** byte-for-byte fingerprint equality. The
finalize fingerprint folds in live `claims` counts, so equality stops holding
the moment the pilot records a legitimate claim inside the settled window and
the heartbeat would freeze permanently: production measured exactly that on
2026-09-11, with `reason=proof_changed` and a marker stuck at its old
`valid_until`. The gate instead requires the same bounds, the same expected
count, no missing rows, and fully persisted and complete claims. A regressed
range (`settled_range_has_missing_claims`, `settled_range_incomplete`), a moved
range, incomplete windows, or a missing run is refused, so an unproven range can
never be made productive. Every refusal is logged with its reason
(`zelerdata.devoluciones_renewal_refused`) so a stalled heartbeat is diagnosable
instead of looking identical to a healthy one.

The renewal is **not** gated by `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED`. That
flag gates source work only; the renewal is a local read and runs every cycle
for every refresh seller, which is what carries a settled proof across the
30-minute lease. In certificate mode the same call renews due certificates
instead of the legacy marker; renewal never extends coverage to new days.

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
| `ZELERDATA_REFRESH_SELLERS` | — | Required when enabled: a numeric allowlist, or `all` (see [All eligible sellers](#all-eligible-sellers-all-mode)). |
| `ZELERDATA_REFRESH_INTERVAL_SECONDS` | `900` | Fast-cycle interval. |
| `ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE` | `180` | Reserved acquisition budget. |
| `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED` | `false` | Legacy every-cycle plan of all six models plus the inventory tick (L-021). |
| `ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED` | `false` | Spaced base-inventory sweep. |
| `ZELERDATA_INVENTORY_REFRESH_MINUTES` | `10` | Minutes between inventory discoveries. |
| `ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED` | `false` | Spaced catalog-product sweep. |
| `ZELERDATA_CATALOG_REFRESH_HOURS` | `3` | Hours from the end of one catalog pass to the next. |
| `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED` | `false` | Advance an already-authorized DEVOLUCIONES run from this loop; with history on link off, also admit the ordinary daily tail. |
| `ZELERDATA_PRECALCULATED_FORMULAS_ENABLED` | `false` | Precalculate the heavy aggregate formulas during the refresh cycle. |
| `ZELERDATA_FRESHNESS_ALERTS_ENABLED` | `false` | Emit the operator freshness alarms from the `sheets_read_model_freshness` markers. |
| `ZELERDATA_DLQ_ARCHIVE_ENABLED` | `false` | Run one bounded Sheets DLQ archive pass per refresh cycle. Requires `RABBITMQ_URL`. |

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
- DEVOLUCIONES stays inside an explicit authorization boundary: the loop only
  advances operator or pilot runs, plus, with history on link off, one bounded
  forward tail per day from existing certified coverage. The legacy systemd
  timer is superseded.
- The DLQ archive stays evidence-based: a message is only removed when a
  reconciled marker already covers its window or it is past retention, the
  sanitized record is written before the ack, and everything else is requeued
  untouched. A misconfigured enable fails at build time instead of silently
  skipping the pass.

## Verification

```bash
uv run pytest modules/sheets/tests/test_zelerdata_refresh.py \
  modules/sheets/tests/test_zelerdata_sweep_status.py \
  modules/sheets/tests/test_zelerdata_recovery_pacing.py \
  tests/test_gce_compose_contract.py
```

Deployment: build and deploy the Sheets worker image, then set
`ZELERDATA_REFRESH_ENABLED=true` on the worker and confirm
`zelerdata_refresh` reports a healthy component status.

## All eligible sellers (`all` mode)

`ZELERDATA_REFRESH_SELLERS` and `ZELERDATA_FORMULA_RECOVERY_SELLERS` accept
`all` as well as a numeric allowlist. The environment templates still ship the
pilot allowlist, so nothing changes until an operator sets `all`.

| Value | Refresh (worker) | Formula recovery (worker and API) |
| --- | --- | --- |
| empty or unset | Startup fails when refresh is enabled. | Closed: no seller is admitted. |
| `82453304,...` | Exactly those sellers, as before. | Exactly those sellers, as before. |
| `all` | Eligible sellers, rediscovered every cycle. | Any eligible seller; admission checks eligibility. |

Startup rejects mixed values such as `all,82453304`.

### Eligibility

A seller is eligible when both conditions hold:

1. Its `meli_accounts` document has `status` `active` or `refresh_pending`
   (a token refresh in progress, which the gateway waits for). Sellers with
   `paused`, `revoked`, `invalid_grant`, `error`, `invalid` or `pending` are
   excluded.
2. ZelerData is enabled for it: at least one `sheets_extension_tokens`
   document is `active`, not deleted and not expired, and its `seller_scopes`
   includes the seller. The module registry has no per-seller switch (the
   `sheets` entry is global), so the extension token is the per-seller
   signal. A linked seller that only uses ZelerPricing or ZelerSupport is not
   refreshed.

`eligible_sellers` in `modules/sheets/src/zeler_sheets/formulas/seller_scope.py`
implements this rule. Refresh reads it again on every cycle. Recovery admission
and claiming share a cache of 30 seconds per process. Pausing a seller or
revoking its last token removes it without a restart.

A job that was already queued when its seller became ineligible is closed when
a lane claims it: `state` `failed`, `failure_reason` `seller_not_eligible`,
`available_at` one cooldown (15 minutes) later, and the claim moves on to the
next job in the same call. No request reaches the gateway or Mercado Libre for
it. If the seller becomes eligible again, the next refresh re-admits the work
after the cooldown. The gateway's own 423 `seller_paused` and 412
`account_not_active` answers remain as a second guard for the cache window.

The numeric allowlist does not check eligibility, so the pilot behaves exactly
as before.

### What `all` does not open

- **The 12-month history pilot.** The legacy backfill
  (`build_pilot_history_backfill`) creates a `sheets_history_backfill_plans`
  document and up to twelve months of orders and questions for every seller it
  sees, so `all` mode does not wire it. `ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED`,
  `ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED` and
  `ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED` require an explicit numeric
  `ZELERDATA_FORMULA_RECOVERY_SELLERS`. With `all`, the worker fails at startup
  and names the flag. History on link (`ZELERDATA_HISTORY_ON_LINK_*`) keeps its
  own allowlist and is not affected.
- **DEVOLUCIONES.** The daily tail runs only for sellers in certificate mode,
  which is only the pilot today. A new seller without certificates gets no
  returns acquisition.
- **Refresh without recovery.** `ZELERDATA_REFRESH_SELLERS=all` requires
  `ZELERDATA_FORMULA_RECOVERY_SELLERS=all`, otherwise startup fails. Refresh
  would otherwise queue jobs that the recovery worker never claims.

### Failure isolation

- **Refresh cycle.** Each per-seller step (planning, observed markers,
  DEVOLUCIONES, precalculated formulas, alarms) catches its own error. A 429,
  a revoked token or a storage error for one seller is logged and the cycle
  continues with the next seller. Only a failed discovery (Mongo unavailable)
  fails the whole cycle. Three consecutive failures exhaust the restart budget.
- **Recovery jobs.** A 429 or 5xx is retried after 30 s, then 60 s, up to three
  attempts. Any other 4xx (423, 412, 401, 403) fails the job as
  `source_rejected`, with a 15-minute cooldown. A local quota wait defers the
  job without using an attempt. A job is capped at 240 s, and then its lane
  claims the next job, whichever seller it belongs to.

`modules/sheets/tests/test_zelerdata_all_sellers.py` covers both paths.

### Limits and shared capacity

| Resource | Scope | With N sellers |
| --- | --- | --- |
| Gateway proxy limit (600/min, `GATEWAY_PROXY_RATE_LIMIT`) | Per module and seller | Not shared. One seller's 429 does not affect the others. |
| Recovery pacer (`ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE`, 180) | One per worker process, shared by every seller and lane | The total never exceeds 180/min, so no seller's gateway budget saturates. Sellers split it, about 180/N each under contention. It is fair across lanes, not across sellers. |
| Recovery lanes (`inventory`, `ids`, `ranges`) | One job at a time per lane and worker | Three jobs at once in total, up to 240 s each. Claims are FIFO by `available_at` across sellers. |
| Recovery queue | Up to 20 active jobs per seller | Shared collection with claim indexes. At most N × 20 active jobs. |
| Refresh cycle | Sellers run one after another; the next cycle starts one interval after the previous one ends | Cycle duration grows linearly. Markers last two intervals (30 min). |
| Mercado Libre application limits | Every seller shares the Zeler application | Not measured here. The pacer limits background traffic. |

By default, scheduled refresh plans only orders and questions: the last hour
every 15 minutes, 7 days once a day, and 90 days once a week. That costs a few
requests per seller and cycle. Whole-seller sweeps multiply by the number of
sellers, so keep them off at first in `all` mode. This includes
`ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED` and any spaced inventory or catalog
sweep. As a reference, an inventory sweep for a seller with about 1,900
listings costs about 12 requests per minute. Roughly 15 sellers of that size
would fill the 180 reservation with inventory alone.

### Scale analysis (N eligible sellers)

Measured from the code, not in production. Every cycle logs
`zelerdata.refresh_cycle_completed` with `sellers`, `warm_deferred` and
`elapsed_seconds`; use it to confirm these figures.

**Everything is serial, and nothing chains.** The refresh loop is one task. A
cycle visits sellers one after another, and the next broad cycle starts one
interval *after the previous one ends* (`next_cycle = finished + interval`).
Cycles therefore never overlap and never run back to back, however long they
take. The 10-minute inventory tick follows the same rule, so a long cycle only
delays it. The period of a seller's refresh is `cycle duration + interval`.

**What costs time per seller in the cycle:**

| Step | Cost | Scales with |
| --- | --- | --- |
| Planning (orders and questions ranges), observed markers, freshness alarms | A few Mongo reads and two enqueues, each capped at 2 s | N, in milliseconds |
| DEVOLUCIONES runner | Three Mongo reads for a seller without certificates; it admits and advances a tail only for certificate sellers, which is the pilot today | Number of certificate sellers |
| Precalculated formulas | 10 dispatcher runs (5 formulas × 2 header variants), reading the seller's local catalog. It dominates the roughly 130 s cycle of the pilot | Catalog size of each seller |

**The concrete risk was the warmer.** Markers and precalculated entries last 30
minutes. With period `D + 900 s`, they survive only while `D` stays under one
interval (900 s). Five sellers of pilot size already pushed `D` to about 650 s
and a seventh would have crossed it, after which *every* seller's observed
markers would expire between renewals, not just the warmed ones. Because the
warmer ran inline, the sellers at the end of the list were also the last to be
planned.

**Limit added.** Warming has a per-cycle budget of half an interval (450 s by
default; `warm_budget_seconds` on the supervisor). The check runs before each
seller, so a cycle ends at most one warm after the budget. A seller over budget
keeps every other step and is counted in `warm_deferred`. The next cycle starts
from the first deferred seller, so everyone is warmed in turn. A deferred
seller's precalculated results expire after 30 minutes and its sheet calls fall
back to the on-demand path, the existing degradation. The pilot alone (about
130 s) never reaches the budget. Covered by
`test_precalculated_warm_budget_*`.

**Recovery worker and sweeps.** These are bounded by design, so nothing else
needed a limit:

- The pacer is one bucket per worker process: the total stays at 180 requests
  per minute whatever N is, so no seller's gateway quota of 600 per minute is
  approached. Lanes rotate (`inventory`, `ids`, `ids`, `ranges`), and idle lanes
  lend their slots to the others. A job that waits more than 239 s for budget
  is deferred without using an attempt.
- Each lane runs one job at a time (three in total), claimed FIFO across
  sellers. Active jobs are capped at 20 per seller, so the queue holds at most
  `N × 20`, and a full seller simply stops being re-planned.
- Spaced sweeps (inventory every 10 minutes, catalog every 3 hours) never
  overlap for a seller: `sweep_status` refuses a new pass while one is in
  flight and counts the spacing from the previous pass. At the first tick all N
  sellers are admitted at once, but the single inventory lane drains them in
  order, so later passes start staggered. If N sellers need more inventory
  requests than the budget gives the lane (about 45 per minute while other
  lanes are busy, up to 180 when idle), the passes stretch beyond 10 minutes
  and item freshness degrades. Nothing queues up behind it. At about 12 requests
  per minute for a 1,900-listing seller, 15 such sellers saturate the whole
  reservation. Keep the sweeps off in `all` mode until the first cycles are
  measured.
- Memory does not grow with N: the warmer and each lane handle one seller at a
  time, so the peak follows the largest seller's catalog. The worker also hosts
  consumers and three lanes in one process on a 3.9 GB VM that Mongo shares.
  Watch `docker stats` for `sheets-worker` during the first warm cycles; this
  document has no production measurement of it.
- DEVOLUCIONES: only certificate sellers advance or admit a tail, and the tail
  runs inside the refresh cycle. If more sellers gain certificates, their
  advances add to `D` and are not covered by the warm budget.

Revisit capacity when:

- `elapsed_seconds` exceeds about 300 s, or `warm_deferred` is above 0 for
  several cycles in a row,
- pending `ranges` jobs wait longer than one interval, or
- freshness alarms fire for sellers whose refresh is healthy.

The first options are to raise the reservation or to add claims that are fair
across sellers. The reservation is global, so even 300 stays under each
seller's 600 gateway quota. Check the Mercado Libre application limits before
raising it.

### Production activation

Production changes run only from the main session, after this change is
merged and with explicit authorization. An image without this change rejects
`all` at startup, so the images go first and the variables change after them.

1. **Images.** Build and deploy `sheets-worker` and `sheets-api` from `main`
   without changing any variable. Behavior stays identical. Verify health and
   that the pilot is still served.
2. **Read-only dry run** inside `sheets-worker` (sanitized: counts only, no
   seller IDs, nicknames or tokens):

   ```bash
   .venv/bin/python -m infra.operations.zelerdata_all_sellers_dry_run \
     --seller-id 82453304
   ```

   It prints how many sellers would be eligible, how many are excluded for
   each reason (`account_paused`, `no_extension_token`,
   `extension_token_expired`, ...), the active recovery jobs that belong to
   ineligible sellers, the current scope and flag values (kind and on/off, not
   IDs), and whether the requested seller is eligible. Continue only if:
   - the pilot is eligible (otherwise `all` would stop refreshing it),
   - `matches_runtime_rule` is `true`,
   - `eligible_sellers` is a number the capacity figures above can carry.
3. **Preflight of flags** in the same output: `ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED`,
   `ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED`,
   `ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED`,
   `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED`,
   `ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED` and
   `ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED` must read `false`.
4. **Worker first.** Set `ZELERDATA_FORMULA_RECOVERY_SELLERS=all` and
   `ZELERDATA_REFRESH_SELLERS=all` together (refresh requires recovery to be
   `all`, or startup fails). Leave every other variable as it is. Restart only
   `sheets-worker`. Verify:
   - the `formula_recovery` and `zelerdata_refresh` components,
   - delivery progress (L-027),
   - `zelerdata.refresh_cycle_completed` with `sellers` equal to the dry-run
     count, `warm_deferred` and `elapsed_seconds` (target: under 300 s; the
     cycle that follows the restart is the first full measurement),
   - jobs for every eligible seller reaching `completed`, and `docker stats`
     for `sheets-worker` memory over the first warm cycles.
5. **API second.** Set `ZELERDATA_FORMULA_RECOVERY_SELLERS=all` and restart
   only `sheets-api`. Verify `/health` and a `formula_recovery_admission` with
   outcome `admitted` for a seller other than the pilot.
6. **Sweeps stay off** until at least a day of cycles shows `warm_deferred` at
   0 and a short `elapsed_seconds`. Turn on one sweep at a time afterwards and
   compare the figures in the scale analysis.

**Back to the pilot.** Reverse the order and restore the value on each
service, then restart only that service:

1. `sheets-api`: `ZELERDATA_FORMULA_RECOVERY_SELLERS=82453304`.
2. `sheets-worker`: `ZELERDATA_FORMULA_RECOVERY_SELLERS=82453304` and
   `ZELERDATA_REFRESH_SELLERS=82453304`.

Change the variables before any image rollback. No data migration is involved.
Jobs queued for other sellers stay `pending` and unclaimed while the allowlist
is numeric. `ZELERDATA_REFRESH_ENABLED=false` remains the kill switch for the
loop.

Verification for this mode:

```bash
uv run pytest modules/sheets/tests/test_zelerdata_all_sellers.py \
  tests/operations/test_zelerdata_all_sellers_dry_run.py
uv run pytest modules/sheets/tests/test_formula_recovery.py -k "all_mode or numeric_allowlist_claim"
```
