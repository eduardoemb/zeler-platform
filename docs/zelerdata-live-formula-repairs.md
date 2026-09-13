# ZelerData live formula repairs

Change authority: `openspec/changes/zelerdata-live-formula-repairs/`.
The user authorized repairs and verification in the existing spreadsheet, including
required builds and deployments. The user subsequently authorized commits and
push to the selected `main` branch to continue that release and live verification.

## Baseline

The September 12, 2026 audit executed 24 primary formulas and 11 supplemental
cases in spreadsheet `1NUYbJUgYEc6SumZ_IwOWXj_d9MC4grGO5c2XRrAM858`, tab `gpt`.
All 35 stored formulas were independently read back. The diagnosis occupies
`A10:F34`; inputs use seller `82453304` and August 15–September 11, 2026.
The Chrome profile is Profile 19, selected through the existing `zeler.ai` profile.

Initial local checks: 139 core/order/read-model tests passed before repairs.
Tests use a new disposable loopback Mongo container, port 27028, replica set
`rs0-dev`, verified writable PRIMARY, with a 65536 file-descriptor limit.
No local test connects to production Mongo.

## Runtime observations — September 13 UTC

At 03:16 UTC both Sheets containers were healthy, with zero restarts and no OOM.
This establishes container state, not formula correctness. Running identities:

- API: `sha256:14bda442671e9a79c00fafd6501f07f7716090adbc141799cd1b93e3840c3b47`.
- Worker: `sha256:169bea9f8f7534eedff6ea424246ce88ecc7fda5ac2e3a9acfcd51973ba3f569`.

Root capacity was 27,587,293,184 free bytes; Mongo mount had
48,640,565,248 free bytes. Available memory was 1276 MiB. These measurements
must be repeated before image downloads; they do not authorize cleanup.

The inventory sweep was still running (offset 440). Catalog product jobs had
completed, while some buybox jobs failed with `source_rejected` or
`source_incomplete`. The historical orders job failed with
`source_temporarily_unavailable`. These outcomes do not justify extending TTLs
or substituting zeroes for unknown data.

## DEVOLUCIONES operational attempt

The focused reconciliation dry-run, executed inside the production worker for
the audit seller/date range, succeeded: expected/persisted/complete = 1/1/1,
missing = 0. It made nine recorded physical source attempts.

The authorized write and a diagnostic reproduction failed before productive
marker publication. Sanitized stack frames identify
`_reject_historical_non_productive_devoluciones_rows`, not a missing claim in
the requested interval. The classifier found eleven historical `returns` rows
without canonical productive/basis fields, all outside the audit interval:
three in May 2025, six in June 2026, and two in July 2026.

The existing seller-wide guard remains in place. The requested claim is
canonical, but DEVOLUCIONES is not certified repaired. The failed operation
left the joint marker stale through the existing fencing path. Historical
remediation requires authoritative source evidence; do not delete legacy rows,
assign productive flags manually, or weaken the guard to report success.

A follow-up focused dry-run for May 2025 ended with `source_issue` after
27 recorded physical attempts. No historical marker or canonical classification
can be inferred from that failed acquisition. Further remediation remains open.

## Verification status

The following implementation units have passed focused regression checks:

| Unit | Changed behavior | Evidence |
| --- | --- | --- |
| Output | Explicit NA, cell-local code ambiguity, observed dates, SKU-less products, cancelled-sale exclusion | 151 tests |
| Catalog intervals | Advance to uncovered intervals; retain a supported recent cut | Ten new cases, including four real worker/Mongo acquisitions covering 365 days |
| Shipments | Prove the order interval and recover required shipment identities | 60 tests, including worker/Mongo pending-to-usable |
| Item histories | Bind state, stockout and selected price history to acquired item evidence | 143 tests, including 19 new cases and real writers/Mongo expiry |
| Buybox | Preserve valid siblings and acquire stale dependencies under the existing lease | 70 tests, including four mixed-batch Mongo scenarios |

Ruff check and format pass; mypy passes across 532 source files after correcting
two optional-date assertions in a new test. The direct-Meli access lint passes.
The complete repository suite passed: **4,539 passed, 9 skipped** in 169.17s.
Eight skips are the protected Mongo tests that reject ambient `MONGO_URI`;
they were run separately with their approved loopback configuration and all
**8 passed** in 3.60s. The remaining skip is the existing Caddy required-keys
check. Individual RED/GREEN receipts are stored with the selected change artifacts.

## Prepared deployment scope

The affected services are **sheets-worker** (buybox acquisition) and
**sheets-api** (formula rendering, coverage planning and scoped recovery).
Build one verified image per service from the exact new commit on connected
repository `eduardoemb/zeler-platform`, branch `main`. Do not upload this checkout.
The checkout started at `66329c01a060b57de851d32476e66a95b28df2a4`.

Capture both Cloud Build IDs, full source commit
and immutable image digests; verify provenance before deployment. Deploy worker
then API only, on `platform-vm`, `us-central1-a`, project `zeler-platform-dev`.
Recheck capacity and rollback registration compatibility immediately before pulls.
No schema/validator rollout, registry scope expansion or cleanup is proposed.
Retain the previous running digests recorded above as rollback candidates,
subject to the runbook's provenance/compatibility attestation.

Acceptance requires running-digest checks, dependency/consumer readiness after
the settling window, and the original 35 spreadsheet cases with source comparisons.
Do not overwrite the baseline diagnosis with a passing status before live results
exist. DEVOLUCIONES historical remediation and upstream catalog gaps remain open.

No new images have been built or deployed for this change. Passing local tests
must not be presented as post-deployment Google Sheets acceptance.
