# Design: ZelerData Read-Model Freshness Guards

## Technical Approach

Add a read-only status CLI and core marker helper. The CLI reports 16 reconciliation models plus `devoluciones`, synthesizes missing rows, and derives readiness from one Mongo query. The helper writes only `stale|failed`; reconciliation remains the sole `reconciled` authority. Readers, schemas, indexes, and runtime wiring remain unchanged.

## Scope Boundaries

This change excludes B1, blocked authority, campaigns, Secret Manager, credentials, OAuth, cookies, per-model productive writers, schema/index changes, runtime configuration, deploys, timers, schedulers, cloud changes, production access, and production writes. It authorizes no cloud or production operation.

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| Extend reconciliation CLI | Couples reads to writes. | Reject; create single-purpose `zelerdata_read_model_status.py`. |
| Duplicate inventory | Can drift. | Core owns all 17 names; a contract test compares reconciliation's inventory plus `devoluciones`. |
| Lease every model | Over-serializes markers. | Other models use transactions and indexed seller/model identity; only `devoluciones` retains its lease. |
| Return projected documents | Malformed values can leak. | Rebuild output from an inclusion projection and exact source allowlists; malformed evidence degrades. |

## Data Flow

    validated argv -> runtime DB -> one projected query -> 17 rows -> JSON/readiness
    validated helper -> non-devoluciones pair transaction OR devoluciones lease guard

## File Changes

| File | Action | Description |
|---|---|---|
| `core/src/zeler_platform_core/read_model_freshness.py` | Create | Inventory, allowlists, guarded writer. |
| `infra/operations/zelerdata_read_model_status.py` | Create | Projected status/readiness CLI. |
| `tests/test_read_model_freshness_writer.py` | Create | State, session, index, and lease tests. |
| `tests/operations/test_zelerdata_read_model_status.py` | Create | Status, actions, projection, and redaction tests. |
| `docs/sheets/zelerdata-formulas.md` | Modify | Cross-link the status command. |
| `docs/ops/zelerdata-seller-data-matrix-rollout.md` | Modify | Document unwired models and operator guidance. |

## Interfaces / Contracts

`python -m infra.operations.zelerdata_read_model_status --seller-id ID --confirm-approved-runtime [--readiness]`

Validation precedes environment/database access. Output is `{status, summary, read_models}`. Summary contains exactly `fresh`, `reconciled`, `stale`, `failed`, and `missing`. Rows expose contracted fields, `in_productive_window`, and `action_recommended`. Actions are exact: `none` for productive evidence; `await_lease` for missing `questions`; `re_run_reconcile` for every other missing, stale, failed, expired, or malformed row. Non-`none` actions block readiness. Readiness emits `{status: ready|degraded, blocking: [...]}` and returns nonzero when degraded or anomalous.

The query filters seller plus the 17-name allowlist and projects only `read_model`, state/window fields, `coverage_basis`, `source`, and `updated_at`; output never includes seller ID, `_id`, raw documents, connection data, or unknown fields. Productive evidence requires `fresh|reconciled`, a covering timestamp, required legacy basis, and unexpired `valid_until` for `devoluciones`.

The generic-writer source allowlist is exactly `{operator-action}`. Status may expose existing sources: `questions_event_persistence`, `zelerdata_read_model_reconcile`, `zelerdata_devoluciones_joint_reconcile`, `devoluciones_operation_acquire`, `devoluciones_operation_invalidate`, `devoluciones_event_relevance_unknown`, `devoluciones_relevant_order_event`, and `devoluciones_topology_rollback`. Any other source becomes `null` and the row becomes non-productive.

```python
async def set_read_model_marker_state(
    *, db: Any, seller_id: str, read_model: str, target_state: str,
    source: str, approved_runtime: bool,
    operation: DevolucionesOperationContext | None = None,
) -> None: ...
```

Validation accepts known models, `operator-action`, and `stale|failed` before DB access. Every non-devoluciones write transaction upserts exact `(seller_id, read_model)` identity with Mongo `$$NOW`. The unique `{seller_id: 1, read_model: 1}` index serializes all generic same-pair writers. A duplicate-upsert/write conflict gets one bounded exact-update retry; other errors propagate. Concurrent completed calls leave one valid requested state.

For `devoluciones`, a live caller-owned `DevolucionesOperationContext` is mandatory. `stale` delegates to `invalidate_devoluciones_readiness`. `failed` uses `guarded_devoluciones_write` to set `failed` and expire `fresh_until`/`valid_until`; absent, foreign, expired, or lost lease fails before marker mutation. The helper never acquires a parallel authority.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | 17 rows, counters, actions, windows, output keys | RED tests with fake collections and fixed time. |
| Unit | Invalid state/model/source/runtime and devoluciones states | Assert rejection before DB access and exact delegation. |
| Integration | Same-pair concurrency, reconciliation overlap, active/lost lease | Prove bounded retry, valid final state, and lease failure. |
| CLI | Full/readiness output, sanitized errors, repeatability | Call `main(argv)` twice; assert one read/run and zero writes. |

Negative cases include empty data, missing questions, malformed/duplicate rows, expired windows, PII fields, unsupported `reconciled`, absent transaction support, unknown source, and foreign/lost lease. Existing schema/index regression tests remain unchanged.

## Threat Matrix

The CLI is a process boundary but invokes no shell, subprocess, or VCS automation.

| Boundary | Applicability | Response / RED tests |
|---|---|---|
| Documentation-like paths | N/A: no classification/execution | None. |
| Git repository selection | N/A: no Git | None. |
| Commit state | N/A: no VCS mutation | None. |
| Push state | N/A: no push | None. |
| PR commands | N/A: no PR automation | None. |

## Migration / Rollout

No migration required and no runtime wiring is added. Rollback removes new files and documentation links. A marker already made non-productive stays fail-closed until authorized reconciliation; rollback never writes `reconciled` or deletes read-model data.
