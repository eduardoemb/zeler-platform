# Proposal: ZelerData Read-Model Freshness Guards

## Intent

Give operators a sanitized, fail-closed view of every ZelerData read-model marker and a generic way to mark non-productive states. No standalone status surface exists, and `failed` has no writer.

## Scope

### In Scope
- Add standalone `infra/operations/zelerdata_read_model_status.py` to report all 17 read-models, productive-window status, recommended actions, counters, and readiness without side effects.
- Add reusable `core/src/zeler_platform_core/read_model_freshness.py` support for guarded `stale` and `failed` writes; preserve the existing devoluciones lease authority.
- Add focused status/writer tests and documentation cross-links.
- Keep reconciliation as the sole authority for `reconciled` markers.

### Out of Scope
- B1, blocked-authority work, and campaigns.
- Secret Manager, credentials, OAuth, or cookies.
- Real deploys, timers, schedulers, cloud changes, production access, or production writes.
- New per-read-model writers, schema/index changes, and runtime configuration changes.

## Capabilities

### New Capabilities
- `zelerdata-read-model-freshness-guards`: Sanitized per-seller status/readiness reporting and guarded generic transitions to `stale` or `failed`.

### Modified Capabilities
None.

## Approach

Query `sheets_read_model_freshness` once with a strict projection, synthesize `missing` rows, and emit only contracted aggregate fields. Compute readiness from productive marker coverage. Put the shared writer in core, reject unsupported states or unapproved runtime before database access, use Mongo session safeguards, and delegate devoluciones invalidation to its existing lease-guarded path. Do not write `reconciled` outside reconciliation.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `infra/operations/zelerdata_read_model_status.py` | New | Read-only JSON/readiness CLI. |
| `core/src/zeler_platform_core/read_model_freshness.py` | New | Generic guarded stale/failed writer. |
| `tests/operations/`, `tests/` | New | Focused positive, negative, sanitization, and authority tests. |
| `docs/sheets/`, `docs/ops/` | Modified | Status command and unwired-model guidance. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Writer races with reconciliation | Medium | Session safeguards, strict authority boundaries, and focused concurrency/lease tests. |
| Status leaks seller data | Low | Fixed projection and output-shape tests exclude identifiers, raw documents, and PII. |
| Missing markers are misread as defects | Low | Deterministic `re_run_reconcile` guidance and explicit documentation. |

## Rollback Plan

Remove the standalone status CLI, core helper, tests, and documentation links. Existing reconciliation, marker schema/indexes, readers, and runtime remain unchanged.

## Dependencies

- Existing freshness collection, reconciliation operation, and devoluciones lease/invalidation contract.

## Success Criteria

- [ ] Status emits exactly one sanitized row for each of 17 read-models and degrades on every non-productive marker.
- [ ] Generic writes permit only `stale` or `failed`, fail closed before unsafe access, and never claim `reconciled` authority.
- [ ] Devoluciones transitions continue through the existing lease authority.
- [ ] No scheduler, per-model writer, schema/index, runtime, cloud, campaign, credential, or production change is introduced.
