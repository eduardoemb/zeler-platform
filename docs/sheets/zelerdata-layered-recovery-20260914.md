# ZelerData layered recovery — September 14, 2026

Authority: user approved recovery-first, layered acquisition, then implementation.
Prior commits/push, Cloud Build and scoped deployment authorization remains valid
as recorded in docs/zelerdata-live-formula-repairs.md. Returns and source-limited
positive fixtures remain outside this unit's completion criteria.

## Implementation

Inventory uses owned batches of 20 plus necessary variation identities and existing
history/projection writers. It no longer waits for cost, promotion or quality
acquisition. Identical successful base observations renew only the genuine base
cut; enrichment timestamps remain unchanged and changed bases become unavailable.
Selected projection dependency reads are bounded to their publication IDs.

Inventory, explicit IDs and date ranges have independent supervised claim loops,
sharing 180 requests/minute with work-conserving 1:2:1 weighting. Three-second shared
API admission preserves a slot for inventory and coalesces active requests.
Quality/calculator request base and enrichment independently. Local quota expiry,
including discovery deadlines and concurrent sibling joins, does not consume a
source attempt; genuine provider timeouts still do. No schema or TTL change.

## Local verification

- First full suite: 4599 passed, 9 skipped in 275.57 seconds. Eight protected Mongo
  scenarios passed separately; one Caddy no-required-keys case is inapplicable.
- Final full suite after independent deadline corrections: **4606 passed, 9 skipped in 280.28 seconds**. Protected Mongo: **8 passed separately**.
- Ruff check/format and full mypy across 541 files passed; direct-Meli lint passed.
- 1900-item integration: 95 detail batches, 19 discovery pages, 190 variation lookups and
 600 competing requests. Real Mongo histories/projections and simulated pacing
 completed within 15 logical minutes, including measured persistence wall time.
 This does not establish production latency or provider completeness.
- Independent scoped verification reports are included below. Full live/change
 acceptance is pending deployment and the two-cycle Sheet verification.

## Delivery boundary

Affected images: sheets-worker and sheets-api only. Build separately from the
exact final commit on connected main, verify provenance and immutable identities,
then deploy worker followed by API. Preserve current running digests as rollback;
no registry, schema, volume, cleanup or other service change is included.

## First live delivery and residual pacing defect

Worker and API from `ef0c4bb6d6d50d4264ed1560fd101268748fbecd` were deployed
narrowly. At 17:12 UTC worker RabbitMQ, poller and recovery readiness passed;
API Mongo, RabbitMQ, registry and claims-DLQ checks passed. Both containers and
the unchanged gateway were healthy with zero restarts/OOM. Root had
29,244,047,360 free bytes, Mongo had 48,613,130,240, and available memory was
1358 MiB. These measurements describe this checkpoint only.

The inherited partial inventory advanced from 1000 at 17:00:54 to 1760 at
17:09:32, then completed and reopened naturally. Fresh enumeration began at
17:10:44. By 17:13:24 only 120 of 1900 had been acquired in this cycle. The
five-minute gateway audit recorded 900 requests, with only four variation
lookups. A sustained-competition pacing reproduction exposed a gap in the
finite-load test: while inventory projects a batch, other lanes can consume
the whole fixed window. This first deployment does not establish the SLA.

All 35 original Sheet anchors were recalculated through the native connector
and their results independently read back. Both selected calculator controls,
the selected active/paused histories, price history and dimension controls
returned their expected result shapes again. Catalog/quality remained partial;
returns and the four unsupported historical metric families remained explicitly
unavailable. The scalar code ambiguity, no-sale NA and 11-day sold control
persisted. This bounded retest is not full inventory or enrichment acceptance.

### Sustained pacing correction

The live gap has a RED regression with continuous ID/range competitors and
three simulated seconds of persistence between all 95 inventory batches.
The original pacer exceeds 900 simulated seconds; spaced admission passes.
Lane-aware calls now share a minimum 333334-microsecond interval at 180/minute,
retaining the fixed-window cap, pending 1:2:1 rotation, idle-share borrowing,
legacy-only compatibility and joined cancellation. Mixed callers cannot bypass
spacing. No TTL or budget was changed.

The integration/caller set passed 41 tests in 75.58 seconds, including the
real-Mongo 1900-item workload; a later mixed-mode test passed separately.
Independent review of the final diff passed 41 pacing/caller/lifecycle tests
in 10.91 seconds and found no additional defect. The timing regression is a
scheduler model, not live acceptance. Detailed TDD evidence is in
`openspec/changes/zelerdata-live-formula-repairs/apply-progress-spaced-pacing.md`.
Only sheets-worker constructs these pacers; the current API image remains
applicable to this localized worker correction.

Final repository gates for this correction: **4609 passed, 9 skipped in
280.21 seconds**; the eight protected Mongo cases passed separately in 2.33
seconds. Ruff check/format and mypy over 541 files passed. The remaining skip
is the inapplicable Caddy required-keys case.

Worker correction release proposal, covered by the existing scoped authorization:

- Connected-main source: `14d0311aa0512aa42505582238f43d63327de8b3`.
- Successful verified Cloud Build: `be36a95e-ba80-4555-82d9-cf26461f13e0`.
- Target: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:8b048b8890974878a54b9fe8c2ba7e423f3a31ab0e32132bd19ab2a3ce8bbafc`.
- Compatible running-worker rollback: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:0450c9bf6f5af7ac2778f864a768d2de969c90b0f7c07a71a540c25f655e8f91` from `ef0c4bb6d6d50d4264ed1560fd101268748fbecd`.
- Keep API `sha256:6d9ad5434315ceef9b7b283e0babbc7d865377f9eced1fcc7963c43904e24226` and gateway unchanged. Reattest the current API contract with the candidate worker, preserve schemas/registry/topology, and perform no cleanup.
- Recheck capacity before pulls; deploy only worker with 300-second stop grace and a larger outer timeout. Verify immutable identity, three worker readiness components, settling health/capacity, two newly enumerated inventory cycles and Sheet results.

The corrected worker deployment completed by 17:28:41 UTC. Running digest
matched the verified target; health, RabbitMQ, sync-job poller and formula
recovery checks passed, with zero restarts/OOM. Root remained above 27 GiB free.
It resumed offset 1220, reached 1580 by 17:29:06, and finished the inherited
1900-item job at 17:29:47. That job's enumeration was already old and is excluded
from successful-cycle evidence. A normal CALIDAD recalculation requested a new
inventory acquisition after completion; no queue reset or source patch was used.

First newly enumerated cycle: 17:30:35.567–17:40:52.981 UTC, **617.414 seconds
(10 minutes 17 seconds)**. At 17:41:36, the approved runtime reader confirmed
1900/1900 recent owned sources, 2859 projected rows for 1900 members, zero
missing base projections, current enumeration and zero unavailable identities.
The oldest source was 636.345 seconds old, below the unchanged 900-second limit.
ID and range jobs remained active. All 35 original Sheet anchors were then
recalculated again; subsequent Sheet verification is recorded below.

The 35-way recalculation returned PROCESSING for eight inventory-wide formulas.
CALIDAD returned its matrix on an individual retry; while the second inventory
cycle was writing, that snapshot represented 1900 IDs with 1880 available base
rows and 20 explicitly pending projections. Catalog and buybox still exceeded
the 25-second API limit individually, so this is not attributed solely to the
simultaneous recalculation.

A read-only phase probe inside the production API measured 3.191 seconds to
read 2859 projections, 5.679 seconds to read 1900 complete sources and 2.819
seconds to fingerprint them. Catalog repeated the full source read/fingerprint
before further work. CATALOGO also loaded a full year of orders even when no
sales window was proved and every sales output would be unavailable. The next
bounded correction reuses invocation-local validated sources and narrows sales
reads, preserving full fingerprint/ownership/freshness/row-count checks. It
does not cache across requests or increase the API deadline.

Second consecutive newly enumerated cycle: 17:42:04.085–17:55:51.368 UTC,
**827.283 seconds (13 minutes 47 seconds)**. At 17:55:53, the runtime reader
again confirmed 1900/1900 recent sources, 2859 rows for 1900 members, zero
missing base projections, current enumeration and zero unavailable identities.
The oldest source was 801.025 seconds old. Both cycles used worker `14d0311`;
the subsequent read-only formula optimization does not alter acquisition,
pacing, leases or persisted source/projection contracts. The two-cycle base
criterion is satisfied; catalog execution-time and final visible-result checks
remain a distinct delivery requirement.

## Verified read-optimization release

Existing scoped authorization covers worker then API from connected-main source
`bead0c48bd35449ae5553eb0d695b893fcb653b0`. Both builds succeeded with VERIFIED
provenance and matching immutable digest/source records:

| Service | Build | Target image |
| --- | --- | --- |
| sheets-worker | `fa111430-5ced-427e-a4c2-eab6ed8a4a5d` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:887781cf8d9264a9d49912af03049979a618dd30292a716e3d734a6e75001b98` |
| sheets-api | `deb68102-7bfb-4e91-b0aa-d57282c6e536` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:07499cf3ce2de2e99d41f31db8be557110131c4e941e7068d788b3e2e747f7b7` |

Compatible rollback remains worker `sha256:8b048b8890974878a54b9fe8c2ba7e423f3a31ab0e32132bd19ab2a3ce8bbafc`
from `14d0311` and API `sha256:6d9ad5434315ceef9b7b283e0babbc7d865377f9eced1fcc7963c43904e24226`
from `ef0c4bb`. Gateway, schemas, registry, topology and volumes remain unchanged.
No cleanup is included. Reattest API rollback compatibility, recheck capacity
before each download, replace only the selected service with 300-second stop
grace and a larger outer timeout, then verify identity, readiness, settling
health/capacity and visible formula results.

Operational limit: the two passing cycles are not a continuous-availability
guarantee. During the subsequent release/inspection period, at 18:07:15 an
in-progress third sweep had 1720/1900 fresh sources and an oldest age of
949.635 seconds. The readers correctly exposed expired/pending rows. No TTL or
source timestamp was changed to hide this observation. Final reporting retains
this gap separately from the two completed-cycle acceptance measurements.

The third sweep completed at 18:16:18.921 after enumeration at 17:56:06.615,
20 minutes 12 seconds including the worker replacement period. The 18:16:43
runtime sample found 1420/1900 fresh sources, 480 missing base projections and
expired enumeration. This is an observed freshness failure at that checkpoint;
the two earlier successful cycles must not be generalized to every sweep.

The final worker replacement completed healthy, zero restarts and OOM false,
with the exact `887781cf` digest above. Post-pull/deployment root capacity passed
at 27 GiB free. The optional API-child graceful-stop probe failed its module
identity assertion without sending a signal; API delivery therefore retains
the original bounded 300-second Compose stop strategy. API delivery and final
visible verification remain pending at this checkpoint.

### 18:40 UTC report checkpoint: shared broker readiness failure

Both final `bead0c4` images were narrowly deployed and initially became Docker
healthy with zero restarts/OOM. API post-delivery root capacity passed at 26 GiB.
The subsequent API health request timed out at 20 seconds; at 18:35 the API was
Docker unhealthy. Two later bounded probes returned HTTP 503: Mongo and registry
passed, RabbitMQ and claims-DLQ availability failed. Gateway `/ready` independently
returned HTTP 503 with RabbitMQ failing while Mongo, registry and the repricer
sweep scheduler passed. The broker failure is shared; its cause is not established.
No broker mutation, cleanup or other-service restart was performed. The final
images remain running, with the compatible rollback recorded above still available;
stable runtime acceptance is explicitly open.

The final Sheet retest recalculated 23 original anchors in five staggered groups
before further requests were stopped on the readiness failure. All 35 anchors
were read back, but the remaining 12 retain prior executions. Recalculated
calculator/control headers, supermarket negatives, selected active/paused history,
dimensions and sold/no-sale controls returned. CALIDAD, CATALOGO, BUYBOX and
CATALOGOCOMPLETO remained PROCESSING; OBTENERCATALOGO returned DATA_UNAVAILABLE.
Headers alone do not verify complete matrices. Task 6.6/6.7 and full-change SDD
acceptance remain open. Evidence files: `/tmp/zeler-read-release/` deployment
logs, `health-detail*.log`, `gateway-detail-final.log`, `dependency-capacity.log`
and `sheet-report-cut.json`.

Capacity during the failure: root 26,916,232 KiB free, Mongo 47,455,252 KiB free
on `/dev/sdb` ext4, free inodes 6,080,423 / 3,276,318 and 1,483 MiB available RAM.
Docker reported 30 images / 15.75 GB, 10 active containers, eight local volumes
(three active), zero build cache; no cleanup was performed. Intended runtime
source and both running image bindings remain `bead0c4`; subsequent local edits
are documentation only, so another image build is not indicated by source drift.

Read-only production preflight found 30321201152 bytes free on root,
48610152448 bytes on mounted /dev/sdb Mongo volume, 6123212/3276318 free inodes,
1107 MiB available memory. All inspected services healthy, Sheets and gateway
zero restarts/OOM. Recheck capacity before image downloads.


## Independent pacing evidence

# Focused pacing verification

Scope: shared pacing, HTTP deadline callers and worker quota classification.
This is not full-change SDD acceptance or live certification. The reviewer did
not author the pacing implementation; after finding the first defect, root
assigned its bounded discovery correction to this reviewer. That correction
therefore needs independent final confirmation.

## Findings

1. **Discovery quota misclassified at its own deadline — corrected.**
   Discovery's 180-second outer deadline preceded the worker's 239-second quota
   deadline. With an exhausted pacer and a shortened discovery deadline, the
   actual Mongo worker persisted `attempts=1`, `source_temporarily_unavailable`,
   with zero provider requests. RED regression failed on that attempt count.
   Discovery now applies a 179-second quota deadline inside the existing cursor
   bound. The pacing author made nested quota deadlines honor the earlier parent.
   Both local-quota and genuine HTTP-timeout regression cases pass.

2. **Known quota expiry can be masked while joining a sibling — corrected and independently confirmed.**
   A real `_finish_catalog_batch` wave with one child raising LocalQuotaTimeoutError
   just before the outer worker deadline and another still completing its source
   call remains in TaskGroup join. Outer timeout then replaces the already known
   quota failure. A scaled reproduction (quota at .03s, worker limit .04s, sibling
   at .05s) calls `finish(succeeded=False, retryable=True,
   failure_reason="source_temporarily_unavailable")` instead of `defer_quota`.
   The intended 239/240-second relationship has the same ordering when a sibling
   needs over one second to finish. Cancellation must still drain siblings;
   preserving the known quota classification must not mask independent timeouts.
   The pacing author added a per-job mutable RecoveryQuotaScope inherited by
   child tasks and nested contexts. Pacer quota expiry records this evidence;
   the worker defers an outer TimeoutError only when that job has known quota
   expiry. Independent reinspection and the three-way race regression confirm
   quota deferral, genuine source retry, and externally cancelled sibling drain.
   A subsequent fresh scope has expired=False; deadlines still retain their
   minimum parent value and both context variables reset on exit.

## Executed evidence

- Original requested pacing/caller set: **28 passed in 6.19 seconds**.
- After discovery and nested-deadline corrections, combined pacing, caller,
  worker lifecycle, basic acquisition and backfill set: **230 passed in 6.82s**.
- Discovery correction RED: one failed, one passed; GREEN: two passed.
- Ruff and formatting passed for changed files; mypy passed for backfill and
  caller tests. No production access or mutation was performed.
- Real-Mongo cases use the dedicated isolated loopback replica on port 27028
  and unique disposable databases.

Review confirmed work-conserving 1:2:1 scheduling, cancelled waiter cleanup,
last-waiter timer shutdown, HTTP deadlines beginning after quota admission,
nonpaced compatibility, CatalogLocalQuota propagation after normally completed
sibling joins, and context restoration. Existing tests cover these behaviors;
the original outer-deadline/join race is now covered by the additional regression.

## Final focused verdict

**PASS for this pacing/HTTP/quota-classification scope.** Both reproduced
findings are corrected. The final independently executed four-file pacing,
caller and lifecycle set reports **38 passed in 6.92 seconds**, with real-Mongo
cases on the dedicated port 27028 instance. No additional product edits were
made during this final confirmation. Full repository gates, full-change SDD
acceptance and runtime/live certification remain outside this scoped verdict.


## Independent acquisition, queue and API evidence

# Independent local implementation assessment

Change: `zelerdata-live-formula-repairs`, layered tasks 6.1, 6.3 and 6.4.
Date: September 14, 2026. Assessment: **PASS within the inspected local scope**.
Full-change SDD acceptance: **PENDING**, not a canonical passing verify report.

## Independence and scope

Reviewed actual changes against proposal, design, tasks and the layered-recovery
specification: base acquisition and projection scope; queue admission/claim/defer;
consumer lifecycle/factory wiring; formula recovery intents and API deadlines.
The reviewer authored pacing and worker HTTP deadline helpers, so those portions
are explicitly excluded from this independent judgment and require peer/root
verification. The final quota-accounting correction also requires that peer
confirmation. No production state, images, spreadsheet results or deployment
health were certified by this assessment.

## Executed evidence

- `MONGO_URI=<verified loopback rs0> uv run pytest modules/sheets/tests/test_layered_basic_acquisition.py modules/sheets/tests/test_layered_recovery_queue.py modules/sheets/tests/test_layered_recovery_worker.py modules/sheets/tests/test_formula_layered_admission.py modules/sheets/tests/test_formula_layered_admission_mongo.py -o addopts='' -q`: **37 passed in 4.06s**. Output: `/tmp/zeler-layered-independent-tests.log`.
- `PYTHONPATH=modules/sheets/tests uv run pytest /tmp/test_zeler_layered_independent_probe.py -o addopts='' -q`: **3 passed in 3.52s**. Output: `/tmp/zeler-layered-independent-probes.log`.
- The independent probes admitted 41 concurrent requests into exactly 20 slots
  (19 explicit IDs plus inventory), exercised the actual three-lane runtime
  factory, and cancelled the composite watcher while preserving and then draining
  all three owned lane operations with no remaining tasks.
- The peer's discovery correction was also executed in the final 38-case focused
  run: discovery-local quota deferred without a source attempt, while genuine
  source timeout retained its retry. That run additionally exercises pacing
  authored by this reviewer; its success is not independent pacing certification.
- Parent full-suite log records **4599 passed, 9 skipped** in 275.57s. This run
  began before the last nested-deadline/join corrections; parent must attach
  final affected/full checks before treating it as final-tree gate evidence.
  Protected rs0 checks skipped with ambient MONGO_URI need their separate command.

All Mongo execution used the dedicated isolated loopback replica on port 27028
and unique disposable databases. No production Mongo connection was made.

## Behavioral compliance

| Approved behavior | Inspected and executed evidence | Local result |
| --- | --- | --- |
| Basic inventory skips optional enrichment, retains variation identity | Basic acquisition tests plus real Mongo worker batch of 20; unexpected enrichment calls fail the harness | PASS |
| Freshness belongs to actual source observations | Repeated unchanged base re-observation updates the base cut; existing enrichment dates remain unchanged; changed references become basis_mismatch | PASS |
| Unknown/missing acquisition proof stays unavailable | Untracked changed quality receives invalidation; calculator requires observed enrichment states; quality explicitly rejects basis_mismatch without relabeling source time | PASS |
| Concurrent writes and seller scope remain protected | Real Mongo same-timestamp CAS conflict rejects overwrite; scoped identity/status reads restrict item IDs; other-seller admission remains independent | PASS |
| Reserved slot, active dedup, bounded occupancy | Isolated queue tests and 41-way independent admission probe preserve exact capacity and one inventory slot; active reuse validates allowlist before returning | PASS |
| Disjoint lanes and lease ownership | Claims and expired cleanup apply the same lane filters; quota deferral retains checkpoints and cannot repeat after ownership ends | PASS |
| Independent lane lifecycle and runtime wiring | Blocked ranges allow inventory progress; lane failure is observed; watcher cancellation drains owned work; actual factory shares one pacer and queue while retaining distinct discovery/detail clients | PASS |
| Independent formula recovery and bounded API admission | CALIDAD/CALCULADORA request base and explicit enrichment independently; authenticated repeated ASGI calls persist only two intended jobs; sequential batch intents share three-second deadline | PASS |
| No public signatures, schema migration or TTL extension | Diff inspection retains request/matrix contracts, existing queue fields and 15-minute freshness | PASS |

## TDD and limitations

TDD progress artifacts for basic, queue and admission record RED/GREEN cycles,
companions and existing-test baselines. Tests exist and their current focused
runs pass. Historical RED execution is supported by the apply records, not
independently replayed against reconstructed historical source trees.

The queue progress note still contains stale wording about pending factory and
combined checks; update it to the observed results before delivery. This is an
evidence-record issue, not an observed implementation failure.

The narrative layered requirement is not represented by native requirement or
scenario headings. Native counts remain seven requirements and ten scenarios
for the earlier change; this scoped assessment does not claim those full-change
requirements/scenarios completed. Returns is intentionally outside this user's
current recovery unit.

Task 6.5 final gate aggregation/independent peer confirmation and task 6.6 exact
image delivery, two real inventory cycles within freshness, and the 35-case live
Sheet retest remain outstanding. The 1,900-item harness is local synthetic
available-source evidence and cannot establish production latency by itself.
The canonical full-change SDD report must remain pending until its actual
acceptance obligations are met. Validator executable was located at
`/home/eduardo/.local/bin/gentle-ai`; no missing-tool blocker is asserted.

No additional executable defect was found in the independently inspected
base/queue/consumer/API scope. Peer-discovered discovery and sibling-drain quota
issues were returned for bounded correction and must retain their separate
independent confirmation.


Final independent local confirmation: both pacing findings were corrected and
38 focused cases passed on the final implementation. Other-unit verification
passed 37 cases plus three independent concurrency/factory/cancellation probes.
Full runtime acceptance remains pending; these local results authorize no claim
that production has changed yet.


## Verified release proposal

Source commit: `ef0c4bb6d6d50d4264ed1560fd101268748fbecd` on connected main.
Both Cloud Builds succeeded and passed immutable digest/build/source verification.
Deploy worker then API on platform-vm, us-central1-a, zeler-platform-dev.

- sheets-worker: build `f450f504-335b-4812-80a1-da155c539485`, image `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:0450c9bf6f5af7ac2778f864a768d2de969c90b0f7c07a71a540c25f655e8f91`.
- sheets-api: build `1aebc489-0238-47fc-8290-fba4e4b180d5`, image `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:6d9ad5434315ceef9b7b283e0babbc7d865377f9eced1fcc7963c43904e24226`.

Rollback: previous running worker `sha256:25c2b64a80e70c518689f219740ca50434b62d3f1384264129568da266fb4674` and API `sha256:3b972a4bde3549f72a5c318c1f91c5cbb56d87e0d576d5ba56a3f8b5cd3eca6e`; registration attestation uses API source `1df949fbd2653e2b63648e013b3c330eef92e61f`. No schema/registry changes, cleanup or other-service restart. Capacity is rechecked before attestation/pulls and after deployment. Verify running digests, consumer/dependency readiness, settling health and two live inventory cycles.
