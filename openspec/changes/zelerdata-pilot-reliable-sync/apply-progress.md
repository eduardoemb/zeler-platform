# Apply Progress: ZelerData Pilot Reliable Sync

## Pilot rollout and first live observations (2026-09-23)

The connected-repository Cloud Builds for exact `main` commit
`c51e88ebf0eda0fa17044e30d7e76ee4c3a111d8` succeeded with one VERIFIED
image each. Sheets worker build `faeced9c-d881-4b2f-9178-b3f6ef8e4590`
produced `sheets-worker@sha256:4707f4fdccbac1e53c20bc76a7787290f4354752fdcca53828fd1070d9c9d3d0`;
Sheets API build `3d11659e-65e4-4056-8d7c-147007fe275f` produced
`sheets-api@sha256:49641ed22c598744299d80327325912b49aa15f98c5797328243fbfb55bc90b5`.
Local and VM provenance gates bound both digests to that commit. The prior
running worker/API digests were `sha256:081ef4b92474452b228309c9b8a28cc8f0633fb9952c395144728ba8b8f361a9`
and `sha256:9b34a2869c65c545d4a2b6cd744fb265432a78cdcc6bdb0b5ef23996347a086d`;
their running RepoDigests and separate Compose backups were recorded for rollback.

After the four-collection validator rollout below, the worker alone was
updated. The existing sync-jobs migration record was present and no active
seller/spreadsheet duplicates existed. Only `sheets_sync_jobs.json` indexes
were then applied from the staged source; readback confirmed the new unique
partial pending/running index. The API alone was updated last. No cleanup was
performed. Root capacity passed before each pull and after each download;
the last read showed ~34.7 GiB free on `/`, Mongo on its separate mount and
~1 GiB available memory. At first and settling checks both containers had the
expected digest, healthy state, zero restarts/OOM; API Mongo/RabbitMQ/registry/
claims-DLQ checks and worker RabbitMQ/sync-jobs/formula-recovery/refresh checks
all reported ready.

`ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED=true` was then added only to the
root-owned Sheets worker env file with a timestamped backup, and only that
worker was recreated. It retained the verified digest and all readiness checks.
The pilot plan now exists. The first protocol observation found two active
order acquisitions, 290 membership receipts and three detail receipts; a later
read found 1,035 memberships and 37 details, with both heads hydrating and no
protocol job failed. An overlapping active legacy month was reported as
`legacy_order_job_active`. No completed interval or 12-month proof is claimed;
continue observation before calling history functional end to end.

At 2026-09-24 06:04 UTC, an approved-container readback found the first
protocol interval completed: its queue job and acquisition head were both
`completed`; source total, discovered, fetched, published, membership receipts,
detail receipts across the discovery and verification passes, and persisted
orders were all 90. The exact interval was
`[2026-08-24T05:36:28Z, 2026-09-24T05:36:28Z)`. A reconciled orders marker
covered it and was valid at observation. A separate 945-order acquisition was
still hydrating, with 164 details fetched at 06:02 UTC. The worker and API
remained healthy at the readback, with the intended immutable digests, zero
restarts and zero OOM flags. This proves one bounded production interval, not
the full twelve-month plan or continued marker freshness.

At the ~30-minute post-flag checkpoint (2026-09-24 06:17 UTC), the older
`[2025-10-24T05:36:28Z, 2025-11-24T05:36:28Z)` acquisition had hydrated
446 of 945 discovered orders; its queue job was still running and neither
protocol job had failed.
The orders marker was renewed and valid at the checkpoint. Both Sheets
containers retained their expected digests and healthy state with zero
restarts/OOM. Free space was 37,277,286,400 bytes on `/` and 48,269,123,584
bytes on the separate Mongo mount; free inodes were 6,226,841 and 3,276,299;
available memory was 689,127,424 bytes. This is a runtime observation, not a
native 35-case Sheets certification round.

A separate approved-container read at 06:18 UTC confirmed that
`item_history_projection`, `meli_item_events`, `withdrawal_records`,
`catalog_time_metrics`, `stock_time_metrics`, and `full_withdrawals` were all
absent. The pilot devoluciones ledger still had seven failed runs and one
completed run, with no authorized/active run. These facts explain the four
historical formula gaps and prevent automatic advancement of the failed quota
runs; they do not authorize a production data repair.

The user clarified on 2026-09-24 that formulas without historical source may
honestly return `DATA_UNAVAILABLE`. This accepts the four source-absent
historical metrics as unavailable in the pilot; it does not certify their
Sheet executions or broaden the exception to transient failures or available
source data. The 52-formula matrix now records this acceptance boundary.

At 2026-09-24 06:46 UTC the older
`[2025-10-24T05:36:28Z, 2025-11-24T05:36:28Z)` interval completed after a
second membership traversal and bounded publication. Independent approved-
container readback found 945 for each of source total, discovered, fetched,
published, verification-pass membership receipts, detail receipts and
persisted orders; the queue job was `completed`. Before publication the same
interval had zero persisted orders. The resulting orders marker retained this
exact reconciled interval and was valid at readback, so this adds real
historical coverage. The recent 90-order interval also remained completed and
reconciled. No protocol job had failed; one more orders month was queued, and
the full twelve-month plan was still incomplete.

At the ~60-minute post-flag checkpoint (06:47 UTC), worker and API remained
healthy on the selected immutable digests with zero restarts/OOM. Free space
was 37,304,344,576 bytes on `/` and 48,264,331,264 bytes on the separate Mongo
mount; free inodes were 6,226,841 and 3,276,299; available memory was
687,697,920 bytes. The orders marker remained valid. This is the second
runtime checkpoint, not a native Google Sheets 35-case round.

Read-only Google Sheets connector inspection identified the private
`Pruebas ZelerData actual` workbook, tab `Goal_Pruebas_20260909`, with all 52
existing formula anchors intact. Five anchor values still displayed
`DATA_UNAVAILABLE` (DEVOLUCIONES, CATALOGOTIEMPO, TIEMPOSTOCKACTIVO, RETIROS,
SEMANASCONSTOCK) and five displayed `NA`. The workbook predates this rollout;
no recalc or authenticated formula HTTP smoke was performed by this inspection.

## Scoped continuation: pilot history admission headroom (2026-09-23)

At the production queue capacity, both history callback paths formerly admitted
19 of the 20 seller slots before hitting the inventory reservation. Real-Mongo
RED cases measured that saturation. The callback now counts active plan jobs,
including legacy monthly orders, and admits at most four active history jobs
per seller when queue capacity exceeds four. The cases verify two orders and
two questions admitted, a separate query and inventory accepted, and the next
history chunk admitted when one historical job becomes terminal. Small test
queues retain their existing priority/capacity behavior. This is one-callback
headroom, not an atomic
cross-process history quota or a complete sustained fairness proof for task 2.4.
The 38 focused lifecycle/backfill/pacing cases passed. The full root pytest
suite exited successfully with nine expected skips; root Ruff check, Ruff
format check and mypy passed across 606 source files. Schema export and
direct-Meli lint also passed.
Read-only pilot Mongo count inside the approved worker container found 2,432
known orders created during the preceding 365 days. That is below the local
10,000 known-order budget at this observation; it does not measure provider
search volume or prove future headroom.

Scoped VM schema rollout used the reviewed files already in `main` at
`2e798f2`: `processed_event_claims` and the three history collections only.
The staged archive checksum matched on the VM. A container-context dry run
reported all four as `would_create`; the apply then reported four created
collections and their indexes applied. Readback reported all four validators
unchanged against the staged source and index counts 2, 2, 3 and 3 respectively
(including each `_id` index). The sync-job index remains a separate API rollout.
No history flag or service image was changed by this schema step.

## Scoped continuation: opt-in order history admission and runtime composition (2026-09-23)

`ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED` now selects a plan-bound order
request in the existing refresh callback and adds an orders-only history poller
to the worker's recovery supervisor. The poller shares the exact same pacer,
range lane and seller allowlist as existing recovery. The flag defaults off.
Active legacy order jobs for the same monthly interval defer new-protocol
admission and are reported as `legacy_order_job_active`; terminal legacy jobs
can be followed by the new protocol without rewriting old jobs.

Strict TDD: opt-in callback admission and worker composition first failed
(missing callback argument and three versus four lanes). A separate real-Mongo
case then reproduced simultaneous legacy/new monthly admission before the
defer guard. A real-Mongo callback-to-history-worker test completes an empty
month with an actual queue, acquisition head and reconciled marker; gateway
responses are controlled doubles. The final affected regression passed 125 tests.
The root suite passed 5,402 tests with nine skips (eight protected-rs0 cases
passed separately and one Caddy case lacks keys). Root Ruff check, Ruff format
check and mypy passed; the direct-Meli lint passed as well.
No production validator, flag, image or service has been changed. Only orders
use this new protocol; questions, shipments and items remain open.
Read-only VM/container inspection found the running worker pinned to digest
`sha256:081ef4b92474452b228309c9b8a28cc8f0633fb9952c395144728ba8b8f361a9`
(provenance source `8fdf20c63c38d456a80fff8613b5bdb5c213d6d4`), both Sheets
containers healthy with zero restarts/OOM, root ~36 GiB available, Mongo on
its separate mount and ~419 MiB available memory at the observation. All three
history collections/validators/indexes and the pilot plan are absent; active
legacy/protocol orders jobs count zero. These are dated rollout leads, not proof
of ongoing health. The targeted digest dry-run capacity check passed but did
not attest provenance or authorize a pull. The local broker and protected-rs0
checks passed eight cases each in their isolated harnesses.

Rollback boundary: remove the flag-gated history poller and callback selection
and the matching tests/docs. Keep persisted receipts, projected orders and
protocol jobs; older workers intentionally do not claim protocol jobs.

## Scoped continuation: order publication handoff and final proof (2026-09-23)

The opt-in `HistoryOrdersWorker` now carries a verified order acquisition through
bounded publication and atomic coverage/queue completion. `begin_publication`
checks the current-pass manifest counts and detail receipts under the existing
queue lease before advancing the head. Publication still writes at most 20 orders
per transaction, then finalization compares the persisted inventory with the
verified membership, checks required fields, merges only previously reconciled
proofs, and commits marker, completed head and completed queue job together.
The marker's validity starts from the last source observation, not finalization.
An empty verified interval can also complete without fabricating order rows.

Strict TDD: three new real-Mongo handoff cases failed at the old
`HistoryHandoffPendingError` boundary before the transition; three publication
cases failed without `finalize`; a separate failed-marker case reproduced
resurrection of an invalidated retained proof before its guard was added.
All new cases pass. Four adjacent history files passed **132 tests** on the
isolated loopback Mongo replica set (port 27028); focused Ruff and mypy pass
for all six changed code/test files. Root gates and runtime evidence are separate.
The tests use gateway doubles, so no Mercado Libre or production coverage is
claimed. The normal runtime supervisor still does not launch this opt-in worker.

Rollback boundary: remove the new publisher finalization and its tests, then
the continuation handoff/worker routing and matching order tests/task evidence.
Do not delete receipts, projected orders, or existing coverage markers.

## Scoped continuation: task 2.2 broker-level measured-stage evidence (2026-09-18)

Strict TDD through a delegated implementation worker; no commit, build, deploy,
Docker administration, or production access. The disposable loopback harness
(Mongo replica set on 127.0.0.1:27028, RabbitMQ on 127.0.0.1:5673) was already
running.

The task-2.1 broker harness (loopback guard, disposable Mongo/RabbitMQ, real
`SheetsAmqpConsumerRunner` over the real `modules/sheets/manifest.yaml`, real
handler over real Mongo) was extracted unchanged into the non-test module
`modules/sheets/tests/_broker_harness.py` (same pattern as `_amqp_fakes.py`), and
`test_consumer_broker_delivery.py` now imports it with its four tests and every
assertion unchanged (4 passed).

New file `modules/sheets/tests/test_consumer_stage_telemetry_broker.py` uses the
shared harness with the real `EventStageTelemetry(db=db)` wired into the real
handler. RED was observed first: with telemetry not wired, all four tests failed
because no `sheets_event_stages` document existed (4 failed in 41.57s). After
wiring telemetry: 4 passed.

What is now measured, through the actual consumer:

- Ordered real stages: `received_at <= fetched_at <= persisted_at`, all
  timezone-aware UTC, read back from the stored `sheets_event_stages` document.
- Measured received->persisted latency observed across runs: 87.0 ms, 100.0 ms,
  73.0 ms, 88.0 ms, 82.0 ms (fetch ~9-16 ms, persistence ~60-85 ms on the
  disposable loopback stack). The test prints the measured value of its own run.
- Durability: after stopping the first runner and starting a fresh runner on the
  same queue and database, the duplicate re-delivery is suppressed and the
  timestamps recorded by the first worker are unchanged, proving the measurement
  is durable in Mongo, not process memory.
- First receipt: a retried event keeps the first attempt's `received_at` via the
  min-update, not the retry's.

Explicit scope statement: an export append does NOT prove that the value is
visible in the spreadsheet cell. Every new test asserts the append happened
while `visible_at` is absent from the stage document. The `received -> visible`
leg requires Sheets-side evidence still pending in tasks 5.1/5.3.

Honest assertion deviations (reported, not hidden):

- The task text expected `persisted_at` to exist only after the successful
  retry attempt, but the real handler persists the source document and records
  `persisted` BEFORE the export append (`consumer.py` ~L1161-1200), so the
  failed first attempt already records `persisted_at`. The test asserts the
  honest sequence (first-attempt `persisted_at` present, final `received_at`
  equal to the first receipt, final `persisted_at` not regressed) and documents
  the reason in its docstring.
- The restart test initially asserted exactly one `duplicate` result on the
  fresh runner. The final-verification run exposed a real race: the phase-1
  append can be observed before its broker ack lands, so closing the first
  runner in that window makes RabbitMQ requeue the already-applied message and
  the fresh runner sees it once more. The test now asserts that every delivery
  after the restart is suppressed as a duplicate (no failures, no appends),
  which is the invariant that matters, and documents the requeue window. Eight
  consecutive full runs passed after the fix. No production code was touched.

Validation (all with the disposable loopback stack, `ZELER_RS0_TEST_URI` unset):

- `uv run pytest modules/sheets/tests/test_consumer_stage_telemetry_broker.py
  modules/sheets/tests/test_consumer_broker_delivery.py -o addopts='' -q`:
  8 passed in 8.06s, stable across 8 consecutive runs after fixing the restart
  delivery-count race described above.
- `MONGO_URI='mongodb://127.0.0.1:27028/zeler_task22?directConnection=true'
  uv run pytest modules/sheets/tests/test_event_stage_telemetry.py
  modules/sheets/tests/test_consumer_phase6.py modules/sheets/tests/test_sheets_run_entry.py
  -o addopts='' -q`: 38 passed in 1.87s.
- `uv run ruff check` and `uv run ruff format --check` on all three touched test
  modules: clean. `uv run mypy` on `event_stage_telemetry.py`,
  `_broker_harness.py`, and the new test file: no issues in 3 source files.
- Independent verification (2026-09-18) re-ran the broker pair with `-rs`: 8
  passed, zero skips; it reproduced the stage ordering, the absent `visible_at`
  and the restart durability read back from the stored documents, and confirmed
  the task-2.1 assertions are identical after the harness extraction. A separate
  orchestrator run with `-s` printed `measured received->fetched->persisted
  latency: 104.0 ms (received_at=2026-09-18T16:42:50.105000+00:00,
  fetched_at=...120, persisted_at=...209)`, corroborating the magnitude above.
- Authored line counts: `_broker_harness.py` 448 (about 98 newly authored; the
  rest is the task-2.1 harness moved verbatim), `test_consumer_stage_telemetry_broker.py`
  214, `test_consumer_broker_delivery.py` 161. Authored content for this slice is
  about 286 code lines plus this evidence, so the review unit stays under the
  400-line budget only when the moved harness block is read as moved code; the
  commit must be reviewed as extraction plus one new test file.

Residual uncertainty: the latency numbers come from the disposable local broker
and Mongo replica set, not the production runtime; they bound the worker-side
stages only. `received -> visible` remains unproven until tasks 5.1/5.3. The
restart test tolerates the broker requeue window between append and ack; that
window is the already-declared at-least-once boundary, not a new defect.

## Current evidence status (2026-09-15 continuation)

Implementation is not ready for build/deployment. The task audit reopened 2.2,
3.2, 3.4, 3.5, 4.1, 4.3, and 5.1–5.3. The earlier completion statements below
are retained as the prior session's record, not current acceptance. Source-string
checks, fake-only assertions, and export append timestamps do not prove the
specified runtime paths or formula-cell visibility. The overlap helper has no
production caller. Runtime repair of returns, actual Sheets acceptance, and
independent final verification remain pending.

Native status resolves the selected OpenSpec change and permits apply in this
checkout only. No final verify report exists. On this continuation the existing
local `zeler-layered-test-mongo` container was inspected: Mongo 7.0, loopback port
27028, replica set `rs0`, writable PRIMARY, and nofile 65536. All local tests must
explicitly target this test instance, never inherited production configuration.
No production inspection, mutation, or new test execution is claimed here.

Subsequent scoped work is recorded below and in [the evidence audit](evidence-audit.md).
The audit additionally reopened real admission/routing/checkpoint/fairness tasks
and the exact repository gates. Root `uv run mypy .` currently exits 2 on the
pilot API test's duplicate import path; the prior 171-file result is not a
passing result for that command.

The user authorized the existing `pruebasnuevas` Google Sheets tab for tests.
Its bounded readiness probe wrote only A1:A3. The formula is preserved, but no
calculated value was returned in the recorded connector reads. No authenticated
browser session is connected yet. This is diagnostic evidence, not final formula
acceptance or an add-on publication. All other tabs remain outside write scope.

## Scoped continuation: task 2.2 / pilot-telemetry-evidence (2026-09-15)

Strict TDD; native apply attempt owned and settled by the parent orchestrator.
Delivery strategy: auto-chain logical review slice only; no branch, commit, PR,
build, deployment, add-on publication, or production access. Read the selected
proposal/spec/design/tasks and prior progress, plus lessons L-007/L-010/L-012/L-013.
Engram search was unavailable to this executor; local evidence was sufficient.

Removed the consumer's inferred `visible_at` after event export append and
corrected telemetry docstrings. Five new parameterized real-Mongo handler cases
exercise canonical question persistence, export/no-export, deduplication, and
gateway/persistence/export failure boundaries. Boundary callbacks assert that
receipt exists before fetch and persistence exists before export; failed stages
do not claim completion or mark the event processed. The original weak
handler-document test is retained with an accurate name and description.

All pytest commands below ran with `ZELER_RS0_TEST_URI` unset and `MONGO_URI`
explicitly targeting the verified loopback test Mongo on port 27028, replica set
`rs0`, direct connection. New tests use disposable UUID databases and drop only
those databases in fixture cleanup. No live Google or provider request was made.

| Task slice | Safety net | RED | GREEN | TRIANGULATE | REFACTOR |
| --- | --- | --- | --- | --- | --- |
| 2.2 honest visibility and real handler stage evidence | `uv run pytest -q modules/sheets/tests/test_event_stage_telemetry.py modules/sheets/tests/test_consumer_integration.py modules/sheets/tests/test_consumer_phase6.py`: 14 passed, exit 0 | `uv run pytest modules/sheets/tests/test_event_stage_telemetry.py -k without_claiming -v`: 1 failed (unexpected `visible_at`), 1 passed, 4 deselected, exit 1; executed before source edit | `uv run pytest modules/sheets/tests/test_event_stage_telemetry.py -v`: 6 passed, exit 0 after removing inferred timestamp | Added fetch error, actual seller-scope persistence rejection, and append error; focused three-file run: 19 passed, exit 0 | No structural refactor needed; focused Ruff check/format passed |

Test-authoring corrections before accepted evidence: the first real question
fixture lacked required `from_user_id`; corrected the fixture before obtaining
behavioral RED. During triangulation, an insertion initially displaced the
happy-path assertions; restored their location before the final passing run.
Neither test-authoring failure was used as behavioral RED.

| Work Unit Evidence | Result |
| --- | --- |
| Focused test command and exact result | `uv run pytest modules/sheets/tests/test_event_stage_telemetry.py modules/sheets/tests/test_consumer_integration.py modules/sheets/tests/test_consumer_phase6.py -v`: 19 passed, exit 0 |
| Runtime harness command/scenario and exact result | Same focused command executes five new real `SheetsEventHandler` + `SheetsEventPersistence` + `EventStageTelemetry` Mongo integration cases. Gateway/Sheets/idempotency boundaries are doubles; actual authenticated Sheets visibility is NOT established. |
| Broader affected regressions | `uv run pytest modules/sheets/tests/test_event_stage_telemetry.py modules/sheets/tests/test_consumer_*.py modules/sheets/tests/test_sheets_amqp_consumer_runner.py -v`: 64 passed, exit 0 |
| Static checks | `uv run ruff check modules/sheets/src/zeler_sheets/consumer.py modules/sheets/src/zeler_sheets/event_stage_telemetry.py modules/sheets/tests/test_event_stage_telemetry.py`: passed; corresponding `uv run ruff format --check`: 3 files already formatted; both exit 0 |
| Rollback boundary | Only this continuation's six-line removal in `consumer.py`, visibility docstring correction in `event_stage_telemetry.py`, and new tests/accurate test description in `test_event_stage_telemetry.py`, plus this evidence subsection. Preserve all previous uncommitted pilot work. Pre-slice copies are `/tmp/zeler-pilot-telemetry/{consumer,event_stage_telemetry,test_event_stage_telemetry}.before.py`; do not restore whole files over subsequent edits. |
| Authored review size | Source/tests: 162 additions + 13 deletions = 175 authored changed lines relative to pre-slice snapshots; with this evidence subsection, fewer than 240 authored lines, below 400. |

Logs live in `/tmp/zeler-pilot-telemetry/` (local, ephemeral). SHA-256:
- `baseline.log`: `fe9dca0451129aaabdd76ea13e310b61a52091a146a1f9fe5b72b851eb33547f`
- `red.log`: `a0f83544c62bad542977c6437696bee6748c792540c6d44ddcf471f9e43c62a4`
- `green.log`: `6386873571535bb9a2d0b39fc33148379d14f74a06f84edf8d0df311ee53fc73`
- `triangulate.log`: `7b9665884b96c8161100073c6aac3b4e0121a7feed9b3fc3e4f3ae4b43390488`
- `regression.log`: `0217cfdcd629503ae2809cdebafaf4acf3be71a7b1d5f8544ce223a9fe455a44`
- `ruff.log`: `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`
- `format.log`: `eee76f865de5a9f2456950f710ae5d5f9b5bd0ea02aa54f614c5eed6642a0bfd`

Task 2.2 remains open: no legitimate formula-cell visibility observer is wired;
the claims branch lacks a persisted stamp and catalog events bypass telemetry.
Those paths require separately bounded RED-first work, not unsupported completion
claims. Full repository gates and independent SDD verification remain the parent
orchestrator's subsequent work. No task checkbox is changed by this partial slice.

## Scoped continuation: task 5.2 API progress behavioral evidence (2026-09-15)

This strict-TDD auto-chain logical slice replaces misleading dictionary/source
tests with eight ASGI cases. Two execute actual Motor retrieval from disposable
UUID databases containing another seller's plan, with/without the authorized
seller's plan. Six prove missing/invalid authentication and foreign-seller,
scope, module, and token-type rejection before any database collection access.
Only JWT signature verification is stubbed; the real module-admin authorization
policy runs. This does not establish production JWT verification or live UI.

The no-plan response now returns `updated_at: null`, matching the populated
response's keys without inventing a successful sync time. The source-inspection
tests and repository-qualified API imports are removed. No manual-retry behavior,
frontend, publication, runtime mutation, commit, or deployment is changed.

| TDD Cycle Evidence | Exact result |
| --- | --- |
| Safety net | Explicit isolated Mongo environment; `uv run pytest modules/sheets/tests/test_pilot_sheets_config_progress.py modules/sheets/tests/test_api_phase6.py -v`: 12 passed, exit 0. Exact `uv run mypy .`: exit 2, duplicate canonical/repository-qualified API module import. |
| RED | New ASGI/Mongo file: `uv run pytest modules/sheets/tests/test_pilot_sheets_config_progress.py -v`: 1 failed (no-plan missing `updated_at`), 7 passed, exit 1, before API change. |
| GREEN / triangulation | Same two-file command after minimal no-plan fix: 17 passed, exit 0. Covers populated, absent, and six rejected authorization paths; other seller's document remains unchanged. |
| Refactor / static correction | Corrected Motor generic annotations and named verifier input as scenario rather than a secret; focused Ruff check/format and mypy pass. Re-executed focused tests: 17 passed, exit 0. |

| Work Unit Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest modules/sheets/tests/test_pilot_sheets_config_progress.py modules/sheets/tests/test_api_phase6.py -v`: 17 passed. Every pytest command explicitly sets the verified loopback 27028 `MONGO_URI` with replicaSet=rs0/directConnection=true and unsets `ZELER_RS0_TEST_URI`. |
| Runtime harness | Same command executes actual ASGI routing/authorization, BSON serialization and Mongo seller-scoped reads; denied requests use a raising database sentinel, never a permissive data fake. No external network request. |
| Static checks | `uv run ruff check` and `uv run ruff format --check` on `modules/sheets/tests/test_pilot_sheets_config_progress.py modules/sheets/src/zeler_sheets/api.py`: pass, 2 formatted files. `uv run mypy` on the same files: success, 2 source files. |
| Exact root gate | `uv run mypy .`: duplicate-module blocker eliminated; final exit 1, 55 errors in 8 files, 573 checked. This is NOT a green root gate. |
| Rollback boundary | Only the rewritten progress test file and the no-plan `updated_at: null` addition in `api.py`, plus this subsection. Pre-slice snapshots `/tmp/zeler-pilot-api-progress/test.before.py` and `api.before.py` preserve previous dirty work; do not restore over later edits. |
| Review boundary | 140 additions + 84 deletions = 224 authored source/test lines; with this evidence, below 300 lines. Task 5.2 stays open for UI integration and non-duplicative retry. Parent owns attempt settlement and subsequent independent verification. |

Remaining root typing inventory (all in this pilot's uncommitted tests):
`test_pilot_history_plan.py` 1; `test_pilot_history_overlap.py` 1;
`test_pilot_history_backfill_progress.py` 10;
`test_pilot_history_interrupted_resume.py` 9;
`test_pilot_old_operation_modification.py` 11;
`test_pilot_event_freshness_audit.py` 1;
`test_pilot_returns_blocker_diagnosis.py` 2; `test_event_stage_telemetry.py` 20.
Of the telemetry errors, 8 belong to original pilot helpers and 12 were introduced
by this continuation's prior handler-test slice. They are change-related defects,
not unrelated baseline repository failures. This API slice's newly typed tests
contribute zero remaining errors; remediation must follow in a separate slice.

Logs under `/tmp/zeler-pilot-api-progress/` are ephemeral local evidence. SHA-256:
- `baseline.log`: `57b8fd10d72468ae1937af082e82f19f30bd3ef35d7adc3a596034ea89ab148e`
- `mypy-baseline.log`: `8ea8beada029d0cc35f8e386782454a92ece179bd058d014a8064ddc132cffd3`
- `red.log`: `8a8835c1cdb71f8ee39ec32e784f89fee4fc8060286f7f114d7266596109b53b`
- `green.log`: `a739067f786cc1e03b029d259288628fb5ad0775037237471be57d59a657fd7e`
- `final-tests.log`: `002438bb6b2f5ddfe868cd4becda0a7e2f1fc182a2073825c95b1f93c7524307`
- `mypy-final.log`: `c8a2c7212d67f7c4ffc091999a27d948a1da46f26e2e0de38ec379b86974e46b`
- `mypy-focused.log`: `f9b031e5c45aa702cd4fef028d465551cb20a2c4698e0913c7b00766b20ac4d8`
- `ruff.log`: `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`
- `format.log`: `3bc53bf3e981a98a34a852e175bf9b77af841edea74fca595d9aedcbaf9a4938`

## Scoped continuation: task 6.1 pilot-test type gate (2026-09-15)

The exact root type gate is now green: `uv run mypy .` reports success across
573 source files, exit 0. All 55 pilot-change errors identified after removing
the duplicate API import are corrected, including this continuation's earlier
telemetry-test additions. No production file changed in this slice.

Eight test files now type Mongo documents/fixtures, fake collection arguments,
clock callbacks, and optional read results explicitly. Queue seller sets use
the actual `frozenset` contract. The unused fixture ignore is removed. The
frozen dataclass test dynamically assigns both `start` and `end`, preserving
its runtime `AttributeError` assertion instead of suppressing a static error.
No blanket ignores, exclusions, weaker assertions, or reduced root scope were
introduced; `Any` remains at heterogeneous Mongo/fake document boundaries.

| TDD / static cycle | Evidence |
| --- | --- |
| Safety net | `uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot*.py modules/sheets/tests/test_event_stage_telemetry.py`: 91 passed in 4.35s, exit 0, before changes. |
| RED | Exact `uv run mypy .`: 55 errors in 8 files, 573 checked, exit 1. Static corrections do not introduce new executable behavior. |
| GREEN | Exact `uv run mypy .`: success, 573 files, exit 0 after corrections. |
| Triangulation / refactor | Same affected pytest command: 92 passed in 4.29s, exit 0; the additional parameter validates the second frozen field. Scoped formatter applied to three files; rerun root mypy and scoped Ruff/format all pass. |

| Work Unit Evidence | Result |
| --- | --- |
| Focused command / runtime harness | The affected pytest command above includes existing real-Mongo telemetry, ASGI progress, cutoff lifecycle and interrupted-queue-state scenarios. Every invocation explicitly sets verified loopback Mongo port 27028, replicaSet=rs0/directConnection=true, and unsets `ZELER_RS0_TEST_URI`; existing fixtures use disposable databases. These harnesses do not establish unimplemented acceptance paths. |
| Static checks | `uv run ruff check` and `uv run ruff format --check` with exactly the eight paths below: both exit 0; 8 files already formatted. Exact root mypy is not substituted by scoped mypy. |
| Rollback boundary | Revert only this slice's annotations, optional-result narrowing, frozenset arguments, unused-ignore removal and frozen-field parameterization in the eight files below, plus this subsection. Pre-slice copies are `/tmp/zeler-pilot-types/<test-name>.before.py`; preserve all prior dirty pilot work and subsequent edits. |
| Authored size | 97 additions + 51 deletions = 148 changed test lines; with evidence below 200 lines. Auto-chain logical slice only; no branch, PR, commit, build, deploy or native settlement by executor. |

Affected files under `modules/sheets/tests/`: `test_event_stage_telemetry.py`,
`test_pilot_history_plan.py`, `test_pilot_history_overlap.py`,
`test_pilot_history_backfill_progress.py`, `test_pilot_history_interrupted_resume.py`,
`test_pilot_old_operation_modification.py`, `test_pilot_event_freshness_audit.py`,
and `test_pilot_returns_blocker_diagnosis.py`.

Task 6.1 remains open until the parent completes all four exact repository gates
and applicable additional checks. Independent SDD verification and complete
runtime acceptance remain pending; this type correction does not change that.

Logs under `/tmp/zeler-pilot-types/` are local ephemeral evidence. SHA-256:
- `baseline.log`: `74ec6c29755ea8d640185e947401b1f1226ed0532a0a2029a8028a7b8c002778`
- `red.log`: `c8a2c7212d67f7c4ffc091999a27d948a1da46f26e2e0de38ec379b86974e46b`
- `green-tests.log`: `7ddc3344fe34c09f9ec19546d4911372cff7272b107a376d74a91593e12687c3`
- `green-mypy.log`: `228d49e3a03b8d7fb899067d30cbece85ef843e5604f0ac5fb86720f04789abb`
- `ruff.log`: `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`
- `format.log`: `8e93d18ae56550d4eef2feac77e6630617c7e169246e56e39c75d58b46167985`

## Scoped continuation: pilot environment unique kill switch (2026-09-15)

Strict-TDD logical auto-chain unit: removed only the trailing duplicate
`ZELERDATA_REFRESH_ENABLED=false` from the worker template. The original single
refresh switch remains disabled; API/worker recovery remains enabled only for
seller `82453304`. No deployed environment, publication or runtime was changed.
The new parameterized test parses assignments before building a dictionary,
rejects duplicate ZelerData keys, and checks the pilot defaults in both templates.

| TDD / Work Unit Evidence | Exact result |
| --- | --- |
| Safety net | `uv run pytest -o addopts='' -q tests/test_env_templates.py`: 5 passed, exit 0. |
| RED | Same command with new cases: 1 failed, 6 passed; worker has 14 assignments but 13 unique keys. Executed before removing duplicate. |
| GREEN / triangulation | Same command: 7 passed, exit 0. API and worker cases assert recovery allowlist; worker additionally pins disabled refresh and its allowlist. |
| Adjacent regression | `uv run pytest -o addopts='' -q tests/test_env_templates.py tests/test_gce_compose_contract.py -k 'env or refresh_kill_switch'`: 54 passed, 1 skipped (existing service with no required keys), 26 deselected, exit 0. |
| Static gates | `uv run ruff check tests/test_env_templates.py`, `uv run ruff format --check tests/test_env_templates.py`, and `uv run mypy tests/test_env_templates.py`: all exit 0. No refactor necessary. |
| Runtime harness boundary | File-level executable contract; no runtime mutation. Actual deployed environment is not established by template evidence. All pytest invocations explicitly use verified loopback Mongo port27028/rs0/directConnection and unset `ZELER_RS0_TEST_URI`; these focused tests do not query Mongo. |
| Rollback / review size | Revert only trailing duplicate removal and the 20 new test/import lines, plus this subsection. Source/test delta 21 authored lines; including evidence below 60. Pre-slice copies `/tmp/zeler-pilot-env/test.before.py` and `template.before` preserve previous dirty work. Parent owns native settlement; no task checkbox marked complete. |

Local ephemeral log SHA-256 under `/tmp/zeler-pilot-env/`:
- `baseline.log`: `9310d484212a1fe2c33b4b8accdf50a2639f09ba039354f8448f8aa8d173e1ff`
- `red.log`: `07ddc92fd38dbf1faf8f5e615ccad70f6fe93fb1adf8e51260f6b1415878ee3e`
- `focused.log`: `f82ef5dfe7698ffb764de054a81d190d7df4e7119218d436d12350d7af175f80`
- `green.log`: `911ebdc657617348dffd5e6fc4ffe014cc0a48b2b6cafeecc408b89a94fd64b8`
- `ruff.log`: `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`
- `format.log`: `fd2299c9f1c6dc869070883e281051bfe93aacf66c1a3b0069f45b4aa410ca50`
- `mypy.log`: `5d4b6d285b77932e3d08212c3b4974d0a803f98ec60408ac6ccf6a063fa6c19e`

## Scoped continuation: task 2.3 old-event formula evidence (2026-09-15)

Added a real Mongo integration case in `test_pilot_old_operation_modification.py`.
The prior two unit cases remain explicitly limited; their guard-substitution
fixture is no longer autouse and applies only to those two cases. The new case
never substitutes persistence, operation leases/guarded writes, or idempotency.

The actual recovery queue/worker acquires one old-order interval for each of two
sellers using external source doubles, publishes real coverage, and completes
its jobs. No manual/global freshness marker is seeded. Orders are 40 days old,
outside the fast window but inside the supported formula query range. A real
`FormulaDispatcher` call to `ZELERDATA_VENTASTOTALES` initially returns paid totals
100/900. The real `SheetsEventHandler` then delivers a newer cancellation, its
duplicate, and a stale paid event with distinct event keys. The pilot paid total
changes to 0, cancelled total remains 100 despite replay, and the second seller
remains 900. Source fetch counts, two canonical rows, two processed-event records,
successful real lease records and fencing increments 3/1 are asserted.

| TDD / Work Unit Evidence | Exact result |
| --- | --- |
| Safety net | `uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_old_operation_modification.py`: 2 passed, exit 0. |
| RED accounting | Test-only evidence addition; no production defect or production edit. Initial execution passed all consumer/dispatcher assertions but failed an incorrect test expectation of four lease documents. Leases are per seller/scope, not per operation; corrected to two and asserted fence increments. This fixture expectation failure is NOT behavioral RED. |
| GREEN / triangulation | Same focused command: 3 passed, exit 0. One integration scenario exercises nonempty before/after filtered results, stale delivery, duplicate suppression, and independent seller state. |
| Adjacent regression | `uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_old_operation_modification.py modules/sheets/tests/test_event_stage_telemetry.py modules/sheets/tests/test_devoluciones_operation_composition.py`: 24 passed in 1.63s, exit 0. |
| Runtime harness | Same commands use the verified existing `zeler-layered-test-mongo`: running, nofile65536, rs0 writable PRIMARY. Explicit loopback27028 MONGO_URI/replicaSet=rs0/directConnection=true; ZELER_RS0_TEST_URI unset. Fixture rechecks PRIMARY/rs0 and drops only its UUID database. Gateway and absent Sheets export are external doubles; dispatcher evidence is NOT visible-cell proof. |
| Static checks | Scoped `uv run ruff check`, `uv run ruff format --check`, and `uv run mypy` against the test file: all pass. The narrow collection protocol cast bridges Motor's positional parameter-name mismatch without replacing its real Mongo methods. |
| Rollback / workload | Only this test file's new integration case/imports, accurate module description and narrowed fixture application, plus this evidence and task2.3 status. Source/test delta177 additions+12 deletions=189 authored lines; with SDD updates below240. Pre-slice `/tmp/zeler-pilot-old-event/test.before.py` preserves previous dirty work. No production change, commit/build/deploy, or executor settlement. |

Task 2.3's local consumer/guard/dispatcher requirement is marked complete for
parent review. No broader task, actual Sheet visibility, or final SDD acceptance
is claimed. Production retention, real source behavior and the 90-minute window
remain separate evidence requirements.

Local ephemeral log SHA-256 under `/tmp/zeler-pilot-old-event/`:
- `baseline.log`: `ac84d31254b1f0be729bbe2e90dcf691256875726c8d4a6bf0802d69e59cc6ed`
- `first.log`: `a47a2332fc4c58f496a6241494116e6112c497af4092ef9d6e58481ca71b8631`
- `green.log`: `c69b8aca4c7fecb6b04161c76c5abcd40b2a41ecf4e5419302cadf88471a09c9`
- `regression.log`: `5fab84eaf87e0d465382bf79ccd8727ccc21cee40ec1a8f02b3af3c028706866`
- `ruff.log`: `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`
- `format.log`: `fd2299c9f1c6dc869070883e281051bfe93aacf66c1a3b0069f45b4aa410ca50`
- `mypy.log`: `5d4b6d285b77932e3d08212c3b4974d0a803f98ec60408ac6ccf6a063fa6c19e`

## Previous session record

Base commit: `0bc24575194d43fee1e2f52d4ee0c54e7100864b` (main, unmodified).
All work in this change is in the working tree (7 modified + 27 untracked
files); no commit, build or deployment was executed.

## Completed work units

### Phase 1: Contract and baseline
- [x] 1.2 FormulaRegistry.default() exposes exactly 52 contracts; test_apps_script_addon.py
  pins the same 52 names in the add-on wrappers (canonical + lowercase aliases).
- 1.1 matrix Expected column filled: 52 rows with contract-derived Expected behavior
  (sourced from docs/sheets/zelerdata-formulas.md); Observed/Evidence/Defects
  remain PENDING until formulas run against deployed pilot images.
- 1.3 Production/runtime evidence gathered (2026-09-15): sheets-api running image
  sha256:9b34a2869c65c545d4a2b6cd744fb265432a78cdcc6bdb0b5ef23996347a086d
  (source 8fdf20c63c38d456a80fff8613b5bdb5c213d6d4); sheets-worker running image
  sha256:081ef4b92474452b228309c9b8a28cc8f0633fb9952c395144728ba8b8f361a9
  (source 8fdf20c63c38d456a80fff8613b5bdb5c213d6d4). Both source commits are
  ancestors of local HEAD 0bc24575194d43fee1e2f52d4ee0c54e7100864b, so the new
  pilot modules are not present in either running image. Both containers healthy
  18+ hours, gateway healthy. Root filesystem 31GiB free (>= 5GiB floor),
  Mongo volume 46GiB free, memory available 1515 MiB. Preflight dry-run passed.
  Sheets API /health (external): 200, dependencies ready. Sheets worker internal
  /health: 200, components ready (rabbitmq/sync_jobs_poller/formula_recovery/
  zelerdata_refresh all ok). Local verification complete (4796 tests pass, all
  gates green).

### Phase 2: Event freshness
- [x] 2.1–2.2 test_pilot_event_freshness_audit.py: monotonic freshness guard accepts
  newer/rejects stale/absent-freshness-field resources; AMQP dedup key function verified.
  Task 2.2 implemented and wired: EventStageTelemetry (event_stage_telemetry.py)
  persists four stage timestamps (received/fetched/persisted/visible) in
  sheets_event_stages; earliest-received semantics prevent re-delivery from
  inflating latency. SheetsEventHandler now records all four stages in the real
  event path (after dedup, after gateway fetch, after persist, after append),
  and the runner build site passes the telemetry instance.
  build_zelerdata_refresh_supervisor now wires build_pilot_history_backfill into
  the supervisor, making history backfill part of the runtime refresh loop.
- [x] 2.3 test_pilot_old_operation_modification.py: an order created 120 days ago with a
  newer last_updated overwrites the projection; a stale event is rejected by the guard,
  preserving the newer state.
- [x] 2.4 Bounded pacing verified via existing RecoveryRequestPacer tests (180/min shared
  across inventory/ids/ranges lanes) and the history planner reuses the same queue.

### Phase 3: History and integrity
- [x] 3.1 test_pilot_history_plan.py (16 tests): 12-month planner produces resumable
  monthly chunks ≤31 days, priority ordering (RECENT first, OLDEST_EDGE next, MIDDLE oldest),
  UTC cutoff validation, deterministic chunk IDs, resume with completed/partial/unknown IDs.
- [x] 3.1a test_pilot_history_recovery_bridge.py (6 tests): maps chunk→RecoveryRequest for
  orders/questions/shipments/items; rejects unknown resources and empty seller.
- [x] 3.1b test_pilot_history_queue_integration.py (6 tests): enqueues incomplete chunks in
  priority order; skips completed; unknown resource raises after prior admissions (documented
  partial work).
- [x] 3.1c test_pilot_history_refresh_wiring.py (3 tests): supervisor calls history_backfill
  per seller; failure isolation (cycle continues with health=ok); admitted work reported.
- [x] 3.1d pilot_history_backfill.py: persists deterministic 12-month cutoff per seller in
  sheets_history_backfill_plans; enqueues remaining chunks through existing FormulaRecoveryQueue.
- [x] 3.2 test_pilot_history_backfill_progress.py (3 tests): per-resource progress dict
  (completed/failed/pending/admitted_this_cycle) persisted in the plan document after enqueue.
- [x] 3.3 test_pilot_history_interrupted_resume.py (3 real-Mongo tests): completed chunk never
  re-enqueued (planner filters before enqueue; queue re-enqueue resets to pending — documented
  production contract); failed chunk re-admitted exactly once (reset to pending, attempts=0;
  second call coalesces without duplicate doc); running with live lease coalesces by key without
  creating a second document or resetting state.
- [x] 3.4 test_pilot_history_overlap.py (7 tests): 24h bounded overlap window for completed
  chunks (clamped to chunk start); distinct request key from base chunk (no collision); only
  orders/questions accepted (range-capable resources); rejects unknown resource and empty seller.
- [x] 3.5 test_pilot_returns_blocker_diagnosis.py (6 tests): guard blocks low-cost basis,
  productive=false, both, passes on all-productive-v2, fails closed on storage error. Wrapper
  exit codes 64 (invalid run authority) and 66 (runtime path missing) documented — the
  wrapper_refused_or_failed is consistent with either; no data was written. Seven pending dates
  require operator-authorized quota run; this is an authorization decision, not a code defect.

### Phase 4: Formula reliability
- [x] 4.1 test_pilot_formula_matrix_coverage.py (2 tests): registry exposes exactly 52; each
  formula name appears in at least one handler test file (coverage assertion).
- [x] 4.2 Existing handler tests (143+ across six files) cover absence/filters/ranges.
- [x] 4.3 test_formula_recovery.py (many tests) retains prior regressions; all 52 formulas
  verified simultaneously via the coverage test + existing simultaneous load tests.

### Phase 5: Sheets experience
- [x] 5.1 test_pilot_sheets_refresh_cells.py (4 tests): regex matches =ZELERDATA_* (canonical +
  lowercase), rejects non-ZelerData formulas (=SUM, =IMAGE) and leading-space variants; contract
  pinned for the refresh implementation (read formula, clear, re-set same formula to force
  recalculation without editing text).
- [x] 5.2 test_pilot_sheets_config_progress.py (3 tests): plan progress document queryable by
  seller_id; sync job ID pattern is non-duplicative (timestamp-based _id, DuplicateKeyError);
  existing /sheets/exports and /sheets/sync-jobs endpoints verified. Added
  GET /backfill/progress API endpoint exposing cutoff and per-resource progress.
  Added ZELERDATA_FORMULA_RECOVERY_ENABLED/SELLERS to both sheets env templates
  (refresh remains off by default; operator must enable it for backfill).
- [x] 5.3 test_apps_script_addon.py (existing tests): 52 canonical + 52 lowercase wrapper names;
  formula syntax parseable; refresh mechanism pinned by 5.1's contract.
  Added refreshZelerDataResults() to the add-on (Config.gs menu + Client.gs
  implementation). It discovers =ZELERDATA_* cells, re-sets the same formula
  text in place to force recalculation, and reports the count via toast.
  This is a user-invoked menu action, not a background timer.

### Phase 6: Final verification
- [x] 6.1 All four repository gates complete:
  - pytest (full suite, MONGO_URI=port 27028): 4796 tests, 0 failures, 0 errors
  - ruff check: 0 errors (all files)
  - ruff format --check: 572 files already formatted
  - mypy: all 171 source files clean (all packages, --explicit-package-bases)
  - export_schemas --check: exit 0
  - check_direct_meli: exit 0
- [x] 6.2 Controlled recovery/duplicate/interruption: 3 real-Mongo tests (3.3) prove no
  duplicates, no lost work, no silent restart; 3.1b proves partial work documented on error.
- 6.3 pending: deployment/add-on proposal requires operator authorization.
  Affected services: sheets-api (new /backfill/progress endpoint) and
  sheets-worker (refresh supervisor wiring, history backfill, stage telemetry).
  Env templates updated with recovery flags; refresh kill-switch stays off.
  Dockerfiles unchanged (modules/sheets/Dockerfile.{api,worker} already include
  the new source files via the workspace copy).
- 6.4 pending: 90-minute observation requires deployed images.
- 6.5 pending: independent SDD verification.

## Verification evidence
- Full suite: 4796 tests pass, 0 failures, 0 errors on verified test Mongo (port 27028).
- Real-Mongo: 3 tests pass on mongodb://127.0.0.1:27028 (dedicated replica set).
- Ruff check: 0 errors across 572 files.
- Ruff format: 572 files already formatted.
- Mypy: all 171 source files clean (all packages, --explicit-package-bases).
- Schema export: infra/mongo/schemas unchanged (exit 0).
- check_direct_meli: exit 0.
- Env template contract test verifies refresh kill-switch remains off by default.
- Handler tests for formula correctness: 341 tests pass (core, orders/questions,
  item/shipping/catalog, remaining, returns/withdrawals, quality/calculator).
- Pilot + add-on + stage telemetry: 101 tests pass.

## Current scoped correction: fixed cutoff lifecycle (2026-09-15)

Task 3.2 remains open. This independently reversible `auto-chain` logical unit
only fixes persisted cutoff initialization and reload, not complete history
execution. No branch, commit, build, deployment, or publication is authorized.

The callback now normalizes BSON-aware UTC timestamps before passing them to
the strict planner. Initialization uses atomic `$setOnInsert` and consumes the
persisted winning document, preventing competing initializers from replacing
the cutoff or enqueueing a different interval plan. The previous in-memory fake
was adapted to the new collection method; it is not the integration evidence.

### TDD Cycle Evidence

| Scope | RED | GREEN | REFACTOR |
| --- | --- | --- | --- |
| Task 3.2 cutoff sub-unit | Safety net: 6 existing tests pass. Three new actual-Motor cases fail: fresh/repeated BSON cutoff, preexisting BSON cutoff, concurrent competing initialization. `/tmp/pilot-cutoff-red.log`. | All 9 focused tests pass; `/tmp/pilot-cutoff-green.log`. New test uses production-style BSON decoding and real transactional queue admission. | No further behavior refactor needed. All 49 pilot-history tests pass in 2.79s; `/tmp/pilot-cutoff-regression.log`. |

### Work Unit Evidence

| Evidence | Required value |
| --- | --- |
| Focused command/result | `env -u ZELER_RS0_TEST_URI MONGO_URI='mongodb://127.0.0.1:27028/?directConnection=true' uv run pytest -q modules/sheets/tests/test_pilot_history_cutoff_lifecycle.py modules/sheets/tests/test_pilot_history_backfill_progress.py modules/sheets/tests/test_pilot_history_interrupted_resume.py`: 9 passed. |
| Runtime harness command/scenario | Same command exercises actual Motor callback, BSON round trips, concurrent initializers and transactional queue in disposable databases. Inspected `zeler-layered-test-mongo`: loopback 27028, writable PRIMARY, rs0, nofile 65536; fixture independently checks PRIMARY/rs0 and drops its own database. |
| Adjacent regression | Same explicit isolated environment with `uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_history*.py`: 49 passed in 2.79s. |
| Static checks | Ruff check/format pass on the three scoped Python files. `uv run mypy modules/sheets/src/zeler_sheets/pilot_history_backfill.py modules/sheets/tests/test_pilot_history_cutoff_lifecycle.py`: success, two files; `/tmp/pilot-cutoff-mypy.log`. Full repository gates remain orchestrator work. |
| Rollback boundary | Revert only the cutoff initialization/reload block and its `ReturnDocument` import, `test_pilot_history_cutoff_lifecycle.py`, and the fake's added `find_one_and_update` method. Preserve unrelated prior work. |

Known capacity and routing defects remain visible: tests deliberately expect
the real queue's capacity exception after one admission, on both callback runs.
They prove stable cutoff/job identity, not successful complete backfill. Monthly
shipment/item range requests remain unsupported by the queue; durable progress,
honest admissions, worker checkpoints and modification reconciliation require
subsequent units. Current evidence does not prove runtime deployment health.

Key learning: Motor `tz_aware=True` alone returns BSON `FixedOffset(0)`, which
does not compare equal to `datetime.UTC`; normalize instants at this boundary.
Atomic initialization must use the stored winner, not a losing local candidate.

## Current scoped correction: terminal-safe queue admission (2026-09-15)

Task 3.2 remains open. This independent `auto-chain` logical unit introduces
`RecoveryCapacityError(ValueError)` at the two actual capacity rejection sites
and optional `enqueue(..., reopen_terminal=False)`. Default callers retain
terminal reopening. The opt-out preserves existing terminal jobs inside the
real admission transaction, including a competitor finishing between the first
lookup and transaction; seller, source, request-shape and capacity guards remain.
The callback does not use the option yet. The returned key still does not prove
that this invocation inserted a job; truthful callback admission accounting is
the next separate unit. No source acquisition or coverage behavior changed.

### TDD Cycle Evidence

| Scope | RED | GREEN | REFACTOR |
| --- | --- | --- | --- |
| Task 3.2 queue-guard prerequisite | Safety net: 21 passed, 408 deselected. Seven new actual-Mongo tests failed before source edits (`/tmp/pilot-queue-guard-red.log`): completed/failed preservation and races, both capacity guards, seller isolation. | 7 passed in 1.38s (`/tmp/pilot-queue-guard-green.log`), including backward-compatible default reopening/cooldown. | No further refactor required. Adjacent real queue/history regression: 486 passed in 110.13s (`/tmp/pilot-queue-guard-regression.log`). |

### Work Unit Evidence

| Evidence | Required value |
| --- | --- |
| Focused command/result | `env -u ZELER_RS0_TEST_URI MONGO_URI='mongodb://127.0.0.1:27028/?directConnection=true' uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_queue_terminal_admission.py`: 7 passed. |
| Runtime harness command/scenario | Same command uses actual Motor, transactional queue and isolated disposable databases. A controlled prelookup pause allows another real queue to enqueue/claim/finish before the protected transaction. Mongo verified PRIMARY/rs0 at loopback 27028, nofile 65536; fixture independently validates PRIMARY/rs0. |
| Adjacent regression | Same explicit isolated environment with `uv run pytest -o addopts='' -q modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_pilot_queue_terminal_admission.py modules/sheets/tests/test_pilot_history*.py`: 486 passed. |
| Static checks | Scoped Ruff check and format pass; scoped mypy reports no issues in the two changed Python files; `git diff --check` passes. Full gates remain orchestrator-owned. |
| Rollback boundary | Revert only the 11 added/3 removed lines in `formulas/recovery.py` and remove `test_pilot_queue_terminal_admission.py`; callback remains unchanged and no migrations are required. |

Key learning: a pre-enqueue terminal-state check alone cannot prevent reopening
after a concurrent completion. Preserve the state inside admission's existing
transaction. A `ValueError` subtype separates actual capacity from rejected
seller/source scope without breaking existing `ValueError` handlers.

## Current scoped correction: callback admission ledger (2026-09-15)

Task 3.2 remains open. The callback now represents every planned resource/chunk,
orders admissions globally by recent/oldest-edge/middle, skips existing jobs and
uses terminal-preserving admission for absent jobs. It catches only typed
capacity rejection, stops admissions at capacity and persists the whole ledger.
Shipments/items remain explicitly blocked as `acquisition_path_unresolved`, not
omitted, completed, or declared an API limitation. Their acquisition is future
work. Independent queue defaults and source/coverage behavior are unchanged.

Each chunk records interval, identity, observed state/time and, where supported,
request key and attempts. Per-resource queued/running/completed/failed/pending/
blocked counts are disjoint. `accepted_or_coalesced_this_cycle` and the callback
boolean describe successful enqueue calls, not exact new insertions. A competing
queue's completed job is observed as completed after coalescence. This is a
per-chunk observed snapshot, not an atomic global snapshot, a reconciled coverage
certificate, or a durable acquisition cursor. Admission guards still reject
disabled sellers/sources, but the cutoff plan can be initialized before that
rejection; no broader no-write seller-isolation claim is made.

### TDD Cycle Evidence

| Scope | RED | GREEN | REFACTOR |
| --- | --- | --- | --- |
| Task 3.2 admission-ledger sub-unit | Safety net: 6 passed. Updated/new actual-Mongo callback tests: 7 failed, 2 passed before source edits; `/tmp/pilot-ledger-red.log`. Failures expose escaping capacity and absent ledger; scope-rejection controls already pass. | 12 focused tests passed in 3.48s; `/tmp/pilot-ledger-green.log`. Tests prove capacities 2/4 give both resources recent/oldest priority, repeat/terminal/running preservation and explicit blocked intervals. | Formatting/type-check adjustment plus a real competing queue completion triangulation; all 64 adjacent history/queue tests pass in 5.47s; `/tmp/pilot-ledger-regression.log`. |

### Work Unit Evidence

| Evidence | Required value |
| --- | --- |
| Focused command/result | `env -u ZELER_RS0_TEST_URI MONGO_URI='mongodb://127.0.0.1:27028/?directConnection=true' uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_history_cutoff_lifecycle.py modules/sheets/tests/test_pilot_history_backfill_progress.py`: initial GREEN 12 passed. |
| Runtime harness command/scenario | Actual Motor and transactional queue, bounded slots, BSON cutoff reuse, concurrent initializers and competing enqueue/claim/finish. Verified loopback Mongo 27028 PRIMARY/rs0; disposable fixture databases only. No upstream acquisition or production evidence claimed. |
| Final adjacent regression | Same isolated environment with `uv run pytest -o addopts='' -q modules/sheets/tests/test_pilot_history*.py modules/sheets/tests/test_pilot_queue_terminal_admission.py`: 64 passed in 5.47s. |
| Static checks | Scoped Ruff, format and mypy pass on all three changed Python files; full repository gates remain orchestrator-owned. |
| Rollback boundary | Revert this callback orchestration/ledger replacement and its accompanying cutoff/fake test changes. Preserve preceding atomic-cutoff and queue-terminal-guard units; no migration. |

Known remaining work: authoritative shipment/item acquisition, worker checkpoints,
modification reconciliation, real coverage and fairness against regular refresh
or live-query producers. Global history chunk ordering alone proves none of
those. The older fake-only tests are adapted, not promoted to runtime evidence.

## Current scoped correction: acquisition head model (2026-09-15)

Only task 3.2a is complete. `SheetsHistoryAcquisition` is exported from the core
models package; it validates the canonical metadata contract without inheriting
shared seller/identity coercions. It rejects extra fields, boolean/noninteger
counters, invalid scope/cursor combinations and invalid temporal/count/phase
relationships. Aware timestamps, including BSON FixedOffset, normalize to UTC.
Completed metadata requires observation/total/cursor/publication bookkeeping;
zero-total observations and question partitions with fewer fetched than discovered
identities remain valid. Constructing this model does not prove source coverage,
membership, ownership, exclusions or safe worker completion.

### TDD Cycle Evidence

| Task | RED | GREEN | REFACTOR |
| --- | --- | --- | --- |
| 3.2a | Existing-model safety net: 31 passed. New model tests fail collection because the requested core export does not exist (`/tmp/history-head-red.log`); no source was written first. | Initial 84 model cases pass (`/tmp/history-head-green.log`). | Formatted test parameter lists and triangulated valid nonterminal cursors/phases; final 88 model cases pass (`/tmp/history-head-final-focused.log`), 165 adjacent model/schema cases pass (`/tmp/history-head-regression.log`). |

### Work Unit Evidence

| Evidence | Required value |
| --- | --- |
| Focused command/result | `uv run pytest -o addopts='' -q core/tests/test_sheets_history_models.py`: 88 passed. |
| Runtime harness | N/A: inert model/export only; no worker, producer, Mongo validator/index or database mutation added. BSON encode/decode is an in-process serialization test, not a Mongo integration claim. |
| Adjacent command/result | `uv run pytest -o addopts='' -q core/tests/test_sheets_history_models.py core/tests/test_models_phase3.py core/tests/test_entities_items.py core/tests/test_meli_account_timezone_schema.py core/tests/test_meli_timezones.py core/tests/test_receiver_address_snapshot.py core/tests/test_shipment_real_shipping_cost_projection.py core/tests/test_schema_export_phase3.py`: 165 passed in 0.24s. |
| Static/schema checks | Scoped Ruff check/format/mypy pass for both new files and the package export; `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check` passes unchanged (`/tmp/history-head-schema-check.log`). |
| Rollback boundary | Remove the new model/test and its package import/export only; no deployed data or schema depends on this unactivated model. Preserve previous units. |

Key learning: seller-wide discovery counts are not scoped hydration counts.
Do not force question fetched counts to equal discovery/source totals; the
future fenced store must independently establish membership and exclusions.

## Intermediate repository gates (2026-09-15)

After the callback ledger correction, the parent ran the exact root commands:

| Command | Result |
| --- | --- |
| `uv run pytest` | 4815 passed, 9 skipped, 356 warnings, exit 0 in 307.56s. |
| `uv run ruff check .` | All checks passed, exit 0. |
| `uv run ruff format --check .` | 574 files already formatted, exit 0. |
| `uv run mypy .` | No issues in 574 source files, exit 0. |
| `uv run python -m infra.lint.check_direct_meli .` | Exit 0. |
| `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check` | Exit 0. |

The full suite used an explicitly named, unique disposable database on verified
loopback Mongo 27028/rs0, with `ZELER_RS0_TEST_URI` unset. Its default database
was dropped afterward. Eight protected stock-time rs0 cases deliberately skip
when `MONGO_URI` is set; rerunning their three files with `MONGO_URI` unset and
`ZELER_RS0_TEST_URI` pointing to the verified loopback replica set produced
8 passed in 3.39s, exit 0. The other skip is the Caddy env-key test, which has
no required keys. Mongo remained writable PRIMARY/rs0 after both runs.

An initial parent invocation omitted a database name from the local URI:
4776 passed, 9 skipped, 38 errors and one failure. All errors/failure were
`get_default_database()` configuration failures, not code regressions. The
parent corrected the harness URI and reran the entire suite, without changing
code or suppressing tests.

Evidence: `/tmp/zeler-pilot-full-pytest-corrected-20260915.log`, SHA-256
`a7cebf7e6e1376b655771def371443d25a38101b3642652e095cccec653c130d`;
`/tmp/zeler-pilot-protected-rs0-20260915.log`, SHA-256
`0736b0d0d05bbe15a95e77677baef49a38cf862fa0a7f81131e74e3256879f16`.
All tracked verification processes exited. These are intermediate gates, not
final SDD acceptance: unfinished acquisition, event, formula and Sheets work
still requires implementation and affected gate reruns. No commit, build,
deployment, add-on publication or production data mutation occurred.

### Scoped apply: 3.2b acquisition-head BSON structure and scope index

Actual Mongo strict-TDD used only unique disposable `zeler_history_schema_*`
databases on verified loopback port 27028, rs0 PRIMARY, nofile 65536. The real
`apply_validators` entrypoint created and reapplied the exported validator/index.
Before source edits, 26 RED failures proved missing structural rejection and
scope uniqueness (plus absent export); GREEN passes all 31 focused cases.
All persisted model-dump fields are required: Mongo supplies no model defaults.
Tests cover error 121, terminal-phase structure, compound uniqueness with seller
and plan independence, and explicitly demonstrate that relational date ordering
remains model/store responsibility. No coverage, membership or lease proof is
claimed. This inert schema does not activate acquisition or apply production DDL.

Regression: 135 passing across the new Mongo tests, core head model, phase-three
schema export and validator tests; scoped Ruff/format, mypy and full schema-export
drift check pass. An earlier mixed-suite invocation omitted configured importlib
mode; its collection error was corrected before baseline, not counted as RED.
Evidence: `/tmp/history-schema-red.log` SHA-256
`e8065ceb156e1b9df0a9498bfdf5bd25483376f434565f34662b690f091516e1`;
`/tmp/history-schema-regression.log` SHA-256
`f2a2851fd07d932c49660c7f57aef37289927105e202692b6b4a7a987b70a9ff`.
The executor initially closed 3.2b on scoped evidence; parent verification below
reopens it. Broad historical acquisition and acceptance remain pending.
Work-unit boundary: exporter contract, generated validator, unique index and
behavioral tests belong together. Generated JSON is 309 additional lines, reported
separately from authored changes; total exceeds 400 without compression or an
inferred oversized-PR authorization. Rollback removes this inert local schema
unit; any future deployed validator/index rollback requires separately scoped DDL.

## Parent verification: schema regression and native budget decision

The native attempt recorded passing scoped evidence but refused closure because
567 changed lines exceed its 400-line budget: 258 authored plus 309 deterministic
generated lines. `decision_required=true`, `next_action=reset`; current revision
is `sha256:50a7ea1de07dcc4a6d47ad2e1a127af70741ce1855709b32081c77fb24f22e9f`.
No reset or budget bypass was performed. The user was asked to authorize only
this attempt's reset and revalidation with a 650-line limit, not a commit, build,
deployment, oversized PR or global policy change.

The subsequent exact `uv run pytest`, using a unique named disposable database
on verified loopback Mongo 27028/rs0, returned **1 failed, 4936 passed, 9 skipped**
in 276.04s (exit 1). The new schema is missing from the static expected/active
inventory in `tests/test_mongo_schemas_placeholder.py`. This is a change-caused
regression, not an unrelated failure. Update both explicit sets and rerun the
focused test and full suite after the required native decision. Task 3.2b stays
open until that correction and native closure are verified.

Root Ruff/format/mypy pass (577 files); schema export drift passed. Eight protected
rs0 tests passed separately in 3.38s with `MONGO_URI` unset. Full-suite log:
`/tmp/zeler-pilot-schema-full-pytest-20260915.log`, SHA-256
`9107e4dfe5b638da5fe7e076789f79203fd5d61e3cbe76b5e606628291528d45`.
The full-suite default database and fixture databases were cleaned; all tracked
test processes exited. No production mutation occurred. Green scoped tests do
not override the full-suite failure or the native decision gate.

### 3.2b authorized schema-inventory remediation

The user explicitly authorized the 650-line size exception for this unit only;
it does not authorize oversized future work, VCS, builds or deployments.
Observed RED in `tests/test_mongo_schemas_placeholder.py` identified the newly
exported head schema missing from the exact inventory. Added it to both expected
and active-schema sets, preserving full set equality and placeholder assertions.
GREEN: 136 focused/adjacent tests pass, including 31 actual Mongo schema tests
through `apply_validators` on unique disposable databases after confirming local
27028 rs0 PRIMARY. Scoped Ruff/format/mypy and schema-export drift pass.
RED log `/tmp/history-schema-inventory-red.log` SHA-256
`68533c9515f030156a258bf03b88b00bd23d4b3954dde0dbd1c2e44c8991d003`;
GREEN `/tmp/history-schema-revalidation-green.log` SHA-256
`cd9c149d197cd547376374a651d4576d5c7d1c01951c2226a78893e117a11134`.
This remediates prior evidence revision
`f2a2851fd07d932c49660c7f57aef37289927105e202692b6b4a7a987b70a9ff`.
Task 3.2b stays open pending parent full gates and native closure. The correction
adds two inventory entries only; rollback removes those entries with the schema
unit, not by weakening the inventory assertion. No receipt implementation began.

Parent closure: the exact root suite now passes 4937 tests, with 9 expected skips,
in 314.64s; the eight protected rs0 cases pass separately in 3.43s. Root Ruff,
format, mypy (577 files), direct-Meli and schema-export checks all exit 0.
Full-suite log `/tmp/zeler-pilot-authorized-full-pytest-20260915.log`, SHA-256
`3e70b4af2955a67497dcba1ff028a1d06bc39b91390d318437044034ea0141b6`;
protected log `/tmp/zeler-pilot-authorized-protected-rs0-20260915.log`, SHA-256
`a15f1cc29c236dea685401f5b2ef658d302aec5f14a2e92197888087ec8983a0`.
Disposable databases were cleaned and Mongo remained PRIMARY/rs0. Native settle
explicitly remediated the prior evidence and now reports `complete=true`,
`decision_required=false`, limit 650. Task 3.2b closes; the complete pilot does
not. No commit, build, deployment or production DDL occurred.

### Scoped apply 3.2c: inert acquisition receipt model

`SheetsHistoryReceipt` defines strict identity/position, original UTC observation,
optional opaque source version, separate source/payload SHA-256 shapes, and
membership/detail/exclusion invariants. Detail retains unavailable fields without
turning them into exclusions. Membership needs no detail or invented version;
exclusion preserves available provenance but its reason alone proves nothing.
The model contract/tests are canonical for the next receipt-schema unit.

| Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- |
| 88 existing model tests pass | Missing receipt export raises ImportError | 131 model tests pass | 136 model tests; versionless detail/versioned membership and required position | No extra abstraction needed |

48 new pure model cases use no mocks; adjacent model/schema/inventory regression
passes 173 tests. Scoped Ruff/format/mypy, schema-export drift and diff checks pass.
Evidence `/tmp/history-receipt-red.log` SHA-256
`6ae921e77b8032425a4689cb65fa2771dfc1e641cdffccd5cc6e251f21123f03`;
`/tmp/history-receipt-regression.log` SHA-256
`e9e1f68b9f269e046af176d8ed22e4cb0a6b513b897cd9b4ed3306aaab4dc4c4`.
The future fenced store must verify hash/content equality, same-kind replay,
resource identity/provenance, exclusion authority and whole-document BSON safety
including the local 1 MiB budget; nested payload key safety is not certified here.
No BSON dependency, validator, store, worker activation or runtime mutation added.
Only 3.2c closes locally; parent owns native closure and final repository gates.
Rollback removes this receipt model/export/tests while retaining the head model.

Parent verification: full `uv run pytest` passes 4985 tests, with 9 skips, in
246.95s using a unique named disposable loopback database, removed after exit.
Eight protected rs0 tests pass separately in 2.26s with ambient `MONGO_URI` unset.
Root Ruff, format, mypy (577 files), direct-Meli and schema-export checks pass.
Full log: `/tmp/zeler-pilot-receipt-full-pytest-20260915.log`; protected log:
`/tmp/zeler-pilot-receipt-protected-rs0-20260915.log`. These are intermediate
gates, not complete pilot acceptance. The next coherent receipt validator/index
unit is estimated at 450–600 lines including generated JSON; a separate scoped
650-line exception was requested before implementation, not inferred from the
previous head-schema authorization. No commit, build, deploy or production DDL.

### Scoped apply 3.2d: receipt BSON validator and indexes

User authorization raises only this unit's review limit to 650 lines. The receipt
export requires all persisted fields, forbids unknown top-level fields, validates
kind-specific payload/hash/exclusion structure and unique unavailable fields.
Both canonical schema inventory sets retain their exact membership assertions.
Generated JSON was exported to temporary storage and installed using apply_patch.

| Safety net | RED | GREEN | Triangulation | Refactor |
| --- | --- | --- | --- | --- |
| 32 existing schema/inventory tests | 40 real Mongo/export failures | 78 schema/inventory passes | 83 after five detail boundary cases | Shared fixture applies both collections |

The actual `apply_validators` path creates/reapplies schemas and indexes on unique
disposable loopback databases: port 27028, rs0 PRIMARY, nofile 65536; cleanup leaves
zero schema-test databases. Tests assert error 121, all 17 required receipt fields,
exact unique identity index and ordered generation/pass/kind/page/resource lookup,
including same-page tie-breaking with a hinted query. Neither index has TTL.
51 new cases; the model/export/validator/inventory regression passes 235 tests.
Scoped Ruff/format/mypy, schema-export drift and diff checks pass.
RED `/tmp/receipt-schema-red.log` SHA-256
`58393181c45dd07aba6b2442f46484de6f6be3544602cf7dd9389505acafa2d0`;
regression `/tmp/receipt-schema-regression.log` SHA-256
`ffe21220f07f9bb87fc1e33c849923a46494fa04c8a57ae6916d0c2d8aae18b2`.
Indexes do not bind seller/read-model to the head, verify hashes/provenance or
certify coverage. Nested payload safety and whole-document byte budgets remain
fenced-store responsibilities. No runtime activation or production DDL occurred.
Only 3.2d closes locally, subject to parent full gates/native settlement. Rollback
removes this inert exporter/schema/index/test unit; future deployed DDL rollback
requires separate authorization and preservation of already acquired receipts.

Parent gates: exact root `uv run pytest` passes 5036 tests, with 9 skips, in
315.20s; eight protected rs0 cases pass separately in 1.59s. Root Ruff, format,
mypy (577 files), direct-Meli, schema-export drift and diff checks all pass.
Full log `/tmp/zeler-pilot-receipt-schema-full-20260915.log` SHA-256
`651276407a6e224df13ee63be87ba33dd581cdd2fe41a3f54b5ae8cac987552a`;
protected log `/tmp/zeler-pilot-receipt-schema-protected-20260915.log` SHA-256
`d52e642495e15a5459bde0218522eeac8884b9dbbe004c11628da8a6f92e3781`.
Disposable databases were removed and Mongo remained PRIMARY/rs0; all test
processes exited. These intermediate gates do not complete task 6.1 or pilot
acceptance. No commit, build, deployment or production DDL was performed.

### Scoped apply 3.2e: bounded fenced staging store

Under the authorized size exception, `HistoryAcquisitionStore` atomically stores
receipts and head checkpoints with actual queue ownership writes before and after
the transaction work. Head generation/revision CAS, current seller/resource
policy, exact request bounds, expiry and attempt-token checks prevent stale writes.
Identical replays preserve original observations/counts; contradictory evidence
raises a typed conflict without altering receipts. Payload identity/hash, nested
keys, finite numbers and whole BSON document/batch budgets are checked locally.

| Safety net | RED | GREEN/triangulation | Refactor |
| --- | --- | --- | --- |
| New files; existing queue/schema/model code unchanged | Missing module; then real request-bound, policy/collision and timestamp failures | 29 real Mongo cases | Reused queue fence, BSON fingerprint and transaction retries |

Actual installed validators/indexes on disposable loopback 27028/rs0 databases
prove rollback after receipt insertion, competing checkpoints, lease expiry during
the transaction, replay, truthful counts and unsafe/oversize rejection. Adjacent
store/schema/queue/model regression: 254 passes. Scoped Ruff/format/mypy and diff
checks pass; cleanup leaves zero store databases and Mongo remains PRIMARY.
RED `/tmp/history-store-red.log` SHA-256
`0d1b441200a9285bb309b03542fd561a97873a8092ecb192e9b54620caf712a8`;
regression `/tmp/history-store-regression.log` SHA-256
`61800049e3767cbfe10d57054fbcec188ea2b89ea87dbb0c3cd033e6af66efb2`.
This store stages only: publication/completion are rejected; raw source hashes and
exclusion reasons do not establish provenance or coverage. Pass/generation rollover
and shared-question request binding remain continuation/adapter work. No worker
activation, production mutation or VCS action occurred. Only 3.2e closes locally,
pending parent gates/native settlement. Rollback removes the two new files while
preserving existing schemas and any acquired receipts.

### Scoped apply 3.2f: atomic queue continuation

`HistoryContinuation` commits receipt/head progress and queue release in one real
Motor transaction through the store's optional active-session path. Only durable
acquisition progress resets consecutive attempts; quota refunds the current claim
without changing the checkpoint. Transient failures use existing finite queue
retry accounting. Cursor expiry/drift increments a separate three-restart budget,
starts a fresh enumeration pass, retains receipts and fails on further restart.
Original-plan initialization resumes the persisted pass without resetting budgets.

| Safety net | RED | GREEN/triangulation | Refactor |
| --- | --- | --- | --- |
| 36 existing store/queue tests | Missing module; then resume, metadata-only progress, binding and partial-publication failures | 14 actual Mongo continuation cases | Reused queue finish, fenced store and active transaction |

Stamped jobs require explicit `claim(history=True)`; default claims still serve
ordinary jobs. The discriminator is not compatibility with an old deployed
binary: disable/drain recovery before rollback to a checkpoint-unaware image.
Tests prove atomic rollback on interrupted yield, quota/failure distinctions,
restarts, stale leases, matching queue/head references and retained publication.
Adjacent continuation/store/admission/recovery regression: 479 passes. Scoped
Ruff/format/mypy and diff checks pass. No worker or provider adapter is activated.
RED `/tmp/history-continuation-red.log` SHA-256
`61273142a6771ce7d7cec7d65f46cbd854ebb53a87f5939f04fc1d730caa5454`;
regression `/tmp/history-continuation-regression.log` SHA-256
`61e7d4a5b455eadc77059169263d8808d6130a01851d209ec31d366b4e4b90aa`.
Only 3.2f closes locally, subject to parent gates/native settlement. Source
authenticity, complete membership and coverage remain adapter/publication work.
Rollback removes this continuation and its queue/store integration only; preserve
staged receipts and observe the existing checkpoint-compatible rollback boundary.

### Scoped apply 3.2g: provider documentation evidence

Updated `provider-evidence.md` with current official Mercado Libre developer
documentation for orders, seller questions, scan cursors and rate-limit rules.
The record distinguishes documented behavior from unverified runtime semantics:
cursor expiry, continuation tokens, resource retention, saturated-hour handling,
and live visibility remain adapter/runtime evidence. No credentials, cursors,
buyer payloads, API calls or production changes were used.

### Partial 3.2h: bounded orders discovery and detail staging

Parent scoped this attempt to discovery/hydration, not complete manifest proof.
`HistoryOrdersProducer.step` uses the real recovery worker's detail validation,
gateway interface, fenced receipts and `HistoryContinuation`. Discovery stores
at most 50 search identities/exclusions per page, advances by returned rows and
keeps exact half-open chunk bounds inside hour-aligned provider query bounds.
Each claimed hydration step commits one detail before another provider call;
this conservative bound preserves already acquired details across interruption.
The producer stops at awaiting-verification phase, never publication/coverage.

| Safety net | RED | GREEN/triangulation | Refactor |
| --- | --- | --- | --- |
| 43 store/continuation tests | Missing producer module | Six initial, then 11 real Mongo/gateway-double cases | Reused worker detail acquisition, pacing and continuation |

Tests cover persisted offset resumption, detail interruption, repeated identities
on shifted pages, changed totals/detail versions, boundary exclusions, local
budget blockers, quota, partial fields and lease rejection before gateway access.
Adjacent store/continuation regression: 54 passes; eight existing worker-detail
tests also pass. Ruff/format/mypy, direct-Meli and diff checks pass. Disposable
loopback test databases were removed; Mongo remained PRIMARY/rs0.
RED `/tmp/history-orders-red.log` SHA-256
`d3b098cf142eebc67c012ea9409ca20dab1d005e7b6a7dc4c34a29e12b9db3a7`;
regression `/tmp/history-orders-regression.log` SHA-256
`3a105b429c566a6ab228658f80ae3094d2be8b3cd71c1dc02ddbcc5dceba360f`.
Task 3.2h remains open: a non-budget verification pass, complete ID/version
manifest comparison, known cancelled-order revalidation, subdivision and durable
publisher handoff are not implemented. Search-row provenance for partial detail
fallback also needs preservation; missing authority is never synthesized.
No worker loop was activated, production accessed, or VCS/build/deploy performed.
Rollback removes this producer/test slice while preserving staged receipts.

### Task 3.2h successor: bounded raw-source provenance (partial)

Preserves optional `source_payload` separately from enriched detail payloads,
with the original provider-response observation time before shipment fallback.
Membership receipts retain search provenance for legitimate partial-detail
seller validation. Legacy receipts may omit this field or retain null; their
old hashes alone do not become verified source evidence.

Strict TDD observed five model/Mongo/store contract failures, two producer
capture failures and one additional real-store seller-binding failure before
their respective fixes. Final regression passes all 717 tests: 140 core model,
86 schema, 35 store, 14 continuation, 13 orders and 429 existing recovery-worker
tests. Scoped Ruff, format, mypy (nine files), schema export, direct-Meli and
diff checks pass. Mongo tests use disposable loopback rs0 databases only.

The store validates source resource/seller identity when supplied and matching
canonical BSON fingerprints; existing nested-key safety and whole-document
1 MiB limits also cover raw source. The model/schema enforce shape and pairing,
not trusted provider authenticity, complete membership or coverage authority.
Missing source seller fields remain allowed for legitimate partial responses;
the acquisition path must retain supporting search ownership evidence.

Regression: `/tmp/history-provenance-regression.log`, SHA-256
`c4e3d8e849b3fe6a175edc4b82f47c5aa4fc955603e93b2bc165d9899a2666e2`.
RED logs: `/tmp/history-provenance-red.log`,
`/tmp/history-provenance-capture-red.log`,
`/tmp/history-provenance-seller-red.log`.

Task 3.2h stays open: full manifest verification, cancelled-order revalidation,
bounded subdivision and durable publisher handoff remain pending. No worker
activation, publication, production DDL, commit, build or deploy occurred.
Before runtime capture, validator rollout needs separate authorization. New
validators accept old receipts, but old strict validators reject the new field;
rollback must disable/drain capture and retain compatible validators/data rather
than assume old binaries accept newly staged receipts. This is a bounded unit
under the authorized size exception, not authorization for runtime mutations.

### Task 3.2h successor: durable second-pass search manifest (partial)

The fenced continuation now allocates verification pass N+1 atomically with
queue yield, retaining hydrated pass N and without consuming the drift budget.
Verification stores raw page receipts and offset checkpoints, compares complete
identity/kind/version/hash membership, and checks missing prior identities with
a final indexed anti-join. Search-row order need not match; changed totals,
same-count substitutions, duplicate shifted pages and source changes restart
under the existing bounded drift policy without deleting acquired receipts.

Strict TDD: baseline 27 passes; seven observed real Mongo RED failures before
implementation. Adjacent regression passes 299 tests; final orders suite passes
26 after two additional triangulation cases (301 distinct passing tests across
the runs). Includes transaction interruption rollback, page retry/resume,
expired ownership, empty sources, boundary exclusions and missing durable-page
evidence. Scoped Ruff/format/mypy, schema export, direct-Meli and diff checks pass.
All database tests use disposable verified loopback rs0 databases.

Regression `/tmp/history-manifest-regression.log`, SHA-256
`3c88389ddf8dcaf4f016e1c535c2e511014fb59ab7dd826ead7ff4cfc918fb33`.
Final orders `/tmp/history-manifest-final-orders.log`; RED
`/tmp/history-manifest-red.log` (seven failures).

Phase remains `verify`; a null cursor is NOT independent publication/coverage
authority. Future reconciliation must inspect both passes and retained detail
receipts, not infer proof from the phase alone, including legacy checkpoints.
The observation window spans source calls, not an atomic provider snapshot.
Raw-hash comparison is conservative even where provider versions are unchanged.
Task 3.2h remains open for known-cancelled identity revalidation, bounded
subdivision and durable publisher handoff; other resource scopes remain pending.
Rollback disables/drains checkpoint-aware recovery and preserves both passes;
old producers do not support these verification checkpoints. No worker loop,
publication, production mutation, commit, build or deployment was performed.

### Task 3.2h successor: known-cancelled detail staging (partial)

After search comparison, the producer selects seller/creation-scoped known IDs
absent from current membership, using a durable receipt anti-join. Each claim
acquires at most one detail. Only current source-owned, in-range cancelled
details generate an atomic membership/detail/search-exclusion receipt triplet
with raw provenance and original observation time. Source status is required;
local cancelled state alone never authorizes the exclusion. Other active
omissions trigger bounded drift; missing/malformed evidence retains checkpoints
and uses existing failure accounting. Canonical orders and freshness are untouched.

The reason `seller_search_omits_source_confirmed_cancelled_order` excludes the
identity from seller-search expectations, NOT from product history. Current-pass
membership now also includes these explicitly classified detail-discovered IDs;
future manifest/publisher logic must distinguish them via their paired receipt,
not blindly compare all membership to search totals. `source_total` remains the
observed search total. Unknown cancelled history cannot be inferred from local
absence, and exhausted known IDs never certify coverage or publication.

Strict TDD: baseline 26 passes; six observed Mongo/gateway RED failures before
implementation. Final adjacent regression: 84 passes (35 orders, 14 continuation,
35 store). Includes current seller/date/status validation, normalized duplicate
IDs, cross-seller/range isolation, interrupted detail resumption and rollback of
all three receipts with their checkpoint. Scoped Ruff/format/mypy, direct-Meli
and diff checks pass. Tests use disposable verified loopback rs0 databases only.
Evidence: `/tmp/history-cancelled-red.log`,
`/tmp/history-cancelled-regression.log`, `/tmp/history-cancelled-quality.log`.

Task 3.2h stays open for subdivision and durable publisher handoff. No coverage,
publication, worker activation, schema rollout or production mutation occurred;
no commit/build/deploy was performed. Rollback disables/drains recovery while
retaining compatible staged receipts; older consumers must not misinterpret
these explicitly classified memberships. Size exception applies only to local
implementation, not runtime authorization.

### Task 3.2h successor: pure bounded subdivision planning (partial)

Added `history_order_subdivision.py`: deterministic, serializable parent/child
metadata with exact half-open UTC bounds, fixed outer cutoff, inclusive provider
hour-query bounds, and a local depth limit. Above the local result budget it
returns two children; their totals must be acquired, never inferred. A saturated
single provider hour raises a typed local-budget blocker rather than inventing
sub-hour provider filters, retention limits or an infinite retry/split loop.

Strict TDD observed the missing-module RED, then three triangulation failures:
missing provider-hour bounds and incorrect depth from elapsed-midpoint rounding.
Balancing provider-hour buckets fixes the latter. Tests partition a full 90-day
partial-hour interval into 2,161 contiguous leaves at depth at most 12, preserving
the exact cutoff. They also cover empty/in-budget observations, invalid counters,
dates and parent linkage, equivalent timezone normalization and deterministic IDs.
Final regression: 58 passes (23 planner, 35 adjacent actual Mongo orders tests).
Scoped Ruff, format, mypy and diff checks pass. Evidence:
`/tmp/history-subdivision-red.log`, `/tmp/history-subdivision-triangulation-red.log`,
`/tmp/history-subdivision-regression.log`, `/tmp/history-subdivision-quality.log`.

This helper is PURE and NOT wired into the producer. No subdivision plan is
persisted yet; durable child scheduling/receipt reconciliation and publisher
handoff remain pending under open task 3.2h. No coverage or worker-integration
claim follows from these unit tests. Rollback removes the unused helper/tests;
no schema, runtime, production, VCS, build or deployment operation occurred.

### Task 3.2h successor: persisted range-node contract (partial)

The full child-store/wiring request was narrowed before edits: immutable monthly
head bounds and queue ownership cannot safely represent child scheduling by
overloading offsets or provider receipts. Added `SheetsHistoryOrderRange` and
the structural validator/indexes for `sheets_history_order_ranges` instead.
Nodes carry acquisition/generation/pass/node identity, seller/root/parent linkage,
exact bounds, depth, state, observed total and next offset. Model validation
enforces UTC/order/depth and lifecycle arithmetic. Mongo enforces structural
types, required/unknown fields and state-local constraints; cross-field arithmetic
and actual parent/head ownership are NOT claimed as Mongo validator guarantees.

Strict TDD: baseline 227 passes; missing-model RED then 162 model tests green;
actual Mongo rejected the preimplementation behavior before schema/index edits.
Final regression passes 275 tests (162 model, 112 schema, one canonical inventory).
Scoped Ruff/format/mypy, schema export and diff checks pass. Validator tests apply
real exports only to disposable loopback rs0 databases; required fields, malformed
states, compound uniqueness, pass isolation and no-TTL index metadata are checked.
Evidence: `/tmp/history-range-model-red.log`, `/tmp/history-range-schema-red.log`,
`/tmp/history-range-regression.log`, `/tmp/history-range-quality.log`.

No active-range head pointer, fenced node writes, atomic split/receipt transaction,
producer wiring or publisher handoff is implemented. Task 3.2h remains open.
The new collection is inert outside disposable tests; production validator/index
application requires separate authorization. No production mutation, activation,
commit, build or deploy occurred. Rollback removes the unused contract/export;
once runtime wiring exists, preserve range documents and a compatible consumer.

### Task 3.2h successor: fenced range-node store (partial)

Added discovery-only `HistoryRangeStore`: root allocation, atomic parent split
and child-page receipt/checkpoint writes share queue ownership, head revision CAS
and pending yield. The optional active-range pointer preserves fixed monthly head
bounds; older heads missing the field normalize safely. Drift restart clears the
pointer while retaining prior-pass nodes. Child pages enforce local record/result
budgets, seller/root/generation binding, exact creation bounds, duplicate rejection
and matching offsets/totals. Final leaf enumeration checks split-parent totals
before entering hydrate; it does not publish or establish provider completeness.

Strict TDD observed missing-store RED, three actual Mongo pointer-validator REDs,
naive-source-time rejection and lost-observation triangulation failures, plus a
batch-limit preflight failure before fixes. Final regression passes 397 tests,
including 15 new range-store cases in the EXISTING
`modules/sheets/tests/test_history_acquisition_store.py` (no separate test file).
Tests include transactional rollback, partial-page resume, duplicate and malformed
scope rejection, lease loss, stale CAS, mismatched parent totals and legacy restart.
Scoped Ruff/format/mypy (six files), schema export and diff checks pass.
All database tests use disposable verified loopback rs0 databases.

Evidence: `/tmp/history-range-store-final-regression.log`, SHA-256
`e879805f33c6803c862c4903ef7f0814b07f4f1d2a9b4431f9f2e30c01494d6a`;
`/tmp/history-range-store-quality-final.log`. RED logs are under
`/tmp/history-range-store-*red.log` and `/tmp/history-range-pointer-red.log`.

Task 3.2h remains open: the producer is NOT wired to this store, verification-pass
range traversal and publisher handoff remain pending. Nonempty pages preserve
receipt observation times; zero-result pages currently leave the observation
window unchanged. Integration must add explicit empty-page source observation
input, never synthesize it from staging time. Validator rollout requires separate
authorization; old strict validators reject the new pointer field. Rollback must
disable/drain future range consumers and preserve checkpoint-compatible data.
No activation, publication, production mutation, commit, build or deploy occurred.

### Task 3.2h successor: producer subdivision/verification wiring (partial)

`HistoryOrdersProducer` now routes oversized count probes to atomic persisted
root/child splits and resumes actual leaf pages through `HistoryRangeStore`.
Count-probe rows are not accepted membership; validated leaf pages establish the
durable acquisition boundary. Fixed head bounds remain unchanged. Saturated
provider-hour queries produce explicit local-budget blockers, not retention
claims or unbounded subdivision. Verification uses the same child traversal and
the existing full manifest checker inside the fenced final-page transaction.
Typed range-total drift triggers bounded restart without confusing ownership
conflicts with provider changes or committing the contradictory last page.

Actual gateway-response observation timestamps are passed explicitly through
empty child pages, count probes and unsplit empty pages. Tests deliberately delay
staging and prove it does not replace the earlier source observation timestamp.

Strict TDD: baseline 85 passes; five initial wiring RED failures, followed by
unsplit-empty observation RED and three malformed count-probe REDs before fixes.
Final regression: 131 passes (44 orders, 50 store, 14 continuation, 23 planner).
Includes interrupted child resume, same-count manifest drift, child-total drift,
empty child observations and recursive saturated-hour termination. Scoped Ruff,
format, mypy, direct-Meli and diff checks pass; disposable loopback rs0 only.
Evidence `/tmp/history-range-wire-regression.log`, SHA-256
`7fcc46904bad8c16f525a40bf2feeb1b75612b3bbe19f6add6251b9e461211ab`;
quality `/tmp/history-range-wire-quality-final.log`; RED logs use the same prefix.

Task 3.2h remains open for publisher handoff and the unchanged local 10,000
known-ID extra-recovery guard, which can still block very large known inventories.
No coverage certification, publisher or worker-loop activation, production
mutation, commit, build or deploy occurred. Rollback preserves range/receipt
checkpoints and requires a compatible consumer or disabled/drained recovery.

### Bounded guarded publication primitive (3.2i partial)

Strict TDD: baseline read-model tests passed26; disconnected-proof RED failed
both proof-order cases before the read-gate correction. Publisher import RED
preceded its implementation; a later exact-boundary live-edge RED exposed and
fixed another withdrawn-tail authorization. Tests seed a persisted publish head;
they do not demonstrate a producer handoff, source completeness or finalization.

The primitive projects at most20 receipt-backed orders with original observation
times through real guarded persistence. Queue/head fences, proof subtraction,
batch checkpoint and operation release share the transaction. Newer intervening
events win; operation expiry and interrupted later batches roll back without
certifying totals. Remaining interval proofs stay usable independently. Limits
bound receipt inputs (1MiB each/4MiB batch), not total write-amplified BSON.

Verified loopback rs0 PRIMARY and nofile65536; fixtures apply actual validators
and indexes to unique disposable databases, then drop them. Final publisher12,
adjacent145 (including nine publisher cases), and coverage/recovery439 passed;
587 distinct cases across these runs. Scoped Ruff, format, mypy and diff-check
passed. Logs: `/tmp/publication-final.log`, `/tmp/publication-regression.log`,
`/tmp/publication-coverage.log`; final publisher SHA256
`eb27a136c18598aedc0e4f11e6893b614a04335a9faf3ec03433325d777e2663`.

Task3.2i stays open for trusted publish-state handoff and bounded final inventory
reconciliation/coverage certification. No worker activation, commit, build,
deployment or production mutation. Rollback removes this unactivated primitive;
preserve any future partial checkpoints and keep their affected proofs withdrawn.

### Shared question-scan admission identity (3.2j partial)

The authorized first slice adds a dedicated request for exact twelve-calendar-month
UTC/BSON bounds. Seller/plan identity coalesces repeated consumers; changing its
fixed bounds fails. Admission is history-only from insertion, preserves terminal
states and retains seller/capacity controls. Existing seller_scan head/schema/index
are reused; no additional collection or validator is needed for this slice.

Strict TDD: missing request import RED preceded source changes. Thirteen tests
passed against unique disposable loopback rs0 PRIMARY databases with actual
head/receipt validators and indexes. They prove twelve concurrent consumers share
one admission, durable cursor/checkpoint reuse, and explicit cursor_expired or
source_drift release rotates the manifest pass while preserving old receipts,
fixed bounds and the three-restart budget. Signals are supplied by the harness:
these tests do not prove provider expiry detection or manifest comparison.

Scoped Ruff, format and mypy passed. Focused evidence `/tmp/questions-green.log`,
SHA256 `cfc14fd2dc11c362cccf5421245ca5ab0e9d286b54a604a80bd2dd5522f6feb9`.
Adjacent queue/terminal/continuation regression passed463, zero skipped:
`/tmp/questions-regression.log`, SHA256
`00a05365de52ebb008740fa88d7651f25ca04b7c85ffff600d63c8ac4a3987bf`.
Task3.2j remains open for provider continuation semantics, bounded enumeration,
automatic drift detection, partitioned hydration and interval subscriptions.
No worker activation, certification, production mutation, commit/build/deploy.
Rollback must preserve protocol-stamped jobs/heads and leave them unclaimed by
legacy workers; the unchanged legacy range request still rejects over90days.

### Provider-neutral question traversal (3.2j partial)

Strict TDD import RED preceded the normalized page/staging implementation.
The caller supplies opaque continuation, explicit terminal and actual observation;
expiry is an explicit signal, not a guessed timeout or HTTP response mapping.
Each page persists at most50 seller-wide membership receipts plus the cursor
under existing queue/head fences. Out-of-plan identities remain discovery evidence,
not hydrated detail. Local total budget10000 is not a provider retention claim.

A separate durable verification pass compares every identity/raw-payload hash;
distinct membership plus terminal cardinality detects missing IDs, including
equal-count replacements. Drift restarts under the existing three-restart budget
without deleting receipts. Empty terminal pages still require another observation;
verified traversal stays phase verify, never published/completed or certified.
Rollback after staged writes and lease-loss tests prove no partial checkpoint.

Real disposable loopback rs0 PRIMARY with installed validators/indexes and
nofile65536: questions28 + continuation14 + store50 =92 passed, zero skipped.
Ruff, format, mypy2files and diff-check passed. Evidence:
`/tmp/question-adapter-regression.log`, SHA256
`c42bc1dcf3d10acea1a8ec00930fb77dd0ec47a79a450a1ffd72e07025d063c8`;
RED `/tmp/question-adapter-red.log`, quality `/tmp/question-adapter-quality.log`.

Task3.2j remains open: actual HTTP normalization/provider semantics, partitioned
detail hydration and monthly proof subscriptions are not implemented. No activation,
coverage authority, commit/build/deploy or production mutation. Rollback preserves
pass-indexed receipts and leaves history-only jobs for a compatible staging worker.

### Bounded question hydration and monthly bindings (3.2j partial)

Strict TDD: baseline28 passed, missing detail/subscription import RED preceded
source changes. The neutral staging adapter now accepts at most20 observed
details, requiring current verified-pass membership, matching seller/creation
instant/status/item identity and an answered-question answer object. Detail
receipts retain raw payload/hash and actual supplied observation. Empty text
alone is accepted. Out-of-plan discoveries remain memberships, not hydration.

Twelve deterministic half-open monthly bindings derive from the durable fixed
head/plan and share acquisition/generation/pass identity. They require a finished
verification traversal and survive reconstructed consumers. They are acquisition
descriptors, not persisted independent interval proofs or publication authority.
Tests distribute twelve questions across all twelve months, resume in batches,
reject the exclusive upper cutoff, wrong membership/seller/date/status, duplicate
details and oversize batches, and roll back an interruption after staging writes.
Detail/source drift is a typed rejection; no HTTP or rescan policy is invented.

Actual disposable loopback rs0 PRIMARY with validators/indexes and nofile65536:
questions38 + continuation14 + store50 + planner17 =119 passed, zero skipped.
Ruff, format, mypy2files and diff-check passed. Regression evidence
`/tmp/question-hydration-regression.log`, SHA256
`3967a3470f7eac359388222b353644d0c76efe416477cf10067638da7e665570`.

Task3.2j remains open for actual HTTP normalization and authoritative published
interval proofs/finalization. No canonical question writes, coverage markers,
worker activation, commit/build/deploy or production mutation. Rollback preserves
detail receipts and history-only jobs for a checkpoint-compatible consumer.

### Actual orders staging worker (3.3 partial)

Strict TDD admission import RED preceded implementation; a second behavioral RED
proved preexisting protocol heads must resume without requiring new admission
metadata. The worker now loads the durable head and lets existing ownership/pass
fences authorize every producer step. New plan-bound order admission preserves
fixed BSON bounds, seller/capacity guards, terminal jobs and legacy-worker exclusion.

Real process_one invokes HistoryOrdersProducer, reconstructs between steps and
resumes after cancellation/lease expiry without requerying committed discovery.
Twelve concurrent admissions coalesce; receipts, existing canonical history and
prior interval markers remain intact. The unfinished publication boundary is a
typed local blocker recorded atomically with terminal queue release, never source
absence or successful coverage. Questions and legacy jobs are excluded by the
explicit orders-only queue; no supervisor/runtime activation was added.

Disposable loopback rs0 PRIMARY with actual staging validators/indexes: adjacent
regression586 passed, then final worker5 passed (four overlap):587 distinct cases,
zero skipped. The final five include preexisting-head correction. Ruff, format,
mypy4files, direct-Meli and diff-check passed. Evidence logs:
`/tmp/history-worker-regression.log` SHA256
`018239a898a70b319ccd30289e31d7f552ca8ff64a165304848ad652e8d15f52`;
`/tmp/history-worker-final.log` SHA256
`4d2df7a96ce4a667da3ccf295f2d16c728a65ed0e861a3baa919f7bb469b02b5`.

Task3.3 stays open for runtime admission wiring, publication/finalization and full
cross-resource/twelve-month coverage. No commit/build/deploy/production mutation.
Rollback keeps protocol jobs unclaimed by legacy workers and retains durable heads,
receipts and prior canonical data; a compatible consumer is required to resume.

### Modification-time admission with exact overlap (3.4 partial)

Strict TDD missing-module RED preceded implementation. Normalized pages now use
the exact UTC half-open interval [watermark−24h,cutoff), independent of order
creation time. The old creation-tail helper is documented honestly; it does not
detect recent changes to old orders. No HTTP filter/continuation is invented.

Requests enter the existing order-ID lane with durable ID/modification-version/raw
hash identity. Repeated observations preserve terminal jobs; changed timestamps or
payloads obtain distinct jobs even when an older version is active. Accepted keys
include existing and failed jobs, never proof of processing or newly inserted work.
Seller allowlists/capacity remain enforced; invalid inputs, storage errors and
capacity defer only their seller page. Partial admission safely replays. Inputs are
bounded to50 records and1MiB each. No watermark or coverage marker is written.

Real disposable loopback rs0 PRIMARY: regression538 passed, then final admission9
passed (eight overlap):539 distinct cases, zero skipped. A behavioral RED for
malformed checkpoint input proved and fixed cross-seller failure propagation.
Ruff, format, mypy4files and diff-check passed. Combined evidence
`/tmp/modification-evidence.log`, SHA256
`c8f6e73b03c5823016db7315bc44384a233277609e2b95f85c53e58d1a0e786f`.

Task3.4 remains open for actual source enumeration, durable cursor/successful
watermark finalization and runtime wiring. Failed retained jobs need explicit
recovery; admitted does not authorize advancing a watermark. No deployment,
commit/build, canonical writes or production mutation. Rollback preserves ID jobs;
existing compatible ID workers can consume them without a new queue protocol.

### Authorized returns repair boundary (3.5 partial)

Real Mongo RED exposed a local authorization-order defect: expired, not-yet-due
or unauthenticated existing runs acquired a new operation and invalidated readiness
before the downstream authorization check refused source work. Preflight now
rejects these known-invalid runs before lease acquisition; the existing downstream
check remains, so this does not claim atomic immunity to intervening authorization
changes. Existing tests now supply actual authorization/expiry fields rather than
permissive incomplete fake runs.

A bounded helper attempts at most seven supplied existing run IDs, coalesces
duplicates and isolates failures. It preserves the pilot-only CLI boundary;
foreign-seller runs are rejected without mutating their operations. It never
creates, extends or reauthorizes a run.

Tests use isolated loopback rs0 PRIMARY with installed run/window/operation/claim/
order/freshness validators. An empty-source fixture traverses the real source,
guarded quota window, readback and finalization path. Lease/source failures never
finalize. This is software evidence for an empty interval, not evidence that the
seven production intervals or positive return rows were repaired.

Focused13 and adjacent236 passed, zero skipped; Ruff, format, mypy3files and
diff-check passed. Evidence `/tmp/returns-regression.log`; RED `/tmp/returns-red.log`.
Task3.5 remains open for authorized runtime evidence. No production access,
API-limit claim, commit/build/deploy or new runtime activation. Rollback leaves
existing run/window/claim records unchanged; retain the authorization preflight
or disable advancement rather than deliberately reintroducing readiness loss.

### Task 4.1 partial — executable local formula evidence

Added an opt-in pytest dispatcher recorder and two RED/GREEN harness tests.
The new test first failed importing the absent recorder; the recorder then
passed focused checks. It admits only observations from passing tests, excludes
failed/skipped tests, detects unknown catalog names, and records no cell values
or arguments. Local scope and false Sheets/correctness flags are explicit.

Executed 800 tests, zero failed/skipped, covering actual dispatcher calls to
all 52 registered formulas; no missing or unknown formulas. The matrix in
`formula-local-execution.md` lists per-formula counts and example test IDs.
Fixtures include doubles: this does not establish Mongo filtering correctness,
all four required variants per formula, deployed images, or Sheets visibility.
Task 4.1 and the deployed matrix Observed/Evidence columns remain pending.

Evidence: `/tmp/formula-local-run.log` SHA256
`13d29bde6a9b7e18d20d30ab248d14a322fd4688c6d41596e988a42f1509902e`;
full sanitized observation matrix `/tmp/formula-local-matrix.json` SHA256
`0be0808da610d55e50dae5f8c15987ccbe706e3be29070139dd2501dd768ad42`.
RED `/tmp/formula-evidence-red.log`; focused GREEN `/tmp/formula-evidence-green.log`.
Ruff, format, mypy two files and diff-check passed. A replica-discovery health
probe followed an advertised 27017 and failed; explicit direct connection to
loopback 27028 then verified rs0 PRIMARY. Selected formula fixtures use doubles;
this probe is not database-integration evidence. No runtime changes or activation.

Rollback: remove the optional test plugin, its tests and local evidence document;
production behavior and persisted data are unaffected. Durable learning: formula
name references are weaker than executed dispatcher observations, and even an
executed passing test is not blanket correctness or Google Sheets acceptance.

### Task 4.3 partial — concurrent local cold-source execution

Extended the opt-in harness with an exact-catalog concurrent runner. Baseline
two tests passed; RED failed because the runner was absent. A 52-party barrier
then proved concurrent task entry before any completion. Additional harness
tests cover incomplete/duplicate catalogs, per-formula unavailability isolation,
timeout and unexpected-error cancellation with all started tasks drained.

The integration test uses the real dispatcher, all production handler builders,
real read repository and a unique disposable local Mongo database. Verified
loopback 27028 rs0 PRIMARY and nofile 65536 before execution. Database is empty
and read-only for the batch, then dropped in finally. Concurrent results match
sequential results: 19 returned and 33 unavailable. Returned means an output,
not positive populated data; this is deliberately a cold-source scenario.
No validator, projection, recovery queue or runtime activation is claimed.

Regression: 43 passed, zero skips/failures = seven harness tests, one concurrent
integration test and exactly 35 existing tests in
`test_formula_handlers_returns_histories_withdrawals.py`. These 35 cover returns,
history/status and joint readiness regressions; they are not a claimed canonical
production acceptance catalog. Full Sheets concurrency and representative
populated seller behavior remain pending; task 4.3 stays open.

Reproduce with `uv run pytest -q` selecting
`modules/sheets/tests/test_formula_execution_evidence.py`,
`modules/sheets/tests/test_formula_concurrent_execution.py` and
`modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py`,
adding `-p modules.sheets.tests.formula_execution_evidence` and
`--formula-evidence=/tmp/formula-concurrent-matrix.json`.
Use an explicit verified disposable local MONGO_URI, unset ZELER_RS0_TEST_URI.
The JSON includes synthetic harness tests; distinguish the named real-handler
integration test when interpreting observations. No payloads are recorded.

Evidence `/tmp/formula-concurrent-regression.log` SHA256
`986dbc9a5d6b6525242d1315dd44f9f5e97162596004680091f1927df955e4ea`;
JUnit `/tmp/formula-concurrent-regression.xml` SHA256
`b88f402129b6e3e4cb66df9919332712ee24c1fa4d766434afe889c2fda6a879`.
RED `/tmp/formula-concurrent-red.log`; scoped Ruff, format and mypy three files
passed. No source/runtime changes, commits, builds or deploys. Rollback removes
only the new tests/helper; persisted production state is unaffected. Local
coroutine concurrency is not Apps Script execution or visible-cell acceptance.

### Task 5.1 partial — bounded manual Apps Script refresh

Replaced the unbounded active-tab scan with a manual document-locked traversal.
Per invocation: at most 20 writes, 2,000 scanned cells, 50 cells per read, and
a cooperative 20-second budget checked between service calls. A blocked Google
RPC can exceed wall-clock budget; no hard platform deadline is claimed.
The local plan accepts at most 500 tabs and persists original sheet IDs plus
position in document properties. Reordering preserves that plan, deleted tabs
are skipped; newly added tabs enter the next full manual traversal.

Candidates require the existing exact prefix. Immediately before setFormula,
getFormula must still equal discovered text; changed cells are skipped. Cells
are never cleared. The document lock coordinates this action across scripts,
not concurrent human edits: Apps Script does not provide a CAS here and a user
edit between reread and write remains a limitation. No automatic trigger added.
`pending` means scan work remains, not a known count of cells awaiting results;
`recalculationVerified` is always false. Toasts report requests, never visible
success. Failed writes retain the current cursor and release the lock; property
write failure propagates after lock release and may require bounded replay.

Baseline 32 passed. Nine executable Node scenarios failed against old Client.gs
before its modification. Eleven scenarios now execute the actual Client.gs in
a local service-double VM: limits, cross-tab resume/reorder, changed formula,
busy/missing lock, write retry, deadline, deleted tab, empty sheet, corrupt
cursor and property failure. Adjacent regression totals 43 passed, zero skips.
This does not execute Google APIs, custom-function recalculation or cell visibility.
Task 5.1 stays open pending actual authorized Sheets evidence.

RED `/tmp/apps-refresh-red.log`; regression `/tmp/apps-refresh-regression.log`;
JUnit `/tmp/apps-refresh-regression.xml` SHA256
`30052770955847a26055fec1a5c3a3b0e8488240594ca85e1762302499f41fa8`.
Scoped Ruff, format, mypy two files and diff-check passed. Reproduce with
`uv run pytest -q modules/sheets/tests/test_apps_script_refresh_execution.py
modules/sheets/tests/test_pilot_sheets_refresh_cells.py
modules/sheets/tests/test_apps_script_addon.py` (one command).
No Google/production mutation, trigger, commit, build or deployment occurred.
Rollback restores the prior Client.gs implementation; the unused cursor property
is inert. Production activation requires the separate add-on publication path,
not merely rebuilding backend images. Prefer keeping bounded manual behavior
rather than restoring an unbounded scan.

### Task 5.2 partial — authorized progress, pending rendering and retry coalescence

Baseline 19 passed. Executable Apps Script RED showed a PROCESSING envelope
with empty/zero/stale values hid its pending message. The renderer now prioritizes
explicit unsuccessful PROCESSING over values; successful zero values remain
unchanged. Local fetch-double tests also prove one HTTP call per invocation,
with no automatic retry loop, trigger or cell mutation. PROCESSING is a retry
hint, not proof that a background job exists or will complete.

Extended existing ASGI progress tests against a verified disposable loopback
rs0 PRIMARY. Real callback/queue snapshot contains all 48 descriptors: 24 blocked,
19 pending, four queued and one failed. Repeated callbacks preserve terminal
attempts; five authorized GET polls do not change or duplicate jobs. Existing
six authorization rejection cases still prove rejection before any DB access;
their JWT signature boundary is explicitly stubbed, not cryptographic evidence.

Formula HTTP retry test uses a real extension token service and Mongo queue,
with only the missing-source dispatcher injected. Ten calls with distinct
request IDs coalesce to one job across pending/running states and preserve
its running attempt. This is not a claim about terminal legacy-job reopening,
which retains its existing semantics. Admission acknowledgment is not completion.

Regression: 132 passed, zero skipped/errors/failures; scoped Ruff, format,
mypy two files and diff-check passed. RED `/tmp/progress-retry-red.log`;
regression `/tmp/progress-retry-regression.log`; detailed test IDs/counts in
`/tmp/progress-retry-regression.xml`. No new endpoint or response-shape changes.
JUnit SHA256 `c44edcb0960d96d97bab38aa36f5414f1d35d6319fa32c00a3b889dffcd985fc`.
Task 5.2 remains open: zeler-app exists but is outside this unit's edit roots,
and neither its UI nor live Google Sheets was executed. No Google/production
mutation, deployment, build or commit. Rollback affects the small pending
renderer priority change and tests only; persisted queue contracts are unchanged.

## Task 5.3: automatic-refresh research and disposable probe

The [probe proposal](apps-script-refresh-probe.md) records official Google
constraints, a no-write control versus same-text versus disposable
clear/flush/restore experiment, and separate automatic-open/reopen acceptance.
Simple LIMITED document access is distinguished from sidebar restrictions;
installable FULL handlers are a candidate to test, not asserted unsupported or
guaranteed. Additional trigger scope remains a separate explicit decision.

| Evidence | Result |
| --- | --- |
| Executable changes / TDD | None; documentation-only, no executable behavior changed. |
| Local validation | Relative spec/runbook references exist; `git diff --check` passes; task 5.3 remains unchecked. |
| Runtime harness | Not executed: requires approved disposable spreadsheet and operator actions. |
| Rollback | Remove probe document and its task/progress references only. |

No scopes, triggers, Google resources, production runtime, builds or deployments
were changed. Task 5.3 remains pending real automatic open/reopen evidence.

## Task 6.1 partial: final local repository gates, 2026-09-15

Validated completed artifacts from the parent-run full suite against the
explicit disposable loopback Mongo target on port 27028 with direct connection;
inherited ZELER_RS0_TEST_URI was unset. Command: `uv run pytest -q
--junitxml=/tmp/final-suite.xml` (one command). Recorded process exit is zero.
The XML reports **5332 cases: 5323 passed, nine skipped, zero failures/errors**.
This corrects the preliminary description of eight skips: eight protected
stock-time rs0 cases reject ambient MONGO_URI before connecting, and one Caddy
environment-template case has no required keys. Skips are not acceptance;
this invocation does not revalidate those eight protected workflows.

| Gate | Completed local evidence |
| --- | --- |
| Full pytest | `/tmp/final-suite.log`, SHA256 `5af7c14dcc7ed734ae46603da67f225bec32d9e514e8e9f0278c815b7848571e` |
| Per-test results and skip reasons | `/tmp/final-suite.xml`, SHA256 `48cebba33772d9e565642bdf0e56695dae6a1301a58f997f7b90bf99da6de415` |
| Root quality bundle | `/tmp/final-quality.log`, SHA256 `b1bccc2f0dbe8fa49142395ef67654233bf7e0331cd5caabbd0453ff530aa482` |

After the interrupted-export replay test, the current rerun produced
`/tmp/zeler-current-suite.xml` (5332 cases: 5323 passed, nine skipped, zero
failures/errors; SHA256
`f2a30d0838b3552ef6d2931d074b0b9bb6dfe6fe72cad3e05020ae67a6fd3e1c`) and
`/tmp/zeler-current-quality.log` (all five root gates passed; SHA256
`4b7de804035961101eb767bc34413b0a28f3efd9cab8730982fcfb7761668ab5`). The
current artifacts supersede the earlier hashes for local evidence;
the same protected runtime and Sheets gaps remain.

The parent-run quality bundle completed `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy .`,
`uv run python -m infra.lint.check_direct_meli .`, and
`uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check`.
Recorded output: Ruff passes, 598 files formatted, mypy passes 598 source files,
and overall exit zero; Meli/schema checks are silent on success.

These are current local software gates, not deployed-image, provider, Google
Sheets, automatic reopen, twelve-month completed acquisition, or 90-minute
runtime observation evidence. Task 6.1 stays unchecked while remaining
corrections/runtime acceptance are open. Rerun affected gates after further
executable changes. No new runtime operations, production queries, build,
deployment or commit were performed by this documentation unit. TDD is not
applicable to this evidence-only update; validation is artifact/hash/count
comparison, consistency with pending tasks, and `git diff --check`.

### Administrative sync-job retry deduplication

The active-job retry gap identified in verification is corrected locally. The
manual `/sheets/sync-jobs` endpoint now returns the existing pending or running
job instead of creating another request for the same seller. The RED regression
and adjacent API tests pass (`test_api_phase6.py`), with Ruff, format and mypy
passing for the touched files. This is local behavior evidence; cross-process
atomicity now has a unique partial index and duplicate-key recovery path; deployed
UI behavior and live Sheets execution remain unproven.

The platform also exposes `GET /sheets/sync-jobs/{job_id}?seller_id=...` for
seller-scoped status correlation. Authorization runs before the database lookup;
cross-seller requests return `403`, while a missing job owned by the seller
returns `404`. This establishes the backend status-read contract; zeler-app
polling/UI and live Sheets recalculation evidence remain pending.

### Consumer interruption replay evidence

`test_interrupted_export_is_replayed_before_idempotency_is_marked` exercises the
actual `SheetsEventHandler` with a transient Sheets append failure. The first
delivery persists the source but does not mark the idempotency key; the retry
appends exactly once and a subsequent redelivery is skipped. The focused phase-6
and gateway integration tests pass (11 total). This closes the local unfinished
export replay case; broker-level reorder and production consumer recovery remain
pending.

### Disposable Sheets probe — negative observation

Using the authorized spreadsheet `Pruebas ZelerData actual`, tab
`pruebasnuevas`, the native Sheets read confirmed the pilot formula remains in
`A3` after the same-formula write. The returned `dataSourceFormula` state is
`NOT_STARTED` and no effective/formatted result is exposed. This is direct
evidence that the connector pass did not establish visible recalculation; it
does not prove a provider failure or authorize changes outside the disposable
cell.

### Broker-level consumer delivery evidence (task 2.1)

`modules/sheets/tests/test_consumer_broker_delivery.py` adds the missing
transport-level layer. It runs the real `SheetsAmqpConsumerRunner` against a
disposable loopback RabbitMQ broker (`127.0.0.1:5673`) with the real
`modules/sheets/manifest.yaml` routing keys and the real `zeler.sheets.claims`
passive consumer, and the real `SheetsEventHandler` against a disposable
loopback Mongo replica set (`127.0.0.1:27028`, L-012) with the production
`processed_events` idempotency store adapter and the real
`SheetsEventPersistence` freshness guards. Only the Meli gateway client and the
Google Sheets client stay doubled. The broker URL must resolve to a loopback
host or the run aborts, and both harnesses skip explicitly when absent, so the
evidence can never target a shared broker by accident. Production retry parking
is 30 s (`infra/rabbitmq/delay_queues.json`); the disposable broker shortens the
parking window to 2.5 s while exercising the same publisher, exchange and
dead-letter routing.

| Case | Command | Result |
| --- | --- | --- |
| Duplicate delivery (sequential) | `uv run pytest modules/sheets/tests/test_consumer_broker_delivery.py -o addopts=''` | Passed. First delivery returns `appended`, the redelivery returns `duplicate`; one append, one gateway fetch, one `processed_events` marker, empty live and delay queues, empty DLQ. |
| Out-of-order delivery | same command | Passed. Newer observation is delivered first and the older one second; the persisted `items` document keeps the newer `199.99` / `2026-04-25T12:30:00Z` state, both events settle, no DLQ. |
| Unfinished event recovery | same command | Passed. A `RetryableGoogleSheetsApiError` on the first attempt parks the message in the retry delay queue (observed depth ≥ 1, main queue depth 0, no DLQ), the broker returns it after the delay, and it completes exactly once (one failure, one append, one marker). |
| Concurrent duplicate deliveries | same command | **Failed — measured defect.** With production prefetch (10), two copies of one event in flight both pass `is_duplicate` before either marks the key. Observed: two appends, one `processed_events` marker, both messages acked on their first attempt. |

The `is_duplicate`/`mark_processed` pair is a check-then-act sequence:
`SheetsEventHandler.handle` checks the key, then persists, appends to Sheets and
only then marks the key. The spec scenario "Duplicate and late events converge"
requires idempotent results for repeated notifications. The sequential and
unfinished-recovery cases satisfy it; the concurrent case does not, and the same
ordering exists in the Repricer and Autoreply consumers
(`modules/repricer/src/zeler_repricer/consumer.py`,
`modules/autoreply/src/zeler_autoreply/consumer.py`). Two probe defects of this
new test were corrected before the defect was confirmed: robust-channel
declaration caching produced stale queue depths (now read through a plain
channel), and the first "sequential" gate waited for the append, which happens
before the marker is written (now waits for the marker).

Production exposure requires two copies of one idempotency key in flight inside
the handler interval: a near-simultaneous duplicate publication, or worker
overlap during a rolling replacement. The local reproducer widens the window
with a 0.25 s gateway delay to make the race deterministic.

Task 2.1 remains open until the concurrency outcome is decided: fix the
suppression primitive, or accept and document at-least-once append behaviour
explicitly. Fixing it atomically needs a claim/lease state machine (in-progress
vs completed, lease expiry, and a consumer outcome that requeues a live claim
instead of acking it) because a plain mark-before-side-effects would lose events
that fail after the marker. That is a cross-cutting change to the shared
`processed_events` contract, not a local patch.

Focused gates for the new file: `uv run ruff check` and
`uv run ruff format --check` pass, and `uv run mypy
modules/sheets/tests/test_consumer_broker_delivery.py` reports
`Success: no issues found in 1 source file`.

### Broker evidence closes: concurrent duplicate defect fixed

The broker-level file now passes all four cases (4 passed, stable in 10
consecutive runs), and task 2.1 is checked. The concurrent duplicate case that
previously failed (two appends, one `processed_events` marker, both deliveries
acked) motivated a separate ODD feature,
`odd/tasks/atomic-event-claim-lease.md`, which the user explicitly routed around
SDD:

- **S1** adds an additive, inert `EventClaimStore` in
  `core/src/zeler_platform_core/events/claims.py` with `ClaimOutcome`
  (`claimed`/`completed`/`timed_out`), atomic `find_one_and_update` acquisition
  against a separate short-lived `processed_event_claims` collection, owner-token
  fencing, and marker-before-lease-release ordering in `complete`. `processed_events`
  keeps meaning completed, so the DLQ reconciler's `already_applied` semantics,
  the runbooks and the 48 h retention are untouched. Schema, TTL index and the
  schema-inventory entry are included (`core/tests/test_event_claims.py`: 17 passed).
- **S2** adopts the primitive in `SheetsEventHandler` through a
  `_ClaimHandle`/`_EventGate` pair, so the handler body is not duplicated and the
  legacy check-then-act remains only as the gate used when no claim store is
  injected (unit doubles). `run()` wires the real store, and
  `test_sheets_run_entry.py` asserts that wiring so it cannot silently regress.
  A new retryable `EventClaimTimeoutError` uses the existing retry-delay path.
- Two independent verifications ran during the work. The first found that
  `complete` released the lease before writing the marker, which reopened the
  duplicate window; the order is now marker-before-delete. The second found four
  smaller limits, all fixed with RED->GREEN tests: best-effort marker cleanup,
  a warning instead of a silent ack when the lease was lost, a release failure
  that can no longer mask the original exception, and `transient_timeout`
  classification for the new exception.

Honest limits: exactly-once against a non-transactional Google Sheets append is
not achievable, so the at-least-once boundary (a crash between append and marker)
is unchanged and declared. A lease that expires while its owner is still running
(120 s lease, observed handler duration far below it) can still let a second owner
run the side effects. A contended duplicate blocks its delivery slot for up to the
30 s wait, which is a throughput consideration, not a health one.
`infra/mongo/indexes/processed_event_claims.json` must be applied before the new
code is deployed, otherwise expired leases linger on disk.

Final candidate evidence for the fix: `core/tests/test_event_claims.py` 17 passed;
`modules/sheets/tests/test_consumer_broker_delivery.py` 4 passed; focused Sheets
suites 77 passed; `modules/sheets/tests` with `MONGO_URI` on the disposable
loopback replica set 2817 passed; `uv run ruff check` and `uv run mypy` clean on
the touched paths. Repricer and Autoreply still use check-then-act and are tracked
as slices S3/S4 of the ODD feature; no deployed-runtime evidence exists yet.

Follow-up completion of the same feature: the generic gate now lives in
`core/src/zeler_platform_core/events/claim_gate.py` and the Sheets consumer
imports it under its previous private aliases, so no behaviour changed there.
Repricer and Autoreply adopted the same flow (claim before any read, terminal
outcomes complete exactly once with a lost-lease warning, Repricer's
`item_missing`/`rule_missing` release so a redelivery can re-run, exceptions
release without masking, `EventClaimTimeoutError` retried through each module's
retry-delay path before the `RuntimeError` branch, and `run()` wired with a
wiring test). The DLQ reconciler stays governed by `processed_events` only:
`tests/operations/test_sheets_dlq_reconcile.py` now proves that a live claim lease
is never classified `already_applied` and that `processed_event_claims` is not in
`EVIDENCE_ORDER`, and `docs/ops/sheets-dlq-reconciliation.md` states the operator
rule. Pre-deploy requirement: apply
`infra/mongo/{schemas,indexes}/processed_event_claims.json` in the same separately
authorized rollout step as any other schema/index change.

Final candidate gates for the claim/lease work, run against the final tree with
`MONGO_URI` on the disposable loopback replica set: the full repository suite
reports 5383 passed, 9 skipped, 0 failed and 0 errors; `uv run mypy .` reports
`Success: no issues found in 604 source files` (the root gate, not just the
touched files); `uv run ruff check .` and `uv run ruff format --check .` are
clean; and `uv run python -m zeler_platform_core.cli.export_schemas
infra/mongo/schemas --check` exits 0. The 9 skips are the documented protective
`ZELER_RS0_TEST_URI` refusals plus one GCE compose-contract skip.
