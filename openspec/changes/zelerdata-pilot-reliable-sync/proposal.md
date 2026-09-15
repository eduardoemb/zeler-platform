# Proposal: ZelerData Pilot Reliable Sync

## Intent

Make ZelerData dependable for the active pilot: all 52 active formulas must return
correct, useful results; notifications must refresh data immediately; the
recoverable 12-month history must be loaded and reconciled; and users must see
progress without editing formulas. This change replaces the incomplete
`zelerdata-live-formula-repairs` acceptance, without approving it retroactively.

## Scope

### In Scope

- Maintain a 52-formula acceptance matrix with purpose, inputs, resources,
  freshness, coverage, expected/observed results, evidence, and defects.
- Process notifications on arrival through the existing AMQP path and measure
  receipt, fetch, persistence, and visible-result stages separately.
- Add controlled reconciliation and resumable 12-month history acquisition,
  including recent changes to old operations.
- Repair recoverable data, especially blocking returns, without weakening
  seller isolation, source receipts, or freshness proofs.
- Provide Apps Script-compatible refresh and `/sheets/config` progress.
- Prove the full 52-formula catalog, regressions, recovery, and acceptance.

### Out of Scope

- New product UI, additional sellers, renamed formulas, new parameters, or a
  replacement frontend.
- Uploading historical data that Mercado Libre no longer retains.
- Inventing price, stock, quality, or competition history from current values.
- Unbounded quota increases, global TTL changes, or suppressing failures.
- Builds, deployments, migrations, add-on publication, or commits not separately
  authorized.

## Capabilities

### New Capabilities

- `zelerdata-pilot-reliable-sync`: reliable formula results, event freshness,
  recoverable history, integrity recovery, and visible Sheets synchronization.

### Modified Capabilities

None. No canonical OpenSpec capability is currently published.

## Approach

Extend the existing event consumer, durable recovery queue, guarded persistence,
and 90-day backfill boundaries. Add a resumable interval ledger around monthly
history chunks. Keep formula APIs read-only and source-gated. Use Apps Script
auto-refresh that only recalculates existing ZelerData formula cells.

## Affected Areas

| Area | Impact | Description |
| --- | --- | --- |
| `modules/sheets/` | Modified | Event pipeline, history orchestration, formulas, recovery, add-on |
| `../zeler-app` | Conditional | `/sheets/config` progress surfaces if contract changes |
| `infra/mongo/` | Conditional | Optional schemas/indexes for new durable artifacts |
| `docs/sheets/` | Modified | Matrix and verification evidence |

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| 52-formula demand exceeds budget | High | Measure attempts/retries; separate priorities and preserve honest gaps |
| Historical retention differs by resource | Medium | Verify per resource; retain only evidenced history |
| Background cell refresh is unreliable | Medium | Test open/reopen and bounded Apps Script refresh before claiming it |
| Returns blocker persists | Medium | Diagnose before writes; use focused guarded reconciliation |

## Rollback Plan

Keep each behavior unit independently reversible. Restore affected services from
compatible prior images, stop new backfill work without deleting acquired data,
and disable Apps Script refresh through its explicit setting.

## Dependencies

Pilot seller authorization, verified development Mongo, approved runtime for
production evidence, and separate deployment/add-on publication authorization.

## Success Criteria

- [ ] All 52 formulas have passing expected-result evidence and no unresolved self-defect.
- [ ] Event, reconciliation, inventory, and history lanes coexist without starvation.
- [ ] Recoverable history is complete, reconciled, resumable, and deduplicated.
- [ ] Returns and blocking integrity records are resolved or have auditable proven limitations.
- [ ] Sheets updates without manual formula edits; open/reopen behavior is verified.
- [ ] All repository gates, prior regressions, 52-formula rounds, and 90-minute observation pass.
- [ ] Final report records result, coverage, latency, capacity, versions, recovery, and operation state.
