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

### First release and live retest

Source `1df949fbd2653e2b63648e013b3c330eef92e61f` was pushed to main.
Both builds used the connected repository and verified provenance:

| Service | Cloud Build ID | Immutable digest |
| --- | --- | --- |
| sheets-api | `876925fd-31ca-44bc-ab8a-4c7da6fbf4d2` | `sha256:3b972a4bde3549f72a5c318c1f91c5cbb56d87e0d576d5ba56a3f8b5cd3eca6e` |
| sheets-worker | `27a598aa-a583-4656-8828-65eec73aa71f` | `sha256:e707c5c7a33ff3f84db46887265a0f8f852fae65b925db878871cdd2fffa570f` |

Worker then API were deployed narrowly after capacity, image provenance and API
rollback-contract attestation. Worker consumer/recovery/poller readiness, API
Mongo/RabbitMQ/registry/claims-DLQ checks and gateway dependency readiness passed.
All 35 Sheet formulas were refreshed and independently read back after deployment.

Confirmed in Sheets: CODIGOML ambiguity and mixed-vector ordering; absent sale NA;
pending question answer/date NA; PRODUCTOSINVENTA has 2,818 rows, 1,062 observed
dates, 19 absent SKUs rendered NA, zero NONE values, and zero date mismatches
against canonical items. An initial comparator additionally keyed by stock found
four nonmatching rows; removing that irrelevant key proved all dates independently.

ENVIOSMERCADOENVIOS recovered from 85 pending rows to two open shipments with
zero DATA_UNAVAILABLE cells. Source checks through the VM confirmed orders
2000018411889322 and 2000018428288488 are paid, quantity one each, and their
shipments 47992641793 and 48000531704 are `ready_to_ship` / `xd_drop_off`.
The displayed package IDs match `meli_pack_id`; they are not shipment IDs.

The actual acquisition chain exposed an additional worker omission: acquired
items did not refresh their status/price/stock observations. A failing real-worker
Mongo test reproduced it; the follow-up repair is documented in
`apply-progress-unit4-live.md`. Histories are not certified live until that second
worker image is deployed and tested.

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

The first release above was built, deployed and exercised in Sheets. The
follow-up history release is recorded below; its internal runtime checks must
not be presented as post-deployment Google Sheets acceptance.

## Interrupted-session recovery — September 13, 04:53 UTC

Read-only inspection confirmed that the history follow-up had already deployed
before the session interruption. No repeated build or deployment was needed.
Remote `main` and local HEAD both resolve to
`145ba4ffae0cb94d1c9ef8f4d87937e7393fcf2d`.

- Worker build: `b8f1fc42-ade0-4093-a074-a3be3fed5504`, `SUCCESS`.
- Running worker:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:25c2b64a80e70c518689f219740ca50434b62d3f1384264129568da266fb4674`.
- Connected repository, full source commit, build and subject digest passed
  `infra.deploy.provenance_check verify-image` again on resumption.
- API remains the first-release digest `sha256:3b972a4bde3549f72a5c318c1f91c5cbb56d87e0d576d5ba56a3f8b5cd3eca6e`.
  The follow-up corrects worker acquisition; no API rebuild is needed for this
  worker-only behavior.

Both containers were healthy with zero restarts and no OOM, with the worker
running for more than 25 minutes. Two component checks, at 04:52 and 04:53 UTC,
confirmed RabbitMQ consumer, sync poller and formula recovery readiness. API
Mongo, RabbitMQ, registry fingerprint and claims DLQ checks passed; DLQ ready
and unacked counts were zero.

Root available bytes were 25,995,071,488 with 6,055,297 free inodes. Mongo's
separate `/dev/sdb` ext4 mount had 48,636,604,416 available bytes and 3,276,318
free inodes. Available memory was 1,389 MiB. Docker reported 17.37 GB of images,
10 active containers and no build cache. Dry-run capacity preflight passed.
These are observations, not cleanup authorization.

A read-only internal dispatcher probe inside the worker returned one row each
for TIEMPOACTIVA and PRECIOHISTORICO on all three original history examples
(`MLM1939453749`, `MLM1318561388`, `MLM1968668367`): six reads, zero
DATA_UNAVAILABLE cells, no recovery requests. TIEMPOACTIVA returned 6, NA and 6,
respectively. For the previously failing `MLM1939453749`, source age was 218.5
seconds and status/stock observation timestamps and values matched the acquired
item. An unchanged price retains its original history timestamp by design;
absence of a duplicate price observation at the latest acquisition is not a
failed recovery. PRECIOHISTORICO accepted the retained history and current source.

The probe used no HTTP authentication, queue admission or business writes. It
does not establish authenticated API or Apps Script acceptance. Its sanitized
script is `/tmp/zeler-formula-resume-inspect.py` on the VM and local host.

The browser reopened the original spreadsheet with the selected `zeler.ai`
Profile 19, but Google requested sign-in. The user was asked to restore that
session; no spreadsheet cells or diagnosis statuses were changed on resumption.
The 35-case Sheet retest, historical DEVOLUCIONES remediation, catalog source
gaps and independent final SDD verification remain open. Aggregate recovery
records still include failed source acquisitions; those lifetime counts do not
establish a new regression or authorize replaying completed jobs.

## September 14 live retest

The original 35 Sheet cases were recalculated and read back. Selected history
controls now returned the expected results in Sheets; the expiry probe correctly
rejected an old observation and requested recovery. Large inventory and catalog
results remain incomplete. Shipment and selected-item jobs subsequently completed,
but the session resumed after their freshness windows had elapsed. A subsequent
selected-item recovery completed and the Sheet returned the expected history
controls again, proving that bounded expiry/recovery cycle. The next shipment
recovery also completed and returned five open shipments without unavailable
cells. Whole-inventory acceptance remains pending. See the
[live retest report](sheets/zelerdata-live-retest-20260914.md) for source comparisons,
coverage counts, the assisted shipment admission and remaining acceptance gates.
