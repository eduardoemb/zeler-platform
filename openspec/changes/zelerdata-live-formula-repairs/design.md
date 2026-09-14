# Design: ZelerData Live Formula Repairs

## Technical Approach

Implement output correctness, scoped recovery, and existing returns reconciliation. Preserve signatures, widths, headers, seller isolation, and vector cardinality. No new recovery protocol, TTL expansion, or migration.

## Architecture Decisions

| Option | Tradeoff | Decision |
| --- | --- | --- |
| Normalize absence before string conversion | Prevents synthetic `NONE`; requires sales matching tests | Use empty internal SKU and visible `NA`; preserve real literal SKU strings and zeroes. |
| Choose first conflicting inventory code | Simple but silently wrong | Return `AMBIGUOUS_VARIATION` in that cell; identical duplicate codes resolve normally. |
| Treat observation baseline as historical transition | Misstates provenance | Render valid `last_status_change_at` as observed status evidence with `change_date_basis=observed_status_change`; otherwise `NA`. |
| Remove global freshness guards | Hides missing coverage | Retain strongest global proof; permit only validated per-resource fallback. |
| Repeat first historical recovery chunk | Never converges for long windows | Recover the earliest unproven gap, bounded to 90 days. |
| Add generic returns recovery | Duplicates joint-proof authority | Reuse existing focused reconciliation with leases and fingerprints. |

## Data Flow

Formula → validated scope → proven rows plus explicit gaps → existing recovery intent → worker acquisition/enrichment → persisted observations → recalculated formula.

### Group 1: Output correctness

PREGUNTAS normalizes absent answer/date. DIASDESDEULTIMAVENTA emits `NA` for no sale, preserving zero. PRODUCTOSINVENTA uses `_order_items`/`_item_quantity` for item-level sales exclusion without SKU; retain `_unit_totals` matching otherwise. Test shared normalization callers. Existing `last_status_change_at` includes first paused observations: render it with observed-basis metadata, never as reconstructed history, and never substitute `status_started_at` or `first_observed_at`. No production rewrite for rendering.

CODIGOML groups candidates by requested SKU/publication and counts distinct nonempty inventory codes. Zero codes yields `NA`; one yields the code; multiple yield `AMBIGUOUS_VARIATION`. Evaluate each vector element independently.

PUBLICACIONESDESCUIDADAS retains paused/full selection and withdrawal helpers. Missing reason/quantity is legitimate `NA`; never infer recommendations from paused duration alone.

### Group 2: Recovery and coverage

Catalog sales planning reuses validated current/retained interval proofs. Merge overlapping coverage, select the first gap inside the requested window, and cap its end at the next proof or 90 days. Preserve the established read cut and avoid equivalent moving requests while acquisition is pending.

ENVIOS first proves its actual 30-day order interval, then derives shipment IDs. Resolve recent owned shipment status evidence or request explicit-ID recovery. Missing required shipments remain visible; cancelled/closed filtering must not silently remove unresolved shipments.

For TIEMPOACTIVA and selected PRECIOHISTORICO, reuse current item acquisition and verify the corresponding status/history observation belongs to that source before reading. For whole-inventory TIEMPOSINSTOCK, require verified membership plus per-item stock observations and expose uncovered membership. Existing item recovery maintains observations; completion alone establishes no global proof.

Catalog/quality continue preserving independently successful rows. Measure source failures and sweep duration before scheduler changes; add an accelerated-clock regression if early batches expire during traversal. Do not extend TTL to satisfy a test. Unresolved throughput remains an explicit limitation.

Buybox validates fresh participation per resource inside the existing joined batch. Expired item dependencies reuse leased acquisition once, then revalidate ownership, freshness and participation. Failed siblings remain explicit; verified sibling snapshots survive. No global freshness marker is published.

### Group 3: DEVOLUCIONES

Use the existing focused operation in `infra/operations/zelerdata_read_model_reconcile.py` for the selected seller/window. Acquire source claims and associated orders, verify returned quantity and joint fingerprint, then publish through its existing lease authority. Recalculate the known claim fixture. No generic queue model or validator expansion.

## File Changes

Paths below are relative to `modules/sheets/`.

| File | Action | Description |
| --- | --- | --- |
| `src/zeler_sheets/formulas/read_models.py` | Modify | SKU normalization, proof-gap planner, validated resource resolution. |
| `src/zeler_sheets/formulas/handlers_core.py` | Modify | Code ambiguity. |
| `src/zeler_sheets/formulas/handlers_orders_questions.py` | Modify | Missing values, sales exclusion, transition date. |
| `src/zeler_sheets/formulas/handlers_item_shipping_catalog.py` | Modify | Shipment scope and gaps. |
| `src/zeler_sheets/formulas/handlers_remaining_phase4.py` | Modify | Stockout/history scoped reads. |
| `src/zeler_sheets/formulas/handlers_returns_histories_withdrawals.py` | Modify | Status fallback and supported withdrawal fields. |
| `tests/test_formula_*.py` | Modify | Focused regression and recovery evidence. |

## Interfaces / Contracts

No public signature changes. Additional internal metadata may describe partial coverage; no new persisted fields. Preserve existing recovery request types and source ownership checks.

## Testing Strategy

| Layer | Evidence |
| --- | --- |
| Unit | RED-first absence/zero, ambiguity/vector, SKU-less sales, genuine timestamps, interval gaps. |
| Integration | Isolated Mongo; stale → acquired → usable; wrong-owner and incomplete-source rejection; retained coverage and real gaps. |
| Live | Same 15 diagnoses plus CALCULADORA control; expected/actual/source evidence before and after recovery, and after expiry where relevant. |

## Threat Matrix

N/A — no new routing, shell, subprocess, VCS automation, executable classification, or process integration. Existing operational commands retain their documented controls.

## Migration / Rollout

No migration required. Identify affected images after implementation; exact authorized main commit, verified Cloud Build provenance, scoped deployment, compatible rollback, and spreadsheet recertification remain required. Operational returns reconciliation is separately recorded as a bounded data repair.

## Open Questions

None blocking. Measure source availability and acquisition throughput live.


## September 14: layered recovery

Original recovery-first scope (expanded by the closure below). Basic inventory
acquisition fetches owned item batches of 20 plus necessary variation identities,
then existing histories/projections. Full enrichment remains the default for
explicit IDs. Preserve enrichment timestamps, invalidate changed bases using
existing states, retain CAS, and scope projection identity/status reads to IDs.

Three disjoint claim lanes use existing fields: inventory, explicit IDs, ranges.
Run one job per lane, including matching expired-lease cleanup. Share 180 requests
per minute with work-conserving 1:2:1 weights. HTTP deadlines start after quota
admission. Local quota exhaustion defers work without source-attempt consumption.

Reuse validated active admissions; reserve one of 20 slots for inventory. Use a
shared three-second admission deadline inside the existing 25-second formula
budget. Drain old occupancy naturally. Quality/calculator request missing base
and enrichment independently. No new public signatures, queue fields, migration,
or TTL expansion. Retain seller isolation and distinct discovery/detail clients.

Process integration requires lane lifecycle cancellation/failure tests; shell,
VCS and routing threat cases are N/A. Acceptance includes an accelerated 1900-item
mixed workload (including necessary variation calls and projection time), all
four quality gates with isolated Mongo, independent SDD verification, two live
base inventory cycles inside 15-minute freshness, and the 35-case Sheet retest.
Deploy worker then API only with exact-main provenance, capacity and compatible
rollback under applicable authorization. Quality/catalog failures remain explicit.

## September 14: full closure and broker ownership

Fix gateway ownership before formula certification. Installed RobustConnection
has is_closed/connected, not is_open; ten local probes currently create ten new
connections and do not close the original. Production has 20 connections, 17
without channels; DNS/TCP/management work while new AMQP is rejected. This is
evidence of the code defect, not yet proof of the broker's exact rejection cause.

Reuse a connected owned connection; await an existing robust reconnect within
the current budget. Serialize creation only for absent/closed connections,
recheck state under the lock, and close failed/unpublished resources. Close
owned state on shutdown. Initial startup completion must not permanently lock
readiness to an initial broker failure. Preserve the initializing state while
the lifecycle is still starting. Tests must use the real connection interface.

Preserve Sheet signatures, source-bound snapshots, seller isolation, 180/minute
shared acquisition, 15-minute base freshness and the 25-second API budget.
Profile full-size concurrent formula reads before any additional optimization.
Use existing focused returns reconciliation and source-gated historical writers
only with demonstrated source authority; no schema migration or legacy import
is planned. Missing positives use the user-approved combined evidence rule.

Deliver gateway first, then changed worker/API images with exact-main provenance
and compatible rollback. The 90-minute production window starts only after
warm-up and dependencies pass; no deployments/config changes occur inside it.
Recalculate all 35 at 0/30/60 minutes, read complete matrices, sample lightweight
health/freshness/queue/connection metrics every minute, and restart the window
after any corrected failure. Keep all 24 diagnosis rows synchronized with the
35 expected/actual/source cases. Independent SDD verification gates closure.

Runtime inspection found refresh disabled. Enabling the broad refresh every
30/60 seconds would churn distinct moving orders/questions ranges, so preserve
its existing 900-second cadence. Add an inventory-only 30-second admission tick
inside the same owned supervisor loop, reusing the existing seller allowlist,
inventory request key and active-job coalescing. No separate scheduler/task or
persisted field is introduced. Broad refresh retains returns proof renewal,
markers and its individually gated optional operations. Enable this existing
supervisor for the pilot seller during scoped worker delivery; keep optional
DLQ archival and unrelated actions disabled. Prove deadline/cancellation,
failure isolation and non-inventory cadence before enabling it.

## September 14: canonical UTC membership of return candidates

The May 14 read-only reproduction found four valid productive claims already
persisted, while the UTC readback counted three. Search and hydrated claim detail
agree that one productive candidate predates the requested start; the provider
search therefore supplies candidates outside the exact local interval. This is
not missing persistence or a monotonic-write conflict. Keep the paired inclusive
search parameters, complete two-pass inventory, physical-call limits and original
claim timestamps unchanged.

Membership is determined by the authoritative hydrated claim's aware
`date_created`, normalized to UTC, in `[start, end)`. An outside candidate may be
classified only after detail acquisition proves the same claim identity, seller
respondent, and the same aware creation instant recorded by the inventory.
Missing/invalid/naive or contradictory timestamp evidence fails closed; it never
silently excludes a candidate. Exact start belongs to the interval, exact end
does not. The existing terminal-cancellation pre-detail rule is unchanged.

Retain outside identities and dates in the full inventory fingerprint, retain a
bounded `outside_requested_range` exclusion reason in the exclusion fingerprint,
and report `excluded_outside_requested_range`. Only the canonically in-range
claims enter projected writes, expected claim IDs and joined read-model proof.
This classifies requested-window membership, not return disposition: it creates
no negative claim, rewrites no timestamp, hides no inventory identity and bypasses
no seller-wide historical guard. Final revalidation reacquires the same complete
inventory and details; membership, date, identity or exclusion drift prevents
publication. Public evidence remains a bounded category/counter mapping.

## September 14: identical item acquisitions in flight

Production profiling measured 18.67 MB per 1900-item canonical source read,
4.929 seconds of database transfer and 1.831 seconds of synchronous fingerprint
work. Concurrent inventory formulas exhausted the existing 25-second dispatch
budget despite isolated reads completing. Share only identical acquisitions
currently in flight, including projection rows, full source documents and their
full fingerprints. Bind the coordinator to one application database owner and
key by seller plus the exact normalized identity set. Remove completed work
immediately; retain no TTL cache or source snapshot after completion.

After full canonical fingerprinting, retain only a private association source
view (owner/observation, parent and variant catalog membership, title, quantity,
and acquired promotional-price inputs). Full item-history reads are unchanged.
Each waiter receives its own mutable rows/source-view copies and validates all
receipts, ownership, completeness and observation timestamps against its own
request time. Cancelling one waiter leaves others running; cancelling the last
waiter or application shutdown cancels and drains owned work. Failed reads are
not reused. Different applications/databases/sellers/identity sets do not share.
Prove realistic 19 MB concurrent reads against isolated Mongo, independent
freshness boundaries, mutation isolation, failure/cancellation cleanup and
application wiring before runtime recertification. This optimization neither
extends freshness nor changes source acquisition quotas or public contracts.

### Truthful multi-window return readback

A large read-only request may retain its existing bounded source slices, but
source acquisition is not local persistence. Aggregate the actual per-slice
persisted/complete/missing counts and preserve unknown/query-failed counts.
A duplicated expected claim across disjoint UTC slices is inconsistent source
membership and must suppress certification instead of collapsing the IDs and
inventing matching counts. Per-snapshot physical counters are each recorder's
actual attempts, not cumulative run totals. Outside-membership counters remain
bounded diagnostic counts across acquired slices. No writer or marker contract
changes are introduced by this dry-run evidence correction. Source and read-model
fingerprints aggregate their respective per-slice proofs separately, each bound
to the seller and ordered half-open UTC scopes; hashes are never sorted away
from their interval identity or relabeled as another proof type.

### Economic enrichment basis: tag membership compatibility

Economic item tags are membership flags: their order and repeated occurrences do
not change shipping or listing fee inputs. Canonical economic bases and fee request
contexts therefore use sorted unique tags; other lists retain their existing
semantics. Backfill and item events share the same basis matcher. For persisted
pre-correction hashes, a retained complete basis can establish semantic equality
without rewriting its hash or observation timestamp. A hash-only legacy state
that cannot establish equality remains untrusted. Malformed tags and actual
membership, price, currency, category or shipping changes still invalidate the
corresponding enrichment. Existing owner/source guards and freshness windows stay
in force; this correction performs no migration or retrospective retimestamping.

### Failed acquisition siblings retain valid projections

After all item-acquisition sub-batches join, an ordinary acquisition exception
must not prevent already persisted seller-owned item sources from receiving their
normal history and formula projections. Existing lease checks remain mandatory.
The worker retains the first acquisition exception, projects persisted sources,
then rethrows it before readiness/cursor success handling. If projection itself
fails, the original acquisition exception remains primary and chains that failure
as its cause. External cancellation does not start a projection cleanup phase,
renew a source timestamp or extend the job deadline. This closes a reproducible
partial-write gap; it does not establish that historical live discrepancies had
this cause.
