# Design: Cumulative certified DEVOLUCIONES coverage

## Technical Approach

Introduce independently renewable interval certificates over existing canonical
claims/orders and acquisition evidence. Keep quota runs/windows as immutable
acquisition authority; a certificate is mutable permission to read those facts,
not another acquisition or a synthetic run. Finalization adds a certificate;
readers select a gap-free proof vector; all fact writers preserve unrelated
proofs and invalidate or atomically recertify affected ones.

Inputs: this change's `proposal.md`, validated `exploration.md`, and
`specs/devoluciones-multiperiod-coverage/spec.md` (14 requirements, 41 scenarios),
read and aligned before completing this design. There is no main OpenSpec
baseline/config to substitute. No new
external service or dependency is required. This design does not execute a
migration, source probe, build or deployment.

## Architecture Decisions

### Decision: Dedicated certificates, not fields that require every proof to be a quota run

**Choice**: Add `sheets_devoluciones_certificates`, with one document per source
publication identity. Reuse quota run/window receipts; support explicitly typed
joint-snapshot publications from the existing focused one-shot path.

**Alternatives considered**: Optional certificate fields on runs; expanded
singleton `retained_intervals`; querying every completed run directly.

**Rationale**: `_finalize_devoluciones_quota_run` has quota receipts, whereas
`write_complete_read_model_freshness_markers` also publishes legitimate
`zelerdata_devoluciones_joint_reconcile` snapshots without a quota run. Run-only
storage would require invented runs or permanent dual authority. A small separate
collection supports both real writer types with one lifecycle and indexed renewal;
it avoids unbounded arrays and leaves authorization/expiry semantics unchanged.
No per-seller collections or duplicate business facts are introduced.

### Decision: One proof lifecycle with typed, non-interchangeable provenance

**Choice**: Certificate kinds are `quota_run`, `joint_snapshot` and
`legacy_joint_snapshot`. Each has a strict evidence validator. A failed quota
proof cannot fall back to a legacy kind. A certificate's source receipt is
immutable; recertification updates separate current-state fields.

**Rationale**: A legacy accepted marker may be migrated while still valid and
matching its original fingerprint, but it cannot claim a newly executed source
scan. The current run expiry remains an acquisition deadline, never a readiness
expiry. Incomplete/failed runs never produce productive certificates.

### Decision: Snapshot-consistent reads plus current proof-vector validation

**Choice**: Read certificates, claims and linked orders in a Mongo snapshot read
transaction; then validate the selected proof vector and compatibility fence
against current state before returning. Query facts once for the requested range,
not once per certificate. Preserve public formula arguments and output columns.

**Rationale**: Overlap must not duplicate quantities, and multiple independent
proofs must not allow mixed revisions. A sorted interval-union algorithm proves
continuous coverage; taking minimum start/maximum end is insufficient.

### Decision: Keep the existing seller fence and add an old-writer tripwire

**Choice**: Extend the existing operation document with `coverage_mode`,
`coverage_epoch` and `coverage_ack_fence`. Modes are `legacy` and `active`;
missing fields mean legacy. Every compatible lease acquisition atomically sets
`coverage_ack_fence` to its new fence. An old writer advances `fence` without
acknowledging it, so active readers/renewers immediately fail closed.

Before a new writer acknowledges a previously mismatched fence, it invalidates
all certificates for that seller in the same transaction and increments the
coverage epoch. It must not conceal an intervening legacy mutation by merely
copying the new fence. Renewal never repairs this mismatch by itself.

**Rationale**: Old `$set` writers preserve unknown fields, so a persistent
`writer_version` value alone falsely appears compatible. Binding acknowledgement
to the existing monotonically increasing fence detects legacy participation
without another service or operation-control collection. Rollout still inventories
all writers; unfenced direct Mongo writes remain forbidden, not magically safe.

### Decision: Transactional impact handling, not date-only invalidation

**Choice**: Centralize certificate impact helpers beside existing core fencing.
For each mutation inspect prior/new canonical claim membership and shared-order
references. Invalidate affected certificates in the same transaction as the fact
write; preserve known unrelated certificates. Unknown impact invalidates all
seller certificates. Lease acquisition alone is not evidence that an unrelated
period changed; defer known-scope invalidation until its actual guarded write.

Known authoritative mutations may recertify an affected certificate atomically
when pre-write completeness and the exact membership/row transition are proven.
Otherwise retain it as stale with `needs_reacquisition`, never silently renew
from counts alone. No new upstream acquisition is launched by invalidation.

**Rationale**: Claim dates determine interval membership; order creation dates
cannot reveal every claim that references an order. New acquisitions must not
permanently discard unrelated coverage, while uncertainty cannot leave changed
facts readable. A temporary guarded exclusion of genuinely conflicting data is
not historical data loss.

### Decision: Fair bounded renewal with honest capacity failure

**Choice**: The existing worker refresh loop is the sole owner. Use indexed
`next_check_at, _id` ordering, at most 20 certificates and 30 seconds per cycle,
with a maximum 5-second per-certificate certification attempt. Stop before
starting work that cannot fit the remaining budget; use bounded Mongo operations.
Each renewal acquires the existing compatible seller lease without blanket
invalidation, certifies under its heartbeat, and CAS-publishes under that same
live fence; a lost or expired owner cannot renew. Successful renewal grants the
existing 30-minute validity window. Attempted
failures advance their next check by one refresh interval; unattempted records
retain their earlier due time and therefore cannot be starved by new records.

**Rationale**: Preserve every certificate, paginate rather than scan or evict,
and measure due/backlog/expiry counts. Arbitrarily many periods do not promise
infinite throughput within 30 minutes. If capacity is exhausted, keep the data
and certificate but report expired/unavailable and an operator-visible capacity
alarm. Do not extend validity without proof or create a second scheduler.
At activation and each health report compute the conservative revisit estimate
`ceil(eligible_count / sustainable_batch_count) * refresh_interval + batch_seconds
+ safety_margin` and compare it with 1,800 seconds. Derive sustainable batch
count from the smaller of the configured count limit and measured bounded
certification throughput; report unknown capacity if no measurement exists.
Use at least one refresh-interval jitter observation and a 60-second safety
margin rather than assuming 20 proofs fit the time budget. Insufficient capacity
is explicit degraded readiness, not a hidden certificate-count limit.

## Data Flow

```text
Normal authorized source acquisition
  -> canonical claim/order guarded writes + affected-proof invalidation
  -> exact snapshot revalidation / contiguous quota-window readback
  -> transaction: complete receipt + publish independent certificate

Formula request
  -> active-mode/fence check
  -> snapshot transaction: covering certificates -> claims -> linked orders
  -> current vector/epoch/fence/expiry check
  -> existing formula aggregation (each fact once)

Existing worker refresh cycle
  -> indexed due certificates (bounded fair batch)
  -> unchanged-proof or qualified-mutation certification
  -> CAS renewal or explicit stale/expired status
```

## Interfaces / Contracts

### Certificate document

Strict schema, UTC BSON dates, `schema_version=1`; no token, PII or raw payload.

```python
class Certificate:
    id: str                 # hash(kind, seller, immutable publication identity)
    seller_id: str
    kind: Literal['quota_run', 'joint_snapshot', 'legacy_joint_snapshot']
    date_from: datetime
    date_to: datetime        # exclusive
    source_identity: str    # real run ID or original operation attempt revision
    source_fingerprint: str | None  # only legacy migration may lack original hash
    acquisition_fingerprint: str    # immutable persisted acquisition proof
    acquired_at: datetime
    expected_count: int
    state: Literal['reconciled', 'stale', 'failed']
    revision: int           # changes for invalidation or certified fact changes
    current_membership_hash: str
    current_read_model_fingerprint: str
    certified_count: int
    validated_at: datetime
    valid_until: datetime
    next_check_at: datetime
    invalidation_reason: str | None  # bounded allowlist
    needs_reacquisition: bool
    coverage_epoch: int
    schema_version: int
```

- `quota_run`: require real same-seller completed run, exact same bounds,
  contiguous completed windows and their source/readback fingerprints. Store the
  composite acquisition fingerprint and verify it against receipts when renewing.
- `joint_snapshot`: publication occurs only on the existing authoritative
  collect/write/revalidate path, inside its live fence and publication-age guard;
  capture immutable operation identity, source fingerprint and exact verified
  snapshot evidence. Never create this kind from a generic count-only marker.
- `legacy_joint_snapshot`: migration accepts only an unexpired recognized
  `zelerdata_devoluciones_joint_reconcile` marker with nonempty revision/proof
  fingerprint and exact matching live canonical snapshot. Record its original
  proof as legacy provenance; do not invent a source fingerprint or new scan.
  Reject expired, uncertain or quota-sourced markers from this branch.
- `expected_count` and acquisition fingerprint remain historical evidence;
  `certified_count` and current fingerprint describe any subsequently qualified
  source-backed projection changes. Renewal cannot quietly replace either basis.
- Identical publication retries are idempotent; a conflicting publication identity
  fails closed rather than replacing receipt fields. No TTL deletion of history.

Indexes: unique `(seller_id, kind, source_identity)`; covering lookup
`(seller_id, state, date_from, date_to)`; due renewal
`(seller_id, next_check_at, _id)`. Query selectivity and real Mongo `explain` are
part of verification, not assumed from index names. Claims need indexed
`(seller_id, order_id, type, date_created)` for cross-period order impact; reuse
an existing equivalent index if present.

### Shared API

```python
publish_certificate(db, operation, verified_evidence, *, session) -> ProofRef
select_covering_proofs(db, seller, start, end, now, *, session) -> ProofVector
validate_proof_vector(db, vector, now) -> None  # raise safe unavailable on drift
mutate_with_certificate_impact(db, operation, impact, writer, *, session) -> Any
renew_due_certificates(db, seller, *, max_count=20, seconds=30) -> Summary
migrate_legacy_certificate(db, operation, marker, *, session) -> MigrationResult
```

`ProofRef` contains certificate ID, seller, bounds, revision, current fingerprint
and epoch; `ProofVector` also captures active mode and acknowledged operation
fence. A pure validity extension need not increment revision, but every invalidation
or certified fact change must. Current validation permits an unchanged proof with
an extended `valid_until`; it rejects changed mode/epoch/fence, missing proof,
changed facts/revision or current expiry. A global fence advance during a read
may conservatively fail that invocation; it does not erase unrelated certificates.

Coverage selection walks sorted candidate intervals and advances a cursor from
request start. Reject the first uncovered instant. Choose deterministic references
for overlap; retain all actual contributing identities, never materialize an
unproven envelope. Do not truncate candidates or facts to a hidden fixed count;
query/runtime budget exhaustion returns a safe unavailable result, not partial
success. Future requested bounds cannot be certified beyond acquired evidence.

### Canonical readback and qualified mutation

Reuse `read_devoluciones_claims_keyset`, linked-order keyset reads,
`verify_devoluciones_read_model` and `devoluciones_read_model_fingerprint`.
Certification validates identities and the joint order-line/return-quantity basis,
not just `count_documents`. Persist a deterministic sorted membership hash.
Unchanged membership plus the previously certified joint fingerprint is renewable.

For a known source-backed update, inside the existing guarded transaction:
validate the affected certificate's pre-write identity set/fingerprint; apply the
explicit mutation; derive its exact expected post-write identity set; validate
post-write canonical claims and linked order lines; then update current proof and
revision without altering acquisition history. This permits legitimate versioned
updates/additions and scoped authoritative removals, never arbitrary row changes.
If pre-state verification or bounded recertification cannot complete, keep the
business write guarded but mark its affected proof stale/needs reacquisition;
do not report a successful recertification. A stale proof may renew locally only
when its prior certified fingerprint/identity set is recovered or an exact
qualified transition was durably committed with its new proof. Counts alone are
not sufficient to recover unexplained drift. No unbounded mutation journal or
synthetic source receipts are introduced.

### Writer coverage map

| Existing path | Required integration |
|---|---|
| Quota window executor and focused one-shot snapshot writer | Source reads remain outside writes; claim/order writes use shared impact helper; quota/window finalization publishes typed proof without replacing others. |
| Generic `write_complete_read_model_freshness_markers` | Publish joint certificate only when existing authoritative inputs and exact snapshot verifier pass; non-claims markers unchanged. |
| `persist_claim_projection` | Canonical prior/new claim bounds, identity/version and linked order determine affected certificates; monotonic stale no-op does not invalidate facts. |
| `SheetsEventPersistence._persist_order` | Find all same-seller return claims referencing the order before/after the update, including claims outside the order date; preserve unrelated intervals. |
| `consumer.py` claim/relevant-order handling | Unknown relevance fails closed; existing source fetch and ACK/retry contracts unchanged; source-backed updates feed the normal impact helper. |
| `formulas/recovery_worker.py`, `history_publication.py` | Order writes flow through the same helper even when lease acquisition uses `invalidate_readiness=False`; no bypass through an external session. |
| `historical_meli_backfill.py`, `sheetseller_backfill.py` | Retain operation/fingerprint guards; direct claim/order writes must call impact handling, or conservatively invalidate all before writing. |
| Generic stale/failed marker operators | Propagate explicit non-productive state to affected certificates under the same operation authority. |
| One-off operational writers discovered during apply | Inventory all raw claim/order mutations; integrate them or fail active-mode preflight. Do not silently exclude an authorized writer from the safety contract. |

## File Changes

| File | Action | Description |
|---|---|---|
| `core/src/zeler_platform_core/devoluciones_certificates.py` | Create | Typed evidence/proof contracts, interval selection, indexes, publication and impact primitives. |
| `core/src/zeler_platform_core/devoluciones_readiness.py` | Modify | Mode/epoch/fence acknowledgement and legacy-writer detection. |
| `core/src/zeler_platform_core/read_model_freshness.py` | Modify | Explicit non-productive certificate transitions. |
| `core/src/zeler_platform_core/cli/export_schemas.py` | Modify | Strict certificate and operation-control fields. |
| `infra/mongo/schemas/sheets_devoluciones_certificates.json`, `infra/mongo/indexes/sheets_devoluciones_certificates.json` | Create | Generated validator and non-destructive indexes. |
| `infra/mongo/schemas/sheets_devoluciones_operations.json`, applicable claims index file | Modify | Compatibility fields and dependency lookup. |
| `modules/sheets/src/zeler_sheets/devoluciones_reconciliation.py` | Modify | Shared strong joint readback and source-evidence publication adapter. |
| `infra/operations/zelerdata_read_model_reconcile.py` | Modify | Additive quota/one-shot finalization, no singleton-only authority in active mode. |
| `infra/operations/devoluciones_certificate_migrate.py` | Create | Approved-runtime dry-run/write migration and explicit activation/rollback controls using ordinary Python entrypoint. |
| `modules/sheets/src/zeler_sheets/formulas/read_models.py`, `formulas/handlers_returns_histories_withdrawals.py` | Modify | Snapshot-session certified reads and proof-vector validation. |
| `modules/sheets/src/zeler_sheets/devoluciones_runner.py`, `formulas/refresh.py` | Modify | Bounded fair renewal and sanitized counters. |
| `modules/sheets/src/zeler_sheets/claim_projection.py`, `event_persistence.py`, `consumer.py` | Modify | Transactional dependency-aware invalidation/qualified recertification. |
| `modules/sheets/src/zeler_sheets/formulas/recovery_worker.py`, `history_publication.py`, `historical_meli_backfill.py`, `sheetseller_backfill.py` | Modify as required by writer audit | Ensure every fact path uses the same guard, including externally owned transactions. |
| `infra/operations/zelerdata_read_model_status.py`, `modules/sheets/src/zeler_sheets/zelerdata_freshness_alarm.py` | Modify | Interval status, expired/needs-source/capacity reporting. |
| Focused core/Sheets/operations tests and `tests/integration/test_devoluciones_fencing_transactions.py` | Create/Modify | Required RED and real transaction regressions. |
| `docs/deploy.md`, change-local verification/rollout notes | Modify/Create | Separate deployment, schema, migration and native acceptance gates. |

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Pure unit | Half-open UTC union, gap/overlap/adjacency, proof identity, provenance variants, safe errors | Deterministic clocks and fixtures; RED before implementation. |
| Writer/reader unit | Add June then August/earlier/later; failed run; stale source version; shared orders; no duplicate quantities; independent expiry | Existing formula, quota and runner suites plus focused certificate cases. |
| Real Mongo rs0 | Atomic receipt+certificate publication, strict validators, unique identity, concurrent readers/writers, lease takeover, stale owner, old-writer fence mismatch, idempotent migration | Isolated verified test URI only; fake DB tests cannot establish transaction safety. |
| Scheduling | Many due proofs, budget exhaustion, failed proof fairness, no eviction, capacity alarm and recovery | Fake monotonic clock plus indexed Mongo query verification. |
| Compatibility | Legacy-only, active new API/worker, old worker acquisition after activation, old API compatibility, downgrade and interrupted migration | Explicit mixed-version behavioral fixtures; no implied safety from unknown-field preservation. |
| Gates | Whole-repository regressions, schema parity and typing | `uv run pytest`, Ruff check/format, full mypy; schema export `--check`; applicable direct-Meli lint. |
| Runtime acceptance | Both original June and newly authorized August formulas; rejected gap; independent renewal beyond 30 minutes; ordinary service behavior | Separate approved VM/operator and native Sheet checks; not performed by local tests. |

Use the prepared isolated runner only once implementation/tests are authorized;
do not run local tests with a production Mongo target. No source calls are required
for deterministic implementation verification.

## Threat Matrix

N/A — no new routing, shell construction, subprocess launch, VCS/PR automation,
executable-file classification or external process-integration boundary. The
migration entrypoint uses existing approved-runtime Python/DB patterns, no shell
or dynamic command execution. Authorization, tenant isolation, bounded queries,
secret redaction and transaction races are covered above. Deployment commands
remain operator runbook actions, not a new subprocess implementation.

## Migration / Rollout

1. **Prepare, no activation:** build/test code locally; enumerate every canonical
   writer; capture source/digests and compatibility coverage. Publish images,
   apply additive validators/indexes and deploy only with separate approval.
2. **Compatible code in legacy mode:** API preserves existing marker behavior;
   new workers acknowledge fences but do not expose new authority. Existing June
   proof stays untouched. New code is installed on all persistent and one-shot
   writer entrypoints before activation. No separate timer is enabled.
3. **Dry-run migration:** inventory same-seller completed quota runs and current
   valid joint marker; verify receipts, exact ranges, joint facts and fingerprints.
   Reject invalid quota evidence without legacy fallback. Output counts/ranges/
   refusal codes only; do not print facts or credentials.
4. **Authorized certificate migration:** hold existing seller lease, recheck the
   dry-run evidence and publish idempotently under transaction. A valid June
   quota proof receives a quota certificate. Missing/expired legacy one-shot
   provenance stays unavailable until separately reacquired; no synthetic run.
5. **Activate:** under the lease verify all intended existing productive ranges
   have valid certificates, record active mode and a new epoch, bind certificates
   to that epoch and acknowledge the current fence atomically. Require the
   operator's verified writer inventory; readers fail closed on future mismatch.
6. **Acquire another interval:** only after activation and its separate source
   authorization; normal finalizer publishes a second certificate while preserving
   existing valid ones. Observe both after the 30-minute original validity horizon.
7. **Rollback:** first switch mode to legacy under a compatible lease and
   invalidate new certificate authority by epoch change. Preserve the existing
   genuine legacy singleton as-is; do not automatically select/project a new
   certificate into it. Its old reader may offer a narrower interval or no
   readable interval if that marker is stale/expired. Report that downgrade and
   retain every period's facts/receipts/certificates. Only then revert approved
   images; retain expanded schemas. Re-activation requires fresh verification,
   not reusing an old epoch. This conservative implementation adjustment avoids
   manufacturing legacy source/revision semantics from a differently typed proof.

A legacy valid marker is a migration input, not a forever fallback in active mode.
Mixed mode cannot claim multiple productive periods from a legacy singleton. The
migration/activation command defaults to dry-run, requires explicit approved
runtime and separate write/activation confirmation, and has no upstream client.
It must reject scope/epoch drift and an active competing lease, and never perform
an implicit production write just because schema drift was detected.

## Open Questions

None blocking design. The parallel specification has been read and aligned,
including mutation recertification, honest capacity degradation and distinct
quota versus non-run provenance. Its 14 requirements and 41 scenarios remain
the acceptance contract. Exact index reuse is resolved from the existing schema
inventory during implementation without changing these contracts. The user
accepted `delivery_strategy=exception-ok` / `size:exception`; no branch, PR,
commit, build or deployment follows from that exception. Existing unrelated
incident/lesson and Google diagnostic files must remain byte-identical.
