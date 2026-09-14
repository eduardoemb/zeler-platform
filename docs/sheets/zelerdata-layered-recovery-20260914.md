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
