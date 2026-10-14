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
| Renewal of buybox, quality and costs | `ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED` (on by default) | `ZELERDATA_RENEWAL_REFRESH_HOURS` (12, at most 12) | fixed UTC slots: 01:00 and 13:00 at 12 hours; one seller at a time |

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
- Buybox is not kept within 15 minutes: that would take about 150 sustained
  requests per minute for roughly 900 publications, which L-021 rules out.
  Readers serve a buybox snapshot, quality and costs for up to 24 hours (L-044),
  and the renewal sweep below keeps them inside that day.
- Bulk and spaced sweeps are mutually exclusive; enabling both fails startup.

### Renewal of on-demand acquisitions (11 October 2026)

Buybox, quality and costs are acquired only by recovery. Until this change a
formula read was the only trigger, so a sheet nobody opened for more than a day
came back with almost every row `DATA_UNAVAILABLE` while a recovery pass ran
(about one hour). On the pilot on 11 October, after two quiet days, `CATALOGO`
had 921 of 922 rows without buybox, `CATALOGOBUYBOX` 8,109 of 8,109 cells
without data, `CALIDAD` 1,874 publications without quality and `CALCULADORA`
2,813 of 2,886 rows without costs.

The renewal sweep plans that same recovery on a schedule, with two
whole-inventory passes: one `catalog_buybox_snapshots` intent and one
`item_formula_rows` intent by explicit IDs, which re-reads quality, costs,
commission, fixed fee and promotion. The worker, the 20-ID chunks, the per-chunk
retries, the coalescing with jobs already queued, and the buybox load control
(L-020) are the ones formula reads use.

**What a pass renews.** The readers' own rules, evaluated at the end of the
renewal horizon: a pass selects what readers would no longer serve 6 hours
from now (half the interval). That is anything absent, mismatched (product,
title, quantity, quality basis), failed or incomplete, and every acquisition
at least 6 hours old. A source-declared absence (`not_listed` buybox, quality
not generated or HTTP 400, an `authoritative_absent` cost) is served as `NA`
and is not selected while it is younger than 6 hours (L-045). It is renewed
like any other acquisition before the readers' 24 hours expire. Only the
publications of the latest inventory enumeration are considered, minus those
its pass already reached but could not re-read (their base is older than the
discovery, typically a detail 404). Readers count those as partial misses, and
renewing them would only fail their 20-ID chunk three times. Without an
enumeration nothing is renewed.

**When.** Slots are fixed in UTC: with 12 hours, at 01:00 and 13:00 UTC (19:00
and 07:00 in Mexico City). Each slot admits at most one pass per model, keyed
by the slot (`RenewalRecoveryRequest`), so it never reopens a terminal job of
an earlier pass or an on-demand job. A pass is not planned while any
explicit-ID pass of the same model is pending or running, including one a
formula read admitted. The first cycle after a deploy or restart plans the
current slot at once. A slot where nothing is due is checked once per process.
A selection or admission that fails is retried on the next cycle.

**Why the margin holds.** An acquisition is renewed at most 1.5 intervals plus
two passes after it was made: 6 + 12 + 2 × 1.25 hours, plus up to two
15-minute cycles, is about 21 hours, under the readers' 24. Hence the 12-hour
maximum. A pass that fails leaves its gaps to the next slot; formula reads
still request them in between.

**Several sellers take turns (12 October 2026).** Renewal is planned once per
refresh cycle for the whole fleet (`ZelerDataRefreshPlanner.plan_renewals`),
not per seller. While a seller's renewal pass of this or the previous slot is
pending or running, only that seller may plan its other model; everyone else
waits. When no pass is in flight, the turn goes to the first seller with
something due: sellers whose previous slot has no pass first, then the rest in
seller order. A seller with nothing due, or whose own on-demand pass holds the
model, does not take the turn. Why one at a time: every pass uses the same
`ids` lane and pacer, so N passes together would each take about N times
longer, and so would the inventory pause of each buybox pass (L-037) and the
age of what they renew. One at a time, each seller keeps the pilot's pass
length and pause, and its turn lands at about the same time each slot.
If a slot ends before every seller had its turn, the sellers it missed go
first in the next slot, so an overloaded fleet rotates instead of starving
the last sellers. The turn is read by slot key (`renewal_passes`), so it
survives restarts and adds no field to the job document. With one seller,
as with the numeric allowlist today, nothing changes.

**Selection cost.** Planning reads the enumeration, then items, buybox
snapshots and formula rows in chunks of 200 IDs with projections, keeping only
the selected IDs (L-041). It never calls Mercado Libre.

**Source calls, from the code, per pilot pass (about 934 catalog publications
and 1,895 inventory publications):**

| Pass | Calls per publication | Calls per pass |
| --- | --- | --- |
| Buybox | `price_to_win` + offers listing = 2; plus the winner's detail when it is not in the listing (rare); plus a full item re-read (detail + sale price + listing price + quality, and shipping options for seller-paid free shipping: about 5) when the item's base row is older than 15 minutes | 1,900 if every item is fresh, about 6,500 if every item is stale; about 4,800 when the first 15 minutes are fresh |
| Quality and costs | detail in batches of 5 (0.2) + sale price 1 + listing prices 1 (the fixed fee reuses that quote when the parameters match, otherwise +1) + quality 1 (a User Product retry adds 1; skipped during the not-generated retry window) + shipping options 1 for seller-paid free shipping | about 6,100 to 9,900; about 8,000 typical |

That is about 8,000 to 16,400 calls per slot, about 12,800 typical, and about
25,600 calls per day for the pilot, roughly 18 per minute averaged over the day.
The 9 October on-demand recovery of the same two sets (934 and 1,895 IDs) took
51 and 74 minutes under the 180-per-minute recovery pacer, at most about 13,300
calls, which matches the typical figure. During a pass the pacer is the limit,
so other recovery waits its turn as with any on-demand pass. For comparison, the spaced inventory
sweep costs about 16,500 calls per day (about 115 every 10 minutes) and the
catalog product sweep about 6,400 (one call per product, about 875 products,
every 3 hours plus the pass).

**Side effect during a buybox pass.** The base inventory sweep waits while a
buybox job is making progress (L-037), so for the 50 or so minutes of the
buybox pass the enumeration ages past 15 minutes and item formulas show the
expired-enumeration row and rows whose base is older than 15 minutes as
unavailable. On-demand buybox passes already do this; the slots place it at
19:00 and 07:00 in Mexico City.

**Worker memory.** A pass runs the same 20-ID chunks as an on-demand recovery
of the same IDs, one job per lane, with no new resident state; the job
document holds the ID list (about 30 KB). Selection holds one 200-ID chunk at a
time and keeps only the selected IDs, under 2,000 short strings. Neither grows
with the seller beyond that list. The worker used about 235 MiB of its 1 GiB
limit on 11 October; this document has no production measurement during a
pass, so watch `docker stats` for `sheets-worker` during the first slot.

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

Each cycle first renews every seller's proof, once per seller
(`advance_due_devoluciones_run` with source work off). Renewal is local and
runs whatever the source flags say; see "Renewing a settled marker".

Source work then gets its own pass after every seller's other steps, capped at
**one window per cycle for all sellers together**. A window can take up to
about three minutes (165 s of source work plus its local readback, finalize and
activation) inside the serial cycle, and the warm budget does not cover it.
The sellers take turns: the pass offers the turn in discovery order, starting
after the last seller served, and stops at the first seller that does source
work. A seller with nothing due passes the turn at the cost of a few Mongo
reads. A failure counts as that seller's window (it may already have spent
calls), is logged as `zelerdata.devoluciones_run_failed`, and the next cycle
starts with the next seller, so no seller blocks the others. The turn is kept
in memory; after a restart the pass starts again from the first seller.
`zelerdata.refresh_cycle_completed` reports `devoluciones_windows` (0 or 1).

For the seller that gets the turn, the runner advances one due window:

1. a run that already exists for that seller, is advanceable (`authorized` or
   `active`), unexpired and past its own `not_before` (operator or pilot runs,
   or a resumed automatic run);
2. otherwise, with history on link off, the ordinary daily tail of a seller in
   certificate mode (below);
3. otherwise, with history on link off, the initial window of an eligible seller
   without coverage (see "Initial coverage for a new seller").

It never re-authorizes or widens an operator run. The real advancement keeps the
existing lease, 10-day window bound, and readback guarantees.

When no seller took the window that way, the cycle offers it to the intraday
passes, in their own turns (see "Intraday coverage of the day in progress").

The source pass is off by default (`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=false`).
The ordinary tail, initial coverage and intraday coverage all need it on.

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
turn. The tail never starts without certified coverage (a new seller first gets
its initial window; see "Initial coverage for a new seller") and never
re-acquires a stale interval; that remains an operator run. With history on
link on, nothing changes: the pilot owns the incremental run. The tail
certifies closed days only; since 2026-10-12 the day in progress is covered up
to an hourly cut (see "Intraday coverage of the day in progress"). The tail
continues from the newest certificate of a closed day, never from a cut.

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

##### A listed claim whose detail Mercado Libre forbids (2026-10-09)

The tail for 2026-07-31..08-10 failed in the same minute on 9 and 10 October.
Its inventory listed six claims; for one of them (stage `dispute`) Mercado
Libre answered 403 on the claim, its v2 returns, its detail and its reputation
impact. No endpoint returns data for that claim, so the window could never
close, and the quota runner turned the failure into a failed run with no log.

The tail now excludes such a claim from the window. The exclusion applies only
to a 403 that Mercado Libre returns for the claim detail, which the gateway
forwards with `X-Zeler-Upstream-Attempts: 1`. A 403 from the gateway itself,
or a 401, 404, 429 or 5xx, still fails the window. The tail excludes at most one
such claim per window, and only while it is at most 20 % of the window's listed
claims; otherwise the window fails as before. The exclusion is part of the
window's source fingerprint. Revalidation must see the same 403. The completed
window stores `counters.excluded_claim_detail_forbidden`, and the worker logs
`zelerdata.devoluciones_forbidden_claim_excluded` with the claim id. No row is
written, so the claim is outside the expected count, the readback, the
certificate and the `DEVOLUCIONES` total for that range. Nothing in the formula
output marks the gap. If the claim already has a canonical row (for example,
from an earlier webhook), the readback counts it, and the window still fails
closed with `persisted_count` above `expected_count`. Operator and pilot runs
keep failing closed.

Any tail failure is now logged as `zelerdata.devoluciones_tail_failed` with its
`phase` (`window`, `readback` or `finalize`). A window failure also logs the
error class, the bounded source diagnostic (`failure_class`, `source_stage`,
`source_family`) and, for an incomplete readback, the four proof counts. It
never logs exception text, URLs or tokens.

Since 2026-10-13 a window failure also logs `failure_reason`, a stable code
for the check that refused it, and the quota runner stores it on the failed
run (`sheets_devoluciones_runs.failure_reason`, every run kind). Each of the
roughly 35 checks that raise `DevolucionesReadModelVerificationError` has its
own code: `source_*` for the hydrated source proof built while collecting
(for example `source_order_missing`, `source_order_line_ambiguous`), a field
name plus `_required` or `_not_datetime` for a missing field
(`return_subtype_required`), `revalidation_*_changed` for what the source
changed before publication, `snapshot_publication_too_old`, and `persisted_*`
for the read model's own readback. Any other failure gives its source stage and
family (`claim_search_server`), its projection reason, `window_proof_incomplete`
for a readback that does not match, or its `failure_class`. A readback failure
logs `failure_reason` only for a verification check. The pilot's year window
of 2026-05-12 to 05-22 failed twice on 2026-10-13 with only the error class,
and about 35 checks raise it. The runs validator must allow the field before
it is stored (applying it is a separate production step). Until then, the run
fails exactly as before and the reason is only in the log.

##### A return without a subtype (2026-10-14)

With that code, the pilot's window of 2026-05-12 to 05-22 failed a third time
with `return_subtype_required`: Mercado Libre answered one of its v2 returns
without a `subtype`. The claim model, the `claims` validator and the
projection already kept the subtype optional, and no reader uses it.
DEVOLUCIONES counts the return's order row (`return_quantity`), which is still
required, unique and a positive integer. Only the hydrated source proof
required the subtype, so the window could never close, in any run kind.

The proof now takes the subtype when present and `null` otherwise. A present
subtype keeps its exact value, so the fingerprints of certificates already
published do not change. A subtype that appears or changes later still
changes the fingerprint that revalidation and renewal compare. The other
return fields the proof requires (`id`, `status`, `last_updated`) and the
claim's `claim_version` and `last_updated` stay required. A window that one
of them blocks names it in `failure_reason`.

##### A v2 returns 404 the exclusion does not accept (2026-10-14)

The window of 2026-02-11 to 02-21 then failed three times with
`safe_404_precondition_failure`: Mercado Libre answered 404 for one claim's v2
returns, and the claim did not pass the checks that let a 404 exclude it as a
closed mediation without a return. That failure class alone did not say which
check, and production keeps no copy of a claim it does not count. The failure
now names the first check that refused, as `failure_reason` and as
`precondition_reason` in `zelerdata.devoluciones_tail_failed`, in this order:
`safe_404_inventory_not_mediation`, `safe_404_inventory_not_closed`,
`safe_404_claim_identity_differs`, `safe_404_claim_version_differs`
(`last_updated` differs from the search), `safe_404_claim_not_mediation`,
`safe_404_claim_not_closed`, `safe_404_order_identity_not_numeric`,
`safe_404_order_identity_conflict`, `safe_404_item_identity_present`,
`safe_404_related_return_present`, `safe_404_seller_respondent_conflict`,
`safe_404_seller_respondent_unproven` (or `safe_404_order_seller_unproven`,
below), `safe_404_return_evidence_present`. A 404 never excludes a claim that
may hold a return DEVOLUCIONES must count.

Deployed at 16:28 UTC, the next retry named
`safe_404_seller_respondent_unproven`: every check before it passed (closed
mediation in the search and the detail, one numeric order, no item, no linked
return), but its `players` did not name the seller as the one respondent.
`players` only proves whose claim it is, so when it names no other respondent
and no other seller, the claim is proven the seller's by its own order instead:
one `GET /orders/{id}` with the seller's token, whose `id` is the claim's order
and whose `seller.id` is the seller. That order is evidence only: it is not a
DEVOLUCIONES row and does not change the read-model or exclusion fingerprints.
It is the third detail call the candidate's budget already allows. Players that
name another respondent or another seller refuse the 404
(`safe_404_seller_respondent_conflict`), and an order that does not prove the
seller refuses it as `safe_404_order_seller_unproven`. A claim whose players
already name the seller reads no order, so certificates already published do
not change. The other checks are unchanged.

#### Initial coverage for a new seller (2026-10-12)

Until 2026-10-12 only the pilot advanced. A new seller's bootstrap claims stage
leaves its coverage control in legacy mode with a stale marker, the onboarding
initializer accepts only a seller with no control at all, and the tail needs a
certificate to extend. The only way in was an operator quota run, which the CLI
allows only for the pilot, followed by `devoluciones_certificate_migrate --run-id
... --write --activate`. A new seller therefore never received DEVOLUCIONES.

Now, when the seller gets the turn with history on link off, the runner admits
its initial window if all of these hold:

- it is in refresh scope (the numeric allowlist, or `all`) **and** eligible by
  `eligible_sellers` (active or `refresh_pending` account plus an active
  ZelerData extension token). The check also applies to a numeric allowlist,
  which otherwise does not check eligibility;
- its control is absent or in legacy mode;
- it has no certificate. A seller with certificates outside certificate mode
  (an operator rollback) is left to the operator and logged as
  `zelerdata.devoluciones_initial_refused` with
  `reason=certificates_need_operator_activation`;
- its marker carries no legacy proof of another run. The bootstrap's stale
  marker is not a proof. A legacy proof from an operator reconciliation or an
  operator quota run is left to the operator's migration
  (`reason=legacy_proof_needs_operator_migration`).

The initial run (`authorization_id=refresh-initial:v1`) is **one 10-day window
starting 90 days before the settled UTC midnight**: the 90 days are what the
bootstrap acquired at link time. Its identity includes the admission day, like
the tail, so a failed or expired window is retried on the next UTC day. It uses
the tail's executor and tolerances: the ordinary runtime gateway, the same
per-window call budgets (104 per pass, 208 per window), the same exact readback
and fingerprints, the pre-v2 row quarantine (L-040) and the exclusion of one
claim whose detail Mercado Libre forbids (L-050). It is admitted, acquired and
finalized in the same invocation. In legacy mode the finalize publishes the
legacy marker for that window. Right after it, and after the run's lease is
released, the worker runs the operator's migration logic itself
(`migrate_certificates(..., run_id=<run>, write=True, activate=True)`): it
publishes a `quota_run` certificate only if the run's completed window and the
current joint facts still match, and switches the control to certificate mode
in the same fenced transaction, or changes nothing. Logs:
`zelerdata.devoluciones_initial_admitted`, then
`zelerdata.devoluciones_coverage_activated` or
`zelerdata.devoluciones_activation_refused` (with `error_type`). A refused
activation is retried on every later turn while the marker still names that
run; if the proof no longer holds, the window is acquired again the next day.

From then on the seller is an ordinary certificate seller: the tail extends
coverage from the end of the initial window one 10-day window per turn up to
the settled midnight (eight more windows), then once a day. The reader serves
each range as soon as its windows are certified. Only the first window is an
initial run, so every window keeps its own proof: a failure costs one window,
not the whole range, and no single run has to outlive its expiry (a 9-window
run expires 8,230 s after admission, and nine turns take longer than that).

Initial coverage never runs with history on link on (the pilot owns its runs
then, as for the tail). Once the seller is in certificate mode, its year of
DEVOLUCIONES goes back from the initial window (see "Twelve months of
history").
`ZELERDATA_DEVOLUCIONES_INITIAL_COVERAGE_ENABLED=false` is the emergency switch;
sellers already in certificate mode keep their tail.

How long it takes: one window per turn. With the pilot alone and one new
seller, the new seller gets a window on almost every cycle, so 9 windows take
about 9 cycles, each one interval plus the cycle (about 15 + 2 to 5 minutes):
roughly two and a half to three hours. With K sellers catching up at once, each
gets a window every K cycles, so about K times longer. The pilot's daily tail
waits at most one round.

How to verify (read-only, inside `sheets-worker`):

```bash
.venv/bin/python -m infra.operations.zelerdata_read_model_status \
  --seller-id <new seller> --devoluciones-coverage --confirm-approved-runtime
```

Expect `mode=active`, `compatible=true`, intervals from 90 days before the
admission day's settled midnight, with no `unacquired_gaps`, growing by 10 days
per turn until they reach the settled midnight. In the worker log, expect one
`zelerdata.devoluciones_initial_admitted` and one
`zelerdata.devoluciones_coverage_activated` for the seller, then
`zelerdata.devoluciones_tail_admitted` for each later window.

#### Intraday coverage of the day in progress (2026-10-12)

The tail certifies closed UTC days only. A range that ends today
(`fecha_final` = today, read up to tomorrow 00:00) was therefore
`DATA_UNAVAILABLE` all day: on 12 October at 14:29 UTC the pilot served seven
days ending today 00:00, but not seven days ending now or tomorrow 00:00.

With history on link off, every certificate seller now also gets an intraday
pass, only with windows the tail and initial coverage leave:

- **Interval.** `[today 00:00, cut)` UTC. The cut is the last whole hour at
  least 30 minutes old (`INTRADAY_SETTLE`), so a claim created just before it
  has time to appear in the search. The first cut of a day (01:00) is
  acquired from 01:30; until then the previous day's 23:00 cut applies.
- **Identity and cadence.** One run per seller and cut
  (`authorization_id=refresh-intraday:v1`, the cut in its identity): at most
  one pass per hour, after restarts and across workers. A completed, failed or
  expired cut is not retried; the next cut, an hour later, re-acquires the
  whole day so far. Hourly matches what the loop can give: a cycle lasts the
  15-minute interval plus 2 to 5 minutes, about three cycles an hour.
- **Priority.** Intraday passes take turns in their own rotation and get the
  cycle's window only when no seller had a run, a tail or an initial window
  due. The cap stays one window per cycle for all sellers. A seller whose
  closed days stop before yesterday (still catching up) gets no pass: its cut
  would not connect to its certified days.
- **Same executor and proofs as the tail.** Two inventory passes per
  snapshot, full revalidation, exact readback, the pre-v2 quarantine (L-040)
  and the exclusion of one forbidden claim detail (L-050). The run is
  finalized in the same invocation and publishes an ordinary `quota_run`
  certificate for `[today 00:00, cut)`. No validator, index or schema
  changes.
- **Replacement without gaps.** Publishing any quota certificate removes, in
  the same transaction, every intraday certificate whose interval it covers
  entirely: the next cut removes the previous one, and the tail for a day
  removes that day's last cut. The replacement covers what it removes, so
  `select_covering_proofs` never meets a gap or an orphaned cut. Each open day
  keeps at most one cut, so a seller has one (two between midnight and the
  tail), renewed like any certificate. Runs and windows stay.
- **Invalidation.** A cut is an ordinary certificate: a claim or order
  mutation inside it carries it over or invalidates it (`claim_mutation`,
  `order_mutation`) exactly like any other certificate. A stale cut stays
  unreadable until the next cut replaces it, so after an unprovable change a
  range ending today is unavailable for up to about an hour.

**Reader.** A fully certified range is served as before. Otherwise a
certificate seller's range is served up to the end of its certified coverage
when both hold:

- it ends at most at tomorrow 00:00 UTC, the end of the day in progress, and
- that coverage, contiguous from `fecha_inicio`, reaches a cut at most three
  hours old (`DEVOLUCIONES_INTRADAY_MAX_CUT_AGE`). A cut normally ages 30 to
  90 minutes; three hours allows one missed pass and the cycle's delays.

The sheet's headers and rows do not change. The API response says where the
data stops:

```json
"coverage": {"exact": true, "scope": "certified_until_cut",
  "date_from": "2026-10-06T00:00:00+00:00", "date_to": "2026-10-13T00:00:00+00:00",
  "covered_until": "2026-10-12T14:00:00+00:00", "reason": "current_day_in_progress"}
```

A range ending after tomorrow 00:00, a cut older than three hours, or nothing
certified at `fecha_inicio` stays `DATA_UNAVAILABLE`. Shortly after midnight,
before the tail closes the previous day, a range ending that day is served up
to its 23:00 cut.

**Cost, from the code.** A pass lists the day's claims twice for the snapshot
and twice for the revalidation, and fetches the claim detail and v2 returns of
every listed claim that is not a closed cancellation, plus the order of each
return: `2 × (2 × ⌈I/100⌉ + 2 × H + U)` calls, with at least one search page,
`I` claims listed today, `H` of them hydrated and `U` distinct orders with a
return. A pass with no claims costs 4 calls; with one return, 10 (asserted in
`tests/integration/test_devoluciones_intraday.py`). A day has 23 cuts, so a
seller without claims costs 92 calls a day, and each return adds 6 calls to
every later cut: about 160 to 180 a day for the pilot's roughly one listed
claim a day.
The tail's per-window limits (104 per pass, 208 per window) still bound any
pass, and return reads keep their 1.75 s spacing.

**Capacity.** About three windows an hour serve about three sellers' hourly
cuts. With N certificate sellers each gets a cut about every N/3 hours; past
about six sellers a cut can pass three hours and ranges ending today are
unavailable for part of the day. A seller catching up, or the nightly tails,
pause intraday passes for those cycles. Revisit `devoluciones_windows_per_cycle`
only if `elapsed_seconds` stays well under the interval.

**Known limit.** The executor fails a window with a listed claim it cannot
classify, such as a cancellation that is still open (`cancel_purchase`, not
`closed`): `ClaimInventoryError`. The tail meets such a claim once a day; an
intraday pass sees claims within hours of their creation, so every cut can
fail while one is open, and a range ending today becomes unavailable three
hours after the last good cut.

`ZELERDATA_DEVOLUCIONES_INTRADAY_ENABLED=false` is the emergency switch: no new
cut is acquired, the last one is served while it is under three hours old,
and the tail replaces it at night. Intraday passes also need
`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=true` and history on link off.

Logs: `zelerdata.devoluciones_intraday_admitted` (seller, run, start and
cut) once per cut; a window failure as the tail's
`zelerdata.devoluciones_tail_failed` with that run's id; an admission or lease
failure as `zelerdata.devoluciones_intraday_failed` with `error_type`.
`zelerdata.refresh_cycle_completed` counts the window in
`devoluciones_windows`.

How to verify (read-only, inside `sheets-worker`): the coverage status of
"Initial coverage for a new seller" lists, besides closed days, one interval
ending at the latest cut (`date_to` on a whole hour of today, `readable`).
Between midnight and the tail, `unacquired_gaps` shows the previous day's last
hour; the tail's certificate removes it.

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

## Twelve months of history (2026-10-12)

Until 2026-10-12 a new seller had what its bootstrap acquired at link time
(orders and claims for 90 days) plus what refresh added from then on. Order
and question ranges older than the refresh windows, and DEVOLUCIONES older
than its initial 90 days, stayed `DATA_UNAVAILABLE`. The refresh loop now walks
each source backwards from the start of its proven coverage until that coverage
reaches a full year, with no operator step. It plans existing recovery work and
DEVOLUCIONES windows; it never calls Mercado Libre itself.

**Who.** Every eligible seller (`eligible_sellers`, checked for a numeric
allowlist too), each source judged on its own proofs. Until 2026-10-13 a seller
with a `sheets_history_backfill_plans` document (the paused history pilot,
82453304) was excluded whole; by the user's decision of 2026-10-13 it walks
like any other seller (see "The pilot" below). Its legacy plan, runs and flags
are never read, edited or resumed by the walk.

**When a seller has its year.** The target is UTC midnight 366 days back
(`year_history_target`), so any "same day last year" range is inside, leap
days included. A source is covered once its proven coverage reaches the
target: for orders and questions, the most recent block of the freshness
marker (its own interval and its retained proofs, merged where they touch)
starts at or before it; for DEVOLUCIONES, the oldest certificate of the
current epoch starts at or before it. The target moves forward a day at a time,
so a covered seller stays covered and is logged once as
`zelerdata.year_history_covered`. Progress is the proof itself: nothing else is
stored, and a restart or a second worker computes the same next portion.

### Orders and questions

- **One portion per cycle for the whole fleet**, after the DEVOLUCIONES pass
  (`YearHistoryPlanner`, `zelerdata.year_history_planned`). Sellers and the two
  sources take turns, starting after the last pair served (in memory; after a
  restart the turn starts again from the first seller).
- **Priority.** Nothing is admitted while another year-history portion is
  running or ready, or while any seller's renewal pass (or a whole-sheet buybox
  or item pass) is pending or running. A portion runs in the `ranges` lane, at
  least a quarter of the pacer while every lane is busy. Sweeps, renewal,
  formula recovery and the fast order sweep keep their lanes and priority.
- **The portion.** It ends at the start of the most recent proven block,
  rounded up to the hour (order search has hour precision), and starts at most
  `MAX_PORTION` earlier (30 days for orders, 90 for questions), never before
  the target, and never before the hour in which an older proven block below
  a gap ends: an older proof (the pilot's retained history, say) is joined,
  not read again. Its span holds about 120 orders or 100 questions at the density
  of the rows already stored around that edge, so it finishes inside the
  240-second job deadline at 45 requests per minute (180 calls). A
  `YearHistoryRecoveryRequest` has its own key (no coalescing with a formula
  range or a sweep) and `year_history: true` on the job.
- **Publication.** The worker acquires the portion like any range (search,
  details, revalidation of stored identities) and adds it to the marker's
  `retained_intervals` in the same transaction as the rows and the job
  completion. The marker's own interval and lease (the live claim the sweeps
  renew) do not change, and the question sweeps keep re-reading only their own
  live union, never the year. Question sweeps now carry retained proofs over
  like order sweeps; without retained proofs (the pilot) their marker is
  written exactly as before.
- **Failures.** A 429, 5xx, job deadline or a source answer that cannot be
  proven whole (`source_incomplete`: a row whose detail fails a check, a list
  that changed during the scan, a lost race) uses an attempt (retried after
  30 s and 60 s). Unlike ordinary range work it is neither deferred without an
  attempt nor failed at once, because a portion too large for the deadline, or
  holding a row the source never gives whole, would restart forever. After
  three attempts the portion fails and the next one at the same edge has half
  the span; once its newer half is proven, the next portion is the rest of the
  failed one, so the walk narrows down to the hour the source refuses (one
  failed portion per halving: about 8 for a week, 12 for 90 days) instead of
  failing whole spans again. A one-hour portion that keeps failing is retried
  every 6 hours (three attempts each time): the edge stays right above it,
  not covered, and `--year-history` names it under `retrying`. Only a portion
  closed because the seller was not eligible is retried whole. The worker logs
  each refused attempt as `zelerdata.year_history_portion_incomplete` with the
  check that refused it (`check` as `module.function`, and `line`; no
  identities or source text). A portion waiting for a retry holds no other
  seller, and nothing already acquired is withdrawn.
- **Fixed on 2026-10-13.** `source_incomplete` used to fail a portion at its
  first attempt, and the planner reopened the same portion whole after every
  15-minute cooldown with its attempts back at zero: the pilot's last question
  portion (2025-10-12 to 10-18 23:00) was planned 53 times in a day, a scan of
  the seller's questions each time, and never halved.
- **Shipments** are not acquired ahead: the readers serve a missing shipment
  cost or address as `NA` and request it, as for any range (three calls per
  shipment: `/shipments/{id}/orders`, `/shipments/{id}`, `/shipments/{id}/costs`).

### DEVOLUCIONES

Once certificate coverage is active (the initial window of L-053), the source
pass gives the seller one 10-day window ending at its oldest certificate
(`authorization_id=refresh-year-history:v1`), back to the target; the last one
is shorter. It uses the tail's executor, tolerances and same-invocation
finalize, and publishes an ordinary `quota_run` certificate that touches the
existing coverage, so `select_covering_proofs` sees one contiguous run of
certificates. Year windows take turns in their own rotation and get the
cycle's window only when no seller had an operator run, a tail, an initial
window or an intraday cut due: the cap stays one window per cycle for all
sellers. The regular pass never picks up a year-history run. Logs:
`zelerdata.devoluciones_year_history_admitted` per window,
`zelerdata.devoluciones_year_history_failed` for an admission or lease failure,
and the tail's `zelerdata.devoluciones_tail_failed` for a window failure.

**A failed or abandoned window** (its run `failed`, or still `active` past its
deadline with its window `prepared` after a restart) gets a new run of the same
window in a later free cycle: 15 minutes after the last run ended, then 1 hour,
then every 6 hours (`YEAR_HISTORY_RETRY_AFTER`; the run's `attempt` is in its
identity, counted over every run of the window that ends at that certificate).
A window the source keeps refusing costs at most four windows a day, and waiting
leaves the cycle's window to nothing. A run still in time is resumed, after a
restart too. Only a completed run publishes a certificate, so a replacement
never duplicates one; the abandoned run and its prepared window are left as
they are. `--year-history` names the window under `retrying` (with `runs`).
Until 2026-10-13 only the admission day was in the identity, so the pilot's
window of 2026-05-12 to 05-22, failed at 03:06, matched the day's run and held
its year for the rest of the UTC day (no admission in 16 hours).

A year is about 37 certificates per seller (plus one or two intraday cuts),
each valid for 30 minutes. One renewal batch handles at most 20 within 30
seconds, so a full batch is now followed by another, up to three per seller and
cycle (`RENEWAL_BATCHES_PER_CYCLE`, 60 certificates). The pilot's partial batch
is unchanged. `renewal_capacity` in the coverage status counts the three
batches.

### Cost and duration, from the code

For a pilot-sized new seller (about 6,600 orders, 300 questions and 50 claims
a year, 2,000 shipments):

| Source | What the walk acquires | Calls |
| --- | --- | --- |
| Orders | Up to 359 days before the daily sweep's 7 days (276 if the weekly 90-day sweep completed): about 6,500 orders in about 55 portions of about 120. Each order is one detail; each portion has 3 search pages; an order without a shipment ID adds one relation call | about 6,700 to 6,800 |
| Questions | About 300 questions in 4 or 5 portions of up to 90 days. Each portion scans the seller's whole question list (50 per page; about 12 pages for 600 questions) plus one detail per question in range | about 350 |
| DEVOLUCIONES | 28 windows (276 days in 10-day windows). Per window `2 × (2 × ⌈I/100⌉ + 2 × H + U)`: about 12 with the seller's 1.4 claims per window, at least 4 | about 330 |
| Shipments | Not acquired ahead; on demand when a reader asks | up to about 6,000 if the whole year of ORDENES is read |

That is about 7,400 calls up front, against about 33 calls per minute that the
same seller's sweeps and renewal cost in steady state (about 47,500 a day).
One portion every cycle averages about 7 calls per minute (4 % of the pacer)
and none during renewal passes, so the pilot's renewal is not displaced: a
portion that started just before a slot runs alongside it for at most 240
seconds.

Duration: about 60 portions at one per cycle (the 900-second interval plus a
2 to 5 minute cycle) take 17 to 20 hours, plus the hours held by renewal passes
(about 1.2 hours per seller and slot, two slots a day: about 5 hours a day with
the pilot and the new seller), so **about a day**. DEVOLUCIONES runs in parallel
in the source pass: after the initial window and the tail's catch-up (about 3
hours), the cycles left by two sellers' intraday cuts give about one year
window an hour, so 28 windows take **about a day**. K sellers walking at once
share one portion per cycle and take about K times longer. Past about three
certificate sellers, intraday cuts use every window and year windows wait
(the same limit as the intraday capacity above); revisit
`devoluciones_windows_per_cycle` then.

**What a failure costs (2026-10-13).** The per-cycle caps are unchanged: at
most one portion admitted and one DEVOLUCIONES window run per cycle for the
fleet. What changed is how many cycles a failure takes, so the worst case per
cycle is:

- **A portion that keeps failing:** at most three attempts in a cycle (the
  second and third 30 and 60 seconds after the first), each bounded by the
  240-second job deadline at the ranges lane's pace and sized to about 130
  calls (120 orders or 100 questions plus search pages; at most about 300 at a
  quarter of a 300-per-minute pacer). So about 390 calls in a cycle, at most
  about 900 if every attempt runs to its deadline, as for a 429 before.
  Narrowing to the refused hour takes one failed portion per halving (about 8
  for a week, 12 for 90 days) plus as many proven halves.
  The stuck hour then costs three attempts every 6 hours; for the pilot each
  attempt is a scan of its questions (`⌈T/50⌉`, 6 to 12 pages) plus a detail
  or two, so about 85 to 160 calls a day, against about 1,000 to 1,450 a day
  that reopening the week-long portion every cycle cost.
- **A DEVOLUCIONES window that keeps failing:** the cycle's one window, only
  when nothing more recent wants it, at most 4 times a day after the first
  hours. Per attempt `2 × (2 × ⌈I/100⌉ + 2 × H + U)`: 4 to 46 for the pilot, at
  most 208 (the tail's limit), so at most about 830 calls a day and usually
  under 200. Before, one attempt a day and no year window in between.

### The pilot (2026-10-13)

Production on 2026-10-13 (read-only, `--year-history`): orders covered (edge
2025-09-24, from the old pilot's retained proofs), questions from 2026-07-14
and DEVOLUCIONES from 2026-06-01 (the oldest certificate of its current
epoch). So the walk asks the pilot for **no order portion**, question portions
from the July edge back to the target, and DEVOLUCIONES windows from the June
certificate back. How it fits the old pilot's proofs:

- **Orders.** The completed interval proofs of L-022 are already retained
  intervals of the marker, so the planner reads the pilot as covered. If a
  sweep ever left a gap under its live block, the portion would fill only the
  gap, down to the end of the older proof.
- **Questions.** The old pilot's twelve-month question scan never published a
  proof (its edge stayed in July); the portions add retained intervals like
  any seller's. If that scan were ever resumed, its publication withdraws and
  re-merges its own interval with the marker's retained proofs, so nothing
  contradicts; it would only read again.
- **DEVOLUCIONES.** Each window ends exactly at the oldest certificate and
  publishes an ordinary `quota_run` certificate, so `select_covering_proofs`
  sees one run without overlap or gap. The plan's certificates and runs are not
  touched (asserted). Older claims stored locally since 2025-04-30 carry no
  certificate and are reacquired in their windows with the tail's tolerances.

Cost, from the code, with the pilot's stored density (273 questions since
2025-09-26, 56 claims since 2025-04-30), from a 2026-10-13 deployment (target
2025-10-12):

| Source | What the walk acquires | Calls |
| --- | --- | --- |
| Orders | Nothing: covered | 0 |
| Questions | 275 days in 4 portions (90-day cap: about 150 questions per 180 days around the edge). Each portion scans the whole list, `⌈T/50⌉` pages for the seller's `T` listed questions (6 to 12 for 300 to 600), plus one detail per question in range (about 200) | about 225 to 250 |
| DEVOLUCIONES | 232 days in 24 windows (23 of 10 days, one of 2). Per window `2 × (2 × ⌈I/100⌉ + 2 × H + U)`: 4 without claims, 10 with one return. With one listed claim per window (stored density) about 10; with one a day (the intraday estimate) about 46 | about 240 to 1,100 (at most 4,992 under the tail's 208-per-window limit) |

That is about 500 to 1,350 calls in all, against about 12,800 gateway calls a
day in production. Duration: the 4 question portions take 4 turns of the
fleet's one portion per cycle (about 1 to 2 hours plus renewal passes, longer
if other sellers are walking). The 24 DEVOLUCIONES windows get the cycle's
window only when no tail, initial window or intraday cut wants it, about one
an hour, so **about a day**, longer when several sellers walk at once. A year
of certificates adds 24 to the pilot's; check that
`--devoluciones-coverage` still reads `sufficient` (three renewal batches of 20
per cycle). Renewal keeps its priority as for any seller: no portion is
admitted while a renewal pass runs.

`tests/integration/test_year_history_new_sellers.py`
(`test_the_paused_pilot_walks_questions_and_devoluciones_once_across_a_restart`)
reproduces these edges and asserts the counts above: one scan page per portion
plus one detail per question in range, four search pages per window plus six
reads for the one old return. It also keeps the old pilot's pending question
scan (`policy_authority` history-on-link-v1) in the queue and asserts it is
left exactly as it was: the walk reads only `year_history` jobs, the ordinary
queue never claims another authority's job, and a portion's key never
coalesces with it.

**Two stalls seen on 2026-10-13 (read-only, 19:30 UTC), fixed the same day.**
Questions walked three portions to 2025-10-18 23:00 and then the last one
(2025-10-12 to 10-18 23:00) failed `source_incomplete` at every attempt, reopened
whole after each cooldown. DEVOLUCIONES walked one window to 2026-05-22 and then
the window of 2026-05-12 to 05-22 failed at 03:06 with its window `prepared`; no
year window was admitted for 16 hours. Neither needs an operator step after the
fix: the failed question portion is the latest at its edge, so the planner
halves it and narrows down to the refused hour, and the failed run is
replaced in the next free cycle (its 15-minute delay has long passed).
`tests/integration/test_year_history_new_sellers.py` reproduces both
(`test_a_failed_year_window_left_prepared_is_replaced_and_the_walk_goes_on`,
`test_a_question_portion_the_source_cannot_complete_stops_at_an_honest_edge`).
The questions source counts as covered once the target passes its edge, at
the latest on 2026-10-20 for the 2025-10-18 23:00 edge.

**The 2026-05-12 window (2026-10-14).** It kept failing after the fix above:
three runs, the last at 00:06 UTC with `return_subtype_required` (see "A return
without a subtype"). Once the proof accepts it, the next free cycle after the
6-hour retry delay replaces it and the walk continues from 2026-05-12. No
operator step: failed runs and prepared windows stay as they are. Skipping a
window that can never be proven, leaving a declared gap, is not done.
Certificates must join without a gap for `select_covering_proofs`, so every
range across the gap, and the year itself, would stay unavailable. A stuck
window costs at most four attempts a day and now names its check, so the
check gets fixed instead.

### Switch and verification

`ZELERDATA_YEAR_HISTORY_ENABLED` is on by default; `false` is the emergency
switch: no portion is planned, no year window is admitted, and the recovery
worker leaves queued portions unclaimed until it is turned back on. Like the
tail it only runs with history on link off, and DEVOLUCIONES windows also need
`ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED=true`. `zelerdata.refresh_cycle_completed`
reports `year_history_portions` (0 or 1).

How to verify (read-only, inside `sheets-worker`):

```bash
.venv/bin/python -m infra.operations.zelerdata_read_model_status \
  --seller-id <seller> --year-history --readiness --confirm-approved-runtime
```

It prints the target and, per source (`orders`, `questions`,
`devoluciones`), where proven coverage starts (`edge`) and whether it reaches
the target, plus the seller's year-history portions by state; no identities.
`ready` means every source is covered; the pilot is no longer `excluded`.
A source held at its edge also shows `retrying`: for orders and questions the
failed (or waiting) portion at the edge with its `failure_reason` and
`attempts`, for DEVOLUCIONES the next window with the `state` of its latest run
(`failed`, or `expired` when abandoned), its `failure_reason` when the run
kept one, and how many `runs` it has had. For a
new seller, expect the `orders` and `questions` edges to move back about one
portion per cycle and DEVOLUCIONES 10 days per year window, `portions` mostly
`completed` with at most one `pending` or `running`, and `failed` only with a
later, narrower retry. A `retrying` that stays on a one-hour portion, or on one
window with several `runs`, is a row the source does not give whole: the
worker log names the check (`zelerdata.year_history_portion_incomplete`, or
`zelerdata.devoluciones_tail_failed` with its `failure_reason`). Also:

- `zelerdata_read_model_status --devoluciones-coverage`: no `unacquired_gaps`,
  and the capacity reads `sufficient` with a year of certificates.
- In the worker log: `zelerdata.year_history_planned` at most once per cycle,
  `zelerdata.year_history_covered` once per source when done (for the pilot,
  `orders` at once). `zelerdata.year_history_excluded` no longer appears.

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
| `ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED` | on (off with BULK) | Renewal of buybox, quality and costs, for named sellers and in `all` mode. `false` is the emergency switch. Mutually exclusive with BULK when set to `true`. |
| `ZELERDATA_RENEWAL_REFRESH_HOURS` | `12` | Renewal slot length, at most 12. |
| `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED` | `false` | DEVOLUCIONES source work from this loop, one window per cycle for all sellers: advance an already-authorized run; with history on link off, also admit the ordinary daily tail and the initial window of a new seller. |
| `ZELERDATA_DEVOLUCIONES_INITIAL_COVERAGE_ENABLED` | on | Initial window and certificate activation for an eligible seller without coverage. `false` is the emergency switch. |
| `ZELERDATA_DEVOLUCIONES_INTRADAY_ENABLED` | on | Hourly cut of the day in progress for every certificate seller, only with windows the tail and initial coverage leave. `false` is the emergency switch. |
| `ZELERDATA_YEAR_HISTORY_ENABLED` | on | Twelve months of orders, questions and DEVOLUCIONES for every eligible seller, the paused pilot included since 2026-10-13: one backward portion per cycle for the fleet, and one DEVOLUCIONES window only when nothing more recent wants it. Only with history on link off. `false` is the emergency switch and leaves queued portions unclaimed. |
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
  forward tail per day from existing certified coverage, one initial window
  for an eligible seller without coverage, one cut per hour of the day in
  progress, and one window back towards a year with what those leave, at most
  one window per cycle in total. Certificate mode is
  activated only from a completed window's proof.
  The legacy systemd timer is superseded.
- The DLQ archive stays evidence-based: a message is only removed when a
  reconciled marker already covers its window (questions only) or it is past
  retention, the sanitized record is written before the ack, and everything
  else is requeued untouched. The per-cycle pass does not read the platform's
  read stamps, so `resource_reread` belongs to the operator runtime in
  [`docs/ops/sheets-dlq-reconciliation.md`](../ops/sheets-dlq-reconciliation.md).
  A misconfigured enable fails at build time instead of silently skipping the
  pass.

## Verification

```bash
uv run pytest modules/sheets/tests/test_zelerdata_refresh.py \
  modules/sheets/tests/test_zelerdata_sweep_status.py \
  modules/sheets/tests/test_zelerdata_renewal_sweep.py \
  modules/sheets/tests/test_zelerdata_all_sellers_sweeps.py \
  modules/sheets/tests/test_zelerdata_recovery_pacing.py \
  modules/sheets/tests/test_year_history.py \
  modules/sheets/tests/test_devoluciones_year_history.py \
  tests/integration/test_year_history_new_sellers.py \
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

- **The paused 12-month history pilot.** The legacy backfill
  (`build_pilot_history_backfill`) creates a `sheets_history_backfill_plans`
  document and up to twelve months of orders and questions for every seller it
  sees, so `all` mode does not wire it. `ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED`,
  `ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED` and
  `ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED` require an explicit numeric
  `ZELERDATA_FORMULA_RECOVERY_SELLERS`. With `all`, the worker fails at startup
  and names the flag. History on link (`ZELERDATA_HISTORY_ON_LINK_*`) keeps its
  own allowlist and is not affected. A seller with such a plan, the pilot, is
  also left out of the new year history and keeps exactly what it has.
- **Anything older than a year.** Since 2026-10-12 every eligible seller
  without a legacy plan gets twelve months of orders, questions and
  DEVOLUCIONES on its own: the bootstrap's 90 days, the initial DEVOLUCIONES
  window and the daily tail, then one backward portion or window at a time
  (see "Twelve months of history"). Ranges that start more than 366 days back
  stay unavailable. Shipments are acquired when a reader asks for them, and
  RETIROS starts at its first observed notification by design.
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

Scheduled refresh plans orders and questions for every seller: the last hour
every 15 minutes, 7 days once a day, and 90 days once a week, a few requests
per seller and cycle. The spaced inventory and catalog sweeps and the renewal
work in `all` mode exactly as for the pilot, for every eligible seller:

- **Inventory and catalog products.** Each seller has its own pass and its own
  spacing (`sweep_status`). The lanes claim one 20-ID chunk (or one discovery)
  per job and send the job to the back of the queue, so passes of several
  sellers interleave chunk by chunk: a large seller's pass never holds a small
  seller's until it ends. Inventory waits only for the seller's own buybox pass.
- **Renewal.** One seller at a time, sellers that missed the previous slot
  first (see "Several sellers take turns").
- `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED` stays off: it re-plans every
  model every cycle (L-021).
- **Year history.** One backward portion per cycle for the whole fleet, in the
  `ranges` lane, none while a renewal pass is in flight (see "Twelve months
  of history"). It adds about 7 calls per minute on average while a seller
  walks back, nothing in steady state.

#### Capacity for N sellers of the pilot's size

From the code, not from production. A pilot-sized seller has about 1,900
publications, 934 catalog listings and 875 catalog products. Per seller, the
inventory pass costs 114 calls every 10 minutes (19 discovery pages of 100,
95 batches of 20), about 11.4 per minute; the catalog product pass 875 calls
every 3 hours plus the pass, about 3.6 per minute; renewal 8,000 to 16,400
calls per 12-hour slot (12,800 typical), about 17.8 per minute averaged over
the day. That is about 33 calls per minute per seller. The pacer gives 180
per minute to the whole worker. While a renewal pass fills the `ids` lane, the
inventory lane gets one grant in three (60 per minute) or one in four (45)
when `ranges` is busy too. Reader limits: inventory enumeration and base rows
15 minutes, catalog products 4 hours, buybox, quality and costs 24 hours.

| N | Average load (typical) | Inventory age | Renewal pass, all sellers per slot | Buybox/quality/costs age at renewal | Catalog product age |
| --- | --- | --- | --- | --- | --- |
| 1 | 33/min (18 %) | about 10.5 min | 1.2 h (0.8 to 1.6), 1.3 h | about 13 h | up to about 3.8 h during a renewal pass, about 3.1 h otherwise |
| 5 | 166/min (92 %; 106 % with the heaviest renewals) | about 10.5 min: the four sellers not renewing need 46/min of the lane's 60 | 1.9 h (1.2 to 2.4), 10 h (12.6 h with the heaviest renewals, which then rotate into the next slot) | about 14 to 15 h | about 4.2 h when the catalog pass overlaps a renewal: brief expiries |
| 15 | 500/min (276 %) | about 27 min per round: expired | 3.5 h, 55 h | far over 24 h: expired most of the day | about 4.8 h: expired |

Where 180 per minute stops being enough: the average load passes 100 % at
N = 6 (110 %). At N = 5 the sweeps fit with almost nothing left for
formula-triggered recovery, so on-demand fills slow down, and catalog product
passes that overlap a renewal pass can let products expire for a few minutes
(`ZELERDATA_CATALOG_REFRESH_HOURS=2` avoids that for about 50 % more catalog
calls). Up to N = 4 (74 %) every datum stays inside its limit with room for
on-demand work. Beyond that, renewal rotates past 24 hours from N = 7 to 9 and
inventory passes 15 minutes from N = 9. A seller of a different size counts in
proportion to its publications (the dry run reports `eligible_inventory`).
The next options are to raise `ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE` (at
most 600; the gateway limit of 600 is per seller, so a global 360 leaves each
seller far below it; check the Mercado Libre application limits first) or to
add lanes. Each lane runs one job at a time, so a lane is also bounded by
request latency, which this document has not measured.

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
| DEVOLUCIONES renewal | A few Mongo reads per seller; certificate sellers renew up to three batches of 20 due certificates, each within 30 s (a year is about 40) | N, in milliseconds |
| DEVOLUCIONES source pass | At most one window per cycle for all sellers together (up to about 3 minutes), plus a few Mongo reads for each seller offered the turn before it | Constant: one window, whatever N is |
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
  reservation. See "Capacity for N sellers of the pilot's size".
- Renewal passes run one seller at a time, so a renewal never stretches over
  the fleet; the planner reads the turn by slot key once per cycle.
- Memory does not grow with N: the warmer and each lane handle one seller at a
  time, so the peak follows the largest seller's catalog. The worker also hosts
  consumers and three lanes in one process on a 3.9 GB VM that Mongo shares.
  Watch `docker stats` for `sheets-worker` during the first warm cycles; this
  document has no production measurement of it.
- DEVOLUCIONES: the source pass adds at most one window (about 3 minutes) to
  `D`, whatever N is. With the warm budget (450 s plus one warm) a cycle stays
  near 800 s at most, under the 900 s interval. Sellers take turns, so N
  sellers in steady state need N windows a day out of about 80 cycles, and K
  sellers catching up at once (9 windows each) share the slot, about K times
  slower each. Intraday cuts use the cycles left over: 23 a day per seller,
  so about three sellers get every hourly cut. Year windows use what intraday
  leaves, so they progress only while fewer than about three certificate
  sellers need a cut each hour. Certificate renewal takes up to three batches
  of 20 per seller and cycle (a year is about 40 certificates), a few seconds
  of local reads at most. Revisit the cap (`devoluciones_windows_per_cycle` on the
  supervisor) only if `D` stays far under the interval and many sellers wait.

Revisit capacity when:

- `elapsed_seconds` exceeds about 300 s, or `warm_deferred` is above 0 for
  several cycles in a row,
- pending `ranges` jobs wait longer than one interval,
- a seller's renewal starts more than about 10 hours after its slot, or its
  inventory pass ends more than 15 minutes after its discovery, or
- freshness alarms fire for sellers whose refresh is healthy.

Claims are already fair across sellers (one chunk per claim, oldest first),
so the first option is to raise the reservation. The reservation is global,
so even 300 stays under each seller's 600 gateway quota. Check the Mercado
Libre application limits before raising it.

### Production activation

Production changes run only from the main session, after this change is
merged and with explicit authorization. Switch to `all` only when a second
seller exists: today the dry run finds one eligible seller, the pilot.

1. **Image.** Build and deploy `sheets-worker` from `main` without changing
   any variable. With the numeric allowlist the pilot is served as before
   (renewal is now planned once per cycle, with the same slots and passes).
   Verify health and the pilot's next renewal slot. This change does not touch
   the `sheets-api` path; any `sheets-api` image from `ef0308b` on accepts
   `all`.
2. **Read-only dry run** inside `sheets-worker` (sanitized: counts only, no
   seller IDs, nicknames or tokens), once for the pilot and once for the new
   seller:

   ```bash
   .venv/bin/python -m infra.operations.zelerdata_all_sellers_dry_run \
     --seller-id 82453304
   .venv/bin/python -m infra.operations.zelerdata_all_sellers_dry_run \
     --seller-id <new seller>
   ```

   It prints how many sellers would be eligible, how many are excluded for
   each reason (`account_paused`, `no_extension_token`,
   `extension_token_expired`, ...), the active recovery jobs that belong to
   ineligible sellers, the size of the eligible inventory
   (`eligible_inventory`: sellers enumerated, publications, largest seller),
   the current scope and flag values (kind and on/off, not IDs), and whether
   the requested seller is eligible. Continue only if:
   - both sellers are eligible (otherwise `all` would not serve them),
   - `matches_runtime_rule` is `true`,
   - `eligible_inventory.publications` fits the capacity table: about 1,900
     publications per pilot-sized seller; up to about 4 of them leave room for
     on-demand recovery, 5 fill the pacer to about 92 %. A seller whose
     inventory was never enumerated is not counted yet: add its publications
     from Mercado Libre.
3. **Preflight of flags** in the same output:
   `ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED`,
   `ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED` and
   `ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED` must read `false` (they need
   named sellers and fail startup in `all`), and
   `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED` must read `false`. Leave the
   inventory, catalog and renewal sweeps as the pilot has them: in `all` they
   serve every eligible seller.
4. **Worker first.** Set `ZELERDATA_FORMULA_RECOVERY_SELLERS=all` and
   `ZELERDATA_REFRESH_SELLERS=all` together (refresh requires recovery to be
   `all`, or startup fails). Leave every other variable as it is. Restart only
   `sheets-worker`. Verify:
   - the `formula_recovery` and `zelerdata_refresh` components,
   - delivery progress (L-027),
   - `zelerdata.refresh_cycle_completed` with `sellers` equal to the dry-run
     count, `warm_deferred` and `elapsed_seconds` (target: under 300 s; the
     cycle that follows the restart is the first full measurement),
   - for the new seller: an inventory pass about every 10 minutes, a catalog
     product pass, and `orders`/`questions` jobs reaching `completed`,
   - `docker stats` for `sheets-worker` memory over the first warm cycles.
5. **API second.** Set `ZELERDATA_FORMULA_RECOVERY_SELLERS=all` and restart
   only `sheets-api`. Verify `/health` and a `formula_recovery_admission` with
   outcome `admitted` for a seller other than the pilot.
6. **First renewal slot with two sellers** (01:00 or 13:00 UTC, or at once
   after the restart). `zelerdata.refresh_renewal_planned` appears for one
   seller; the other seller's appears only after the first seller's renewal
   jobs complete, with the same `slot`. Each seller's inventory pauses only
   during its own buybox pass. Afterwards `CATALOGO`, `CALIDAD` and
   `CALCULADORA` of the new seller fill without opening the sheet. Watch
   `docker stats` during the passes. `ZELERDATA_SCHEDULED_RENEWAL_REFRESH_ENABLED=false`,
   and the inventory and catalog flags, stay the emergency switches; each
   applies to every seller, the pilot included.

7. **DEVOLUCIONES for the new seller** (no operator step). On its first turn
   after the switch, the worker logs `zelerdata.devoluciones_initial_admitted`
   and `zelerdata.devoluciones_coverage_activated` for it, then one
   `zelerdata.devoluciones_tail_admitted` per later turn. Check its coverage
   with `zelerdata_read_model_status --devoluciones-coverage` (see "Initial
   coverage for a new seller"): about three hours after the first turn it
   reaches the settled midnight. The pilot keeps its daily tail;
   `devoluciones_windows` in `zelerdata.refresh_cycle_completed` stays at 0 or
   1, and `elapsed_seconds` grows by at most one window.

8. **Twelve months for the new seller** (no operator step). From the cycle
   after the switch, `zelerdata.year_history_planned` appears at most once per
   cycle, for the new seller and, since 2026-10-13, the pilot's questions
   (its orders are logged `zelerdata.year_history_covered`). Once the tail has caught up,
   `zelerdata.devoluciones_year_history_admitted` appears about once an hour.
   Check progress with `zelerdata_read_model_status --year-history` (see
   "Twelve months of history"): about a day for a pilot-sized seller.
   `ZELERDATA_YEAR_HISTORY_ENABLED=false` on `sheets-worker` is the emergency
   switch.

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
  modules/sheets/tests/test_zelerdata_all_sellers_sweeps.py \
  modules/sheets/tests/test_devoluciones_initial_coverage.py \
  tests/integration/test_devoluciones_new_sellers.py \
  tests/integration/test_year_history_new_sellers.py \
  tests/operations/test_zelerdata_all_sellers_dry_run.py
uv run pytest modules/sheets/tests/test_formula_recovery.py -k "all_mode or numeric_allowlist_claim"
```
