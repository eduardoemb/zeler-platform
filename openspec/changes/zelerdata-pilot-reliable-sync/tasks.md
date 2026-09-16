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

- [ ] 2.1 Prove actual-consumer duplicate/reorder and unfinished-event recovery.
- [ ] 2.2 Measure real stages; export append never proves cell visibility.
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
- [ ] 3.2h Orders producer; durable subdivision/verification wiring and explicit empty-page observations verified; large known-ID budget reconciliation and publisher handoff remain pending (`test_history_orders.py`, `test_history_order_subdivision.py`, `test_history_acquisition_store.py`).
- [ ] 3.2i Bounded publisher; `modules/sheets/tests/test_history_publication.py`: guarded batch primitive verified with real Mongo newer events, operation loss, partial totals and unaffected interval reads. Producer publish-state handoff and final reconciliation/coverage certification remain pending; seeded prerequisites are not end-to-end evidence.
- [ ] 3.2j Shared question scan; admission, neutral cursor/manifests and bounded detail staging verified in `modules/sheets/tests/test_history_questions.py`. Twelve deterministic monthly subscription bindings share the verified pass; these are not coverage proofs. Actual HTTP normalization, publication/finalization and authoritative interval-proof subscriptions remain pending.

- [ ] 3.3 Orders staging worker resume/deduplication/interruption and retained prior data/proofs verified with actual Mongo and gateway doubles. Full cross-resource worker activation, publisher handoff and twelve-month coverage remain pending.
- [ ] 3.4 Modification-page admission verified with exact [watermark−24h,cutoff) bounds, durable ID/version/hash deduplication and seller failure isolation. Actual modification HTTP traversal, durable cursor/watermark finalization and runtime wiring remain pending; creation-tail rereads are not this proof.
- [ ] 3.5 Resolve production returns through guarded repair or evidenced API limitation.

## Phase 4: Formulas

- [ ] 4.1 Execute 52 positive/absent/filter/range cases.
- [x] 4.2 Repair readers/projections preserving independent valid fields.
- [ ] 4.3 Run 52 simultaneously plus 35 regressions; distinguish local/Sheets evidence.

## Phase 5: Sheets

- [ ] 5.1 Execute bounded Apps Script recalculation without text changes.
- [ ] 5.2 Verify authorized progress API/UI and nonduplicative retry.
- [ ] 5.3 Prove automatic open/reopen refresh.

## Phase 6: Acceptance

- [ ] 6.1 Rerun final gates after remaining corrections; intermediate 5036 passed/9 skipped, eight protected passes, Ruff/format/mypy 577 and Meli/schema pass.
- [ ] 6.2 Prove actual-worker recovery/duplicates/interruption.
- [ ] 6.3 Complete deployment/add-on proposals and separate authorizations.
- [ ] 6.4 Warm-up, 90-minute observation, rounds 0/30/60.
- [ ] 6.5 Independent SDD verification/report; stop tests, retain normal sync.
