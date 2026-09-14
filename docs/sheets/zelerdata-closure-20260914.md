# ZelerData full closure — September 14, 2026

Status: implementation and recovery in progress; the 90-minute certification
window has not started. Source of acceptance: the updated
`openspec/changes/zelerdata-live-formula-repairs/` artifacts and the user's
approved plan (35 simultaneous cases, 90 minutes, combined evidence for absent
positive production fixtures).

## Broker baseline

Read-only probes inside the approved Sheets runtime confirmed DNS and TCP
connectivity, HTTP 200 from broker management, 20 current connections and a
configured `max-connections=20`. Seventeen connections had no channels; all 20
were running and older than ten minutes. A new AMQP connection was rejected
with reply code 530. No limits, topology, messages or credentials were changed.

API `/health` and gateway `/ready` returned 503 with RabbitMQ unavailable;
Mongo and registry checks passed, as did the gateway scheduler. Sheets worker
Docker health remained healthy, so that alone does not prove broker admission.

Installed aio_pika exposes `is_closed`/`connected`, not `is_open`. A local
non-network reproduction of the actual gateway checker performed ten probes,
created ten additional connections and never closed the original. Existing
test doubles supplied `is_open` and hid the real interface mismatch. The
gateway correction must preserve ownership during reconnect, cancellation and
shutdown as well as normal reuse.

Independent probe inspection additionally reproduced orphan robust reconnect
work after core health timeout and an unbounded Sheets passive queue operation.
Each executable correction requires its own failing regression before editing.

## Delivery boundaries

The three scoped service replacements are complete. Preserved rollback identities:
gateway `sha256:2d4a514cab2d3ddca7e95109aeedc1e11e41115f8c09fddedd850aa0dc9ef130`,
Sheets API `sha256:07499cf3ce2de2e99d41f31db8be557110131c4e941e7068d788b3e2e747f7b7`
and Sheets worker `sha256:887781cf8d9264a9d49912af03049979a618dd30292a716e3d734a6e75001b98`
These identities remain rollback evidence, not proof of current acceptance.
The deployed candidates are bound to the exact source/build/digests below.

Current source calls the shared helper from four module APIs. Runtime inspection
confirmed that repricer, publicador and autoreply still run older images without
that helper; their updates would include unrelated product changes. This delivery
is limited to gateway, sheets-api and sheets-worker. Record those other images
as drift requiring a separately scoped assessment.

## Certification record

Pending: guarded returns/historical source verification, complete matrix
expected/actual evidence, any additional repair gates and delivery,
three simultaneous 35-case rounds at minutes 0/30/60, 90 continuous minutes of
lightweight runtime observations, diagnosis readback and independent SDD closure.

## Local implementation acceptance

Final corrected isolated-Mongo suite: **4663 passed, 9 skipped** in 244.07 seconds.
The eight protected replica-set cases passed separately with an explicit verified
loopback target and no ambient MONGO_URI. The ninth skip is the existing Caddy
fixture with no required keys. Ruff check/format and full mypy passed (547 files);
direct-Meli lint passed. Initial suite failures were caused by an invocation URI
without a default database; all 39 affected cases and the full corrected suite
passed. No production database was used.

Gateway ownership, ephemeral probe cleanup and inventory cadence each have
RED/GREEN evidence and independent focused review in the change's apply-progress
artifacts. A 35-way local authenticated API harness with 1900 source documents
completed in 3.096 seconds (maximum request 3.061 seconds), with no HTTP 5xx or
PROCESSING. This proves bounded local load, not 35 positive production outcomes:
nine cases had explicit missing synthetic coverage, and the harness excludes
the gateway and native Sheets execution. Production certification remains pending.

## Verified release candidates

Connected repository source `f30f33d3bedb90cd816a7c80eb34564b6b81a53b` was pushed to main before the three separate VERIFIED Cloud Builds. Local provenance verification bound the exact repository, source and digest. Runtime verification remains separate.

| Service | Build ID | Immutable digest |
| --- | --- | --- |
| gateway | `e767e707-274f-4ec4-b2e4-6632cd654803` | `sha256:4b10da0f1ade34d4c88a0b3b2b7a9ca3f55da633e10f33e90d0550f57425435c` |
| sheets-worker | `3e2d6073-ab8a-4708-bc87-1046292b0235` | `sha256:4d3b8c2e86d89fdf5b1f4985dd22c74894b1130b977acfe4f8112675d4429713` |
| sheets-api | `c88ea9c3-a9e4-48cf-98b6-249975fd8968` | `sha256:32c665795a3d35b302300b7359f92da5d44224c3b939a232361d8e86c4cd801b` |

Delivery order: gateway, worker, API. Preserve the exact prior identities above and attest the prior Sheets API registration contract. Enable existing worker refresh only for seller 82453304 with the broad interval 900 seconds; inventory admission uses the new 30-second callback. No other product image, broker limit/topology, schema validator, cleanup or capacity mutation is included.

At 20:05:29 UTC before replacement: 20 broker connections, 17 without channels, 3 channels, 146 ready messages, 0 unacknowledged messages, 4 consumers. Root available bytes 27,581,247,488; Mongo available bytes 48,584,208,384, mounted separately on /dev/sdb ext4. Memory available 783 MiB; do not infer post-delivery capacity from this baseline.

## Gateway live verification

Gateway candidate was narrowly deployed and its immutable running identity and
container health verified. At 20:18:05 UTC the broker had 11 connections, eight
without channels. Thirty concurrent readiness requests (concurrency ten) all
returned HTTP 200 with dependency readiness, in 1.142 seconds. Connections stayed
at 11 immediately after those requests and at 20:20:58 UTC; gateway Mongo,
registry, RabbitMQ and scheduler checks remained ready. This establishes the
gateway correction's initial live behavior, not the full 90-minute acceptance.
The old Sheets API still ran at that observation; the later API evidence below
supersedes its connection count.

All eleven historical daily source acquisitions completed successfully through
the canonical gateway-backed dry-run. Ten days returned productive source rows;
June 23 returned zero productive projections from an inventory of one claim.
The June 23 legacy identity is now privately bound to the canonical low-cost
exclusion without authoritative item identity. Daily source success does not
publish original-range coverage. The guarded-write outcomes are recorded below.


## Worker/API delivery and warm-up

All three deployed images match the table above and source
`f30f33d3bedb90cd816a7c80eb34564b6b81a53b`. The worker refresh is enabled only
for the pilot seller; broad refresh remains 900 seconds and inventory admission
30 seconds. The first inventory sweep completed at 20:35:47 UTC in 775.848
seconds (12m55.848s). Every minute sample from 20:36 through 20:44 showed all
1900 sources fresh, zero expired. All discrepancy sets observed since 20:38
resolved by the following minute; an earlier set persisted during warm-up,
so these samples are not a passed certification window.

At 20:36:58–20:37:11 UTC, thirty API health probes with concurrency ten returned
HTTP 200; the separate health read confirmed Mongo, RabbitMQ, registry and claims
DLQ readiness. Broker connections remained four before/after, one without
channels, with 146 ready messages and zero unacknowledged messages. Warm-up
samples through 20:44 showed no restart/OOM and stable four broker connections.

## Guarded returns repair outcomes

May 2 canonical reconciliation succeeded (expected/persisted/complete 1).
The seller-wide legacy blocker count moved from 11 to 10. May 14's canonical
operation failed validation, after productive writes, and the count moved to 9.
A read-only identity comparison subsequently proved all four expected IDs exist
with productive v2 data; one has a source and persisted creation timestamp before
the requested UTC day. The date-filtered readback counted three and raised
`claims_reconciliation_incomplete`. Another write retry cannot fix that interval
disagreement. A focused regression/correction passed local verification; no guard bypass
or invented productive return is permitted.

June 23 has one legacy blocker but no productive canonical projection. The
approved product policy excludes low-cost facts without authoritative item
identity before persistence. A negative projection would still violate the
historical guard. The [one-record migration proposal](devoluciones-jun23-migration-proposal.md)
preserves the original in audit custody and requires explicit scope authorization;
no such migration has been executed.

## Native 35-case warm-up round

All 35 anchors were changed in one native batch at 20:42:53.908 UTC, preserving
inputs, signatures and other cells. At 20:45:54.999 (just beyond three minutes),
29 anchors still reported Sheets LOADING. This round failed the agreed deadline.
At the complete capture ending 20:48:20.672, no anchor remained LOADING, but eight
large formulas returned PROCESANDO, indicating API deadline exhaustion. The
three calculator cases also contained explicit unavailable source fields.
DEVOLUCIONES remained unavailable; stock-time, catalog-time and withdrawals
reported uncovered intervals. These are measured failures/limitations, not
successful 35-case acceptance.

The independent source cut ran 20:44:34–20:46:13 with receipt validation at
20:45:08: 1900 item identities, zero remaining invalid projection receipts,
2859 quality rows, 936 catalog/buybox rows, 881 catalog products, 285 neglected
rows and four selected publication rows. Source and full native output comparison
remains separate from structural capture; timestamp alignment must not be relaxed
to manufacture certification. The 90-minute window has not started.


## Remaining measured performance work

Live execution logs locate the eight large-formula deadline failures in dispatch,
not recovery admission. Individual read-only handlers complete in roughly
3–15 seconds, but simultaneous requests repeat the 1900-item source acquisition.
One measured full item read transferred 18.67 MB in 4.929 seconds and full
fingerprint computation added 1.831 seconds of synchronous CPU. The next bounded
correction shares only identical reads currently in flight, with per-request
freshness/receipt validation, seller/database isolation, cancellation ownership
and no retained result TTL. RED/GREEN, independent review and final local quality
gates passed; runtime verification remains pending.

Calculator source values exist, but acquisition states include basis mismatch
and stale observations (measured ages 2841–7061 seconds). Their unavailable
cells must not be described as absent input data or converted to invented zeros.
Enrichment scheduling/recovery is under investigation.

All 24 native diagnosis rows were updated for this failed warm-up round; only
columns C/E/F changed. Readback matched all 72 intended cells. Original labels,
expected results, links and formatting were preserved. The independent comparator
found no value discrepancies among the available-result cases in this diagnostic
cut, but the final native capture exceeded the source-cut alignment budget;
therefore no case gained certification from this comparison. The eight timeout
outputs cannot be compared as complete matrices.


Follow-up warm-up did not preserve zero-expiry: at 20:53, 193 item sources were
expired (maximum age 966 seconds); at 20:56, 390 were expired (maximum age 1012
seconds). Some identical receipt discrepancy tokens persisted between samples.
Broker connections stayed four, with no container restart/OOM. These measurements
invalidate any claim that cadence alone solved sustained freshness. API/load
optimization and a fresh simultaneous-load observation are required; earlier
all-fresh samples remain only point-in-time evidence. A diagnostic comparator also
exceeded its 90-second wrapper limit; its own process had ended when checked and
no service was stopped. The auxiliary comparison was optimized and given an
internal timeout before further use. No causal attribution of expiry to that
auxiliary alone has been established.


The next fully observed inventory sweep completed at 21:07:46 UTC after
1035.354 seconds (17m15.354s), failing the 15-minute limit. During 20:53–21:08,
base expiry and repeated receipt discrepancies persisted; connections remained
four and no container restarted or reported OOM. This was still the previous
production code, before the new concurrent-read correction. Local representative
performance evidence for that correction is promising but is not substituted
for another live sweep or the required complete window.

## Second correction batch: local verification

The final production-code tree passed 4709 tests (9 documented skips), Ruff,
format checks and full-repository mypy (551 files), using the verified local
replica set on loopback port 27028. Eight protected transaction tests passed
separately with their explicit test-target variable. A test-only assertion was
corrected after the full suite started; all three parameters and its Ruff,
format and mypy checks then passed separately. No production code changed
between these checks.

This batch shares identical item reads only while they are in flight, treats
economic tags as membership flags, projects persisted siblings before propagating
an ordinary acquisition failure, and validates returns against canonical UTC
membership with truthful per-chunk persisted counts. It changes neither the
180/minute acquisition budget, the 15-minute freshness requirement, schemas,
registry permissions nor the 25-second API deadline. The affected service images
are Sheets API and Sheets worker; gateway code is unchanged from its verified
f30f33d3 deployment. Exact-source build, delivery, new live warm-up and the full
90-minute acceptance window remain pending. The June 23 quarantine migration
remains a separate unapproved scope.

Independent local review found no blockers in in-flight read ownership,
canonical return membership/readback, retained economic tag bases, or partial
projection error propagation. This review and passing local checks establish
implementation evidence, not live acceptance.
