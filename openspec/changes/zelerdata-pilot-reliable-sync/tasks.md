# Tasks: ZelerData Pilot Reliable Sync

## Review Workload Forecast

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Delivery strategy: auto-chain. Logical ≤400-line units only; no VCS/build/deploy
authorization or size exception. PR topology pending. Historical evidence:
[audit](evidence-audit.md), [progress](apply-progress.md).

## Phase 1: Contract

- [x] 1.1 Complete 52 Expected rows; Observed/Evidence remain runtime-pending.
- [x] 1.2 Verify 52 formula contracts and matching add-on.
- [x] 1.3 Historical: deployed 8fdf20c lacks changes; 4796 local passes.

## Phase 2: Events

- [x] 2.1 Prove actual-consumer duplicate/reorder and unfinished-event recovery. Broker-level evidence in `modules/sheets/tests/test_consumer_broker_delivery.py` (real RabbitMQ + real Mongo, 4 passed, stable in 10 runs): sequential duplicate, out-of-order arrival, retry-delay recovery, and concurrent duplicate delivery. The concurrent case first measured a real defect (2 appends, 1 marker under production prefetch); it is fixed by the atomic claim/lease in `odd/tasks/atomic-event-claim-lease.md` (S1+S2). Deployed-runtime evidence on the production image is still pending, as for 2.3.
- [x] 2.2 Measure real stages; export append never proves cell visibility.
  Broker-level stage evidence in `modules/sheets/tests/test_consumer_stage_telemetry_broker.py`
  over the shared disposable harness `modules/sheets/tests/_broker_harness.py` with the real
  `EventStageTelemetry` wired into the real handler (8 passed with 2.1): ordered
  `received_at <= fetched_at <= persisted_at`, all timezone-aware UTC; measured
  received->persisted latency 73-100 ms across observed runs; the measurement survives a worker
  restart (durable in Mongo, not process memory) and the retried event keeps its first receipt via
  the min-update. `visible_at` is asserted absent in every case: the export append is present while
  cell visibility is not claimed. `received -> visible` remains pending on the Sheets side
  (tasks 5.1/5.3).
- [x] 2.3 Prove old-order/stale/duplicate/isolation through consumer, guarded Mongo, dispatcher; Sheets pending.
- [ ] 2.4 Prove sustained event/inventory/query/history admission and pacing fairness.

## Phase 3: History

- [x] 3.1 RED: fixed 12-month monthly planner, ≤90-day chunks.
- [ ] 3.1a Acquire all resources through valid requests; never synthesize historical items.
- [ ] 3.1b Prove capacity-aware priorities, completed retention and honest admissions.
- [x] 3.1c Supervisor invokes backfill with failure isolation.
- [ ] 3.1d Complete acquisition lifecycle beyond BSON cutoff/admission fixes.
- [ ] 3.2 Persist real counts/errors/exclusions/cursors through queue and worker.

### Ordered Range Units

Follow [design](design.md): RED→GREEN→REFACTOR; `uv run pytest -q <listed test>`
and listed harness, verified disposable loopback Mongo 27028. Rollback assigned
additions only; no activation.

- [x] 3.2a Head model: `core/src/zeler_platform_core/models/sheets_history.py`; `core/tests/test_sheets_history_models.py` validates fields/phases/UTC. Runtime N/A: inert model.
- [x] 3.2b Head validator/index: real Mongo rejection/uniqueness, corrected schema inventory, full gates and authorized 650-line native closure verified.
- [x] 3.2c Receipt model in `core/src/zeler_platform_core/models/sheets_history.py`; `core/tests/test_sheets_history_models.py`: kind/hash/version invariants. Runtime N/A: inert model.
- [x] 3.2d Export receipt validator/index; `modules/sheets/tests/test_history_acquisition_schema.py`: real Mongo structural rejection/uniqueness.
- [x] 3.2e Fenced store `modules/sheets/src/zeler_sheets/history_acquisition.py`; `modules/sheets/tests/test_history_acquisition_store.py`: Mongo crash/replay/lease/byte bounds.
- [x] 3.2f Queue continuation; `modules/sheets/tests/test_history_continuation.py`: real queue progress/failure/quota accounting.
- [x] 3.2g Record primary-source cursor/expiry/subdivision/modification/retention evidence in `openspec/changes/zelerdata-pilot-reliable-sync/provider-evidence.md`; validate references. Runtime N/A: research.
- [ ] 3.2h Orders producer; durable subdivision/verification and publish-state handoff verified with real Mongo. Large known-ID budget reconciliation remains pending (`test_history_orders.py`, `test_history_order_subdivision.py`, `test_history_acquisition_store.py`).
- [x] 3.2i Bounded orders publisher; real Mongo tests cover guarded batches, newer events, operation loss, incomplete projections, invalidated prior proofs and atomic coverage/queue completion. The opt-in order worker now runs producer through finalization; runtime activation remains 3.3/6.3.
- [ ] 3.2j Shared question scan; admission, neutral cursor/manifests and bounded detail staging verified in `modules/sheets/tests/test_history_questions.py`. Twelve deterministic monthly subscription bindings share the verified pass; these are not coverage proofs. Actual HTTP normalization, publication/finalization and authoritative interval-proof subscriptions remain pending.

- [ ] 3.3 Orders worker resume/deduplication/interruption, producer-to-publisher handoff and final coverage verified with actual Mongo and gateway doubles. Full cross-resource runtime activation and twelve-month coverage remain pending.
- [ ] 3.4 Modification-page admission verified with exact [watermark−24h,cutoff) bounds, durable ID/version/hash deduplication and seller failure isolation. Actual modification HTTP traversal, durable cursor/watermark finalization and runtime wiring remain pending; creation-tail rereads are not this proof.
- [ ] 3.5 Local authorized-run advancement guard and bounded failure isolation verified with real Mongo/source-readback fixtures. Production's seven intervals still require authorized runtime repair/evidence; no API limitation is established by these tests.

## Phase 4: Formulas

- [ ] 4.1 Execute 52 positive/absent/filter/range cases. Local dispatcher execution recorded for all 52 in `formula-local-execution.md`; variant acceptance and actual Sheets evidence remain pending.
- [x] 4.2 Repair readers/projections preserving independent valid fields.
- [ ] 4.3 Run 52 simultaneously plus 35 regressions; distinguish local/Sheets evidence. Local cold-source batch of all 52 real handlers and 35 returns/history regressions passed; populated pilot/Sheets concurrency remains pending.

## Phase 5: Sheets

- [ ] 5.1 Execute bounded Apps Script recalculation without text changes. Manual bounded multi-tab refresh and executable local harness pass; real Google Sheets recalculation/visibility remains pending.
- [ ] 5.2 Verify authorized progress API/UI and nonduplicative retry. Local authorized progress snapshots, queue retry coalescence, Apps Script pending rendering, active `/sheets/sync-jobs` retry reuse—including unique-index collision handling—and the seller-scoped sync-job status read are verified; zeler-app UI and live Sheets evidence remain pending.
- [ ] 5.3 Prove automatic open/reopen refresh.
  Research and the separately authorized disposable-sheet experiment are in
  [apps-script-refresh-probe.md](apps-script-refresh-probe.md); no runtime
  recalculation or automatic reopen evidence is claimed.

## Phase 6: Acceptance

- [ ] 6.1 Rerun final gates after remaining corrections; latest local full suite: 5323 passed/9 skipped, zero failures/errors; Ruff/format/mypy 598 and Meli/schema pass. Runtime/Sheets acceptance and the eight protected cases skipped by this invocation remain unproven by this run; historical separate passes do not replace current evidence.
- [ ] 6.2 Prove actual-worker recovery/duplicates/interruption.
- [ ] 6.3 Complete deployment/add-on proposals and separate authorizations.
- [ ] 6.4 Warm-up, 90-minute observation, rounds 0/30/60.
- [ ] 6.5 Independent SDD verification/report; stop tests, retain normal sync.
