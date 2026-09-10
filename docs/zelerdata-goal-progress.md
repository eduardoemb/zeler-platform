# ZelerData stabilization evidence

Goal source: user attachment `pasted-text-1.txt`, confirmed grill summary
`grill/estabilizar-zeler-platform/summary`. Execution uses Goal, not SDD.
User authorized commits, Cloud Build, GCP deployment and necessary runtime work.
Keep unrelated `.codegraph/` files untouched in both repositories.

## Acceptance ledger

- [ ] All 52 formulas: contracts, truthful values, HTTP production smoke.
- [ ] Representative formulas in a real Google Sheet and existing app surfaces.
- [ ] Async Mercado Libre recovery persisted in Mongo for subsequent queries.
- [ ] Required coverage/freshness; optional NA; explained unavailability.
- [ ] Mongo schemas/indexes/persistence/isolation and actual service operations.
- [ ] Purpose-complete data and minimum PII controls, including deletion.
- [ ] Current official orders API contract verified/migrated as necessary.
- [ ] Entire custom-function execution below 30 seconds; measured p95 budget.
- [ ] Evidence-backed simplification and preserved verified consumers.
- [ ] Deployed source/image correspondence and final regression/smoke.

## Real Google Sheet: all-52 first pass and user add-on update, 2026-09-09

### All 52 formula HTTP responses observed through the real Sheet, 2026-09-10

Local correction implemented (not committed or deployed): item requests larger
than 20 IDs now reuse the existing explicit-ID continuation (`CatalogRecoveryRequest`
and persisted `catalog_offset` vocabulary). One job retains the full request;
the worker acquires only the next 20 IDs and uses existing lease/retry/failed-chunk
handling. Small requests and inventory discovery keep their existing behavior.
No capacity, freshness, concurrency or source scope was widened.

TDD extended the real-Mongo 401-ID test: catalog passed, items failed with
`MLA401` absent before the fix. Afterward all three sources retain their full
request and can admit a questions job. Added worker tests reconstruct each
continuation from Mongo after restart and prove remaining chunks execute after
the first chunk exhausts retries. The lease-exhaustion/reopening test now also
covers items. Seven focused cases passed; the combined API/recovery regression
passed 487 tests in 99.41s. Ruff check passes and format checks 509 files.
Mypy had internal-error/segfault runs during an environment interruption;
`uv run mypy --no-incremental --show-traceback .` subsequently passed all 509
files. A repeated focused run initially skipped because the dedicated local
Mongo had stopped (exit 255); that skipped run is not acceptance evidence.

Rollback boundary: revert only this explicit-item continuation extension in
API/queue/worker and its tests; do not remove existing catalog continuation or
the prior order interval correction. Before production, verify runtime job
collection validator compatibility and deploy matching Sheets API/worker images
from the tested commit; old workers cannot process these new large item jobs.

Pre-deployment read-only VM/container check confirmed the jobs collection exists
and has no validator (`validator_present=false`); no schema mutation is needed
for this extension. This observation does not close the general Mongo hardening
gate. Update the worker first, verify stable health, then update the API so no
new-format item jobs reach an old worker. For rollback, restore the old API first
and retain the new worker until all admitted large item continuations have drained;
do not delete requests or hand pending large jobs to the old worker. Final focused
rerun after restarting the stopped local test Mongo passed seven cases in 1.47s.

Committed and pushed as `208decf296f8f0b8d9f39925421a745aaf337510`.
Two single-image builds with `requestedVerifyOption: VERIFIED` were submitted
from that exact connected-repository revision and observed WORKING:

- Worker: `85085827-1ab5-478f-8c30-46cd63cac355`.
- API: `a452d4fc-63ea-45b7-a37d-36f3c1c41255`.

No deployment has occurred for this commit. Poll these build IDs; do not submit
duplicates because a local polling process disappears. Verify resulting digests
and source provenance before the worker-first activation described above.

Follow-up diagnosis at `2026-09-10T01:52:40Z`: a sanitized, read-only
VM/container Mongo query found numerous exhausted `item_formula_rows` jobs,
an active item recovery, pending buybox recovery, and an expired questions
marker whose failed recovery had not been reopened by the preceding smoke.
This suggests admission pressure but does not prove causality for each live call.

The admission defect itself is reproducible against the dedicated local Mongo
with the deployed source's actual `_request_formula_recovery` and
`FormulaRecoveryQueue`: request 401 synthetic publication IDs, then a questions
interval for the same synthetic seller context. Result: `item_admitted=false`,
400 IDs persisted across 20 jobs, and `questions_admitted=false` with zero
questions jobs. The remaining publication has no durable intent. The isolated
test database was removed afterward; no production writes or Mercado Libre
requests occurred. Reproducer: `/tmp/zeler-item-admission-repro.py`, executed
with `uv run python`; this is a diagnostic, not a committed regression test.

Next correction must retain the entire explicit item request in one bounded,
durable continuation rather than fan out into 20 active queue entries and lose
the tail. Catalog already has a continuation mechanism and a real-Mongo
401-ID regression in `test_formula_recovery.py`; item recovery does not.
Reuse/generalize that proven mechanism with strict schema and restart/failure
coverage. Do not increase capacity, widen requested identities to all inventory,
mark missing fields optional, or relax freshness to hide this defect.

Recalculated all 52 existing anchors in `Goal_Pruebas_20260909`, in groups
of at most eight, preserving arguments and changing only the existing cuenta
reference's trailing whitespace. No token was read, copied, created or revoked.
The production API log window beginning `2026-09-10T01:45:48Z` contains exactly
52 parsed `formula_execution` events, one per expected formula, all HTTP 200
and phase `serialization`. The logs deliberately omit account/request IDs;
the match is by formula and intervention window, not exact request-ID correlation.

Endpoint durations range from 11.366 to 9498.960 ms; pooled nearest-rank p95
is 4841.175 ms. This is one sample per formula and excludes Apps Script/network/
Sheets overhead: it does not close the whole-custom-function 30-second/p95 gate.
Bounded readback of three rows by 40 columns per anchor found no cell errors or
`SERVICE_UNAVAILABLE`. Exactly 26 samples contain `DATA_UNAVAILABLE`, including
five tables with bare field markers (catalog variants and quality); the other
26 require semantic and complete-output review. Orders again returned tabular
data, but this pass sampled only its first two data rows. Optional NA, empty
results and header-only results are not counted as correctness passes.

Per-formula sanitized HTTP timings and sample classifications are recorded in
`docs/sheets/zelerdata-goal-smoke-20260910.json`. Readback included effective
formatting; native visual fit remains unverified. No production code, image or
runtime configuration changed in this pass. Next: verify recovery/freshness for
the unavailable families and explain field-level absence without mistaking HTTP
200 or a narrow sample for complete, trustworthy data. All acceptance gates
remain open.

### Order recovery: independent interval proofs (local, not deployed)

Recovery now acquires only the requested orders interval instead of expanding
May to September because August was already reconciled. Successful publication
retains other unexpired interval proofs with their original expiry. Gaps are
never certified, and expired or undated legacy proofs are not retained. Each
interval still requires complete authoritative acquisition and atomic publication
of normalized rows, coverage and queue completion under the existing lease guard.
Questions and other products keep their existing behavior.

TDD first reproduced the expanded search bounds in a real local Mongo test.
Enabling the committed strict validator then reproduced rejected publication
until the schema was extended; a legacy null-expiry case also failed before its
guard was added. Tests cover subsequent publications, repository reads, gaps,
independent expiration and stale parent state. Root Ruff check/format and Mypy
(509 files) pass. Recovery/read-model regression passed 442 tests in 92.65s
without skips. After that run, an added invalidation scenario reproduced stale
retained proofs being resurrected by a later publication. The final state guard
fix passes all three interval lifecycle cases (1.10s); the root quality checks
were repeated successfully. Repeat the complete regression on this final source
before building images.

Final commit `d3e457af1e330e3de06a9354b7c498765e1cf5a3` was pushed to
`origin/main`. The final regression passed all 442 cases in 92.18s without skips;
all 316 formula handler cases passed in 1.10s. Schema export/Sheets contract
tests passed 39 cases in 0.24s using `--import-mode=importlib` (without it, mixed
test directories caused a collection import collision; that failed invocation
did not execute tests). CI lint `34424977074` succeeded; test `34424977054`
was last observed running.

Both single-service, VERIFIED-option Cloud Builds succeeded from that exact
connected-repository commit; runtime provenance attestation and deployment remain
pending:

- API build `97bd3465-57c1-42e5-b70f-e67657b6f831`, digest
  `be0a539fa0b2d35efdaab07da16d6dd9a3c524081c18c12b0fb20e4306376229`.
- Worker build `8d051f94-13ec-4b35-9762-b8b218ae4a8e`, digest
  `53a91d929e2c1551486a9de5eae9b282cce948736ca210de9a5cbaf8c64ed5df`.

Read-only VM checks still show the old API/worker healthy and approximately
8 GiB available on root. The May job reached terminal failure after three
attempts at 01:15:07.900Z; the later August jobs completed, extending top-level
coverage through September 11. No new formula request or data repair was issued
in this verification pass.
The targeted VM/container validator comparison confirmed exact equality to the
previous committed schema, strict validation and rejection of invalid documents;
the new schema is not applied (`writes: 0`). Staged desired schema SHA-256 is
`6b5c4aba104b4302dcba001e526918aefe4250f78f935dcbaa290dbfaa33bac7`.
Temporary checker `/tmp/zeler-order-interval-validator-check.py` is read-only;
the desired schema is staged on the VM and in the old worker container at
`/tmp/zeler-order-interval-freshness.json`. No validator or service was changed.

Activation attempt `zeler-order-interval-activate-d3e457a.service` started
01:25:01Z and terminated at 01:25:06Z before any mutation: the running-recovery
guard (helper line 67) refused deployment. Follow-up VM/container evidence found
an active `item_formula_rows` job, attempt 1, with heartbeat 01:26:07.989Z and
lease through 01:36:07.989Z; both old Sheets images remained healthy and the
deployment backup did not exist. This is a wait for active recovery, not a reason
to rebuild or rerun an uncertain deployment. CI test `34424977054` still reports
its pytest step in progress. Recheck these exact jobs before the next activation.
Prepared helper `/tmp/zeler-order-interval-activate.py` (local and VM), SHA-256
`97ef71ca6b883e12d8a5de5b7499758dac67a1a22e7c94dcca9073c3ca0251ec`,
verifies both new/rollback images, applies only the additive freshness validator,
then activates API and worker while checking gateway identity/health is unchanged.
Its exact backup path is `/opt/zeler-platform/docker-compose.yml.pre-order-interval-d3e457a`.
The next read-only check returned zero running recoveries. Retry unit
`zeler-order-interval-activate-d3e457a-retry1.service` started at 01:28:06Z and
was confirmed active/running, not yet terminal. CI test `34424977054` has now
completed successfully. Poll that exact retry unit; do not launch another one
because a local SSH observation times out or fails.
Retry completed successfully at 01:32:19Z (`Result=success`, inactive/dead).
It verified new API/worker provenance at 01:28:27/01:28:49Z and rollback
provenance at 01:29:08/01:29:25Z, applied and verified the targeted additive
validator at 01:29:30Z, then confirmed stable healthy API at 01:31:57Z and
worker at 01:32:19Z on the exact new digests above. The terminal
`activation_complete` confirms source `d3e457af1e330e3de06a9354b7c498765e1cf5a3`
and the helper's unchanged healthy gateway check. Do not rerun this deployment.
The API's former digest `a94b3a31d82322ae0019f1dffd0088db8f7d87dfe9844f6c5aaa757a962d3543`
and worker's former digest `5ccfc9a004ee27037728242e75313cbeadd8478979d18da90e90669fa24eeb1f`
remain the recorded rollback pair; no stored data was deleted. Real Sheet
recalculation and completed recovery on these new images remain unverified.

### Orders: first successful real Sheet read after interval deployment

On the deployed `d3e457a` images, all three August orders jobs completed at
01:34:11.535Z, 01:34:21.570Z and 01:34:31.608Z. The May job completed on its
first attempt at 01:36:22.071Z. A bounded, sanitized gateway log inspection
confirmed search bounds remained May 1 07:00Z–May 30 06:00Z (hour-precision
upper bound), offsets 0 through 1200: 25 search HTTP 200, 1231 detail HTTP 200,
2 detail HTTP 206, 8 detail HTTP 429 and 7 hosted-shipment HTTP 404. These are
request counts, not a distinct-order census. Mongo readback retained all three
August proofs with their original expiries after May became the top-level proof.

The first recalc of `Goal_Pruebas_20260909!A42901` still returned update-requested
DATA_UNAVAILABLE. A read-only API-container reader probe isolated 96 expired
shipping costs, with zero missing cost values, documents, observations, order
IDs or item IDs. The existing shipment recovery was actively running. After it
finished, the same reader returned 101 rows, no recovery or additional recovery,
and zero writes (this probe is explicitly not HTTP authentication evidence).

The next real Google Sheet recalc succeeded. Connector readback of
`A42901:AN43002` found 13 expected headers, 100 data rows, zero cell errors,
zero DATA_UNAVAILABLE, 500 numeric cells and 11 NA cells exclusively in
`ID Carrito`. No cost/commission column contained NA. Row 43002 was empty.
The anchor now uses nine spaces appended to the token reference; dates remain
August 8–September 6, state `todos`, headers `si`. Only that owned formula cell
was changed, with the `userEnteredValue` mask; the credential cell was not read.

This proves one representative formula can recover then return data through the
real add-on. It does not prove all 52 authenticated HTTP smokes, semantic equality
of every field, whole-function p95, or long-term freshness behavior. Native visual
fit is not verified; no layout/formatting change or credential-workbook export
was performed. Continue the remaining acceptance ledger instead of rebuilding
these already deployed images.

Deployment remains pending: update only the freshness validator from the approved
VM/container context, then deploy verified Sheets API and worker images. Older
APIs can read the newest top-level interval but do not recognize retained ones.
Rollback boundary: the orders interval selection/retention, reader support and
optional schema field; leave existing documents and the additive validator intact
when rolling back images. No data deletion is needed.

This is not durable acquisition checkpointing: a single requested interval may
still exceed the unchanged 240-second deadline. Production must prove that May
and pilot recovery complete and remain readable on subsequent real Sheet calls;
if not, bounded durable progress remains necessary. No acceptance gate is closed
by this local correction.

### Order projection identity: SKU mismatch correction deployed

A read-only VM/container probe of the pilot's 100 orders isolated the remaining
fixed-fee NA: the canonical item exists, exactly one formula projection exists,
and its fixed fee passes the current reader validation. The order and projection
both have no variation, but their SKUs differ. No production data was changed.

Order tables now fetch seller-scoped projections by item ID and associate them
by item/variation identity, preserving the historical order SKU and SKU filtering.
Duplicate projections for an identity are not selected arbitrarily. Other
SKU-based consumers retain their existing lookup contract. This also removes
the order projection query's arbitrary 500-row/multiplier cap.

TDD reproduced four failures: two renamed-SKU cases and two wrong-variation
matches. All 66 order/question handler cases pass after the correction;
`uv run pytest modules/sheets/tests/test_formula_handlers*.py -q` passes all
316 cases. Root Ruff check, format check and Mypy (509 files) passed.
Runtime consumer verification of the changed behavior is **pending**: the
read-only probe proves the defect, not the complete formula result.
CI test `34417158529` and lint `34417158528` passed source
`c36dd406d599141f6d26ef5b6db309c45c1051c8`. Cloud Build
`1d06a669-b92c-4ebb-b1da-2f9193b81b5e` produced API digest
`sha256:a94b3a31d82322ae0019f1dffd0088db8f7d87dfe9844f6c5aaa757a962d3543`.
The initial activation failed at its 300-second pull timeout, before Compose
mutation; the old API remained healthy. After confirming terminal failure and
no backup/config mutation, a separate pull completed with the exact digest.
The same activation unit `zeler-order-identity-activate-c36dd40` was restarted
and finished inactive/dead, exit 0, with explicit `activation_complete`.
It verified new/rollback provenance and the 13-scope/6-routing-key fingerprint,
enforced the 5 GiB floor, confirmed stable API health and unchanged worker ID.
Rollback API remains `d55f8bb4057e54919b0630cf05dc32a28a78901a16013ecaa80726f36ee71ea4`;
Compose backup is `docker-compose.yml.pre-order-identity-c36dd40`.

Post-deploy internal reader checks found 96 expired shipment-cost observations
(all documents and costs exist), so no successful complete result was claimed.
The live Sheet later also reported expired order coverage. The authorized
`Goal_Pruebas_20260909!A42901` formula was recalculated with four spaces in its
token-reference expression, preserving dates/filters and all other cells.
VM readback at 23:50 UTC showed the August 8–September 6 request pending while
the May request was running (attempt 3). No direct queue or Mongo edits occurred.
Repeat the real Sheet order read after normal recovery and check the fee cell.
A separate read-only probe inside the deployed API loaded the same 100 orders
and invoked the corrected projection lookup plus fixed-fee reader for each line:
zero fixed-fee NA findings, zero writes. This proves the SKU association defect
is corrected in runtime independently of the still-pending coverage refresh.
Rollback boundary: the order-only projection lookup and associated regression
tests in `handlers_orders_questions.py` and its handler test file; no schema,
worker, token, or production-data migration is involved. This does not resolve
the wider missing/ambiguous projection availability contract or other goal gates.

### Order recovery: bounded detail acquisition (local, not deployed)

Current read-only VM/container job inspection confirms the pilot August range
completed at 23:53:17 UTC on September 9; both August 11 variants completed
afterwards, with coverage updated at 23:53:57. May remains failed after three
attempts (`source_temporarily_unavailable`, 23:52:52). This supersedes the pending
job observation above, but is not a fresh Google Sheet result or latency proof.
No queue or production data was edited.

Order acquisition now joins waves of at most four details for both search rows
and known orders absent from search. Identity/date/ownership validation, complete
publication, expanded coverage, 10,000-order budget and 240-second timeout remain
unchanged. Original error types reach retry classification; cancellation joins
in-flight requests. There is no formula HTTP or schema change.

TDD: after restarting only the stopped dedicated local Mongo container, the new
integration test failed on old code (`peak == 1`, expected four). All six new
cases pass after implementation: normal completion, transport failure and
cancellation, each for discovered and previously known orders. Tests use real
local Motor/queue state and controlled detail calls; publication is mocked, so
they do not establish live Mercado Libre throughput or actual publication.
`uv run pytest modules/sheets/tests/test_formula_recovery.py -q` passes all 416
cases, without skips. Root Ruff check/format and Mypy (509 source files) pass.
Commit `31c62dea82637dd89e90bab7689c80013e032e8b` is now on `origin/main`.
Cloud Build `a0f57541-c833-43b2-b12a-79ccef1e64c6` completed successfully from
that exact connected-repository revision, producing only Sheets worker digest
`sha256:f5841723a09b01529b12d896fb9c5429ab51dd27faa1992256d103d9e4ea1ca7`.
The first local submission crashed; a Cloud Build listing confirmed no new job
before retry. A later status-query crash was handled by re-polling the same build,
not rebuilding. CI lint `34419413656` and test `34419413515` both passed.

Read-only VM preflight passed with 9.2 GiB free. Running API remains healthy at
`a94b3a31d82322ae0019f1dffd0088db8f7d87dfe9844f6c5aaa757a962d3543`, worker
healthy at `637a335e0b68955acff21c6d09f8246788080cdd57eb4f7b8c07f06e4adbc732`.
Helper `/tmp/zeler-order-concurrency-activate.py` is now on the VM; local/remote
SHA-256 agree (`552a9a95acb70744941919ca94f7428609f9b9c68f4265fa6e4618e246b83b73`).
Unit `zeler-order-concurrency-activate-31c62de.service` completed successfully:
journal contains both provenance confirmations, stable new-worker health,
`activation_complete=true` and `Deactivated successfully`; subsequent transient
unit state is not-found/inactive/dead. New worker digest is running/healthy;
API digest remains unchanged/healthy. Initial SSH failure was followed by a
`LoadState=not-found` check before starting this unit. Do not rerun activation.
The helper verified offline registration fingerprints, capacity, no running
recovery, exact Compose replacement and unchanged API container identity.
Rollback worker is digest `637a335e0b68955acff21c6d09f8246788080cdd57eb4f7b8c07f06e4adbc732`
from `aee2ef1`; backup is `docker-compose.yml.pre-order-concurrency-31c62de`.

The real Sheet anchor `Goal_Pruebas_20260909!A42901` still displays
`DATA_UNAVAILABLE: Actualización solicitada; vuelve a intentar.` with the four-space
formula unchanged. A fresh read-only API-container handler probe subsequently
found one expired shipment-cost observation (document, cost and observation all
present), no missing orders/items, zero writes. This is not an authenticated
HTTP smoke or successful Sheet recalculation. Preserve freshness checks.

After deployment, the same authorized anchor was refreshed from four to five
spaces in its token-reference expression; only `userEnteredValue` changed,
with no validation/formatting or other-cell edits. Readback still reports
update requested. VM inspection confirms May recovery running (attempt 1,
started/updated `2026-09-10 00:12:39.767 UTC`), with August pilot pending.
No direct queue edits occurred. Poll this specific job before another recalc;
the new worker's 240-second recovery outcome is not yet known. Native visual
fit remains unverified; no workbook export or credential-cell read occurred.

Post-deploy May attempt ended at `00:15:15.228 UTC`: **155.461 seconds**, with
`source_incomplete`, not timeout. August pilot completed at `00:15:30.887 UTC`.
This does not prove successful May recovery or a p95. Read-only gateway log
aggregation for the attempt shows 25 successful search pages, 1,198 HTTP 200
details, two HTTP 206 details and four shipment-relationship 404 responses.
The last request was search, after 1,200 details. Script:
`/tmp/zeler-may-recovery-log-summary.py` (local and VM); no IDs/payloads printed.

Replaying only the last two logged search URLs through the approved bootstrap
gateway returned stable total 1,231: offset 1,150 has 50 rows; offset 1,200 has
31. Neither page has invalid/duplicate IDs or cross-page overlap, but the final
page contains **one date outside the requested interval**. Thus the existing
search date validation is reproducibly rejecting the response; do not skip
validation or publish the out-of-range row. Investigate exact boundary semantics
and authoritative detail before choosing a correction. Read-only script:
`/tmp/zeler-may-last-page-probe.py` (local and VM). No business/queue writes.
The repeated probe identifies the boundary discrepancy without printing an
order ID: requested inclusive upper timestamp `2026-05-30T06:59:59.999Z`, returned
creation timestamp `2026-05-30T07:58:51Z`. This is nearly an hour, not millisecond
rounding. Detail confirmation and API date-filter semantics remain pending.

### Order search upper hour: source-confirmed correction (not deployed)

The follow-up approved-runtime probe confirms HTTP 200 detail with matching
identity, pilot seller and creation timestamp (`03:58:51-04:00`, identical to
the search's `07:58:51Z`). Holding the query otherwise constant, an upper bound
of `06:00:00.000Z` returns total 1,230 and 30 final-page rows, none outside the
original interval; `06:59:59.999Z` reproduces total 1,231 and the outside row.
This is source-read evidence, not a complete new recovery or full inventory
comparison. No Mongo/queue writes or credential output occurred.

Official [orders documentation](https://developers.mercadolibre.com.mx/gestiona-ventas)
states date filters use hour precision and discard minutes, seconds and
milliseconds. Search-index excerpts were available; direct page fetch returned
403. The live probe independently confirms the behavior relevant to this fix.

Recovery now sends the beginning of the last included hour for the upper search
bound. It retains exact requested-range checks on search and detail rows,
ownership, pagination totals, atomic publication and the existing 240-second
budget. No out-of-range rows are silently accepted. The historical backfill
query builder is not changed by this unit.

TDD: the new `hour_boundary` integration case failed before the change; all 18
`test_order_recovery_publishes_only_complete_owned_inventory` cases pass after
it. The boundary case includes an order in the last valid second and verifies
complete persistence/coverage, preventing the coarse request limit from becoming
a coarse local cutoff. Root Ruff check/format and Mypy (509 files) pass.
`uv run pytest modules/sheets/tests/test_formula_recovery.py -q` passes all 417
cases without skips. Runtime now uses worker `1c9ca38` and
API `c36dd40`; May recovery still needs post-deploy functional verification.
Code rollback is only the upper search-bound expression
and its boundary regression, not concurrency, stored orders or validation.

Build/deploy preparation for committed source
`1c9ca38367993632fcc669985d19de124bfe2e88` (also `origin/main`): Cloud Build
`290272a2-6aa5-49f1-91b8-af732cb4633a` completed SUCCESS from that exact revision,
single worker image, verified provenance requested. Resulting digest:
`sha256:56739389c470b118800a1b94f63fa6fea1c62b2707d440cd6f7eb6b26c7e95b4`.
CI lint `34421141720` and test `34421141680` passed for the exact source.
Activation completed at `2026-09-10T00:36:47Z` in
`zeler-order-hour-activate-1c9ca38-retry1.service`: new and rollback provenance
verified, exact new worker digest healthy and stable, API identity/health
unchanged, explicit `activation_complete`, terminal systemd success.
The first unit failed before creating the Compose backup; the old worker stayed
healthy. Its generic RuntimeError did not establish the exact cause. Read-only
checks then confirmed 8.7 GiB free, zero running recovery jobs, one old Compose
image match and valid provenance for both images. The helper gained sanitized
failure line numbers before the successful retry; no acceptance checks changed.
Runtime rollback remains worker
`f5841723a09b01529b12d896fb9c5429ab51dd27faa1992256d103d9e4ea1ca7`
from `31c62de`, build `a0f57541-c833-43b2-b12a-79ccef1e64c6`; backup:
`docker-compose.yml.pre-order-hour-1c9ca38`.
Next: trigger recovery through normal Sheets use, then verify May completion
and truthful persisted readback. Deployment health alone does not close these gates.

Post-deploy Sheets check (`2026-09-10`, about 00:38–00:42 UTC): changed only
`Goal_Pruebas_20260909!A42901.userEnteredValue`, adding the sixth trailing space
to the token reference expression; pilot dates/filters, formats and validation
were preserved. No token value was read. Native anchor readback still says
`DATA_UNAVAILABLE: Actualización solicitada; vuelve a intentar.` Visual fit has
not been verified; no credential-bearing workbook export was made.

Normal recalculation completed the pilot orders job at `00:38:13.518Z` and
started May recovery at `00:38:14.439Z`. May ended failed after three attempts at
`00:40:57.634Z`, reason `source_temporarily_unavailable`; two additional August
windows also failed with that reason. Sanitized gateway logs for 00:38:13–00:41:00
show 696 order-detail 200s, 20 search 200s, one order-shipment 404 and 30
order-detail 429s. This is not successful May recovery and does not yet identify
whether throttling originated locally or upstream. All three services remained
running/healthy. Intermittent local gcloud exit 139 and SSH handshake failures
were followed by successful read-only inspection, not service restarts.

The internal pilot reader (not an authenticated HTTP test) now reports 97
expired shipment costs, zero missing shipment documents/costs/observations,
zero missing orders/items, and zero writes. Related shipment recoveries failed
transiently. Next investigation: attribute the 429s and make recovery honor
source backpressure without restarting useful acquisition unnecessarily; retain
truthful freshness and whole-range coverage. Current queue retries are fixed
30/60 seconds and `process_one` does not pass response Retry-After to `finish`.

The same gateway interval contains **106 structured local `rate_limit_exceeded`
events for module Sheets**, proving internal throttling was active (not a claim
that every observed 429 has been individually correlated). No quota was changed.
A focused correction (deployed as `37dc9a6` below) retries the same order-detail request up
to three times on `GatewayRateLimitError` with a numeric Retry-After, preserving
already acquired pages in the active attempt. It uses the raw header rather than
the shared client's 30-second cap; invalid/missing headers retain existing queue
failure handling. The existing 240-second job deadline and cancellation remain.
This does not add durable checkpoints or change shipment/other-product clients.

TDD: all four `test_order_detail_waits_for_quota_without_restarting_acquisition`
cases failed before and pass after the change: success after waiting 59 seconds
(simulated), bounded exhaustion, cancellation during waiting, and wrong-owner
rejection after retry. Root Ruff check/format and Mypy (509 files) pass. Full
recovery suite (`uv run pytest modules/sheets/tests/test_formula_recovery.py -q`)
passes all 421 cases without skips; live end-to-end proof remains pending. Rollback
boundary is the order-detail request retry loop and its new regression only;
retain the prior hour-boundary, concurrency and ownership protections.

Quota-wait source is committed/pushed as
`37dc9a6609b469e014995fa23997fee38b194102`. CI lint `34422807219` and
test `34422807153` both passed for that exact source. Cloud Build
`7e4d0be0-9c45-49b7-8413-96ecd2646fb0` was submitted once from that exact
connected-repository revision, single worker, VERIFIED option. Terminal status is
SUCCESS; image push ended at `2026-09-10T00:50:16.473Z`; digest
`5ccfc9a004ee27037728242e75313cbeadd8478979d18da90e90669fa24eeb1f`.
Build and CI succeeded; no rebuild is needed for this correction.

Prepared helper `/tmp/zeler-order-quota-activate.py` exists locally and on VM,
matching SHA-256 `d30a9cd907fb19c4ffb728158d1fccde1e443108211cf168db5013fae6af8b89`.
It retains the verified single-service activation gates, with
rollback worker `56739389c470b118800a1b94f63fa6fea1c62b2707d440cd6f7eb6b26c7e95b4`
from `1c9ca38` / build `290272a2-6aa5-49f1-91b8-af732cb4633a`; intended backup
`docker-compose.yml.pre-order-quota-37dc9a6`. Read-only preflight: 8.2 GiB free,
worker on that rollback digest and API on `a94b3a31...`, both running/healthy.

Activation completed at `2026-09-10T00:58:47Z` through
`zeler-order-quota-activate-37dc9a6.service`. Journal confirms provenance for
new and rollback sources, healthy/stable worker on exact digest `5ccfc9a0...`,
explicit `activation_complete`, and terminal systemd success. The helper also
verified unchanged API container identity and healthy state. One local gcloud
exit 139 during polling was followed by a successful read of the same unit;
activation was not repeated. Next: normal Sheets recalculation and complete
May/pilot recovery readback; the 97 expired shipment costs remain unresolved.

Live quota-wait verification (`2026-09-10T01:00Z`): only
`Goal_Pruebas_20260909!A42901.userEnteredValue` was updated to seven trailing
spaces in the token reference expression, preserving dates/filters and formats.
Anchor readback remains the update-requested DATA_UNAVAILABLE message; native
visual fit is not verified and no credential-bearing export was made.
Pilot orders completed at `01:00:43.521Z`. May attempt 1 started
`01:00:44.721Z`, then became pending at `01:04:44.744Z` (240.023 seconds),
`source_temporarily_unavailable`, next eligible `01:05:14.744Z`.
This matches the existing 240-second deadline; do not claim successful recovery.

Sanitized search logs prove the actual acquisition was May 1 07:00Z through
September 7 07:00Z (hour-precision request upper 06:00Z), not only May: fresh
pilot coverage expanded the requested range via `_coverage`. During the attempt,
gateway logs show 48 search 200s, 2,363 detail 200s, two detail 206s, 14 detail
429s and 18 order-shipment 404s. Coverage stayed at August 8–September 7.
The quota wait alone is insufficient. Next: preserve bounded acquisition
progress and honest range coverage without repeated whole-union acquisition;
do not raise timeouts or label partial data complete. Automatic retries remain
owned by the existing queue; no direct queue edits or worker restarts occurred.

Rollback boundary: `_order_details` and its two `_orders` call sites plus the
new concurrency regression; retain the earlier detail validation and header fix.
Before claiming the timeout resolved, build a verified Sheets worker image from
the intended committed source, deploy with the existing service-specific safety
gates, and measure complete recovery and subsequent formula readback. Other
acceptance gates remain open.

### Order recovery: bracketed missing-content header fix (worker deployed)

The failed orders job targeted May 1–30; its existing coverage expanded acquisition
to May 1–September 10 (132 days). Two read-only source searches returned 1,231
orders for the requested interval and 2,359 for the union: neither exceeds the
10,000-order budget. Fifty initial details passed (HTTP 200). Sanitized gateway
logs for the original job interval showed 873 HTTP 200, two 404 and one 206,
without 429. The locally owned order behind that 206 was re-read through the
normal Sheets identity: `X-Content-Missing: [buyer]`, valid identity, seller and
nonempty order items. No identifiers, buyer data or credentials were output.

The parser previously treated `[buyer]` as an unknown field. A shared parser now
accepts the observed non-JSON bracketed list and existing comma-separated fields,
retaining the known-field allowlist and rejecting malformed/unknown headers.
Both order location and detail validation use it. Missing buyer/shipping data
remains explicitly unavailable; no scope, schema or purpose requirement changed.
TDD first failed three bracketed-header cases (seven passed); the corrected
header and Mongo consumer tests passed 18 cases. Full recovery suite: **410
passed in 86.59s**. Root Ruff check/format and Mypy passed (509 files).

Worker source `aee2ef1905e49e077bae6a9fb37dbaeecb10e5e5` is now deployed.
CI test run `34410085664` passed. Cloud Build
`1ebdf444-1499-4006-a549-f308deafa0cf` produced worker digest
`sha256:637a335e0b68955acff21c6d09f8246788080cdd57eb4f7b8c07f06e4adbc732`.
The VM reverified both new and prior worker provenance, enforced the 5 GiB
disk floor and checked for running recovery jobs before replacement. Unit
`zeler-order-header-activate-aee2ef1` finished successfully with explicit
`activation_complete`, stable worker health, and unchanged healthy API container.
Only the worker was replaced; the API remains on `7256f84`. The prior worker
digest `sha256:7c39fc98174082a5ef8e5b1b359b71ec8634b33d499d753676c27046a6aa75f1`
and Compose backup `docker-compose.yml.pre-order-header-aee2ef1` are retained.

The deployed parser passed a synthetic HTTP 206 `[buyer]` assertion. A follow-up
read-only probe confirmed local ownership of the same real order, then invoked
the deployed `FormulaRecoveryWorker._order_detail` through the normal Sheets
gateway identity, including its shipment recovery path. It passed with matching
identity and exactly `buyer` marked unavailable. No queue claim/publication or
Mongo writes occurred. This verifies the real partial-detail path, not full
recovery or coverage. Normal recovery persistence and consumers remain pending.
Normal Sheet retry was then requested only at
`Goal_Pruebas_20260909!A42901`, retaining August 8–September 6 and existing filters.
VM readback showed the corresponding August 8 07:00–September 7 07:00 job
completed at 23:08:45.438 UTC; two newer-range jobs also completed. The Mongo
coverage marker spanned August 8 07:00–September 10 07:00, updated at
23:09:29.837 UTC. The May job was running at 23:09:30.703 UTC (its old
`failure_reason` is not a new terminal failure). No direct queue edits occurred.
A subsequent normal formula re-evaluation still displayed `DATA_UNAVAILABLE:
Actualización solicitada; vuelve a intentar.` at the anchor. Investigate the
consumer/cache/coverage difference before claiming success. Only the formula
value changed; target validation/format fields remained absent and untouched.
Native visual fit and whole-function latency were not measured by this readback.
The deployed API handler was subsequently invoked read-only with the exact
`_seller_timezone` account resolver and identical formula arguments. It passed
order coverage but raised at `_real_shipping_costs_for_orders` →
`find_shipment_real_shipping_costs` → `_require_shipment_field`: **96 shipment
costs unavailable or stale**. This is the next recovery dependency, not evidence
that the completed order coverage failed. No HTTP authentication was exercised,
queue jobs admitted, or data written by this diagnostic. An initial diagnostic
with a hard-coded Mexico City timezone was invalid for comparison and discarded.
Next inspect shipment recovery state and distinguish absent, explicitly
unavailable, and expired cost observations; do not reread all orders or label
these costs permanently unavailable without source evidence.
Follow-up classification found all 96 documents and costs present, with no
explicit unavailable flags or missing observations: all 96 were expired.
Matching recovery state showed one running job (23:13:30.743 UTC) and one
pending job, without operator queue changes. A subsequent invocation of the
same deployed API handler returned **101 rows**, no primary recovery and no
additional recoveries. The reader now accepts the persisted dependencies.
This is a read-only internal handler result, not HTTP authentication, a Google
Sheets readback, or a source-to-result correctness/count audit. Those checks
remain necessary before accepting the formula.
For the exact requested interval and account-resolved timezone, a read-only
bootstrap discovery probe reported 100 source orders and 100 Mongo orders.
Both source pages (50 each) retained the same total and unique IDs. All 100
identities matched Mongo; status mismatches and total-amount mismatches were
both zero. The repository's `find_orders` has no default 100-row limit.
This supports count/identity/status/amount correctness for the interval, not
every output column or Sheets display. No source payloads or identifiers were
printed and no data was written.
The real Sheet was then re-evaluated only at
`Goal_Pruebas_20260909!A42901` (three trailing spaces in the token expression;
dates and filters unchanged). Bounded readback of `A42901:AD43002` returned
101 populated rows, 13 columns each: one header plus 100 data rows, zero native
cell errors and zero `DATA_UNAVAILABLE` cells. Twelve `NA` cells remain:
11 in `ID Carrito`, one in `Costo Por Unidad`; their source semantics still
need checking. Readback arrived 12.377 seconds after the write acknowledgement,
not a measurement of Apps Script execution or p95. No token value or personal
data was output. Only the anchor formula changed; formatting was preserved.
Native rendered visual fit remains unverified; this establishes returned cell
content, not a complete 52-formula acceptance or every-column correctness.
Read-only detail requests for all 11 orders with missing Mongo `meli_pack_id`
confirmed matching order/seller identities and absent source `pack_id` in all
11 cases. Those cart `NA` values have source evidence. The one fixed-fee `NA`
was traced through the actual SKU resolver and item-row lookup: its required
item formula row is absent, so no listing-price fixed-fee projection is found.
This is not verified optional source absence. Next determine why that owned
order line has no row and recover its product data when possible; do not accept
the remaining `NA` as permanent or change it to zero. No production data writes
or identifiers/payload output occurred in these probes.
Deployment health alone does not establish formula or order coverage acceptance.
Rollback removes only the header parser and its tests from
`formulas/recovery_worker.py` and `test_formula_recovery.py`; legitimately stored
partial-data documents remain compatible and must not be deleted.

### Catalog quality: dedicated User Product route permission

**Route-reuse optimization deployed; full-cycle freshness still fails:** the normal
Sheet-triggered inventory cycle completed 1,900/1,900 at 21:43:03.921 UTC from
enumeration 21:27:33.450 UTC: **930.471 seconds (15m30.471s)**. The previous
cycle took 1,160.896 seconds; this run was 230.425 seconds shorter, but exceeded
the unchanged 900-second enumeration window. Live-service variation means this
before/after comparison is not an isolated causal benchmark or p95.
At age 919.919 seconds, offset was 1,860 and enumeration had already expired;
at terminal readback (age 961.042), only 1,720 member items remained fresh.
All 2,859 membership projection rows persisted. Twenty sampled fresh User
Product quality rows matched canonical state and passed the reader. Existing
source gaps remained (including performance-not-generated, HTTP 400 and rate
limits); completing traversal does not certify every field. No operator
readmission, timestamp refresh, quota change, service restart or freshness-window
extension was used during this cycle. Next work must reduce remaining acquisition
or scheduling cost and prove useful full fresh coverage, not repeat an unchanged
cycle or declare completion from offset alone.

Quality acquisition now
reuses an already learned User Product endpoint only when fresh owned item detail
reconfirms the exact same valid, same-site User Product relationship as the stored
item. It reuses no quality values or timestamps: the endpoint is requested again
and its response undergoes the existing identity validation. Changed, missing or
cross-site links retain item-first discovery and the guarded HTTP-400 fallback.
A known-route failure does not retry through another endpoint to bypass denial.
The supported endpoint is documented in [Mercado Libre listings quality](https://developers.mercadolibre.com.ar/en_us/trends/listings-quality).

TDD reproduced two redundant item calls; both now pass alongside four routing
guards. Known-route 400/403/404/timeout/identity failures preserve the prior acquisition
cut, with no item fallback or duplicate User Product call. The three related test
files passed 250 tests; the recovery suite passed 396 tests in 87.55 seconds. Root
Ruff check/format and Mypy passed (509 files). This is not measured production
savings. Runtime verification must compare request counts and full inventory
freshness under the unchanged quota. Rollback is just this route-selection change
and its tests; existing persisted quality, schemas and scope remain compatible
with deployed `c532ebf`. Source is `7256f84e3708e5111959af943c7e73ee00f1e580`.
API build `7f757af6-a243-4511-bb96-64564ece03ec` and worker build
`3ef288ca-c936-4523-85ec-9350d01cccf3` succeeded, each with one image and verified
provenance checked against the exact connected-repository commit. API digest:
`sha256:d55f8bb4057e54919b0630cf05dc32a28a78901a16013ecaa80726f36ee71ea4`;
worker digest:
`sha256:7c39fc98174082a5ef8e5b1b359b71ec8634b33d499d753676c27046a6aa75f1`.
CI lint `34404144321` and test `34404144688` both passed. VM disk preflight
passed (at least 5 GiB free). Download unit `zeler-route-reuse-pull-7256f84`
started at 21:03:39 UTC, reverified API provenance from the VM and then timed out
after its 300-second Docker pull budget. It is terminal `failed`, result
`exit-code`, status 1; the target API image was confirmed absent afterward.
No worker pull, runtime activation or new inventory admission occurred. Do not
restart the same unit on the basis of old progress messages. Diagnose the pull
before a separately identified retry. A successful read-only diagnostic then
confirmed registry reachability (unauthenticated HTTP 401 in 0.176 seconds),
12,008,148,992 free root bytes, and an installed credential helper that returned
credentials in 6.327 seconds without reauthentication. No credential values were
printed. Docker's matching resolution failure contained `context canceled`;
this does not establish the cause of the original stall. One separately named
bounded retry, `zeler-route-reuse-pull-retry-7256f84`, completed successfully:
terminal inactive/dead, exit 0, both exact RepoDigests verified locally on the VM,
10,920,464,384 root bytes free afterward. The prior failed unit remains terminal.
The isolated API contract probe passed for both new and rollback images.
Activation unit `zeler-route-reuse-activate-7256f84` completed terminal
inactive/dead, exit 0, with explicit activation completion for `7256f84`.
All four image/source proofs passed. Recovery inactivity was rechecked after
provenance and before the Compose write. Both new services passed two stable
health observations with their expected digests. No rollback was needed.
Rollback is the compatible `c532ebf` pair. Do not resubmit completed builds.

Post-deployment acquisition dry runs reused the same three five-item inventory
offsets (0, 950, 1895). All validated five items with zero writes. They made
17/20/20 calls in 3.4165/3.8878/3.5989 seconds, versus the prior
20/24/20 calls in 3.9505/4.4749/3.8910 seconds. Total calls fell from 64 to 57
(seven redundant item-quality requests removed, 10.94% of sampled calls).
User Product request counts and sampled failures remained 3/4/0 and 3/2/0:
the optimization did not manufacture missing quality. Timing is a bounded
before/after sample subject to live-service variation, not p95 or whole-inventory
acceptance. A normal Sheet-triggered full inventory recovery and freshness
verification remain required; no full inventory job was admitted by these probes.

The subsequent real Sheet pass changed only `Goal_Pruebas_20260909!A29321`
from the five-space to six-space token-expression variant after metadata and
CellData readback; token values were not read. Formula and header readback passed,
with original formatting/validation untouched. Bounded H29322:H33319 returned
332 numeric quality values, 1,980 DATA_UNAVAILABLE, zero NA and zero cell errors.
Readback occurred 18.227 seconds after the write began; this is not internal
execution latency or p95. Native visual fit was not verified.
Approved-runtime reads found the inventory job pending with expired enumeration,
and a separate orders job running alongside pending catalog jobs. This is not
proof of a stalled worker or completed inventory recovery. No queue priority,
coverage timestamp or production data was manually changed. Observe the normal
worker transition before evaluating whole-inventory performance.

Follow-up runtime observation confirmed that transition without operator
readmission: inventory enumeration renewed at 21:27:33.450 UTC and reached
offset 100 at age 38.654 seconds, then 200 at age 95.196 seconds. At the latter
read it was pending, attempt 1, with a 30-second scheduled retry (available
21:29:12.762 UTC). Enumeration was still current; 360 member items were fresh,
which includes prior observations and is not a processed-count substitute.
Full recovery and freshness acceptance remain unproven. Separately, the current
audit foundations/API tests passed 20 tests (52 deselected); the old collision
finding below was already corrected by `57e106e`, not a new defect to reimplement.

**Normal pass finished, freshness acceptance failed:** the inventory job reached
`completed`, offset 1,900, at 20:48:41.629 UTC. Its enumeration was observed at
20:29:20.733: elapsed **1,160.896 seconds (19m20.896s)**. The subsequent read
found only 1,600 fresh member items and expired enumeration. Alternative-source
quality was persisted in 233 canonical items and 233 formula rows; all 20 sampled
fresh rows still matched canonical values and passed the reader. Completion is
not proof that all required source fields exist: recorded quality reasons still
included 1,184 `performance_not_generated`, 235 `http_400`, and 29 `rate_limited`.

Read-only approved-runtime timing narrowed, but did not settle, the bottleneck.
Three 20-item projection dry runs took 0.3115/0.4336/0.4976 seconds, zero writes;
these exclude real write cost. After completion, one five-item acquisition dry
run took 3.9505 seconds, zero writes, making 20 calls: one item batch, five sale
prices, five listing prices, five item-quality calls (all failed), three
User Product quality calls (all failed), and one shipping call. Endpoint timing
totaled approximately 3.9234 seconds. This is one bounded sample, not a seller-wide
latency distribution or proof that redundant quality calls explain the full gap.
No new full-inventory job was admitted by these probes.

Two additional five-item acquisition dry runs (offsets 950 and 1,895) took
4.4749 and 3.8910 seconds, zero writes, and made 24 and 20 calls respectively.
Across the three samples this is 64 calls for 15 publications. The gateway's
effective proxy limit was confirmed equal to its default 600/minute, shared per
module/seller; the later current-window counter was below the limit, which is
not evidence about earlier windows. Extrapolating these samples gives roughly
8,107 calls / 13.5 minutes of quota for the pilot before contention/retries.
This is an estimate, not measured whole-pass request volume. Failed item-quality
calls account for 13 of the sample's 64 calls. Review redundant acquisition and
retry work before changing concurrency; do not automatically raise the shared
gateway quota or weaken the 15-minute reader contract.

**Throughput acceptance gap confirmed (20:44 UTC):** the same normal inventory
job remained running at offset 1,480 of 1,900 when its enumeration age reached
928.669 seconds. The existing 900-second reader window correctly reported
`inventory_enumeration_current=false`; 1,480 member items were individually
fresh. Thus this production pass cannot establish simultaneously current whole
inventory coverage, regardless of its eventual terminal status. Do not extend
freshness, rewrite observation times, restart this worker or manually enqueue a
replacement to conceal the gap. Inspect acquisition cost and retry delays,
reduce demonstrated redundant work, then verify a complete normal pass.

At that read, 203 canonical items and 203 formula rows held alternative-source
quality. A 20-row fresh sample still matched canonical data and passed the
reader. Source-state counts included 1,036 `performance_not_generated`, 413 old
`http_400`, and 29 `rate_limited`; these are mid-run observations, not terminal
classification of all inventory. The focused quality/calculator/acquisition
suite passed 81 tests (156 deselected). No executable code, image, runtime
configuration or business-data repair changed during this verification.

**Normal recovery and subsequent Sheet read now demonstrated (20:35 UTC):**
recalculating only `Goal_Pruebas_20260909!A29321` admitted the existing normal
inventory recovery; no operator job insertion or freshness-marker edit occurred.
The job progressed through offset 400 of 1,900 discovered publications. At that
observation, 33 canonical items and 29 formula rows held alternative-endpoint
quality; the worker was still projecting, so these were not an atomic snapshot.
A bounded sample of 20 fresh alternative-source rows matched canonical quality
and User Product binding exactly, and all 20 passed the deployed formula reader.

A subsequent real Sheet recalculation returned 65 numeric quality scores,
2,005 `DATA_UNAVAILABLE` rows, zero `NA`, and zero cell errors in the reserved
score range. The anchor retained its header and original formatting; only its
formula value changed. Readback occurred 14.081 seconds after the write, which
is not a whole-function latency measurement or a p95 receipt. Native rendered
layout remains unverified. Mongo holds 2,859 projected rows for the 1,900-member
inventory, including variants; unavailable publications may instead occupy one
placeholder row, so changing output row counts alone do not prove data loss.
Complete current coverage and the terminal recovery result remain pending.
The latest source-state counts included 291 `performance_not_generated` and
29 `rate_limited` observations; neither is proof of permanent unavailability.

**Deployed and live alternative route verified:** Sheets API and worker now run
`c532ebf18fb10300a09cbfca26a3a4a91a5516c6`. Exact-source CI passed (lint
`34399657839`, test `34399657805`); the permission baseline `f131587` also passed
CI (lint `34399399310`, test `34399399264`). All four one-image Cloud Builds
completed with verified provenance, checked locally and again from the VM.

| Role/service | Source | Build | Immutable digest |
| --- | --- | --- | --- |
| Active API | `c532ebf` | `5c5e2356-1a93-491d-b16f-56499d011734` | `sha256:26ec71960971e978f19f0eedb5254c445963776413b19418f42d62961f8d3b21` |
| Active worker | `c532ebf` | `855a1a30-ece8-4aef-95a8-cb4d91e5c0cd` | `sha256:7e9fec01ce40d41ec1ced3fcab7cba2c76604e509c707ab08c476586bb23dee5` |
| Compatible rollback API | `f131587` | `a63420d1-4ca0-4f07-b614-ac505b7ade66` | `sha256:54b181885387cd05c267a8413cd0844e89b7385cd5f6c19e83ffa8722bec993a` |
| Compatible rollback worker | `f131587` | `8d68372c-00bd-443e-9d08-139925d3eded` | `sha256:361460a512d9d4212f5635187a4e9aff7da711fbd456f4577b4bd9a12ae4269a` |

Repositories remain `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`
plus `sheets-api` or `sheets-worker`. Isolated canonical API probes confirmed
the exact 13-scope/six-routing-key contract for active and rollback images.
The two Mongo validators matched the prior deployed source before the additive
update and matched the new source afterward, with strict/error preserved.
This changed no business documents. Unit `zeler-quality-c532ebf` completed with
exit 0, `Result=success`, `activation_complete=true` and repeated healthy checks
for both exact active images. Never rerun that completed unit as a status check.
Compose backup: `/opt/zeler-platform/docker-compose.yml.pre-quality-c532ebf`.
All prior provenance bindings and images were retained. After four pulls,
12,044,632,064 bytes remained free, above the 5 GiB preflight floor; boot disk
remains 30 GiB and the end-of-mission original-capacity evaluation still applies.

Read-only approved-worker probe `/tmp/zeler-up-fallback-route-probe.py` selected
an owned active catalog publication with the earlier item-performance HTTP 400.
Fresh item detail returned 200, with a user-product link. The dedicated
User Product performance request now returned **200**, `entity_type=USER_PRODUCT`,
and its identity matched that exact fresh link. The deployed normalizer accepted
the actual alternative source with three components and five pending actions.
No raw response, identifier, token or personal data was printed or persisted by
this probe. This proves the formerly scope-blocked alternative API contract,
not seller-wide acquisition or formula coverage. Next use normal formula
recovery, verify persisted alternative-source projections and re-read the real
Sheet; do not replace that acceptance with direct probe-only success.

The acquisition correction now tries the dedicated User Product route only
after item-performance HTTP 400 and only with a fresh same-site, syntactically
valid link from the owned item detail. Both requests share the existing
five-second acquisition timeout. There is no fallback for 401/403, no stale-link
reuse and no direct Mercado Libre request from formula HTTP. Persisted quality
and enrichment state retain the actual endpoint source; the model rejects an
ITEM entity returned under the User Product source. Failed fallback preserves
the prior quality and observation time without claiming refreshed completeness.

Strict TDD first produced three failures (missing persisted fallback result,
unsupported source parameter, missing permission), then passed. Verification:
288 focal tests; three actual local Mongo validator roundtrips for both endpoint
sources; eight stock-time cases separately passed; 13 acquisition quality cases
passed after adding absent/fresh-cross-site link guards. Ruff check/format,
Mypy (509 files) and generated schema drift passed. The broad root run finished
with 4,226 passed, nine skipped and one failure: the cached 12-scope assertion
in `core/tests/test_runtime_phase4.py`, corrected in `f131587` and verified by
the 180 core tests. It is not a clean exact-final root receipt; final-commit CI
must pass before deployment. A prior root invocation incorrectly cleared
configured `addopts`, causing import collection errors; the normal invocation
retained repository `--import-mode=importlib` and reached the above result.

Permission baseline source is `f1315870374f1fcd150740f6a7567462e06f6d63`.
Its verified-mode builds were submitted: API `a63420d1-4ca0-4f07-b614-ac505b7ade66`,
worker `8d68372c-00bd-443e-9d08-139925d3eded`; completion/provenance verification
and deployment preparation subsequently passed as recorded above.
Rollback is the compatible 13-scope baseline pair, not removal of recovered data.
Live alternative-route success, sampled normal persistence and a subsequent
Sheet response are verified above; full source-specific Sheet coverage remains pending.

A bounded approved-runtime probe selected an owned active catalog publication
whose recorded quality failure was HTTP 400. Fresh item detail returned 200 and
contained a user-product relationship; `/item/{id}/performance` returned 400
(`bad_request`, unsupported entity). Calling the documented
`/user-product/{id}/performance` through the normal Sheets gateway returned
**403 `out_of_scope`**. This is a demonstrated module permission gap, not proof
that Mercado Libre cannot supply the quality. The alternative upstream response
remains unverified until the specific permission is active.
Reference: [official quality contract](https://developers.mercadolibre.com.ar/es_ar/descripcion-de-articulos/calidad-de-publicaciones).

The permission-only unit adds `GET /user-product/*/performance` to the Sheets
manifest, seed and canonical rollback contract, with startup/registration and
negative unrelated-route/write-method assertions. No wildcard product write or
unrelated endpoint is added. Its test first failed on the absent permission;
the combined focal verification is 288 passing tests. The canonical contract
is now **13 scopes / six routing keys**, fingerprint
`98cd1f6c9eba470251fdfc5e120b635e4928f9defd28af7cfff0510a63f2c96a`.
This independently buildable permission baseline is needed before releasing
the new acquisition behavior so rollback startup cannot remove its scope.
Rollback of this unit is its manifest/seed/contract and matching tests, only
when no active worker requires the new route. Do not credit the permission-only
baseline with fallback acquisition or persistence of the alternative source.
Current deployed API/worker remain `febea19` with 12 scopes; the permission
baseline needs separate verified Sheets API/worker builds and runtime checks.

### USER_PRODUCT persistence and real Sheet readback

Normal async recovery now persists the deployed quality projection. Approved
VM/container read-only counts grew from 104 items / 142 formula rows to
208 items / 271 rows with fresh quality; the latter included 159 USER_PRODUCT
items and 157 USER_PRODUCT rows. These are observations during a running
inventory, not equal-time complete coverage. In a bounded fresh USER_PRODUCT
sample, **20/20** formula-row projections matched their canonical item quality
and user-product link, and **20/20** were accepted by the deployed formula reader.
Probe: `/tmp/zeler-user-product-status.py`, executed inside the Sheets worker.
Only counts, queue states and boolean comparison results were emitted.
The inventory was still running at offset 1,880, attempt 1; another item recovery
job remained pending. No jobs were manually inserted or freshness markers changed.

In the authorized `Goal_Pruebas_20260909` tab, only `A29321` was updated to
`=ZELERDATA_CALIDAD($A$2&"   ","si")` to recalculate using the unchanged
canonical account. Token/input cells, other tabs and formatting were untouched.
Connector readback of `H29322:H32181` returned 2,792 populated score cells:
**218 numeric, 2,574 DATA_UNAVAILABLE, zero NA and zero cell errors**.
The range was inspected about 15 seconds after the write response; this is not
a whole-function execution measurement or a p95 receipt. Layout was checked
through cell metadata only, not a native browser render.

This proves live source -> normal recovery -> Mongo -> formula reader -> real
Google Sheet for a bounded subset. It does **not** close quality coverage,
explain every remaining unavailable row, reconcile the changed inventory count,
or establish all-52 acceptance. Let the existing recovery finish, inspect its
terminal state and remaining source reasons, then verify complete current
readback without repeatedly forcing inventory sweeps.
Runtime remains exact source `febea19`; this evidence-only change requires no
new image. Rollback remains the image pair below, not deletion of recovered data.

### Quality acquisition gap: confirmed missing source path and permission

USER_PRODUCT correction `febea1901f860748e6e5fd4d0858be79d81b1666` is deployed
to Sheets API and worker. Exact-commit CI passed: lint `34396073764`, test
`34396073794`. Separate verified Cloud Builds and canonical provenance checks
bind the following images to that source:

| Service | Build | Immutable digest |
| --- | --- | --- |
| sheets-api | `63bab5cc-833e-42a3-a4f4-fa7dab58eabf` | `sha256:45c29c343ee93b1977d55c63882a8c5603867a9f80c5692fff74128ade4577d7` |
| sheets-worker | `7b5dc764-bc9c-410e-84e5-88c066184734` | `sha256:329cc4d0c03c40d6415270789b4fc5d180a3c12b040b883e7aef98b4a28f57a8` |

Both images use the existing Artifact Registry service repositories under
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`.
Before deployment, `items` and `sheets_item_formula_rows` validators matched
the prior source exactly; their additive updates were applied from the approved
VM/container context and read back with strict/error validation unchanged.
No business documents were changed by this validator operation.
The API runtime contract was verified for both new and rollback images.
Unit `zeler-quality-febea19` finished with `Result=success`, `ExecMainStatus=0`,
and `activation_complete=true`; both exact new images passed repeated health
checks. The shared provenance map preserves earlier bindings. Compose backup:
`/opt/zeler-platform/docker-compose.yml.pre-quality-febea19`.
Rollback is the prior healthy `0c80a97` API/worker pair, whose full digests and
build bindings are recorded below; it retains the 12-scope contract but rejects
USER_PRODUCT quality rather than fabricating values. Do not delete acquired
data during rollback or rerun the completed activation unit as a status check.

Post-deploy read-only probe, run in `zeler-platform-sheets-worker-1` from
`/tmp/zeler-user-product-performance-probe.py`: an owned active non-catalog
item detail and its performance endpoint both returned HTTP 200. The response
was USER_PRODUCT and its identity matched the fresh owned item relationship.
The deployed normalizer accepted it, producing three components and five
pending actions. No identifiers, payloads, tokens or personal values were
printed. This proves the formerly rejected live contract, **not acquisition
persistence, all-52 acceptance or the real Sheet result**. Next verify normal
async recovery persistence/readback and the owned Sheet quality section.

After both pulls, root free space was 14,229,340,160 bytes, above the 5 GiB
floor; disk capacity remains 30 GiB. Preserve the user's end-of-mission request
to evaluate returning to the original 20 GiB via a separately agreed migration.
No further disk resize, other-product deployment or data deletion occurred.

Strict-TDD regression first failed six cases, including acquisition/persistence
and unknown relationship rejection. The normalizer now accepts the observed
USER_PRODUCT response only when its identity matches the fresh item detail's
`user_product_id`. Projections retain `entity_type`, upstream `entity_id` and
bound `item_id`; canonical items and current formula rows retain the relationship.
The reader rejects changed/missing user-product relationships and mismatched
item bindings. Existing ITEM projections remain readable; failed acquisition
preserves their previous representation and observation time.

Focused verification: **258 passed**, plus **two real local Mongo roundtrips**
covering ITEM and USER_PRODUCT while still rejecting invalid scores, raw payloads
and unknown components. Root Ruff and Mypy (509 source files) passed; generated
schema drift check passed. The root run completed with **4,219 passed, nine
skipped, 356 warnings in 156.21s**. It began before the final missing-relationship
correction: that regression first failed because the old link survived, then
passed in the 258-test focal run after clearing the link from fresh full item
detail. Therefore the root count is broad regression evidence, not proof of a
clean full run of the final exact checkout; CI must verify that final commit.
The nine skips are the same eight ambient-URI stock-time cases (separately
verified earlier) and one inapplicable Caddy required-key check.
Deployment used updated `items` and `sheets_item_formula_rows` validators
before the new API/worker images. No additional gateway scope or separate
user-product endpoint is introduced. Rollback boundary is this identity binding
model/producer/reader/schema correction; prior deployed images must not be
credited with support for this response. Production acquisition/readback and
real Sheets acceptance remain pending.

Post-deploy contract diagnosis, 2026-09-09: the initial item's identifier format
is valid; its HTTP 400 is `bad_request` with sanitized source-error vocabulary
indicating an unsupported product/entity, not evidence of a malformed item ID.
Do not generalize that result to the seller or to permanent data absence.

A separate owned active **non-catalog** pilot item returned HTTP 200 both for
`GET /items/{id}` and `GET /item/{id}/performance`. The item response contains a
`user_product_id`; the performance response has `entity_type=USER_PRODUCT`, and
its `entity_id` matches that exact owned item relationship (not the item ID).
The deployed normalizer rejects it as `quality source identity mismatch`
because it only accepts ITEM. This is a demonstrated compatibility defect, not
missing upstream quality. No raw payloads or identifiers were printed or
persisted by these diagnostic probes. The official
[quality contract](https://developers.mercadolibre.com.ar/es_ar/administra-proyectos-aplicaciones/calidad-de-publicaciones)
documents both ITEM and USER_PRODUCT entities. Next correction must retain the
verified item-to-user-product relationship, support this observed response,
persist its source identity truthfully and keep rejecting unrelated entities;
start with a failing regression. Direct use of the separate user-product path
has not been verified or authorized through a new registry scope, and is not
needed to explain the observed successful item-path response.

Quality API and worker activation completed on 2026-09-09. VM systemd unit
`zeler-quality-0c80a97` finished with `Result=success`, `ExecMainStatus=0` and
`activation_complete=true`. Both services passed repeated healthy-state checks
with the verified `0c80a979688a8c0a70beaa62cc89f747380cc0f9` images listed below.
The canonical repository API runtime-contract verifier accepted both the new API
and compatible baseline API; all four images passed external provenance checks
again from the VM. The shared image-to-commit map was merged without removing
previous entries. Compose backup: `/opt/zeler-platform/docker-compose.yml.pre-quality-0c80a97`.
The failure-conditional fallback is the compatible `28d8ed4` API/worker pair;
it was not activated. Only the two Sheets services were targeted with `--no-deps`.

First post-deploy owned-active-item performance probe through the normal Sheets
gateway client returned **HTTP 400**, not a valid quality projection. It printed
no item ID, token or response payload and made no persistence writes. This does
not prove permanent source absence or successful quality acquisition. Diagnose
the rejection before accepting CALIDAD; persistent acquisition and real-Sheet
readback remain outstanding despite healthy deployed services.

Quality validators applied and read back on 2026-09-09 from the approved VM
runtime container. Before changing anything, both `items` and
`sheets_item_formula_rows` matched the exact `28d8ed4` baseline, with strict/error
validation. The scoped `collMod` operations then installed the reviewed
`0c80a97` validators; both post-write reads matched exactly and retained
strict/error validation. No business documents, indexes, seeds or other
collections were modified. Baseline and new schema contracts remain in
`/tmp/zeler-quality-validator-contracts.json` on the VM. The first apply attempt
lost SSH during connection establishment; a read-only check confirmed both
validators were still baseline before retrying successfully. Service image
activation and quality acquisition/readback remain pending. Additive validators
may remain during image rollback so persisted quality is not lost.

Capacity blocker resolved with explicit user authorization on 2026-09-09:
boot disk `platform-vm` (`pd-balanced`, `us-central1-a`) grew from **20 GiB to
30 GiB**. Its existing ext4 root partition `/dev/sda1` was extended online
after a dry run confirmed its start sector stayed unchanged. Root available
space became **15,322,804,224 bytes**, above the 5 GiB deployment floor. No VM
restart was requested; the separate 50 GiB Mongo data disk was not resized.
The user requests returning to the original capacity at mission completion if
possible. Preserve that follow-up: [GCP does not support shrinking an existing
Persistent Disk](https://docs.cloud.google.com/compute/docs/disks/resize-persistent-disk).
Returning to 20 GiB would require evaluating a smaller-disk migration, capacity
headroom and an outage/recovery plan; do not promise an in-place shrink or
perform that migration without discussing it with the user. This capacity
change does not itself activate the quality images or prove formula behavior.

Deployment preparation, 2026-09-09: GitHub test run `34391302400` and lint run
`34391302423` both succeeded for `0c80a979688a8c0a70beaa62cc89f747380cc0f9`.
Four Cloud Build images passed the canonical external provenance verifier and
were pulled by immutable digest onto the VM:

| Role | Build ID | Image digest |
| --- | --- | --- |
| Compatible API rollback, `28d8ed4` | `b6d7de7a-2017-45f3-8873-6452c75e60d2` | `sha256:99fe18f2a9964b7486445031588065dd1cd7d1c514e4df7d7625a9893cb4ada6` |
| Compatible worker rollback, `28d8ed4` | `08cc2b66-9a03-40ee-a06d-ecc1a6866e85` | `sha256:eda3358b1138eaa033af8bd23be5fb9d2820ca3f3d2eb9974f1f50fb7fd9caf9` |
| Quality API, `0c80a97` | `5f9e5da4-fc4c-4bbe-8614-af1e2e34c106` | `sha256:56225360c6ff57670a42931a0e2fb2f88326928729d169b6eb351e848e2c5ce0` |
| Quality worker, `0c80a97` | `4736735b-39f7-4564-9883-81b7ffc60fa7` | `sha256:eba8953d3ff9ff07b9da8600021283cf11ae7b312acff38d74efacffa58eb1f3` |

All four passed isolated, network-disabled entrypoint import and exact
12-scope/six-routing-key registration fingerprint probes. The first temporary
probe referenced a nonexistent `zeler_sheets.worker` module; correcting the
harness to `zeler_sheets.formulas.recovery_worker` produced the four passing
results without changing product code.

Only three unused, unprotected local Sheets image copies were removed after
confirming their immutable artifacts remained recoverable in Artifact Registry:
worker `5f23d9b…`, APIs `14509bb…` and `3ca3930…`. No containers, volumes,
business data or active/previous rollback images were removed. Capacity passed
the 5 GiB floor before each pull, but after all four pulls only **4,916,715,520
bytes** remained, below the **5,368,709,120-byte** activation floor. Do not run
Compose until capacity is restored. No validator, registration or service
activation occurred. Existing API `ec04713…` and worker `9cf679b…` remained
healthy; actual performance acquisition and real-Sheet CALIDAD readback remain
unverified. This preparation is not production acceptance.

The eight stock-time tests skipped by the root run were subsequently executed
separately against the dedicated loopback replica set on port 27028, with
ambient `MONGO_URI` unset and `ZELER_RS0_TEST_URI` explicitly selected. All eight
passed with no skips (exit 0): acquisition, mixed-plan transaction commit,
external target drift rejection, validation-failure transaction abort, exact
rollback restoration, CLI rollback preflight, terminal rollback drift and
atomic inverse rollback failure. The command selected
`tests/integration/test_stock_time_forward_{acquisition,execution,rollback}_rs0.py`.
These tests use isolated disposable databases; no production Mongo access or
product code change was involved. This closes the local skipped-test evidence
gap, not the real-Sheet stock-time acceptance requirement.

Latest local gate: after the environment transition lost the earlier process
handle, a new authorized full run against the dedicated local replica set
completed with **4,213 passed, nine skipped, zero failures** in **156.18s**.
Eight stock-time integration cases intentionally reject ambient `MONGO_URI`;
the remaining skip is Caddy's inapplicable required-key check. Those skips are
non-acceptance, not proven stock-time behavior. No quality acquisition or
recovery tests were skipped. Production acquisition and real-Sheet readback
remain pending. The deployment must retain a rollback image compatible with
the reviewed 12-scope/six-routing-key registration before activation.

Local implementation now connects bounded performance acquisition to canonical
items, formula rows and the existing recovery worker. The reader validates item
identity and acquisition age (the existing 15-minute current-data window), keeps
source score/level, and reports unavailable quality separately from known item
columns. Legacy health-based level inference was removed. Failed acquisition
preserves the prior quality observation; a performance 404 remains retryable,
not evidence of permanent optional absence.

Focused verification: 160 enrichment tests, 122 handler/API tests, and eight
bounded-worker cases passed. Real local Mongo accepted both normalized storage
forms and rejected out-of-range scores, unknown components and raw payloads
(`test_quality_projection_roundtrips_with_real_mongo_validators`). The first
full recovery run had 388 passes and six failures: test gateways lacked the new
performance response or expected quality completion without acquisition. Their
eight parametrized regression cases passed after correcting those fixtures.
Full recovery/root reruns are pending; do not infer production acceptance.

The subsequent root run completed with **4,162 passed, eight failed, 52 skipped**
(191.65s). Seven failures were the old registry count/enrichment metadata and
retry fixtures, now corrected (180 core tests and seven retry cases pass).
The eighth exposed the deploy verifier's old canonical registration fingerprint:
the reviewed contract now includes 12 scopes and six routing keys. Update the
verifier and its probe expectations together; do not bypass rollback attestation.
Its complete preflight suite passed 83 tests after that change. A clean root
rerun remains required. Most Mongo skips used the default development port,
not the dedicated recovery Mongo on 27028; those skips are not passing evidence.

Runtime rollout still requires compatible validators for `items` and
`sheets_item_formula_rows`, the reviewed Sheets gateway scope, and verified new
Sheets API/worker images. No runtime changes have been applied for this unit.
Rollback stops the new worker/API behavior and restores the prior images;
additive validators may remain so persisted quality is not deleted or rejected.
The source rollback boundary is the quality producer/model/schema/reader path,
its single worker option and corresponding tests; unrelated inventory renewal
and other products remain outside this unit.

Repository tracing found `quality_projection` populated only by test fixtures,
not by Sheets acquisition/persistence. The reader also accepts three alternate
projection names and legacy health; none establishes production acquisition.
The official [quality contract](https://developers.mercadolibre.com.mx/es_ar/preguntas-y-respuestas/calidad-de-publicaciones)
uses `GET /item/{id}/performance`, with source score 0–100, source level and
calculation time, plus bucket variables/rules. It is not the old health resource
or the unrelated purchase-experience metric. The legacy acquisition reference
also consumes that singular path, but its fallback zeros must not be copied.

An approved-runtime read-only probe selected one owned active pilot item:
the current Sheets registry did **not** permit this path and the normal gateway
returned **403**. This is a platform permission gap, not proof that Mercado Libre
withholds the pilot's quality data. No permission or business data was patched
in production and no token was copied or printed.

Local prerequisite: add only `GET /item/*/performance` to the Sheets manifest
and its admin seed. New scope regression initially failed (1 failed in 0.18s),
then `uv run pytest tests/test_sheets_schema_contract.py
modules/sheets/tests/test_app_phase6.py --tb=short` passed **32 tests in 0.56s**.
The test checks the exact resource and rejects writes/unrelated singular-item
paths. Existing startup expectations were updated; Ruff and diff checks pass.

**Not deployed or complete:** keep this scope with the upcoming acquisition,
source-bound persistence and reader correction. Preserve source percentage/level
rather than applying the current legacy 0–1 buckets to a 0–100 score. Normalize
the existing twelve columns from verified variables; only confirmed absent
optional components may be NA. Missing acquisition is not confirmed absence.
Use asynchronous recovery and trusted Mongo fallback without invalidating item
fingerprints or relabeling old observations. A normal owned live performance
response and persisted readback remain required before acceptance.

Rollback of this local prerequisite removes its one manifest/seed scope and
matching tests in `test_sheets_schema_contract.py` and `test_app_phase6.py`;
it does not delete acquired data. No new image is requested for this permission
alone while the functional producer remains unfinished.

### Real Sheet current-read renewal verified; quality fields remain absent

The demanded inventory completed **1,900/1,900**. At observation age 563.152s,
the persisted next due time was still **36.848s away** (observation + 600s).
The actual CALIDAD handler returned **2,859 rows × 19 columns**, complete/current
inventory, zero partial misses, no recovery, and zero DATA_UNAVAILABLE cells.

Changed only `Goal_Pruebas_20260909!A29321` from
`=ZELERDATA_CALIDAD($A$2,"si")` to `=ZELERDATA_CALIDAD($A$2&" ","si")`.
The account resolves to the same pilot. First connector readback had results
at **6.245 seconds** from write initiation; a new production HTTP 200
serialization event measured **2,591.99ms**. Full bounded readback of
`A29322:S32181` found 2,859 populated rows, zero cell errors and zero
DATA_UNAVAILABLE. Ordered publication membership fingerprints and NA counts
matched the backend cut. This is membership/count corroboration, not an
independent field-by-field source audit or a p95 sample.

After this real current read, the existing inventory job changed from completed
to **pending**, retained all 1,900 identities and its observation cut, and had
**7.434s remaining until the same due time**. Subsequent readback found it
**running at offset 160**, with a new observation age of 36.364s. No operator
enqueue, timestamp edit, worker restart or new deployment was used. This proves
demanded preventive admission and execution for one cycle, not perpetual
freshness or every formula's final correctness.

**Remaining data gap:** both backend and Sheet contained **34,330 NA cells**.
Columns H:S (all twelve quality fields) were NA for every one of the 2,859
rows; the remainder was 18 SKU cells and four stock cells. No NA was silently
counted as verified source absence. Next trace acquisition/persistence of quality
fields and the four missing stock values. A repository search found no quality
acquisition references in the item backfill/event persistence paths inspected;
this is a lead requiring contract/source verification, not proof of impossibility.

Only the anchor's value changed; original tabs, validation and formatting were
preserved. Native rendered layout remains unverified. This evidence-only update
requires no image rebuild and must not be rolled back by deleting acquired data.

### Current hosted order relationship: one live positive control

A read-only approved-runtime probe selected the two newest stored pilot orders
with shipment links, bounded to August 8 through September 9. Each detail was
validated for order identity and seller before requesting the hosted relationship
through the normal Sheets gateway. One **September 9** order returned **HTTP 200,
an array, one forward shipment, and a match to the persisted shipment ID**. The
other relationship returned **404 / known not-found**. No IDs, PII, tokens or raw
payloads were printed, and no business data or queue records were changed.

This adds a positive live control to the earlier all-404 observations. It proves
the new endpoint/array format is available for one real pilot relationship, not
universal coverage or repair of a genuinely absent link. The current official
[orders contract](https://developers.mercadolibre.com.mx/gestiona-ventas) was
rechecked: hosted results are arrays and purchase shipments are selected by
`type=forward`; a 204 can reflect asynchronous propagation. Existing focused
adapter/cancellation tests passed **5 tests in 0.23s**, with no skips. Full orders
migration and purpose-complete formula acceptance remain open.
Command: `uv run pytest modules/sheets/tests/test_formula_recovery.py -k
'order_detail_recovers_purchase_shipment or order_shipment_fallback' --tb=short`.
This evidence-only documentation unit has no runtime rollback or new image;
reverting its two documentation files must not revert services or acquired data.

Meanwhile the inventory job advanced from offset 340 to **940**, still running
on its first attempt. At the earlier offset-340 cut the actual reader returned
478 trusted rows and 1,560 unavailable items out of 1,900. Do not replay its
admission or manufacture freshness while it is acquiring.

### Demand-triggered renewal of still-current inventory

The API now requests the next inventory sweep when a successful response
explicitly reports a current inventory enumeration. It reuses the existing
one-second admission helper, queue key, cooldown and capacity controls; no
autonomous loop or Mercado Libre call is added to formula execution. Required
item recovery takes precedence over preventive renewal. Returned values and
freshness remain unchanged, including when admission is disabled, fails or
times out. `inventory_refresh_requested` reports admission separately from
missing-data recovery.

TDD: five initial cases failed for absent renewal; four precedence cases then
caught redundant renewal alongside required item recovery. The real-Mongo
buybox test now verifies the additional inventory job is deferred until its
existing ten-minute due time, preserves the observation cut, and does not
prevent immediate price/competition repair. Combined API/recovery suites:
**452 passed in 93.05s**, without skips. Ruff and focused API mypy passed.
Sustained-renewal runtime verification is still pending. The image change was
limited to **sheets-api**;
rollback removes this admission hook/meta field and its tests, with no schema
or data migration.

Committed/pushed as `6cc570b8f68ada56bddbdeb353d7742df143bf0d`.
API-only Cloud Build `27b6e6d2-7110-43eb-a60b-ab81096f42d8` succeeded;
image `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:ec04713bd400cb6f11fc1327ed56b6244cad08f95762a2ca35588ce56b64e417`;
config `/tmp/zeler-inventory-renewal.VMU23J/cloudbuild.yaml`. CI lint
`34384766073` and test `34384766021` passed. The production API now runs this
verified image: activation completed healthy, zero restarts, with worker
identity/start time unchanged. Backup:
`/opt/zeler-platform/docker-compose.yml.pre-sheets-api-6cc570b`.
Rollback API remains `7ddca362...`; no images or data were deleted in this
activation. Free space passed the 5-GiB floor before Compose activity.

The post-activation replay changed only A5801, A18321, A22321 and A38901 in
`Goal_Pruebas_20260909` (two trailing account spaces to three, same normalized
pilot). New production serialization events were HTTP 200: CATALOGOBUYBOX
6,874.536ms, CATALOGO 7,181.874ms, OBTENER_CATALOGO 7,204.109ms and
CATALOGO_COMPLETO 7,277.993ms. Connector readback at **10.293 seconds** from
write initiation showed results, still containing DATA_UNAVAILABLE. This is
a bounded response observation for these four calls, not a p95 measurement
or complete-data acceptance. Native rendered layout remains unverified;
only anchor values were written, preserving formatting and original tabs.

The approved-runtime reader then found **82 trusted rows, 1,900 inventory
items, 1,840 unavailable items, current enumeration**. The inventory job was
running at offset 40 and product recovery was pending at offset 60. This
confirms real demand started acquisition; it does not yet prove preventive
renewal of a fully current inventory. Next let this acquisition progress,
then test a current read and verify its deferred renewal without changing
timestamps or directly preparing another queue job.

Separately, the pilot sweep initiated by the real Sheet completed. The actual
VM/container read-model reader returned **2,859 trusted rows across 1,900
inventory items, zero missing items, enumeration current**. This proves current
inventory at that cut, not buybox/product/sales completeness or sustained
availability. The worker signal-fix deployment started only after the scoped
pending/running job list became empty.

### Worker stop-signal correction

The live old worker's PID 1 was `sh`. Its Dockerfile used a shell command
without `exec`, while Python registers SIGTERM/SIGINT shutdown handlers.
Removed that unnecessary shell by making the existing Python module the
exec-form CMD. No dependency, scope, queue, or data contract changes.

TDD: the new Dockerfile regression failed against the shell CMD (1 failed,
2 passed), then the Dockerfile/runtime-contract suites passed **42 tests**.
Existing entrypoint/supervisor tests passed **19 tests**, including signal
registration, waiting for in-flight work and ordered shutdown. This is local
evidence; a new worker image must prove Python PID 1 and graceful stop in runtime.
Rollback changes only the CMD and its focused regression. The operational
activation helper must still allow more time than Docker's stop grace.

Committed/pushed as `fc642deae15a3ba9b1423e36848c5e73f116487e`.
Cloud Build `3b04fb93-3785-4b8e-b9ce-a1b12dc249de` succeeded; worker image
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:9cf679bb5803ae4f2a8b4d24cd2c522ec5cbd195ad2d8b8e39a8d4734aff0657`.
CI lint `34383367259` passed; test `34383367174` ended with 1 failure,
3,807 passes and 393 skips: the existing Dockerfile contract still required
the removed shell. Updated that existing test for Sheets only and removed the
new duplicate assertion from the healthcheck test file. The image's runtime
content is unchanged by this test-only follow-up; no rebuild is needed for it.
The combined Dockerfile, runtime-contract, entrypoint and supervisor checks
passed **82 tests in 2.88s** after correcting the stale expectation.
Local helpers: `/tmp/zeler-worker-signals.uRArwZ/`. Before activation, the running
worker was the verified `36f9d28` image from attempt 2 below; the completed
activation and signal verification are recorded after the preparation details.

The new image was verified and downloaded. Removed only unused local worker
`7833b955...` after all-container, current Compose, protection-file and Artifact
Registry checks; no volumes/data touched. Free disk returned to 5,859,319,808
bytes. At preparation, VM helper `/tmp/activate-worker-signals-fc642de.py` had not run;
it preserves the currently running `7a380060...` worker as rollback and checks
Python PID 1. Pilot acquisition advanced 520 → 1,180 → 1,580 during this work.

Activation completed: worker `9cf679bb...`, source `fc642de`, verified Python
PID 1, stable healthy state, zero restarts; API identity/start time unchanged.
Backup `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-fc642de`.
The scoped pilot queue was empty again before launching
`/tmp/verify-worker-stop-fc642de.py` for a controlled stop/start verification.
That verification completed: clean stop in **1.777 seconds**, exit code 0,
not OOM; the same container restarted and remained healthy on repeated checks.
API identity/start time stayed unchanged. The new worker's stop-signal behavior
is now runtime-proven. No additional worker build is required for the API-only
renewal change.

Post-deployment Sheet replay changed only the four owned anchor account
expressions from one trailing space to two (same normalized seller). Production
confirmed new HTTP 200 events: CATALOGOBUYBOX 7,576.578ms, CATALOGO_COMPLETO
7,403.748ms, OBTENER_CATALOGO 7,686.024ms, CATALOGO 7,535.278ms. Readback at
45.5 seconds still showed DATA_UNAVAILABLE, so neither complete data nor the
whole-function 30-second bound is proven by this cut. Existing formats were
preserved; native rendered layout was not verified. The scoped recovery job
was running at inventory checkpoint 200 after the calls, confirming that this
real Sheet demand initiated acquisition. Allow it to progress before another
worker deployment; then re-read values and source completeness.

### Catalog replay and demanded inventory refresh lead time

Follow-up for source `36f9d2838e46575f77e59be63e77e0a5c993c0fc`:
the complete recovery suite passed **393 tests in 90.48s**, without skips,
against the dedicated local Mongo fixture. CI test `34380882968` and lint
`34380882853` passed. Cloud Build `c71e0233-6c24-412e-bbd7-88dc77709889`
succeeded; the canonical verifier bound the exact connected-repository source to
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:7a38006071832901ef1c4b747901e583376e638b27fa2754fd0f682f59e81936`.
The first VM pull reached its 240-second bound (`TimeoutExpired`). A read-only
check found no new image, no disk exhaustion, and a reachable registry (expected
unauthenticated 401). A single 90-second retry succeeded: ten layers completed.
Removed only the unused local worker image `88a61a75...`, after checking all
container references, current Compose, protection files, and recoverability in
Artifact Registry. No volumes/data were touched; free disk returned above 5 GiB.

The helper `/tmp/activate-refresh-lead-36f9d28.py` was invoked once and verified
the VM provenance, but Compose activation exceeded its 120-second bound. The
helper restored Compose and confirmed healthy rollback to worker `5f23d9ba...`.
The API remained on `7ddca362...`. Do not count `36f9d28` as deployed or blindly
repeat activation. Backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-36f9d28`.
Scoped reads found no pending/running pilot jobs before download and activation.
Investigate the activation timeout before retrying; no Sheet replay was issued
in this follow-up because the new worker did not activate.

The subsequent runtime check contradicted the first rollback health result:
Docker completed a delayed SIGKILL and the old worker exited 137 (not OOM).
The helper's outer 120-second timeout equaled Compose's 120-second stop grace,
so it began rollback while the daemon was still stopping the container. Restored
the old worker with the existing Compose configuration and reverified both
services healthy. Compose dry-run with the new digest succeeded in 0.33s.
The corrected attempt-2 helper gives Compose 240 seconds for its 120-second
stop grace and verifies running/healthy state twice, ten seconds apart. This
fixes the operational wait race, not the worker's slow graceful shutdown.

Attempt 2 completed: worker `7a380060...`, source `36f9d28`, running and healthy
on repeated checks, zero restarts; API container identity/start time unchanged.
Compose has no command/entrypoint override, so the separate PID-1 Dockerfile
correction will take effect in its next image. Preserve worker `5f23d9ba...`
as the rollback authority for this completed deployment. Do not repeat attempt 2.

Read-path review confirms catalog recovery is requested on missing/expired
coverage, not merely because the successful-job refresh interval has elapsed.
Therefore the 10-minute eligibility change does **not** establish refresh before
expiry or continuous availability. Keep the demand-path acceptance open.

After diagnostic API activation, new requests from the four authorized test
anchors were confirmed in production logs: CATALOGO_COMPLETO 6,955.788ms,
CATALOGOBUYBOX 7,254.380ms, OBTENER_CATALOGO 7,287.785ms, CATALOGO 7,044.896ms;
all HTTP 200. Only the account expression gained trailing whitespace, normalized
by the existing account resolver, to change evaluated arguments and avoid cached
custom-function results. First-three-row readback still contained unavailable
data, so this does not clear correctness or populated-catalog latency.

A VM-scoped read found all 1,900 canonical items and 2,859 projection rows:
261 trusted sources, 1,639 expired sources, no observed fingerprint/observation/
row-count mismatch among the fresh sources. The inventory job was running at
checkpoint 180, alongside a pending product-snapshot recovery. This identifies
source expiry as the dominant availability failure at that cut, not data loss.

Successful inventory recovery previously could not run again before discovery
plus 15 minutes, exactly when its reader evidence expires. The local change
permits a **requested** refresh at discovery plus 10 minutes (or completion if
later), without starting autonomous scans. Failures retain the 15-minute cooldown;
reader expiry, source timestamps and seller capacity remain unchanged. This
only removes the admission wait: the demand path and acquisition throughput
still need to prove sustained coverage. Do not label this a complete fix.

TDD: after restarting the existing dedicated loopback Mongo test container on
27028, the revised clock test produced 2 failures/4 passes against old code.
With the change, inventory/capacity/cooldown tests passed **85 tests in 17.92s**,
without skips. Ruff check/format and focused mypy passed. Random test databases
were cleaned by the fixture, not production. Only **sheets-worker** needs a new
image for this behavior; it is not deployed yet. Rollback restores the successful
inventory scheduling interval and its clock-test expectations; no schema/data
migration is involved.

### Bounded execution diagnostics deployed; catalog reproduction pending

Build/pull follow-up for source `a2b084bd0b637106a18b35d56d8c8811f6bd4f37`:
Cloud Build `ac887c98-7041-4bdb-9295-f6ce5582f4ee` succeeded. The canonical
`verify_image_to_commit` verified the connected repository, exact revision,
build and immutable image
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:7ddca362ea8876ad870b4f80a7a0f45aa1f43741be13ae54ffe83f50d0fd203f`.
This image is downloaded on the VM; do not rebuild or repeat the pull.
CI lint `34378845022` and test `34378844903` both completed successfully.

The pull reduced free disk below 5 GiB. Removed only the unused local API image
`d9203ac5...` after confirming zero container references, no current Compose or
checked rollback-protection references, and continued availability in Artifact
Registry. No volumes/data were removed. Free disk returned to 5,873,590,272 bytes.
The current healthy API `14509bbf...` remains the rollback authority; the healthy
worker `5f23d9ba...` remains unchanged.

Helpers are `/tmp/zeler-formula-trace.nYKdxg/` locally. VM
`/tmp/pull-formula-trace-a2b084b.py` completed; the prepared
`/tmp/activate-formula-trace-a2b084b.py` was invoked once and failed before
activation: the preflight defaults to `/usr/bin/gcloud`, absent on this VM, while
the installed executable is `/snap/bin/gcloud`. Compose was restored and the
previous API remained healthy. Read-only metadata checks and the canonical
verifier passed inside the VM using the actual executable; no permissions changed.

The corrected `/tmp/activate-formula-trace-a2b084b-attempt2.py` completed:
API `7ddca362...`, source `a2b084b`, healthy, zero restarts. Worker container ID
and start time were unchanged. It supplied `ZELER_GCLOUD_BIN=/snap/bin/gcloud`,
verified a dedicated provenance file, then used the canonical merge/writer to
preserve the existing shared image map. Backup:
`/opt/zeler-platform/docker-compose.yml.pre-sheets-api-a2b084b-attempt2`.
Do not repeat activation. External `/health` returned 200; an unauthenticated
formula request returned 401 and emitted the bounded `formula_execution` event
(SKU, serialization, 401, 0.349ms), with no sensitive keys. Runtime logging uses
the console renderer, not JSON; JSON-only log parsing misses these events.
This denial probe is not authenticated formula acceptance. Reproduce the four
populated catalog requests through the user's Sheet next.

The inventory checkpoint advanced from 240 to 580 of 1,900, with zero recorded
unavailable IDs and 1,040 canonical items acquired within 15 minutes. This is
ongoing acquisition evidence, not stable full-inventory availability.

The single-formula HTTP endpoint now emits one `formula_execution` event with
only registry-bounded formula name (or `unknown`), phase, HTTP status and monotonic
duration. Timeout phases distinguish authentication, seller context, dispatch,
recovery and serialization. No account, arguments, caller request ID, response
values or exception text is supplied to the event. This uses existing logging,
not a new service or collection. Batch telemetry is unchanged. Formula outputs,
freshness, recovery policy and the 20-second deadline are unchanged.

TDD: five initial cases failed for the absent event; seven diagnostic cases now
cover success, unknown names, handler failure, authentication/dispatch/recovery
timeouts and serialization failure. The focused API/token/foundations/contracts/
HTTP-smoke suites passed **103 tests in 4.15s**. Ruff check/format and mypy for the
changed API passed. The audit-failure regression still proves token denial and
one audit warning, alongside the new execution event.

Runtime harness: local ASGI requests through token validation and the endpoint;
production emission and deployment are now verified above. Only **sheets-api**
changed; no further image is needed for this unit. Reproduce populated catalog
calls from the authorized Sheet, checking the actual timeout phase. Do not count
this diagnostic unit as the catalog fix. Rollback removes only the endpoint
logging/phase annotations and their tests; it does not alter data or schemas.

### Sheet observations

User authorized formula writes in the existing private spreadsheet
`1NUYbJUgYEc6SumZ_IwOWXj_d9MC4grGO5c2XRrAM858`. Google Drive/Sheets connector
access succeeded without exposing a token or changing sharing. Created only
`Goal_Pruebas_20260909` (`sheetId=1903536092`); original tabs remain untouched.
The index in A10:D62 links to 52 separate output sections. Column C preserves
initial classifications and D records the post-update observation. Each formula
uses the canonical local signature; scoped queries use the existing pilot
publication/SKU, date queries use 2026-08-08 through 2026-09-06. COMPRADORES uses
one real owned order selected read-only from production Mongo inside the API
container on the approved VM. No token was extracted or copied.

Initial first-four-row observations: 24 responses needing data review, 25 with
DATA_UNAVAILABLE, one unknown function (CATALOGO_COMPLETO), one header-only and
one empty response. A bounded production audit aggregation confirmed all 38
recognized formulas in the first three groups reached the API with allowed
authorization; this was not a full 52-status HTTP trace.

The user subsequently updated the four Apps Script files in the same project.
Readback across all 52 output anchors now shows 31 responses needing review,
15 with DATA_UNAVAILABLE, four SERVICE_UNAVAILABLE, one header-only and one empty.
CATALOGO_COMPLETO is now recognized. Do not attribute every availability change
to the add-on: asynchronous acquisition also ran between observations.

CATALOGO, CATALOGOBUYBOX, CATALOGO_COMPLETO and OBTENER_CATALOGO still returned
SERVICE_UNAVAILABLE after an explicit four-formula replay using TO_TEXT on the
same account reference. They were LOADING at the 21.489s observation and terminal
at 32.632s; these are polling bounds, not execution durations or p95. A read-only
runtime dispatcher probe completed all four without exceptions (938, 938, 834,
834 rows), but bypassed HTTP authentication, deadline and recovery admission.
Thus that direct result does not clear the real Sheets failure. The API has a
20s deadline returning 503. A subsequent Caddy access-log aggregation (only
timestamp/status/duration/response size, no headers or request bodies) confirmed
the last four replay requests returned 503 in 25.818–26.186s, each 166 bytes.
This supports deadline investigation; it does not identify the slow phase.

Further isolation on 2026-09-09:

- Four concurrent read-only dispatcher calls plus JSON-safe serialization took
  11.803–12.887s, with 650/802 rows. These still bypass HTTP/auth/admission.
- No container CPU quota or cgroup CPU throttling was present at inspection.
- Rewriting A5801 with an equivalent account expression produced no new Caddy
  request and retained SERVICE_UNAVAILABLE. Do not count expression-only changes
  with unchanged evaluated arguments as fresh custom-function executions.
- Changing the supported header argument from `si` to `sí` produced a new
  authenticated Sheets request: HTTP 200 in 2.364s, 513 bytes. Readback preserved
  the formula and showed a header plus DATA_UNAVAILABLE, not a complete catalog.
  Current-data membership had changed; this is not a like-for-like latency pass.
- The subsequent VM-scoped inventory check found one active pending recovery
  job, 1,900 inventory IDs, checkpoint 240, discovery age 59s and 700/1,918
  canonical items acquired within 15 minutes. Recovery is running, not blocked
  on user action. Sustained availability across the acquisition cycle remains
  unproven; rerun populated catalog requests before judging latency fixed.

These counts inspect only the first four rows per output, not whole-matrix
completeness or correctness. Full-output checks, source comparisons, all-52 HTTP
status evidence, latency measurements and app acceptance remain open. Native
rendering was unavailable; formula/style readback used the Sheets API. No build,
deployment, runtime code change or ad-hoc production repair occurred in this unit.

Pilot: seller `82453304`; initial historical window 2026-08-08 through
2026-09-06, plus current snapshots. Other products are out of scope.

## Tenant-scoped formula audit identity: deployed and read-only runtime checks passed

On resumed verification on 2026-09-09, GCP access succeeded. The read-only
`/tmp/zeler-catalog-rollout-preflight.py` confirmed API source `57e106e` at
the intended `14509bbf...` digest and worker source `3a5a016` at `5f23d9ba...`.
Both services were healthy with zero restarts; free space was 5,897,539,584 bytes.
No activation, build or rollback was repeated.

After inspecting the VM copy of `/tmp/check-runtime-audit.py`, its read-only
execution passed: runtime identities separate seller/token/formula scopes,
same-scope replay is stable, and production audit indexes are compatible.
This executed the loaded API code with synthetic in-memory identities and read
Mongo index metadata only: **no production audit writes and no authenticated
HTTP verification**. The previously unconfirmed activation is now confirmed;
all-52 HTTP, real Sheet/app and the remaining hardening gates remain open.
The earlier local `/tmp/zeler-audit-scope.SHm996/` helper directory was absent
in this resumed environment; the inspected VM helper remains the evidence path.

API image for source `57e106eb00fe3cb0ecb1d6c2c8b43fd55e3c5661` is built,
verified locally and on the VM, and downloaded; **activation and final health
are now verified**:
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:14509bbffbe36757853357b9fa7be67168361eeb05d879e3b310d017cdb0fdbb`.
Build `a4db454e-0aa2-460a-a649-88f0818e7baa` succeeded; reuse it. CI lint
`34312143957` and test `34312143905` both passed before activation.
The activation process emitted `activating_cached_image` and created backup
`/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-57e106e`.
Observation was interrupted by an environment permission change; the local
process handle was subsequently absent. A read-only VM check then failed with
GCP reauthentication required. This is not evidence of either deployment failure
or successful final health. Do not repeat activation or rebuild the image.
The recovery procedure was to first inspect the running digest/health through
`/tmp/zeler-catalog-rollout-preflight.py`, then run `/tmp/check-runtime-audit.py`
only if the intended API image is active. Both checks have now passed as recorded
above. No rollback has been performed.

Local artifacts/helpers: `/tmp/zeler-audit-scope.SHm996/`; VM provenance inputs
`/tmp/audit-build.json`, `/tmp/audit-artifact.json`, recorded by the canonical
verifier. `/tmp/pull-audit-api.py` already completed in 11.29s with Compose
unchanged. Only unused older API cache `3c9d72f0...` was removed after checking
all containers, Compose, protected images and Artifact Registry recovery.
No data/volumes were deleted; free space after pull was 5,895,331,840 bytes.
The pre-activation API `d9203ac5...` is retained as the rollback authority; worker
`5f23d9ba...` does not need rebuilding. `/tmp/activate-audit-api.py` was invoked
once; do not use it as a status command.
Local `check-runtime-audit.py` is a read-only post-activation identity/index probe,
not an authenticated HTTP or production audit-write test.

Formula audit IDs now hash a structured identity containing seller, token,
formula and request ID (or the existing timestamp fallback). Reusing a client
request ID across sellers/tokens/formulas no longer silently drops later audit
records through duplicate-key handling. Same-scope replays remain idempotent.
HTTP payloads, audit fields, indexes and record schema are unchanged; repository
search found the old ID layout consumed only by its tests. Existing records are
preserved, not migrated or deleted. A replay spanning rollout may append one new
scoped record alongside its legacy record; it must not match the unsafe global ID.

TDD: scope regression initially **4 failed, 2 passed in 0.12s**. API/foundation/
extension-token service and API suites then passed **87 tests in 3.89s**, including
one token's two seller scopes using the same HTTP request ID and a replay.
Real local Mongo concurrent insertion/replay with four scopes and a preserved
legacy record passed **1 test in 0.39s** (`test_formula_recovery.py -k
formula_audit_scope`). Ruff check/format and mypy pass (507 files).

Rollback boundary is `_audit_id` and its matching tests; never delete audit
history. Reverting reinstates the known collision and is not an acceptable
hardening completion. The verified **sheets-api** image already exists; runtime
audit identity/index readback and current-image confirmation passed after the
interrupted observation. The other minimum-hardening and functional acceptance gates
remain open. No production data was accessed or changed by these audit tests.

## Buybox price dependency: local end-to-end recovery correction

The 15 previously missing pilot prices were acquired and persisted after rollout.
At `2026-09-09T04:38:39.936669Z`, all **15 canonical prices** were verified and
all **15 buybox prices** were present, current, and matched canonical product,
title, quantity and acquisition ordering. The item recovery completed on its
first attempt. The catalog intent traversed **15/15**, but remained truthfully
`failed/source_rejected`: only **1/15 snapshots has an offer count**. This proves
the selected price repair, not complete competition fields, sustained freshness,
all-52 authenticated HTTP or a real Google Sheet.

The initial read at `04:36:17.556427Z` found all 15 canonical items expired and no
safe prices. A normal scoped item job refreshed them first, then a normal catalog
intent refreshed the same identities. No 936-ID replay, broad inventory sweep,
manual business-field patch or global freshness-marker change occurred. This is
operator queue/runtime evidence; the single-intent missing-price dependency path
remains covered by the local HTTP/Mongo harness, not a manufactured production
failure. Do not claim this two-stage live repair proved that exact branch live.

Receipt: `/var/lib/zeler-platform/repairs/price-dependency-3a5a016.json` (0600).
Item key `fd4d1ade90838082a5ea2fb94bdeedeefa922e1c0c62543e5d2d717ce0f67eb4`;
catalog key `c44f47906407e35e8ec245fa5e1c7607e21c46261b9f2cdf553ec9faf4566986`.
Both jobs are terminal. Use `sudo python3 /tmp/recover-price-pilot.py status`
for read-only observation; `plan`, `items` and `catalog` already executed and
must not be repeated. Local helper is under `/tmp/zeler-price-dependency.wCVhKC/`.
An initial launcher import error occurred before admission (host Python 3.10
does not expose `datetime.UTC`); status proved no job before the corrected
launcher admitted the first request. No token, raw payload or PII was printed.

Images for source `3a5a016a4279815e76f5d7ff420ae20af76ccb10` are now
**deployed**, worker first and then API. Both explicit health endpoints returned
HTTP 200, Docker health was healthy and restart counts were zero. Each
single-image Cloud Build succeeded; digest/build/source
verification passed locally and on the VM:

- API build `6ec13922-046e-4c24-8428-e299c43d803d`, image
  `sheets-api@sha256:d9203ac552bd1ebd96e751f1cf87becbe0308e1caee7a5628cc40282905f30cf`.
- Worker build `fa757d7b-0cc4-45c5-b3b8-8cab066926cf`, image
  `sheets-worker@sha256:5f23d9ba77c64d20715ed0cc70794fd7a8b52362f4dbb216c2cccbc54961c40c`.

Both image names use repository prefix
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`.
Local build configs/receipts: `/tmp/zeler-price-dependency.wCVhKC/`.
VM receipts: `/tmp/{api,worker}-{build,artifact}.json`; canonical provenance map
was updated through the verifier and both bindings were read back successfully.
CI lint `34310663151` and test `34310663198` both passed before activation.
Reuse these builds; the later evidence-only commits require no new image.

Backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-3a5a016`
and `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-3a5a016`.
Rollback authorities are the previous running worker `7833b955...` and API
`3c9d72f0...`, both retained. No whole-Compose rollback is implied: replace only
the affected service binding, preserve acquired data and the compatible worker's
durable catalog jobs. The worker activation helper's final extra health probe
initially used the API port default and failed; read-only Docker inspection
proved the new worker healthy, then the correct `WORKER_HEALTH_PORT` probe
returned 200. Activation was not repeated. Corrected local helper and read-only
probe live in `/tmp/zeler-price-dependency.wCVhKC/`.

For pull capacity, also removed unused API cache `87a56f17...` and worker cache
`d2ccd62a...` only after all-container/Compose checks and Artifact Registry
availability confirmation. Current and special rollback images were preserved;
no data or volumes were deleted. Worker pull took 13.54s; API pull took 8.26s.
Both pulls left Compose unchanged and passed the 5 GiB guard. Final API health
observation had 5,896,896,512 bytes free. Runtime helpers are `/tmp/pull-worker.py`,
`/tmp/pull-api.py`, `/tmp/activate-price-worker.py`, `/tmp/activate-price-api.py`
and `/tmp/check-price-worker-health.py`; do not repeat completed mutations.

Post-deployment read-only pilot check at `2026-09-09T04:33:49.825599Z` still
found the same **15 missing prices**, all with transient promotion enrichment
and no safe fallback. No recovery was enqueued by this read: deployment alone
does not acquire data. `/tmp/price-gap-readback.py` checks these gaps with the
new API digest guard. Revalidate current item freshness before bounded recovery;
do not replay the already completed 936-ID intent merely to reproduce evidence.

Preflight found both existing services healthy with zero restarts, API `6cd66e9`
and worker `3b27cf4`; they do not contain this correction. Removed only unused
API cache image `1904ed9...`, after all-container/Compose/protected-image checks
and confirming its Artifact Registry availability. Freed 543,547,392 bytes,
leaving 5,905,989,632 bytes free at that observation. No data, volumes or Compose
bindings changed. Recheck capacity before each pull/activation; this margin may
not accommodate both new images while preserving the 5 GiB floor. Preserve the
currently running images as rollback authorities and the special rollback images.

The missing-price recovery now resolves item enrichment inside the existing
durable catalog job when neither competition nor verified canonical enrichment
provides the price. It reacquires competition against the refreshed item cut,
with at most one enrichment attempt per item per worker attempt. No extra queue
type, schema, formula-side Mercado Libre call or relaxed freshness guard is added.
The Mongo reader can also use an already verified canonical price when the
snapshot omits it; primary competition price retains precedence.

The first real-Mongo HTTP test exposed a rejected approach: independently queued
item and competition jobs both completed, but competition ran first and the
later item update invalidated its snapshot. Those extra dependency jobs and the
temporary reader flag were removed. The replacement preserves available
competition/offer fields on transient enrichment failure and retries through the
existing bounded policy rather than declaring missing prices complete.

Focused verification: `test_formula_recovery.py -k 'http_buybox_price_gap or
explicit_item_recovery'` passed **29 tests in 7.31s**. The authenticated local
HTTP harness covers admission, real Mongo persistence, worker acquisition,
temporary failure/retry and subsequent Mongo-only HTTP readback; Mercado Libre
responses are synthetic, not a production acceptance receipt. Protected Mongo
acquisition/execution/rollback suites passed **8 tests in 3.03s**. Ruff check,
format check and mypy passed (507 files). Broader regression across
`test_formula_recovery.py`, `test_formula_api.py` and
`test_formula_handlers_item_shipping_catalog.py` passed **482 tests in 88.51s**;
`test_formula_handlers_remaining_phase4.py` passed **63 tests in 0.15s**.

Rollback boundary: remove the reader fallback and worker-owned price enrichment
with their matching tests; preserve legitimately acquired Mongo data. This unit
affects **sheets-api and sheets-worker** images. Their deployed source matches
this correction. The selected price recovery/readback is recorded above; full
catalog field availability is not achieved. All-52 HTTP,
real Sheets/app, sustained freshness and the other goal acceptance gates remain
open.

Read-only hardening diagnostic also confirmed `_audit_id` collides for two
different sellers/tokens sharing the same caller-supplied `request_id`.
`FormulaAuditService.record` ignores duplicate-key insertion, so audit identity
is not tenant-scoped. The diagnostic used synthetic local inputs and no
production data; no audit implementation changed in this deployment unit.
Retain this as an unresolved minimum-hardening gate, not a new goal requirement.

## Full pilot catalog admitted after inventory completion; observing the same intent

Terminal result: at `2026-09-09T03:58:31.640Z`, the same catalog intent reached
**936/936** without readmission. All **936 primary snapshots** were persisted;
**921 have prices**, **257 have offer counts**. Its 47 chunks recorded failures
and the terminal state is `failed/source_rejected`, not complete fields. The
observer finished successfully after terminal readback; it is no longer running.
This now proves both durable >400-ID admission and traversal of the entire live
intent despite per-chunk source failures. No business flags or global coverage
markers were patched to obtain that result.

Readback started at `03:58:53.385Z`: inventory enumeration current, all 1,900 item
identities backed by 2,859 trusted SKU rows, **936 current buybox snapshots**, and
the same two invalid catalog-product identities. `CATALOGOBUYBOX` returned 937
rows (including the explicit inventory-gap row), with 921 rows having all first
eight columns available. Remaining unavailable item columns were price and sole
competitor. Read times were 9.2372s (buybox) and 8.4575s (`CATALOGO`); these single
operator reads do not establish p95, authenticated HTTP or Google Sheets latency.
Historical winning-time coverage remains explicitly unavailable for all 936.
Registry remained exactly 11 scopes/6 topics; global markers were unchanged.

Read-only `/tmp/catalog-price-gaps.py` identified **15 missing prices** whose
canonical items have valid base prices but `current_promotion` acquisition state
`transient`, aligned to the item cut. The conservative current-price fallback
correctly does not assert that a potentially promoted base price is the current
sale price. These are **recoverable dependencies**, not proven permanent absence;
next verify that formula-triggered recovery refreshes the item enrichment as well
as the competition snapshot. Do not treat catalogue replay alone as a fix or
weaken the promotion guard. Sustained freshness between sweeps remains unproven.

The inventory admitted by the prior formula completed at 1,900/1,900, observed
terminal at `2026-09-09T03:54:53.622Z`. A bounded VM observer then executed the
deployed buybox handler once and admitted its actual dependencies: two item IDs
and **all 936 buybox IDs in one durable intent**. Admission took 0.0336s; read
plus admission 4.8709s. Both admissions succeeded, with global freshness markers
unchanged. This is real >400-ID admission through the normal API admission helper,
but remains operator-backend evidence, not authenticated HTTP or Google Sheets.

Receipt (0600): `/var/lib/zeler-platform/repairs/post-inventory-catalog-6cd66e9.json`.
Catalog job: `4f96227ca77a9e3487b8183b8386b6adad843985993ad3f4ca000a7547bb2e08`.
Two-item job: `4e927e871aef344acdd68544ef8479c613efd0fb4662021a4ab8b48d3d50db89`.
Both were pending at `03:55:01.002Z`; catalog cursor was zero and all 936 IDs were
persisted. Do not repeat enqueue. VM `/tmp/post-inventory-catalog-pilot.py status`
observes these jobs. `/tmp/observe-full-catalog.py` polls the catalog job and runs
the read-only current-coverage helper once it is terminal; observation expiry does
not restart work. Local helper copies are in `/tmp/zeler-independent-recovery.6thjHk/`.
The preceding `/tmp/await-inventory-catalog.py` observer finished successfully;
it is not a background producer or a permanent runtime service.

Two bounded six-request offer comparisons were read-only. The first received
gateway `429/rate_limit_exceeded` for both samples and all three endpoints. A
later comparison, after the window elapsed, found both samples paused, competition
HTTP 200 / `not_listed`, and active product HTTP 200. The sample with no stored
offer count received offers HTTP 404 / `not_found`; the stored-count control
received offers HTTP 200 with paging. Thus paused status alone cannot imply zero
offers or permanent absence. No third comparison was launched.

Read-only gateway inspection confirmed its configured limit matches the code's
600-per-minute default; at `03:53:18.203Z` the current Sheets window had 103
attempts and was below the limit. No limiter, scope, retry policy or production
environment value was changed. Rate limiting explains transient refusals, not
permanent data absence. End-to-end freshness, terminal acquisition and formula
readback must still be measured before declaring the full catalog accepted.

## Independent recovery deployed; 152-ID live intent traversed despite partial source failures

Sheets API now runs source `6cd66e94416b0ac5572aca70cadd0189c2010e52`, image
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3c9d72f0248a39f954290a286c6a99ffbb683834431eaaeb097d3d4250c2d913`.
Build `119a665c-0c00-4dcd-b70f-74faa758ed94` succeeded with verified provenance.
Digest/build/source verification passed locally and on the VM. CI test
`34307676476` and lint `34307676475` both completed successfully before activation.
Worker remains healthy at `3b27cf4` / `7833b955...`; no worker build was needed.

Removed only unused older worker image `0cb733...`, after checking every
container, Compose, protected current/rollback/special images and Artifact
Registry availability. Freed 543,502,336 bytes; the image is recoverable and no
data/volumes were removed. Guarded API pull took 11.85s with Compose unchanged.
Activation finished HTTP 200, healthy, zero restarts, 5,373,468,672 bytes free.
Backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-6cd66e9`.
API rollback is `87a56f17...`; keep the compatible current worker and durable jobs.
Artifacts/helpers: local `/tmp/zeler-independent-recovery.6thjHk/`, VM
`/tmp/independent-api-{build,artifact}.json`, `pull-independent-api.py`,
`activate-independent-api.py` and `independent-catalog-pilot.py`.

At `03:44:48.836Z`, the real deployed Mongo-only buybox handler and normal API
admission helper independently admitted inventory recovery and all 152 currently
trusted buybox identities it returned. No IDs were manufactured and no global
freshness markers changed. Admission took 0.0836s; read plus admission 2.1861s.
This is operator-backend evidence, not authenticated HTTP or Google Sheets.
The earlier local SSH launcher exited 139 without output; read-only VM inspection
proved the exclusive pre-admission receipt absent before retrying the launch.
The successful receipt is `/var/lib/zeler-platform/repairs/independent-catalog-6cd66e9.json`
(0600). Do not repeat its `enqueue` mode; use `status`.

Catalog job `42d4c4b06c409c27cb5eb895e55fd3057b8a79084c134cc30d75357c3c0239a6`
reached offset 152/152 at `03:45:33.864Z`. Its eight chunks recorded terminal
source rejections, but all 152 primary snapshots were persisted with prices;
43 have offer counts. Final job state is correctly `failed/source_rejected`,
not complete coverage. Failed chunks do not mean every identity failed.
This proves bounded continuation with partial acquisition, not the >400-ID live
acceptance case. The formula saw fewer trusted identities as older source cuts
expired during CI/build/deploy; do not substitute this sample for the full seller.

The same formula also reopened inventory job
`5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f` through normal
admission. At `03:46:55.464Z`, it was pending retry at offset 400/1,900, attempt
one, `source_temporarily_unavailable`, available at `03:47:12.419Z`. Observe that
same job without restarting it. Once current inventory completes, measure and
admit the formula's actual full catalog dependencies promptly; the >400-ID case,
freshness across the complete sweep and remaining goal gates are still open.

Follow-up read at `03:48:06.422Z` found the new inventory enumeration current
but 1,200 item identities not yet backed by current trusted projections. It
returned zero current buybox rows and 374 missing known buybox identities;
persisting the earlier 152 snapshots did not establish ongoing visible coverage
after their canonical source cuts aged out. Both handlers kept unavailable cells
explicit (1.8308/2.359s), with registry 11/6 and markers unchanged. This is a
remaining end-to-end freshness/throughput acceptance gap, not grounds to relax
source validation or call the catalog complete.

## Independent catalog recovery no longer waits for every inventory item

Post-sweep production evidence confirms the dependency, not just an intermediate
state. The existing inventory job completed at `2026-09-09T03:33:28.221Z`, offset
1,900/1,900, zero unavailable inventory items, with the `03:24:57.065Z` discovery
cut. It was not restarted. At `03:34:09Z`, `/tmp/current-catalog-coverage.py`
found all item projections trusted (2,859 SKU rows for 1,900 identities), 936
missing buybox snapshots and two invalid catalog participants. Both invalid
participants have an invalid/missing `catalog_product_id`; this is distinct
from missing item projections and is not yet proof of permanent API absence.
Both deployed catalog handlers requested only those two item IDs, not the 936
known buybox identities. Read times: 4.337/4.5364 seconds. Registry remained
exactly 11/6 and global markers unchanged. No raw identity, price or customer data
was printed. The fix is committed/pushed as `555be9e`; its CI runs
`34307610607` (test) and `34307610515` (lint) were still in progress at this check.

During the live inventory sweep, the deployed Mongo-only dispatcher reported
322 missing buybox snapshots but requested only 1,339 missing item projections;
`CATALOGO` similarly requested inventory only despite 335 missing buybox items.
The two read calls took 2.9483/3.4679 seconds. They ran at different instants while
the worker advanced, so their counts are not one atomic coverage snapshot.
Registry remained exactly 11 scopes/6 topics and global freshness markers were
unchanged. Helper `/tmp/current-catalog-read.py` is operator-backend evidence,
not authenticated HTTP or a Google Sheet test.

The same dependency reproduced locally in `CATALOGO`, `CATALOGOBUYBOX`,
`OBTENER_CATALOGO` and `CATALOGO_COMPLETO`: a missing unrelated item prevented
recovery of known product/competition identities. Four handler regressions
failed in 0.11 seconds before the fix. Four HTTP cases failed before support
for independent recoveries (0.40 seconds). An additional sales-coverage
regression failed separately: inventory/competition could also starve orders.

`FormulaExecutionResult` now retains its primary recovery and carries independent
additional recoveries internally. The API admits them concurrently through the
existing validated, seller-scoped queue and one-second per-admission deadline,
instead of serially adding deadlines. Available values, explicit unavailable
cells and existing metadata remain intact. `recovery_requested` means at least
one admission succeeded, not full coverage. Rejection/timeout of the primary
does not discard another successful admission; timed-out admissions are cancelled.
No Mercado Libre request runs in the formula path. Existing transactional seller
capacity and durable bounded catalog-intent processing remain unchanged.

Verification: focused HTTP/handler suites **148 passed in 4.09s**; full recovery
plus those suites using local Mongo replica set **538 passed in 85.04s**;
protected stock-time replica-set suite **8 passed in 2.85s**. Ruff check/format
and mypy (507 files) pass. The local Mongo container was stopped after the
environment restart; only `zeler-goal-mongo` was restarted, not the older container
sharing its volume. No database volumes were removed.

This correction is not deployed yet. Build a new `sheets-api` image from its
CI-approved commit, verify provenance and capacity, then verify real handler/API
admission and durable catalog cursor progress. Worker queue/schema behavior did
not change and the deployed `3b27cf4` worker already supports these intents.
Rollback scope: the additional-recovery result field, API admission fan-out and
the catalog handler additions with their tests. No migration or deletion is
required; already admitted jobs can finish on the current worker. Full seller
coverage and the remaining goal acceptance gates are still open.

## Corrected catalog intent deployed; current inventory recovery started

Both Sheets services now run exact source
`3b27cf4bd73678151b2375029971afff3221e82e`. GitHub Actions lint
`34304958522` and test `34304958509` completed successfully before activation.
The existing builds were reused, not rebuilt:

| Service | Successful build | Deployed digest |
| --- | --- | --- |
| sheets-worker | `804a6a93-0a95-4a83-9bda-9c3477e25dae` | `sha256:7833b95553c02792d205756c3fbd2935a9240b930e5c9f93c14e0c5b6aa53155` |
| sheets-api | `42652820-3356-4b22-863c-8c1977b1b743` | `sha256:87a56f17a5da0eda05f8931497646e15cd9fdc84d5e4bf05af9d3f15e7c2d565` |

Digest/build/connected-repository/source verification passed locally and on the
VM; the canonical image map was updated. Local temporary files from the earlier
session were absent. Recovered existing helpers from the VM and adapted their
exact digest/source guards in `/tmp/zeler-catalog-resume.E4rN37/`, then copied
the corrected helpers and freshly fetched provenance artifacts to VM `/tmp/`.
No business logic or test changes were made in this rollout.

Fresh preflight found 6,468,100,096 free bytes and both prior services healthy
with zero restarts. Guarded worker/API pulls passed in 11.17/10.87 seconds,
respectively, with Compose unchanged. Worker was activated before API; each
activation verified its expected prior digest, pilot settings, zero running
recovery jobs, cached image and source mapping. Both finished healthy with
HTTP 200 and zero restarts. Free space after activation: 5,380,644,864 bytes.
Backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-3b27cf4`
and the corresponding `pre-sheets-api-activate-3b27cf4` file.

At `2026-09-09T03:24:56.253Z`, normal queue admission reopened the pilot inventory
job `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`
exactly once. VM helper: `/tmp/corrected-current-inventory.py`; receipt:
`/var/lib/zeler-platform/repairs/current-inventory-3b27cf4.json` (0600).
Initial state was pending, attempts zero, offset unset. The 1,900 IDs and
01:08:42 observation shown at admission belong to the prior enumeration, not
proof of a new completed sweep. Continue with helper mode `status`; do not
repeat `enqueue` or restart on an observation timeout.

At `03:25:37.252Z`, the same job was running on attempt one, with a new
`03:24:57.065Z` enumeration of 1,900 identities, offset 240 and zero unavailable
items so far. This confirms worker execution and durable progress, not completion.

Next prove current enumeration and normal catalog recovery beyond 400 IDs, then
read back actual formula coverage. Deployment/health does not establish full
seller coverage, all-52 HTTP acceptance, Google Sheets acceptance or historical
completeness. Rollback API to `1904ed9...` first to stop new large admissions;
do not return the worker to `d2ccd62...` while large intents remain active.
Drain/resolve them with the new worker without deleting durable recovery data.

## Catalog-intent activation stopped by stale HTTP test expectations

Both connected-repository builds succeeded for exact source
`f6ae9dd173ebe4660c434eea8ce2b7ec5fd0af53`:

| Service | Build | Digest |
| --- | --- | --- |
| sheets-worker | `b7304036-28c9-4723-b833-1216286dee3d` | `sha256:e35c888272c405b1381271e06765a6044e618da3bf8aaadd5a6b0e3092e11662` |
| sheets-api | `05c2752a-36d9-429e-befc-d0e5543f5832` | `sha256:cdf4343e30d28b41afedb0e792b908cb6ee4725d6761e6b33a72b11fdaeb08d2` |

Image references use `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`
plus the service name and digest. Digest/build/source verification passed locally
and on the VM, updating `/var/lib/zeler-platform/image_to_commit.json`. Artifacts
and guarded helpers are in local `/tmp/zeler-catalog-rollout.tdDS4D/` and VM
`/tmp/`: `intent-{worker,api}-{build,artifact}.json`, `pull-intent-{worker,api}.py`,
`activate-intent-{worker,api}.py`, and `intent-storage-check.py`.

Approved-runtime storage check found no recovery-collection validator, all three
expected recovery indexes, zero pending/running jobs and zero existing large
intents. No schema mutation was necessary. Removed only unused old cache worker
`f70530...` and API `155a13...`, after checking every container, Compose, protected
images and Artifact Registry availability. Each removal freed 543,498,240 bytes;
both images remain recoverable. No volumes or business data were removed.

Pulls completed in 11.86 seconds (worker) and 9.06 seconds (API), leaving
5,382,758,400 free bytes with Compose unchanged. CI lint `34304308632` passed;
test `34304308697` **failed**: **2 failed, 3,778 passed, 390 skipped in 467.22s**.
Both failures are `test_catalog_product_recovery_http_keeps_values_and_bounds_admission`
(`success`, `duplicates`), which still expected two 20/1 jobs for 21 IDs. The new
contract intentionally persists one complete intent. Activation did not run.

The HTTP test now requires exactly one typed catalog intent containing every
deduplicated ID, while retaining checks for seller scope, available response
values, invalid/mixed inputs, capacity rejection and timeout cancellation. This
is a test-expectation correction, not removal of the HTTP contract. The full API
suite (`uv run pytest modules/sheets/tests/test_formula_api.py --tb=short`) passed
**38 tests in 1.69s**; Ruff check/format and mypy (507 files) pass. No executable
code changed after source `f6ae9dd`. Do not deploy the cached builds based on a failed CI gate;
verify the corrected main commit and its exact build/source mapping first.
Then require fresh capacity/readiness checks and activate worker before API.
Current rollback images remain worker `d2ccd62...` and API
`1904ed9...`; never return to an old worker while new large intents remain active.
The real >400-ID recovery and complete formula acceptance remain pending.
Prepared `/tmp/intent-current-inventory.py` has **not** been enqueued and still
guards the cached-but-not-deployed digests. Its intended receipt
`/var/lib/zeler-platform/repairs/current-inventory-f6ae9dd.json` has not been created
by this session. Adapt image guards to the actually approved deployment before use.

## Catalog recovery retains complete intent and resumes bounded chunks

Large product/buybox requests now persist one validated, seller-scoped intent
with up to 10,000 explicit IDs before returning, within the existing one-second
admission budget. The worker processes at most 20 identities per claimed chunk,
using the existing four-acquisition concurrency and source/ownership checks.
`catalog_offset` advances under the owned lease; no continuation depends on a
second formula call or in-memory worker state. Small requests keep their existing
20-ID contracts. Seller capacity remains 20 active jobs, not 20 expanded batches.

Transient failures retain bounded retries on the current chunk. Terminal failure
records its offset/reason and advances to the next chunk, preserving successful
snapshots; the overall job remains failed when any chunk failed. A crash on the
last permitted attempt atomically reacquires the expired lease to record that
failed chunk and continue the tail, without another upstream attempt. Repeated
admission of a pending intent leaves its cursor unchanged. Reopening a terminal
intent resets progress/failure offsets without bypassing its cooldown.

TDD initially produced **8 failures in 2.73s**, covering lost tail admission and
restart/error continuation; expired-final-lease regression separately failed in
**0.39s**. After correction, focused tests passed **9 in 8.06s**, including full
401-ID acquisition/persistence for both models, 41-ID 403/503 cases, stale-owner
rejection, final-lease exhaustion and cooldown-preserving reopening. Command:
`MONGO_URI=<local replica-set URI> uv run pytest
modules/sheets/tests/test_formula_recovery.py -k 'catalog_intent or
retains_full_request' --tb=short`. Final focused run including invalid-tail,
oversize and pending readmission checks: **10 passed in 7.90s**. Expanded recovery,
item/shipping/catalog handlers, phase-4 handlers and schema suite: **518 passed
in 83.39s** (collected before the final supplemental checks). Protected suite:
**8 passed in 2.53s**. Ruff check/format and mypy (507 files) pass. Full-root local
execution was not repeated after the recorded native interpreter failures;
complete CI and real-runtime acceptance remain required.

Deployment remains pending and affects **both Sheets images**. Verify recovery
collection options/indexes in the VM, then deploy the **worker before the API**:
the old worker cannot execute large intents. Before rolling back the worker,
stop new large admissions and resolve/drain pending intents with the new worker;
do not delete intent documents or recovered data. This change adds fields to the
existing recovery collection, not a new collection or a business-schema change.
Rollback scope is the new intent type, admission branch, cursor/lease continuation
and tests. The latest deployed worker remains `f598ed2`, API `f4573de`.

After deployment, prove a full pilot catalog request progresses beyond 400 IDs
through the normal asynchronous path, with current source data, bounded HTTP
latency and explicit remaining unavailable fields. Local mocked-upstream Mongo
tests do not establish live seller completeness, historical coverage or all-52
Google Sheets acceptance.

## Catalog scale defect reproduced; offer absence is not proven

Read-only six-request probe `/tmp/offers-availability.py` on the approved VM
worker (`d2ccd62...`) examined the same frozen two-item receipt. Both canonical
items are paused. For each, competition returns HTTP 200 with `status=not_listed`,
no winner, no product ID and no `only_competitor` field. The owned catalog product
returns HTTP 200, `status=active`, zero children and no buybox winner. Its offers
listing returns HTTP 404 / `not_found`. No business data was written. Thus the
product itself is not missing or inactive; neither a total of zero nor permanent
unrecoverability is established. Keep the unavailable offer flag explicit.

The official [competition listing contract](https://developers.mercadolibre.com.mx/es_ar/envio/competencia-en-catalogo)
still identifies `/products/{product_id}/items` as the offer listing. The
[product contract](https://developers.mercadolibre.com.mx/es_mx/buscador-de-productos)
distinguishes active terminal products from parent/inactive products. No verified
alternate source for this count was found; the two-case evidence does not justify
guessing a boolean or excluding paused publications from the current surfaces.

Separately, a real local Mongo test exposed lost recovery intent at seller scale.
`_request_formula_recovery` admits batches of 20 until the seller's 20-active-job
capacity is reached, then returns false without persisting the remaining IDs.
A single call with 401 IDs persisted only 400 for both product and buybox models.
No durable continuation exists for the final ID; another caller invocation is
currently necessary. The one-second admission budget can also truncate admission,
but this test specifically reproduced the capacity boundary, not a timeout.

TDD: `MONGO_URI=<local replica-set URI> uv run pytest
modules/sheets/tests/test_formula_recovery.py
-k retains_full_request_beyond_active_job_capacity --tb=short`:
**2 failed, 380 deselected in 0.96s**. New tests remain uncommitted pending the
implementation. Next retain full bounded catalog intent durably, process it in
bounded resumable chunks, and preserve seller capacity, leases, retry limits and
the HTTP budget. Do not fix by raising capacity or requiring another formula call.
No executable production change or new build occurred in this investigation;
worker remains source `f598ed2`, API `f4573de`. All full-goal gates remain open.

## Acquired-price worker deployed; both real missing prices recovered

Cloud Build `da17604f-0c14-43ad-b618-d5068e90377f` succeeded for exact connected
repository source `f598ed20379fad7d9acd0f6174abd29e6831506a`. The worker image is
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:d2ccd62a30fb407dd268190f1c254c9d4035563c0f0911d99107af80e189bae3`.
Digest/build/source verification passed locally and on the VM, updating the
canonical image map. Artifacts and guarded helpers are in local
`/tmp/zeler-catalog-rollout.tdDS4D/` and VM `/tmp/` with `price-worker-*`,
`pull-price-worker.py`, `activate-price-worker.py`, and `two-price-cases.py`.

Only unused worker cache `d3bee37...` was removed after checking every container,
the Compose configuration, protected images and its availability in Artifact
Registry. It freed 543,514,624 bytes; no volumes or business data were removed.
The new image pull completed in 14.37 seconds, leaving 5,384,400,896 free bytes
and Compose unchanged. An initial SCP connection closed before transferring
the artifacts; the verifier refused missing input and no pull occurred until
the transfer and verification succeeded.

CI test `34302749490` and lint `34302749492` both passed before activation.
The worker now runs the verified image above, source `f598ed2`, with HTTP health
200 and zero restarts. Activation checked capacity, zero running recovery jobs,
the pilot recovery settings, exact image provenance and the unchanged healthy
API. Backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-f598ed2`.
Free space after activation was 5,384,175,616 bytes. Worker rollback is the prior
`0cb733...` image; the API remains `1904ed9...` at source `f4573de`.

The frozen two-item refresh job `c467f3...` was reopened once through normal
admission at `02:28:26.734Z` and completed at `02:28:28.680Z` on September 9.
No source timestamps or global freshness markers were manually advanced.
Buybox job `ea3b67...` was reopened once at `02:29:10.793Z`, ending
`failed/source_rejected` at `02:29:11.269Z`: the independent offers resource
remains rejected, not silently complete. At `02:29:40.674Z`, both snapshots had
numeric prices equal to their acquired canonical price, current competition
cuts and source alignment. Their original offers cuts and value hashes remained
unchanged. Neither prior row had a known numeric offer count; this is not live
proof of retaining an existing numeric count.

Mongo-only dispatcher readback returned CATALOGOBUYBOX in **1.2652s**, three rows
of width nine (two items and an explicit inventory gap). Unavailable cells fell
from 13 to 11; both item rows now have all first eight columns available, with
only column 8 (sole-competitor flag, zero-based) unavailable. CATALOGO took
**1.3843s**, retaining 42 unavailable cells and the explicit unreconciled-history
reason for both items. Registry remained exact at 11 scopes/6 topics and global
freshness markers were unchanged. This proves the price fallback, not current
whole-seller coverage, authenticated HTTP or a real Google Sheet.

Read-only follow-up on the VM: `sudo python3 /tmp/two-price-cases.py status`
and `sudo python3 /tmp/two-offers-read.py`. Both `refresh` and `recover` already
executed; do not repeat them as status checks. The immutable sample receipt
remains `/var/lib/zeler-platform/repairs/two-offers-cases-f4573de.json`.
Remaining work includes full-seller freshness/recovery, unresolved offer and
historical data, all-52/end-user acceptance and minimum hardening. This evidence
note needs no additional image build; the worker runtime change is deployed.

## Missing competition price uses the verified acquired selling price

The recovery worker now fills a null/missing competition price from the owned,
fresh canonical item, without adding API requests. A verified absence of promotion
uses the item's numeric price; a trusted promotion uses its sale amount. The
promotion state must belong to the same acquisition cut as the item. Promotional
projection currency and cut must also match. Transient, stale, malformed or
currency-conflicting evidence does not authorize substitution. An existing
competition price remains authoritative, including when a promotion is stored.
Explicit numeric zero is retained; boolean and invalid prices are rejected.

This addresses the two-case follow-up probe in `/tmp/buybox-price-source.py`:
both live competition responses had null current price and currency, while the
canonical items had numeric prices and authoritative absence of promotion.
It does not manufacture offer counts or historical coverage. The existing lease,
seller ownership and canonical BSON recheck still guard persistence.

TDD command: `MONGO_URI=<local replica-set URI> uv run pytest
modules/sheets/tests/test_formula_recovery.py -k buybox_explicit_item_recovery
--tb=short`. Before implementation: **3 failed, 15 passed in 3.95s** (normal,
promotional and zero fallback). After: **18 passed in 4.04s**. The new cases use
the strict snapshot validator in real local Mongo. Ruff check/format and mypy
(507 files) pass. Protected acquisition/execution/rollback suite: **8 passed in
2.96s**. Expanded recovery/handler/schema regression: **509 passed in 72.97s**
(`test_formula_recovery.py`, `test_formula_handlers_item_shipping_catalog.py`,
`test_formula_handlers_remaining_phase4.py`, `test_sheets_schema_contract.py`,
with the local replica-set URI). No new full-root run was attempted after the
previously recorded native interpreter failures; these scoped results do not
replace the complete CI gate or production acceptance.

Runtime acceptance is pending. Only `sheets-worker` consumes the new helper;
the API's existing promotional reader is unchanged. Build a verified worker
image from the committed source, then refresh/recover the frozen two-item sample
through normal admission and verify numeric persisted price and Mongo-only
readback. Do not replay old helpers with obsolete image guards or reuse expired
source timestamps. The last verified API/worker source remains `f4573de`.
This is not all-52 HTTP, real Sheet or full-seller acceptance.

Rollback boundary: remove the worker's null-price substitution and the added
`acquired_current_price` helper plus its cases; retain independently dated offer
handling, schema and legitimately acquired data. No schema migration is needed.

## Real 404 cases now persist competition without advancing retained offer cuts

The two exact stale members of the earlier 20-item batch were resolved from their
stored source/snapshot cuts. Private receipt (mode 0600):
`/var/lib/zeler-platform/repairs/two-offers-cases-f4573de.json`. It retains identities,
original cuts and offer-field hashes, not raw source responses. All operations ran
through the approved API container against the expected API `1904ed9...` and worker
`0cb733d...` images.

Only these two items were admitted for refresh. Item job
`c467f3f14eafe0e7488eccd4b3f721798646c98f1d2d4696c79947d697124549`
completed at `2026-09-09T02:04:07.932Z`. After verifying their current source-bound
rows, buybox job
`ea3b67b16ebeed2eadf03cb1ab19a1bc33f6bb252261d42860ee2be102f9f834`
was admitted once and ended `failed/source_rejected` at `02:04:36.565Z`.
Do not repeat `prepare`, `refresh` or `recover`; read-only status is
`sudo python3 /tmp/two-offers-cases.py status`.

At `02:05:10.925Z` and `02:07:22.354Z`, both snapshots had newer, current competition
cuts aligned with the acquired item product/title/stock. Each had explicit
`offers_snapshot_at` equal to its recorded prior cut; offer-value hashes were
unchanged. Neither prior snapshot had known offer count/sole-competitor values.
Thus the live evidence proves current competition persists despite rejection and
the old cuts are not advanced, but does **not** prove retention of a real prior
numeric offer count (that case is covered by local Mongo tests).

Mongo-only formula observations returned three rows each: two publications and
an explicit inventory gap, widths 9/24. CATALOGOBUYBOX took 2.1099 seconds and
CATALOGO 2.0206 seconds; repeat reads took 2.0614/1.525 seconds. They retained
13/42 unavailable cells respectively; no publication had all first eight buybox
columns available. Detailed counts isolated missing buybox columns 5 and 8
(zero-based): current price and sole-competitor flag. History remains explicitly
unreconciled for both publications. Registry was exactly 11/6 and global markers
were unchanged. This is partial backend acceptance, not full formula or Sheet/HTTP
acceptance, and no global inventory freshness was fabricated.

The follow-up read found numeric, non-null `items.price` in both freshly acquired
canonical documents, but null snapshot price. Next: verify the formula's price
semantics against the acquired selling-price fields, then connect the justified
Mongo fallback instead of leaving recoverable price unavailable. The independent
offers 404 must remain explicit; it does not justify inventing a competitor flag.
No executable source or deployment change was made in this evidence unit; both
running sources remain `f4573de`. No image rebuild is needed for this note.

## Independent offer cuts deployed in schema → API → worker order

Both Sheets services now run source `f4573de10271dafc73a9d6f48418872479db2fcf`:

- API build `513de250-a8d3-434f-a2f2-cab2435e2cfd`, digest
  `sha256:1904ed9bad23d3902075f86f428ab9a142fce79bfee73289af87bbef06b972b7`.
- Worker build `3d5c1f88-9c10-4844-850b-d46e22427b2a`, digest
  `sha256:0cb733d96532584af5ae6e34622a58aab18e66484fb39c1d47cd1dd5d49fd84b`.

Both builds succeeded and passed local plus VM digest/build/source verification
into the canonical image map. GitHub lint `34300767649` and test `34300767575`
succeeded before schema application or service activation. This closes the CI
gate, not the previously failed local full-runtime executions or end-user acceptance.

The runtime validator exactly matched the prior schema before `collMod`. Only
nullable `offers_snapshot_at` was added, retaining strict/error and all indexes.
Schema was applied before the API, and API health was verified before worker
activation. Final read-only checks confirmed the new exact schema, both expected
running digests/source commits, HTTP health 200, zero restarts and zero running
recovery jobs. Free space was 5,402,595,328 bytes at the final observation.

To maintain the 5 GiB floor, removed only unused cache worker `ae3c245...` and,
after API activation, API `0944389...`; each released about 543 MB. Every container
was checked, current/immediate rollback images were retained, and both removed
images were verified recoverable in Artifact Registry. No volumes or business
documents were deleted. Pulls took 16.52 seconds (API) and 11.66 seconds (worker).
Unique Compose backups end in `.pre-sheets-api-activate-f4573de` and
`.pre-sheets-worker-activate-f4573de`. Prior running images were API `155a13...`
and worker `f70530...`; the reader rollback restriction below still applies once
independently dated snapshots are written.

No recovery was re-enqueued in this rollout. Next: use the two precisely identified
404 cases from `/tmp/buybox-rejection-source.py`, refresh only their required item
data, and prove new competition persists while old offer cuts remain unchanged.
Existing temporary probes with old image guards must be adapted, not blindly run.
Read-only deployed-schema helper: `/tmp/offers-schema-active.py check`.
Full 52-formula HTTP, real Sheet/app, full seller coverage and minimum hardening
remain open. This evidence-only commit does not require another image build.

## Preserve current competition independently of missing offers

The read-only `/tmp/buybox-rejection-source.py` probe established the endpoint
failure on both stale members of the 20-item batch: competition returned HTTP
200 with matching item identity, while `/products/{product}/items` returned 404.
One current control returned 200 for both endpoints, with valid offers list and
paging total. No data or job was changed. A 404 here is not proof that historic
offers are permanently unrecoverable.

The worker previously retained the entire old snapshot after any offers failure.
It now persists acquired competition and independently resolves the winner.
Previously acquired offer count/sole-competitor values survive for the same
product, retaining their original optional `offers_snapshot_at` cut. A failed
first acquisition writes null for that cut; a successful one writes the actual
acquisition cut. The reader uses these fields only while their own cut is valid
and within 15 minutes. Expired values remain stored but render unavailable without
hiding current competition. Existing snapshots lacking this new field use their
original single `snapshot_at`, preserving the previously verified producer contract.
Canonical ownership, BSON reread, lease and newer-snapshot guards remain intact.

Six focused cases failed before the change: retained 503/404 prevented the new
price from being stored, and both HTTP formulas treated expired/null offer cuts
as complete. The updated Mongo/HTTP/recovery suite passes 41 cases in 12.48 seconds,
including independently resolving a foreign winner when the offers endpoint fails.
Ruff, format, mypy (507 files) and exported schema drift checks pass.
Three default full runs terminated with SIGSEGV/139 during collection; a separate
collect-only run passed. The local interpreter is Python 3.11.0rc1. An isolated
managed Python 3.11.15 run with `--locked` dependencies reached execution but
terminated with `Illegal instruction`/132 around 15%, outside this changed path.
Neither error has a proven root cause and neither run counts as acceptance.
The complete recovery file, both affected handler suites and Sheets schema tests
passed together: 501 tests in 73.85 seconds. Protected Mongo scenarios passed
separately: eight tests in 3.01 seconds. The full regression remains pending in CI;
do not deploy this change until that gate is complete. The repository environment
and lockfile were not replaced to obtain these results.

Deployment is pending and ordered: apply the additive nullable-date schema for
`sheets_catalog_buybox_snapshots`, activate the new Sheets API reader, then activate
the new worker. **Do not deploy the worker ahead of the API**: an older reader
would mistake retained offers for newly acquired fields. Both images need rebuilding.
Verify the two real 404 cases after refreshing only the required item data, prove
current competition remains readable and retained offer cuts do not advance on
failure, then continue full-seller/52-formula acceptance. No freshness marker or
global inventory coverage may be fabricated to make the smoke green.

Rollback: return the worker first to its prior digest; retain the new API reader
while any independently dated snapshots exist. Reverting that reader requires
first ensuring those snapshots cannot be misread by the old reader. Keep the
additive schema and persisted offer data; do not delete them to simplify rollback.

## Optional product response fix deployed; source acquisition still incomplete

Cloud Build `c1ea0ae9-f913-4011-b805-c97de9c943eb` succeeded for source
`b26389469fa85ee9e19f0c0fcbe5853be7150e5f`, producing worker digest
`sha256:f70530a507c2302eaa373e07269fccf90af9b45a3dc724ac3086ab110f25569d`.
Local and VM provenance verification passed into the canonical image map.
GitHub test `34299202036` and lint `34299202086` both succeeded before activation.
The single-service rollout checked zero running recoveries and the 5 GiB floor;
pull took 12.68 seconds, with Compose unchanged until activation. New worker
health is HTTP 200, zero restarts. Backup:
`/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-b263894`.
Rollback is the prior running worker digest `d3bee37...`; API remains `155a13...`
from `c6b540b`, unchanged. No other service or data volume was modified.

The exact 20 publications from the failed buybox batch were refreshed through
normal item recovery, not by repeating the full inventory. Item job
`40efa1115603f57de2fa79521d34f535e5853dbd926b9c2c63db43be69dce7a9`
completed at `2026-09-09T01:36:10.399Z`, attempt one. After source-bound row
verification, the same buybox job `835e036...` was reopened at `01:36:52.872Z`.
It ended `failed/source_rejected` at `01:36:56.385Z`, attempt one. At the
`01:37:27.362Z` status read, 20 snapshots existed (four before the attempt), with
18 fresh snapshots matching canonical product/title/stock and acquired after
the item sync. This is material acquisition, **not** full purpose-field acceptance.
Do not blindly re-enqueue; identify the rejected source endpoint next.
Read-only status: `sudo python3 /tmp/retry-buybox-product.py status`.
The helper's `refresh` and `recover` modes have already run and must not be repeated
merely to recreate this receipt.

The unchanged API's Mongo-only four-formula smoke now returned 21/21/22/22 rows
with widths 9/24/3/6 in 1.2137/1.6257/1.6544/1.1657 seconds. Buybox and CATALOGO
returned useful fields plus 60/203 unavailable cells respectively; expired global
inventory and historical gaps remained explicit. Product matrices remained
unavailable. Registry stayed exactly 11 scopes/6 topics and freshness markers
were unchanged. These are operator backend observations, not authenticated HTTP,
full-seller coverage, or real Google Sheet acceptance.

A separate attempt to select the earlier two invalid publications by current
`catalog_listing=true` and null product failed its selection assertion before
source evidence was returned. It does not establish why those two original rows
were invalid; reacquire their precise identities from a current reader result
before diagnosing them. Do not infer catalog participation from missing product alone.

This evidence-only follow-up needs no new image. The intended acquisition source
`b263894` matches the running worker; further runtime verification is still needed
for source rejection and complete formula behavior.

## Completed inventory exposed an over-strict competition response check

The existing inventory job completed at `2026-09-09T01:18:06.822Z`: offset
1,900/1,900, zero unavailable IDs, acquisition cut `01:08:42.144Z` (564.678
seconds). It was not restarted. During acquisition the four backend formula
reads returned widths 9/24/3/6 in 10.4439/14.9521/10.1077/9.9088 seconds;
CATALOGO retained 936 participating rows plus an explicit incomplete row, with
history reason `catalog_history_not_reconciled`. These are Mongo-backed operator
reads, not authenticated HTTP or Google Sheets acceptance. Markers were unchanged.

After completion, the canonical reader found 936 missing buyboxes and two
invalid publications. Both invalid sources lacked `catalog_product_id`; title,
quantity and boolean participation were present. Source comparison for these two
remains pending. Other verified publications were not blocked by those rows.

One normal recovery batch for 20 verified participants was admitted at
`01:20:02.129Z`, key
`835e036f53dcb2d87638a974015c57c3fca0f2a488f35712185ca1455c3e3573`.
It terminated `failed/source_incomplete` at `01:20:04.444Z`, attempt one. Four
snapshots already existed before admission; their count is not new acquisition
evidence. Do not blindly repeat admission. Receipt:
`/var/lib/zeler-platform/repairs/current-buybox-29e88e5.json`; status helper
`sudo python3 /tmp/current-buybox.py status`.

A read-only worker-container probe queried three batch members through the
Sheets gateway identity. All three responses were HTTP 200, matched `item_id`,
had status and normalized sharing fields, but had no non-null product ID. Their
owned canonical items had fresh product, title and quantity. The strict equality
check rejected the response before persistence. No probe business data was written.
Helper: `/tmp/buybox-source.py`; no raw responses or customer fields were printed.

Recovery and notification acquisition now permit an absent/null response product
ID only by using the separately acquired owned item's product. Explicit conflicting
product IDs and wrong item IDs still fail. Recovery retains the canonical BSON
recheck before writes; notification persistence still validates the source product.
Four new absent/null TDD cases failed before the fix; all 16 focused Mongo cases
then passed in 2.93 seconds, including ownership, expiry, changed source, conflicting
product, replay and acknowledgement failure. Static checks pass for 507 files.
The first full regression terminated with interpreter SIGSEGV/139 during collection;
the new normal run passed: 4,137 tests, nine expected skips and 356 warnings in
138.62 seconds. The eight protected Mongo tests passed separately in 3.35 seconds;
the remaining skip is the optional Caddy check. The failed invocation is not
acceptance evidence.

Rollback is the optional-response-product guard in `catalog_observations.py` and
`formulas/recovery_worker.py` with its tests. No schema or data change is required.
This source correction is not deployed: build a new Sheets worker image from the
verified commit, then verify the failed batch via real source acquisition and
Mongo-backed reads. API formula readers do not use either changed acquisition path.

## Reader/writer corrections deployed; current inventory recovery running

Approved service-only rollout now runs API source `c6b540b` at digest
`sha256:155a13ab9a06a144cffa1ef243d0486e3c982f937c7ef9223ef91e4a8149d752`
and worker source `29e88e5` at
`sha256:d3bee37f73336de7e6d27415c24d2f2a8a121c5e5e5b9ff25fd0c883a94ae0a3`.
Worker Cloud Build `68323bfa-1743-4a9c-832e-6d83f43f7a32` succeeded; both image
proofs passed exact-source verification into the canonical VM map. Both sources
passed GitHub lint/test (worker test `34297295104`, lint `34297294831`; API test
`34296728426`, lint `34296728441`). No new build was started in this rollout.

Free space and zero running recoveries were checked before each activation.
Exact unused cache images API `37b750d...` and worker `c3ad9ee...` were removed
after all-container checks, retaining current/immediate rollback images. They
remain recoverable from Artifact Registry; no volume or data was deleted.
Each single image replacement used a unique backup, `up --no-deps --pull never`,
and reached HTTP health 200 with zero restarts. Backups end in
`.pre-sheets-api-activate-c6b540b` and `.pre-sheets-worker-activate-29e88e5`.
Prior running rollback digests are API `0944389...` and worker `ae3c245...`, both
with competition support. Preserve acquired data if rollback becomes necessary.

The read-only API smoke returned unavailable inventory rows with correct widths
9/24/3/6 in 1.2966/1.8193/1.3366/1.2799 seconds for CATALOGOBUYBOX/CATALOGO/
OBTENER_CATALOGO/CATALOGO_COMPLETO. Registry was exactly 11/6 and markers unchanged.
Zero current participating rows meant the history-specific metadata branch was
not live-data acceptance. This is explicit expiry, not a complete formula result.
The worker image's canonicalizer accepted a real stored order and rejected its
in-memory copies missing quantity or unit price with the static expected error;
Mongo readback was identical. That probe made no business writes and does not
replace full source-response recovery acceptance.

Because the real reads exposed expired inventory, the normal admission queue
was invoked once for pilot `82453304`. No dates/cooldowns/coverage markers were
edited. Receipt: `/var/lib/zeler-platform/repairs/current-inventory-29e88e5.json`.
Observe with `sudo python3 /tmp/current-inventory.py status`; **do not repeat
`enqueue`**. It reopened canonical job
`5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
At `2026-09-09T01:08:57.721800Z`, the job was running, attempt one, offset
40/1,900, zero unavailable IDs, with new observation
`2026-09-09T01:08:42.144000Z`. Both services remained healthy with zero restarts
and 5,906,173,952 free bytes. Do not deploy over this active recovery or treat
the receipt alone as current state; poll the same job. Completion and subsequent
catalog/buybox/formula acceptance remain pending.

No executable repository changes in this rollout unit. Worker includes the
current writer change; API includes the reader change. The source difference
between them is the worker persistence guard plus tests/docs. No additional
image rebuild is needed solely for this evidence update.

## Orders: missing line amounts must not overwrite acquired values

Review of the current orders contract reconfirmed that `gross_price` is a
line-total measure, not a replacement for the unit price consumed by existing
sales formulas. No new gross-price or billing surface was added. The separate
hosted-shipment migration and its previously observed pilot 404 remain open;
the order-detail endpoint itself is still documented.
[Mercado Libre orders](https://developers.mercadolibre.com.mx/gestiona-ventas).

Repository inspection exposed an independent integrity defect: `_order_items`
substituted quantity one or unit price zero when a detail omitted those fields.
Two TDD cases reproduced successful persistence of incomplete input. The writer
now requires those source values before canonicalization and raises a static
error if either is absent/null, before replacing the stored order. This preserves
the prior acquired document and prevents manufactured sales values. It does not
infer net unit price from gross totals or mix old and new line amounts.

The 78 persistence tests pass in 0.32s. The 17 real-Mongo order-recovery cases
pass in 3.81s, including both missing fields: prior documents remain unchanged,
the incomplete recovery fails and no reconciled coverage marker is published.
This does not claim per-field partial-order acquisition is complete: accepting
available portions of an incomplete new line without inventing its missing
amount remains separate work. Existing stored data stays consultable under its
normal coverage contract. Static checks pass (507 files). The initial full run
terminated with interpreter SIGSEGV/exit 139; it is not acceptance evidence.
After that process was confirmed terminal, a fresh full run completed normally:
4,132 passed, nine expected skips and 356 warnings in 133.86s. The eight protected
Mongo tests passed separately in 2.68s; the other skip is the optional Caddy check.

Rollback is the required-line-value guard and associated persistence/recovery
assertions; no Mongo schema, data deletion, new queue or compatibility layer is
introduced. This writer correction is not deployed. Include it in the next
verified Sheets worker image and validate missing-detail behavior, retained data
and truthful recovery state from the approved runtime context.

Separately, Cloud Build `9c28f597-36b2-4f75-87bf-87f71b812e2e` succeeded for
API source `c6b540b0b9d74030ca6e8823d5600fdd1ba4de6e`, producing
`sha256:155a13ab9a06a144cffa1ef243d0486e3c982f937c7ef9223ef91e4a8149d752`.
The local verifier passed exact source/repository/project and Artifact Registry
provenance. Files are `/tmp/zeler-catalog-rollout.tdDS4D/history-{build,artifact}.json`;
no production map update, pull or activation occurred. This image contains the
historical-percentage reader correction, not the later order writer change.
Do not rebuild it merely because it is waiting for rollout gates.

## CATALOGO no longer treats current snapshots as historical percentages

The historical percentage column no longer accepts `winning_time_percent`,
`winning_percent` or `catalog_win_percent` from a current buybox snapshot.
Repository search found no current producer for those snapshot fields; the
separate historical metric writer does not make them a verified source for
this matrix. Neither a missing snapshot nor one winning observation proves
optional absence, zero, 100% or any other percentage across an interval.

The column now returns `DATA_UNAVAILABLE`, with
`winning_time_unavailable_reason=catalog_history_not_reconciled` and an affected
item count in metadata. Inventory, current competition, prices and independently
covered sales remain available. History absence alone does not enqueue repeated
buybox recovery. Existing inventory/buybox/sales recovery still retains its
priority and reason; the history-specific reason remains alongside it. Empty
catalog inventories do not report missing historical rows.

This is a truthfulness correction, **not a completed historical implementation**:
the current matrix has no verified interval-history source for this column.
Connecting genuinely covered history, or establishing that the requested past
cannot be recovered, remains in the goal. Stored observation samples must not
be promoted to full-period coverage merely to return a number.

TDD reproduced seven failures (NA, unverified numeric aliases and missing
reason). The handler suite now passes 59 tests in 0.15s. Ten authenticated local
HTTP/real-Mongo cases pass in 4.15s, preserving the 24-column matrix, explained
historical unavailability, current buybox values and no redundant recovery on
repeat reads. Ruff check/format and mypy (507 files) pass. Full local replica-set
regression (`uv run pytest --tb=short`) passed 4,128 tests, nine expected skips
and 356 warnings in 134.22s. Eight protected Mongo tests passed separately in
3.41s; the remaining skip is the optional Caddy environment check.

Rollback is limited to this percentage-source rejection, its metadata and
associated assertions in the handler/recovery tests; no observations or source
records are removed. This unit is not deployed. Runtime last verified API/worker
source remains `99f933a`. Include this reader correction in the next verified
Sheets API image and confirm production response values/reason and repeat-read
queue behavior. Do not infer production acceptance from the local HTTP harness.

## Competition rollout: worker active and real notification persisted — 2026-09-09 UTC

Both Sheets services now run verified source `99f933a`: API digest `0944389...`
and worker digest
`sha256:ae3c245d2cb344e9beb86dd526fc3c66716557747bb73e903948c9de4a29b279`.
The worker's Artifact Registry/Cloud Build proof was verified into the canonical
VM map before service-only activation. Source CI remained green. Preflight
confirmed no running recovery jobs; the exact worker image binding was backed
up to `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-99f933a`.
`/tmp/zeler-competition-activate-worker.py` used `up --no-deps --pull never`;
health reached HTTP 200 with zero restarts. Final API and worker identity checks
both matched the source and remained healthy with zero restarts.

To retain the 5 GiB disk floor after the pull, exact unused API cache digest
`sha256:1702d8adc804f8b10a31eeb7b96e3e1d9964f94e5609643e74e8b6545036b391`
was checked against all containers and removed. Current and immediate rollback
images stayed present. The 543,309,824-byte recovery touched no volumes or
business data; Artifact Registry retains the removed image. Final free space
was 5,908,267,008 bytes.

Read-only management API inspection confirmed the real
`catalog_item_competition_status.*` bindings from both `meli.events` and
`zeler.sheets.replay` to `zeler.sheets.events`, one live consumer, and zero
ready/unacknowledged messages. Mongo had zero pilot observations but **223 real
stored competition notifications**; the latest receipt was
`2026-09-08T23:47:16.395000+00:00`.

The bounded runtime harness `/tmp/zeler-competition-replay-one.py` selected
that one real notification, preserving its original identity/resource through
the gateway's canonical classifier/envelope. `prepare` saved a VM-only 0600
receipt at `/var/lib/zeler-platform/repairs/catalog-notification-99f933a.json`.
Two intentional `publish` calls sent that same event only to the Sheets replay
exchange, never the shared product exchange. The normal worker persisted one
observation and its seller-scoped processing confirmation. Acquisition time was
after harness preparation, not the old notification time; source was
`meli_price_to_win`, basis `observed_only`. Subsequent `status` confirmed exactly
one row and identical BSON fingerprint after duplicate delivery. The queue was
again empty and the total pilot observation count was one. No fake notification,
manual token, rewritten coverage marker or unrelated product replay was used.

This proves real stored-event replay through broker/consumer/acquisition/Mongo
and unchanged observation on duplicate delivery. It does not prove a newly
arriving upstream notification, continuous history, runtime HTTP-call counts on
the duplicate, current formula completeness or all-52/Sheets acceptance. The
no-refetch branch has the focused code-test evidence recorded below; unchanged
Mongo alone is not an upstream-call measurement. Do not repeat `prepare` or
publish again merely to recreate this receipt.

Failure boundary after this activation: retain the new API, all observations
and durable queued messages. If consumer acceptance fails, stop only the new
Sheets worker and investigate/fix forward; do not start the previous generic
consumer on queued competition events, purge queues or run the unrelated broad
DEVOLUCIONES rollback. A backward-compatible consumer rollback is not proven.
No failure occurred and the worker was left running. No repository executable
code changed in this rollout unit, so no new regression run/build was needed.
Main's subsequent differences are documentation only; verified runtime source
is current for executable behavior. Remaining work includes historical-field
truthfulness, full current acquisition/formula acceptance and the goal ledger.

## Competition rollout: API active, worker still pending — 2026-09-09 UTC

The Sheets API now runs the verified `99f933a` image
`sha256:09443897564002c72055b98de3af66162468200791327e9a49b45d054e7e48b9`.
The canonical VM image-to-commit map was updated through provenance verification,
not manual relabeling. CI for that source passed lint and test. Only evidence
documentation differs between the image source and the subsequent main commit.

Before activation, isolated, read-only, network-disabled image probes imported
the real entrypoint and checked complete manifest fingerprints: prior API
`3ca3930...` has 11 scopes/5 topics; candidate `0944389...` has 11 scopes/6 topics.
This is a staged API-only rollout, not the DEVOLUCIONES timer/topology rollback
procedure. No worker, RabbitMQ binding, gateway or timer was changed. While that
boundary remains true, failed API acceptance can restore the prior running API
digest and its own five-topic registration via normal startup. Do not claim
that prior image satisfies the six-topic contract. After activating the new
consumer, re-evaluate rollback with queued competition events retained: starting
an old generic consumer against those messages is not a proven safe rollback.

Preflight found zero running recovery jobs and sufficient disk before pull.
The pull reduced free space slightly below 5 GiB; activation did not proceed
until exact unused worker cache digest
`sha256:443691ebbe7fc488a1a7fb34d57a0e98e0628249864a02b5948f82738c62bf03`
was removed after checking every container. All current/prior rollback images
were retained. This recovered 543,305,728 bytes; Artifact Registry can restore
the removed image. No volume or business data was removed. Before Compose,
capacity and zero running recovery jobs were checked again.

`/tmp/zeler-competition-activate-api.py` changed exactly one image binding,
saved `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-99f933a`,
and ran service-only `up --no-deps --pull never`. The API became healthy with
HTTP 200 and zero restarts. A subsequent check confirmed source/image identity,
worker source `449a382` unchanged and healthy, and 5,909,164,032 free bytes.

Approved-container read-only smoke (`/tmp/zeler-competition-api-smoke.py`):

| Formula | Rows | Columns | Unavailable cells | Seconds |
| --- | ---: | ---: | ---: | ---: |
| CATALOGOBUYBOX | 3 | 9 | 27 | 1.8239 |
| CATALOGO | 3 | 24 | 42 | 2.2329 |
| OBTENER_CATALOGO | 3 | 3 | 9 | 1.7359 |
| CATALOGO_COMPLETO | 3 | 6 | 18 | 1.9509 |

All four requested recovery metadata; none enqueued work or called Mercado
Libre. Exact live registry/manifest equality (11/6) and unchanged global markers
were verified. These operator backend reads do not prove data completeness,
authenticated HTTP, Google Sheets acceptance or p95. The first smoke harness
omitted the separate CATALOGO handler bundle; its immediate unavailable result
was a harness error, superseded by the corrected four-handler results above.

No executable repository changes or additional regression run were needed for
this deployment unit. Remaining runtime drift is the Sheets worker: activate
the already built `ae3c245...` image from `99f933a` after its gates, then verify
normal/replay bindings, pilot acquisition, persistence/replay and current formula
results. Do not rebuild the same source just because this evidence was committed.

## Competition rollout: schema ready, images verified — 2026-09-09 UTC

The additive `sheets_catalog_competition_observations` collection is now present
in production with the checked-in strict/error validator and the non-TTL
`idx_catalog_competition_seller_item_observed` index. An approved VM/API-container
check first confirmed the collection was absent; apply created it, and a separate
read-only check confirmed the exact schema/index with zero observations. No
existing data, registry documents, queues or service images were changed.
The guarded command was `sudo python3 /tmp/zeler-catalog-rollout-schema.py`
with `check`, then `apply`, then `check`. Local and VM script/schema/index hashes
matched before execution. Reversing a service release must retain this collection
and any subsequently acquired observations, not delete them.

Both connected-repository builds of
`99f933ae78a5c76a1064fb7ce2398fa5bb5b1c16` succeeded:

| Service | Cloud Build | Immutable digest |
| --- | --- | --- |
| Sheets API | `b6cceb52-6613-4d75-87a8-0805e46d8686` | `sha256:09443897564002c72055b98de3af66162468200791327e9a49b45d054e7e48b9` |
| Sheets worker | `d90f4734-86e1-40e1-a154-30bab7c993b2` | `sha256:ae3c245d2cb344e9beb86dd526fc3c66716557747bb73e903948c9de4a29b279` |

`infra.deploy.provenance_check verify-image` independently passed for both
Artifact Registry/SLSA records with the exact source, connected repository and
GCP project identity. Evidence is in local `/tmp/zeler-catalog-rollout.tdDS4D/`;
the production provenance map has not yet been updated. GitHub lint
`34294456170` and test `34294456190` both passed. No new executable repository
code changed in this evidence unit, so no additional local regression was run.

Activation remains pending: revalidate capacity and active jobs, resolve the
11-scope/5-topic to 11-scope/6-topic rollback boundary, and verify the image
runtime contract before service-only activation. Build provenance alone does
not prove registration compatibility. Do not relabel a previous image as
six-topic compatible. Then verify normal/replay bindings, actual acquisition
and formula reads. The last verified running sources remain API `1131554`
(digest `3ca3930...`) and worker `449a382` (digest `88a61a7...`), so current
`99f933a` behavior is not yet runtime acceptance. No additional build of the
same source is needed; deploy the already verified images once gates pass.

## Competition notifications have a persisted acquisition path — 2026-09-08

Sheets now handles `catalog_item_competition_status.updated` explicitly. It
validates the resource path, fetches current item ownership/stock and version-v2
competition through the Sheets gateway, checks publication/product identities,
and persists an `observed_only` state at acquisition time. Each upstream fetch
has a ten-second timeout. It does not invent a transition at notification time,
append new event types to customer spreadsheets or certify a historical period.

Notification observation identity binds seller, publication and event key. A
retry after persistence but before processing confirmation finds the observation
and makes no upstream calls. Concurrent delivery keeps the first persisted cut,
without replacing it with a later response. Consumer idempotency for this topic
is seller-scoped. The earlier snapshot-time recorder behavior remains unchanged.

The manifest, default routing and checked-in RabbitMQ definitions now include
the competition topic for both the regular and replay exchanges. No production
queue was changed in this unit. Four new Mongo consumer cases initially failed;
the focused persistence selection now passes five tests in 0.84s, including
post-persistence confirmation failure/retry, foreign seller, wrong product and
invalid resource path. Two binding assertions failed before routing was added;
the final runner/topology selection passed 26 tests in 0.28s. Ruff check/format,
mypy (507 files) and diff checks pass. The first root run identified four stale
registration expectations: manifest/startup/seed and the pinned full-registration
fingerprint. The seed and deployment verifier now match the canonical manifest:
11 unchanged upstream scopes, six routing keys including passive claims. The
focused registration/topology/deployment suite passed 122 tests in 3.05s after
the correction. A fresh full local replica-set regression (`uv run pytest
--tb=short`) passed 4,122 tests, nine expected skips and 356 warnings in 134.96s.
Eight protected Mongo tests passed separately in 3.17s; the other skip is the
optional Caddy environment check. Schema drift checks also pass.

Before runtime activation, apply the observation schema/index from the approved
context and deploy the verified Sheets worker with this handler. Verify normal
and replay bindings, seller isolation, legitimate live observation persistence
and duplicate replay without upstream refetch; initial schema/current-source
rollout and API acceptance remain pending. This unit did not build or deploy,
and did not recheck runtime drift. Pending API code also needs a verified image.
Revalidate rollback compatibility against the new registration fingerprint;
do not relabel old provenance records as satisfying the six-routing-key contract.

Rollback removes the competition branch, notification-key recorder option and
the new topic's two bindings/default/manifest entries, retaining persisted
observations and the preceding normal-recovery recorder. Sparse observations
still do not prove uninterrupted historical coverage or a winning-time ratio.

## Buybox recovery retains native competition observations — 2026-09-08

Verified owned-publication recovery now appends the acquired status, stock,
product identity and observation time to
`sheets_catalog_competition_observations` before updating the replaceable buybox
snapshot. It uses the existing ownership/source and lease checks; foreign,
non-participating, stale or changed items do not produce observations. These
records are explicitly `observed_only`, not continuous interval proof or imported
legacy history. No global freshness marker is advanced and no percentage is
fabricated. Unknown upstream states remain source observations, not assumed wins.

The recorder persists only purpose fields, not raw payloads. Its identity binds
seller, publication and millisecond-normalized acquisition time. Identical retries
are no-ops, later observations preserve earlier cuts, and a conflicting payload
at the same cut raises rather than rewriting history. A dedicated strict schema
and seller/item/time index keep these records separate from legacy import inputs;
there is no TTL. The generated schema is checked in but not applied to production.

The initial owned-worker assertion failed before implementation. Focused real
Mongo verification (`test_formula_recovery.py -k 'buybox or catalog_observations'`):
37 passed in 10.37s. It covers persistence from normal recovery, exclusion of
invalid ownership/source states, replay, chronology, conflict preservation, raw
field omission and validator rejection of `legacy_imported` coverage. Ruff
check/format, mypy (507 files), schema and diff checks pass. The root run passed
4,117 tests with nine expected skips and 356 warnings in 135.36s, with one failure:
the explicit schema inventory omitted the new collection. Both expected and
active-schema sets now include it; the failing test passed separately in 0.01s.
No executable change followed the root run and it was not repeated after that
test-inventory correction. Eight protected Mongo tests passed separately in 2.87s.

Next wire actual competition notifications to this recorder through a validated
persistence branch before subscribing the queue. Capture an observation at fetch
time, not a retroactive state at notification time; replay and outage handling
must not turn sparse observations into complete coverage. CATALOGO's missing
historical percentage and forward coverage/readback acceptance remain open.

No production writes, builds or deployments occurred. Apply the additive
collection validator/index from the approved runtime before activating a verified
Sheets worker image, then verify observation persistence/replay without changing
historical markers. Pending API changes also require a verified API image.
Rollback removes the recorder call/module and matching schema/index/tests;
retain any legitimately persisted observations. Runtime drift was not rechecked.

## Production has no catalog-time history to join — 2026-09-08

A narrowly scoped approved-runtime Mongo probe found 1,918 pilot `items`, but
zero seller-scoped `item_history_projection`, `meli_item_events`,
`sheets_catalog_time_metrics`, documents with `catalog_history`, or
`event_type=catalog_change` records. No catalog-time freshness marker exists.
The API image/health guard passed. This is actual absence in these queried
platform sources, not proof that every possible Mercado Libre history API is
unavailable. Do not fabricate a 30-day winning percentage or call it optional NA.

Artifact: local `/tmp/zeler-catalog-history.Hoomtr/probe.py`; VM read-only command
`sudo python3 /tmp/zeler-catalog-history-probe.py`. The result contains counts and
booleans only; no business data was changed and no credentials/identifiers were
printed. Prior executable regression remains 4,117 passing tests; no executable
repository change or new test run belongs to this evidence-only unit.

Code inspection explains the missing forward path: the gateway classifier maps
`catalog_item_competition_status`, but Sheets' `manifest.yaml` and default
consumer routing only subscribe to items/orders/shipments/questions. Its
`SheetsEventPersistence.persist` also has no competition branch. The existing
catalog metric writer consumes legacy history/imported change events and labels
its result `legacy_imported`; it is not an active native acquisition pipeline.
Its `_covered_segments` carries a prior state through the requested end, which
cannot prove uninterrupted coverage for a new stream merely from one observation.

Next implementation must wire real competition notifications to owned,
idempotent, timestamped persistence and distinguish observed history from proven
interval coverage. Keep the available formula columns usable; unknown historical
percentage must be explained and must not cause repeated snapshot recovery that
cannot recreate past transitions. Do not populate historical states from today's
status, import an old database, or activate a queue without a persistence handler.

No builds/deployments or business writes occurred. Runtime API still matches
the recorded `1131554` image; worker was not rechecked. Pending executable work
through `13296a8` still requires verified Sheets API/worker images and scoped
production recovery/readback. This documentation unit needs no image rebuild;
rollback is removal of this evidence entry, not deletion of any persisted data.

## Buybox resolves the winner publication to its seller — 2026-09-08

The recovery worker now persists `winning_user_id`: an owned winning publication
uses its verified seller; another winner is resolved from the validated offer
page or a bounded Sheets-detail `/items/{winner_item_id}` fallback. The fallback
must match the winner publication and catalog product and provide a numeric
seller identity. Explicit `winner: null` persists null; an unacquired winner
identity remains absent. CATALOGO distinguishes that absence as DATA_UNAVAILABLE
and requests recovery, rather than treating an unknown winner as optional NA.
Existing payload/timestamp preservation on secondary acquisition failures remains.

The [official competition contract](https://developers.mercadolibre.com.mx/es_ar/competencia-en-catalogo)
describes `winner.item_id`. A read-only approved-runtime probe of three current
pilot publications returned that field without `seller_id` in all three cases.
Each winner was the queried publication, matched one product-offer row with a
numeric seller, and its detail endpoint returned HTTP 200 with matching item,
product and seller. This proves three owned-winner source paths, not live external
winner coverage. No business data or credentials were printed/written. Artifact:
local `/tmp/zeler-winner-source.EanPDo/probe.py`; VM
`sudo python3 /tmp/zeler-winner-source-probe.py`. Its API image/health guard passed.

Next source lead: the legacy catalog percentage helper in
`sheetsellerapi/src/colecciones/router_publicaciones.py` around line 4390 uses a
30-day calendar window and `catalog_history`; it is not an instantaneous winner
flag. The platform already has source-gated catalog history/metric writers in
`source_gated_read_model_writers.py`. Inspect their actual coverage before joining
that percentage; do not infer a historical ratio from today's winner or copy the
legacy single-event whole-window assumption without evidence.

Five acquisition assertions and one missing-value assertion failed before their
respective changes. Final focused Mongo buybox tests: 36 passed in 7.47s,
including own/external/on-page/fallback winner, wrong product and explicit null.
Handler suite: 53 passed in 0.15s. Ruff check/format, mypy (506 files), schema
and diff checks pass. Full local replica-set regression (`uv run pytest --tb=short`):
4,117 passed, nine expected skips and 356 warnings in 124.55s. The eight protected
Mongo tests passed separately in 2.59s; the other skip is Caddy's optional
environment check. External-winner runtime acceptance
and the historical winning-time percentage remain required, not inferred here.

No images were built/deployed. The runtime API still matched the recorded
`1131554` image; worker drift was not rechecked. Verified Sheets API/worker images
must include these local changes before production recovery/readback acceptance.
Rollback removes winner resolution and the corresponding CATALOGO absent-value
handling/tests, preserving stored data and prior offer-count acquisition.

## Catalog sales validate each interval without hiding item columns — 2026-09-08

CATALOGO no longer gates its whole matrix on a productive orders marker. Each
sales window requires reconciled coverage from its calendar-day start through
the reported `sales_as_of`. An acquired endpoint less than 15 minutes old can
be reused at that explicit cut; an older endpoint cannot certify current sales.
Covered windows with no sales return zero. Uncovered windows return
DATA_UNAVAILABLE and are listed in `unavailable_sales_windows`; available item
and competition columns remain visible. Historical calendar-day inclusion is
preserved, and queries no longer include orders after the reported cut.

After inventory/competition recovery, the first uncovered sales window requests
orders acquisition. Admission is at most 90 days, including for a missing
365-day window. The existing worker reacquires the union with prior reconciled
coverage, including gaps; this is not a claim that 365-day production acquisition
has succeeded or that its cost is bounded by the admission interval.

Three new behavioral tests failed before implementation. The final handler suite
passed 50 tests in 0.16s, including absent/partial/complete coverage, zero sales,
recent versus expired cuts, and bounded recovery requests. The local HTTP/Mongo
buybox/catalog harness passed ten tests in 4.03s. Its orders fixture now supplies
reconciled range evidence, not just a globally fresh flag. Ruff check/format and
mypy (506 files), schema and diff checks pass. Full regression with local
replica-set Mongo: `uv run pytest --tb=short` passed 4,110 tests, nine expected
skips and 356 warnings in 146.75s. The eight protected Mongo tests passed
separately in 3.29s; the remaining skip is the optional Caddy environment check.

No build or deployment occurred. Required next evidence includes live orders
coverage extension and source-complete winner/time fields before full CATALOGO
acceptance. Sheets API/worker images remain behind these local changes according
to the last recorded runtime sources (`1131554`/`449a382`); verify provenance and
recovery/readback when deploying. Rollback removes the catalog-specific coverage
reader, per-window rendering/recovery and their tests, retaining persisted data.

## CATALOGO joins verified inventory to current owned competition — 2026-09-08

CATALOGO now selects explicit catalog participants from the source-verified
inventory/buybox reader instead of accepting all product links and stored buybox
rows behind global markers. Its item matrix and competition checks share the
same inventory observation; the reader rechecks canonical source fingerprints.
Expired inventory or missing item sources request inventory recovery first.
Otherwise missing snapshots, unknown shared counts or unknown sole-competitor
values request the explicit buybox IDs. Available item columns remain visible
when competition is missing, and inventory gaps add a 24-column unavailable row.
Sole competitor accepts a source boolean, never legacy strings or optional NA.

Four new handler cases failed before implementation. Final handler suite:
44 passed in 0.14s. The real local HTTP/Mongo harness now runs both CATALOGO and
CATALOGOBUYBOX: ten cases passed in 4.70s, proving admission, worker persistence,
two subsequent Mongo-only reads, and rejection of changed association,
expired/future/foreign snapshots or partial sole-competitor fields. This is local
acceptance with controlled gateway responses, not authenticated production smoke.
Full regression (`uv run pytest --tb=short` with local replica-set Mongo):
4,104 passed, nine expected skips and 356 warnings in 132.83s. Eight protected
Mongo tests passed separately in 2.40s; the remaining skip is Caddy's optional
environment check. Ruff check/format, mypy (506 files), schema and diff checks pass.

Remaining CATALOGO gaps are explicit: the orders gate still checks a global
productive marker rather than each sales window's coverage and may block the
whole result; required winner/time fields still need purpose-complete acquisition
and absence handling. This change does not certify the entire matrix as complete.
No builds or deploys occurred. Verified Sheets API/worker images and live
recovery/readback are still required before runtime acceptance; last recorded
runtime is API `1131554`, worker `449a382`, not verified anew in this unit.
Rollback removes this handler selection/recovery change and the optional shared
inventory argument in the reader with their tests; it must retain acquired data.

## Buybox acquires sole-publication evidence from product offers — 2026-09-08

The worker now fetches `/products/{product}/items` with the Sheets detail client
after the version-v2 competition response. It persists the validated paging total,
not the number of rows on a potentially paginated page. Sole competitor is true
only for a total of one whose publication and seller match the requested item.
This counts competing publications, not distinct sellers. Empty or other-only
listings produce false; malformed paging, duplicate identities and conflicting
ownership cannot establish the field. Values supplied by the competition payload
are not trusted as substitutes for this acquisition.

If offers fail, an existing snapshot and its timestamp remain untouched. With no
snapshot, acquired competition fields persist while count/sole remain unknown.
Retryable upstream failures keep the job pending; malformed source data fails it.
No global marker, schema change or new synchronous formula API call is added.

Verification: the initial eight acquisition tests were red before implementation.
The recovery suite passed 342 tests in 63.05s; after adding three malformed-source
cases, the focused buybox selection passed 27 tests in 4.93s. Its real local
HTTP/Mongo harness now provides separate offer responses and proves repeated
formula reads cause no additional upstream calls. Ruff check/format and mypy
(506 files), schema drift and diff checks pass. Full regression:
`uv run pytest --tb=short` with local replica-set Mongo passed 4,095 tests,
nine expected skips and 356 warnings in 131.07s. The eight protected Mongo tests
ran separately with `ZELER_RS0_TEST_URI` and passed in 2.40s; the other skip is
the environment-dependent Caddy check.

No build or deployment occurred. Live evidence remains the preceding read-only
single-offer probe, not live acceptance of this worker. Before deploying verified
Sheets API/worker images, finish the other CATALOGO consumer's source-bound
selection and recovery. Rollback removes the offer parser/fetch/persistence branch
and its tests from `recovery_worker.py` and `test_formula_recovery.py`, preserving
prior acquisition behavior and stored data. The full goal remains open.

## CATALOGOBUYBOX reads current owned membership and requests missing IDs — 2026-09-08

CATALOGOBUYBOX no longer reads all stored snapshots behind a global freshness
marker. It derives membership from current source-verified item inventory,
includes only explicit catalog participants, and rejects mismatched association,
title/stock, source identity, future/expired snapshots and snapshots older than
the canonical item observation. Inventory/source gaps request item recovery first;
otherwise missing or incomplete competition rows request explicit buybox IDs.
Valid rows remain visible alongside unavailable rows, preserving nine columns.
Unknown sole-competitor values are DATA_UNAVAILABLE, not a complete optional NA;
partial rows keep their other values and metadata explains incomplete coverage.

The first real local HTTP-to-Mongo test failed because buybox still required the
global marker. Five final cases now prove HTTP admission, worker persistence,
two reads without more upstream calls, then rejection of changed associations,
expired/future snapshots, another seller's snapshot, and partial purpose fields.
They passed in 2.21s. Existing fake-handler tests were updated to seed verified
inventory rather than certify arbitrary stored rows; all 43 passed in 0.33s.
Protected Mongo tests: eight passed in 2.46s. Ruff check/format, mypy (506 files),
schema drift and diff checks pass. Full regression passed 4,084 tests, nine
expected skips and 356 warnings in 130.37s; eight protected skips ran separately.

Before deployment, complete actual sole-competitor acquisition: the HTTP fixture
supplies that field, whereas the live competition response does not establish it.
The [official product-offer listing](https://developers.mercadolibre.com.mx/es_ar/envio/competencia-en-catalogo)
provides paging totals and item identities. One read-only approved-runtime probe
using Sheets credentials returned HTTP 200, total=1, offset=0, limit=100, one row,
and the owned publication itself. Artifact: `/tmp/zeler-buybox-shared.8pPRC4/competition.py`.
This validates access/one response shape, not all paging/absence cases, and wrote
no business data or printed identifiers. Next acquire this purpose field safely,
then extend source-bound recovery to the other CATALOGO consumer as required.

No images were built/deployed. Runtime remains API `1131554`, worker `449a382`;
these local changes and the preceding acquisition unit require verified API and
worker images before live acceptance. Rollback removes the new repository read,
buybox handler selection/recovery changes and associated fixtures/tests, retaining
stored data. The full 52-formula and real-user-surface goal remains open.

## Bounded owned-publication buybox acquisition implemented locally — 2026-09-08

The recovery worker now supports explicit buybox publication IDs through the
existing `ItemIdsRecoveryRequest` and API admission helper. Item-row and buybox
requests retain different deterministic keys because their read models differ.
Buybox date-range requests are rejected; no unbounded seller-wide source request
or new collection is introduced. Jobs retain the existing 20-ID limit and share
the catalog worker's four-at-a-time joined acquisition/error handling.

Before fetching, all selected publications must belong to the seller, explicitly
participate in catalog and have an acquired item observation within 15 minutes.
Each buybox fetch uses the Sheets detail identity and the existing version-v2
competition endpoint. Publication/product response identities, source title/stock,
status and presence of a valid shared-first-place field are required. The worker
rechecks the stored item document after fetching and checks its lease before
persisting; changed source data is rejected. Conditional snapshot writes preserve
newer observations. Snapshot time is acquisition start, and successful buybox
renewal eligibility now uses that time, not completion plus another 15 minutes.
No global freshness marker is advanced.

Seven new Mongo cases initially failed because buybox item requests were rejected.
They now cover valid persistence, foreign ownership, non-participation, stale item
data, source change during fetching, wrong response identity and newer-snapshot
preservation. Valid persistence uses the generated buybox Mongo validator and
preserves zero stock/shared count and the actual winner price. A real Request /
formula context test exercises the normal API helper and confirms explicit-ID
admission plus date-range rejection. A separate added cooldown case failed before
the eligibility correction. Existing catalog tests cover the shared bounded-wave
runner and cancellation/error behavior; these are not live buybox measurements.

Verification: initial seven red cases 1.31s; selected acquisition/catalog cases
14 passed in 3.12s; recovery suite 327 passed in 56.03s before the final API and
cooldown additions; final buybox/cooldown selection 13 passed in 2.70s. Full root
regression collected before the final cooldown parameterization passed 4,078
tests, nine expected skips and 356 warnings in 143.81s. The final cooldown change
was verified by the focused selection afterward. Protected Mongo tests passed
eight cases in 2.37s. Ruff check/format, mypy (506 files), schema drift and diff
checks pass; a test-context typing error was fixed using the actual Request and
FormulaExecutionContext types.

This is acquisition plumbing, **not finished automatic formula recovery**. The
current buybox formula still depends on the global marker and does not select
owned missing IDs from current inventory. Next add source-bound membership,
freshness/purpose-field reads and explicit recovery intents in its real consumers;
then verify the full local HTTP-to-worker-to-Mongo-to-second-read path. In
particular, a source change after the worker's last check still needs rejection
by the consumer; this unit is not an atomic cross-collection source certificate.
Other unacquired buybox purpose fields and genuine source absence remain open.

No build/deploy or production data mutation occurred. Runtime remains API
`1131554` and worker `449a382`. Include this unit with the consumer changes in
verified API/worker images before live acceptance, rather than deploying an
incomplete reader/worker contract. Rollback removes the buybox request/model
support, worker method and shared-runner extraction plus associated tests; it
requires no schema/data deletion and must retain any later legitimate snapshots.

## Buybox source-count API deployed; acquisition gap measured — 2026-09-08

Sheets API now runs source `1131554b2ceffb5d9d787c92e587966bdc09d6c9`, digest
`3ca3930db3b311bbe6b4d5ef2ee2c08ba53b412ca07c5aa1b3281d0d1222c41f`.
Build `e3a956fd-5b89-48b1-85bb-37c87023fafc` and CI test `34288359293` / lint
`34288359306` succeeded before activation; provenance was already verified
locally and in the VM canonical map. Only the API was replaced, with no running
recovery jobs and `--no-deps --pull never`. HTTP health is **200**, zero restarts.
Worker remains `449a382`, digest `88a61a75...`; the shared-value helper change
does not require a worker rebuild.

The exact unused local API cache digest `542a5406...` was removed only after
all-container and Artifact Registry recoverability checks. Active/rollback
images remained present, with no volumes or data removed. Preflight passed
with automatic cleanup disabled; pull took 11.48s and left Compose unchanged.
Post-activation free space was 5,915,353,088 bytes; recheck before future pulls.
API rollback is prior running digest
`37b750d889046d8ee4fa9f5996afa7f0fdd36c85b9348b77f86628c3720f5c7e`, with backup
`/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-1131554`.
Artifacts: `/tmp/zeler-buybox-shared.8pPRC4/` locally and on the VM. Pull,
activation and cleanup scripts have succeeded and must not be repeated.

A read-only approved-runtime probe then measured the remaining buybox gap:

- 939 stored publications explicitly have `catalog_listing=true`.
- 473 buybox snapshots exist in total; 330 match those participating item IDs.
- None of those 330 snapshots is within the 15-minute freshness window, and
  all 330 lack the source `competitors_sharing_first_place` field.
- 609 participating item IDs have no stored buybox snapshot.
- `catalog_buybox_snapshots` is not in the worker's implemented recovery models.
- The real Mongo-backed CATALOGOBUYBOX handler returns DATA_UNAVAILABLE for
  that read model (0.0016s), rather than a fabricated current result.

Probe: `sudo python3 /tmp/zeler-buybox-shared.8pPRC4/buybox.py` on the VM.
It prints counts/booleans only and makes no upstream requests or business-data
writes. Participation counts describe stored explicit source flags, not a newly
enumerated current source audit. This confirms acquisition/membership/freshness
work remains; successful deployment does not prove buybox data acceptance.
Next implement bounded owned-item buybox recovery and source-bound consumer
coverage without forcing global freshness markers or masking missing fields.

No new executable repository code was changed in this deployment unit; the
preceding 4,070-test regression and successful CI support the deployed source.
This documentation-only delta does not require another image. The full goal,
authenticated HTTP/Sheet checks and remaining product requirements stay open.

## Current catalog converged with two explained not-found products — 2026-09-08

Both catalog handlers returned **883 available products plus two explained
not-found rows**, covering all 885 product associations from the current
1,900-publication inventory. No item sources were missing, no further recovery
was requested and no product jobs remained pending/running. This is a bounded
live backend result, not perpetual freshness or authenticated HTTP/Sheet acceptance.

The existing inventory finished 1,900/1,900 with zero exhausted IDs; temporary
source failures resumed through normal retries without a new sweep. At the first
terminal watcher probe, enumeration age was 509.42s and time since completion
21.39s, placing completion near 488.03s. Watch session **89549 is terminal,
exit zero**; do not restart it or repeat inventory preparation.

The watcher initially requested 884 recoverable products, excluding the previously
observed 404. Normal subsequent admissions observed 400/404 available products
and then 800/804 in sequential reads; the final 84-product request was fully
admitted. Earlier false admission results represented partial enqueues. A second
upstream not-found product was persisted during this recovery. The two historical
source-rejected jobs remain as history; they are not current missing coverage.
Job history contains 1,205 product slots, not 1,205 unique current products.

Two read-only verification passes agreed on membership, values' availability,
and reasons. The second pass reported:

| Formula | Rows | Available products | Unavailable products | Read time |
| --- | ---: | ---: | ---: | ---: |
| OBTENER_CATALOGO | 885 | 883 | 2 | 3.1084s |
| CATALOGO_COMPLETO | 885 | 883 | 2 | 2.6964s |

Both had `inventory_enumeration_current=true`, `recovery_needed=false`, and
exactly two `catalog_product_not_found` reasons. Their three-/six-column outputs
contained six/twelve DATA_UNAVAILABLE cells respectively, entirely those two
rows; cached-products count was zero. `catalog_products_complete` intentionally
remains false: not-found rows must not be presented as complete available data.
This establishes current source unavailability, not permanent impossibility.
The second pass also hashed snapshots internally before/after the reads and
confirmed they were unchanged; global freshness markers were unchanged too.
Following inventory status showed enumeration age 713.94s, still within 900s.
These are individual timings, not a measured p95 or Google Sheets execution time.

Evidence: approved VM `/tmp/zeler-catalog-unavailable.I9e2ZV/products.py read`
and `inventory.py status`, with original receipts retained. Product reads invoke
the real Mongo-backed dispatcher without an upstream client; admissions use the
normal API helper and queue. No data was fabricated, retimed or deleted. Runtime
still uses API/worker `449a382`, and no deployment occurred during this check.
The next availability cycle, buybox recovery and all-52/user-surface gates remain
open; do not trigger another full inventory solely to recreate this receipt.

The pending buybox API image build `e3a956fd-5b89-48b1-85bb-37c87023fafc`
succeeded from `1131554b2ceffb5d9d787c92e587966bdc09d6c9`, producing digest
`3ca3930db3b311bbe6b4d5ef2ee2c08ba53b412ca07c5aa1b3281d0d1222c41f`.
Provenance passed locally and in the canonical VM map; artifacts are
`/tmp/zeler-buybox-shared.8pPRC4/`. It has not been pulled or activated. Last CI
observation: lint `34288359306` succeeded; test `34288359293` was still running.
Recheck that same run before deployment; do not rebuild. Rollback remains the
existing service-image boundaries and must preserve recovered snapshots.

## Buybox shared-first-place values no longer use competitor totals — 2026-09-08

CATALOGOBUYBOX now reads `competitors_sharing_first_place` for its existing
`# DE GANADORES` column, using the same source-value helper as CATALOGO. It no
longer substitutes `competitor_count` or the unverified legacy `winner_count`.
Zero remains zero, an explicitly acquired null becomes NA, and missing/invalid
source counts become DATA_UNAVAILABLE with a reason in buybox response metadata.
The nine-column contract and header remain unchanged. The helper preserves the
source count; it does not infer a global winner total or add one to shared counts.

The [official competition contract](https://developers.mercadolibre.com.mx/en_us/introduction-services/catalog-competition)
distinguishes shared first place from total competition and specifies zero for
winning and null for competing/listed. The legacy product handler also selected
this source field, but incorrectly merged null and zero into a unique-winner
message; that inference was not restored. The common helper was moved from the
CATALOGO handler into `catalog_values.py` for these two proven consumers. Removed
the now-unreferenced `_first_present` compatibility helper after repository search.

Four focused cases first failed in 0.09s: source zero, positive, null and an
absent source field with both legacy totals present. After correction the two
handler suites passed 83 tests in 0.25s, including unchanged CATALOGO behavior;
the missing-count case checks the explicit unavailable reason. Protected Mongo
tests passed eight cases in 2.45s. Ruff check/format, mypy (506 files), generated
schema drift and diff checks pass. Full regression passed 4,070 tests with nine
expected skips and 356 warnings in 125.30s. The eight protected skips were run
separately; the remaining skip concerns Caddy keys. The unused helper removal
was also followed by the focused 83-test run and static checks.

This is a local handler correction, not live formula acceptance. Runtime still
uses `449a382`; only a new Sheets API image is required for the visible behavior.
Do not deploy during the active inventory/product observer, whose image guards
remain pinned to that source. Before runtime acceptance, build the committed
source, verify provenance/CI and check actual buybox persistence and formula output.
Buybox membership, freshness and automatic acquisition remain open; this change
does not claim that missing buybox data is irrecoverable. Rollback restores the
two handlers and their helper/test change, without schema or data rollback.

## Real not-found observation persisted; fresh inventory in progress — 2026-09-08

The deployed worker persisted `catalog_product_not_found` for the one still
missing owned product identified from the prior source-rejected batches. The
read-only precheck found no snapshot and no existing single-product job. One
normal queue admission then completed on attempt one; the follow-up read found
the snapshot, `source=sheets_backfill`, and the not-found observation aged
23.079s. Title, description, image and attributes were absent, not fabricated.
This proves a real upstream not-found observation persisted by the normal
worker, not permanent source impossibility or whole-catalog acceptance.

Job: `b4ee182b03ff37ec30230ca380bfaf9af7bbd7e49b3ae0a83d609c417de932ff`.
Receipt: `/var/lib/zeler-platform/repairs/catalog-not-found-449a382.json`.
Guarded artifact: `/tmp/zeler-catalog-unavailable.I9e2ZV/not-found.py` (VM and
local). `prepare` has executed; do not repeat it. Its status selection is tied
to the prior rejected batches and expects exactly one product without a stored
title; if that source later recovers, re-resolve the scope instead of overriding
the guard. This operator check is not authenticated production formula HTTP.

After confirming no active recovery jobs, admitted one current inventory
recovery for the newly deployed code. No cooldowns or timestamps were overridden.
The retained old enumeration in the immediate pending response was not new
coverage. The next fresh checkpoint reported **120/1,900**, zero unavailable
IDs, enumeration age 23.77s and running state. This run is not complete.

Observe the existing job
`5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`;
receipt `/var/lib/zeler-platform/repairs/catalog-inventory-449a382.json`.
Artifacts are `/tmp/zeler-catalog-unavailable.I9e2ZV/{inventory,products,watch-products}.py`.
The watcher is live in exec session **89549** and has its own exclusive receipt
`catalog-product-admission-449a382.json`. Poll that handle; never restart from a
stale progress report. It will make one normal product admission only after a
complete still-current inventory. Subsequent catalog coverage and source-reason
consumer verification remain required. No further build/deploy or executable
repository changes occurred; rollback remains the preceding rollout boundary,
not deletion of legitimately acquired observations.

## Catalog unavailable-source rollout verified — 2026-09-08

Sheets API and worker now both run source
`449a3826db7ec40804c3bd7954cc246a56263f5d`, including bounded catalog acquisition
and per-product not-found persistence. Both report HTTP health **200** and zero
restarts. CI test `34286628759` and lint `34286628787` completed successfully
before activation. Separate Cloud Builds succeeded; digest/build/source bindings
were verified locally and sequentially into the VM canonical provenance map.

| Service | Cloud Build | Deployed digest |
| --- | --- | --- |
| sheets-worker | `5364808d-1a6a-4ecc-840c-74146f3c017f` | `88a61a753deebdc887291ef3314087d3740212f5c3d8ffa1ddc3dd36c71f80fa` |
| sheets-api | `e65cc95e-9247-41b1-907c-383e744c8c35` | `37b750d889046d8ee4fa9f5996afa7f0fdd36c85b9348b77f86628c3720f5c7e` |

Before activation, the approved runtime-container check proved the production
product-snapshot validator differed only by the new `source_unavailable`
property. Applied that additive property alone and read back exact equality with
the generated schema; strict/error validation remained enabled. No business
documents were modified by this schema operation. Retain this optional property
on rollback so new observations stay valid.

Both pulls passed capacity/preflight with automatic cleanup disabled and left
Compose unchanged; worker pull took 12.92s and API pull 11.21s. Each activation
required no running recovery jobs, replaced exactly its own image binding and
used `--no-deps --pull never`. To preserve the 5 GiB floor, removed only unused
local cache images worker `5d27006e...` and API `2c2c8bf2...`, after exact registry
recoverability and all-container checks. No volumes/data were removed. Current
and immediate rollback images stayed present. Final free space was
5,880,037,376 bytes; recheck before any subsequent pull/Compose activity.

Rollback authorities are the previous running worker digest
`c3ad9eeba1e364ee2268fc3cbce9e811c79a997300029a8d51be862b38f7b647`
and API digest
`1702d8adc804f8b10a31eeb7b96e3e1d9964f94e5609643e74e8b6545036b391`.
Compose backups end in `.pre-sheets-worker-activate-449a382` and
`.pre-sheets-api-activate-449a382`. Artifacts and guarded scripts are in
`/tmp/zeler-catalog-unavailable.I9e2ZV/` locally and on the VM. Pull, activation
and cache-removal scripts have executed successfully; do not repeat them.

The post-deploy read-only progress probe found 44 completed and two failed
catalog-product jobs, no pending jobs, and 806 snapshots acquired since the last
inventory enumeration. The inventory remains completed 1,900/1,900 with zero
unavailable IDs, but enumeration age was 3,031.36s: this is expired evidence,
not current catalog coverage. No inventory was restarted in this rollout unit.
Next verify actual not-found persistence and fresh whole-catalog convergence
through normal recovery; neither is proved by health checks or existing snapshots.
Authenticated all-52 HTTP, real Sheet/app, and the remaining goal gates stay open.

This unit only deploys the already-tested implementation and records evidence;
no new executable repository change or regression run was needed. A subsequent
documentation-only commit does not require another service image.

## Persist per-product not-found observations and cached fallback — 2026-09-08

Catalog recovery now persists an HTTP 404 as optional `source_unavailable`
metadata on that product snapshot: reason `catalog_product_not_found` and the
actual request-start `observed_at`. It does not erase an earlier payload or
advance its `snapshot_at`; a never-acquired product gets identity/source metadata
only, not invented title/description values. Both positive and not-found writes
are guarded against newer positive or negative observations. A later successful
response replaces the payload and clears the unavailable marker. Other 4xx,
429 and 5xx retain their prior rejection/retry behavior.

The two current catalog formulas consume this observation without synchronous
Mercado Libre calls. A current 404 with no purpose-complete stored payload emits
DATA_UNAVAILABLE and a per-product reason. If a trusted older payload exists,
it is returned as cached, with its original UTC observation date in metadata;
`catalog_products_complete` stays false. Neither case requeues the known 404
while its observation remains current. Expired/future-dated observations cannot
suppress recovery or make an old cached payload current. Inventory and item-source
coverage checks remain unchanged, as do the three-/six-column contracts.

Four HTTP cases failed before the change, then both formulas passed available,
missing and cached scenarios against Mongo with the actual product validator.
They prove two subsequent reads make no upstream calls, preserve cached fields
and their original date, explain the 404 and resume recovery after expiry or an
invalid future date. Eight additional cases cover newer positive/negative writes,
clearing the marker on recovery and separate 403/429/503 handling. These 14 cases
passed in 4.52 seconds; recovery/formula suites passed 361 tests in 47.08 seconds,
and eight protected replica-set tests passed in 3.20 seconds. Ruff check/format,
mypy (505 files), schema generation and diff checks passed.
Root regression passed 4,068 tests with nine expected skips and 356 warnings
in 127.36 seconds.

Before runtime validation, apply only the additive product-snapshot validator
property from the generated schema, then build and verify separate Sheets API
and worker images from the committed source (also including `02ccbaf` concurrency).
Current production still uses worker `0db69e5` and API `c90a941`; this behavior is
not yet deployed. Rollback reverts the worker/reader/handler change and its tests,
retaining the optional validator property so newly written observations remain
valid. No stored payload needs deletion. Real pilot convergence, authenticated
production HTTP, visible Sheet/app behavior and the remaining goal gates are
still unproven; local HTTP tests do not close those gates.

## Bounded concurrent catalog acquisition and rejected-resource diagnosis — 2026-09-08

Catalog-product recovery now acquires at most four products concurrently, in
joined waves within the existing 20-product job. It retains seller-association
checks, per-resource timeout, lease checks, source timestamps and the conditional
write that preserves newer observations. A task group drains started operations
before the next wave or job completion; typed storage/implementation failures
are re-raised after joining siblings instead of being hidden in an exception
group. Existing source-error retry classification is unchanged. This changes
neither queue capacity, freshness, API admission nor the seller rollout scope.

Three event-gated real-Mongo tests failed on the sequential implementation, then
passed with the bounded waves. They prove four concurrent requests without
exceeding four, all 20 successful products persisted, cancellation of blocked
fetches joined with no writes, and a storage error classified as retryable only
after the three successful siblings persisted. The lease-loss test now gates
responses on actual lease revocation rather than relying on sequential order;
it still proves no snapshot is written after that simulated revocation.
Focused worker/HTTP cases passed 12 tests in 3.34 seconds; the complete recovery
suite passed 308 tests in 55.25 seconds. The eight protected replica-set tests
passed separately in 2.10 seconds. Ruff check/format, mypy (505 files) and diff
checks passed. Root regression passed 4,056 tests with nine expected skips and
356 warnings in 122.69 seconds.

A read-only approved-VM probe separately resolved the two `source_rejected` jobs:
they contain 33 unique product IDs, 32 already acquired since the enumeration.
Only one product remained missing; its current `/products/{id}` request through
the legitimate Sheets client returned HTTP 404. Ownership association was checked
before fetching and no business data was written. Artifact:
`/tmp/zeler-projection-profile.97ePq6/rejections.py` locally and on the VM.
This proves a current not-found response, not permanent impossibility or an
exact reconstruction of the historical failures. Per-product unavailable-source
observations/reasons still need persistence and consumer handling; rejecting a
whole batch or repeatedly recovering its successful siblings is not that behavior.

Rollback boundary: the bounded-wave wrapper in `FormulaRecoveryWorker` and its
associated tests; no schema/data rollback. Only a new `sheets-worker` image is
needed for this code. Runtime still uses `0db69e5`; the concurrent implementation
has not been deployed or timed against the whole pilot catalog. Before the next
full rollout acceptance run, address the known per-product unavailable reason
and remaining admission/convergence gaps. The goal remains open.

## Full inventory faster, catalog convergence still incomplete — 2026-09-08

The same `0db69e5` inventory acquisition completed 1,900/1,900 publications with
zero unavailable IDs. Watch session `78965` is terminal, exit zero; do not restart
it. Its final inventory probe reported age 689.51 seconds and last update 2.29
seconds earlier, placing completion at approximately 687.22 seconds, versus
896.44 for the previous run. This is a measured whole-inventory improvement of
about 23%, not the larger improvement from the earlier 20-item sample.

The watcher admitted product recovery through the normal helper while enumeration
and all item sources were current. The first two actual handlers identified
885 products, zero missing item sources and three-/six-column rows. They took
9.2279/11.9843 seconds and reported zero/one available product. Admission returned
false after partial enqueue; it did not mean that no work was admitted.

Two subsequent normal `products.py recover` calls observed available products
240/261 and 527/552, with current inventory and preserved incomplete metadata.
Read durations were 10.9318/10.7749 and 7.2514/8.7006 seconds. The later request
found enumeration expired, 100/120 unavailable item sources and 794/790 available
products, so it correctly skipped further product admission. The changing counts
are sequential observations, not a fixed-membership comparison. No observation
timestamps, cooldowns or freshness markers were overridden.

A separate lightweight VM probe confirmed 806 product snapshots acquired since
this enumeration, with 43 completed, two failed and one pending product jobs.
The two failed jobs reported `source_rejected`; this does not identify the exact
upstream HTTP status or prove which individual products are unrecoverable.
The normal request sequence had 920 product slots across job history; rebuilding
groups from a changing missing set can overlap earlier batches. Do not interpret
job slots or completed-job counts as unique/current product coverage. The pending
job remains scheduled: a follow-up probe measured 499.07 seconds until its
existing `available_at`, with no running product job. No cooldown was bypassed
and no new inventory run was admitted after expiry.

The recovered purpose data persists, but the end-to-end current catalog remains
unproven: 79 products were still missing at the expired read, and that read itself
no longer covered the full current membership. Next work must improve product
acquisition/admission throughput and diagnose the rejected resources rather than
repeat the identical sweep or relax the currentness test. The product worker is
currently sequential per product, whereas item acquisition already uses four
bounded concurrent sub-batches; full reads during acquisition also cost more than
the approximately three-second idle samples. These identify investigation paths,
not a claim that a particular next change will solve the complete problem.

Evidence: `/tmp/zeler-projection-profile.97ePq6/{watch-products,products,progress}.py`
on the approved VM, using the real worker, normal queue and Mongo-backed handlers.
This is still operator evidence, not authenticated production HTTP/real Sheet
acceptance. Documentation-only unit; no new build or deploy. Rollback removes
this section alone. Worker remains `0db69e5`, API `c90a941`.

## Variation-attribute worker rollout — 2026-09-08

`sheets-worker` now runs `0db69e5d9317b6f57c4d51d4521d4e6471c77956` as
`sha256:c3ad9eeba1e364ee2268fc3cbce9e811c79a997300029a8d51be862b38f7b647`.
Cloud Build `0541e642-462e-45d4-8de5-b86c363c2fc5` succeeded from that exact
connected-repository commit; digest/build/source provenance passed locally and
in the VM canonical map. CI test `34282539619` and lint `34282539551` both
succeeded before activation. Only the worker was replaced, without dependencies
or running recovery jobs; HTTP health was 200 with zero restarts.

The current rollback is worker
`sha256:443691ebbe7fc488a1a7fb34d57a0e98e0628249864a02b5948f82738c62bf03`,
with Compose backup `.pre-sheets-worker-activate-0db69e5`. API remains
`c90a941`, digest
`sha256:1702d8adc804f8b10a31eeb7b96e3e1d9964f94e5609643e74e8b6545036b391`;
its active HTTP paths are unchanged by this acquisition-only fix.

To preserve the 5 GiB floor, removed only the unused local worker image
`sha256:7dde61dfd30a17560bf581cc62315d4f7901531a88f0f94c8da1bb172cfacc5f`
after confirming exact Artifact Registry availability and no running/stopped
container references. Current and immediate rollback images remained present;
no business data or volumes were removed. Preflight with automatic cleanup
disabled passed. Pull took 15.96 seconds and left Compose unchanged;
post-activation free space was 5,891,936,256 bytes. Recheck before another pull.

One normal inventory request was admitted after deployment with no active jobs,
no cooldown override and no fabricated observation time. It reuses deterministic
job `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
Initial state was pending, attempt zero and no offset; the retained old 1,900 IDs
and expired enumeration were not new coverage. Receipt:
`/var/lib/zeler-platform/repairs/catalog-inventory-0db69e5.json`.
Observe this same run; do not repeat `inventory.py prepare`. The one-shot product
watcher uses receipt `catalog-product-admission-0db69e5.json` and admits products
only after a completed, still-current inventory. Full convergence remains open.
Local/VM artifacts are `/tmp/zeler-projection-profile.97ePq6/`, including the
verified build, pull/activation guards and the new inventory/product probes.

## Acquire variation attributes in the existing multiget — 2026-09-08

Item enrichment now requests `include_attributes=all` in its existing multiget,
preserving the individual-variation fallback when no usable SKU is returned.
This removes a demonstrated source of redundant requests without dropping
purpose fields, increasing concurrency, changing freshness or adding a cache.
The [official variation contract](https://developers.mercadolibre.com.mx/en_us/variations)
documents the parameter for variation attributes; the approved runtime probe
also verified it works on this seller's multiget responses.

Read-only profiling used the last 20 IDs of the completed pilot inventory,
the actual Sheets gateway identity, four concurrent five-item sub-batches and
`dry_run=True`. Original acquisition validated all 20 in 5.2167 seconds with
93 requests: four multigets, 34 variation details, 20 sale prices, 20 listing
prices and 15 shipping options. Adding the parameter validated the same 20 in
3.2432 seconds with 59 requests and no individual variation calls. These are
two sequential samples, not a p95 measurement or proof of whole-inventory
convergence. No business data was written by either sample.

Projection was checked separately: 20 items in 0.2357 seconds, including
0.0089 seconds to load six order-line identity groups and 0.0362 seconds to load
1,529 status records. The broad status read is not the main measured delay;
it was intentionally left unchanged. Artifacts are under local
`/tmp/zeler-projection-profile.97ePq6/`, with VM scripts
`/tmp/zeler-projection-profile-97ePq6.py`,
`/tmp/zeler-acquisition-profile-97ePq6.py` (original query) and
`/tmp/zeler-acquisition-attributes-97ePq6.py` (candidate query).

The new regression failed on the old multiget path and passed with the single
query change. It verifies persisted variation attributes, no redundant detail
call and a source-bound formula row retaining zero stock. Eight existing
real-Mongo acquisition cases now additionally cover that enriched variation,
while retaining dry-run, ownership, concurrent-write and unavailable-history
checks; all eight passed in 1.55 seconds. Existing fallback tests remain.
The acquisition/recovery/history/event suite passed 537 tests in 45.73 seconds.
Root regression passed 4,053 tests with nine expected skips and 356 warnings in
121.94 seconds; the eight protected replica-set cases passed separately in
2.48 seconds. Ruff check/format, mypy on 505 files and diff checks passed.

The affected normal runtime paths are Sheets recovery and item-event acquisition
in `sheets-worker`; no formula HTTP handler starts acquisition. Build and verify
a worker image from the committed change before claiming it runs in production,
then measure one full inventory and actual catalog-product recovery. The current
worker still runs `c90a941`. Rollback is the query parameter and its associated
fixtures/regression only; no schema or data rollback is needed. Full catalog
convergence and the remaining goal acceptance gates remain open.

## Completed acquisition exposes catalog freshness starvation — 2026-09-08

The same `c90a941` inventory job completed all 1,900 publications with zero
unavailable IDs. Watch session `70728` is now terminal: its final probe observed
`completed`, offset 1,900, enumeration age 904.66 seconds and time since the
last update 8.22 seconds. Completion therefore occurred approximately 896.44
seconds after enumeration, leaving under four seconds of the 15-minute window.
The watcher exited with its freshness assertion, before product admission. This
is a successful inventory acquisition but **not** current catalog coverage.
Do not restart the watcher or inventory merely because this observation ended.

A subsequent VM/API-container `products.py read` confirmed both real handlers
remain incomplete. `OBTENER_CATALOGO` took 3.0095 seconds: zero current products,
874 missing products and 80 unavailable item sources. `CATALOGO_COMPLETO` took
2.9758 seconds: zero current products, 873 missing products and 100 unavailable
item sources. Both reported expired enumeration and `inventory_incomplete`,
with their unchanged three-/six-column contracts. These are sequential readings
with independently evaluated freshness, not comparable fixed membership counts.
The earlier stored job history remained one completed and 19 rejected product
jobs (400 slots); it is not evidence of new admission. Global freshness markers
were unchanged. No new recovery was admitted by this read-only probe.

The current handler requests item recovery before product recovery whenever any
inventory gap exists. Combined with this measured acquisition time, the serial
dependency leaves effectively no time for acquiring the missing catalog products;
early item observations also expire while later items finish. The next functional
correction must address acquisition sequencing/throughput with a regression for
whole-inventory convergence. Repeating the same sweep, stamping observation times
at completion, or relaxing freshness solely to make the check pass does not prove
the requested behavior. The original generic failure's exact cause remains
unproven, although this run advanced past its former offset and completed.

Evidence: `/tmp/zeler-catalog-retry.UAUPVJ/watch-products.py`, `inventory.py status`
and `products.py read` on the approved VM. This is operator/runtime evidence,
not authenticated production HTTP or a real Sheet smoke. Documentation-only
unit: no executable change, build or deployment required; rollback removes this
section alone. Both deployed service sources remain `c90a941`.

## Acquisition retry and shared-count rollout — 2026-09-08

Both Sheets services now run source `c90a9410e0b19ede3919160d6f41c34a7179492f`,
including the shared-user count fix and bounded item-acquisition retry below.
Each image was built separately from the exact pushed connected-repository
commit with requested verification, and digest/build/source provenance passed
locally and in the VM canonical map. CI test `34278851008` and lint
`34278851027` both succeeded before activation.

| Service | Successful Cloud Build | Deployed digest |
| --- | --- | --- |
| sheets-worker | `3bfb2c2c-0da4-4ac2-ae20-7361d1d83ab0` | `sha256:443691ebbe7fc488a1a7fb34d57a0e98e0628249864a02b5948f82738c62bf03` |
| sheets-api | `c3daad42-1057-49f6-9504-d4a123c7edaa` | `sha256:1702d8adc804f8b10a31eeb7b96e3e1d9964f94e5609643e74e8b6545036b391` |

The additive `competitors_sharing_first_place` validator was applied first to
`sheets_catalog_buybox_snapshots` only. The guard confirmed the previous strict,
error-action validator differed solely by that property; readback matched the
expected schema. No business documents were modified by the schema operation.

Worker then API were replaced independently with exact Compose substitutions,
zero running recovery jobs at the gates, no dependency restarts, preflight and
the 5 GiB floor. Both passed HTTP health 200 with zero restarts. Pulls took
17.18s and 12.14s; post-activation free space was 5,911,506,944 bytes. Current
rollback images remain worker
`sha256:5d27006e97150292a3d5bdda1e3bf5fca596fc06cfd8a58f6186d25d4141ab65`
and API `sha256:542a54066589ef4417c29d33ce552d5f22eddcbb32c62a0adf31c8861be7aa27`.
Compose backups end in `.pre-sheets-worker-activate-c90a941` and
`.pre-sheets-api-activate-c90a941`; reverse only the affected service.

Three unused image copies were removed from local cache after confirming exact
Artifact Registry availability and no running/stopped container references:
worker `sha256:65a8dcffe3ae125b94c3b50092af3e5fa08abd88921b8fe8ddc8b512940dc623`,
API `sha256:c679a81b7ad3e0b026f8b4a8a4e1ff5bddc1387bcccbf59fc31cb808f70ab56c`,
and worker `sha256:5e6a0bae160b005a34efc0f7894de078b442ef99b63b8b0da7734a2ca6a43a18`.
No volumes, business data or other services were removed; current/prior rollback
images were retained. Artifacts: `/tmp/zeler-catalog-retry.UAUPVJ/` locally and
on the VM, including schema guards, builds, provenance, pull/activation scripts
and sanitized acquisition probes.

One new genuine inventory acquisition was admitted through the normal queue
after the previous terminal failure, without overriding cooldown or freshness.
It reuses job `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
Initially pending/attempt zero with no new offset, it still carried old IDs and
the old failure reason; these are not new coverage or a new failed attempt.
Protected receipt: `/var/lib/zeler-platform/repairs/catalog-inventory-c90a941.json`.
`inventory.py prepare` succeeded once. Observe the same job with `status` and
the already-started one-shot `watch-products.py`; never repeat prepare or start
another watcher while that observation is live. Its protected receipt ends in
`catalog-product-admission-c90a941.json`. Product admission occurs only after a
completed, still-current inventory through the normal helper. The full catalog,
production authenticated formula smoke and real Sheet remain unproven.

## Inventory failure and bounded acquisition retry — 2026-09-08

The second genuine inventory acquisition on worker `f4fee30` stopped at
1,460/1,900, attempt one, with `failure_reason=recovery_failed` and zero items
recorded as unavailable. This is terminal incomplete acquisition, not success.
`watch-products.py` observed that exact terminal state and exited without
admitting products. Its one-shot protected receipt is
`/var/lib/zeler-platform/repairs/catalog-product-admission-f4fee30.json`; do not
restart the watcher or reinterpret its receipt as a live process.

A read-only runtime probe of the next 20 IDs, four five-item batches through the
Sheets client with `run_item_detail_enrichment(dry_run=True)`, validated all 20
with zero stale entries. It made no business-data writes. Therefore the original
generic failure was not reproduced and its exact historical cause remains
unproven. Artifact: `/tmp/zeler-catalog-client.Mgb5Vu/failed-items.py`.

Code review and failing real-Mongo worker tests demonstrated a related concrete
failure class: an item changing during enrichment, an older/undated source, and
429/5xx embedded in a successful multiget response were generic runtime errors
and bypassed bounded retries. A single typed acquisition exception now routes
only those known conditions through the existing 30/60-second retry policy.
The full-source compare-and-swap and source-age checks remain intact; no failed
observation is written. Unknown implementation errors and foreign-seller
responses still fail, rather than being blindly retried.

The corrected fixture reproduced all five cases as `recovery_failed` without the
new catch, then seven focused cases passed in 1.72s with the catch: five recover
on their next attempt and two unsafe/unknown cases stay failed. The existing
inventory exhaustion test also exercises embedded 503 responses through the real
parser, including the three-attempt cap, continued later batches and explicit
unavailable membership. Acquisition/recovery verification passed 459 tests in
65.72s. Root regression passed 4,052 tests, nine expected skips and 356 warnings
in 121.05s; the eight protected replica-set cases passed separately in 3.17s.
Ruff check/format, mypy on 505 source files and diff checks passed.

Rollback boundary: the typed exception, its three acquisition raise sites, worker
catch and their regression cases. No queue schema, cooldown bypass, new scheduler
or credential change is introduced. A worker rebuild is required before a new
production acquisition; this code fix does not prove the unknown original error
cannot recur. The earlier shared-count change still also requires its additive
buybox validator and an API rebuild.

## Catalog shared-user count — 2026-09-08

`CATALOGO` now reads `competitors_sharing_first_place` for its existing shared-user
column, without substituting total competitors or an undocumented alias. The
normalizer persists the official field when explicitly supplied as a nonnegative
integer or null; it leaves missing/malformed values unacquired rather than
coercing booleans, negative numbers or numeric strings. Mongo's additive optional
field accepts nonnegative int/long/null, and the reader also handles BSON Int64.

The existing 24-column matrix is unchanged: zero remains zero, an explicit null
is NA, and absent/invalid data is DATA_UNAVAILABLE. Metadata reports the count
of affected rows and `catalog_shared_users_not_acquired` when needed, preserving
the other columns. The source-column fixture now names the actual field.
This follows the official [catalog competition contract](https://developers.mercadolibre.com.mx/en_us/introduction-services/catalog-competition):
the shared-first-place measure is not the total number of competitors and can
be null for nonwinning states. It is not a global count of winners.

TDD exposed nine acquisition/schema/consumer failures initially, plus the
missing-field/zero/malformed distinctions and a BSON Int64 regression. The final
focused historical/consumer/schema/recovery suite passed 433 tests in 52.66s,
including three actual Mongo-validator persistence cases for zero, a positive
shared count and null. Root regression passed 4,044 tests with nine expected
skips and 356 warnings in 113.15s; the eight protected replica-set cases passed
separately in 3.06s. Ruff check/format, mypy (505 files), schema export and diff
checks passed. The remaining skip is the existing Caddy-key check.

Before deployment, apply the additive buybox validator, then build/verify Sheets
API and worker images from the intended commit and reacquire real buybox data.
Do not interrupt the inventory/product recovery currently running on `f4fee30`.
Rollback can revert the normalizer/reader/fixture change independently, retaining
the optional validator property so already persisted snapshots remain valid.
This unit does not fix `CATALOGOBUYBOX` winner-count semantics, other missing
buybox purpose fields, automatic buybox recovery, current membership, or the
remaining historical/order freshness gates; those remain required goal work.

## Catalog detail-client rollout — 2026-09-08

Worker source `f4fee302073693ed5df2f17202ded42b866b30a7` is deployed as
`sha256:5d27006e97150292a3d5bdda1e3bf5fca596fc06cfd8a58f6186d25d4141ab65`.
Cloud Build `44b00de5-99ad-4f30-b572-1507b47b10f5` succeeded from that exact
connected-repository commit, one worker image with requested verification.
Digest/build/source checks passed locally and in the VM canonical image map.
CI test `34275324620` and lint `34275324769` both succeeded before activation.

Only the worker was replaced, with no dependencies restarted. It passed HTTP
health 200 with zero restarts. API remains the prior `a5fe92a` image; no API code,
Mongo schema or permissions changed. Immediate worker rollback is
`sha256:7dde61dfd30a17560bf581cc62315d4f7901531a88f0f94c8da1bb172cfacc5f`,
with Compose backup `.pre-sheets-worker-activate-f4fee30` for service-scoped
reversal. Artifacts: `/tmp/zeler-catalog-client.Mgb5Vu/` locally and on the VM.

To retain the 5 GiB floor, removed only the unused local worker image
`sha256:98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`,
after verifying that exact digest remains in Artifact Registry and no running
or stopped container uses it. Six current/prior protected Sheets images were
retained; no volumes, business data or other services were removed. The new pull
took 16.65s, left Compose unchanged, and passed preflight with automatic cleanup
disabled. Post-activation free space: 5,378,048,000 bytes; recheck before further
pulls or Compose activity because the margin remains small.

`pilot.py prepare` succeeded once, reopening one existing rejected 20-product
job through the normal queue without changing its prior `available_at`:
`1333321b97d9281d74b57caaf81a3eba4259e4951d9d0d910f8b7bf0e098506f`.
It was pending, attempt zero, with 130.62s scheduled wait and zero newly acquired
products. The retained `source_rejected` reason describes the previous attempt,
not a new rejection. Global coverage markers were unchanged. Protected receipt:
`/var/lib/zeler-platform/repairs/catalog-detail-client-f4fee30.json`.
Use `pilot.py status` for this same job; never repeat `prepare` or shorten cooldown.
This operator repair does not substitute for current whole-catalog coverage,
authenticated production HTTP or the real Sheet validation.

The same job subsequently completed on attempt one: all 20 requested product
snapshots were newly acquired after the receipt, with matching identities,
valid titles, purpose-field keys and `sheets_backfill` source. No failure reason
remained and global markers were unchanged. Snapshot observation times span
3.652s; that is not the whole wall-clock job duration. The status read occurred
183.35s after preparation, including its preserved initial cooldown. This proves
the repaired production worker can persist the previously rejected products,
not that all catalog products or all 52 formulas are now validated.
A second read at 263.30s confirmed the same 20 persisted snapshots without
re-enqueueing the product job or making gateway calls from the read harness.

After the previous inventory had completed and expired, one new genuine
inventory request was admitted with no active jobs. It reuses deterministic job
`5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`,
now pending, attempt zero and immediately eligible, with the processing offset
cleared by the normal queue. Its retained 1,900 IDs are the old enumeration until
the worker rediscovers them; they are not new coverage evidence. New protected
receipt: `/var/lib/zeler-platform/repairs/catalog-inventory-f4fee30.json`.
`/tmp/zeler-catalog-client.Mgb5Vu/inventory.py prepare` succeeded once; observe
with `status`, never repeat prepare or restart the worker during acquisition.
Use `products.py` in the same directory for readers/admission with the new worker
image guard. Avoid repeated full-inventory reads while measuring acquisition;
the lightweight job status is sufficient until completion.

## Catalog recovery client correction — 2026-09-08

The full pilot inventory completed 1,900/1,900 publications with zero unavailable
items, approximately 846 seconds after discovery. Immediately afterward the two
catalog consumers found 885 current associated products, no missing item sources,
and no available current product snapshots. They returned truthful unavailable
rows in 4.0505s and 5.5827s respectively, with the existing 3/6-column contracts.
Earlier reads during inventory acquisition took 7.25–17.35s; those are operator
dispatcher timings, not authenticated HTTP or Google Sheets latency evidence.

One normal API recovery-helper invocation requested the 885 missing products.
It admitted 20 jobs / 400 product slots before the bounded admission returned
false. The next observation already showed ten failed jobs (`source_rejected`),
nine pending and one running. No global freshness marker changed. Do not infer
that all 885 products were queued or that unavailable data is irrecoverable.

The rejection exposed a real client-selection defect: production wires
`FormulaRecoveryWorker.gateway` to the bootstrap discovery identity and
`detail_gateway` to the Sheets identity, but product acquisition used discovery.
A read-only VM probe of one failed job's seller-associated product verified:
bootstrap has no registered product scope and received HTTP 403; Sheets has the
existing scope and received HTTP 200 with matching product identity and a title.
No scopes, tokens, data or timestamps were modified by that probe.

The correction routes product detail acquisition through `detail_gateway`, just
as other detail reads do. The existing six persistence scenarios now use separate
discovery/detail clients, with discovery explicitly returning 403. All six failed
before the fix by observing forbidden discovery calls; afterward all ten catalog
recovery tests passed in 2.11s, including the two real local HTTP/Mongo cases.
Root regression passed: 4,033 tests, nine expected skips and 356 warnings in
120.05s. The eight protected replica-set cases passed separately in 2.71s;
the ninth skip is the existing Caddy-key check. Ruff check/format, mypy on 505
source files and `git diff --check` passed.

Runtime artifacts: `/tmp/zeler-catalog-consumers.5t16dm/products.py` (real readers
and normal product admission, no direct Meli calls), `inventory.py status`, and
`product-auth.py` (two authorized gateway reads with sanitized output). The
original inventory job and receipt remain unchanged; do not rerun `prepare`.

Rollback boundary: the product-fetch client selection and its separate-client
regression fixture, plus this evidence. No schema, permission or API contract
change is required. Only the worker image needs rebuilding for this correction;
its deployed source must be verified before retrying product recovery. Inventory
freshness now needs a new genuine acquisition, not refreshed timestamps. The
near-15-minute inventory duration leaves little time for a subsequent full
catalog acquisition; end-to-end current availability remains unproven.

## Catalog product runtime rollout — 2026-09-08

Sheets API and worker now run source
`a5fe92aab98dbe1d35ed3d9c989a0d34416d698c`. This deploys the product worker,
HTTP admission and current-inventory consumers described below; their earlier
“not deployed” labels are historical. It does not close buybox or full-goal
acceptance. Both containers passed HTTP health 200 with zero restarts.

| Service | Verified Cloud Build | Deployed digest |
| --- | --- | --- |
| sheets-worker | `58a16b7b-1fc6-4972-95a3-fc408defb87e` | `sha256:7dde61dfd30a17560bf581cc62315d4f7901531a88f0f94c8da1bb172cfacc5f` |
| sheets-api | `f1b51387-17f3-4230-9362-1e00728863db` | `sha256:542a54066589ef4417c29d33ce552d5f22eddcbb32c62a0adf31c8861be7aa27` |

Both builds used the connected repository at that exact pushed commit, one image
per build and requested verification. Digest/build/source provenance passed on
the operator host and VM. The canonical VM image map contains both new entries
and the retained prior entries. CI test `34271626578` and lint `34271626556`
completed successfully before service replacement.

Worker then API were pulled and activated independently, using exact single
Compose substitutions, no dependency restarts, no running recovery jobs at the
replacement checks, and the 5 GiB preflight/activation floor. Pulls took 16.42s
and 18.93s respectively. Retained immediate rollback images are worker
`sha256:5e6a0bae160b005a34efc0f7894de078b442ef99b63b8b0da7734a2ca6a43a18`
and API `sha256:2c2c8bf22f7fbe21fc8253962e53fe5314dfbcf3bedc6f85b1f71f5f17cc311a`.
Compose backups end in `.pre-sheets-worker-activate-a5fe92a` and
`.pre-sheets-api-activate-a5fe92a`; use service-scoped reversal, not a broad
restoration that could undo another service's later changes.

Two unused old API images were removed only from the local Docker cache:
`sha256:d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`
and `sha256:b03d53422a57202974f77e70d651731ca01317aa7d3e7448d4592c71364defaf`.
Both exact digests were confirmed in Artifact Registry and unused by any running
or stopped container before removal. Current/rollback images were retained;
no volumes, business data or other services were removed. Post-rollout free
space was 5,389,115,392 bytes, still close to the floor: recheck before every pull.

Artifacts on operator host and VM: `/tmp/zeler-catalog-consumers.5t16dm/`, including
builds, provenance, guarded pull/activation scripts and the read-only coverage
probe. The probe ran inside the new API container and found 887 stored associated
products, two explicitly known catalog participants, no active recovery jobs,
and an expired inventory with 1,900 unavailable item sources. Zero products were
currently verified by the consumer; stored associations are not current coverage.
This was read-only and did not refresh timestamps or publish completeness markers.

The operator then admitted the normal pilot inventory request once through
`FormulaRecoveryQueue`, guarded by both new healthy image identities and no
active recovery jobs. Job
`5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`
was pending, attempts zero, immediately available, with no new processing offset
yet. Protected receipt: `/var/lib/zeler-platform/repairs/catalog-inventory-a5fe92a.json`.
`inventory.py prepare` succeeded once; use `inventory.py status` for subsequent
observation, never repeat prepare or stamp old inventory dates. This is an
authorized operator recovery, not an authenticated end-user HTTP smoke.
The next status read confirmed the worker running on attempt one with 140/1,900
publications checkpointed and zero unavailable items recorded so far. This is
in-progress evidence, not completed recovery or current product coverage.

Next required evidence: refresh actual inventory through the normal worker,
recover current product snapshots, measure partial-to-complete reads and verify
authenticated production HTTP plus the real Sheet. Health/provenance alone do
not prove formula correctness or data coverage. No additional image rebuild is
needed for this evidence-only documentation change.

## Current-inventory catalog consumers — 2026-09-08 (not deployed)

OBTENER_CATALOGO and CATALOGO_COMPLETO now use the real product recovery bridge.
They derive parent and variation product IDs from current, fingerprint-verified
canonical items belonging to the inventory receipt. A SKU-less parent need not
have its own formula row; its canonical association is still included. The
canonical reread must still match the source fingerprint/observation so a changed
item cannot silently reuse an older projection.

Product reads are seller- and membership-scoped, require a nonfuture snapshot
younger than 15 minutes, normalized acquisition source, a valid title and the
purpose-field keys. Global catalog markers no longer authorize these reads.
Missing products get explicit DATA_UNAVAILABLE rows and targeted async recovery;
available products remain visible. Unknown/expired item inventory adds an
unavailable coverage row and requests item recovery first. A proven empty current
inventory returns an empty complete result, never all historical snapshots.
Metadata explicitly reports completeness and the reason for unavailable data.

- TDD: both actual formula HTTP paths failed before migration. Extending the
  scenario to a SKU-less parent plus a variant then exposed the lost parent
  association; the canonical-source reader fixed it.
- Local runtime boundary: the actual application, token validation, inventory
  receipt, canonical/projection Mongo reads, durable queue and worker participate
  in `test_catalog_product_http_admission_reaches_worker_and_persists`.
  Both formulas passed in 0.97s with parent and variant products: the first HTTP
  request queues recovery with no gateway call, the worker persists both products,
  and two later requests reuse them without new acquisition or a global marker.
  This is synthetic local source data, not a production HTTP acceptance result.
- Handler regression: 41 passed in 0.17s, including 1,001 current products,
  unrelated snapshots, stale/future/missing/incomplete products, expired inventory,
  unverified items and proven empty inventory. Old global-marker-only fixtures
  were migrated to explicit inventory/source evidence.
- Final root regression with loopback Mongo: 4,033 passed, nine skipped,
  356 warnings in 119.16s. Protected replica-set tests ran separately: eight
  passed in 3.21s. Ruff check/format, mypy (505 files), and diff checks passed.
- Rollback boundary: the new repository reader, the two shared-handler entrypoints,
  and their inventory/HTTP tests. No schema changes or business-data deletion.

The last observed production images remain at `07c8ad3`; this migration and the
preceding product worker/admission units are not deployed. Build new verified
Sheets worker and API images, recheck VM capacity and image drift, then validate
pilot HTTP recovery, persisted parent/variation products, subsequent reads and
unchanged global coverage markers. Buybox/CATALOGO semantics and the other goal
acceptance requirements remain open; this is not closure of all catalog work.

## Catalog HTTP recovery admission — 2026-09-08 (not deployed)

Formula recovery errors/results can now carry explicit `catalog_product_ids`.
The API keeps them separate from publications, orders, shipments and date ranges;
sorts/deduplicates the complete set; validates every batch before admission; and
enqueues batches of at most 20 within a single one-second insertion budget.
Capacity errors and timeout preserve already-calculated values and report that
the complete recovery request was not admitted. No external API call is added
to formula execution.

- TDD: five HTTP scenarios initially returned 500 before the new error field and
  dispatch branch. A sixth later exposed redundant batches for repeated/reordered
  IDs. Final `test_formula_api.py`: 38 passed in 1.73s.
- Local runtime boundary: `test_catalog_product_http_admission_reaches_worker_and_persists`
  passed in 0.60s with real Mongo and authenticated local HTTP. An injected test
  handler first reports missing product data; HTTP admits the durable job without
  gateway calls; the actual worker obtains and persists it; two later HTTP reads
  reuse it with no further gateway calls. This isolates admission/persistence;
  it does **not** prove current production catalog handlers or inventory coverage.
- Root regression before the final deduplication case: 4,017 passed, nine skipped,
  356 warnings in 112.26s. Protected replica-set tests ran separately: eight
  passed in 3.18s. Final API regression includes the deduplication change.
  Ruff check/format, mypy (505 files), and diff checks passed.
- Rollback boundary: the optional error field, product-specific admission branch,
  and associated HTTP/runtime tests. No database schema/index or runtime changes.

Next required step: migrate OBTENER_CATALOGO and CATALOGO_COMPLETO from global
markers/all stored products to current-inventory membership, per-resource
freshness, and partial-result recovery using this bridge. Until then, the normal
handlers do not emit the new product requests. Both API and worker require new
verified images after that consumer migration; the last observed production
images are still from `07c8ad3`. Verify image drift again before rollout and
prove the actual production formula → worker → Mongo → formula path afterward.

## Catalog product recovery worker — 2026-09-08 (not deployed)

The queue/worker now support explicit catalog-product requests, separate from
publication IDs and date ranges: numeric seller, 1–20 validated product IDs,
deduplicated identity and existing transactional seller admission. Range-shaped
catalog requests are rejected. The API/formula bridge is still pending; this
unit alone does not make user-triggered catalog recovery operational.

The worker checks seller-associated parent/variation product IDs before any
gateway call, fetches each product with a ten-second bound within the existing
240-second job limit, verifies response identity and a textual nonempty title,
and writes only normalized snapshots under seller-scoped IDs. Successful sibling
products survive failures; transient failures use the existing bounded retry
policy. Lease loss prevents subsequent writes. Older overlapping observations
cannot replace newer snapshots. No whole-seller coverage marker is published.
Successful refresh cooldown ages from acquisition start, not completion.

Product normalization now retains official plaintext
`short_description.content`, including paragraph boundaries; empty content stays
absent. Contract source:
[Mercado Libre product detail](https://developers.mercadolibre.com.mx/es_mx/buscador-de-productos).

- TDD: six initial queue/worker cases failed before implementation. A malformed
  title case then exposed coercion; a refresh-timing case exposed extra cooldown;
  and a description case exposed discarded content. Each was fixed after failure.
- Local runtime boundary: Mongo validator insert/read and real durable queue
  processing cover parent/variation association, seller rejection, sibling
  failures, retries, lease theft, and out-of-order snapshot writes. The eight
  focused worker/request cases passed in 1.68s before adding the cooldown case.
- Root regression before the final description/cooldown additions: 4,007 passed,
  nine skipped, 356 warnings in 111.25s. Protected replica-set tests ran separately:
  eight passed in 2.35s. Final affected-module rerun with loopback Mongo:
  `test_historical_meli_backfill.py` plus `test_formula_recovery.py`:
  358 passed in 53.13s, including the description and cooldown additions.
- Ruff check/format, mypy (505 files), and diff checks passed after all code edits.
- Rollback boundary: the product request type/admission, worker branch, successful
  product cooldown rule, description mapping and their tests. No schema or index
  change, business-data deletion, or production mutation was performed.

Next: bridge missing product IDs from formulas into the queue and read current
inventory-bound product snapshots with per-resource freshness and honest partial
results. Catalog buybox recovery and count/reason semantics remain separate open
work. Build verified worker/API images after the consumer unit, then prove the
actual request → worker → Mongo → subsequent formula path in production; current
deployed `07c8ad3` images do not contain this implementation.

## Catalog item-purpose fields — 2026-09-08 (not deployed)

Buybox normalization now takes publication title and available quantity from
the canonical item/detail source, not from the competition response. The Mongo
source projection retains both fields; freshly acquired item sources still
override stored ones. Zero stock stays zero; absent stock remains unknown.
No extra formula-side acquisition or schema change is introduced.

Read-only pilot evidence from the approved worker container, at source
`07c8ad36e52451e13fa46167502972909b55d997`: one explicit catalog participant
selected from the existing 20-item pilot receipt was checked through the normal
Sheets gateway. The final probe made three calls (item, competition, product)
and no business-data writes. Stored and current item product links agreed.
The item was `under_review`; competition returned `not_listed` with
`item_not_opted_in`, null product identity/prices/shared-first-place count,
and no winner. Null competition identity is not evidence of a changed item
association. Title and quantity were present in the item and absent from the
competition response. Product detail provided `short_description`, not
`description`. Only approved status labels and field presence/types were printed.
Probe: `/tmp/zeler-catalog-purpose-probe.py` on the operator host and VM;
selection receipt: `catalog-participation-07c8ad3.json` in the protected VM
repairs directory. This is not an authenticated formula HTTP smoke.

- TDD: three source-title/quantity cases failed before the fix, then passed.
  `uv run pytest modules/sheets/tests/test_historical_meli_backfill.py --tb=short`:
  60 passed in 0.28s.
- Local Mongo boundary: `test_formula_recovery.py -k
  'catalog_source_projection or catalog_buybox_persists'`: four passed in 1.11s.
  Source projection, seller filtering, and validated snapshot insert/read cover
  stock zero, positive stock, and unknown stock with an actual not-listed-shaped
  competition response. These are synthetic local cases, not production writes.
- Root regression with loopback Mongo: 3,999 passed, nine skipped, 356 warnings
  in 108.01s. Eight skips are the protected replica-set tests, run separately
  without ambient `MONGO_URI`: eight passed in 2.24s. The remaining skip needs
  Caddy keys. Ruff check/format, mypy (505 files), and diff checks passed.
- Rollback boundary: the two optional `CatalogSnapshotSource` fields, their
  source projection/parser, buybox title/quantity mapping, and associated tests.
  No schema narrowing or business-data deletion is needed.

Still required: automatic catalog recovery and current-resource receipts,
purpose-complete competition fields/reasons and product description mapping,
and truthful consumers. Both current count consumers conflate
`competitor_count` with shared-first-place/winner columns. The legacy reference
reads `competitors_sharing_first_place`; Mercado Libre documents it separately
from all competing publications. Do not derive total competition or sole
competition from that field, and do not turn a not-listed response into a
successful complete competitive snapshot. Reference:
[Mercado Libre competition contract](https://developers.mercadolibre.com.mx/en_us/introduction-services/catalog-competition).

At the probe, deployed API `2c2c8bf...` and worker `5e6a0bae...` remained healthy
with zero restarts; free disk was 5,393,076,224 bytes. This code change is not in
those images. Build a new verified Sheets worker image when the next catalog
recovery unit is ready for rollout, then verify persistence and subsequent
formula reads in the approved runtime context. Do not claim deployment from
local tests; API consumer changes will also require an API image.

## Catalog participation persistence — 2026-09-08 (not deployed)

The canonical item and formula-row projection now preserve Mercado Libre's
`catalog_listing` boolean independently of `catalog_product_id`. Missing or
malformed flags remain unknown; neither a product link nor a variation's link
implies participation. Variations inherit the publication's participation flag.

This is an acquisition/persistence unit. The subsequent calculator unit below
uses the flag; dashboards are migrated below, while catalog table consumers
still require migration. Existing
production data has not been backfilled or relabeled by these changes.

- TDD: ten canonical-item/projection cases failed before the change, then passed
  (true, false, null, malformed string and integer, each for parent/variation).
- Focused regression: `uv run pytest modules/sheets/tests/test_event_persistence.py
  modules/sheets/tests/test_sheetseller_backfill.py core/tests/test_models_phase3.py
  tests/test_sheets_schema_contract.py --tb=short`: 283 passed.
- Local runtime boundary: `test_formula_recovery.py -k catalog_participation`,
  with the loopback replica-set fixture and committed Mongo validators:
  3 passed. Canonical item insert/read followed by projection insert/read retains
  true, false and unknown. This is not production or HTTP evidence.
- Root regression with loopback Mongo: 3,976 passed, 9 skipped, 356 warnings
  in 113.69s; the three new Mongo cases were added after root collection and
  verified separately above. Protected replica-set tests: 8 passed in 2.30s.
  Ruff check/format, mypy (505 files), schema export drift and diff checks passed.
- Deployment gate: apply the additive `items` and `sheets_item_formula_rows`
  validators in the approved VM context before deploying writers. The current
  strict `items` validator otherwise rejects the new field. Verify accepted
  writes and subsequent projection reads before changing consumer semantics.
- Rollback boundary: revert the optional model field/normalizer, projection,
  corresponding schema additions and their tests together. An already-applied
  additive validator may remain; do not narrow it while stored documents retain
  the field. No business-data deletion is part of rollback.

## Calculator participation and recovery — 2026-09-08 (not deployed)

CALCULADORA now reports CATALOGO only for explicit `catalog_listing=true`,
REGULAR only for false, and DATA_UNAVAILABLE for unknown participation.
`catalog_product_id` no longer determines this classification. Missing
participation joins existing price/cost gaps in bounded item recovery; available
columns remain usable, and formulas do not call Mercado Libre.

- TDD classification matrix: 4 failed and 2 passed before implementation;
  all six combinations of participation and product-link presence pass now.
- Quality/calculator suite: 58 passed in 0.11s, including selected-publication
  and complete-inventory targeted recovery for a missing participation flag.
- Root suite with loopback Mongo: 3,988 passed, 9 skipped, 356 warnings in
  124.31s. Protected replica-set scenarios separately: 8 passed in 3.06s.
  Ruff check/format, mypy (505 files) and diff checks passed.
- Local HTTP/worker/Mongo boundary: the existing cost-recovery scenario now
  also covers a catalog-only gap. Both passed in 0.99s. An authenticated local
  HTTP read queues only the affected item, worker acquisition persists false
  despite an associated product, and the next HTTP read returns REGULAR without
  requesting recovery or making upstream calls. Gateway responses are synthetic;
  this is not production HTTP or real-Sheet evidence.
- Deployment still requires the preceding additive Mongo validators and new
  Sheets API/worker images, then a bounded owned-item refresh and repeated
  authenticated reads. Do not relabel old snapshots from product associations.
- Read-only VM check after local verification: API digest `c679a81b…` and worker
  digest `65a8dcff…` remain healthy with zero restarts; neither contains these
  catalog changes. Free space was 5,395,533,824 bytes, barely above the 5 GiB
  gate: recheck capacity before any pull/activation. No production writes here.
- Rollback boundary: revert calculator classification/recovery selection and
  its tests together; the additive persistence field can remain independently.
  Dashboard filtering is migrated below; catalog snapshot consumers remain pending.

## Historical buybox participation scope — 2026-09-08 (not deployed)

Historical catalog acquisition now selects buybox requests only for explicit
`catalog_listing=true`; product snapshots still include associated parent and
variation products regardless of participation. Mongo source projection and
fresh-response override preserve the boolean independently of those links.

Unknown participation, or true participation without a parent product identity,
refuses this historical backfill before catalog requests or business writes.
This is an operator backfill precondition, not a change to formula availability:
refresh item details first. It does not implement automatic catalog recovery,
remove old snapshots, establish current catalog membership, or bypass item limits
by silently acquiring all unknown stored publications. Those remain separate
functional work; production has not been refreshed by this unit.

- TDD: explicit true/false/unknown scope test initially had 2 failures and
  1 pass; the historical suite now has 57 passed in 0.29s. Tests check product
  acquisition remains intact for false, zero buybox calls/writes for false,
  and no catalog calls or item/order writes for unknown.
- Local Mongo source-projection test: 1 passed in 0.46s, preserving true/false,
  deduplicated variation associations and seller isolation. No upstream live
  calls or production writes were made for this unit.
- Root regression with loopback Mongo: 3,991 passed, 9 skipped, 356 warnings
  in 114.95s. Protected replica-set scenarios: 8 passed in 2.83s. Ruff check,
  format, mypy (505 files) and diff checks passed.
- Deployment: include this change in the next verified Sheets worker/API
  images, after the additive item validators. Do not invoke a broad historical
  backfill as a smoke test; verify a bounded owned-item catalog scope first.
- Rollback boundary: source dataclass/projection/parser and participation scope
  guard with their tests. The canonical persisted flag and calculator fix are
  independent and need not be reverted.

## Dashboard catalog classification and recovery — 2026-09-08 (not deployed)

DASHBOARD and DASHBOARDSINCATALOGO now use explicit `catalog_listing`:
true renders Sí, false renders No, unknown renders DATA_UNAVAILABLE.
The exclusion filter removes only true participation. Unknown rows stay visible
with their other available fields; `catalog_filter_complete=false` and a reason
make unresolved membership explicit. Recovery requests deduplicate item IDs
across variant/SKU rows and use the existing bounded item recovery path.

- TDD: both mixed-participation dashboard cases failed before the change.
  Core handler suite now passes 43 tests in 0.29s. Existing tests no longer
  expect No from an absent flag; tests of known regular/catalog rows provide
  the actual boolean explicitly.
- Root suite with loopback Mongo: 3,993 passed, 9 skipped, 356 warnings in
  114.05s. Protected replica-set scenarios: 8 passed in 3.28s. Ruff check/format,
  mypy (505 files) and diff checks passed.
- Local runtime boundary: the existing HTTP/worker/Mongo test now reads both
  dashboards before and after acquisition. Both cost-gap/catalog-only scenarios
  passed in 1.15s, showing DATA_UNAVAILABLE then No, preserved rows, no subsequent
  recovery request, and no upstream calls from formula reads. This test extension
  was run separately after root collection began. Upstream responses are
  synthetic; it does not establish production HTTP or real Sheet behavior.
- Scope caveat: this fixes participation and filtering, not the dashboards'
  broader inventory/order coverage and freshness guarantees. Those still need
  verification/correction; missing orders must not be assumed to prove zero sales.
- Deployment requires the additive item validators and new Sheets API/worker
  images. Verify scoped acquired values and repeated reads after rollout.
- Rollback boundary: dashboard participation helper, rendering/filter/recovery
  and corresponding tests. Canonical persistence, calculator and historical
  acquisition fixes can remain independently. No data deletion is required.

## Catalog rollout preparation — 2026-09-08

Production Mongo now accepts optional `catalog_listing` in `items` and in
`sheets_item_formula_rows.current`. A runtime-container comparison first proved
that each live validator equaled the committed schema with only this field
removed. The scoped collMod operation changed those two validators only, keeping
strict/error enforcement; a separate subsequent read proved exact equality to
the schemas from `07c8ad36e52451e13fa46167502972909b55d997`.
No business documents or indexes were changed, and no service was restarted.

Operational artifacts are at `/tmp/zeler-catalog-rollout.gE7bNb/` locally and
(check script/schemas) on the VM. `check.py` defaults to read-only; `apply` was
executed once successfully. Do not rerun mutations to obtain status. Rollback
may leave the compatible additive validators in place; never remove the optional
field from a validator while stored documents may contain it.

Separate verified-option Cloud Builds were submitted from the exact connected
repository revision above, with one image per build. Last authoritative status:

| Service | Build ID | Status |
| --- | --- | --- |
| Sheets API | `d517ab72-3560-4917-9da6-594a25426cf4` | SUCCESS |
| Sheets worker | `67e264a7-22f3-489f-9926-dbe7de9aff80` | SUCCESS |

Do not resubmit these builds. Canonical `infra.deploy.provenance_check verify-image`
passed separately for both using full Cloud Build and Artifact Registry provenance,
expected connected repository, commit, project ID and project number. Immutable
digests are:

- API: `sha256:2c2c8bf22f7fbe21fc8253962e53fe5314dfbcf3bedc6f85b1f71f5f17cc311a`.
- Worker: `sha256:5e6a0bae160b005a34efc0f7894de078b442ef99b63b8b0da7734a2ca6a43a18`.

Full evidence and the verified local `image_to_commit.json` are in the temporary
rollout directory above (`*-complete-build.json`, `*-artifact.json`). The subsequent
worker-deployment section records VM proof registration and partial rollout. Final recheck:
GitHub test run `34265791402` and lint run `34265791416` both succeeded.
Deployment remains gated on fresh capacity checks and VM provenance registration.
The newer main commit
only records this operational evidence; it does not require rebuilding these images.

Pre-change health check: API digest `c679a81b…` and worker `65a8dcff…` healthy,
zero restarts, 5,394,870,272 free root bytes. Those images lack the catalog changes.
Capacity is barely above 5 GiB; perform a new preflight before pull and activation,
preserve current/rollback images, and never remove Mongo volumes. Required runtime
verification after rollout: bounded pilot acquisition persists explicit flags,
repeated calculator/dashboard reads agree with them without unnecessary recovery,
and formula calls remain below the Sheets deadline. This does not close the wider
catalog recovery, all-52 HTTP, real-Sheet or minimum-hardening acceptance items.

## Catalog worker deployed — 2026-09-08

Sheets worker now runs verified source `07c8ad36e52451e13fa46167502972909b55d997`,
digest `sha256:5e6a0bae160b005a34efc0f7894de078b442ef99b63b8b0da7734a2ca6a43a18`.
Activation reported healthy, zero restarts and HTTP `/health` 200. API remains on
`sha256:c679a81b7ad3e0b026f8b4a8a4e1ff5bddc1387bcccbf59fc31cb808f70ab56c`;
its new verified image is not pulled/activated yet. Functional pilot verification
of acquired participation and the new API readers remains pending.

Both new image proofs were independently verified in the VM with the canonical
verifier and merged serially into `/var/lib/zeler-platform/image_to_commit.json`.
Both Mongo validators were rechecked compatible before activation. Worker startup
asserted zero running recovery jobs and preserved pilot-only recovery settings.

To make room, only the unused local worker image
`sha256:d4a665c9bf05fc4ee3463ca71b3c10a93cde06a7339250fcea6ca5e4537ff6a3`
was removed after confirming no container referenced it, all four protected
current/rollback images were present, and the exact digest remained in Artifact
Registry. It is recoverable there. No Mongo volume or business data was removed.

Worker pull preflight passed with 5,937,225,728 free bytes. Download completed in
13.6s; Compose was unchanged until activation. After activation free space was
5,394,132,992 bytes, barely over 5 GiB. Recheck and obtain capacity safely before
pulling API; do not relax the floor or remove current/rollback images.

Rollback worker image is `sha256:65a8dcffe3ae125b94c3b50092af3e5fa08abd88921b8fe8ddc8b512940dc623`.
Compose backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-07c8ad3`.
Rollback must replace only the worker image, preserving subsequent API changes.
Scripts/evidence remain in `/tmp/zeler-catalog-rollout.gE7bNb/` locally and on VM;
worker pull and activation are terminal successful operations, not status commands.

## Catalog API deployed — 2026-09-08

Sheets API now also runs source `07c8ad36e52451e13fa46167502972909b55d997`,
digest `sha256:2c2c8bf22f7fbe21fc8253962e53fe5314dfbcf3bedc6f85b1f71f5f17cc311a`.
Activation reported healthy, zero restarts and HTTP `/health` 200. Worker remains
on verified digest `5e6a0bae…` from the same source; this operation did not restart
it. Newer main commits are evidence-only, so no additional image build is needed
for them. This is rollout/health evidence, not acceptance of formula correctness.

The only removed local image was the now-unused older worker digest
`sha256:791e9c90eb9871b1e7573a429e013035ee8a279e064383a4fe77fd1030dfaea7`.
Pre-removal checks proved no container referenced it, current/rollback images
for API and worker were present, and its exact digest remained in Artifact Registry.
It is recoverable there; no volumes, Mongo documents or indexes were removed.

API pull passed the standard dry-run and active preflight with 5,937,004,544 free
bytes, completed in 12.16s, verified the digest locally and left Compose unchanged.
Activation then asserted the disk floor, pilot-only recovery configuration,
zero running recovery jobs and exactly one old image occurrence. It changed only
the API service with `--no-deps --pull never`. Free bytes after health: 5,393,899,520.
The remaining margin is small: continue enforcing the 5 GiB preflight floor.

API rollback image is `sha256:c679a81b7ad3e0b026f8b4a8a4e1ff5bddc1387bcccbf59fc31cb808f70ab56c`;
backup is `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-07c8ad3`.
Rollback must replace only the API image, preserving the deployed worker.
`cleanup-api.py remove`, `pull-api.py` and `activate-api.py` in the rollout directory
are completed mutations, not status commands; do not repeat them for observation.

Next: bounded pilot acquisition and subsequent Mongo-backed formula reads, then
authenticated production formula HTTP and a real authorized Sheet/app session.
The real Sheet URL and legitimately linked user identity were requested again;
no credentials/tokens were requested or bypassed. Wider catalog recovery,
coverage/freshness and minimum-hardening acceptance items remain open.

## Catalog participation pilot recovered — 2026-09-08

The deployed API/worker recovered explicit participation for 20 pilot publications
through the existing item queue, then CALCULADORA reused the persisted result.
Selection was 20 sorted owned product-linked publications from the recorded
inventory IDs, not a new full-inventory scan or a claim of fresh global membership.

Receipt: `/var/lib/zeler-platform/repairs/catalog-participation-07c8ad3.json`
(created exclusively with mode 0600). Script:
`/tmp/zeler-catalog-rollout.gE7bNb/pilot.py` locally and on VM. `prepare` was
executed once; the job is terminal completed. Use `status` only for observation.

| Observation | Evidence |
| --- | --- |
| Before recovery | All 20 stored flags unknown; selected CALCULADORA unavailable in 0.0131s; one bounded 20-item job queued through the API recovery helper |
| Worker outcome | Completed on attempt 1, no failure reason |
| Stored participation | 1 true, 19 false, 0 unknown |
| First subsequent read | 23 rows, 0 partial misses, 0 unavailable cells/cost cells, 23 numeric prices, 0.0197s |
| Independent repeated read | Same counts; 0.0231s; no recovery needed |
| Classification | 1 CATALOGO row, 22 REGULAR rows including variants; all agree with canonical items |
| Coverage safety | Global read-model markers unchanged throughout |

The first successful observation was 51.39s after receipt creation and the second
76.49s; these are observation ages, not measured worker execution duration.
No new queue request, timestamp relabeling or coverage-marker rewrite was needed
for the second read. These are point-in-time selected-publication results, not
proof of perpetual freshness or all 52 formulas.

This is real production VM/container, worker, gateway acquisition and Mongo-backed
dispatcher evidence. It is **not authenticated formula HTTP or a real Google Sheet**:
the operator helper invoked the deployed dispatcher/recovery helper directly and
did not mint or bypass user credentials. Those acceptance checks remain open.
Catalog snapshot recovery and current snapshot membership are still unimplemented
in the automatic recovery worker; they must be completed before catalog acceptance.

## Baseline — 2026-09-07

- Backend main: `c5a2e097e765a083fa1fff7fdec3782ef81fd998`.
- GitHub and GCP access verified; platform-vm RUNNING.
- Docker lists gateway, Sheets API/worker and Mongo as healthy. Root disk has
  7.5 GiB free. Health does not prove formula data readiness.
- Runtime read-only command, inside the Sheets worker:
  `/app/.venv/bin/python -m infra.operations.zelerdata_read_model_status
  --seller-id 82453304 --confirm-approved-runtime --readiness`.
- Command returned degraded (exit 1): 7 missing, 9 reconciled, 1 stale;
  all 17 inventory entries fail its current productive-window check.
  Orders/questions coverage ends in July, multiple snapshots in June;
  devoluciones is stale with source `devoluciones_operation_acquire`.
  This is marker evidence, not proof that underlying collections are empty.
- Formula API currently returns DATA_UNAVAILABLE without scheduling recovery
  (`modules/sheets/src/zeler_sheets/api.py`, `_execute_formula_payload`).
- Full baseline pytest completed with exit 0. Several integration checks were
  skipped because local Mongo is not the expected rs0-dev replica set; baseline
  success does not prove Mongo integration. Session handle 72403 is terminal.

## Work unit: complete item, SKU and order reads

- Found silent default truncation: item/SKU readers returned only 500 rows and
  order reads only 1,000, potentially understating formula output and totals.
- Added three boundary regression scenarios: 501 item rows, 501 SKU rows,
  1,001 orders. All failed against the original defaults with observed counts
  500, 500, 1,000 respectively.
- Default reads now consume the complete seller/request-filtered cursor.
  Explicit caller limits remain supported; other explicit and default caps
  still require audit, so this does not close the global completeness gate.
- Focused repository/core/order/calculator tests: 109 passed in 0.32s.
  Ruff check/format and focused mypy pass.
- Production validation pending: larger results must be measured for memory,
  response size and the end-to-end 30-second deadline before release.
- Runtime harness: dedicated local Mongo 7 replica set, loopback port 27028,
  container `zeler-goal-mongo`. Real Motor cursor reads return all 501/501/1,001
  rows and exclude a second seller; 1 integration test passed. Random test DB
  is removed by the test after use, never using production configuration.
- Mongo/schema/drift/formula subset with dedicated local connection:
  46 passed in 2.51s (no skips).
- Rollback boundary: the three default limits in formulas/read_models.py and
  their boundary tests; no schema or persisted-data changes.

## Remaining baseline quality findings

- Root Ruff check passes. Root format check flags the existing
  tests/integration/test_stock_time_forward_execution_rs0.py.
- Root mypy found pre-existing errors in stock-time schema tests (2),
  source-gated writer tests (3), reconciliation quota counter typing (1), and
  quota advance test re-export (1). New Mongo test client annotation fixed.
- Runtime Sheets API digest: cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc.
- Runtime Sheets worker digest: b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931.
- No loaded zelerdata systemd units were listed; this alone does not exclude a
  live manual reconciliation process. Source provenance still needs resolving.

## Next evidence/actions

1. Finish baseline checks and inspect deployed image/source bindings.
2. Inspect actual marker aliases (inventory uses sheets_item_formula_rows,
   formula readers use item_formula_rows) before inferring missing data.
3. Inspect active reconciliation processes before any overlapping repair:
   recent devoluciones acquire could represent another running operation.
4. Implement recovery with failing behavioral tests first, reuse existing
   reconciliation and keep the formula path independent of remote API latency.
5. Continue every acceptance item above; a passing narrow test is not closure.

## Work unit: durable recovery request boundary

- Missing-model exceptions now carry structured model and normalized range.
  Three new scenarios failed first, then passed after adding the metadata.
- Mongo-backed recovery queue coalesces exact seller/model/range requests with
  deterministic IDs, claims jobs atomically, renews leases, fences completions
  from expired attempts and applies a 15-minute terminal cooldown.
- Real Mongo tests verify 20 concurrent requests coalesce, seller separation,
  exclusive claims, expired-attempt fencing and cooldown rescheduling.
- API can use an injected queue only after token/seller validation. Enqueue is
  capped at one second; response remains DATA_UNAVAILABLE with an explicit
  update-requested message. The authorization/API regression failed before
  wiring and passed afterwards.
- 73 focused API, recovery, model and handler tests passed in 1.35s. Focused
  Ruff and mypy pass.
- NOT production-enabled: worker execution, indexes/schema, retry/queue limits,
  full model coverage, startup wiring and end-to-end recovery remain pending.
  No success claim for automatic data recovery until the executor proves it.
- Next reuse point: historical_meli_backfill currently always fetches orders,
  even for questions/catalog; broad reconciliation also acquires a devoluciones
  lease. Avoid blindly invoking that broad path for each missing model.
- Rollback boundary: new recovery module and tests, optional API scheduling
  helper, and exception metadata. No production schema/data changes occurred.

## Work unit: question recovery executor

- Added bounded question scan/detail recovery through gateway clients, reusing
  SheetsEventPersistence for normalized writes. Search and detail clients can
  retain their existing distinct module identities.
- Tests first demonstrated missing execution, false coverage with extra local
  rows, rejection of a valid reused scan cursor, and acceptance of expired
  proof. Each corresponding correction now passes.
- Executor verifies remote total/unique identities, date and seller scope,
  required answer detail, and exact persisted inventory before publication.
  Marker publication and job completion share a Mongo transaction guarded by
  the current lease token. Explicit proof expiry now blocks reconciled reads.
- Real-Mongo recovery + reader + HTTP tests: 44 passed in 1.82s; focused mypy
  and Ruff pass. Gateway calls are controlled doubles in these tests.
- Live read-only verification from approved worker container: scan returned
  total 252, first and second pages 50 each, scroll available. Detail retrieved
  with the existing sheets identity had matching seller/question scope and
  a creation date. No production data was written.
- A prior wider diagnostic ended with HTTPStatusError without a captured
  status; it is not evidence of complete live recovery. Narrow subsequent scan
  and detail checks succeeded. Full date-window counts remain unverified.
- Still pending: other recovery sources, startup wiring, schemas/indexes,
  bounded retries/queue admission, deletion lifecycle and deployment. Do not
  deploy the executor as full ZelerData recovery yet.
- Rollback boundary: recovery_worker.py, its tests and optional valid_until
  enforcement in read_models.py. No production write or deployment occurred.

## Work unit: bounded formula HTTP execution

- Individual and batch endpoints now share a 20-second overall async deadline,
  covering token validation, data reads and execution; batch uses one budget
  for the whole batch. Timeout cancels work and returns retryable INTERNAL/503.
- Tests with a nonterminating handler first failed at the test watchdog and
  now prove cancellation and a stable response for both endpoints.
- Shared payload execution removes duplicated argument wiring between routes.
- Formula API tests: 30 passed in 0.62s; focused Ruff/mypy pass.
- This does not prove the end-to-end 30-second limit: synchronous CPU work,
  JSON serialization, network and Apps Script overhead still need live timing.
- Rollback boundary: deadline constant, two route wrappers/shared execution
  closure, timeout response and the two timeout tests. No data migration.

## Baseline quality corrections

- Corrected mixed-type proof annotations, schema fixture typing, optional
  immutable mapping assertions, canonical readback import and formatting.
- Root Ruff check and format now pass; mypy passes for all 500 source files.
- Focused affected tests: 38 passed in 0.31s. Runtime behavior is unchanged:
  corrections are typing/test expectations/formatting only.
- Full regression is running against the dedicated local Mongo replica set;
  record terminal result before treating the overall gates as satisfied.

## Work unit: real-Mongo regression corrections

- First full replica-set regression: 3,578 passed, 3 failed, 9 skipped in
  66.73s. A separate invocation overriding pytest addopts failed collection
  because it removed the repository's required importlib mode; it is not a
  product defect. Subsequent runs preserve repository options.
- Reproduced all three failures in isolation. The proxy test seeded a limit
  of 60 while runtime defaults to 600; it now explicitly selects its test
  limit. The quarantine assertion now requests timezone-aware BSON decoding.
- Actual recovery defect: prepared-window replay compared naive BSON UTC to
  aware domain dates; read-next also rejected default Mongo decoding. Normalize
  only database-read dates, keeping timezone validation on domain inputs.
- Existing failing transaction test now proves replay, resume and obsolete
  owner rejection against actual Mongo. Focused suite: 13 passed in 0.74s;
  root Ruff, formatting and mypy remain clean (500 source files).
- Rollback boundaries: recovery date decoding is independent of the two test
  fixture corrections. No production data or deployment changed.
- The first rerun was invalidated by the dedicated local Mongo exhausting its
  default file-descriptor limit (WiredTiger error 24), not a disk-space or
  production failure. Preserved its volumes and stopped container as
  `zeler-goal-mongo-low-ulimit`; replacement `zeler-goal-mongo` shares those
  volumes with explicit `nofile=65536:65536`. Never run both concurrently.
- The eight protected stock-time transaction tests require `MONGO_URI` absent
  and a loopback `ZELER_RS0_TEST_URI`. With the repaired local replica set:
  all 8 passed in 3.55s. The normal root invocation skips them by design.
- Final full regression after fixture/decoding corrections and local Mongo
  repair: **3,581 passed, 9 skipped in 66.62s**. Eight skips are covered by the
  separate successful protected invocation; the remaining Caddy parameter has
  no required keys. Existing asyncio/anyio deprecation warnings remain (348).
  Root Ruff check, format check and mypy also exit zero.
- Next functional work remains recovery admission/retries, source coverage and
  worker/API startup integration. These green gates do not prove production
  recovery, 52 live formulas, app surfaces or a real Google Sheet.

## Work unit: bounded automatic recovery retries

- Two new real-Mongo tests failed before implementation: transient gateway
  failures required another formula request, and repeated worker crashes had
  unlimited attempts. Both are now corrected.
- Retry connection/timeouts, HTTP 429/5xx and database failures with persisted
  30/60-second backoff and at most three claims per request cycle. Expired
  third attempts become failed; obsolete owners retain no completion rights.
- Non-transient source rejections and incomplete source inventories fail closed.
  Failure reasons are allowlisted codes, not exception text or remote payloads;
  successful transactional completion clears the prior failure reason.
- Verification: recovery and formula API tests **43 passed in 2.69s**, using
  actual local Mongo and controlled upstream responses. Includes 403 versus
  429/503 retry behavior, automatic resume, coalescing and lease fences.
- Runtime activation remains pending; this changes persisted queue execution
  behavior but does not yet connect the API/worker startup. Rollback boundary:
  retry/attempt logic in recovery.py, worker error classification and associated
  tests; no production migrations or deployments have occurred.

## Work unit: connect formula recovery to API and worker lifecycles

- `ZELERDATA_FORMULA_RECOVERY_ENABLED` enables the API queue and co-resident
  worker executor; default is disabled. Runtime queues accept/claim only
  implemented sources (currently questions), so unsupported orders/catalog
  cannot falsely report that a working recovery was requested.
- Reuses the existing poller supervisor with concurrent sync/recovery lifecycle
  management and a dedicated recovery health component. Search uses bootstrap
  identity; details reuse the worker's sheets gateway client. Startup ensures
  claim and expired-lease indexes, without adding a new service.
- New integration tests initially failed for absent startup/lifecycle wiring.
  Full authenticated HTTP -> durable Mongo queue -> supervised recovery -> HTTP
  integration exposed BSON precision loss: the recovered range failed to cover
  its original microsecond endpoint. Recovery intervals now round outward to
  BSON milliseconds. The next HTTP request succeeds after persisted proof, and
  the first HTTP request makes zero gateway calls.
- The real gateway raises its own GatewayRateLimitError for HTTP 429, unlike
  the earlier generic HTTP double; added a failing regression then included it
  in bounded transient retry handling.
- Focused recovery, HTTP and worker lifecycle tests: 51 passed in 3.48s;
  root Ruff, formatting and mypy pass. Full local replica-set regression:
  **3,590 passed, 9 skipped in 76.67s**; the same protected stock-time tests
  require their separate invocation, and Caddy has no required-key parameter.
- No production activation yet. Queue admission/schema, write fencing across
  competing recovery intervals/events, remaining sources and productive/live
  acceptance remain necessary before activating recovery as the full solution.
- Rollback boundary: activation flag plumbing, optional extra pollers, queue
  index/source selection, BSON interval rounding and corresponding tests. No
  production configuration/data migration has occurred.

## Work unit: atomic, fenced question recovery writes

- Real-Mongo regressions demonstrated rows persisting after lease expiry and
  partial rows after a later resource failed validation. Previously only the
  final marker/job state shared a transaction; data writes were outside it.
- Normalized question persistence now accepts an explicit session (rejected for
  other event types). Recovery acquires data outside the transaction, then
  commits every row, inventory readback, coverage and job completion together
  under the current attempt's lease. Failures roll back the complete unit.
- A separate regression demonstrated overwriting a coverage marker changed
  during acquisition. Compare the marker captured before remote acquisition
  inside the transaction; competing publication aborts without touching rows
  or the newer marker. Existing question freshness rules still apply.
- Verification: recovery, event-persistence and formula API tests **111 passed
  in 4.02s**, with three new failure scenarios reproduced before correction.
  Root Ruff, formatting and mypy remain clean. Production remains unchanged.
- Rollback boundary: optional question-only session propagation, recovery
  transaction scope/preimage guard and associated tests. Remaining admission,
  schemas, source expansion and live acceptance are not proven by this unit.

## Work unit: complete question and unit-cost reads

- Extended the real-Mongo boundary harness: questions stopped at 1,000 of
  1,001 stored rows; after correcting that, the 1,001st valid unit cost still
  resolved to NA solely because its source query stopped at 1,000 documents.
- Removed default truncation for find_questions and find_unit_costs; explicit
  limits remain an opt-in repository capability. Questions/KPI callers request
  complete ranges and cost callers can resolve all matching persisted costs.
- Harness proves seller isolation, an actual PREGUNTASKPI result of 1,001,
  and resolution of every one of 1,001 valid unit costs, not only list lengths.
- Verification: Mongo boundary, read-model, order/question handler and unit
  cost tests **74 passed in 0.75s**; root Ruff/format/mypy clean. No deployment.
- Remaining fixed/heuristic limits in catalog/history/other handlers still need
  review; this is not proof that all 52 formulas are complete. Large-input CPU,
  memory and live end-to-end response timing also remain unverified.
- Rollback boundary: the two reader default limits and the expanded Mongo
  boundary harness. No persistence schema or production data changed.

## Work unit: complete history rows and catalog sales inputs

- Six formula boundary tests first returned 1,000 of 1,001 rows: stockout
  duration, active-stock time, weekly stock, price history, catalog time and
  withdrawals. Their full-range calls now request all rows; five corresponding
  reader defaults no longer silently cap results. Seller/interval/coverage
  filters remain unchanged.
- Extended the actual local Mongo boundary harness for all five collections,
  including foreign-seller rows, to check more than test-double behavior.
- Catalog sales previously truncated at 5,000 orders. A failing 5,001-order
  case demonstrated undercounting in all six sales windows; that query now
  reads the complete requested range.
- Verification: Mongo boundary, remaining-formula, item/shipping/catalog and
  reader tests **63 passed in 5.09s**. Ruff, formatting and mypy pass globally.
- Other explicit item/shipping/catalog heuristics and source completeness
  guards still require inspection; this is not all-formula/live acceptance.
  Large-result latency/memory measurement remains pending.
- Rollback boundary: seven complete-range caller limits, five reader defaults
  and associated boundary regressions. No production state changed.

## Work unit: complete shipping and catalog snapshot queries

- Five boundary scenarios failed first: three catalog outputs returned only
  1,000 of 1,001 snapshots; seller shipping cost excluded the latest order after
  5,000 earlier ones and returned an old cost; Mercado Envios omitted that
  latest open label. These full-input queries now use no silent row cap.
- Catalog product/buybox reader defaults are complete; extended actual Mongo
  boundary checks for both collections and foreign-seller exclusion.
- Verification: Mongo boundaries, item/shipping/catalog, remaining formulas and
  reader tests **68 passed in 0.76s**. Root Ruff, format and mypy pass.
- This preserves the existing latest-cost, status/date and seller semantics;
  it does not prove productive source coverage or large-input response timing.
  Remaining heuristic SKU/item joins and catalog buybox enrichment are pending.
- Rollback boundary: five handler limit arguments, two reader defaults and
  their boundary tests. No production data or deployment changed.

## Work unit: complete SKU and buybox joins

- Actual Mongo test demonstrated sales and dashboard SKU resolvers both
  returning an empty SKU for a stored variation beyond their 500-row heuristic.
  They now read every seller/item-matching index row; ambiguity rules remain.
- Catalog's buybox join returned NA for stored winner data when 1,000 unrelated
  snapshots sorted first. Reused the exact-output catalog regression with that
  additional inventory; it failed before removal of the heuristic and passes
  afterwards, preserving all winner/price/competitor fields.
- Verification: Mongo boundary, core, order/question and remaining-formula
  tests **134 passed in 1.20s**. Ruff, format and mypy pass globally.
- Rollback boundary: three heuristic limit arguments and their regressions.
  No runtime activation, production data change or live-completeness claim.

## Work unit: preserve order partial-content evidence through gateway

- Official source checked: https://developers.mercadolibre.com.mx/gestiona-ventas
  (indexed text available; direct fetch returned 403). The late-September 2026
  deprecation notice concerns the current order-shipment view; do not interpret
  it as proof that every /orders endpoint is being retired. Hosted shipment
  responses are arrays. Order partial responses use HTTP 206 and
  X-Content-Missing to identify absent fields.
- Current proxy already forwards X-Api-Version/X-New-Domain request headers,
  but stripped X-Content-Missing on responses. New authenticated integration
  test reproduced the missing header; explicitly forward it while keeping
  unrelated response headers excluded. Status and JSON body remain unchanged.
- Verification: gateway-flow and client tests **17 passed in 3.50s** using local
  Mongo and mocked upstream; root Ruff, format and mypy pass.
- Important remaining gap: fetch_resource returns only JSON, so Sheets source
  acquisition still needs explicit partial-content/field-completeness handling.
  No hosted order-shipment acquisition/normalization was found in Sheets. Do
  not mark the new-order-contract requirement verified from this transport fix.
- Rollback boundary: one response header and its authenticated regression.
  Gateway image must eventually be rebuilt/deployed alongside relevant Sheets
  images; no image build, deployment or live contract test happened in this unit.

## Work unit: preserve known identities during sparse order updates

- A regression with an existing order and a newer response containing empty
  buyer/shipping objects failed before saving the new status: buyer identity
  validation ran without consulting known Mongo state.
- Read the same seller/order inside the existing fenced transaction before
  canonical normalization. Missing/empty objects can reuse observed buyer and
  shipment identifiers; explicit null shipping and no_shipping do not revive
  a previous shipment. Existing monotonic write checks and SKU refresh remain.
- No unknown buyer ID is fabricated for a new partial order. Such orders still
  require field-aware recovery; this fix is not complete 206 handling and does
  not establish completeness of any order interval.
- Verification: persistence, historical backfill and recovery tests **120 passed
  in 4.15s**, including actual Mongo transactional fallback, explicit-clear and
  no-shipping controls. Ruff, format and mypy pass globally.
- Rollback boundary: transaction-local identity fallback, checkpoint timestamp
  normalization and associated tests. No schema change or production mutation.

## Runtime release — 2026-09-07, source 35bed8c

- Root regression with local Mongo: **3,611 passed, 9 skipped in 70.99s**.
  Eight protected replica-set scenarios were then run with their explicit local
  URI and no ambient MONGO_URI: **8 passed in 3.55s**. The remaining skip is
  the Caddy service's empty required-key case. Ruff, format (500 files) and
  mypy (500 source files) pass. Deprecation warnings remain.
- Published exact source commit
  `35bed8c8fea1bbaef9bd481f36709dd0128e3e9a` to GitHub main.
  Built only gateway, sheets-api and sheets-worker, one verified Cloud Build
  per image, from the connected repository at that revision; no local image
  build or upload of the dirty checkout.
- All three builds succeeded. The repository provenance verifier confirmed
  each image's digest, successful build, exact source revision and connected
  repository. Build IDs and immutable image digests:

| Service | Cloud Build ID | Image digest |
| --- | --- | --- |
| gateway | 55f419ff-9898-4fc2-af29-2d30af1a70ce | sha256:2d4a514cab2d3ddca7e95109aeedc1e11e41115f8c09fddedd850aa0dc9ef130 |
| sheets-api | 277bbd50-5a8e-48cb-a8d4-917f9f320fbf | sha256:b03d53422a57202974f77e70d651731ca01317aa7d3e7448d4592c71364defaf |
| sheets-worker | 647379f2-4a81-41a5-8d04-86d5b3796316 | sha256:ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646 |

- Image repository prefix:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`.
  Each service was replaced individually with `up -d --no-deps`, after
  free-space preflight and an exact-one Compose image replacement assertion.
  Preflight free space was 7.5 / 7.1 / 6.6 GiB before the successive pulls.
- Rollback authority is each previous running image, not a moving tag:
  gateway `sha256:2e06dd93345e5b3f2cb3f6385e74c5227d3a41fd785de908c06d31402d3c8a68`;
  sheets-api `sha256:cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc`;
  sheets-worker `sha256:b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931`.
  Compose backups remain at
  `/opt/zeler-platform/docker-compose.yml.pre-<service>-35bed8c`.
  Revert only the affected service image using the section 5 runbook, then
  prove its running digest, health and relevant smoke. No Mongo volumes or
  unrelated product services were altered by deployment commands.
- Gateway initially returned HTTP 502 during startup, then became healthy
  with zero restarts and HTTPS health 200. A real authenticated, read-only
  questions scan through the new gateway returned HTTP 200, 50 rows,
  total 252 and a scroll cursor; no question contents or credentials emitted.
- Sheets API became healthy with zero restarts. HTTPS health returns 200;
  Mongo, RabbitMQ, registry and claims-DLQ checks all pass. Live inventory is
  HTTP 200 with 52 implemented formulas. Inventory is not execution proof.
  Recovery flag remains disabled. No smoke credential is configured in the
  API container; authenticated all-formula execution remains unproven.
- Final runtime inspection: all three running digests equal the verified
  images above, all containers healthy, all restart counters zero. The worker
  health endpoint reports ready, RabbitMQ ok and sync_jobs_poller ok; recovery
  is also disabled in the worker. Root disk has 6.1 GiB free after deployment.
- Read-only readiness check inside the new worker remains degraded:
  7 missing, 9 reconciled, 1 stale; 17 productive-window blockers. No missing
  data was repaired merely by deploying code. This release proves image
  correspondence and basic operational boundaries, not global data readiness,
  complete formula execution, new-order migration or the 30-second SLA.
- Next: complete field-aware order acquisition and asynchronous persistent
  recovery, then verify the pilot window and authenticated formula results.
  The final Google Sheet, existing app surfaces and minimum sensitive-data
  controls remain mandatory. A documentation-only follow-up commit does not
  require rebuilding these images; future runtime changes do.

## Work unit: do not stop order acquisition at a short page

- Three new regressions initially failed: a short first page silently returned
  one order while the source total was two; an empty subsequent page and a
  repeated identity were never inspected. Two further regressions proved a
  changed or disappearing total could also be accepted as complete.
- Order acquisition now advances by the received row count, continues short
  pages when the source total requires more rows, and rejects premature empty
  pages, missing/repeated identities and changes to a previously observed total.
  Explicit max_orders remains an operator cap, not proof of full coverage.
  Sources without total metadata still need a separate completeness contract.
- Verification: historical backfill, event persistence and recovery tests
  **125 passed in 4.22s**; root Ruff, format and mypy pass. The five new
  pagination scenarios use an injected source, not production fault injection.
- Runtime boundary evidence: from the approved worker container, a read-only
  gateway search for the pilot and Aug 8–Sep 6 returned HTTP 200, one requested
  row and total 100. One corresponding order detail returned HTTP 200, no
  X-Content-Missing header, and present buyer/seller/shipping/items/payments/
  created/updated fields. Output contained only status, counts and presence
  booleans. This is not complete interval or HTTP 206 acceptance evidence.
- Rollback boundary: _search_orders pagination/completeness checks and their
  tests; no schema or persisted-data migration. The new code is not deployed.
  Both Sheets images include this module and will need new Cloud Build images
  before productive acceptance of this correction; gateway has no new change.
  Verify complete pilot acquisition and truthful unavailable results after
  that deployment. Field-aware partial detail recovery remains unfinished.

## Work unit: enforce expiration in generic formula freshness checks

- Generic productive-model checks accepted expired or malformed valid_until
  values whenever fresh_until covered the requested end. Four new regressions
  failed for fresh/reconciled markers; two valid-proof controls already passed.
- The generic gate now rejects expired/malformed explicit validity, matching
  the existing reconciled-range gate. Existing markers without valid_until
  are unchanged; migrating those proofs and guarding all order consumers
  remain separate incomplete requirements.
- Verification: repository, item/shipping/catalog, remaining-formula and
  calculator tests plus the actual Mongo boundary harness **82 passed in
  0.94s**. Mongo demonstrates BSON-decoded expired proof rejection followed
  by acceptance after valid renewal in a disposable local test database.
  Root Ruff, format and mypy pass.
- Rollback boundary: four-line validity check and associated regressions;
  no production data writes or schema migration. Not deployed: Sheets API
  needs a new Cloud Build image and live expired/valid proof acceptance after
  this change. Keep it with the pending Sheets release; gateway is unchanged.

## Pilot data comparison — approved runtime, read-only

- Gateway pagination returned 100 unique order IDs in the requested Aug 8–
  Sep 6 range with a stable total. All 100 are present in seller-scoped Mongo;
  the Mongo date-window count is also 100. None of those persisted orders
  lack buyer_id, nonempty items or last_updated. Their 97 unique shipment
  references all resolve in the seller-scoped shipments collection.
- These results contradict an assumption that the degraded status report
  implies absent orders or shipments. Its 17 productive-window blockers are
  marker evidence, not 17 proven underlying data defects. Actual order values,
  shipment fields and the formula-specific date/freshness contracts must be
  checked before repairing or certifying coverage.
- A paced, read-only comparison fetched all 100 order details through the
  gateway, then compared the current canonical projection against Mongo.
  All normalized successfully without partial-content responses. 51 matched
  exactly; 49 differed by list comparison. Differences were confined to tags
  (49) and last_updated (4). Buyer/shipment/pack identifiers, status, creation
  and closing dates, amounts, normalized items and feedback matched in all
  compared documents. Acquisition-only sale_fee_synced_at was excluded;
  list ordering was not normalized. This is not proof that all 49 differences
  are business-value changes, nor proof of new-order-contract completeness.
- A separate search-result tag comparison over the same 100 orders found
  99 identical lists and one changed set: delivered replaced not_delivered.
  Search and detail responses therefore must not be treated interchangeably
  when explaining these differences. No stored order or marker was modified.
- A bounded follow-up of 10 actual detail responses compared tags as sets:
  9 differed only in ordering, 1 had different tag values. Do not report the
  earlier 49 list differences as 49 business-data defects. Future complete
  reconciliation comparisons must normalize set-valued tags; the four
  updated timestamps and any substantive tag drift still need recovery.

## Work unit: retain question coverage through source revalidation

- Approved-runtime preflight found no recovery jobs and automatic recovery
  disabled. The current questions marker is reconciled from June 1 through
  July 11, without an explicit expiration. Recovering only Aug 8–Sep 6 would
  replace that marker and remove previously recognized historical coverage.
  No production job or data write was started during this preflight.
- A new actual-Mongo regression failed: recovery fetched only the August
  question, omitting June and the July gap. The worker now expands acquisition
  to the union of a still-valid prior reconciled interval and the requested
  interval, fetching details throughout the gap as well. Coverage is published
  only after full source acquisition and the existing atomic readback checks.
- The reverse-direction regression also passes: an older query cannot erase
  a newer proven interval. Expired/invalid prior proofs are not promoted by
  this extension. Existing 10,000-source-question and 240-second execution
  bounds remain; preserving a wider interval may require more source calls
  than the requested range. Source failure leaves the prior proof untouched.
- Verification: recovery and read-model suites **36 passed in 4.47s**, with
  real Mongo transactions and mocked MercadoLibre source responses. Root
  Ruff, format and mypy pass. No schema change or extra coverage store.
- Rollback boundary: prior-range acquisition expansion and its bidirectional
  regressions. Not deployed. Build the pending Sheets API/worker release from
  its exact main commit, then run one controlled pilot recovery with automatic
  recovery still disabled, and prove completion, persisted values and a second
  formula query without source calls. Automatic admission controls and the
  other recovery models remain unfinished; this is not global activation.

## Runtime release and first controlled recovery — source 4f65d6d

- Regression: 3,624 passed, 9 skipped in 70.84s; protected replica-set suite
  separately 8 passed in 14.87s. Root Ruff, format and mypy pass.
- Verified Cloud Build source: 4f65d6db950f00e97127ffc546dfb7506ced57ec.
  API build 45e06398-5e7d-4ebd-a31f-dab8db79c57f produced
  sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f;
  worker build e0a08c5b-9cd0-463e-a018-76e25f8bddb3 produced
  sha256:9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5.
  Both passed digest/build/source/connected-repository provenance checks.
- Both running digests now match these images; both healthy, zero restarts.
  API HTTPS health returned 200/ready. Targeted replacements used the runbook
  preflight and exact-one-image checks. Disk free after release: 5.1 GiB;
  recheck before further pulls. No other product was deployed.
- Rollback API digest: b03d53422a57202974f77e70d651731ca01317aa7d3e7448d4592c71364defaf;
  rollback worker digest: ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646.
  Compose backups use suffix .pre-<service>-4f65d6d. Images use the same
  Artifact Registry service repositories recorded above.
- One controlled recovery job was persisted for pilot questions, Aug 8–Sep 6:
  ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d.
  Automatic recovery remains off. It failed source_incomplete after five
  search calls and one detail, 1.281 seconds; no completion was published.
  The existing June 1–July 11 reconciled marker remained unchanged.
- Read-only diagnosis identified matching question/seller identities, valid
  answer/schema, but search/detail creation times differed by 435 microseconds
  within the same BSON millisecond. Exact datetime equality rejected the row.

## Work unit: compare question timestamps at persistent precision

- New actual-Mongo regression reproduced the 435-microsecond failure; exact
  timestamps passed, and a different-millisecond control remained rejected.
- Recovery source dates now normalize to UTC BSON milliseconds, consistent
  with persistent request boundaries. Seller/identity checks and validation
  of explicit timezone remain intact. This is not a general time tolerance.
- Recovery/read-model suites: 38 passed in 4.30s. Ruff, format and mypy pass.
  Test Mongo had stopped during the environment transition; only the task-owned
  current container was restarted, not the old container sharing its data.
- Rollback boundary: source-date millisecond normalization and its regression.
  Worker rebuild and controlled retry still required for live acceptance.
  The failed durable job must not be confused with successful persistence or
  authenticated HTTP/Google Sheets formula verification.

## Corrected worker release — source 0b83408

- Cloud Build 3b766f92-da1d-48ca-ba90-125a32b03e4b succeeded from exact
  source 0b8340864946ab5dfef9c5c11319fcec095e627f. Provenance verifier
  confirmed the connected repository, build, revision and immutable digest
  sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee.
- Only sheets-worker was replaced, after preflight at 5.1 GiB free and an
  exact-one Compose replacement. Running digest matches, container healthy,
  zero restarts, worker health ready; automatic recovery remains disabled.
  Rollback image is the prior worker digest 9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5;
  backup suffix .pre-sheets-worker-0b83408. The API remains on its verified
  4f65d6d image; this correction changes only worker-executed code.
- Post-pull disk free is 4.6 GiB. Restore the 5 GiB preflight margin before
  another pull; no further image build is implied by this operational record.
- Browser-use is installed but the CLI differs from the skill's current
  syntax: it exposes --connect, not a connect subcommand. An isolated
  zeler-goal session using --connect could not find Chrome remote debugging.
  Asked the user whether to enable their Chrome debugging or select a profile
  for managed Chromium. No cookies/credentials were extracted and no UI or
  real Google Sheet acceptance is claimed from this diagnostic.
- Removed only the unused local copy of original Sheets worker digest
  b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931 after
  confirming no container referenced it. It remains recoverable from Artifact
  Registry. Recent rollback images and all volumes were retained. Free disk
  returned to 5.1 GiB.
- Retried the same job only after its cooldown elapsed. It fetched six search
  pages and 50 details, then failed source_incomplete in 15.275 seconds.
  A read-only diagnostic stopped before transaction creation and confirmed
  all 50 source details normalize successfully, but Mongo has 52 rows in the
  expanded interval. The marker remained unchanged; no recovery completion.
- Direct detail checks of the two extra numeric question IDs returned HTTP
  200, matching question identities and dates, but explicit nonempty numeric
  seller IDs different from the pilot. Both are ANSWERED. This confirms two
  misattributed question records, not missing API data. Do not drop the scope
  check or silently accept these records to make recovery pass.

## Work unit: reject explicit foreign ownership during question persistence

- A new regression reproduced the write boundary flaw: a resource naming a
  different seller was normalized under the caller's seller without rejection.
- Canonical question normalization now rejects an explicit source seller that
  differs from the requested seller, before any question or marker write.
  Historical callers omitting seller_id remain supported; this does not prove
  ownership for absent-source-owner payloads or close the broader isolation
  audit for other resources.
- Event persistence, historical backfill and real-Mongo recovery tests:
  130 passed in 4.28s.
  Root Ruff, format and mypy pass.
- Rollback boundary: explicit question-owner validation and its regression.
  Worker deployment and backed-up repair of exactly the two confirmed foreign
  rows remain required. No reassignment to another user/account is authorized
  by this repair, and no production row has yet been removed.

## Verified question recovery and ownership repair — source abf84b4

The controlled pilot question recovery now completes, and all 50 persisted
documents match fresh canonical Mercado Libre details. This proves the question
recovery path only; automatic recovery remains disabled and global acceptance
items above remain open.

- Cloud Build `4aa66e34-b70b-4244-965a-4d9ebace97fa` succeeded from exact
  source `abf84b4b00912f16beb5aeae13fd49f7c655abf0`. The provenance verifier
  matched connected repository, revision, build and worker digest
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`.
  Only sheets-worker was replaced. Running digest matches; healthy, zero
  restarts, internal health HTTP 200/ready. API remains on source 4f65d6d.
- Before replacement, exactly two complete original foreign-question rows and
  source ownership proofs were backed up inside the VM at
  `/var/lib/zeler-platform/repairs/question-owner-abf84b4.bson` (root, mode
  0600, parent 0700). No payload or foreign identity left the runtime. This
  restricted backup is not evidence of application-level encryption; account
  for it and its container copy in the final retention/deletion hardening.
- Fresh source detail checks reconfirmed both foreign owners and matching IDs
  and dates. A Mongo transaction compared both full rows against the backup
  before deleting exactly those two pilot-scoped rows. Neither falls inside
  the previously validated June 1–July 11 coverage; the prior marker was
  compared and retained unchanged. Expanded-interval inventory became 50.
  No record was reassigned to another seller. Removal is recoverable from the
  restricted backup, but restoration would require a separately justified,
  ownership-aware repair, not blindly reinserting the misattributed records.
- The same job `ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d`
  was retried after its cooldown, with no other pending/running recovery job.
  Six search calls and 50 detail calls completed in 8.281 seconds. Transactional
  publication recorded 50 questions and coverage June 1–September 7 exclusive;
  exact persisted/source identity sets match. Proof expires after 15 minutes;
  this successful run is not a promise of indefinitely fresh coverage.
- Two subsequent internal PREGUNTASKPI queries for August 8–September 6 read
  Mongo and returned 3 questions, in 0.0171s and 0.0040s. Recovery-client call
  counters did not increase. These are operator diagnostics, not authenticated
  HTTP/Google Sheets acceptance or a measured end-to-end p95.
- An independent read-only pass fetched all 50 details again and compared
  BSON-normalized canonical documents with Mongo: 50 exact matches, no field
  differences, all source sellers match the pilot.
- Rollback worker digest is
  `sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee`;
  Compose backup suffix `.pre-sheets-worker-abf84b4`. A code rollback does not
  restore removed data. Disk free after pull is 4.6 GiB: restore the 5 GiB
  preflight margin before another pull; retain Mongo volumes and rollback images.
- Authenticated smoke remains pending. Its existing host runner requires the
  documented human readiness/authorization gate and an approved platform user
  identity; no runner invocation or credential workaround was performed.
- Post-release regression: `MONGO_URI=<task-owned loopback replica set> uv run
  pytest` finished with 3,627 passed, 9 skipped in 69.24s. The eight protected
  stock-time replica-set tests were then run with MONGO_URI unset and the
  dedicated ZELER_RS0_TEST_URI: 8 passed in 3.54s. The remaining skip is the
  Caddy contract's no-required-keys case. Ruff check, format (500 files), mypy
  (500 files) and diff whitespace checks pass. This evidence-only update needs
  no additional image; the affected worker source already matches its verified
  deployed image.

## Work unit: reject foreign ownership during order persistence

- Following the confirmed question contamination, inspection found that order
  normalization also overwrote the source owner with the caller's seller.
  Four real-Mongo scenarios failed first because foreign orders were accepted.
- Canonical order normalization now checks both `seller_id` and Mercado Libre's
  `seller.id` independently. Either explicit foreign value rejects the write;
  a matching alias cannot conceal a contradictory one. The error contains no
  source payload or seller identity. Missing-owner partial payloads retain their
  existing contract; absence is not proof of ownership or complete source data.
- Real transaction tests exercise both an empty collection and an existing
  same-seller order, proving rejection cannot create or replace an order. The
  matching-owner control persists successfully. Existing sparse buyer/shipping
  fallback remains covered by the adjacent real-Mongo regression.
- Recovery, event persistence and historical backfill suites: 134 passed in
  5.13s. Root Ruff, format and mypy pass (500 files). Runtime harness for this
  unit is the task-owned local Mongo replica set; no production order mutation
  is part of the test.
- Rollback boundary: the ten-line order-owner normalization guard and its
  regression. The worker is the identified runtime consumer; build and verify
  its next exact main image before claiming production protection. This does
  not implement order recovery, field-aware HTTP 206 handling or all-resource
  isolation. Those remain required before global acceptance.

## Order ownership guard deployed — source d145d61

- Worker Cloud Build `b40aeff1-ac67-4c7a-88cd-fa93e77f25d7` succeeded from
  `d145d61d887c2f4b9a036cfbf3ac73b5416f59e7`. Connected repository, exact
  source, build and immutable digest passed provenance verification:
  `sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`.
  Only sheets-worker was replaced. Running digest matches, healthy, zero
  restarts, health HTTP 200/ready. Three pure in-memory owner rejection cases
  also passed inside the deployed image, without production database writes.
- A separate runtime read-only pass checked details for all 100 Mongo orders
  in the August 8–September 6 pilot window. All 100 source owners matched the
  pilot; none were foreign or missing. No production order repair was needed.
- Removed only the unused local worker image
  `sha256:9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5`
  after verifying no container referenced it and the Artifact Registry copy
  still existed. This restored 5.1 GiB preflight capacity. No volumes were
  removed. After the targeted pull, free space is again 4.6 GiB; restore the
  runbook floor before another image pull.
- Worker rollback digest:
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`.
  Compose backup suffix `.pre-sheets-worker-d145d61`. The previous question
  repair backup remains on the VM, root-owned mode 0600, 1,234 bytes. Automatic
  formula recovery remains disabled. No other product or API was deployed.
- Full regression: 3,631 passed, 9 skipped in 70.26s; protected replica-set
  suite separately 8 passed in 3.36s. Static gates remain clean. This release
  evidence changes no executable source and needs no additional image.

### Next functional gap: complete order ranges and recovery together

Inspection of `handlers_orders_questions.py` found that its eleven order/sales
handlers call `find_orders` without a coverage check; unlike its two question
handlers, they can calculate a successful result from an incomplete range.
The repository method and HTTP dispatcher do not add that check. Other handler
groups already have some generic order freshness checks, so audit per consumer
rather than infer coverage from a single helper.

The next implementation must pair truthful range validation with persistent
order recovery, not just add a gate that leaves recoverable data unavailable.
Reuse the existing guarded order writer and seller isolation. Its transaction
is coupled to the devoluciones operation lease: do not bypass it to reuse the
question transaction implementation. Handle partial source responses and prior
Mongo fields explicitly. The last-sale handler requests from 1970; applying the
queue's 90-day request limit blindly would make it permanently unrecoverable.
All-history absence and latest-known-sale evidence need distinct treatment.

## Work unit: atomic order recovery publication prerequisite

- Four new real-Mongo scenarios first failed because the order writer rejected
  all external sessions. Covered order writes can now join an existing active
  transaction while retaining the same server-time operation lease guard.
  Calls without a session retain the existing owned-transaction path.
- Commit, deliberate rollback, expired lease and session-without-transaction
  cases prove that order, SKU index and a recovery completion record commit
  together or remain absent. No production data was used or changed.
- Recovery, event persistence, historical backfill and core lease suites:
  149 passed in 5.58s. Ruff, format and mypy pass (500 files).
- Rollback boundary: optional session support in guarded_devoluciones_write
  and Sheets order persistence, plus the transaction regression. This is a
  prerequisite, not enabled order recovery. The pending worker implementation
  is its intended runtime consumer; deploy together after its acceptance.
  Existing callers keep their transaction/lease contract unchanged.

## Work unit: complete order inventory recovery worker

- Added order acquisition to the recovery worker, not to automatic admission.
  It follows short search pages to a stable required total, validates detail
  identity/owner/date/items, acquires the existing covered-order operation,
  and publishes rows, SKU indexes, coverage, job completion and operation
  success in one transaction. Empty authoritative inventory is supported.
- Questions and orders reuse coverage-union and atomic-publication code.
  Existing question regressions remain green. Orders additionally verify
  persisted buyer/item availability and the live covered-order operation.
- Real-Mongo scenarios first failed because order acquisition never ran. They
  now prove successful and empty recovery, missing total, foreign detail,
  extra Mongo inventory and refusal to claim an HTTP 206 response complete.
  The negative cases assert source acquisition actually executed, not merely
  that the unimplemented worker rejected the model.
- Recovery, event persistence, historical backfill and core lease suites:
  155 passed in 7.35s.
  Root static checks pass. No production recovery or image deployment yet.
- Rollback boundary: the order acquisition branch and shared coverage/publish
  extraction, with these tests. Automatic admission still enables only
  questions. Field-aware partial-response fallback and formula range checks
  remain required before enabling orders; this worker stage is not the final
  fallback contract or a proof of all eleven order/sales formulas.

## Work unit: partial order response fallback uses owned Mongo state

- A real-Mongo regression first rejected HTTP 206 despite existing normalized
  buyer/shipment identities. Order recovery now consumes X-Content-Missing
  explicitly and passes only its allowlisted field names to the order writer.
  Missing/malformed partial metadata still cannot prove complete recovery.
- Buyer and shipment fallback reads the same seller's current order inside the
  publication transaction, never a detached or other-seller snapshot. A known
  no_shipping state still prevents resurrection. If seller is unavailable in
  detail, the matching search row must explicitly establish its owner; any
  contradictory owner remains rejected.
- Previously stored feedback is retained when upstream marks it unavailable.
  That is last-known data, not newly verified feedback: the existing covered
  order operation invalidates devoluciones readiness, which is not promoted
  by this order inventory recovery. No raw response or auth data is persisted.
- The partial-source regression proves cancelled status updates while buyer,
  shipment and prior feedback survive. The no-cache control does not publish
  completion. Fields declared unavailable are not trusted merely because the
  response body happens to contain a value.
- Focused suites: 156 passed in 7.54s. Full regression initially found one
  test double with the old private writer signature; it now accepts the new
  optional parameters while asserting the unchanged default/context contract.
  Final full regression: 3,642 passed, 9 skipped in 71.55s. The eight protected
  replica-set tests separately passed in 3.44s; the remaining skip is Caddy's
  no-required-keys case. Ruff, format and mypy pass (500 files).
- Rollback boundary: unavailable-field handling in recovery and order
  persistence plus its regression/test-double update. Automatic admission is
  still questions-only and the production flag remains off. No build, deploy
  or production mutation was performed for these three work units.

Before activation, connect truthful range checks and recovery to the eleven
order/sales handlers and prove a missing-data/next-HTTP-query cycle. Do not treat
the current blanket buyer/shipment requirement as final: each formula must
require only the fields needed for its result, so missing buyer information
must not prevent a complete sales-total calculation. Resolve this together
with partial normalized persistence/field availability, not by returning a
misleading zero or discarding the available amounts. The all-history last-sale
case, recovery admission controls and other model dependencies remain open.

The pending runtime consumer is sheets-worker; a verified new image and a
controlled pilot order recovery are required before claiming live support.
Pair the release with the forthcoming API range/admission changes rather than
activate this staging implementation alone. Existing non-session core callers
retain their contract; other product deployments remain out of scope.

## Work unit: unavailable buyer does not erase usable order amounts

- A new real-Mongo test first failed because a partial source order without a
  cached buyer could not be persisted. Order normalization now omits the absent
  buyer ID and explicitly records unavailable_fields. No placeholder identity
  is manufactured. Source-available complete documents retain their old shape.
- Core validation and the exported Mongo order validator require the buyer
  omission to match the unavailable marker. Mongo tests reject undeclared
  absence, unrelated flags, contradictory identity/flag and unknown field names.
  The allowed normalized field names are buyer_id, shipment_id and feedback.
- Recovery can publish an authoritative inventory with explicit field gaps.
  Last-known feedback remains marked unavailable when not freshly sourced;
  existing identity fallback and no_shipping behavior are preserved.
- A validated Mongo recovery test proves sales total 30 remains usable while
  buyer-filtered ORDENES raises structured DATA_UNAVAILABLE instead of silently
  excluding the order. Both buyer-filter call sites share that check. No source
  call occurs during either calculation. This is not yet a range-coverage or
  authenticated HTTP acceptance claim.
- Model, schema export, recovery, order/question formula and persistence suites:
  199 passed in 6.22s. Static checks pass. No production schema/data mutation.
- Rollback boundary: explicit order-field availability, buyer omission model
  and Mongo schema, and buyer-filter guards with their tests. Production rollout
  must apply the compatible order validator before any partial writer is enabled
  and protect all relevant readers. Do not restore the old required-buyer Mongo
  validator while partially populated orders exist; retain the compatible
  validator through a code rollback until those documents are resolved.

## Work unit: bounded sales formulas request persistent recovery

- Nine range-based order/sales handlers now share a coverage-checked read.
  Ten new cases failed first: each of those handlers accepted unproven empty
  inventory, and the local HTTP sales-total request returned success instead
  of requesting recovery. They now emit structured orders/range unavailability.
- Runtime order coverage no longer requires the legacy_imported basis used by
  imported history models. Other models retain that requirement. Existing
  reconciliation interval and expiry checks remain in use.
- The opt-in recovery wiring now admits questions and orders; shipments and
  other unfinished models remain excluded. The production flag has not been
  enabled. Admission quotas and safe global activation remain unfinished.
- Local authenticated ASGI HTTP plus actual Mongo tests cover questions,
  complete orders and HTTP 206 orders with no cached buyer. First query requests
  recovery without source calls; background work persists data/proof; the next
  sales-total query returns 30 without another source call. All three HTTP
  scenarios passed in 1.08s. This does not substitute for production HTTP smoke.
- Calculation/address fixtures now explicitly declare their complete test
  inventory; their fake collection supports find_one. The schema contract test
  checks conditional buyer presence rather than the superseded unconditional
  requirement. Tenant/ID requirements and buyer-address isolation assertions
  remain intact. Negative coverage and conditional-validator behavior are
  exercised against actual Mongo, not mocked away.
- Rollback boundary: shared bounded-order read, runtime-order basis selection,
  orders opt-in admission, and related tests. Pair Sheets API and worker images
  with the compatible order validator; do not activate partial writers first.
- Final regression: 3,655 passed, 9 skipped in 72.18s. Protected replica-set
  suite separately: 8 passed in 2.24s. Remaining skip is Caddy's no-required-keys
  contract case. Ruff check, format, mypy and diff whitespace checks pass.
  No build, deploy, production schema change or production order write was
  performed for these two work units.

### Still required before production order-recovery activation

- DIASDESDEULTIMAVENTA reads all-history; handle the latest-known-sale versus
  unknown-history distinction explicitly. COMPRADORES missing IDs now request
  discovery as documented below, but missing shipment snapshots remain pending.
- Continue the required-field audit beyond the explicit shipment_id guard
  below: missing shipment snapshots and required address/cost fields still need
  their own acquisition and availability handling.
- Ranges beyond the queue's 90-day limit need bounded acquisition scheduling;
  do not claim they are unrecoverable merely because of that internal limit.
- Verify/release the pending schema/API/worker changes in the approved runtime,
  then prove pilot order recovery and production formula reads. The last live
  worker is still source d145d61 and the API source 4f65d6d, not these changes.

## Work unit: retain recovery requests and expose required shipment gaps

- Requests arriving during a completed/failed job's cooldown now remain pending
  with the original deadline. Twenty concurrent requests keep one job; the worker
  can claim it after the deadline without another user recalculation. Both
  terminal-state regression cases failed before the fix.
- ORDENES, ORDENESPORSKU and COMPRADORES reject explicitly unavailable shipment
  identity when needed for shipping cost/address. The structured error identifies
  orders and their creation-time interval for asynchronous recovery. Sales totals
  continue using available amounts; unrelated SKU rows do not require that
  shipment. Genuine optional absence retains existing behavior.
- The actual-Mongo partial-order test failed first for shipping. After the fix,
  recovery and buyer-address suites passed: 56 tests in 8.46s. The gateway fixture
  records no additional source calls during formula evaluation. This is local
  source-fixture/Mongo evidence, not a production HTTP or real Sheet result.
- Rollback boundary: terminal-job requeue behavior and shipment-identity helper,
  its five call sites and associated regression changes. No stored order schema
  change belongs to this unit. Reverting the guard must not accompany activation
  of partial-order writers.
- No build/deploy or production mutation in this unit. Sheets API and worker
  need new verified images once the remaining activation gates above are met;
  verify deployed source/digest, health and controlled pilot recovery then.
- Root regression: 3,657 passed, 9 skipped in 72.98s. The eight protected Mongo
  cases passed separately in 2.48s with the dedicated replica-set test variable;
  the remaining skip is Caddy's no-required-keys case. Ruff check/format, mypy
  (500 source files) and diff whitespace checks passed.

## Work unit: recover explicit COMPRADORES order IDs

- COMPRADORES no longer silently omits requested orders absent from the seller's
  Mongo read model. It raises structured unavailability with private recovery
  targets, without including those IDs or upstream payloads in the public error.
- Opt-in HTTP recovery queues deterministic seller-scoped ID jobs, at most 100
  numeric IDs each, under one total one-second insertion deadline. Existing
  range-job identities and claim/lease/cooldown behavior remain unchanged.
- The worker discovers creation dates, then reuses the existing inventory search,
  detail validation and transactional publication. Discovery alone never proves
  coverage. Every requested ID must occur in the authoritative inventory before
  any publication. Explicit foreign/conflicting ownership is rejected; HTTP 206
  seller omission requires ownership proof from the subsequent search/detail
  validation. The 240-second worker timeout and 10,000-order search cap remain.
- Local authenticated ASGI/Mongo scenarios failed first for absent IDs and for
  recoverable partial seller responses. Both now recover in the background;
  the next COMPRADORES query returns a row without more source calls. Negative
  tests reject foreign/missing ownership, wrong IDs and absent search results
  without persisting an order or coverage marker. Queue tests cover coalescing,
  tenant isolation and invalid/bounded identities.
- Rollback boundary: ID request type, private error targets, API scheduling,
  missing-ID handler guard and worker discovery with its regression cases.
  Deploy API and worker together; do not leave an old worker consuming ID jobs.
  No production write/build/deploy occurred. New Sheets API and worker images
  remain required after the outstanding activation gates, followed by digest,
  health and controlled pilot HTTP recovery verification.
- This does not complete COMPRADORES address acquisition or source freshness,
  wide-history acquisition, global admission controls, or real Google Sheet
  acceptance. Range acquisition may still exceed its worker budget for widely
  separated IDs; independent bounded acquisition remains a follow-up for the goal.
- Final verification: recovery/address suites 63 passed in 10.16s; root suite
  3,664 passed, 9 skipped in 74.59s. Eight protected replica-set cases separately
  passed in 2.42s; remaining skip is Caddy's no-required-keys case. Ruff check,
  format, mypy (500 files) and diff whitespace checks passed.

## Work unit: normalize current shipment detail in recovery transactions

- Current shipment details normalize `logistic.type` and
  `destination.shipping_address` plus `destination.receiver_name` into the
  existing Mongo fields. Legacy-shaped inputs remain supported for proven
  callers. The same eight address fields are retained; raw destination data,
  phone and geolocation are not added to the stored formula projection.
- Source: [Mercado Libre shipment contract](https://developers.mercadolibre.com.mx/envios),
  checked September 7, 2026. It documents `x-format-new: true`, discontinued
  detail `order_id`, and address hiding before confirmed payment. Caller-side
  order linkage still must be established through a verified relationship;
  this normalizer does not invent it or mark hidden addresses optional.
- Shipment persistence now joins an explicitly active caller transaction.
  The actual-Mongo validator test failed first for normalization and unsupported
  transactions, then passed for ordinary write, commit, abort and inactive
  session rejection (4 passed in 0.82s). Committed projections are readable;
  aborted writes remain absent. Existing freshness/tenant write filters remain.
- Persistence and recovery suites before the additional inactive-session case:
  129 passed in 10.47s. Mypy passed for 500 files; Ruff check/format passed.
- Rollback boundary: current-shape extraction and shipment session propagation
  with these regression cases. No Mongo schema change. Do not roll the worker
  back past this boundary while relying on transactional shipment recovery.
- Not activated: shipment recovery jobs, required address/cost availability,
  relationship fetching, current source request headers and formula-triggered
  shipment acquisition. These remain part of the goal, not deferred out of scope.
  No production write/build/deploy occurred. The Sheets worker needs a verified
  Cloud Build image after its acquisition path is completed, followed by source
  digest, health and controlled pilot shipment/formula verification.
- Final root regression: 3,668 passed, 9 skipped in 74.69s. Eight protected
  replica-set tests passed separately in 2.68s; remaining skip is Caddy's
  no-required-keys case. Diff whitespace validation passed.


## Work unit: acquire owned shipment IDs and publish atomically

- The recovery worker can process explicit shipment-ID jobs (up to 100 unique
  normalized numeric IDs). It obtains owned order relationships from
  `/shipments/{id}/orders` with `X-New-Domain: true`, then current detail and costs
  with `x-format-new: true`. Costs reuse the existing seller-matched normalizer.
  Source: [Mercado Libre shipment contract](https://developers.mercadolibre.com.mx/envios),
  checked September 7, 2026.
- The established singular `order_id` projection uses a deterministic owned
  relationship, never a foreign row or invented ID. Full relationship modeling
  and simultaneous multi-seller storage are not claimed: an existing shipment
  document owned by another seller is preserved, not reassigned.
- Normalized shipments and live job completion commit in one Mongo transaction.
  Publication checks persisted BSON-normalized values against the acquisition;
  a newer stored version cannot be overwritten or silently certified as the
  acquired version. Explicit-ID acquisition does not write a history coverage
  marker. Queue completion can join the transaction using the existing lease
  and cooldown logic.
- Initial tests failed because shipment ID requests were unimplemented. The
  actual-Mongo/schema suite now passes 9 scenarios in 1.70s: acquisition,
  foreign relationship, wrong detail ID, partial response, superseded lease,
  invalid second document, foreign cost, preexisting foreign document and newer
  stored snapshot. Failure while publishing the second document rolls back the
  first. Phone/raw destination data are not persisted.
- Activation remains OFF: shipments are not added to runtime IMPLEMENTED_MODELS
  and the HTTP error-to-job path does not yet admit shipment IDs. A range-only
  shipment request is not implemented. Before enabling, add required-field
  availability/freshness and formula-triggered ID scheduling. A hidden/missing
  address must not become optional NA; incomplete costs currently reject the
  acquisition, so preserving independently usable partial fields also remains
  required work. These are goal requirements, not waived acceptance criteria.
- Rollback boundary: shipment-ID request type, transactional queue completion,
  worker shipment branch and its regression cases. No schema migration or
  production mutation/build/deploy occurred. A new verified Sheets worker image
  is required once activation gates are satisfied; verify source/digest, health,
  pilot source equality and formula reads in the approved runtime context.
- Final regression: 3,677 passed, 9 skipped in 76.55s. Eight protected replica-set
  cases passed separately in 2.49s; remaining skip is Caddy's no-required-keys
  case. Ruff check/format, mypy (500 files) and diff whitespace checks passed.

## Work unit: preserve usable shipment fields during partial acquisition

- Shipment documents can record `formula_observed_at` and an allowlisted,
  deduplicated `unavailable_fields` list for receiver address and real shipping
  cost. This timestamp records acquisition, not freshness of flagged fields.
  Core model and schema exporter agree; regeneration changed only shipments.json.
  Legacy canonical documents still omit empty availability metadata.
- Missing or failed seller-cost acquisition no longer discards independently
  acquired address/status data. Hidden/absent address is explicitly unavailable,
  not silently certified as optional absence. Another sender's cost is never
  substituted. Upstream diagnostics are not stored.
- Inside the publication transaction, missing fields can retain the previous
  same-seller Mongo value while remaining flagged. The cached cost's original
  synced_at is preserved, including UTC restoration for naive Mongo decoding;
  no field is stamped freshly sourced merely because fallback found a value.
- Transient cost failures atomically persist usable fields and schedule the
  existing bounded retry. They do not mark the job completed prematurely.
  The regression advances the clock without enqueuing another request, restores
  source availability, and verifies job completion, refreshed cost/address and
  removal of the unavailable flags.
- Tests failed first for missing observation metadata, discarded partial
  acquisition and cancelled retries. The 12 actual-Mongo acquisition scenarios
  now pass in 2.33s, retaining previous tenant, stale-write, lease and rollback
  checks. Ruff check/format and mypy (500 files) pass.
- Rollback boundary: optional shipment availability model/schema fields,
  partial acquisition and transaction-local fallback/retry, with regressions.
  Keep the compatible validator if rolling code back with flagged documents
  present. No build/deploy or production schema/data mutation occurred.
- Not activated: formula readers must honor field availability and observation
  freshness, HTTP must schedule shipment IDs, and readiness/admission controls
  must be verified before enabling. Event-driven shipment writes still need
  equivalent enrichment/retention treatment. This unit does not prove those
  requirements or production/Google Sheet acceptance. Plan a verified Sheets
  worker image and paired API/validator rollout after those gates, then check
  deployed source/digest, health and controlled pilot field recovery.
- Final root regression: 3,680 passed, 9 skipped in 76.87s. Eight protected
  replica-set cases passed separately in 2.58s; remaining skip is Caddy's
  no-required-keys case. Diff whitespace validation passed.

## Work unit: formulas request current required shipment fields

- Receiver-address and realized-cost reads now require a usable seller-scoped
  value, no unavailable flag for that field, and a source observation within
  15 minutes. Addresses use formula_observed_at; costs use their own synced_at.
  Missing, expired, future-dated, malformed and foreign-seller rows produce
  structured shipment-ID recovery targets rather than a successful partial map.
  An unavailable cost does not block an independently usable address, or vice versa.
- HTTP schedules explicit shipment-ID jobs in batches of at most 100 under the
  same total one-second insertion deadline used by order IDs. Shared scheduling
  handles either ID type, not both at once. Opt-in API/worker source admission now
  includes shipments; range-only shipment jobs remain rejected. Production's
  global recovery flag was not changed.
- Twelve scenarios failed first for permissive required-field reads and missing
  HTTP recovery. They passed after the change (1.97s); two additional actual-Mongo
  malformed-field cases pass. Authenticated local ASGI tests cover complete and
  partial-cost shipment acquisition: first query requests recovery without a
  source call, background work persists the address, and the second COMPRADORES
  query returns it with no extra source calls, even while cost retry is pending.
- Calculation fixtures explicitly supply current observations and actual costs
  where those are needed. Obsolete all-NA expectations for absent/foreign/blank
  shipments were replaced with unavailable assertions; tests still verify exact
  safe address fields, seller scope, buyer filters, cart IDs and cost calculations.
  Optional absent individual address fields still render NA. Address suite:
  3 passed in 0.03s; order/item calculation suites: 82 passed in 0.38s.
- Rollback boundary: required shipment field reads/projections, private error ID
  metadata, HTTP scheduling and shipment opt-in admission with their regression
  cases. Retain critical source/tenant validations if reverting UI-facing guards.
  No production write, build or deployment occurred.
- Before rollout, verify admission limits and prepare pilot shipment snapshots;
  old production records without observation evidence will request recovery.
  Build paired verified Sheets API/worker images with the compatible validators,
  verify deployed source/digests and health, then exercise real pilot HTTP reads.
  Remaining work includes non-address/cost shipment surfaces, minimum necessary
  order selection for latest-cost calculations, event-driven refresh/retention,
  wide-history acquisition, global admission controls and real Sheet acceptance.
- Final root regression: 3,694 passed, 9 skipped in 75.13s. Eight protected
  replica-set cases passed separately in 2.42s; remaining skip is Caddy's
  no-required-keys case. Ruff check/format, mypy (500 files) and diff whitespace
  validation passed.

## Work unit: select relevant latest sales before requiring shipment costs

- COSTOENVIOVENDEDOR selects the newest eligible non-cancelled order line for
  each requested SKU/item pair before reading shipment costs. Positive quantity
  and existing shipment eligibility are preserved; explicit shipment-identity
  gaps participate in selection and request order-ID recovery if selected.
- Only the selected shipment IDs need current costs. Older, cancelled or
  unrelated orders no longer force acquisition. A missing selected cost cannot
  be silently replaced with an older cost. The per-unit arithmetic and response
  metadata remain unchanged.
- Removed this formula's global shipment freshness prerequisite: the required
  per-ID cost checks now provide the relevant evidence. The order readiness gate
  remains; ENVIOSMERCADOENVIOS keeps its existing separate gate. This resolves
  the previously noted minimum-needed selection for latest-cost calculation.
- Four cases failed first. Updated tests verify a latest sale beyond 5,000 older
  orders without their cost snapshot, unrelated/cancelled missing shipments,
  selected missing cost/identity, and successful calculation without a global
  shipment marker. Item-shipping and recovery suites: 117 passed in 15.11s.
  These are local calculation/recovery tests, not a new productive cost-formula
  or real Sheet acceptance result. Static checks pass for 500 source files.
- The order read still scans all available history. Strong absent-sale/history
  completeness evidence and bounded acquisition remain required goal work;
  this optimization does not prove those broader properties.
- Rollback boundary: latest-line selection, required-ID lookup and removed
  global shipment gate in this handler with their regression updates. No schema,
  production data, build or deployment change. Sheets API needs a verified new
  image after the outstanding rollout gates, coordinated with the pending
  recovery worker/validator release; verify deployed source/digest, health and
  pilot COSTOENVIOVENDEDOR with obsolete unrelated shipments unavailable.
- Final root regression: 3,696 passed, 9 skipped in 79.50s. Eight protected
  replica-set tests passed separately in 2.53s; remaining skip is Caddy's
  no-required-keys case. Ruff check/format, mypy and diff whitespace checks pass.

## Work unit: restrict automatic recovery to explicitly configured sellers

- Sheets API and worker now read `ZELERDATA_FORMULA_RECOVERY_SELLERS` alongside
  the existing enable flag. Missing/blank configuration enables no sellers;
  comma-separated numeric IDs are required and wildcards are rejected. The
  deployment runbook names the agreed pilot and paired-image activation gate.
- Queue admission, worker claims and exhausted-lease cleanup obey the seller
  scope. Existing jobs belonging to other sellers remain untouched. Internal
  callers can still explicitly construct an unrestricted queue; production
  entrypoints always supply the parsed scope. This is a pilot gate, not a
  replacement for quotas/fairness before broader activation.
- Five regression cases failed before implementation. The local Mongo harness
  verifies pilot admission/claim, rejection outside scope, preservation of
  foreign expired jobs, and an empty scope. API construction also verifies
  propagation. `uv run pytest modules/sheets/tests/test_formula_recovery.py`
  with the task-owned local replica set: 95 passed in 10.34s.
- Read-only VM inspection reconfirmed Sheets API `f9b07c9de23c`, worker
  `b8edfdf59627` and gateway `2d4a514cab2d` healthy with zero restarts. Recovery
  remains disabled on both Sheets services. Root free space is 4.54 GiB, below
  the required 5 GiB pull/Compose floor. No production mutation or deployment
  occurred; these checks do not constitute formula HTTP acceptance.
- Rollback boundary: this seller parser, API/worker wiring, queue filters and
  corresponding tests/runbook changes. Disable recovery on both services before
  rolling back to images without the gate; otherwise the old flag is unscoped.
  No schemas or persisted records need removal. New verified Cloud Build images
  are required for Sheets API and worker after the remaining validator/event
  ingestion gates and VM capacity preflight. Verify deployed source/digest,
  health, pilot recovery and outside-scope rejection before activation.
- Final root regression (`uv run pytest` with the local replica set): 3,701
  passed, 9 skipped in 75.92s. The protected stock-time-forward suites ran
  separately with `ZELER_RS0_TEST_URI` and no ambient `MONGO_URI`: 8 passed in
  2.57s. Remaining skip is Caddy's no-required-keys case. Ruff check/format,
  mypy (500 source files) and diff whitespace checks passed.

## Work unit: retain recovered shipment fields across ordinary events

- Ordinary shipment writes without a formula observation no longer erase the
  stored address, independent shipping cost, original observation timestamp or
  unavailability flags when those fields are absent from the incoming normalized
  document. A Mongo update pipeline retains only these four fields, then overlays
  the canonical document; unknown legacy/raw fields are not carried forward.
- Retention and the existing seller/freshness guard execute atomically, with no
  read-then-write merge race. Recovery publications containing an observation
  still use their existing transactional replacement path, including clearing
  resolved gaps. Incoming explicit normalized values take precedence; an ordinary
  event does not refresh the retained observation or remove previous gap flags.
- Two Mongo regression cases reproduced missing addresses before the fix, after
  correcting the fixture's required shipment fields. Tests now verify delivered
  status, unchanged cost/address/proof, retained flags, removal of a synthetic raw
  sentinel, and continued DATA_UNAVAILABLE for expired retained fields. Existing
  stale-write and recovery transaction tests remain in the focused suite.
- No build, production data change or deployment occurred. This closes the
  destructive replacement gap, not the outstanding event acquisition/new order
  relationship contract or productive HTTP/Sheet acceptance requirements.
- Rollback boundary: the ordinary shipment update branch and its Mongo/fake
  regression coverage. No schema migration is introduced. Rolling it back can
  again erase enrichment on events, so keep recovery disabled when reverting.
  Sheets worker requires a new verified Cloud Build image with the pending paired
  API/validator release. Verify deployed source/digest, health, and a pilot event
  after recovery: status advances while retained fields and timestamps survive.
- Focused local Mongo harness:
  `uv run pytest modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_event_persistence.py`
  with the task-owned replica set: 163 passed in 8.97s. The first root run found
  a historical-backfill fake without pipeline support; after adapting that fake,
  `uv run pytest modules/sheets/tests/test_historical_meli_backfill.py` passed
  all 40 tests in 0.27s. No production behavior was changed to satisfy the fake.
- Final root regression: 3,703 passed, 9 skipped in 78.30s. The eight protected
  stock-time-forward replica-set cases passed separately in 2.62s; the remaining
  skip is Caddy's no-required-keys case. Ruff check/format, mypy (500 files) and
  diff whitespace checks passed. These local results do not close live acceptance.

## Operational checkpoint: restore VM capacity and audit validator compatibility

- Confirmed selected main commit `c82b5bec2a5b8e4896278f1e9d2f28ef91f1ff12` and
  preserved unrelated untracked work. No build, service recreation, data repair
  or validator mutation occurred in this checkpoint.
- Removed only two unused local image copies, after checking every container
  reference and confirming both digests still exist in Artifact Registry:
  Sheets worker `sha256:ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646`
  and Sheets API `sha256:cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc`.
  Running images and immediate rollback images were retained. No volumes or
  containers were removed. Both deleted copies are recoverable by digest pull.
- Root free space increased from 4.54 to 5.62 GiB, above the 5 GiB capacity floor.
  Run the full service-specific deploy preflight again immediately before a pull;
  this capacity observation alone is not a deployment authorization receipt.
- Inside the approved worker container, using `/app/.venv/bin/python`, checked
  production documents against main's orders/shipments `$jsonSchema` payloads.
  Existing validators differ from main; both are configured strict/error.
  Orders: 2,429 documents, zero invalid under the proposed schema. Shipments:
  2,374 documents, 47 invalid. All 47 belong to the pilot and have string-valued
  `date_created` and `last_updated`; no other property violations or missing
  required fields were found. Only aggregate counts/types were emitted.
- Diagnostic correction: the first probe mistakenly included deployment metadata
  (`validationLevel`/`validationAction`) as query predicates and reported all
  documents invalid. That result is discarded; the counts above use only the
  `$jsonSchema` validator. System Python also lacked pymongo, so the successful
  probe used the documented runtime virtual environment.
- Next release gate: validate and reversibly normalize those 47 date pairs in
  the approved runtime context, preserving instants and unrelated fields; recheck
  zero invalid documents before applying compatible validators. This does not
  prove source completeness/freshness or replace new-contract acquisition.
- Verification is the production read-only compatibility/count audit plus exact
  image-reference/registry checks and measured capacity. Unit tests are N/A for
  this documentation-only repository change; no executable code changed.
  Pending Sheets API/worker changes still require new verified Cloud Build images,
  exact deployed-source checks and pilot recovery/HTTP verification after the
  outstanding release gates. The full goal remains open.
- Post-cleanup inspection confirmed API `f9b07c9de23c`, worker `b8edfdf59627`
  and gateway `2d4a514cab2d` still healthy with zero restarts and the same images.
  Diff whitespace validation passed. Documentation rollback removes only this
  checkpoint; image recovery is independent and uses the registry digests above.

## Work unit: bounded, reversible shipment date normalization

- Added `infra.operations.shipment_date_repair.repair_shipment_dates` for an
  operator-supplied backup of at most 100 same-seller shipment identities and
  date pairs. It accepts only timezone-aware ISO strings exactly representable
  as BSON milliseconds. One snapshot/majority transaction compares original
  dates and seller identity before each date-only update; any mismatch aborts
  the entire batch. It neither refreshes formula evidence nor contacts Meli.
- Five tests failed first, then passed against local Mongo: exact offset/instant
  conversion, concurrent-date-change rollback, foreign seller, naive date and
  precision-loss rejection. All 102 recovery tests passed in 10.21s with the
  task-owned replica set. Ruff check/format and mypy (501 files) pass.
- Production read-only preflight found exactly 47 pilot shipments and 94
  timezone-aware millisecond dates, with no rejected values. Before mutation,
  created `/var/lib/zeler-platform/repairs/shipment-dates-148c8ae.bson` on the
  approved VM: 7,367 bytes, root-owned mode 0600 in the existing 0700 directory.
  Backup contains only seller/shipment identity and the two original dates;
  no document payload or backup content was emitted outside the VM.
- Execution gate: use the reviewed helper from the exact pushed source inside
  the approved runtime, loading this backup locally on the VM. After execution,
  compare both dates with converted backup values and recheck the main shipment
  schema without altering validators. A failed comparison must stop the rollout.
- Rollback is a separate guarded date-only transaction: for each backup identity
  require the current two dates equal its converted values, then restore only
  its original strings. Abort if any dates changed since repair; never replace
  whole documents or overwrite later events. Do not restore strings after a
  stricter date validator is activated without first resolving compatibility.
  Keep this restricted backup under the goal's retention/deletion hardening scope.
- This operator-only helper is not called by service entrypoints and does not
  itself require a new image. Pending API/worker behavior still requires verified
  Cloud Build images and productive pilot/HTTP/Sheet checks; the goal stays open.
- Final local regression: 3,708 passed, 9 skipped in 79.11s; eight protected
  stock-time-forward Mongo cases passed separately in 1.56s. Remaining skip is
  Caddy's no-required-keys case. Ruff check/format, mypy and whitespace checks pass.
- Executed reviewed source `3f5ee2021838fa77f3a9d085ff10b2b58d9de821` inside
  the existing worker container without changing its image or filesystem.
  The helper's SHA-256 was checked before execution:
  `e482a722d2331ab3e6583ab44feee0bce9687b5d2bb23a4836ab9878f51b7876`.
  The root-only VM backup was piped directly into the runtime; no credentials,
  identities or original date values were printed or transferred locally.
- Production result: 47 shipment documents repaired in one transaction, all 94
  dates independently compared with the converted backup originals, zero shipment
  documents invalid under main's proposed schema afterward. Only the two date
  fields were updated. Validators, formula observation timestamps, feature flags
  and other collections were not modified. The rollback backup remains available.
  This resolves the identified type-compatibility gap, not source completeness or
  productive formula/Sheet acceptance.
- Post-repair inspection: Sheets API `f9b07c9de23c`, worker `b8edfdf59627` and
  gateway `2d4a514cab2d` retained their running images, healthy with zero restarts.
  They still do not include the staged API/worker changes on main. Apply compatible
  validators and verify new images/pilot behavior through the outstanding release
  gates; do not treat this date repair as a completed deployment.

## Operational checkpoint: apply compatible orders and shipments validators

- At main `71f6c1b4178349ff697288811e341a1668a8f750`, rechecked both proposed
  `$jsonSchema` payloads against production: zero invalid documents. Backed up
  both existing validator/options sets to root-only VM file
  `/var/lib/zeler-platform/repairs/formula-validators-71f6c1b.bson` (4,009 bytes,
  mode 0600 under the 0700 repairs directory). It contains schema configuration,
  not document data or credentials.
- Inside the approved worker runtime, compared current options with the backup
  before mutation, then applied only orders and shipments through majority-
  acknowledged `collMod`. Both resulting validators match the committed schemas
  exactly, with strict/error enforcement and zero invalid documents afterward.
  No indexes, document data, other collections, images or feature flags changed.
- Verification: validator application/idempotency/failure suites passed 10 tests
  in 0.06s; the local Mongo recovery suite passed 102 tests in 16.01s. These tests
  include complete/partial order and shipment publication under current schemas.
  The production result is schema compatibility, not formula HTTP acceptance.
- Rollback boundary: only the two backed-up validator/options sets. Before
  reverting either, recheck current configuration and compatibility of every
  document with its old validator. Once partial orders exist, blindly restoring
  the old required-buyer schema can reject valid writes; keep the compatible
  schema when rolling back application images unless safety is proved.
- Started one verified Cloud Build per affected Sheets image from this exact
  connected-repository commit, without uploading the local checkout:
  API `223142bd-0fcb-4196-ac41-2183517d2f8b`; worker
  `07724522-d44f-420c-affa-6604141978dc`. Both were observed WORKING. Build
  completion, immutable digest/provenance verification and deployment are separate
  gates; neither service has been pulled/recreated by this checkpoint.
- Both builds subsequently completed SUCCESS. Using the repository's
  `verify_image_to_commit`, verified each single-image SLSA subject, build,
  connected repository, source commit, project ID and project number. Immutable
  images ready for the controlled rollout:
  - Sheets API: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`.
  - Sheets worker: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d`.
- Local sanitized binding maps are under `/tmp/zeler-recovery-build.IltD0b/`
  as `sheets-api-image_to_commit.json` and `sheets-worker-image_to_commit.json`.
  Build configurations in the same directory requested VERIFIED provenance and
  produced one image each. These files are convenience evidence; authoritative
  build and registry records must be rechecked before deployment.
- After validator activation, Sheets API, worker and gateway remained healthy
  with zero restarts. Recovery remained disabled. Runtime still uses the older
  API/worker images; next run the capacity/provenance preflight, deploy the exact
  verified images through targeted service replacement, check digest/health and
  then prove pilot behavior. No new build is needed for this documentation-only
  checkpoint; the full goal remains unproven until live acceptance is complete.

## Operational checkpoint: deploy the verified recovery-capable Sheets pair

- Confirmed main `df16a8baa460cb48e6d7ae560f59797ae9badb82` differs from the
  verified image source `71f6c1b4178349ff697288811e341a1668a8f750` only in this
  progress document. Rechecked both successful Cloud Build records, exact source
  revision and image digests. No new build or executable repository change.
- VM dry-run and real capacity preflights passed. Replaced exactly one Compose
  image occurrence per service, first worker then API, with targeted pull and
  `up -d --no-deps`. Backups are
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-71f6c1b` and
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-71f6c1b`.
- Worker now runs `sha256:ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d`;
  API now runs `sha256:c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`.
  Both correspond to the verified build IDs recorded immediately above.
- Preserved immediate rollback authorities: worker
  `sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`
  and API `sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f`.
  Restore only the affected service's image, not the entire Compose backup;
  retain compatible Mongo validators and keep recovery disabled on rollback.
- To preserve the 5 GiB floor before the API pull/recreation, removed only unused
  local worker image `sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee`
  after rechecking all container references and its continued registry presence.
  It is recoverable by digest pull. No containers or volumes were pruned. Free
  space was 5.62 GiB before each pull and 5.12 GiB after the completed pair.
- No feature flags, seller scope, Mongo data or other product services were
  changed. Automatic recovery remains deliberately disabled; deploying code is
  not evidence of background recovery or productive formula/Sheet acceptance.
- Final runtime checks confirmed both exact new digests, Docker health healthy,
  zero restarts, and `/health` HTTP 200 with `ready=true` inside each service.
  Gateway retained digest `2d4a514cab2d`, healthy with zero restarts. No rollback
  was needed. Whitespace validation passed; unit tests are N/A for this
  documentation-only change (the image source's tests are recorded above).
- Runtime now includes the staged Sheets code at the verified source commit;
  current main adds only evidence documentation. No further image rebuild is
  required for this checkpoint. Next prove controlled pilot recovery, real HTTP
  formula behavior, authenticated app surfaces and Google Sheets; all global
  acceptance requirements remain open until the corresponding evidence exists.

## Operational checkpoint: controlled pilot order recovery

- Inspected the pilot queue in the deployed worker: only one completed question
  job existed, with no order jobs. Kept API/worker automatic recovery flags off.
- The first preflight stopped before enqueue because the effective coverage was
  wider than the requested August 8–September 6 dates. Existing order coverage
  starts June 1; the worker preserves it by reacquiring the complete union through
  September 7 exclusive (98 days). A read-only gateway search reported 1,069
  source orders. No marker was deleted or shortened to force the smaller test.
- After explicitly bounding that observed union, enqueued one pilot-only orders
  request: `ebf5decad5d7272397c1cce22e81cd5158259dea80d2d4412eebee0d817297d4`.
  Executed the deployed `FormulaRecoveryWorker.process_one` inside the approved
  runtime, using normal bootstrap search and Sheets detail gateway clients.
  Queue admission/claim is limited to seller 82453304 and orders; no other account
  or model is processed. The existing 240-second acquisition/publication limit
  remains in force. This is an operator-run worker test, not authenticated HTTP
  formula acceptance and not automatic poller activation.
- The controlled attempt finished failed/source_incomplete after 187.233s:
  22 search calls and 1,069 detail calls, one attempt. The order publication did
  not complete; the operation is failed and the old July 10 coverage endpoint
  remains, without a new expiry/proof. No automatic retry or lease override was
  started. Do not report this as successful recovery.
- Independent read-only inventory comparison found 1,069 IDs in the search,
  1,073 stored IDs in the effective interval, six source IDs absent in Mongo and
  ten Mongo IDs absent from search. Direct API detail checks for all ten extras
  confirmed matching pilot ownership and dates inside the interval. These are
  not foreign or out-of-range records and must not be deleted to force equality.
- Official Mercado Libre documentation confirms seller search excludes certain
  cancelled orders: [Search orders](https://developers.mercadolibre.com.mx/en_us/manage-sales).
  The observed discrepancy invalidates the assumption that seller-search IDs
  alone exhaust the authoritative inventory. The precise exclusion reason for
  each of these ten orders was not established by the aggregate owner/date check.
- Next correction must combine bounded search acquisition with direct validation
  of known persisted identities absent from search, retaining only source-proven
  seller/date matches and handling genuinely unavailable detail explicitly. Keep
  atomic publication and source ownership checks; do not remove legitimate orders
  or silently label a search-only partial inventory complete. Also revisit legacy
  no-expiry coverage and union bounds. No new executable code/image changed in
  this checkpoint; rollback of its documentation does not modify stored data.
- This failure is actionable live evidence, not a reason to close or mark the
  whole goal blocked. Required formula HTTP, real Sheet, app and hardening checks
  remain open. Automatic recovery stays disabled until the defect is corrected
  and the controlled worker test passes.

## Work unit: validate known orders omitted from seller search

- Order recovery now augments completed search enumeration with persisted IDs
  in the same seller/date range. IDs absent from search are fetched by detail
  before publication. A shared detail validator checks identity, current source
  owner, date range, nonempty items and supported partial-response metadata.
  Local seller attribution cannot substitute for a missing source owner.
- The existing search/date equality check remains for enumerated rows. Known
  omitted rows are accepted only when their own detail proves scope, then join
  the same normalized publication, inventory comparison and completion transaction.
  No records are deleted to force search-only equality. Missing/invalid detail
  prevents complete coverage; existing records and proof remain unchanged.
- The union of searched/known identities stays within the existing 10,000-order
  budget. The Mongo identity scan is capped at 10,001 and malformed identities
  are rejected before direct acquisition. The 240-second worker limit remains.
- Three cases failed before implementation. Regressions cover a confirmed
  cancelled extra, supported partial buyer detail, empty search with a known
  legitimate order, foreign/missing owner, wrong ID, outside-range dates and 404.
  Additional tests reject malformed/over-budget known IDs without detail calls.
- This corrects the search-only assumption exposed by the productive test,
  but is not yet a successful repetition of that test. Legacy no-expiry markers,
  large coverage unions and genuinely unavailable known detail remain explicit
  limitations; no new productive data, flag or image changes occurred here.
- Rollback boundary: known-ID acquisition and shared order-detail validation in
  the worker plus their regression cases. No schema or data rollback is needed;
  reverting reintroduces the observed inventory failure, so keep automatic
  recovery off. Build a new verified Sheets worker image, deploy it with exact
  digest/health checks, and repeat the pilot job after its normal cooldown.
  Sheets API behavior is unchanged and does not need rebuilding for this unit.
- Local verification: `uv run pytest modules/sheets/tests/test_formula_recovery.py`
  with the task-owned replica set passed 112 tests in 16.29s. Root regression
  passed 3,718 tests with 9 skips in 82.33s; the eight protected Mongo cases passed
  separately in 2.46s. Remaining skip is Caddy's no-required-keys case. Ruff
  check/format, mypy (501 files) and whitespace checks pass. These do not replace
  productive pilot, authenticated HTTP or real Sheet evidence.
- Built the affected worker alone from pushed source
  `9f57afaead67b92ef1ce7d17e83919fc3a28621e` through the connected repository.
  Cloud Build `dd7bfddf-1d71-4284-9b0c-c6f8add91ee9` completed SUCCESS with
  VERIFIED provenance requested. Immutable image:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
  The repository verifier confirmed the SLSA subject, build, exact source,
  connected repository and project identity. Sanitized binding map:
  `/tmp/zeler-known-orders-build.UeJgfe/image_to_commit.json`.
  This image has not been deployed. The currently running worker remains the
  previous `ec056fc54922` image; next deploy this verified fix and repeat the
  controlled job without overriding cooldown or declaring success from local tests.

## Operational checkpoint: deploy known-order fix and repeat the pilot job

- Verified selected main `4e792545a116e698d16bfa9437499238be5145cd` differs from
  image source `9f57afaead67b92ef1ce7d17e83919fc3a28621e` only in this ledger.
  Rechecked successful Cloud Build `dd7bfddf-1d71-4284-9b0c-c6f8add91ee9`, source
  and digest. Deployed only Sheets worker at
  `sha256:98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
- Capacity preflight passed before targeted pull/recreation. To preserve margin,
  removed unused local worker image
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`
  after checking every container reference and continued registry availability.
  It is recoverable by digest pull; no containers or volumes were pruned.
  Free space was 5.62 GiB before pull and 5.12 GiB afterward.
- Compose backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-9f57afa`.
  Immediate rollback is the retained worker image `ec056fc54922`; restore only
  that service's exact prior image, keep compatible validators, and leave
  automatic recovery disabled. API/gateway images and feature flags were not changed.
- Reopened the same pilot order request through normal queue admission:
  `ebf5decad5d7272397c1cce22e81cd5158259dea80d2d4412eebee0d817297d4`.
  Its prior cooldown still had 132 seconds at inspection. The operator process
  polls the deployed worker until this job is due and stops after one processed
  job; it does not change `available_at`, skip ownership checks or enable global
  polling. Effective coverage remains June 1–September 7 exclusive to preserve
  earlier coverage, with the initially requested August range inside it.
- The repeated job completed successfully: 22 search calls, 1,079 detail calls,
  no failure reason. The measured 260.734 seconds include waiting for the
  existing cooldown plus processing; this is not a formula latency or an
  acquisition-only duration. The worker's per-job 240-second timeout was unchanged.
- Independent Mongo readback found exactly 1,079 pilot orders in the effective
  union, completed job state, June 1–September 7 exclusive coverage with an
  unexpired proof, and zero orders with explicit field gaps in that interval.
  The ten valid known orders omitted from search were retained/reacquired; the
  six source orders previously absent could join the atomic publication without
  deleting legitimate records. This resolves the observed inventory mismatch.
- Before completion, the API container's Mongo-only VENTASTOTALES handler for
  August 8–September 6 returned DATA_UNAVAILABLE in 0.0142s. After publication,
  the same handler returned ready over 100 orders in 0.0225s. The diagnostic
  constructed no gateway client and printed no financial values or PII. It is
  explicitly an internal operator read, not authenticated HTTP, real Sheets,
  all-52 acceptance or a p95 benchmark.
- No automatic API/worker recovery flag was enabled. No new repository code or
  tests changed during this operational checkpoint; source regression evidence
  is recorded in the preceding unit. Runtime now has the verified worker fix;
  no further worker build is needed for this ledger-only update. Continue with
  shipment recovery and the outstanding end-to-end/authenticated acceptance gates.
- A second separate API-container Mongo-only read again returned ready over 100
  orders in 0.0277s. Post-recovery API and worker checks were healthy, zero
  restarts, HTTP 200/ready=true, with automatic recovery still disabled.
  Whitespace validation passed. No rollback was needed; do not roll back valid
  source data simply to recreate the prior failure.

## Operational checkpoint: recover pilot shipment addresses and costs

- At main `63b60b9591b1fedb9d45ebd949b50f6853c0ef4d`, preflight found 97 distinct
  shipment IDs referenced by the pilot's August 8–September 6 orders. All 97
  existed in Mongo, none had a recent formula observation, and no shipment
  recovery jobs existed. No identities, addresses or financial values were emitted.
- Ran one shipment-only, pilot-scoped job through the deployed worker inside
  the approved VM/container:
  `d9030f3ecfe275f47bbf3401eec1a3875b88de40ec303f8bf0cd19895c507044`.
  The job completed in 44.739s with no failure reason: 97 relationship, 97 detail
  and 97 cost requests through the normal gateway, all 291 returning HTTP 200.
  This exercised the implemented new shipment relationship/detail headers against
  the live API; it does not prove the entire order-to-shipment migration complete.
- Independent Mongo readback found all 97 requested shipments with addresses,
  costs and observation timestamps, and zero explicit field gaps. Existing
  normalization/owner checks and the transaction remained in force. No historical
  shipment inventory marker was invented from this ID-scoped acquisition.
- Before publication, the API-container Mongo-only ORDENES handler with buyer
  columns returned DATA_UNAVAILABLE for shipments in 0.0961s. After publication,
  the same August-range handler returned ready over 100 orders in 0.0924s.
  These are internal operator reads, not authenticated HTTP, a real Sheet, all-52
  acceptance or a latency percentile. Output values/PII were not printed.
- Automatic recovery remains disabled. No repository executable code, build,
  deployment, feature flag, other account or other product changed in this
  checkpoint. Existing API/worker images remain the intended versions for this
  work; no rebuild is needed for the documentation update. Unit tests are N/A
  for this operational-only checkpoint; runtime evidence is the completed job,
  source response counts and independent stored-data/handler checks.
- Rollback must not delete valid normalized source data merely to restore the
  previous unavailable state. Keep recovery off if a later issue arises and
  diagnose exact affected fields before any guarded repair. The normal previous
  image rollback boundaries and compatible validators remain unchanged.
- Requested the real ZelerData user identity and an authorized test Sheet through
  the user-input channel for the pending authenticated/Google Sheets acceptance.
  No user token was minted, copied or bypassed. The global goal remains open.

## Recovery admission: bound distinct work per seller

- Added an initial cap of 20 pending/running recovery jobs per seller across
  models. Existing active requests still coalesce at capacity; reopening terminal
  jobs consumes capacity without advancing their cooldown. Completion frees
  capacity naturally from job state, without a separate decrement counter.
- A snapshot/majority transaction and one seller identity/revision guard in
  `sheets_formula_recovery_admission` serialize concurrent admission. The new
  seller/state index bounds the active-job lookup. No source payload is stored
  in the guard; authorized seller deletion must include it with admission stopped.
  Cancellation aborts uncommitted admission. The HTTP insertion budget remains
  one second and formulas still do not call Mercado Libre or wait for recovery.
- Evidence: the initial three focused cases failed before implementation.
  `uv run pytest modules/sheets/tests/test_formula_recovery.py` then passed
  **120 tests in 22.66s** against the dedicated local Mongo replica set. Twenty
  concurrent distinct requests admitted exactly three at a configured test cap
  of three; duplicates, another seller, running jobs, terminal cooldown reopening
  and cancellation were independently checked. This is a real local queue
  boundary test, not productive HTTP or a Google Sheet acceptance result.
- Root `uv run pytest` with the dedicated local replica-set test database:
  **3726 passed, 9 skipped, 356 warnings in 83.35s**. The protected stock-time
  acquisition/execution/rollback suite was also run separately with ambient
  `MONGO_URI` unset: **8 passed in 3.09s**. Ruff check/format, mypy over 501
  source files and `git diff --check` passed.
- No productive deployment or feature flag changed in this unit. Both Sheets
  images package the changed queue, so build new verified Cloud Build images for
  `sheets-api` and `sheets-worker`, verify exact source/digest and runtime health,
  then exercise scoped admission before considering automatic pilot activation.
  The cap is not measured throughput, global fairness, API-call quota or retention
  completion. Item/catalog recovery and the global acceptance work remain open.
- Rollback boundary: remove the admission changes in `formulas/recovery.py`,
  their tests and rollout notes together, with recovery disabled. Existing job
  documents stay compatible; the unused index/guard need not be deleted for an
  image rollback. Do not delete normalized customer data or accepted jobs.

## Operational checkpoint: deploy bounded recovery admission

- Built both Sheets images from pushed main
  `f7589c95f95fac93204a9fcf46bd760f10ea38cd`, one image per Cloud Build with
  `requestedVerifyOption: VERIFIED`. The repository provenance verifier accepted
  each exact source commit, connected repository, SLSA subject digest and build:
  - API build `acc5a410-f001-4a64-93cc-517c80f59ab3`, image
    `sheets-api@sha256:f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`.
  - Worker build `6edd910f-a258-4251-a1e1-08165e63b9f2`, image
    `sheets-worker@sha256:603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b`.
  Both use the `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`
  repository prefix. Temporary build/verification files are under
  `/tmp/zeler-admission-build.TCiSFi`; the checked-in verifier is authoritative.
- VM capacity was 5.11 GiB before deployment. Removed only unused local image
  copies `sheets-worker@sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`
  and `sheets-api@sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f`
  after checking all container references and confirming both digests remain
  recoverable in Artifact Registry. No volumes, customer data or containers were
  pruned. Capacity rose to 6.12 GiB and ended at 5.11 GiB after both pulls.
- Each service passed dry-run and real deploy preflight plus the 5 GiB checks
  before pull/recreation. Replaced exactly one Compose image at a time, worker
  first and API second. Independent final inspection confirmed both actual
  running image IDs equal their verified digests, Docker health is healthy,
  restart counts are zero, and `/health` responds HTTP 200. An initial probe of
  `/ready` used an unsupported route; the corrected probe used the implemented
  `/health` endpoint and did not require any runtime fix.
- Recovery remains disabled in both containers. This proves image rollout and
  service health, not productive quota enforcement, automatic recovery, all-52
  authenticated HTTP, Google Sheets or frontend acceptance. No repository code,
  production Mongo documents, validators or recovery flags changed in this
  checkpoint. Prior local test evidence remains applicable; new unit tests are
  N/A for this operational-only update. No additional image rebuild is needed
  for this documentation-only record.
- Rollback authorities retained locally are the prior running API digest
  `c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`
  and worker digest `98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
  Backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-f7589c9`
  and `.pre-sheets-worker-f7589c9`. Restore only the affected image line and
  verify its health; never restore the entire backup over the other service's
  newer configuration. Keep recovery disabled and retain compatible validators.

## Operational checkpoint: automatic recovery enabled for the pilot

- At main `7e5f0ba3a894be8d14ab35ed334293285c09a927`, runtime preflight
  confirmed the verified admission images, 5.11 GiB free, strict/error orders
  and shipments validators with the required partial-data fields, three
  completed pilot jobs and no active nonpilot jobs. No credentials or source
  payloads were emitted. All Mongo operations ran inside the approved VM/API
  container, never through a local production Mongo client.
- Exercised the deployed queue with an explicit pilot allowlist and default
  capacity 20. A nonpilot request was rejected before mutation. Reopened the
  existing questions job
  `ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d`
  and repeated it under the same one-second admission budget used by HTTP:
  **0.0642s and 0.0106s**, one pending job, unchanged cooldown and no additional
  job documents. Normal index initialization added the seller/state index and
  successful admission created the pilot identity/revision guard. This verifies
  live admission/coalescing/isolation, not a productive saturation test of all
  20 slots or authenticated HTTP.
- Enabled `ZELERDATA_FORMULA_RECOVERY_ENABLED=true` and
  `ZELERDATA_FORMULA_RECOVERY_SELLERS=82453304` on the worker first. The normal
  resident poller claimed and completed the questions job in **one attempt**,
  with no failure reason; independent Mongo inspection showed fresh coverage
  and completion at `2026-09-07T23:16:10.449Z`. No operator `process_one` call
  was used. There remained zero active nonpilot jobs. The total pilot questions
  collection count was 101, which is not a count of rows acquired in this run.
- After that verification, enabled the same exact pilot scope on the API.
  Each change passed dry-run/real preflight, preserved the immutable image,
  changed only the selected service's two environment keys (checked against
  rendered Compose), and recreated only that service. Final independent checks
  showed both runtime environments pilot-only/enabled, both verified image IDs
  unchanged, Docker health healthy, zero restarts and HTTP 200 from `/health`.
  Free capacity remained 5.11 GiB. Other products and sellers were not activated.
- The API-container Mongo-only PREGUNTASKPI handler returned ready with three
  questions for August 8–September 6 in **0.0215s**. The initial operator probe
  mistakenly supplied the orders argument `fecha_inicial`; correcting it to the
  existing questions contract `fecha_inicio` resolved that probe error without
  changing application code. This is not authenticated HTTP, a real Sheet,
  all-52 acceptance or a p95 measurement. Those acceptance gates remain open,
  along with item/catalog recovery and minimum hardening.
- Rollback: set recovery enabled to false on both Sheets services and recreate
  each with normal capacity/health checks; keep the pilot allowlist and current
  images. Stop or allow any already-running job to finish through normal worker
  lifecycle handling. Do not delete queued jobs, guard metadata or normalized
  data. Backups are
  `/opt/zeler-platform/docker-compose.yml.pre-pilot-recovery-sheets-worker-7e5f0ba`
  and `.pre-pilot-recovery-sheets-api-7e5f0ba`; never restore either whole file
  over subsequent service configuration. Validators stay compatible.
- This checkpoint changes runtime configuration, indexes, queue state and
  normally recovered question data, not repository executable code. Prior unit
  evidence applies; the acceptance evidence for this operational unit is live
  admission, automatic completion, stored freshness and independent service
  checks. No new Cloud Build image is needed for this documentation record:
  both deployed images still match executable main source `f7589c9`.

## Catalog recovery prerequisite: bind responses to requested identities

- The existing historical catalog acquisition accepted another product/item's
  identity and silently omitted unnormalizable responses. It now rejects a
  product snapshot unless its identity matches the requested product, and a
  buybox snapshot unless both item and catalog identities match the source row.
  Static errors contain no remote payload. Acquisition fails before backfill
  writes; this does not establish completeness of every optional snapshot field.
- TDD: five cases failed before implementation. The complete historical-backfill
  suite then passed **45 tests in 0.27s**, including the existing successful
  catalog case and five rejection cases checking no backfill collections were
  written. This harness uses fake gateways/storage, not live source acceptance.
  Root tests with the dedicated local replica set: **3731 passed, 9 skipped,
  356 warnings in 85.44s**. Protected stock-time tests separately with ambient
  `MONGO_URI` unset: **8 passed in 2.67s**. Ruff check/format, mypy over 501
  source files and whitespace checks passed.
- Read-only pilot counts from the approved VM/API container: 1,562 stored items,
  2,302 item formula rows, 386 catalog product snapshots and 473 buybox snapshots.
  Stored items link to 761 distinct catalog products through 1,209 items. These
  are stored counts, not verified current source inventory or a freshness proof.
- Automatic item/catalog acquisition is still unimplemented. The historical
  entrypoint derives item work from historical orders and can include claims;
  do not wire that entire operation into a catalog miss. Reuse validated
  normalization with bounded current-source acquisition and honest inventory/
  snapshot coverage. Pilot questions/orders/shipments recovery remains enabled.
- No production code or configuration changed here. Both Sheets images package
  this module and need new verified Cloud Build images before this correction
  runs there; last verified images use executable source `f7589c9`. Verify
  catalog identity rejection, valid acquisition and service health on rollout.
  Rollback is limited to the two fetch-helper checks and their regression tests;
  no schema/data reversal is needed. Keep catalog automatic recovery disabled
  until its complete acquisition/publication path is verified.

## Current item acquisition: live inventory and search omissions

- From main `3b2641a4b11d335cbacb941919ebe686c444b2f0`, performed read-only
  pilot source/Mongo comparison inside the approved VM/API container through
  the normal bootstrap gateway client. No formula request, raw payload logging,
  local production Mongo connection, writes or feature-flag changes were used.
- A bounded scan returned **1,900 unique IDs in 19 pages**, with unchanged total,
  no duplicates and count equal to the source total. Mongo contained **1,562**
  pilot items: **356 source IDs absent from Mongo**, **18 stored IDs absent from
  search**. One multiget verified HTTP 200, requested identities and pilot
  ownership for 20 missing items. Scan plus that sample took **4.928s**; this is
  acquisition latency, not formula HTTP latency or proof of all 1,900 details.
- A separate scan/comparison and detail check of the 18 omissions took **4.023s**:
  **12 HTTP-200 pilot-owned details** (5 paused, 7 closed) and **6 HTTP 404**.
  Do not delete the 18 because search omitted them, or label the six 404s
  permanently unrecoverable. Retain their known data while distinguishing
  current source availability from persisted historical evidence.
- This changes the implementation path: `run_item_detail_enrichment` currently
  loads only existing Mongo items, so it cannot discover the 356 missing IDs.
  Current-item recovery needs source discovery plus known-ID revalidation,
  bounded detail/enrichment, normalized persistence and honest per-field/current
  inventory coverage. A source-search-only equality gate or an all-history
  order backfill would not satisfy this evidence. Do not make six unavailable
  details prevent unrelated available item data from being useful.
- Source contract checked against Mercado Libre's
  [Items and searches documentation](https://developers.mercadolibre.com.mx/es_mx/items-y-busquedas):
  scan pagination for larger inventories and multiget batches up to 20. The
  live results above verify the exercised pilot paths, not every documented
  variant. Unit tests/rollback are N/A for this read-only checkpoint; the only
  repository change is this evidence record. The prior catalog identity fix
  still requires verified Sheets image builds and rollout; no new rebuild is
  required solely for this documentation. The global goal remains open.

## Item discovery now feeds the existing enrichment workflow

- Added opt-in `--discover-current-items` to `--source items-enrich`, and
  `discover_current_items=True` to the existing Python entrypoint. It scans
  current seller IDs, unions them with known Mongo IDs (including search
  omissions), then reuses existing multiget ownership validation, optional
  enrichment and canonical Item normalization. No new collection or alternate
  raw-payload persistence path was added.
- Discovery requires a numeric seller, stable total, unique valid IDs and a
  complete count; it permits short pages/reused cursors and caps the inventory
  at 10,000 IDs, scan at 201 pages/180 seconds, and detail batches at 20.
  Combining discovery with an explicit item filter is rejected. The CLI rejects
  discovery on another source before connecting. These are scan bounds, not a
  deadline for the complete enrichment operation.
- New documents are inserted only after all planned detail/enrichment/schema
  validation; a concurrent insert raises without overwriting that document.
  Existing 404 handling preserves known historical records while available
  items proceed. Dry run does not insert. No formula projection or completeness
  marker is published by this operation; follow the existing enrichment-before-
  projection ordering. `items_read` still counts existing Mongo inputs, while
  validated/planned/updated counts can include discovered new items.
- TDD: initial four real-Mongo scenarios and the CLI-scope case failed before
  their changes. Recovery plus Sheets backfill suites passed **274 tests in
  22.91s**; checks include new-item insertion, dry run, foreign source rejection,
  concurrent insert preservation, historical 404 retention and scan integrity.
  Root: **3743 passed, 9 skipped, 356 warnings in 85.92s**. Protected stock-time
  suite separately: **8 passed in 2.11s**. Ruff check/format, mypy (501 files)
  and whitespace checks passed. The persistence harness uses actual dedicated
  local Mongo and synthetic source responses, not productive acceptance.
- Not deployed or connected to formula recovery yet. Existing-item updates
  retain their previous behavior; review/guard concurrent updates before broad
  productive discovery writes. Still needed: productive discovery/enrichment,
  projected-row verification and asynchronous item/catalog job integration with
  honest coverage. Both Sheets images need verified Cloud Build refreshes and
  runtime verification for this change and the pending catalog identity fix;
  last verified deployed executable source remains `f7589c9`.
- Rollback removes the discovery flag, scanner, union/insert branch and associated
  tests, preserving the prior enrichment path. Do not delete successfully
  normalized discovered data on rollback. Pilot recovery configuration is
  unchanged and the global goal remains active.

## Item enrichment preserves concurrent and newer persisted state

- Existing-item enrichment now writes only while the complete Mongo document
  still equals the original read snapshot, using an atomic `$expr`/`$literal`
  equality guard. Checking only `last_updated` would miss concurrent status or
  enrichment changes at the same timestamp. Deleted documents are not recreated
  and unmatched writes are not reported as successful updates.
- Rejects an older detail timestamp, or a missing comparable source timestamp
  when Mongo already has one. It compares the actual source detail timestamp,
  not the canonical merged document, which could inherit Mongo's timestamp.
  Static failures require retrying from current data; no source payload is
  included. New-item insert-only behavior is unchanged.
- Real local Mongo tests reproduced concurrent price/status changes, deletion,
  stale source and undated source before the checks; they now preserve stored
  state, while an unchanged input still enriches successfully. The recovery and
  backfill suites passed **280 tests in 23.58s**. The consumer suite's fake Mongo
  matcher was extended to evaluate the guard; **8 tests passed in 0.27s**.
  Protected stock-time tests separately passed **8 in 2.29s**. No productive
  execution or deployment occurred in this unit.
- Final root suite with the dedicated local replica set: **3749 passed,
  9 skipped, 356 warnings in 87.82s**. Ruff check/format, mypy over 501 source
  files and `git diff --check` passed on the final executable snapshot.
- The enrichment batch is not an all-or-nothing transaction: a conflict can
  occur after earlier item writes succeeded. No completeness marker is emitted,
  and retries must re-read current state. This is a per-document lost-update
  guard, not automatic job scheduling, projected-row acceptance or proof that all
  required item fields are available.
- Both Sheets images need verified Cloud Build refreshes for the pending
  catalog identity, discovery and update-guard changes; deployed executable
  source was last verified at `f7589c9`. Verify dry-run/source discovery, guarded
  enrichment and independent persisted/projection results in the pilot runtime
  before claiming productive completion. Rollback removes these checks and test
  changes only; no schema or customer-data rollback is required. Keep broad
  discovery writes off if reverting the concurrent-write protection.

## Operational checkpoint: deploy item discovery and guarded enrichment

- Built and verified both images from main
  `d8b3a390291a794f109ff6f5d591bf05f2f85183`, one image per Cloud Build with
  VERIFIED provenance. Exact source/repository/build/SLSA digest checks passed:
  - API build `20122f6a-bed2-4dec-b0cc-3c147ff8ee3d`, image
    `sheets-api@sha256:a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`.
  - Worker build `21831493-15d7-4ba9-9c7e-9c110fdd6682`, image
    `sheets-worker@sha256:64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`.
  Both use the existing Artifact Registry repository prefix. Temporary build
  configs/verifier are in `/tmp/zeler-item-build.HLGhj6`.
- Removed only unused local image copies at worker digest
  `ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d` and API digest
  `c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`, after checking
  all container references and confirming Artifact Registry recovery. No volumes
  or customer records were deleted. Free space went from 5.10 to 6.11 GiB and
  ended at 5.10 GiB after both pulls.
- No recovery jobs were running or pending for the pilot at the deployment
  precheck. Dry/real preflight and capacity checks passed before each targeted
  worker/API update. Final running image IDs equal the verified digests, both
  services are healthy with zero restarts and HTTP 200 `/health`, and recovery
  remains enabled exclusively for `82453304`. No other product was recreated.
- Backups: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-d8b3a39`
  and `.pre-sheets-api-d8b3a39`. Rollback images retained locally are worker
  `603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b` and API
  `f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`.
  Restore only the affected image line, preserve the pilot environment and
  compatible validators, and verify health. Keep broad item discovery writes
  off if reverting their guard. Deployment health is not formula acceptance.

## Item inventory uses its authorized gateway client

- The first productive discovery/enrichment dry run failed on its first scan:
  HTTP 403 after 0.885s, no writes. A narrow follow-up confirmed the gateway's
  `out_of_scope` response. Registry seeds authorize `/users/*/items/search` for
  bootstrap, not Sheets; Sheets retains detail/enrichment scopes.
- The existing entrypoint now accepts a separate inventory gateway. The CLI
  creates the bootstrap client only when discovery is requested, sharing the
  existing KMS client; all detail/enrichment calls stay on Sheets. No registry
  scope, OAuth token, user authorization or module permission was bypassed or
  expanded. Four routing/persistence cases failed before this change, then
  passed with explicitly separate source clients; two CLI wiring cases cover
  discovery on/off. The focused six cases passed in 0.91s.
- These routing changes are newer than the deployed `d8b3a39` images. Both
  Sheets images need another verified build/rollout before claiming the normal
  CLI discovery path works productively. The operator-only routed dry run uses
  the existing clients as a diagnostic and is not evidence that the deployed
  CLI already contains this fix. Rollback removes only the inventory-client
  parameter/wiring and its tests; no data/schema reversal is needed.
- Root verification with the dedicated local replica set:
  `MONGO_URI='<dedicated local replica set>' uv run pytest --tb=short` returned
  **3751 passed, 9 skipped, 356 warnings in 87.10s**. The protected stock-time
  suite separately passed **8 tests in 1.96s**. Ruff check/format, mypy over
  501 source files and whitespace checks passed. Productive full enrichment
  remains a read-only diagnostic in progress; this is not persistence or
  formula acceptance.

## Verified inventory-routing images await rollout

- Routing fix and verification are pushed at main
  `016e6bdc7729b95e673caf30df6a2b09796074f7`. Both single-image VERIFIED builds
  succeeded and passed exact repository/source/build/SLSA digest verification:
  - API: build `74f1bed4-1600-462c-b75f-f21e8d40a2e0`, image
    `sheets-api@sha256:d85cbc4e027662461a359c56e0c069293306a6c2534c8ad6fc4fc0475b2c4a54`.
  - Worker: build `cc83f765-0c73-4e65-9e2a-2d2acf4777c0`, image
    `sheets-worker@sha256:6c406b58df0e084a290c194fb45f01f07bf19c0ff5fff3a56be93264ff82e399`.
  Both use the existing Artifact Registry prefix. Configs and verifier are in
  `/tmp/zeler-inventory-route-build.26vQkB`.
- Not deployed at this checkpoint. The current worker is executing the bounded
  read-only diagnostic; do not recreate it or restart the diagnostic blindly.
  At 2026-09-08 00:00 UTC it had attempted 5,000 source calls, including 19 scan
  pages, 63 detail batches and 1,247 sale-price lookups. Acquisition was still
  running, with a 900-second operator timeout. No persistence or completeness
  proof has been produced. Resume the existing process and record its terminal
  result before deciding the next acquisition or rollout step.
- This workload cannot be adopted unchanged into a recovery job with the
  existing 240-second worker budget. Implement bounded, resumable enrichment
  before automatic inventory recovery; retain Mongo-only formula HTTP reads.
  Neither these builds nor the diagnostic replace the remaining authenticated
  52-formula, real-Sheet and current-app acceptance checks.

## Bounded item acquisition after the full-inventory timeout

- The routed productive dry run terminated with `TimeoutError` at **900.003s**:
  6,032 attempted calls (19 scans, 76 detail batches, 824 variation lookups,
  1,498 sale-price lookups, 2,996 listing-price lookups and 619 shipping-option
  lookups). No item/projection writes or completeness markers were produced.
  This is an incomplete acquisition, not proof that remaining data is absent.
  Do not repeat that full workload unchanged or place it in a 240-second job.
- `run_item_detail_enrichment(acquire_item_ids=...)` now accepts an explicit
  batch of 1–20 known or missing IDs. The operator CLI exposes repeated
  `--acquire-item-id` flags with `--source items-enrich`; dry-run remains default.
  It does not scan the inventory. Empty, duplicate, malformed, oversized or
  conflicting scopes fail before storage/network access. Only the selected
  seller/IDs are loaded; the existing `--item-id` missing-ID rejection remains.
- New items use the existing ownership/schema/enrichment checks and insert-only
  persistence. Existing documents retain the full-preimage concurrency guard;
  404s preserve history and never insert placeholders. No batch creates a
  whole-inventory freshness proof. Acquisition completes before writes within
  each batch, but writes remain per-document, not a batch transaction. Retry a
  failed batch from fresh stored state; previously completed batches need not
  be reacquired. This primitive does not itself persist a resumable job cursor,
  implement automatic scheduling or publish projected rows.
- Stricter CLI wiring tests also exposed the unfiltered discovery path passing
  `[]` where the helper requires `None`. The CLI now passes `None` for omitted
  filters. Therefore the verified `016e6bd` images above must not be deployed
  as the finished discovery/acquisition solution; they remain undeployed.
- Initial acquisition tests failed before implementation; strengthened CLI
  tests reproduced the empty-filter defect. The focused recovery/backfill run
  with dedicated local Mongo passed **301 tests in 24.25s**. It includes bounded
  scope, new-item dry-run/write, foreign ownership, concurrent insert, unrelated
  data preservation, 404 absence and retrying a failed batch without rewriting
  a completed batch. Ruff check and mypy over 501 files passed.
- Rollback removes the acquisition argument/CLI wiring, optional missing-ID
  loader behavior and its tests; retain the independent empty-filter correction.
  Never delete successfully normalized items on rollback. Both Sheets images
  need verified builds for this executable snapshot, capacity/preflight-gated
  rollout and pilot batch persistence/projection checks before runtime acceptance.
- Final root run with the dedicated local replica set: **3770 passed, 9 skipped,
  356 warnings in 85.56s**. Protected stock-time cases ran separately with
  `ZELER_RS0_TEST_URI` and no ambient `MONGO_URI`: **8 passed in 2.48s**.
  Final Ruff check/format, mypy (501 files) and whitespace checks passed.

## Operational checkpoint: deploy bounded item acquisition

- Both images were built from pushed main
  `d29ae5218efd92f229edf58f0cfbb37b8d963f96` and verified against exact connected
  repository/source/build/SLSA digest metadata:
  - API build `3e895b8e-5add-44cd-879d-299381ed5815`, image
    `sheets-api@sha256:80df92e6eb2b91e85e9b27c7700df4618b7211c814b1a013749a867ffb9c9433`.
  - Worker build `8fdf089b-1b51-4282-9580-96fdfe209e90`, image
    `sheets-worker@sha256:d885b5117058456430d060d38cc11015995d8f9bcb8172914e6298fdc8abdfe7`.
  Artifact Registry prefix is unchanged. Build configs/verifier are in
  `/tmp/zeler-item-batch-build.odBPPv`; the intermediate `016e6bd` pair was
  never deployed.
- Removed only unreferenced local worker `603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b`
  and API `f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`
  copies after checking all container references and Artifact Registry
  recoverability. No customer records or volumes were deleted. Free space
  increased from 5.09 to 6.10 GiB and finished at 5.09 GiB after both pulls.
- Queue precheck showed zero running jobs and zero pending pilot jobs. Each
  targeted deployment passed dry/real preflight, exact one-line replacement
  and 5 GiB capacity checks. Worker then API were recreated; final probes show
  both running the verified digests, healthy, zero restarts, HTTP 200 `/health`,
  with recovery still enabled only for `82453304`. Other products were untouched.
- Compose backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-d29ae52`
  and `.pre-sheets-api-d29ae52`. Previous running worker `64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`
  and API `a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`
  remain the local rollback authorities. Restore only the affected image line,
  preserve pilot configuration and schemas, and verify health. Retain normalized
  acquired data; do not revert it merely because executable code is rolled back.
- First productive bounded acquisition completed in **29.499s** (operator
  scan + dry-run + fresh acquisition/write + projection, not formula HTTP).
  A current 1,900-ID source scan found 1,562 persisted pilot items; the first
  20 missing IDs were selected in memory. Dry-run validated all 20 in 16.845s.
  Fresh write acquisition then inserted all 20 by 28.854s. Independent Mongo
  checks found 20 refreshed documents and zero violations of the live validator.
- Projecting that persisted batch wrote **24 formula rows and 24 SKU-index
  upserts**, covering all 20 items, with zero projection errors or ambiguous
  identities. Two items lacked parent-level SKU but variation rows supplied
  their identities. All 24 rows had permalink/thumbnail, six had catalog IDs
  and 22 had inventory IDs. The summary's `skipped_missing_source=18` counts
  missing diagnostic fields, not 18 failed writes; all 24 planned rows persisted.
- Read-only audit of the exact latest 20-item sync cohort found trusted shipping
  costs, listing-fee projections and fixed fees for all 20. Promotion state was
  `authoritative_absent/no_trusted_promotion` for all 20; this records persisted
  classification, not independent proof of every upstream absence. The current
  resolver returns the same empty projection for malformed/non-promotional
  sale-price responses, so audit that distinction before claiming optional
  absence is trustworthy. Six variation-detail lookups also enriched successfully.
- No inventory completeness marker was published, and the remaining inventory
  is not acquired by this one batch. Automatic item/catalog recovery, field
  availability semantics and authenticated formula/Sheet/app acceptance remain
  open. The bounded operator process is terminal; do not rerun it blindly as
  a status check because it selects and writes the next missing batch.

## Promotion absence is distinct from acquisition failure

- Sale-price acquisition now requires a well-formed positive amount, currency
  and an explicitly present `regular_amount`. An explicit null regular amount
  or a valid non-discounted price can represent absence; missing/malformed
  fields or a rejected discounted projection produce `malformed_response`, not
  `authoritative_absent`. The official
  [price contract](https://developers.mercadolibre.com.mx/api-de-precios) and
  [sale-price example](https://developers.mercadolibre.com.mx/en_us/en_us/price-apl)
  distinguish nullable regular price from missing required response data.
- Formula-row projection now carries schema-normalized enrichment state into
  `current`. Dashboard promotion cells honor that state: explicit acquisition
  failures yield `DATA_UNAVAILABLE`, and authoritative absence yields `NA`.
  A previously persisted promotion retained after a transient failure remains
  stored, but is no longer displayed as a current promotional price. Acquisition
  reasons remain available in normalized state; no raw API response is retained.
- Seven malformed-response cases initially reproduced false absence; a separate
  transient-failure case reproduced a stale promotional price being displayed.
  The corrected acquisition → projection → dispatcher suite passed **22 focused
  cases in 0.23s**. This changes an unsafe prior test expectation deliberately,
  to honor the goal's prohibition on stale data being presented as current.
- A read-only source audit of the last productive 20-item sync cohort found
  **20 well-formed responses with explicit null regular amounts**, no malformed
  required fields, and no writes. This supports absence for that cohort at the
  audit time; it does not establish freshness for every item or future queries.
- Existing rows without enrichment state retain their legacy reader behavior
  pending acquisition/reprojection; state freshness/expiry and public reason
  reporting still need full acceptance. This unit does not complete automatic
  item/catalog recovery or the 52-formula/real-Sheet/app checks.
- Not deployed in this unit. Both Sheets images require verified Cloud Build
  refreshes from the resulting executable commit, health/source verification,
  and pilot reprojection/HTTP checks. Current deployed executable source remains
  `d29ae5218efd92f229edf58f0cfbb37b8d963f96`. Rollback removes the resolver shape
  checks, projected enrichment state and promo-cell gate with their tests;
  retain acquired customer data and do not treat rollback as approval to display
  failed/stale promotion data.
- A source HTTP 404 also no longer proves promotion absence: the sale-price
  resolver records `malformed/http_404` instead of the generic fetch classifier's
  `authoritative_absent`. The new rejection case failed before this correction;
  final focused promotion/source cases passed **23 tests in 0.23s**. Other
  resources' generic HTTP classification is unchanged.
- Final root suite with the dedicated local replica set: **3779 passed,
  9 skipped, 356 warnings in 87.56s**. Protected stock-time tests separately
  passed **8 in 2.19s**. Ruff check/format, mypy (501 files) and whitespace
  checks passed. The read-model Mongo schema permits this normalized `current`
  metadata; no validator relaxation was made.
- Consumer review found a remaining separate path:
  `handlers_quality_calculator._selected_price` reads the promotion directly
  and falls back to the ordinary price for `tipo_precio=promo`. Apply the same
  availability contract there, including dependent net/margin results, before
  claiming all promotion consumers are correct. This dashboard unit alone is
  not calculator acceptance.

## Calculator shares the promotion availability contract

- `tipo_precio=promo` no longer falls back to the ordinary price when the
  requested promotional price is absent or unavailable. Explicit acquisition
  failure yields `DATA_UNAVAILABLE` in price and dependent estimated net;
  authoritative absence yields `NA` in both. Independently available shipping,
  commission, fixed-fee and total-cost cells remain available. Ordinary/base
  price selection is unchanged.
- Dashboard and calculator now share the existing promotion reader and numeric
  validation in `formulas/pricing.py`; the dashboard no longer owns a separate
  implementation. A trusted state with a missing or malformed projection is
  unavailable, not proof of absence. Legacy unmarked-row behavior remains a
  separate acquisition/reprojection obligation, and temporal freshness still
  requires the outstanding snapshot acceptance work.
- Four calculator cases reproduced stale/fallback prices before implementation.
  A fifth reproduced a trusted marker without its projection being reported as
  absence. Six state scenarios now exercise both promo and ordinary modes through
  the actual dispatcher, including preservation of valid cost totals. Combined
  calculator/core/backfill suites passed **205 tests in 0.39s**; Ruff check/format
  and mypy over 502 source files passed. No productive write occurred in this unit.
- This change and the preceding promotion acquisition fix need verified new
  Sheets API/worker images, pilot reprojection, health/source checks and formula
  HTTP acceptance. Last verified deployed executable source is `d29ae52`.
  Rollback restores the dashboard-local helper and calculator selection/output
  code with their tests; no persisted data deletion is necessary. Reverting is
  not permission to report unavailable promotional prices as actual values.
- Final root regression with the dedicated local replica set: **3785 passed,
  9 skipped, 356 warnings in 94.73s**. Protected stock-time suites separately
  passed **8 tests in 11.91s**. Final Ruff check/format, mypy (502 files) and
  whitespace checks passed; these are local verification, not productive HTTP
  or Google Sheet acceptance.

## Promotion/calculator image provenance

- Built both Sheets images from pushed main
  `ab6e01f60ad7b83402a822ef4325f0014d3bd175`, covering the promotion acquisition
  and shared dashboard/calculator reader changes. Exact connected repository,
  source, successful build and SLSA digest verification passed:
  - API build `d11f4f80-ed24-468f-ab37-2aa049c8ca87`, image
    `sheets-api@sha256:ec894447aa2eae1c5a2d0497938aa38034aafac394641fa7b4d5a1ab70aab9ff`.
  - Worker build `845acd23-c284-47ea-a9e6-334609d4ac91`, image
    `sheets-worker@sha256:1e83c732e90a78ee0464cc62453d4ce93f425c7c358a8d2b1a3a84de4bf6fe92`.
  Existing Artifact Registry prefix is unchanged. Temporary configs/verifier:
  `/tmp/zeler-promo-build.WkS0jv`.
- The local SDK process twice exited with SIGSEGV while reading artifact
  metadata. The existing builds were not restarted. Running the same verifier
  with command-scoped `CLOUDSDK_PYTHON=/usr/bin/python3` completed both checks.
  No credentials, project settings or SDK installation were changed; the
  underlying bundled-interpreter crash cause is not established.
- Before rollout, both existing services were healthy with zero restarts,
  `/health` HTTP 200 and recovery enabled only for `82453304`. There were zero
  running recovery jobs and zero pending pilot jobs. Removed only unreferenced
  local worker `64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`
  and API `a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`
  image copies after checking all containers and Artifact Registry recovery.
  No data or volumes were deleted. Root free space increased from 5.58 to
  6.59 GiB; the currently running image pair was retained for rollback.
- The worker deployment returned successful dry/real preflight, pull and
  targeted recreation, with backup
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-ab6e01f`.
  The API deployment observation handle disappeared when the execution
  environment changed; it was not restarted. A new read-only VM inspection
  proved both services running the verified `ab6e01f` digests above, healthy,
  zero restarts and `/health` HTTP 200, still enabled only for the pilot.
  Root free space after both deployments is **5.57 GiB**.
- The prior running worker `d885b5117058456430d060d38cc11015995d8f9bcb8172914e6298fdc8abdfe7`
  and API `80df92e6eb2b91e85e9b27c7700df4618b7211c814b1a013749a867ffb9c9433`
  are the rollback authorities. Restore only the affected image line, preserve
  pilot configuration and normalized data, and verify runtime health. Do not
  restore an entire older Compose backup over unrelated service changes.
- The original refresh diagnostic stopped before acquisition/writes because
  the latest-sync cohort had changed to one document. A read-only check found
  1,582 dated pilot items. Selection was changed to the 20 most recently synced
  pilot items, with a deterministic ID tiebreaker and a hard 20-document limit;
  no assumption was made that the original cohort remained unchanged.
- The bounded operator refresh then validated all 20 items in dry-run at
  **11.282s**, reacquired and guardedly updated all 20 by **21.402s**, and completed
  projection plus persisted-row checks in **22.097s**. Independent live-validator
  checks found zero invalid items and all 20 refreshed timestamps. It wrote
  24 formula rows and 24 SKU-index upserts, with zero ambiguous identities or
  projection errors. The diagnostic missing-field count was 17, not 17 failed
  writes; all 24 planned formula rows persisted.
- All 24 persisted rows carried promotion acquisition state. Reading those
  actual Mongo rows through the deployed shared promotion reader and calculator
  row function returned `NA` in all 24 dashboard promotion, calculator promo
  price and dependent net cells, matching authoritative absence. No fallback
  ordinary price was substituted. This is productive persisted-row evidence,
  not authenticated HTTP dispatcher or real-Sheet acceptance, and no whole-
  inventory completeness/freshness marker was published.
- The operator process is terminal. `/tmp/zeler-promo-refresh.py` captures the
  corrected bounded scenario; executing it again performs fresh API acquisition
  and writes and must not be used as a read-only status probe. Remaining work
  still includes full inventory acquisition, asynchronous item/catalog recovery,
  temporal availability and the complete formula/Sheet/app acceptance gates.

## Full pilot ID acquisition: independent readback

- The missing-item operator's observation handle disappeared; it was not
  restarted. A read-only check in the approved worker container found zero
  matching acquisition processes. Two fresh source scans independently found
  **1,900 current IDs**, all present among **1,918 persisted pilot items**,
  preserving 18 historical IDs outside the scan. The live Mongo validator
  rejected zero pilot items. The original final batch totals/timing were not
  captured and are not claimed here.
- There are **2,831 formula rows**, 529 carrying enrichment state. Eleven source
  publications have no formula rows. A scoped dry-run confirmed 11 missing
  parent SKUs and 10 missing variation SKUs; the projector's SKU requirement is
  an unresolved omission for consumers that query by publication ID. No SKU
  was invented, no data deleted and no whole-inventory freshness marker set.
- Persisted current-source states expose remaining field acquisition work:
  promotion: 1,890 authoritative absence, 6 unauthorized, 4 transient;
  shipping: 1,894 trusted, 5 basis mismatch, 1 transient;
  commission: 1,886 trusted, 10 basis mismatch, 2 unauthorized, 2 transient;
  fixed fee: 1,885 trusted, 9 transient, 6 unauthorized. These are stored states,
  not proof of present freshness. Zero missing IDs does not close field coverage,
  reprojection, asynchronous recovery or authenticated formula acceptance.
- The audit script `/tmp/zeler-audit-inventory.py` reads production only inside
  the approved VM/container and prints aggregates. A local SDK exit 139 during
  the second audit was followed by the same read-only check with command-scoped
  system Python, which succeeded; no acquisition writes were repeated.

## Calculator cost availability

- The calculator previously used retained shipping, commission and fixed-fee
  values even when their persisted acquisition state reported failure. It now
  propagates `DATA_UNAVAILABLE` from failed acquisition or trusted-but-missing
  numeric data into the affected cells, total costs and estimated net. Explicit
  authoritative absence yields `NA`; independently valid price/cost cells remain
  visible. Unmarked legacy rows keep their prior behavior pending reprojection
  and temporal coverage work. This does not yet fix the separate dashboard cost
  readers or validate calculator cost projections against current pricing basis.
- Strict TDD reproduced 18 failures before implementation. The parameterized
  dispatcher cases cover all three cost sources and seven state/value scenarios;
  calculator/core/backfill suites passed **226 tests in 0.49s**. Ruff check/format,
  mypy over 502 files and whitespace checks passed. Productive HTTP and real-Sheet
  acceptance remain outstanding; this code has not been deployed.
- Rollback is limited to calculator cost selection, sentinel propagation and the
  associated tests. No data rollback or deletion is required. Both Sheets images
  still have last verified source `ab6e01f`; build the affected API/worker images
  from the next verified pushed main source, verify digest/health and pilot
  cost-cell behavior before claiming runtime correction.
- Final root `uv run pytest --tb=short` against the dedicated local replica set:
  **3,806 passed, 9 skipped, 356 warnings in 90.80s**. The eight protected
  stock-time tests were then run separately with `MONGO_URI` unset and the
  explicit local `ZELER_RS0_TEST_URI`: **8 passed in 3.67s**. An earlier root run
  omitted 19 extra Mongo integration tests because the local container was
  stopped at startup; it is superseded by this fully connected run. Only
  `zeler-goal-mongo` was started, retaining its volume and leaving the older
  low-ulimit container stopped; `rs0-dev` was verified writable primary.

## Calculator preserves actual losses

- The calculator formatted estimated net with the non-negative input validator,
  turning valid losses into `NA`. Only the computed Decimal net now uses the
  signed numeric formatter; price/cost validation and unavailable sentinels are
  unchanged. No new data, schema or projection is introduced.
- Dispatcher regression scenarios first returned `NA` instead of -10 and -0.25;
  break-even already returned zero. All three now pass. The focused command
  `uv run pytest modules/sheets/tests/test_formula_handlers_quality_calculator.py
  modules/sheets/tests/test_formula_handlers_core.py
  modules/sheets/tests/test_sheetseller_backfill.py --tb=short` passed **229 tests
  in 0.42s**. Root Ruff check/format, mypy (502 files), and whitespace checks pass.
- Runtime acceptance remains pending the combined calculator release. Rollback
  touches only the estimated-net output expression and these three regression
  scenarios; no data rollback is needed. The previous cost-state correction and
  this loss fix both require the affected Sheets image release and live checks.
- Final local root regression: **3,809 passed, 9 skipped, 356 warnings in 89.58s**.
  The protected stock-time suites separately passed **8 tests in 3.39s** with
  the explicit local replica-set URI and `MONGO_URI` unset. Before release,
  read-only VM inspection confirmed both prior `ab6e01f` Sheets images healthy
  and 5,976,756,224 bytes free on root; capacity must be checked again before pull.

## Calculator release image provenance

- Built from pushed main `898c91671f72fc0941517c3b2fa947313f0c789c`, covering both
  failed-cost availability and signed estimated-net output. Each successful
  Cloud Build produced one image with `requestedVerifyOption: VERIFIED`; exact
  repository/revision, build and single-subject SLSA checks passed:
  - API build `79634177-c6c1-4a75-90bb-beb50197538a`, image
    `sheets-api@sha256:d9b86c8403e1ac27314893b04be5a5d446215957a006e8c644217061b4370641`.
  - Worker build `8c7af03d-7ab3-4313-adba-6d301588b37d`, image
    `sheets-worker@sha256:2aa013bb375c1d14c5dd516f39f472879336c923d69acf425a34be9e1c97b806`.
  Artifact Registry prefix remains unchanged. Build configs and the verifier
  are under `/tmp/zeler-calculator-build.RzLBZh`; metadata commands used
  command-scoped system Python for the previously observed SDK instability.
- Rollback authorities are the previously running `ab6e01f` API
  `ec894447aa2eae1c5a2d0497938aa38034aafac394641fa7b4d5a1ab70aab9ff`
  and worker `1e83c732e90a78ee0464cc62453d4ce93f425c7c358a8d2b1a3a84de4bf6fe92`.
  Restore only the affected image line and recreate that service if necessary;
  preserve pilot configuration, normalized data and unrelated Compose changes.
- Both targeted deployments passed dry/real preflight, exact-one Compose image
  replacement and the pre-pull 5 GiB floor. Worker recovery had zero running
  jobs before recreation; recovery configuration remained pilot-only. Backups:
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-898c916` and
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-898c916`.
  Both exact new digests became healthy with zero restarts and `/health` HTTP
  200. Free bytes after worker were 5,433,823,232; after API, **4,891,086,848**.
  Reclaim narrowly verified unused image space before any further image pull;
  no image, volume or data cleanup was performed in this release.
- A read-only check through the new worker's calculator over 2,831 actual Mongo
  rows independently checked 2,813 numeric net results. It found zero negative
  nets and zero projected failed-cost cells, so it does not prove those branches
  with live data; controlled dispatcher tests cover them. In particular, source
  acquisition failures were not yet represented in those persisted rows.
- The bounded recovery operator then scanned current source IDs and selected
  **all 17 current publications with recorded cost acquisition failures** (hard
  cap 20). It dry-validated 17, freshly acquired and guardedly updated all 17,
  verified zero live-schema violations, and updated/read back 27 formula rows.
  All 27 rows reported trusted shipping, commission and fixed-fee states; none
  of the selected 17 items retained a failed-cost state. Detail-unavailable count
  was zero, and the complete operator took **26.648s**. This is operator duration,
  not formula HTTP latency. No source failure was artificially introduced to
  exercise the unavailable branch.
- `/tmp/zeler-calculator-build.RzLBZh/recover_costs.py` performs fresh production
  acquisition/writes and is terminal; do not execute it as a status probe. This
  repair sets no whole-inventory freshness marker and does not close automatic
  item/catalog recovery, legacy projection, missing-SKU or HTTP/Sheet acceptance.
- Final read-only check through the deployed API container found **2,834 actual
  persisted formula rows**, all with independently checked numeric net arithmetic.
  None exercised a negative net or unavailable cost. This confirms the recovered
  rows are readable by the API image, not authenticated formula dispatch, Google
  Sheets execution, complete SKU coverage or present temporal freshness. Both
  deployment processes and the bounded recovery process are terminal.

## Post-calculator disk margin restored

- Removed only two unused local image references from the older `d29ae52`
  release: API `80df92e6eb2b91e85e9b27c7700df4618b7211c814b1a013749a867ffb9c9433`
  and worker `d885b5117058456430d060d38cc11015995d8f9bcb8172914e6298fdc8abdfe7`.
  Artifact Registry independently returned both exact digests before removal.
  Checks against every running/stopped container found zero image references;
  those checks were repeated immediately before the non-forced removals.
- Current `898c916` and immediate rollback `ab6e01f` API/worker images were all
  present and excluded by image ID, not merely tag. No container, volume, Mongo
  document or remote registry artifact was deleted. The two local copies remain
  recoverable by pulling their exact Artifact Registry digests.
- Root free space increased from **4,890,542,080 to 5,975,814,144 bytes**, restoring
  the 5 GiB pre-pull floor. The temporary operator
  `/tmp/zeler-clean-calculator-old.py` has explicit check/remove modes and is
  terminal; do not rerun removal as a status probe. This is operational image
  cache cleanup, not a source/schema change requiring another Cloud Build.
- Post-cleanup dry-run preflight passed, and read-only inspection confirmed both
  deployed `898c916` image digests still healthy. No deployment was performed.

## Publication-ID access without an invented SKU

- A real-Mongo regression reproduced the omitted-publication defect: an item
  without any usable SKU generated zero formula rows. The projector now creates
  one item-level row only when no parent, variation or order-line identity yields
  a row and the parent SKU is not ambiguous. Its SKU is null; the empty normalized
  key is an internal row identity, not a fabricated SKU. No entry is inserted into
  the SKU index. Existing Mongo validators accept this representation unchanged.
- When a real parent/variation SKU later appears, the old item-only row is
  replaced together with the SKU-index update in a snapshot/majority transaction.
  If the SKU is subsequently removed and no order-line identity supplies it,
  obsolete current rows and non-order-line SKU-index entries are retired in the
  same transaction. Operations are scoped to the seller and item. Canonical
  normalized items and order-line identity evidence are not deleted.
- Further failing scenarios reproduced a duplicate row after SKU removal and
  replacement of a newer projection/status. Transition checks now reject older
  projections/status observations, and a forced failure after a row write rolls
  back both read models. The actual Mongo validators are enabled in these tests.
  `uv run pytest modules/sheets/tests/test_formula_recovery.py -k
  item_without_sku_remains --tb=short` passed **10 scenarios in 2.43s**, including
  item and variation SKUs, inverse transitions and seller-scoped reads.
- Review of the inverse transition additionally reproduced loss of a newer
  status when removing the SKU. Both directions now compare against the newest
  prior status observation, not only the item-only row's observation.
- Existing dry-run/idempotence tests now count the additional non-SKU row while
  preserving the unchanged SKU-index counts. The local query double now implements
  `$ne` instead of silently ignoring it; transactional acceptance uses real Mongo,
  not an emulated transaction. Root Ruff check/format, mypy (502 files), and
  whitespace checks pass. No productive projection or deletion has occurred.
- This is not whole-inventory reconciliation or automatic item recovery. Source
  acquisition, full temporal coverage and authenticated formula/Sheet acceptance
  remain required. Build and deploy new Sheets API/worker images from the verified
  pushed source, then acquire/reproject the currently missing pilot publications
  and verify schema, row coverage and ID-based formula behavior. Last verified
  deployed source remains `898c916`.
- Rollback removes the opt-in missing-SKU row construction and the atomic identity
  transition/helper session support together with their regressions. Persisted
  source items require no rollback; do not blindly delete already-created
  item-only rows when reverting code. Restore derived rows only from the current
  normalized source and verified identity evidence.
- Final root regression with the dedicated local replica set: **3,819 passed,
  9 skipped, 356 warnings in 90.23s**. The protected stock-time suites separately
  passed **8 tests in 3.30s**. Read-only VM inspection still finds the verified
  `898c916` API/worker digests healthy; the new source is not deployed.
- Consumer audit found that `event_persistence._persist_item_read_models` also
  constructs rows independently and still requires a SKU. The consumer invokes
  this corrected backfill after acquisition only when ZelerData enrichment is
  enabled. Verify/consolidate that event path before claiming continuous no-SKU
  coverage; this unit proves the backfill and its identity transitions, not all
  future event processing or automatic missing-model recovery.
- Sanitized runtime checks found enrichment, sale-price and fixed-fee acquisition
  enabled on the current worker. Thus the existing event consumer does invoke
  the backfill after enrichment, but the earlier independent projection stage
  still needs consolidation/transition verification; no feature flags changed.

## Native item events reuse no-SKU projection

- The native event writer now routes missing-SKU items and existing item-only
  identities through the same scoped backfill used by recovery. This occurs
  before separate SKU-index writes, avoiding a partially published index during
  those transitions. Price/stockout observation recording and the established
  normal-SKU event/status controls remain in place. No new collection, worker,
  compatibility layer or formula-side MercadoLibre request was introduced.
- A real-Mongo event sequence first reproduced zero rows for a no-SKU item. The
  verified scenarios now cover no SKU → parent/variation SKU → no SKU, title and
  active/paused status changes, an injected row-write failure followed by retry,
  rejection of an older event and seller-scoped reads. They exercise the native
  writer directly, without calling the consumer's later enrichment step.
- Variation events exposed another failure: an identity transition was refused
  because variation rows intentionally lack publication pause-history scalars.
  The shared transition can now use the accepted item's status observation as
  its temporal guard for those rows, without copying publication pause-history
  scalars into a variation. Prior newer-status rejection tests remain passing.
- `uv run pytest modules/sheets/tests/test_formula_recovery.py -k
  'item_events_project_no_sku or item_without_sku_remains' --tb=short` passed
  **14 tests in 3.79s**. Event-persistence/backfill suites passed **217 tests in
  0.37s**. Their cursor double gained the actual sort/`$in` behavior needed by
  the shared reader; transaction/retry evidence comes from real Mongo.
- Root regression: **3,823 passed, 9 skipped, 356 warnings in 93.09s**. Ruff
  check/format, mypy (502 files), and whitespace checks pass. These scenarios do
  not prove every concurrent first-publication interleaving, complete inventory
  freshness or authenticated HTTP/Sheet acceptance. No production write or
  deployment occurred; the affected Sheets API/worker images still need release
  and a current pilot coverage check from the approved runtime.
- Rollback removes the event-to-backfill routing and the item-status observation
  parameter used by variation transitions, together with these event scenarios.
  Existing normalized source items require no rollback; retain derived rows and
  rebuild from current source/identity evidence if needed. Automatic recovery of
  a missing item/catalog model remains separate outstanding work.
- Protected stock-time suites separately passed **8 tests in 3.39s**. Final
  read-only runtime inspection confirms both `898c916` Sheets image digests
  remain healthy. Neither pending no-SKU source change has been deployed yet.

## Late no-SKU event reconciles the persisted winner

- A controlled real-Mongo interleaving reproduced two formula rows when an old
  no-SKU event paused immediately before its row write and a newer parent-SKU or
  variation-SKU event completed first. The canonical item was already current;
  the delayed projection alone introduced the duplicate and old title.
- The event-to-backfill path now compares the scoped source before and after
  projection and repeats from Mongo when it changed. Three unsuccessful passes
  raise a retryable failure rather than acknowledging an unsettled projection.
  This adds no collection, lock, API request or formula-side waiting.
- Both original failing interleavings now preserve one current row. A separate
  real-Mongo test verifies the three-pass contention limit and preservation of
  the latest source. The focused no-SKU/transition suite passed **17 tests in
  5.02s**; protected stock-time suites passed **8 tests in 2.29s**.
- This proves the delayed no-SKU backfill path, not every interleaving of the
  independent normal-SKU writer or standalone operator backfill. Check those
  boundaries before claiming complete concurrent identity consistency.
- Rollback removes only the bounded reconciliation loop and its three regression
  cases. It does not undo prior no-SKU support or modify normalized source data.
  No production mutation or deployment occurred. Read-only inspection confirms
  the existing `898c916` API/worker digests remain healthy; both Sheets images
  still require a verified Cloud Build release of the pending source changes,
  followed by runtime health and current pilot row-identity/coverage checks.
- Full root regression passed **3,826 tests, 9 skipped, 356 warnings in 91.12s**.
  Ruff check/format, mypy (502 files), and whitespace validation also pass.

## Late SKU event also reconciles no-SKU transitions

- Extending the same controlled Mongo interleaving in the reverse direction
  reproduced an orphan parent-SKU index and, for a variation, a duplicated old
  row after the newer no-SKU event completed. The native writer now checks for
  an item-only row after its writes and shares the bounded reconciliation helper.
- The shared backfill recognizes non-order-line SKU indexes without formula rows
  as a transition requiring transactional cleanup. Canonical source items and
  order-line identity evidence remain untouched.
- The four interleavings (both directions, parent and variation SKU), plus the
  contention budget test, passed **5 tests in 1.52s**. Native event/backfill
  regression passed **217 tests in 0.37s**. This expands the existing regression
  rather than duplicating a separate concurrency harness.
- Rollback removes the native post-write reconciliation check and index-only
  transition detection, and reverses the test expansion. It does not remove
  normalized source data or the previous no-SKU-event correction.
- No production mutation or build occurred in this unit. Pending no-SKU changes
  still require new verified Sheets API/worker images, followed by health and
  pilot identity/coverage checks. Local controlled interleavings are not evidence
  of current production coverage or all 52 authenticated formula responses.
- Root regression passed **3,828 tests, 9 skipped, 356 warnings in 90.99s**;
  protected stock-time suites passed **8 tests in 2.45s**. Ruff check/format,
  mypy (502 files), and whitespace checks pass. Read-only VM inspection again
  confirmed the exact `898c916` API/worker image digests healthy.

## No-SKU source released to pilot runtime

- Both Sheets services now run source
  `f74f3f15c450e29a4fe81485471c6875145441ad`. Each image passed the repository's
  single-subject provenance verifier against its exact connected repository,
  successful Cloud Build, source commit and immutable digest.
- API: build `5176b4bc-f2ae-4989-a82f-fb018730076c`, digest
  `ef49b4d24bf62a9e31b5e9b83fbd5ec61d3983e020775922e168e544d21e0fc0`.
  Worker: build `cf4cb05c-34ba-4c5e-a25c-9c51ea0eb0ee`, digest
  `98cabd3eaf4607a49b08102854289ff898e5359b861f3ac025efd5884ceb5c26`.
- Targeted worker-then-API deployment passed preflight before each pull,
  exact-one Compose replacement and pilot recovery configuration checks.
  Both containers became healthy with zero restarts and `/health` HTTP 200.
  No other service was recreated. The worker had zero running recovery jobs
  at its deployment gate.
- Rollback authority is the previously running `898c916` pair: API digest
  `d9b86c8403e1ac27314893b04be5a5d446215957a006e8c644217061b4370641`, worker
  `2aa013bb375c1d14c5dd516f39f472879336c923d69acf425a34be9e1c97b806`.
  Compose backups end in `.pre-sheets-worker-f74f3f1` and
  `.pre-sheets-api-f74f3f1`; restore only the affected image line, not the entire
  backup over unrelated changes. Do not roll back normalized source data.
- Pre-release scoped Mongo inspection found 1,918 stored source items, 2,834
  formula rows, 15 stored items without rows, and no item-only rows. These stored
  counts include history and do not prove the current MercadoLibre inventory.
- Free space after both pulls was 4,887,502,848 bytes, below the next-pull
  5 GiB floor. Before another release, recheck space and perform narrowly
  verified unused-image cleanup while retaining the current/rollback pair;
  do not prune volumes or infer authority to resize the disk.
- A fresh MercadoLibre inventory scan found 1,900 current items, of which 10 had
  no formula rows. A bounded operator run validated all 10 in dry-run, acquired
  and enriched them through the gateway, and persisted 12 rows (nine item-only).
  Independent live-validator queries accepted all selected source/row/index
  documents. The selected projection had no mixed item-only/SKU identity.
  All 1,900 IDs from that scan were then represented by formula rows.
- Recovery completed in **18.655 seconds** with zero unavailable item details.
  This is operator timing, not formula HTTP latency. No whole-inventory freshness
  marker was advanced; row presence does not prove every field fresh or the 52
  formulas accepted. The mutating recovery invocation is terminal and must not
  be restarted as an observation probe.
- Final read-only inspection from the API container independently found 2,846
  total rows, nine item-only rows and zero mixed identities. Five stored items
  still lack rows outside the just-scanned current inventory; no historical
  source was deleted. Both exact released digests remain healthy, zero-restart,
  with recovery enabled only for pilot `82453304`.
- This ledger-only commit does not require another image build: the intended
  runtime source is `f74f3f1` and both deployed images match it. Authenticated
  HTTP/Google Sheet acceptance and full temporal completeness remain outstanding.

## Runtime diagnosis: row coverage is not productive freshness

- Read-only execution through the deployed API container's real formula
  dispatcher exposed inconsistent availability on the pilot: `TITULO` returned
  one selected no-SKU item's title in 0.0039s and `PUBLICACIONES` returned 2,846
  rows in 0.1880s; `CALCULADORA` for that same item and `CALIDAD` raised
  `FormulaDataUnavailableError(read_model="item_formula_rows")` in 0.0147s and
  0.0021s. Only aggregate outcomes were printed. These are internal dispatcher
  timings, not authenticated HTTP acceptance, and returned values were not
  independently certified as temporally complete.
- The productive marker exists but has no `valid_until`. Calculator/quality
  enforce its coverage before reading rows; core title/publication handlers do
  not enforce that same gate. Runtime `IMPLEMENTED_MODELS` excludes
  `item_formula_rows`, so an unavailable item projection has no automatic worker
  implementation despite its presence in `RECOVERABLE_MODELS`.
- A second scoped read verified the selected canonical item's
  `last_meli_sync_at` was only 265.6 seconds old, while its formula row has no
  source-sync receipt. The row's `updated_at` was about 42 days old: the builder
  intentionally derives it from source modification time, not acquisition time.
  Do not reinterpret that old modification timestamp as proof the recently
  acquired source is stale, or use projection execution time as proof of a new
  MercadoLibre acquisition. The initial probe used nonexistent `synced_at`;
  its null result was corrected by reading canonical `last_meli_sync_at`.
- Next implementation must connect a trustworthy per-publication acquisition
  receipt and complete selected-identity validation to bounded automatic item
  recovery. Keep aggregate inventory completeness distinct from selected-row
  availability, preserve per-field acquisition failures, and cover partial,
  expired, future-dated and missing evidence. Do not bypass or advance the
  global marker merely to make the calculator pass. Existing 20-item acquisition
  and Mongo recovery queue are the starting points, not a second queue/worker.
- No runtime mutation, marker renewal or code change occurred in this diagnostic
  unit. Verification is the real-container read above plus inspection of the
  builder, handlers and recovery allowlist; additional test execution is N/A for
  this evidence-only record. Rollback removes only this ledger section.

## Explicit calculator IDs enter bounded item recovery

- Calculator freshness failures now carry normalized requested publication IDs
  to the existing API recovery admission path. Requests are split into batches
  of at most 20 under the existing one-second total admission budget; each batch
  has a deterministic seller/model/sorted-ID key. Full-inventory/date-range item
  requests are rejected rather than admitted to an unimplemented scan workflow.
- The existing recovery worker handles these explicit batches using the normal
  detail gateway and the previously verified bounded enrichment helper, with
  promotion/fixed-fee acquisition enabled. It projects only scoped source items
  actually present in Mongo; incomplete acquisition remains pending for the
  existing retry policy. No new collection, worker or formula-side API call was
  added. Seller admission, active-job capacity and cooldown controls are reused.
- Ownership is checked before acquisition and again before projection. A lost
  lease is not acknowledged as completed. Existing source acquisition retains
  its full-preimage compare-and-swap guards; this unit does not make remote
  acquisition/source persistence and job completion one atomic transaction.
  Independently obtained source data can remain after lease loss. No inventory
  freshness marker is published by this selected-ID workflow.
- Failing tests first showed the absent request/metadata path and missing
  calculator scope. Real-Mongo admission/claim tests now cover duplicate batches,
  complete/partial acquisition, loss of lease before projection, ID/batch bounds
  and rejection of item date ranges: **4 passed in 0.98s**. Acquisition/projection
  calls are controlled doubles in those queue tests, not proof of a new live
  MercadoLibre run; the underlying helper's earlier local/live evidence remains
  separate. The calculator handler test verifies propagation of selected IDs.
- Root regression before the two added lease-loss parameter cases passed
  **3,831 tests, 9 skipped, 356 warnings in 93.15s**; all four final queue cases
  passed separately. Protected integration: **8 passed in 3.28s**. Ruff, format,
  mypy (502 files), and whitespace checks pass.
- The global calculator read gate is deliberately unchanged. Completion of this
  acquisition job does not yet make that read productive: per-publication source
  receipts, selected-row completeness/expiry checks and aggregate recovery still
  need implementation. Do not claim this unit fixes the full observed calculator
  failure or all 52 formulas.
- Rollback removes the item request/worker dispatch, API admission and calculator
  metadata propagation together with these tests. Keep normalized data; disable
  item job claims before reverting a deployed worker with pending item jobs.
  No runtime mutation or deployment occurred. Sheets API and worker require new
  verified images after the read-side work, with pilot recovery-to-read and health
  verification; retain the current `f74f3f1` runtime pair meanwhile.

## Selected calculator reads accept source-bound projection evidence

- The shared backfill now stamps complete item projections with canonical
  acquisition time (`last_meli_sync_at`), a deterministic BSON source fingerprint,
  and the number of projected rows. It does not substitute source modification
  time or the backfill's execution time for acquisition evidence. Ambiguous or
  partially identified variation sets do not receive the stamp. The optional
  `source_snapshot` schema bounds its shape and row count.
- When inventory freshness is unavailable, CALCULADORA with explicit IDs can
  read these source-bound rows from Mongo. Each selected publication must have a
  source acquired within 15 minutes, matching fingerprints/timestamps on all its
  rows, and the complete expected row count. Missing or invalid selections retain
  explicit item IDs for the existing asynchronous recovery path. No MercadoLibre
  request, projection, queue wait or marker write occurs in this read.
- Existing productive inventory-marker reads are preserved; whole-inventory
  requests still require that proof. This does not establish aggregate freshness,
  per-publication fallback for all other formulas, or partial-success output when
  one publication in a multi-publication selection is unavailable.
- Source-stamped calculator rows additionally require recent acquisition states
  for costs/promotion. Missing, expired or future-dated field evidence becomes
  DATA_UNAVAILABLE and propagates to dependent totals; an independently acquired
  current price remains usable. This is not a claim that all legacy unmarked
  rows or every pricing-basis validation path has been migrated.
- The failing real-Mongo case now reads two variations without a global marker
  despite a 40-day-old source modification date. Five negative cases reject an
  expired/future acquisition, missing row, changed source or absent receipt.
  These run with the actual formula-row Mongo validator. Four cost-age cases
  separately verify fresh, expired, future and absent evidence. Existing absence
  tests now inspect structured read-model metadata rather than require the old
  global-marker wording for a selected-row error.
- Focused calculator/recovery/backfill regression passed **381 tests in 26.10s**;
  protected integration passed **8 tests in 2.09s**. Ruff check/format, mypy
  (503 files), and whitespace checks pass. General test runs encountered Python
  segmentation faults in unrelated collection/routing paths; a separate allocator
  diagnostic run is pending and must not be counted as a pass before completion.
- No runtime mutation or deployment occurred. The current verified `f74f3f1`
  API/worker digests remain healthy. Before release, validate/apply the bounded
  row schema from the approved runtime, recover disk margin, build both affected
  images, and prove the pilot recovery-to-selected-calculator read end to end.
  Rollback removes stamping and the selected-read fallback with their tests;
  retain normalized data and existing receipts rather than deleting history.
- The final root run with command-scoped `PYTHONMALLOC=malloc` and the dedicated
  local replica-set URI passed **3,843 tests, 9 skipped, 356 warnings in 97.51s**.
  No dependency/interpreter or production configuration was changed. This proves
  the suite under that allocator setting, not the cause of the intermittent
  interpreter crashes. The normal allocator run remains unproven for this unit.

## Recovery-to-calculator integration verified before release

- A new real-Mongo test starts with an unavailable calculator selection, uses
  the API's real queue admission path and real recovery worker, and runs the
  actual acquisition, normalization, projection and source-bound reader. Only
  the external MercadoLibre boundary is simulated; source, row and SKU-index
  collections use the real repository validators.
- The first calculation/admission makes no upstream calls. After worker
  completion, the second calculation returns the newly acquired title/price and
  authoritative zero seller-shipping cost without further upstream calls.
  Simulated unavailable promotion/fee endpoints remain DATA_UNAVAILABLE in cost
  cells and dependent totals; no global freshness marker is written.
- Focused integration: **1 passed in 0.54s**. Full recovery/calculator suites:
  **231 passed in 32.94s**, with command-scoped `PYTHONMALLOC=malloc`. Ruff,
  format, mypy (503 files) and whitespace checks pass. Runtime implementation
  is unchanged from `61f1aa3`; its earlier 3,843-test root result remains separate
  from this additional test. This is not authenticated live HTTP acceptance.
- Rollback removes only the new integration test and this evidence record.
  Pending runtime changes still require release of Sheets API and worker, then
  a real pilot recovery-to-read check from the approved runtime context.

## Disk margin recovered for source-freshness release

- Removed only the unused local `ab6e01f` API/worker image references:
  `ec894447aa2eae1c5a2d0497938aa38034aafac394641fa7b4d5a1ab70aab9ff` and
  `1e83c732e90a78ee0464cc62453d4ce93f425c7c358a8d2b1a3a84de4bf6fe92`.
  Both exact digests were verified present in Artifact Registry, so these local
  copies are recoverable. Zero running or stopped containers referenced them.
- The current `f74f3f1` pair and immediate rollback `898c916` pair were present
  and excluded by image ID. Those checks were repeated immediately before
  non-force removal. No volume, data, container or remote artifact was deleted.
- Free space increased from **4,885,688,320** to **5,970,952,192 bytes**. The
  removal invocation completed successfully and must not be repeated as a status
  check. Recheck capacity before each subsequent image pull.
- Post-cleanup dry preflight passed. Both exact `f74f3f1` running digests remain
  healthy with zero restarts; no service was recreated during this maintenance.

## Source-bound calculator recovery released and verified on the pilot

- Sheets API and worker now run source commit
  `f51c374f2f1c4b3faa23c45f533f5beacfa074fc`. Both Cloud Builds succeeded and
  the repository provenance verifier bound each immutable image to that source:

  | Service | Build | SHA-256 image digest |
  | --- | --- | --- |
  | sheets-api | `c7e4b577-4a4a-492b-92fe-983ee4ebb002` | `c187698e5522dbf50952a6577511601143e25346bcfb836e5d494c7fa1f4be87` |
  | sheets-worker | `a3c7f44b-8799-44c4-8a23-eda1c6d17754` | `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512` |

- From the approved VM/container context, the live formula-row validator matched
  the prior schema exactly. All **2,846 rows** passed the proposed schema before
  applying its optional `source_snapshot` property. The prior validator/options
  were saved exclusively with mode 0600 under the protected repairs directory:
  `/var/lib/zeler-platform/repairs/formula-source-snapshot-f51c374.json`.
  The old-schema and zero-invalid-row guards were repeated before `collMod`, and
  the resulting validator matched the proposal. No source records were deleted.
- Deployment ran worker first, then API, with capacity/preflight, exact-one
  Compose replacement and target-only recreation. Both services reached healthy,
  HTTP `/health` **200**, with **zero restarts**. Recovery remained restricted to
  seller `82453304`; the worker had zero running recovery jobs before recreation.
- The real pilot check selected one stored item-only publication. Its initial
  internal CALCULADORA dispatch returned DATA_UNAVAILABLE in **0.0150s**. An
  explicit-ID request entered the normal queue, and the running worker completed
  job `0732ce039d50b06bbaeecbfe2ba283ff6c4d421968c7f2a9ac8320f1e60a561b`
  in **one attempt**, using the real gateway/acquisition/projection paths.
  A subsequent internal API-container dispatch returned **one row**, numeric
  price, and **zero DATA_UNAVAILABLE cells** in **0.0163s**. The seller's global
  freshness-marker hash was unchanged. No second operator worker or synthetic
  MercadoLibre response was used. The protected job receipt is
  `/var/lib/zeler-platform/repairs/calculator-recovery-f51c374.json`; do not
  re-enqueue this completed check merely to inspect its status.
- This demonstrates one real selected-item recovery and subsequent Mongo read,
  not independent correctness of every returned cell, authenticated HTTP
  acceptance, p95 latency, whole-inventory freshness, or all 52 formulas. The
  Google Sheet/app acceptance and broader recovery/freshness work remain open.
- Rollback authority is the previously running `f74f3f1` pair: API
  `ef49b4d24bf62a9e31b5e9b83fbd5ec61d3983e020775922e168e544d21e0fc0`, worker
  `98cabd3eaf4607a49b08102854289ff898e5359b861f3ac025efd5884ceb5c26`.
  Compose backups end in `.pre-sheets-api-f51c374` and
  `.pre-sheets-worker-f51c374`; restore only the intended image line, not the
  entire old Compose file. Before reverting item job support, stop new item
  admissions/claims and account for pending jobs. Preserve normalized data and
  source receipts; do not blindly restore the validator backup.
- Free disk was **5,427,470,336 bytes** after the worker and **4,884,602,880 bytes**
  after the API. Both pulls passed the 5 GiB pre-pull floor, but another pull now
  requires recovering capacity first. No further build is required for this
  source: both affected images match it. This evidence-only update changes no
  runtime implementation and does not itself require rebuilding either image.

## Mixed calculator selections retain verified publications

- CALCULADORA no longer discards every verified publication when another
  selected publication lacks a trustworthy projection. The source-bound reader
  returns only complete, recent, seller-owned publication groups and separately
  identifies unavailable IDs. It still rejects an entirely unavailable selection
  or an exceeded query budget; it never returns surviving rows from an incomplete
  variation group as a complete publication.
- Missing selected publications produce their ID plus DATA_UNAVAILABLE cells,
  not NA. Metadata reports the missing IDs and the explicit
  `missing_incomplete_or_stale_projection` reason. The same missing-publication
  representation applies to the existing inventory-marker read path. This does
  not migrate that path's freshness proof or add whole-inventory recovery.
- An optional internal recovery instruction accompanies the result. The API
  uses the existing bounded queue admission with the authenticated seller and
  only unavailable IDs, then retains the matrix even if admission fails.
  `recovery_requested` reports the admission outcome. No inline MercadoLibre
  request or worker wait was added. Apps Script's existing envelope reader
  returns the matrix unchanged; no new frontend or add-on mechanism is needed.
- The initial mixed-selection test failed with the previous whole-selection
  exception. Authenticated ASGI tests also failed before the result/admission
  path existed (after correcting their missing required request argument).
  Real-Mongo cases now retain two verified variations while excluding an absent,
  expired, foreign-seller or incomplete second publication. ASGI checks use a
  controlled dispatcher/queue and prove retained values for successful and
  rejected admission, with the authenticated seller scope. These are local
  boundary tests, not productive HTTP or live Google Sheet acceptance.
- Focused calculator/recovery/API suites: **267 passed in 32.73s**. Protected
  integration: **8 passed in 2.96s**. Ruff check/format, mypy (503 files), and
  whitespace checks pass. A root attempt with `PYTHONMALLOC=malloc` crashed in
  pytest collection; it is not a pass. The subsequent normal-allocator root run
  passed **3,850 tests, 9 skipped, 356 warnings in 96.68s** with the dedicated
  local replica-set URI. This does not establish the interpreter crash's cause.
- Rollback removes the partial-result/admission changes and associated tests/docs
  together; it needs no Mongo schema or data rollback. No production mutation
  occurred in this unit. Sheets API needs a new verified image and mixed-selection
  runtime verification; the already deployed worker supports explicit-ID jobs.
  Before any pull, recover the previously observed disk margin and recheck it.

## Mixed-selection release verified with two real pilot publications

- Sheets API now runs source `02adf597bacf943088c9af1a2e0e1eb2bc14e553`,
  built once by `e8ebc36c-6961-4b7b-9552-fc9d820a5587`. The repository
  provenance verifier bound its immutable digest
  `f8ccf361eb7e54639d6a6a6128ea4e7841c1e519b98bd37b8ff8dbdf8c633cfe`
  to that exact source before deployment. Target-only API deployment passed
  preflight, reached healthy, returned HTTP `/health` 200 and had zero restarts.
- Removed only the unused local API image
  `d9b86c8403e1ac27314893b04be5a5d446215957a006e8c644217061b4370641`.
  That exact digest remains in Artifact Registry and is recoverable. Checks
  across all running/stopped containers found zero references; the current
  `f51c374` and prior `f74f3f1` pairs were present and protected. Guards were
  repeated immediately before non-force removal. No container, volume, source
  data or remote artifact was deleted. Free space increased from
  **4,883,820,544 to 5,426,511,872 bytes**; dry preflight then passed.
- From the approved API-container context, the probe selected two existing
  pilot item-only publications without source receipts. The normal running
  worker recovered the first through real gateway/acquisition/projection paths.
  An internal CALCULADORA dispatch then returned two rows in **0.0048s**:
  the first retained its numeric price, while the second contained its ID plus
  14 DATA_UNAVAILABLE cells. Metadata reported one missing publication, and the
  actual API admission helper queued only that second ID.
- Both jobs completed in **one attempt each**:
  `4a40f97ce35343dcfd32ce21f0e1bae8f45421ae58f37624fa874095c4fcc9f4` and
  `825719a75e5df1045e89f09acd459fc559346ccb56874ec4963e00727f693fd9`.
  The final internal dispatch returned **two rows**, both numeric prices,
  **zero partial misses and zero DATA_UNAVAILABLE cells**, in **0.0048s**.
  The seller's global freshness-marker hash remained unchanged. The protected
  receipt is `/var/lib/zeler-platform/repairs/calculator-mixed-02adf59.json`;
  preparation and second admission are completed operations, not status probes.
- This is real runtime recovery and Mongo-read evidence, not authenticated
  productive HTTP, live Google Sheets acceptance, a p95 measurement, independent
  verification of every cell, or proof of whole-inventory freshness. No second
  operator worker, synthetic upstream payload or production validator change
  was used. The full 52-formula mission remains open.
- The worker was not recreated: digest
  `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512`
  remained healthy with zero restarts. API rollback is the previously running
  `c187698e5522dbf50952a6577511601143e25346bcfb836e5d494c7fa1f4be87`;
  the Compose backup ends in `.pre-sheets-api-02adf59`. Restore only that image
  line and verify API health/read behavior; preserve recovered data and jobs.
- Post-deployment free space was **4,883,578,880 bytes**. Another pull requires
  recovering capacity and passing preflight again. The API image now matches
  the intended runtime change; this evidence-only commit needs no new build.

## Item recovery completion requires a readable projection

- While tracing full-inventory recovery prerequisites, real-Mongo fault tests
  proved that a job could report completed after its source receipt disappeared
  or its source changed following projection. The calculator correctly refused
  those rows, so the job's success did not prove a productive subsequent read.
- Before completing an acquired item batch, the worker now invokes the existing
  source-bound projection reader for every requested ID. Missing, incomplete,
  expired or source-mismatched groups retain the existing retryable
  `source_incomplete` state. No new collection, queue or global marker is added.
  Optional field unavailability remains distinct from missing projection proof.
- The fault tests failed with completed instead of pending before the fix.
  After removing the injected fault, the same jobs retry and complete on attempt
  two; the actual calculator then reads their recovered projections. Only the
  upstream boundary is simulated in these real-Mongo integration cases. The
  bounded-admission/lease tests now use the real projector instead of a no-op.
- Focused recovery/calculator suites: **237 passed in 32.37s**. Protected
  integration: **8 passed in 2.61s**. Ruff check/format, mypy (503 files), and
  whitespace checks pass. Normal-allocator root regression with the dedicated
  local replica-set URI: **3,852 passed, 9 skipped, 356 warnings in 95.65s**.
- Verification precedes queue completion; it is not atomic with concurrent item
  writers and does not promise permanently fresh rows. Reads continue to check
  their own source evidence. Resumable whole-inventory acquisition and aggregate
  readiness are still required; a successful selected batch does not prove them.
- Rollback removes this worker-side verification and its regression cases, with
  no schema or data reversal. No runtime mutation occurred. Sheets worker needs
  a new verified Cloud Build image and a real recovery-to-read smoke after deploy;
  preserve the existing API and recover disk margin before another pull.
  Read-only runtime inspection still found the `f51c374` worker digest
  `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512`
  healthy with zero restarts; it does not yet contain this completion check.

## Inventory acquisition resumes through the existing recovery queue

- Item-model misses without explicit IDs can now admit one coalesced inventory
  request per seller through the existing bounded API queue path. Authentication,
  seller allowlists, capacity admission and cooldown remain in place. No formula
  executes a MercadoLibre call or waits for discovery/acquisition.
- A worker claim first runs the existing bounded discovery (10,000 IDs maximum,
  201 pages, 180 seconds) and checkpoints its sorted IDs. Subsequent claims each
  acquire/project at most 20 publications through the existing source-bound
  verification path. Mongo stores the next offset; a restarted worker resumes
  there without repeating discovery or earlier successful batches.
- Checkpoints require the current unexpired attempt token, immutable discovered
  IDs and forward progress bounded to one batch. They release the lease and reset
  the per-batch attempt counter. HTTP-transient failures retain the offset for
  retry. Exhausted/source-incomplete batches record their IDs and advance so later
  publications can still be acquired; any recorded unavailable batch makes the
  final job failed/source_incomplete, not completed. Storage/authorization failures
  retain the existing fail-closed behavior. Reopening a terminal request clears
  its prior scan/progress while preserving the existing cooldown.
- Failing tests first demonstrated missing inventory admission/checkpoints and,
  separately, that an exhausted batch stopped all subsequent acquisition. The
  real-Mongo 21-publication tests now cover normal restart, a transient final
  batch, exhausted first-batch recovery followed by a successful later batch,
  and expired-lease checkpoint rejection. They use actual acquisition/projection
  code with simulated upstream responses, not production or live Sheets evidence.
- This unit deliberately writes no aggregate freshness marker. Completion means
  that acquisition finished; a new full-inventory read must still prove scan age,
  inventory membership and current source-bound completeness. That reader is
  pending, so do not deploy this admission path as a claimed full-inventory fix.
  Existing selected-ID reads continue to use independently verified projections.
- Rollback removes inventory request/admission/checkpoint/worker dispatch together
  with these tests; preserve acquired data and account for pending inventory jobs
  before reverting worker support. No runtime mutation occurred. API and worker
  will need verified builds after the aggregate reader is ready, plus pilot
  restart/recovery-to-inventory-read verification and disk preflight.
- Final focused inventory scenarios: **4 passed in 1.74s**. Normal-allocator root
  regression: **3,856 passed, 9 skipped, 356 warnings in 95.32s**. Protected
  integration was run separately: **8 passed in 3.16s**. Ruff check/format,
  mypy (503 files) and whitespace checks pass. The earlier 3,855-test run preceded
  the exhausted-batch correction and is not the final evidence.
- Read-only runtime inspection confirmed the existing API
  `f8ccf361eb7e54639d6a6a6128ea4e7841c1e519b98bd37b8ff8dbdf8c633cfe`
  and worker `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512`
  digests remain healthy. Neither contains this inventory workflow; retain them
  until the read-side proof and verified replacement images are ready.

## Whole-inventory calculator and quality reads verify recovered membership

- CALCULADORA without selected IDs and CALIDAD now have a Mongo-only inventory
  fallback when the existing marker gate is unavailable. It requires a valid,
  seller-owned enumeration observed within 15 minutes, then verifies each member's
  source-bound rows independently. Unlisted stored rows are excluded. A verified
  empty enumeration returns an empty result; absent, malformed, expired or future
  evidence remains formula-level DATA_UNAVAILABLE.
- Discovery records the time its worker claim began. Subsequent batches do not
  renew that observation. Reopening terminal recovery retains the old enumeration
  for reads within its original validity while clearing acquisition progress;
  the next worker claim rediscovers and replaces it. A failing regression proved
  that clearing the enumeration on reopening had unnecessarily hidden valid data.
- During acquisition, verified publications remain visible and each unavailable
  member has its ID plus DATA_UNAVAILABLE cells. `partial_misses`, unavailable IDs
  and an explicit reason describe the gap. `inventory_rows_complete` certifies
  row coverage only, not every field: independently unavailable costs remain
  visible as DATA_UNAVAILABLE. Recovery instructions coalesce into the existing
  inventory request instead of spawning duplicate per-ID jobs during the sweep.
- Real-Mongo 21-publication tests exercise both formulas before, during and after
  normal/retried/partially failed acquisition, plus read continuity when reopening
  and a subsequent fresh scan. No read makes an upstream call. Additional cases
  cover verified empty inventory, absent/expired/future time, duplicates, wrong
  seller and malformed offset. Existing ASGI absence tests now expect the new
  enumeration-unavailable reason. Upstream responses in these tests are simulated;
  this is not productive HTTP or live Google Sheets acceptance.
- Final focused inventory checks: **11 passed in 2.58s**. The earlier broader
  recovery/API/calculator run passed **280 tests in 35.73s**, before the reopen
  continuity correction. Protected integration: **8 passed in 3.25s**. Static
  checks pass; final root evidence is recorded below.
- Rollback removes this inventory reader/handler fallback and observation-time
  changes together with their tests/docs; preserve acquired data. Existing marker
  reads are not migrated by this unit, and marker-only operational readiness
  reporting still needs reconciliation with this new evidence path. No global
  freshness marker, production data change or deployment occurred. Both API and
  worker require verified replacement images and a live inventory sweep/read
  before claiming this path is operationally accepted.
- One final-root attempt reported **3,862 passed and one failure**: the Repricer
  import subprocess exited with signal 11, without a Python assertion from this
  change. Its isolated test subsequently passed **1 test in 0.46s**, without any
  Repricer, dependency or interpreter change. That isolated pass does not turn
  the failed root attempt into a full-suite pass or establish the crash's cause.
- The following normal-allocator attempt also segfaulted, this time during
  Publicador/FastAPI route construction. The final diagnostic root run with
  command-scoped `PYTHONMALLOC=malloc` passed **3,863 tests, 9 skipped, 356 warnings
  in 102.52s**. No interpreter, dependency or production configuration was changed.
  Normal-allocator full-root acceptance remains unproven for the final continuity
  change. The final targeted inventory cases pass under the normal allocator.
- Read-only runtime inspection still found API
  `f8ccf361eb7e54639d6a6a6128ea4e7841c1e519b98bd37b8ff8dbdf8c633cfe`
  and worker `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512`
  healthy. Both must be rebuilt from the intended source before deployment of
  this unit; deploy the worker before exposing the new API recovery admissions.

## Inventory recovery images deployed; pilot sweep started

- API and worker now run source `b74b758a7a7ec1ee826ddd660b7d2ab40839d9f9`.
  Each Cloud Build produced one image and passed exact-source provenance
  verification. Worker build `14f50a78-cb48-429e-b706-e1af06d84fd8` produced
  `50c87edc6503317b283c625a965fd46690dd304af1829a56a77c8fe66855f651`;
  API build `cbcff1fe-1b02-4d38-8dbd-c6ea9f0865ed` produced
  `02b4788b7da0d3ec46d766473f96590ded22fc8e1769cfea33ca48f2a6bc3d0a`.
  The worker was deployed first. Authoritative container inspection confirmed
  both exact digests healthy with zero restarts; the API deploy also verified
  HTTP `/health` 200. No other product was deployed.
- Before pulling, narrowly scoped cleanup removed only two unused local image
  references: API `ef49b4d24bf62a9e31b5e9b83fbd5ec61d3983e020775922e168e544d21e0fc0`
  and worker `2aa013bb375c1d14c5dd516f39f472879336c923d69acf425a34be9e1c97b806`.
  Both were checked against all containers and remain recoverable from Artifact
  Registry. Current and rollback images were protected. Free root space rose
  from 4,881,522,688 to 5,966,884,864 bytes; each deployment enforced the 5 GiB
  pre-pull gate. After the API deployment, 4,880,760,832 bytes remained. No data,
  volumes or remote artifacts were deleted.
- Rollback authorities are the prior running API
  `f8ccf361eb7e54639d6a6a6128ea4e7841c1e519b98bd37b8ff8dbdf8c633cfe`
  and worker `55e10b4593b0ccb5df81a513daf9ce10be26c5da1516d85e7b7b6fb8a72f8512`.
  Compose backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-b74b758`
  and its `pre-sheets-worker-b74b758` counterpart. A worker rollback must account
  for the new inventory job before removing inventory support; preserve acquired
  data. Recover disk margin before any further pull.
- The approved API-container probe admitted exactly one pilot inventory job,
  `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`, through
  the actual private API admission helper. Its exclusive mode-0600 receipt is
  `/var/lib/zeler-platform/repairs/inventory-b74b758.json`. Before admission,
  internal CALCULADORA/CALIDAD both returned DATA_UNAVAILABLE in 0.0024/0.0020s.
  The global marker fingerprint was unchanged. Subsequent probes must observe
  this same job rather than re-admit it. This is internal runtime evidence, not
  authenticated HTTP, all-field correctness or real Google Sheets acceptance.
- The supervisor waits only when idle, not between successful batches. Live
  sweep duration and source/scan freshness still need measurement: completing
  acquisition alone does not prove that the whole inventory is readable within
  its 15-minute evidence window. No claim of full-inventory acceptance yet.
- At 228.73 seconds the same live job had discovered **1,900 publications** and
  checkpointed offset **120**, with **20 IDs** conservatively recorded for one
  exhausted batch. Read-only diagnosis of that batch found 19 matching receipts
  and one missing receipt; the latter had two skipped variation SKUs, with no
  item-SKU or variation-identity ambiguity. This is incomplete projection
  evidence, not proof that MercadoLibre cannot recover those fields. The worker
  advanced after three attempts rather than blocking later batches.
- Internal whole-inventory reads during the sweep returned verified rows plus
  explicit missing-publication cells in **0.8222–1.5402 seconds** across observed
  samples. At the latest sample CALCULADORA reported 1,801 missing publications
  and CALIDAD 1,781; they ran sequentially while another batch published, so these
  are separate observations, not an atomic cross-formula snapshot. Both reported
  incomplete inventory coverage; the global marker fingerprint remained unchanged.
  The sweep is still running and its complete/fresh end state is unproven.
- Follow-up: inspect the partial-variation projection contract and measure the
  full sweep against the 15-minute window without extending observation times
  artificially. The documentation-only commits after `b74b758` do not affect
  service images; no further build is needed for this evidence record alone.
- Continued observation of the same job reached offset **560/1,900** at
  **550.17 seconds**, still running with one exhausted 20-publication batch.
  Both formula reads then reported **1,341** missing publications, 2,167 output
  rows including placeholders, and incomplete coverage in 1.4453/1.4016 seconds.
  Marker fingerprints remain unchanged. The observed duration makes completion
  inside the 15-minute window doubtful, but expiration has not yet been observed.
- Code inspection located the partial-variation cause: the SKU-index builder
  omits variations lacking SKU, the formula-row builder consumes those index
  documents, and backfill withholds its receipt when only some variations are
  represented. A fix must preserve each identifiable variation without inventing
  or inheriting a SKU, keep SKU lookup indexes truthful, and reconcile obsolete
  row identities when SKU availability changes. Both backfill and native event
  persistence consume the builder; modifying only the receipt condition would
  falsely certify incomplete data. No such relaxation was made.
- A new normal-allocator root attempt at `4e50c94` exited **139/SIGSEGV** during
  `test_publicador_health_registers_mongo_rabbitmq_and_registry_checks`, inside
  Pydantic/FastAPI route construction. The exact isolated test subsequently
  passed **1 test in 0.19s** with no code, dependency or allocator change. This
  does not establish the native crash's cause or full-root acceptance; retain
  the earlier explicitly qualified `PYTHONMALLOC=malloc` evidence. No product
  code or runtime configuration was changed during this observation unit.

## Identified variations remain readable without a SKU

- A failing real-Mongo regression reproduced the pilot defect: mixed-SKU
  publications lost all source-bound read availability because two identified
  variants had no SKU. The shared row builder now retains those variants using
  their own IDs, with null SKU and no invented SKU-index entry. It does not copy
  a parent's SKU. Native item events use the same reconciliation path.
- When SKU availability changes, the existing transactional identity replacement
  removes obsolete rows and current SKU-index entries while retaining historical
  order-line entries. Unchanged identity sets use the normal update path rather
  than adding a transaction for each refresh. Missing/duplicate IDs, malformed
  variants and ambiguous SKUs still withhold source receipts; the completeness
  check was not simply disabled to accept a partial variation set.
- Tests cover all-SKU-absent and mixed inventories, with/without a parent SKU,
  backfill and native events, and absent → present → absent SKU transitions.
  Real Mongo applies the actual formula-row validator; source-bound reads and
  CALCULADORA retain publication prices with `NA` SKU, zero missing publications
  and no redundant recovery request. Existing idempotency expectations now count
  the formerly omitted row. This verifies identity/availability, not independent
  correctness of every cost or variation-specific field.
- Final focused recovery/backfill suite: **369 passed in 39.38s** under the
  normal allocator. Event/quality-calculator regression: **108 passed in 0.28s**.
  Protected integration: **8 passed in 3.05s**. Ruff check/format, mypy (503
  files) and whitespace checks pass. Full-root evidence follows separately.
- Live observation of the unchanged `b74b758` worker confirmed a separate
  operational failure: at **916.02 seconds** of scan age, offset **900/1,900**,
  both inventory formulas returned formula-level DATA_UNAVAILABLE, despite the
  job still running and previously recovered rows remaining in Mongo. No global
  marker changed. Scan expiration now contradicts full-inventory operational
  acceptance; optimizing recovery/read continuity remains required, not polish.
- Rollback this unit by reverting its shared row builder, identity reconciliation,
  native-event routing and corresponding tests/docs together; preserve canonical
  acquired data and account for existing null-SKU variation rows. No production
  schema change or deployment occurred. Sheets worker requires a verified new
  Cloud Build image after the sweep/freshness defect is addressed, plus pilot
  variant-transition and full-inventory recovery/read validation. The API does
  not need rebuilding solely for this projection-writer change.
- Final root run with command-scoped `PYTHONMALLOC=malloc`: **3,875 passed,
  9 skipped, 356 warnings in 105.31s**. The protected cases skipped by the ambient
  URI were accepted separately as recorded above. This is conditional allocator
  evidence; it does not resolve the normal-allocator native crash. No interpreter,
  dependency or production allocator setting was changed.
- Final read-only container inspection confirms both `b74b758` digests remain
  healthy with zero restarts. The running worker does not yet include this fix.

## Bounded parallel acquisition keeps recovery writes joined

- Each existing 20-publication recovery claim now acquires at most four disjoint
  sub-batches of five concurrently. Gateway routing, seller authentication,
  response/rate-limit handling, claim size, projection checks and observation
  timestamps remain unchanged. This increases batch-detail calls from one to
  at most four per claim; it does not create another queue or operator worker.
- A TaskGroup joins every sub-batch before projection or queue completion.
  Ordinary failures are returned to the parent and re-raised after all siblings
  finish, preserving the existing public failure classification. Cancellation
  drains child tasks before returning, so no late acquisition write outlives
  the cancelled claim handler. The owned-lease check still gates projection.
- A failing synchronization test first demonstrated sequential acquisition.
  The corrected test proves exactly four concurrent sub-batches, disjoint/full
  20-ID coverage, completion only after all writes, retryable rate-limit handling
  without premature projection, and cancellation with no outstanding task/write.
  Existing real-Mongo 21-publication tests exercise the actual acquisition and
  projection code with simulated upstream responses, including exhausted and
  retried batches; their assertions now allow concurrent sub-batch ordering.
- Normal-allocator recovery suite: **221 passed in 40.35s**. Protected integration:
  **8 passed in 2.94s**. Full-root/static evidence follows below. These tests do
  not establish live MercadoLibre throughput or all-inventory freshness.
- Continued read-only observation of the original production job found offset
  **1,560/1,900** at **1,513.45 seconds** of scan age, still running with 60 IDs
  conservatively recorded across exhausted batches. Both formulas remained
  unavailable because the enumeration had expired; marker fingerprints were
  unchanged. Do not re-admit/restart that job merely to observe it.
- Rollback removes only this worker-side sub-batching and its tests; canonical
  writes and queue checkpoint format remain compatible. No deployment occurred.
  Build one verified Sheets worker image containing this change and `7bb9033`,
  then verify a new scoped pilot sweep, failure/retry behavior and final read
  coverage within the original freshness bound. API rebuild is not required
  for these worker-only execution changes. If the live sweep still outlasts
  freshness, the goal remains incomplete; do not extend timestamps to pass.
- Full Sheets suite under the normal allocator: **1,613 passed in 45.36s**.
  Ruff check/format, mypy (503 files) and whitespace checks pass. The attempted
  full-root run with `PYTHONMALLOC=malloc` instead exited **139/SIGSEGV** in
  Publicador's `test_publicador_rabbitmq_check_calls_broker_transport`; malloc
  is not a reliable workaround, and full-root acceptance for this unit remains
  unproven. No dependency/interpreter/runtime setting was changed.
- Read-only GitHub evidence confirms `7bb9033` completed test run `34193427168`
  and lint run `34193427253` successfully. Those belong to the preceding variant
  fix, not this pending change, and the workflow does not explicitly provision
  Mongo; they do not replace the locally verified Mongo integration cases.
- Worker build `27907157-6eb4-480e-bf9e-7d188943f93f` succeeded for exact source
  `ad8d42b2e1362394113a33bb4501c85694e7e644`. Single-image/source provenance
  verified digest `3ac69caf5cea44692e249f44deef6a280c4d89083c6c9fd582fcc5b4ecb8717b`.
  No deployment started. Exact-source GitHub lint run `34193952814` passed;
  test run `34193952783` / job `101957537104` was confirmed in progress in its
  Pytest step. Observe those handles before deploying; do not substitute the
  preceding commit's green result. Preserve running-worker rollback digest
  `50c87edc6503317b283c625a965fd46690dd304af1829a56a77c8fe66855f651` and restore
  the VM's required free-space margin before pulling.

## Worker download timed out; running configuration restored

- Exact-source test run `34193952783` for `ad8d42b` finished successfully; lint
  had already passed. The original inventory job independently finished at
  offset **1,900**, state **failed**, with **80 IDs** conservatively recorded
  across four exhausted batches. At observation its enumeration age was
  1,951.66 seconds and both inventory formulas were unavailable. No global
  marker changed. This is not successful full-inventory acceptance.
- Removed only unused local worker image reference
  `98cabd3eaf4607a49b08102854289ff898e5359b861f3ac025efd5884ceb5c26`, after
  confirming it remains in Artifact Registry and has no container references.
  Current API/worker and their prior rollback images were protected. Free space
  rose from **4,881,039,360 to 5,423,747,072 bytes**. No volumes, canonical data,
  containers or remote artifacts were deleted.
- The single-worker deployment passed preflight and saved
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-ad8d42b`, but the
  download command hit its 240-second timeout. Subsequent authoritative inspection
  found the new image absent, zero active worker-pull processes, and the old
  worker still healthy with zero restarts. No recreation had occurred. The
  timeout does not establish why the download stalled.
- Restored exactly the changed Compose reference to the existing running digest
  `50c87edc6503317b283c625a965fd46690dd304af1829a56a77c8fe66855f651` and verified
  rendered Compose plus container health. No service restart was needed. The
  new verified image remains in Artifact Registry but **is not deployed**.
- Prepared, but did not execute, `/tmp/zeler-parallel-pilot-ad8d42b.py` on the VM.
  It requires the new worker digest/health, a terminal prior job and elapsed
  cooldown, and writes an exclusive protected receipt before admission. The
  cooldown was observed elapsed with zero running recovery jobs; no new pilot
  was admitted. Diagnose image retrieval before attempting another deployment.
  Do not rerun the original deployment helper: its exclusive backup already exists.

## Parallel worker activated; new full-inventory pilot admitted

- Current VM diagnostics reached Artifact Registry (`/v2/` returned the expected
  unauthenticated 401 in 0.05s) and read the authenticated image manifest in
  4.39s. A separately observed immutable-digest pull then succeeded in **12.76s**
  after preflight with 5,421,924,352 free bytes. Compose stayed unchanged during
  the download. This does not establish the earlier timeout's cause.
- Activated the cached verified worker digest
  `3ac69caf5cea44692e249f44deef6a280c4d89083c6c9fd582fcc5b4ecb8717b` from
  `ad8d42b2e1362394113a33bb4501c85694e7e644`, using `--pull never` and targeting
  only Sheets worker after confirming zero running recovery jobs. Docker health
  is healthy, restarts **0**, and HTTP `/health` is **200**. Free space after
  activation is 4,878,905,344 bytes; restore margin before another image pull.
- Rollback remains worker digest
  `50c87edc6503317b283c625a965fd46690dd304af1829a56a77c8fe66855f651`.
  The activation backup is
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-ad8d42b`;
  preserve the separate earlier failed-attempt backup too. API was not recreated.
  Subsequent main commits so far contain documentation only, not omitted runtime
  code. No further build is required merely for these evidence updates.
- After checking the new worker's exact digest/health, terminal prior job and
  elapsed cooldown, the approved internal API-container probe admitted a new
  inventory sweep through the existing API admission helper. It reuses key
  `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f` and has
  exclusive mode-0600 receipt
  `/var/lib/zeler-platform/repairs/inventory-parallel-ad8d42b.json`.
  Initial reads were DATA_UNAVAILABLE in 0.0041s each; old enumeration membership
  remains stored but expired until rediscovery. No global marker changed.
  Observe this same sweep; do not repeat `prepare`. Full-inventory throughput,
  final freshness and authenticated Sheets/application acceptance remain pending.
- First observed running sample reached offset **220/1,900** at **106.34 seconds**
  of new enumeration age, with **zero exhausted-batch IDs**. Sequential internal
  CALCULADORA/CALIDAD reads took **2.9006/2.5900 seconds** and retained verified
  rows with explicit missing-publication cells; both declared incomplete coverage.
  Their missing counts differed while acquisition continued, so they are not
  an atomic cross-formula snapshot. No global marker changed. This early sample
  does not prove that the full sweep will finish inside 15 minutes.

## Work unit: preserve native SKU projection receipts

- Reproduced with real Mongo: an ordinary item event removed the source-bound
  receipt from an already recovered publication, making it unreadable again.
  Both new cases (parent SKU alone and parent plus variation SKU) failed with
  `FormulaDataUnavailableError` before the correction.
- The native writer now uses the existing source-stamp helper for an unambiguous
  group, retaining its status/concurrency guards and order-line identity filter.
  Only variation index entries go to the variation builder; parent entries must
  not count as ambiguous variation identities. No upstream calls or extra
  backfill were added. Independent readers still reject changed source hashes.
- Rejected approach: unconditionally re-running the shared backfill after each
  native SKU event broke two existing contracts (stale status and historical SKU
  duplication). That approach was removed; the existing tests were preserved.
- Local runtime harness: the two new cases passed in 0.75s; the full Sheets suite
  passed **1,615 tests in 45.73s** with local replica-set Mongo. Protected Mongo
  integration: **8 passed in 2.89s**. Root Ruff check/format and mypy (503 files)
  pass. Full-root pytest with normal allocator and local Mongo: **3,880 passed,
  9 skipped, 356 warnings in 103.46s**. Eight skipped protected Mongo cases passed
  in the separate run above; the other skip requires Caddy keys. This successful
  run does not establish a fix for earlier intermittent native interpreter crashes.
- Rollback boundary: remove this event-writer stamping/filter change and its two
  regression cases together; no schema, queue, deployment or data migration.
  This correction is not deployed. It affects the Sheets worker image; verify a
  recovered SKU publication stays readable after a newer native event on release.

## Parallel inventory observation: freshness still expires

- Same admitted sweep, no repeated `prepare`: offset **1,300/1,900**, attempt 1,
  reason `source_incomplete`. A sanitized diagnostic found 19 matching receipts
  and one absent receipt in its selected batch. This does not prove native events
  caused that absence; SKU diagnostic helpers ran in the older API image.
- At **748.25s** enumeration age: offset **1,460**, 20 exhausted-batch IDs;
  CALCULADORA/CALIDAD returned partial data in **2.0282/2.098s**. At **867.65s**:
  offset **1,620**, partial reads **8.071/6.4458s**. Reads are sequential, not atomic.
- At **931.68s**, offset **1,720**, the same sweep remained running with 20
  exhausted-batch IDs, but both formulas returned whole `DATA_UNAVAILABLE` in
  **0.0063/0.0062s** because inventory membership expired. Global markers remained
  unchanged. Bounded parallel acquisition alone does not satisfy ongoing read
  availability; do not extend timestamps or claim full inventory acceptance.
- Continue observing the existing sweep to terminal. Authenticated HTTP, real
  Sheet/app acceptance and the full 52-formula goal remain open.
- Terminal observation: **failed**, offset **1,900/1,900**, 20 exhausted-batch
  IDs, observed enumeration age **1,037.70s** (elapsed **1,041.52s**; not the exact
  completion timestamp). Both formulas remained whole `DATA_UNAVAILABLE` in
  **0.0064/0.0055s**; global markers unchanged. Do not reopen this sweep merely
  to observe it. The next availability fix must separate unverified inventory
  completeness from individually verified data without silently claiming a
  complete current inventory.

## Work unit: retain verified rows across inventory enumeration expiry

- Whole-inventory CALCULADORA/CALIDAD now distinguish unknown current membership
  from the freshness/integrity of each previously known publication. A valid but
  expired nonempty enumeration may supply IDs; only rows passing the unchanged
  15-minute source age and complete fingerprint/count checks can supply values.
  Missing/malformed/future/foreign membership still fails closed; expired empty
  membership cannot certify an empty current inventory.
- Each expired result appends a same-width warning row starting with
  `DATA_UNAVAILABLE`, `inventory_enumeration_expired`. This must be in values,
  since `Client.gs` returns the matrix rather than metadata. Metadata explicitly
  sets `inventory_rows_complete=false` and `inventory_enumeration_current=false`;
  `partial_misses` still counts known missing publications, not the warning.
  Both formulas request coalesced async inventory recovery even if all known
  publications are readable. Reads do not change observation times or markers.
- Four real-Mongo tests first reproduced whole-result unavailability. After the
  change, 12 cases cover both formulas, missing known publications, and current,
  expired or changed canonical sources: **12 passed in 2.76s**. Existing sweep
  resume tests now assert visible partial results after membership expiry while
  retaining immutable checkpoint timestamps and correct rediscovery behavior.
- Runtime harness: local replica-set Mongo and real dispatcher/backfill/reader;
  no live API/Sheet acceptance claimed. This unit affects the Sheets API image.
  Rollback is the reader's additional enumeration-status result, its two formula
  consumers/warning and their tests/docs together; no data/schema migration.
  Worker update from `e902eb5` remains separately required for native SKU receipts.
- Final normal-allocator root suite with local Mongo: **3,892 passed, 9 skipped,
  356 warnings in 109.31s**. Protected Mongo cases: **8 passed in 2.42s**; root
  Ruff check/format and mypy (503 files) pass. The initial full run found one
  unnecessary public error-message change; restoring the prior message preserved
  its existing API test, then the entire suite passed. No test was removed.
- Previous source `e902eb5` GitHub test `34242906407` and lint `34242906456`
  completed successfully. This is not CI evidence for the newer unit.
- Published implementation source **`6098a938e0e3d7c12d6dbe9696079122ee6abcce`**.
  Cloud Build API **`23839edc-6cad-4790-ab74-46c5233be4f9`** and worker
  **`cba6b56c-25db-4df5-8643-3cb75746dbe7`** were each confirmed **WORKING**
  from that exact connected-repository revision, one image per verified build.
  Observe those IDs; no deployment or new pilot admission has been performed.
  Release files are in `/tmp/zeler-inventory-availability.7SEBfo/`. After success,
  verify immutable digests/provenance, exact-source CI and VM disk preflight;
  preserve current API `02b4788…` and worker `3ac69caf…` as rollback images.

## Runtime: inventory availability deployed and bounded recovery verified

- Both builds succeeded with independently verified single-subject digest/build/
  source provenance for **`6098a938e0e3d7c12d6dbe9696079122ee6abcce`**:
  API `sha256:d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`,
  worker `sha256:5a70e40bafa593566bb3f371769854267ddfdabed2f01c9f81675844fc60d397`.
  Exact-source test `34243742186` and lint `34243742367` completed successfully.
  The VM provenance map contains both entries; subsequent main changes are docs-only.
- Initial free space **4,866,322,432 bytes** was below the 5GiB gate. After proving
  no container used them and confirming Artifact Registry recovery copies, removed
  only old API `c187698…` and worker `55e10b4…`. Following healthy API replacement,
  removed older API rollback `f8ccf36…`, preserving newly prior API `02b4788…`.
  No volumes, production data or running containers were removed by cleanup.
- Separate observed pulls took **13.15s API / 10.32s worker**, with Compose
  unchanged during each pull. At least 5GiB remained before each pull/activation.
  Each service was activated alone with `--no-deps --pull never`, after zero
  running recovery jobs. Both exact digests became healthy, zero restarts,
  `/health` HTTP 200; final free space **5,408,358,400 bytes**.
  Backups: `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-activate-6098a93`
  and `.pre-sheets-worker-activate-6098a93`. Running rollback authorities remain
  API `02b4788…` and worker `3ac69caf…`; no other product was deployed.
- Internal API-container smoke first showed 1,900 unavailable publication rows
  plus the expiry warning, no numeric prices, in **2.3654/1.6157s**. All old
  observations had expired; this was not presented as recovered data.
- A separate, single 20-ID request went through the existing API admission helper
  and normal running worker. Job
  `bce2e46e5f5c4d6e3fb78816949a0f4aa260aa7b7e5b6029cbf93122fbefb6bb`
  **completed on attempt 1**. Receipt (0600):
  `/var/lib/zeler-platform/repairs/inventory-availability-selected-6098a93.json`.
  Do not repeat `prepare`; `/tmp/zeler-availability-pilot-6098a93.py status` is
  read-only. The full-inventory job and global markers remained unchanged.
- Subsequent CALCULADORA/CALIDAD whole-inventory reads retained the 20 recovered
  publications: **1,904 rows**, **1,880 missing publications**, **23 numeric price
  rows** in CALCULADORA (variants included), in **1.4357/1.3466s**. Both explicitly
  reported incomplete coverage, expired enumeration and the visible warning.
  This proves useful source-verified values survive expired enumeration after
  normal async recovery. It does not certify every field, full current inventory,
  native-event continuity in production, authenticated HTTP or real Sheet/app
  acceptance. Those checks and the complete 52-formula goal remain open.

## Acceptance gap: execute 52 formulas, not only count them

- Audited the existing fixed B1 smoke: it verifies an inventory count of 52 but
  executes only DEVOLUCIONES for June 1–4. Its success cannot prove this Goal's
  all-formula/current-window acceptance. B1 authorization, credential lifecycle,
  runner and launcher were left unchanged; no live credential was created.
- Added standalone operator CLI `zeler_sheets.scripts.goal_formula_smoke`: six
  real pilot input fields generate all 52 requests from the canonical registry.
  Validation/help make no HTTP calls; `--execute` and legitimate env-only
  credentials are required for the fixed production URL. Each call has a 25s
  deadline, no redirects/retries, and 401/403 stops the run.
- Reports only names/statuses/counts/times, never data or credentials. HTTP 200,
  missing/partial/empty data, and content requiring review are distinct. Even
  exit 0 never certifies business correctness. This is not a p95 measurement.
- TDD started with the missing module; focused new/legacy smoke and B1 runner/
  adapter tests: **222 passed in 2.44s**. Ruff and mypy (505 files) pass. No live
  HTTP smoke ran. User identity and authorized Sheet URL were requested again.
  Operator steps/rollback: `docs/sheets/zelerdata-goal-http-smoke.md`.
- This adds no service entrypoint or schema change. Active API/worker executable
  behavior remains source `6098a93`; no service-image rebuild is needed for this
  standalone operator tool. Its authorized runtime installation/execution and
  per-formula source-value checks remain pending.

## Minimum-hardening audit: unresolved deletion and audit isolation

Follow-up on 2026-09-09: the audit-identity defect described below is now fixed
and deployed; see the runtime verification at the top of this file. Deletion
remains unproven. A renewed focused run passed **40 tests in 0.45s** across
`test_observability_logging.py`, `test_google_token_encryption.py`,
`test_extension_tokens.py` and `test_extension_token_api.py`; formula foundations
passed **13 tests in 0.10s**. Google credential tests exercise account-bound AAD
with fake KMS; extension lifecycle tests use a fake cipher. Audit failure tests
verify bounded logs without secrets. These are not proof of production KMS IAM,
business-data encryption or complete log sanitization: the shared logging suite
tests rendering/tracing, and its processor chain has no general redactor.
Do not treat credential revocation/deletion as erasure of seller business data.
No production data or executable code changed in this follow-up.

- No seller/account erasure implementation was found in repository Python code
  across gateway/core/Sheets/operations. Documentation requires including
  `sheets_formula_recovery_jobs` and `sheets_formula_recovery_admission` with
  admission stopped, but that instruction is not an executable deletion lifecycle.
  This gate remains unproven; do not run ad-hoc production deletes or delete
  shared platform collections belonging to other products.
- Confirmed an audit-isolation defect in `formulas/audit.py::_audit_id`: provided
  request IDs become `formula-audit-<request_id>` without seller/token scope.
  `FormulaExecutePayload.request_id` is supplied by the caller and passed into
  token validation/auditing. `DuplicateKeyError` is silently treated as a retry.
- Local replica-set reproduction used two synthetic sellers/tokens with the same
  request ID: **2 expected events, 1 stored event, 0 events for the second seller**.
  The dedicated `zeler_goal_audit_probe_<uuid>` local test database was dropped
  afterwards. No production data, credential, image or configuration changed.
  Existing retry tests prove same-request deduplication, not cross-seller audit
  independence. The fix must retain legitimate retries while scoping identity
  to the authenticated account/token and relevant event, with regression coverage.
- These findings are mandatory before goal closure. This was a read-only code
  audit plus isolated local diagnostic, not implementation of the hardening
  phase that the user placed after functional stabilization. Do not report
  deletion or audit isolation as complete from current tests or runbooks.

## Work unit: historical SKU identities must not duplicate current publications

- Reproduced in real local Mongo: backfill added a historical order-line SKU row
  alongside the direct current SKU for the same item/variation, duplicating
  stock/prices. Some existing groups instead became unreadable from mismatched
  receipts. Four regression cases failed before the fix: item/variation identity,
  with/without an existing obsolete row.
- Moved the already-proven native-event filtering rule into the shared order-line
  row builder, removing the duplicate private event filter. A direct current SKU
  wins for its item/variation; historical SKU index entries remain available for
  order lookup. This does not redefine fallback where no direct SKU exists.
- Backfill checks row identity changes for items with historical order identities,
  using its existing bounded 10,001-row read and transaction replacement path.
  Existing obsolete rows are removed atomically, not merely left unstamped.
  The transaction still guards newer projections/status and seller/item scope.
  No new queue, global freshness marker or historical source deletion was added.
- New real-Mongo cases passed **4/4 in 1.08s**, including repeat idempotency,
  preservation of the historical index and a foreign seller's row. Full Sheets:
  **1,641 passed in 51.49s**; protected Mongo integration: **8 passed in 3.42s**.
  Ruff check/format and mypy (505 files) pass. Final normal-allocator root suite
  with local Mongo: **3,906 passed, 9 skipped, 356 warnings in 112.47s**. Eight
  protected cases were exercised separately above; the remaining skip needs
  Caddy keys. This is not a production data or all-formula acceptance result.
- Rollback boundary: shared filtering/identity-transition trigger, removed native
  duplicate filter and tests together. No production repair has run; rollback
  must not recreate incorrect duplicate rows. The deployed worker is still source
  `6098a93`; a new verified Sheets worker image is required before runtime
  acceptance. Bootstrap also calls this backfill: update its image before a future
  bootstrap run requiring the correction. API handlers are unchanged.

## Runtime verification: historical SKU correction deployed

- Worker source `749f296271748f7a5d723a2fb190a15eee02c6da` is now deployed by
  digest `4fb14b0d69ee394f2db0bc9e9a90fd4a07a1be834a6195b2ac0a44b08a4daa41`.
  Cloud Build `43ddd4d8-e72a-49fc-b0dc-5687ffffe8a4` succeeded; the canonical
  provenance verifier bound image/build/connected repository/source locally and
  merged the binding on the VM. Exact-source CI test `34246969190` and lint
  `34246968962` both succeeded. No second build was submitted.
- Worker-only activation passed preflight, exact Compose replacement, cached
  immutable image, zero running recovery jobs, health HTTP **200**, healthy
  container and **0 restarts**. API remains healthy at source `6098a93`, digest
  `d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`.
  Worker rollback is digest
  `5a70e40bafa593566bb3f371769854267ddfdabed2f01c9f81675844fc60d397`;
  Compose backup is `docker-compose.yml.pre-sheets-worker-activate-749f296`.
- Removed only unused old worker image
  `50c87edc6503317b283c625a965fd46690dd304af1829a56a77c8fe66855f651`, after
  checking every container, protecting four current/rollback images and
  confirming Artifact Registry recoverability. No volumes/data were removed.
  Pull took **14.24s**; final inspected root free space was **5,406,441,472 bytes**.
- Read-only runtime sampling found **7** historical index entries/publications
  and **3** persisted duplicate direct-identity groups. Enqueued those exact
  seven publications once through the existing recovery queue; the normal
  deployed worker completed job
  `f497b2c60200df3064c355b16b91a5ab8f4adb47a91902e74829cd56c1b002af`
  in **1 attempt**. Protected receipt:
  `/var/lib/zeler-platform/repairs/historical-sku-selected-749f296.json` (0600).
- Post-recovery verification used the receipt's same seven IDs, not a newly
  selected subset: **0 duplicate direct-identity groups, 13 source-verified rows,
  0 missing publications**, reader **0.0119s**. The current historical-source
  index sample contained six entries; this probe does not independently prove
  unchanged historical-index provenance. Global freshness markers and the
  terminal full-inventory job remained byte-for-byte unchanged.
- Whole-inventory CALCULADORA/CALIDAD returned **1,907 rows**, **1,893 missing
  publications**, visible expiry warnings and incomplete/current=false metadata,
  in **3.1542s / 1.8904s**; CALCULADORA exposed **13 numeric price rows**. These
  internal runtime reads are not authenticated HTTP, p95, all-field correctness
  or real Sheets acceptance. No complete-inventory claim is supported.
- Local operator artifacts: `/tmp/zeler-sku-identity.qMOyWV/`. `pilot.py prepare`
  has already executed; use only read-only status/probes to observe it. No new
  service build is required for this evidence-only update. Bootstrap still
  requires an updated image before a future run needing the shared correction.
  Remaining functional work includes stale status precedence during backfill,
  current complete inventory and all-52/user-facing acceptance before hardening
  closure. Do not recreate incorrect duplicate rows during rollback.

## Work unit: backfill status follows the newer observed snapshot

- Four initial real-Mongo regressions reproduced an active snapshot becoming
  paused from older or equal-time conflicting history. Backfill now compares
  `last_meli_sync_at` (and the projection's source receipt at write time) with
  `last_observed_at`, rather than using the item's modification time as an
  observation. On a conflicting tie, the persisted Mercado Libre snapshot wins.
- The shared precedence helper is applied during item enrichment and the final
  status-state reread. A newer/equal snapshot supplies current status and its
  observation time, not guessed transition start/duration scalars. Matching
  history, newer history and legacy rows without snapshot evidence retain their
  prior behavior. No status-history source or transition collection is mutated.
- Focused coverage: **11 passed in 1.94s**, including eight real-Mongo cases for
  parent/variation rows, existing/absent rows, older/tied history, repeated
  backfill, source-bound readability and unchanged persisted history; three
  controls retain matching/newer history or history without snapshot evidence.
  Earlier combined recovery/backfill/native-event suite: **460 passed in 46.03s**.
  Protected Mongo integration: **8 passed in 2.37s**. Ruff check/format and mypy
  (505 files) pass. Full normal-allocator root suite with local Mongo:
  **3,917 passed, 9 skipped, 356 warnings in 108.90s**. Eight protected skips
  passed separately above; the remaining skip needs Caddy keys.
- Runtime scope: Sheets worker and future bootstrap runs use this backfill;
  formula API handlers are unchanged. Production verification of this new
  precedence is still pending, not implied by the prior SKU pilot. Build a new
  verified Sheets worker image before activation and compare a bounded pilot's
  conflicting source/history against the persisted formula status and missing
  duration fields. Refresh bootstrap's image before a future applicable run.
- Rollback boundary: remove the shared precedence helper and its two call sites
  together with the regression tests. No schema/data migration or external
  side effect has run for this change. Do not synthesize history to roll back.

## Runtime verification: snapshot status precedence

- Worker source `e6137076d76508472076c41e520f62eb110fad8e` is deployed as digest
  `b47ec04c1442cad34ab79dbe2437c76047dea52a29d5205bba5df3af6fe3cc53`.
  Build `a713c842-4bb0-4538-8d7f-2c04e73dbb49` succeeded; canonical provenance
  was verified locally and merged on the VM. Exact-source test `34249063926`
  and lint `34249063776` both succeeded before activation.
- Worker-only activation passed free-space/preflight, exact Compose replacement,
  zero running recoveries, health HTTP **200**, healthy container, **0 restarts**.
  Rollback digest: `4fb14b0d69ee394f2db0bc9e9a90fd4a07a1be834a6195b2ac0a44b08a4daa41`;
  backup: `docker-compose.yml.pre-sheets-worker-activate-e613707`. API remains
  source `6098a93`, digest
  `d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`, healthy
  with zero restarts. No API rebuild was required for this worker behavior.
- Removed only unused old worker image
  `3ac69caf5cea44692e249f44deef6a280c4d89083c6c9fd582fcc5b4ecb8717b`, after
  checking all containers, protecting current/rollback images and confirming
  Artifact Registry recovery. No volumes/data removed. Pull **15.17s**; final
  inspected root free space **5,404,868,608 bytes**.
- Read-only pilot discovery examined **1,529 states and matching items**, without
  truncation at its 10,000-row bound: **3 conflicts**, all with newer snapshots.
  Requested those three IDs once through the existing queue; deployed normal
  worker completed job
  `6f20ca2ce9d4896a3955f429da78ef975ad2983b5228bd0cf21fe692186a9ad3`
  in **1 attempt**. Protected receipt (0600):
  `/var/lib/zeler-platform/repairs/status-precedence-selected-e613707.json`.
- Same-receipt verification found **5 source-verified rows, 0 missing items**.
  The **2 parent rows** use the newer source status/observation without guessed
  duration fields; **3 variation rows** match their own status or parent fallback
  and do not inherit absent variation duration fields. Reader **0.0046s**.
  The three source/history conflicts still exist: projection precedence was
  repaired, not historical transitions fabricated. Global freshness markers and
  the terminal full-inventory job remained byte-for-byte unchanged.
- Whole-inventory CALCULADORA/CALIDAD returned **1,903 rows**, **1,894 missing
  publications**, explicit expiry warnings, incomplete/current=false metadata,
  in **1.6854s / 1.2124s**; CALCULADORA had **8 numeric price rows**. This is
  internal runtime verification, not authenticated all-52 HTTP, p95 or real
  Sheets acceptance. Full current inventory and mandatory hardening remain open.
- Operator artifacts: `/tmp/zeler-status-precedence.E0JbMu/`; `pilot.py prepare`
  already ran. Status/probe modes are read-only. This evidence-only update needs
  no service rebuild. Bootstrap still needs an updated image before a future
  run using the corrected backfill. Do not roll back by recreating wrong status
  projections or inventing status-history records.

## Full inventory revalidation on corrected worker: active

- Prior job was authoritatively terminal: failed/source_incomplete, offset 1,900,
  20 unavailable IDs, elapsed cooldown, zero running recoveries. Those 20 IDs
  now have matching source/group receipts under current code; this is not a
  current-freshness claim. Deployed SKU/status corrections justify one new sweep.
- Admitted full inventory once through the normal API recovery helper, running
  worker source `e613707`, unchanged API source `6098a93`. Same coalesced job key:
  `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
  New protected receipt (0600):
  `/var/lib/zeler-platform/repairs/inventory-corrected-e613707.json`.
  `/tmp/zeler-inventory-corrected-e613707.py prepare` already ran; observe only
  `status` or `diagnose`. Local artifacts: `/tmp/zeler-inventory-e613707.dV849M/`.
- Latest checkpoint: **running, offset 540/1,900, 0 unavailable IDs**, inventory
  observation age **240.99s**, operator elapsed **249.56s**. CALCULADORA/CALIDAD
  each returned 2,150 rows and 1,355 missing publications, in **2.7624s/1.9972s**;
  795 numeric price rows in CALCULADORA. Membership is current but coverage is
  explicitly incomplete. Global freshness markers unchanged. This is not a
  terminal result, all-fields validation, authenticated HTTP or p95 evidence.
- No new executable change/build/deployment occurred in this checkpoint. Both
  service image sources remain as above; this evidence-only update needs no
  image rebuild. Observe the existing job to completion before another sweep.

## Current orders contract: forward shipment discovery remains missing

- Official documentation checked September 8, 2026 describes the order shipment
  Hosted View as an array, including single results. Select purchase shipments by
  `type=forward`, not position; `204` can mean absence or delayed propagation.
  Public routing uses `X-New-Domain`; the older view is scheduled for deprecation
  at September's end. This does not mean the ordinary order-detail endpoint is
  itself replaced. [Mercado Libre orders documentation](https://developers.mercadolibre.com.mx/gestiona-ventas)
- Repository evidence: `FormulaRecoveryWorker._shipments` already consumes the
  reverse relationship with its new-domain header and seller checks. In contrast,
  `_order_detail` returns after ownership/date validation without consulting
  `/orders/{id}/shipments`. `_shipment_id` in event persistence reads embedded
  shipping or a top-level ID; shipping handlers consume that singular model.
- Therefore a missing recoverable shipment link is not resolved by the forward
  endpoint today. This is an implementation gap, not proof that every current
  order response is incompatible. Next use a bounded asynchronous fallback after
  order ownership verification, persist the verified purchase relationship, keep
  partial data truthful, and test empty/partial/multiple/foreign cases. Do not
  select a return shipment as the original or treat `204` as permanent absence.
  Full orders-contract acceptance remains open; no adapter was changed here.

## Work unit: recover missing purchase shipment relationships

- Two initial tests failed because `_order_detail` never queried the forward
  relationship. After ownership/date validation, it now uses the normal detail
  gateway for `/orders/{id}/shipments?hosted=true` with `X-New-Domain`, only when
  the order lacks a shipment ID and does not explicitly declare `no_shipping`.
  Contract source: [Mercado Libre orders](https://developers.mercadolibre.com.mx/gestiona-ventas).
- A bounded array (at most 100 entries) must identify one distinct numeric
  purchase shipment by `type=forward`. Returns are not purchase shipments;
  conflicting optional seller/order identities invalidate the relationship.
  The recovered ID enters the existing normalized, guarded order transaction;
  only the resolved shipping-unavailable flag is cleared. Other partial fields
  and the original input remain unchanged. No schema or new queue was added.
- Empty, partial, unavailable, malformed, ambiguous or foreign relationships
  preserve available order data and explicitly mark shipping unavailable, even
  if the original response omitted a partial-content header. A 204 does not
  prove permanent absence. Fallback has a five-second deadline; transport/rate
  errors preserve partial data, while cancellation propagates. Existing trusted
  Mongo field fallback remains in the existing writer.
- Focused adapter/recovery/consumer/HTTP tests: **41 passed in 6.16s**, including
  a real-Mongo purchase-ID publication. Updated fixture gateway behavior and
  expected request counts for the extra asynchronous call; the no-shipping HTTP
  fixture now explicitly declares that fact instead of assuming it from absence.
  Full normal-allocator root suite: **3,934 passed, 9 skipped, 356 warnings in
  107.42s**; protected Mongo integration **8 passed in 3.00s**. Ruff check/format,
  mypy (505 files) and diff check pass. One remaining root skip needs Caddy keys.
- A verified **Sheets worker** image and bounded live missing-link recovery are
  still required. Formula HTTP handlers, bootstrap entrypoints and other products
  are unchanged. Do not deploy over the active inventory recovery. This does not
  complete multi-shipment modeling, every orders API migration or all-52 acceptance.
- Rollback boundary: `_recover_order_shipment`, its `_order_detail` call/import,
  and corresponding tests/fixture changes. No production relationship repair
  has run; rollback must not delete legitimately recovered persisted IDs.

## Inventory completed, but full fresh coverage is not achieved

- The corrected `e613707` sweep reached **completed, 1,900/1,900, zero unavailable
  IDs**, with zero running recoveries. Its checkpoint duration was **1,004.513s**
  (16m44.513s), measured from inventory observation to terminal job update, not
  from a later operator poll. Receipt and job key are the same as the active
  checkpoint above; do not run its `prepare` again.
- Completion exceeded the 900-second freshness window. At the first terminal
  observation, CALCULADORA and CALIDAD each returned **2,737 rows**, **300 missing
  publications**, explicit expiry warnings, and both completeness/current flags
  false. Reader times were **1.8163s / 1.487s**; CALCULADORA had **2,436 numeric
  price cells**. These counts do not establish completeness of every field.
  Global freshness markers remained unchanged.
- This resolves the earlier exhausted-batch failures, not simultaneous fresh
  inventory coverage. Investigate acquisition/projection timing before another
  whole-inventory sweep. Do not extend timestamps or freshness limits merely to
  turn this result green. Backfill currently reloads seller-wide historical SKU
  identities and status states for each selected batch; this is an inspection
  lead, not a measured bottleneck or authorization to weaken concurrency guards.

## Worker 69d66ad deployed; live forward-relationship acceptance remains open

- Source `69d66ad4e97e6db9a893e9ef570d78a47118d135` passed CI test run
  `34251940206` and lint run `34251940230`. Verified Cloud Build
  `e9473000-1c27-4e32-adf5-c2755869c96b` produced worker digest
  `4d1936399c17e0bf0bff72ef51c841a0443e9eb8e0c03ffe674aa29d925020dd`.
  Canonical provenance was verified and merged into the VM image/source map.
- After the inventory job became terminal, worker-only activation passed health
  HTTP 200 with zero restarts. The API remains source `6098a93`, digest
  `d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`.
  Worker rollback is digest
  `b47ec04c1442cad34ab79dbe2437c76047dea52a29d5205bba5df3af6fe3cc53`;
  Compose backup is `docker-compose.yml.pre-sheets-worker-activate-69d66ad`.
- Free-space gates passed before pull and activation. Removed only the unused
  worker image `5a70e40bafa593566bb3f371769854267ddfdabed2f01c9f81675844fc60d397`
  after checking all containers, protected current/rollback images and registry
  recoverability. No volumes or customer data were removed. Post-activation
  free space was **5,392,199,680 bytes**, close to the 5 GiB floor.
- A bounded read-only scan of the pilot range found **100 stored orders, zero
  unknown shipping links**. This is stored coverage, not complete API coverage;
  there was no genuine missing-link candidate to repair. No production links
  were removed to manufacture one.
- Through the normal authenticated gateway, an owned in-range order detail
  validated, but its forward relationship returned **404** with `hosted=true`.
  Removing that query parameter also returned **404**, error code
  `not_found_shipping_for_order_id`. A further selection explicitly requiring a
  stored shipment and excluding `no_shipping` reproduced that code; its live
  order detail had a shipping ID and did not declare `no_shipping`.
- Local proxy code forwards query parameters and the new-domain header. Official
  documentation still describes the hosted array contract, but these probes do
  not prove its availability for this pilot relationship. Preserve available
  Mongo/order data and truthful unavailability; do not claim live migration
  acceptance or a successful missing-link repair. No business-data writes were
  made by these probes. [Mercado Libre orders contract](https://developers.mercadolibre.com.mx/gestiona-ventas)
- Operator artifacts: `/tmp/zeler-forward-shipment.tm6dP3/`. Cleanup, pull and
  activation already ran; do not replay them. This evidence-only update requires
  no new service image. The worker contains the intended executable change;
  bootstrap still needs a current verified image before a future invocation of
  corrected backfill. All-52 authenticated HTTP, real Sheets/app, inventory
  freshness and minimum hardening remain required before closing the goal.

## Inventory timing: reuse identical listing quotes, not more concurrency

Read-only runtime profiling on worker `69d66ad` separated acquisition from
stored projection preparation for two 20-item samples (inventory offsets 0 and
940). Both used the worker's four concurrent five-item sub-batches, the normal
Sheets gateway, and `dry_run=True`; there were zero running recovery jobs before
and after. No business data was written. Operator script:
`/tmp/zeler-inventory-profile-vPWWns.py`; local artifacts:
`/tmp/zeler-inventory-profile.vPWWns/`.

| Measurement | Offset 0 | Offset 940 |
| --- | ---: | ---: |
| Acquisition dry run | 3.7336s | 7.9203s |
| Stored projection dry run | 0.1214s | 0.3247s |
| Historical SKU loader | 0.0092s, 6 groups | 0.0094s, 6 groups |
| Status loader | 0.0329s, 1,529 groups | 0.0330s, 1,529 groups |
| Listing-price requests | 40 | 40 |
| Summed listing-price request time | 6.7520s | 8.1160s |
| Variation detail requests | 5 | 30 |

Both samples validated 20 items with zero stale-item failures or gateway errors.
Summed request times overlap across concurrent tasks; they are not wall-clock
savings. Dry runs exclude writes, and projection reads the existing stored
snapshot, not the newly fetched in-memory detail. This is not an end-to-end
inventory benchmark or p95. It makes seller-wide loader optimization a lower
priority than redundant upstream work for these samples.

The general listing-fee and fixed-fee projections each request `listing_prices`.
They use distinct consumers and must both remain, but can use one successful
response when their complete parameter dictionaries are equal. The work unit
reuses that response only within the same item observation. Different bases or
a failed first request retain the independent lookup. No cross-item cache,
freshness extension, new concurrency, queue or persistence model is introduced.
The fixed-fee requested counter now counts only actual dedicated requests;
its enriched counter still counts successfully projected values.

The new identical-quote test initially failed on the extra request; controls for
different bases and first-request failure already passed. After implementation,
`uv run pytest modules/sheets/tests/test_sheetseller_backfill.py --tb=short`:
**154 passed in 0.31s**. Protected Mongo acquisition/execution/rollback suite:
**8 passed in 2.84s**. Ruff check/format, mypy (505 files) and diff check pass.
Full normal-allocator root suite with local replica-set Mongo:
**3,937 passed, 9 skipped, 356 warnings in 108.17s**. Eight root skips are the
protected Mongo cases separately passed above; the remaining skip needs Caddy
keys. A verified worker release and post-change runtime measurement are pending.
The rollback boundary is the per-item listing response/context initialization,
shared-response branch, and its regression test in the two backfill files.
Reverting must not delete normalized quotes already legitimately persisted.

The affected active service is **Sheets worker**; build a verified image and
repeat the same bounded profile before a justified full-inventory validation.
Bootstrap also imports the backfill and needs the change in its image before
its next run; no bootstrap invocation is required for this work unit. The API
does not execute enrichment and needs no deployment for this optimization.

## Listing-quote reuse deployed: fewer requests verified, full sweep pending

- Verified Cloud Build `0eaab654-9922-44cf-b78f-03eb2589de90` succeeded for source
  `62d799ea0bf7506b0dbfd979447287170101a98a`, worker digest
  `d4a665c9bf05fc4ee3463ca71b3c10a93cde06a7339250fcea6ca5e4537ff6a3`.
  CI test `34254320135` and lint `34254320209` succeeded. Canonical provenance
  checks passed locally and on the VM; the VM image/source map was updated.
- Worker-only activation passed HTTP health 200 with zero restarts. The API
  remains source `6098a93`, digest
  `d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`.
  Worker rollback is `69d66ad`, digest
  `4d1936399c17e0bf0bff72ef51c841a0443e9eb8e0c03ffe674aa29d925020dd`.
  Backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-62d799e`.
- Removed only unused worker image
  `4fb14b0d69ee394f2db0bc9e9a90fd4a07a1be834a6195b2ac0a44b08a4daa41`, after
  checking all containers, four protected current/rollback images and registry
  recoverability. No data or volumes removed. Preflight gates passed; pull took
  **14.44s** and did not change Compose. Post-activation free space was
  **5,390,544,896 bytes**, only slightly above the 5 GiB floor.
- Repeated the same two dry-run samples through the normal gateway. Each now
  makes **20 listing-price calls instead of 40**, with 20 validated items, zero
  stale items and zero gateway errors. No business-data writes or running
  recovery jobs were present in this measurement.

| Measurement after deployment | Offset 0 | Offset 940 |
| --- | ---: | ---: |
| Acquisition dry run | 4.5379s | 5.7619s |
| Stored projection dry run | 0.1186s | 0.3149s |
| Listing-price calls | 20 | 20 |
| Summed listing-price request time | 5.4758s | 3.8417s |

The first sample was slower than baseline despite fewer calls; the second was
faster. These are separate upstream observations, not a controlled estimate of
full-sweep speedup. Request elimination is proven for both samples; completion
within the freshness window is not. Profile script is now
`/tmp/zeler-inventory-profile.vPWWns/profile.py`; the original baseline script
at `/tmp/zeler-inventory-profile-vPWWns.py` still asserts the old worker digest.
Do not rerun cleanup, pull or activation as status checks.

The active worker contains the intended executable change. This evidence-only
update needs no service rebuild. Bootstrap needs a current verified image before
its next invocation of changed backfill. All-52 HTTP, real Sheets/app and the
other goal acceptance requirements remain open.

### Full inventory admitted once on 62d799e: running

After the read-only comparison, admitted one full inventory recovery through the
normal API helper using the formula's recovery request. This is internal runtime
validation, not an authenticated HTTP smoke. The old coalesced job was terminal,
its cooldown elapsed, and no recovery jobs were running before admission.
Protected receipt: `/var/lib/zeler-platform/repairs/inventory-listing-reuse-62d799e.json`.
Job: `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
`/tmp/zeler-inventory-profile.vPWWns/pilot.py prepare` already ran: only use
`status`/`diagnose` for observation; never reopen it because a poll is slow.

Latest checkpoint: **running, 200/1,900, zero unavailable IDs**, inventory age
**54.33s**, operator elapsed **61.42s**. CALCULADORA/CALIDAD each returned 2,018
rows in **1.9180s / 1.6012s**, with **1,720 / 1,714 missing publications** and
incomplete coverage. Membership was current, no expiry warning, global freshness
markers unchanged. CALCULADORA had 298 numeric price cells. Counts are observed
during concurrent progress, not an atomic end-to-end snapshot or proof of all
fields. Observe this job to completion before evaluating freshness or admitting
another whole-inventory sweep.

## Catalog recovery audit: correct winner-price normalization first

Four current consumers depend on catalog snapshots: OBTENER_CATALOGO and
CATALOGO_COMPLETO use product snapshots; CATALOGOBUYBOX and CATALOGO use buybox
snapshots. Both read models appear in `RECOVERABLE_MODELS`, but neither is in
`IMPLEMENTED_MODELS`; runtime admission therefore rejects them. Existing snapshot
acquisition is in the historical backfill, not the formula recovery worker.
The catalog readers still rely on whole-model freshness markers and need an
actual current-snapshot recovery/read contract, not merely enabled model names.

Before wiring recovery, fixed a reproducible normalization error:
`winning_price` was filled from the suggested `price_to_win`, while absent
`price_to_win` could be filled from a legacy top-level `winning_price`. The
documented API gives the actual winner in `winner.price` and the suggested price
separately; these can differ, and the suggestion can be null.
[Mercado Libre competition contract](https://developers.mercadolibre.com.mx/es_ar/como-empezar/competencia-en-catalogo)

The normalizer now reads each canonical field independently. Missing/malformed
winner containers remain unknown instead of borrowing the suggestion. It no
longer accepts the undocumented top-level winner alias on this upstream path.
Seven initial tests failed on the old behavior. After the change, historical
backfill tests **52 passed in 0.28s**, including the existing persistence-path
test now asserting winner 119 versus suggestion 118; item/shipping/catalog and
remaining phase-four handler tests **62 passed in 0.19s**. Ruff check/format and
mypy (505 files) pass. Full normal-allocator root suite with local replica-set
Mongo: **3,944 passed, 9 skipped, 356 warnings in 107.92s**. The eight protected
Mongo cases passed separately in **1.91s**; the remaining root skip needs Caddy
keys.

This does not repair existing production snapshots or enable automatic catalog
recovery. Runtime proof still needs a real owned catalog item, verified upstream
response, normalized publication and formula read. Do not re-label stored target
prices as winners without refetching the source. The rollback boundary is
`_catalog_buybox_snapshot` and its corresponding regression/fixture assertions.
The historical backfill and operational reconcile caller need an image containing
this change before their next invocation. The running inventory worker is still
`62d799e`; do not interrupt its active sweep to deploy this unused recovery path.

### Pilot catalog scope is broader than current snapshot coverage

A read-only VM/runtime probe restricted item reads to the existing 1,900-ID pilot
inventory and seller `82453304`. It found 1,900 stored items, 1,460 with a parent
catalog product, 858 distinct parent products, and 385 distinct variation
products. **27 variation products are absent from the parent-product set**.
Snapshot collections contain 386 product records and 473 buybox records for this
seller; these whole-seller counts do not prove current membership or freshness.

All 1,460 parent-linked items have an unknown/non-boolean `catalog_listing` value
in storage; none are explicitly true or false. The shared Item model currently
does not declare that field. Do not infer catalog participation solely from a
product association. The historical scope helper currently reads only parent
product IDs and cannot distinguish this state. Current product recovery must
cover variation-only product IDs, and buybox acquisition needs source-verified
participation/ownership rather than treating all eligible items as participants.
This is a concrete prerequisite for the remaining automatic catalog workflow,
not a completed recovery implementation.

Probe: `/tmp/zeler-catalog-scope-eg2xPT.py`; local artifacts:
`/tmp/zeler-catalog-scope.eg2xPT/`. Output contains only counts; no upstream calls,
business-data writes, queue mutations or freshness-marker changes were made.

## Inventory 62d799e completed within freshness; cost fields remain incomplete

The same coalesced inventory job is terminal **completed, 1,900/1,900, zero
unavailable IDs**, with zero running recovery jobs. Exact checkpoint duration:
**787.736s (13m07.736s)**, compared with **1,004.513s** for the previous corrected
sweep. These are observed production runs, not a controlled attribution of all
timing differences to quote reuse. The receipt remains
`/var/lib/zeler-platform/repairs/inventory-listing-reuse-62d799e.json`; do not
repeat `prepare`.

The first observation straddled final-batch publication: job state was completed
when read afterward, while formulas had seen 20 missing items. A second read
after terminal state confirmed **2,859 rows, zero missing publications,
inventory_rows_complete=true, inventory_enumeration_current=true**, no expiry
warning and unchanged global freshness markers for both formulas. Observation
age was **833.33s**. CALCULADORA returned in **2.2051s**, CALIDAD in **1.4112s**.
All 2,859 CALCULADORA rows had numeric price cells. This proves a fresh complete
inventory-row view at that observation, not perpetual freshness or all fields.

CALIDAD had zero unavailable cells. CALCULADORA had **218 unavailable cells**.
A further read-only column probe, still reporting complete/current inventory,
localized them as follows:

| Column | Unavailable cells |
| --- | ---: |
| COSTO ENVIO VENDEDOR | 18 |
| COMISION | 40 |
| % COMISION | 40 |
| COSTO FIJO POR UNIDAD | 40 |
| TOTAL COSTOS | 40 |
| NETO ESTIMADO | 40 |

The counts alone do not identify whether each source is recoverable, rejected,
missing parameters or malformed. Next inspect the affected normalized field
states and actual API bases, then recover where possible. Do not turn these
cells into zero or optional absence to claim acceptance. Script:
`/tmp/zeler-inventory-profile.vPWWns/columns.py`.

Continuous freshness remains unproved: inventory observations and field receipts
expire after 15 minutes, and the terminal queue cooldown is another 15 minutes
from completion. Inspect refresh admission/maintenance before claiming future
consultations remain current; do not rerun entire inventories in a blind loop.
All-52 authenticated HTTP and real Sheet/app acceptance remain outstanding.

The catalog-price correction `471b4fb` passed CI lint `34255935674` and test
`34255935806`. It is not deployed: active worker remains source `62d799e`, API
`6098a93`. Before invoking corrected historical acquisition/reconcile, build a
verified Sheets runtime image containing `471b4fb` and verify the real catalog
normalization/persistence/read path. No image rebuild is needed for this
evidence-only update itself.

## Cost gaps: targeted admission and transient enrichment retry

Read-only VM inspection traced the 218 unavailable calculator cells to **37
publications**, not missing inventory rows. The probe examined stored field
states without claiming that these later reads were still fresh. No business
data was written. Script: `/tmp/zeler-cost-gaps-q5RZkE.py`; local artifacts:
`/tmp/zeler-cost-gaps.q5RZkE/`.

| Source field | Publications / rows | Stored row reasons |
| --- | ---: | --- |
| Seller shipping cost | 18 / 18 | 11 transient/rate_limited; 7 basis_mismatch/basis_changed |
| Listing fee | 37 / 40 | 27 transient/rate_limited; 13 basis_mismatch/basis_changed |
| Fixed fee | 37 / 40 | 40 transient/rate_limited |

The corresponding parent item states agree. Eleven shipping values and 24
listing/fixed-fee values were retained, but cannot be presented as current after
failed acquisition or a changed basis. These states support retry, not permanent
absence or zero costs. There were zero running recovery jobs during inspection.

Two local gaps were reproduced and fixed:

- CALCULADORA now requests existing targeted-item recovery when a present row's
  selected price or cost fields are unavailable. IDs are deduplicated across
  variations and exposed as `unavailable_field_items`; row-completeness metadata
  remains about row coverage. Missing/expired whole inventories still use their
  existing inventory request. Optional NA and trusted values do not themselves
  trigger recovery. No upstream calls were added to formula execution.
- Selected-item jobs now retain the existing bounded retry when enrichment
  diagnostics report a transient failure, even if base item details and row
  receipts are valid. Available projections still publish before retry. Whole
  inventory checkpointing is unchanged; no new queue, quota, concurrency or
  freshness policy was introduced.

Eight initial handler cases failed because no recovery was requested; the real
Mongo selected-job case failed because it incorrectly completed after transient
enrichment. Handler tests: **50 passed in 0.10s**. Affected projection, identity,
inventory and retry cases: **23 passed in 7.60s**, including a successful next
attempt after the queued delay. Old tests expecting no recovery for present but
unacquired fields were updated without weakening values, identity or receipt
checks.

A local authenticated ASGI HTTP + real-Mongo test passed in **0.71s**: first HTTP
returns available price plus unavailable fees and queues only the affected item;
the worker publishes recovered costs; the second HTTP reads costs **0/10/10/2**,
total **12**, net **88**, without another upstream call or a global freshness
marker. This is synthetic local integration, not production HTTP acceptance.
Protected Mongo tests: **8 passed in 3.27s**. Ruff check/format and mypy (505
files) pass. The continuation reran `uv run pytest --tb=short -q` against
the local replica set: completed successfully (exit 0), with nine expected
skips. Eight are the protected Mongo cases, rerun separately with
`ZELER_RS0_TEST_URI` and no ambient `MONGO_URI` (exit 0); the remaining skip is
the Caddy required-keys check. The extra quiet flag suppressed totals and
duration, so no elapsed-time claim is made for this rerun.

Rollback boundary: CALCULADORA field-gap recovery selection/metadata and selected
worker transient-diagnostic handling, with their tests. Existing recovered data
must not be removed. Both **Sheets API and Sheets worker** need verified images
for this unit. Deploy worker before API, then admit and verify the actual bounded
pilot cost repairs. Production repair and future freshness maintenance remain
unproved; do not re-run the 1,900-item sweep for this field-level diagnosis.

### Cost-recovery release prepared, not deployed

Commit `29c38320cb4e3d09a5d284741cf4cb8fee0124aa` is pushed to `main`.
Both one-image Cloud Builds succeeded and the canonical provenance verifier
validated digest, build and exact connected-repository source locally:

| Service | Build | Image digest |
| --- | --- | --- |
| Sheets worker | `5c63d9f1-c871-4951-97d7-030828524757` | `791e9c90eb9871b1e7573a429e013035ee8a279e064383a4fe77fd1030dfaea7` |
| Sheets API | `a6a634d4-2929-4629-9c48-821e301430cb` | `c679a81b7ad3e0b026f8b4a8a4e1ff5bddc1387bcccbf59fc31cb808f70ab56c` |

Artifacts and release state: `/tmp/zeler-cost-gaps.q5RZkE/`. CI lint
`34259086965` passed; test `34259087298` was still running at this checkpoint.
A separate collection check confirmed 3,966 root cases, consistent with the
successful execution and its nine skips; no prior lost process result was reused.

Read-only VM inspection found both existing services healthy with zero restarts:
worker remains digest `d4a665c9...` (source `62d799e`), API `d9bfc8a8...`
(source `6098a93`). Free space was 5,423,652,864 bytes, barely above the 5 GiB
floor. No images were pulled or removed, no Compose edits were made, and no
repair was admitted in this continuation. Before activating the prepared worker
then API, recheck CI, validate provenance on the VM, ensure capacity while
retaining current/rollback images, and verify scoped cost recovery afterward.
No additional build is required for this documentation-only checkpoint.

## Cost recovery deployed and 37-publication repair verified

Both Sheets services now run source
`29c38320cb4e3d09a5d284741cf4cb8fee0124aa`, using the two verified digests
listed above. CI test `34259087298` and lint `34259086965` passed. The canonical
provenance verifier also validated each image on the VM and updated
`/var/lib/zeler-platform/image_to_commit.json` before activation.

Worker was activated before API. Each returned HTTP health **200**, with zero
restarts. Pulls completed in **14.65s / 9.93s**, with Compose unchanged until
explicit activation. Capacity was checked before each pull and activation.
Unused local worker images `b47ec04c...` and then `4d193639...` were removed only
after checking every container, protecting current/rollback images and confirming
Artifact Registry recoverability. No volumes or business data were removed.
Final observed free space was **5,414,514,688 bytes**: still close to the 5 GiB
floor, so recheck capacity before any further image pull.

Rollback authorities are the previous running images, retained locally:

- Worker: `d4a665c9bf05fc4ee3463ca71b3c10a93cde06a7339250fcea6ca5e4537ff6a3`.
- API: `d9bfc8a87bf68765bb453618113402139dcd90abbb8d1d9ae3674b96ba2bc844`.

Compose backups are
`/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-29c3832`
and `...pre-sheets-api-activate-29c3832`. Roll back only the affected image
binding/service, not an entire backup that would overwrite the other service's
new binding. Never delete the recovered data as part of image rollback.

The read-only pre-repair probe reconfirmed **37 affected publications**, the same
stored field reasons, and no running jobs. An approved VM operator then invoked
the deployed calculator dispatcher and normal API queue-admission helper for
exactly those IDs. Two selected jobs (**20 + 17**, neither inventory-scoped)
completed on their first attempt through the running worker. Receipt with IDs
is mode 0600 at `/var/lib/zeler-platform/repairs/cost-recovery-29c3832.json`;
IDs and customer field values were not printed. Do not repeat `pilot.py prepare`.

| Verification | Result |
| --- | --- |
| Before admission | Required data unavailable; read 0.0162s |
| First terminal observation, 21.20s after selection | 40 rows, zero partial misses, zero unavailable cells, 40 numeric prices; read 0.0305s |
| Second read, 66.97s after selection | Same complete 40 rows, no recovery request; read 0.0355s |
| Global freshness markers | Unchanged |
| Stored cost-state scan of 2,859 rows | Zero affected publications for shipping, commission or fixed fee; zero running jobs |

These are real production Mongo/worker/dispatcher results, **not authenticated
HTTP or Google Sheets acceptance**. The last stored-state scan does not establish
whole-inventory freshness; only the selected rows passed the current formula
reader's freshness checks. Runtime scripts: `/tmp/zeler-cost-gaps.q5RZkE/`;
read-only checks are `pilot.py status` and `inspect-after.py`. No new repository
executable code or new root-test run was needed in this deployment-only unit;
the preceding unit records the passing suite and HTTP/Mongo regression test.

The images also contain the earlier catalog winner/target normalization fix,
but existing catalog data and automatic catalog acquisition remain unverified.
Next address continuous inventory refresh and catalog recovery, then complete
all-52 authenticated HTTP and real Sheet/app acceptance and minimum hardening.
The current `main` differs from image source only in progress documentation;
no new build is required for this checkpoint.

## Successful inventory refresh no longer restarts the waiting period

The queue applied a fresh 15-minute cooldown at the end of every inventory
sweep, although the reader ages its membership from discovery. A real-Mongo
clock test reproduced the unnecessary wait: a successful 13-minute sweep could
not be claimed again until minute 28; a 17-minute sweep waited until minute 32.
Initial regression result: **2 failed, 4 passed in 1.34s**.

Successful inventory checkpoint completion now sets the next eligible time to
the later of completion and discovery plus 15 minutes. The same cases become
eligible at minute 15 and minute 17 respectively. Failed inventories retain
their cooldown from completion; selected-item and date-range jobs are unchanged.
No automatic recurring job, new queue, freshness extension or upstream call in
a formula was added. A formula request still reopens the existing coalesced job.

`uv run pytest modules/sheets/tests/test_formula_recovery.py -k 'inventory or
cooldown' --tb=short`: **72 passed, 206 deselected in 12.73s**. The new cases
exercise 0/13/17-minute success and failure, valid per-batch leases, concurrent
request coalescing, unchanged observation time, expired inventory still rejected
as current, and no self-restarting completed job. Protected Mongo regression
suite: **8 passed in 2.35s**. Ruff check/format, mypy (505 files), and diff check
pass. Full local replica-set suite (`uv run pytest --tb=short`): **3,963 passed,
9 skipped, 356 warnings in 110.13s**. Eight skips are the protected Mongo cases
run separately above; the remaining skip is the Caddy required-keys check.

This is local Mongo queue/reader integration evidence, not a new production
refresh acceptance. A new **Sheets worker** image is required to activate the
changed checkpoint policy; the API admission code did not change. Existing
production terminal records were not retimed. Verify the next actual successful
inventory completion and its persisted eligibility before claiming this runtime
behavior. Continuous fresh availability, catalog and all-52 HTTP/Sheet acceptance
remain outstanding.

Rollback boundary: the successful-inventory `available_at` calculation in
`formulas/recovery.py`, its focused test and the matching formula-readiness
documentation. Do not alter existing acquisition timestamps or recovered data.

### Refresh-age worker deployed; live inventory in progress

Source `a607932456a25b27b6f7d1871f3d4bf523260925` is deployed to Sheets worker
as digest `65a8dcffe3ae125b94c3b50092af3e5fa08abd88921b8fe8ddc8b512940dc623`.
Cloud Build `8ed7388d-cef9-4cb5-af7c-1bde7413af59` succeeded; canonical provenance
checks passed locally and on the VM. CI test `34260903817` and lint
`34260903789` passed before activation. Worker HTTP health is **200**, with
zero restarts. API remains source `29c3832`, digest `c679a81b...`; no API change
is needed for the inventory checkpoint calculation.

Capacity checks protected both services' current/rollback images. The unused
local API image `02b4788b...` was removed only after all-container checks and
Artifact Registry recoverability confirmation; no volumes or data were removed.
Worker pull took **12.63s** and did not change Compose. After activation,
free space was **5,404,864,512 bytes**, so another pull still needs a fresh
capacity check. Worker rollback is retained digest
`791e9c90eb9871b1e7573a429e013035ee8a279e064383a4fe77fd1030dfaea7`;
backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-activate-a607932`.

One normal inventory recovery was admitted from the deployed calculator's
unavailable result. No timestamps were retimed and no global freshness marker
was written. Initial reads honestly reported all 1,900 publications unavailable
under their expired receipts. At **29.04s** after receipt selection, the worker
was running at **60 / 1,900**, with zero exhausted/unavailable IDs and unchanged
global markers. Membership observation age was **21.24s**; both calculator and
quality reads showed current membership but incomplete rows. Their independently
timed reads straddled worker checkpoints and must not be treated as one atomic
row-count snapshot.

This is an in-progress checkpoint, **not terminal eligibility or whole-inventory
acceptance**. Continue polling the existing job; never repeat preparation:

- Job: `5f2485d573679264481950cce24b1373d2eb93f11c1f79ea2aca606b92d20a8f`.
- Receipt: `/var/lib/zeler-platform/repairs/inventory-refresh-age-a607932.json`.
- Artifacts: `/tmp/zeler-refresh-age.uYUpMd/` (local and VM).
- Read-only check: `sudo python3 /tmp/zeler-refresh-age.uYUpMd/pilot.py status`
  on the VM. At successful completion, require
  `successful_eligibility_matches_observation: true`, then verify formula values,
  freshness and any recoverable field gaps separately.

No executable changes were made in this deployment-only unit; preceding local
tests and current CI support the deployed source. Current `main` will differ
only by this evidence document, which does not require another image build.

## Catalog acquisition includes variation products and fresh associations

The existing historical/reconcile catalog acquisition now includes product IDs
from both the publication and its variations. Product requests are deduplicated;
a variation-only association does not create an item-level buybox request.
Freshly fetched item associations replace stored associations for the same item,
including an explicitly removed parent association. Previously the merge kept
the Mongo association first, causing a changed live buybox identity to fail or
an already removed association to be queried again.

The source query remains seller-scoped and projects only item identity, parent
product ID and variation product IDs. An association-free item is kept in the
in-memory merge so fresh absence can replace stale selection. This does **not**
delete existing catalog snapshots or certify whole-seller snapshot freshness.
No schema, endpoint, queue or formula-call API traffic was added.

Two initial acquisition regression cases failed in **0.29s**. After correction,
the historical suite passed **54 tests in 0.28s**, covering fetched replacement,
removal, stored variation-only products, deduplication, seller isolation and
catalog snapshot persistence through the existing test harness. The fixtures
use valid variation SKUs; no-SKU identity reconciliation remains covered by its
separate Mongo suite. A real-Mongo projection test passed **1 test in 0.46s**
(278 deselected), confirming dotted-field projection and seller scope without
writing snapshots. Protected Mongo suite: **8 passed in 2.32s**. Ruff check/format
and mypy (505 files) pass. Full local replica-set suite (`uv run pytest
--tb=short`): **3,966 passed, 9 skipped, 356 warnings in 113.03s**. Eight skips
are the protected Mongo cases run separately; the remaining skip is Caddy keys.

Runtime acceptance is pending: historical acquisition is not the running
formula-recovery worker's catalog implementation. Its callers are the existing
historical CLI/reconcile path. Before using this correction in that runtime,
build a verified Sheets image containing the change and verify normalized
product persistence/readback. Do not run a broad historical backfill merely to
deploy it. Catalog participation, complete current membership, field completeness,
and automatic recovery still need implementation/verification.

Rollback boundary: catalog source extraction/merge, variation-product selection
and the matching tests in `historical_meli_backfill.py` and its test modules.
No recovered production data should be deleted. This local unit does not change
the running inventory job or the deployed refresh-age worker.

## Refresh-age inventory and cost follow-up: full current read verified

The existing inventory job completed **1,900 / 1,900**, with zero exhausted IDs.
`successful_eligibility_matches_observation` is **true**. The persisted next
eligibility is **228.664s** after completion, consistent with a **671.336s**
sweep and the original 900-second observation interval; completion did not add
another 15-minute wait. No preparation was repeated and no timestamps or global
freshness markers were changed manually.

The first terminal read at observation age **737.73s** returned all 2,859 rows
with current membership and zero partial misses. CALIDAD had zero unavailable
cells; CALCULADORA still had 748 unavailable cells. The whole-inventory reader
requested targeted field recovery for **58 publications / 141 variation rows**.
The normal queue-admission helper scheduled three selected jobs (**20/20/18**),
not another inventory. All three completed on their first attempt. At the
43.16-second follow-up observation, those 141 rows had zero unavailable cells,
no further recovery request, and a **0.0676s** Mongo-backed formula read.

Final whole-inventory verification, at observation age **859.26s**:

| Formula | Rows | Partial misses | Unavailable cells | Read duration |
| --- | ---: | ---: | ---: | ---: |
| CALCULADORA | 2,859 | 0 | 0 | 4.0180s |
| CALIDAD | 2,859 | 0 | 0 | 2.8258s |

Both reads reported current enumeration, complete inventory rows and no expiry
warning. CALCULADORA had 2,859 numeric prices. Global freshness markers remained
unchanged throughout. This proves a full current backend read at that time,
**not perpetual freshness, all-52 authenticated HTTP or Google Sheets acceptance**.
Do not extend these receipts or run another sweep solely to recreate this result.

Receipts (VM, mode 0600) and commands:

- Inventory: `/var/lib/zeler-platform/repairs/inventory-refresh-age-a607932.json`;
  read-only `sudo python3 /tmp/zeler-refresh-age.uYUpMd/pilot.py status`.
- Cost follow-up: `/var/lib/zeler-platform/repairs/inventory-cost-followup-a607932.json`;
  read-only `sudo python3 /tmp/zeler-refresh-age.uYUpMd/cost-followup.py status`.
- Both `prepare` modes have already executed; never repeat them as status checks.

No repository executable changes, image rebuilds or deployments were needed in
this verification unit. Runtime remains worker source `a607932`, API `29c3832`;
catalog source-selection fix `e612473` is not deployed. Before invoking that
corrected historical/reconcile path, include it in a verified Sheets image and
verify catalog persistence/readback. Normal automatic catalog recovery and
participation evidence remain unfinished. The last CI check for `e612473` showed
lint `34262518703` passed and test `34262518663` still running.

Rollback remains the service-specific image bindings documented above. These
legitimately acquired costs must remain persisted; rollback is not data deletion.

## Catalog participation evidence and acquisition count correction

A read-only approved-runtime probe selected 20 owned pilot publications with
stored product links and fetched their current item details through the normal
Sheets gateway (four batches of five). Every response identity and seller was
checked. All 20 still had product links, but **19 returned `catalog_listing=false`
and only one returned `true`**. Mongo retained a known boolean for **zero** of
these 20. This is a bounded sample, not a seller-wide participation estimate.
Script: `/tmp/zeler-catalog-participation-probe.py` (local and VM). No business
data was written, and no IDs, customer values or credentials were printed.

This evidence rules out inferring participation from `catalog_product_id` alone.
Next preserve the explicit source boolean through normalization/persistence and
use it in the relevant formula and buybox-selection consumers, while keeping
unknown distinct from false. The live probe does not implement that fix; current
runtime classification/automatic catalog recovery must not be declared correct.

Review also caught a reporting inconsistency in the preceding variation-source
change: acquisition included variation products, but `snapshots_found` still
counted parent links and counted association-free rows as buybox candidates.
Two added assertions failed (**2 failed in 0.28s**). Product and buybox source
lists are now computed once and reused for both requests and counters, preventing
the report from describing a different scope than acquisition.

Verification: `uv run pytest modules/sheets/tests/test_historical_meli_backfill.py
--tb=short` — **54 passed in 0.24s**; Ruff check/format, mypy (505 files), and
diff check pass. A new full root run was not performed for this counter-only
correction. The existing historical harness verifies scoped requests, persistence
and report counts; live corrected-counter acceptance remains pending deployment.
Rollback is the source-list reuse/count calculation and its two assertions in
the historical module/tests, not acquired data or the prior variation fix.

No deployment occurred. Worker remains `a607932`, API `29c3832`; before using
the corrected historical/reconcile catalog path, include these source-selection
and reporting fixes in a verified Sheets image and check persisted catalog
results. They do not justify another inventory sweep or changes to other products.

## Item-recovery continuation release deployed

Commit `208decf296f8f0b8d9f39925421a745aaf337510` was built from the connected
GitHub repository and deployed in worker-first order on the pilot VM. The Sheets
worker image is pinned to digest
`sha256:f767ecfd4d38ae9960ceb0d539abaed63d0295d0fd3482e24868443469828c72` and
the API image to `sha256:b7fa74a383f5b5206365818124682df1937e005266df8cee87ec7732afe2661a`.
Both containers report `healthy`; the API's internal `/health` endpoint returned
HTTP 200. Preflight reported 6.6 GiB free before worker pull and 6.1 GiB before
API pull (both above the 5 GiB gate). Previous running digests and Compose
backups were retained at the VM for service-scoped rollback.

This proves image provenance, activation and basic runtime health only. The
large item-request continuation still needs an authenticated formula/Sheet
exercise and persisted-job readback; the full 52-formula goal remains open.

## Catalog-unavailable fallback release (in progress)

The pilot VM showed 11 item documents without `catalog_listing`. A bounded
MercadoLibre enrichment returned all 11 details; five records were updated and
six were confirmed as 404/unrecoverable. The write was limited to seller
`82453304` and those 11 item identities; no fabricated participation value was
introduced.

Commits `2e7fdd5`, `bb0cb4d`, and `849b290` add the controlled fallback used by
the reconciliation path: unknown or incomplete catalog participation, and
individual 404 product/buybox snapshots, are counted as unavailable and do not
block valid catalog snapshots. Direct backfill callers retain the previous
strict behavior by default. Focused historical-backfill tests, reconciliation
tests, Ruff, and mypy pass.

Cloud Builds for `849b290` succeeded. The resulting immutable images are
`sheets-worker@sha256:4f06bc873f7fc206b488593023f8c14c9f1cbba7c8c876b72bc26224b5023aa3`
and `sheets-api@sha256:6ca039bd8b02974064c21916fcf03972824c5708c3693843332deccc4a42246e`.
The VM boot disk was expanded from 30 GB to 50 GB after the documented 5 GiB
preflight could no longer be maintained; the root filesystem now has 24 GiB
free. Activation of these final images and the subsequent authoritative
reconciliation/readback were initially pending while local GCP access recovered.

Follow-up on 2026-09-10: the existing deployment session exited 0. An independent
VM `docker compose ps sheets-worker sheets-api` confirmed both final `849b290`
digests listed above active and healthy. Authoritative reconciliation and
functional readback remain pending. See the consolidated
[closure-of-progress report](sheets/zelerdata-cierre-avance-20260910.md) for the
remaining acceptance gates and limits of the 52-formula HTTP evidence.
