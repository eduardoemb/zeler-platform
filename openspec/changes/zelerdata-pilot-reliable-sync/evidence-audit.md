# Pilot evidence audit — 2026-09-15 continuation

The pilot is not ready for build or deployment. Preserve the complete acceptance
scope: 52 real formulas, recoverable reconciled history, automatic visible
updates, integrity repairs, and the 90-minute observation. Smaller passing work
units below repair defects; they do not replace final acceptance.

## Confirmed findings and correction order

| Area | Current evidence | Required next evidence |
| --- | --- | --- |
| Event visibility | Corrected: the consumer no longer labels an exported event row as a visible formula result. Five new actual handler/Mongo cases and 64 affected regressions pass. | Legitimate formula-cell observation; complete claims/catalog stage coverage and distinguish gateway receipt from worker handling. |
| Fixed historical cutoff | Corrected: normalize BSON timezone on reload, atomically initialize the cutoff, and use the stored winner. Three actual Motor lifecycle cases and 49 history regressions pass. | Preserve these cases while fixing the remaining callback path. |
| Admission/capacity | Corrected with real-Mongo evidence: the callback stops admission on typed capacity rejection, persists all 48 planned chunks, and does not reopen existing jobs. Counts distinguish observed queue states and successful/coalesced calls. | Per-chunk snapshots do not prove acquisition coverage or fairness under sustained competing lanes. Complete those worker/runtime proofs separately. |
| Historical resource routing | Range requests for shipments and item rows fail the real queue's explicit-ID requirements. Order acquisition does not acquire their details automatically. | Link authoritative order intervals to shipment IDs and per-ID outcomes; retain observed-only item history and explicit source limitations, without silently dropping resources. |
| Interrupted range acquisition | Order/question workers accumulate pages in memory and publish at completion; manually setting job states does not prove worker checkpoint recovery. | Interrupt an actual multi-page worker, resume from durable safe evidence, and verify rows, counts, exclusions, and interval proofs. Never mark partial chunks complete to avoid retries. |
| Bounded question acquisition | Existing coverage expands a subsequent question interval to the entire union, including its gap. | Separate bounded acquisition from retained interval proofs; prove that recent then oldest monthly work does not become an annual scan. |
| Modification reconciliation | The new overlap helper has no production caller and selects the last 24 hours of an old creation interval. | Search actual modification windows with overlap and monotonic writes; prove an operation created outside the tail is updated now. |
| Formula coverage | Finding a formula name in a test file does not execute that formula or validate its output. The matrix's expected descriptions are not a measured source/result comparison. | Behavioral positive/absence/filter/range cases for all 52, simultaneous local harness, then real Sheets rounds and source comparison. |
| Progress/configuration | API retrieval now has actual ASGI and seller-scoped Mongo tests, with the JWT signature boundary stubbed. The existing app still has no backfill progress consumer; its sync status documentation explicitly leaves that contract unresolved. | Complete supported retry/status semantics and the existing application UI. No new frontend. |
| Manual retry | The current sync endpoint inserts a timestamp-keyed job; it neither finds an in-flight job nor handles same-second duplicate insertion. | Concurrent real-Mongo tests proving non-duplicative retry and seller isolation before changing the implementation. |
| Apps Script | Manual active-tab traversal is unbounded, uses stale-read formula writes, and claims success without observing results. | Execute actual JavaScript in a local harness; validate the candidate operation in the authorized test tab before claiming recalculation or automatic open/reopen behavior. |
| Root type gate | The duplicate pilot API import initially stopped mypy; correcting it exposed 55 pilot-test typing errors. Both defects are now fixed, and the exact root command passes all 573 files. | Retain the corrected behavioral tests and typing; rerun final gates after the remaining implementation changes. |
| Production returns and acceptance | Prior notes retain nine blocking records and seven repairable dates; these are historical leads, not current runtime evidence. | Approved VM-context diagnosis/repair, measured history integrity, 52 real formulas, warm-up, 90 minutes, final independent SDD verification. |

## Evidence boundaries

- The prior report's 4796 passing tests and 171-file mypy result are historical.
  They are not a fresh full-repository gate result. The initial root type error
  is recorded at `/tmp/zelerdata-pilot-audit-mypy-20260915.log` (exit 2).
  The corrected exact root gate passes 573 files in
  `/tmp/zeler-pilot-types/green-mypy.log`; 92 affected tests pass in
  `/tmp/zeler-pilot-types/green-tests.log`. This is not a full-suite result.
- Mongo tests use the verified disposable local replica set on loopback port
  27028. Production Mongo is never queried from the local assistant environment.
- Current runtime image health/provenance has not been rechecked in this
  continuation. Old health evidence cannot authorize downloads or deployment.
- The user authorized the `pruebasnuevas` tab in their supplied spreadsheet.
  Connector metadata confirms its identity and 1000-by-26 grid; the initial
  A1:H20 read was empty and unconstrained. All other tabs are excluded from
  mutations. This readiness probe is not a 52-formula acceptance round.
- The application checkout exists on `main`, with an unrelated untracked
  `.codegraph/` directory. It has only been inspected. Its local instructions
  and the SDD's platform-only edit roots must be resolved before app edits;
  do not move existing work or create a worktree automatically.

## External contracts checked

- [Mercado Libre orders](https://developers.mercadolibre.com.ar/es_ar/publica-productos/gestiona-ventas)
  documents modification-date filters separately from creation dates. Merely
  wiring the current creation-tail helper cannot satisfy that contract.
- [Mercado Libre questions](https://developers.mercadolibre.com.ar/en_us/tools/manage-questions-and-answers)
  documents creation-date sorting and ID reads; do not invent a modification
  search filter for questions without evidence of support.
- [Editor add-on triggers](https://developers.google.com/workspace/add-ons/concepts/editor-triggers)
  limits add-on timer frequency to hourly, not a minute-loop replacement.
- [Authorization lifecycle](https://developers.google.com/workspace/add-ons/concepts/editor-auth-lifecycle)
  distinguishes simple onOpen from full authorization. Manual sidebar opening
  alone does not prove automatic reopen behavior.
- [Custom functions](https://developers.google.com/apps-script/guides/sheets/functions)
  documents dependency-driven recalculation; identical setFormula is not a
  documented cache-invalidation guarantee. Do not clear user formulas or add
  helper arguments/scopes as an unreviewed workaround.

## Authorized Sheets readiness probe

The user explicitly selected `pruebasnuevas` and permitted test-cell changes.
Only A1:A3 was written: two short labels and, in A3,
`=ZELERDATA_SKU("82453304","__PILOT_NO_MATCH_20260915__")`.
The deliberately unmatched SKU is an absence/connectivity probe, not an actual
product identity or positive formula-acceptance case. No formatting, dimensions,
other tabs, add-on code, tokens, or production runtime settings were changed.

The connector acknowledged the write by 17:18:47 UTC. Readback at 17:19:08 and
17:20:50 UTC preserved the exact formula but returned no effective value or
formula error. A subsequent formatted-value read of A3:D5 also returned no
values. This does not prove execution, absence semantics, or recalculation.
The test formula is left in A3 for authenticated browser observation.

No connected Codex document session was available. The installed browser CLI
uses `--connect` rather than the skill's newer `connect` subcommand; its actual
connection attempt reported no Chrome with remote debugging enabled. The user
then authorized the authenticated Chrome `Profile 19`. The managed session
`zelerdata-pilot-profile19` opened a Google sign-in page rather than Sheets.
Inspection of the installed browser library and the session's profile-path
metadata confirms that the library automatically copies the selected profile
into a temporary directory; it did not preserve usable authentication in this
session. No credentials or cookie values were read, printed, or transferred
manually. A subsequent real-Chrome connection attempt still found no debugging
endpoint. The user was asked to enable debugging in the existing authenticated
profile. Automatic open/reopen and real formula results remain unverified,
not failed by inference from an empty connector read.

## Remaining acquisition design constraints

Task 2.3 was reopened because the original
`test_pilot_old_operation_modification.py` cases bypassed the operation guard,
used a fake database and never invoked a consumer or formula. A new real-Mongo
integration case now acquires coverage through the recovery worker, delivers
newer/duplicate/stale notifications through the actual guarded consumer and core
idempotency store, and verifies `ZELERDATA_VENTASTOTALES` via its dispatcher.
The 40-day-old order changes paid total from 100 to 0 and cancelled total to
100; stale/duplicate delivery preserves that result and the other seller's 900.
The bypass fixture is now explicitly limited to the legacy unit cases. Task 2.3
is complete for this local dispatcher-visible requirement, not real Sheets
visibility. The scoped regression has 24 passing tests; see apply-progress.

The actual question worker uses a seller-wide scan with local creation-date
filtering, not a server-side monthly filter. Removing `_coverage`'s expanding
union alone therefore cannot prove bounded source work: a durable scan cursor
and independently acquired per-interval evidence are still required. Cursor
expiry and changing source totals must not discard previously acquired rows or
turn a partial scan into coverage. The existing 10,000-result guard is a local
budget, not proof of a provider retention limit.

Both range workers currently publish rows, interval proof, and job completion
atomically only after all source pages have accumulated in memory. A resumable
design must separate durable acquired-page evidence from final coverage, fence
every checkpoint by the current lease, and validate complete source identities
before publishing a reconciled interval. It must preserve the orders returns
operation guard and concurrent-marker checks. Shipment relationships recovered
from order detail are not shipment-detail or cost acquisition evidence.

## Delivery remains gated separately

Local corrections and repository checks are complete through source commit
`d9f822c` on `main` (the subsequent commits are documentation-only). The
remaining delivery proposal is limited to
`sheets-api` and `sheets-worker`; it requires connected-repository source
verification, two source-bound Cloud Builds, immutable image digests,
pilot-only activation, fresh capacity/preflight, compatible rollback,
validator/topology compatibility, and product verification. Build authorization
does not authorize deployment. Add-on publication and any integrity repair
mutation require their own explicit scope. No push, build, deployment, or
add-on publication has occurred.
