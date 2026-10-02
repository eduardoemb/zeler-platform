# Proposal: Cumulative certified DEVOLUCIONES coverage

## Intent

Allow DEVOLUCIONES to retain all previously acquired, valid historical coverage
when acquiring another earlier or later period. The current singleton readiness
marker makes a successful August reconciliation remove June's readable coverage,
even though June's canonical data and completed run survive. The user explicitly
requires both periods, not a choice of which one to lose.

Replace this single-period certification limitation with independently renewable,
source-backed interval proofs across the complete reader/writer lifecycle. A
request crossing an unacquired gap must remain unavailable; retaining data does
not certify its completeness. Future acquisitions may extend the timeline after
their dates occur, but this change never invents future observations.

## Scope

### In Scope

- Independent certificates linked to existing acquisition receipts, preserving
  run identity, seller isolation, source provenance and exact half-open UTC bounds.
- Additive finalization and safe legacy proof migration that preserve June while
  adding August or any other certified earlier/later interval.
- Read selection and post-read snapshot revalidation across a covering set of
  proofs, including gap rejection and duplicate-free overlapping/adjacent ranges.
- Independent validity, fair bounded renewal, and fenced invalidation for claim
  changes, shared-order dependencies and unknown-impact events.
- Strict schemas, indexed lookup/renewal, meaningful interval-level operational
  status, compatibility activation and explicit rollback behavior.
- TDD, real isolated Mongo transaction tests, regression gates, and a documented
  separately authorized production migration/acceptance procedure.

### Out of Scope

- Google OAuth/billing/append repair and the existing unrelated diagnostic files.
- Rebuilding unavailable history for other formulas or claiming unacquired gaps.
- New sellers, authorization scopes, public formula signatures or replacement UI.
- Running another source dry-run or admitting an August run during implementation.
- Automatic backfill of every possible date, unlimited upstream calls, modified
  quota budgets, manual production state patches, or retrying failed authorized
  acquisitions outside their existing authority.
- Commits, branches, PRs, image builds, deployment, production validator changes,
  cleanup or DLQ replay without their separate explicit authorizations.

## Capabilities

### New Capabilities

- `devoluciones-multiperiod-coverage`: Cumulative certified interval publication,
  proof-based reads, renewal/invalidation, migration and safe runtime compatibility
  for DEVOLUCIONES, without losing valid periods or certifying gaps.

The specification phase will create
`specs/devoluciones-multiperiod-coverage/spec.md` under this change. Repository-local
OpenSpec is the selected store; `openspec/config.yaml` and `openspec/specs/` do not
currently exist. No existing capability baseline is invented or substituted.

### Modified Capabilities

None. Existing executable behavior changes, but there is no corresponding main
OpenSpec capability baseline to modify.

## Approach

Use the source-grounded [exploration](exploration.md). Prefer an optional, typed
readiness certificate on each existing completed run as the smallest robust
storage candidate. Keep acquisition authorization/expiry immutable and separate
from renewable read validity. A dedicated certificate collection remains a design
alternative if enumerated non-run writer/migration requirements justify it;
neither option permits synthetic completed runs or a growing singleton array.

Finalization publishes the new certificate atomically with its completed run,
without replacing unrelated certificates. Readers select exact covering proofs,
retain their identity/revision vector, read canonical claims and linked orders
once, then revalidate all selected proofs. An interval union is accepted only if
every requested instant is covered; a min/max envelope is insufficient.

Retain the existing seller/scope lease, fencing and transactional guards. Identify
affected proofs through claim membership and shared-order dependencies, rather
than order dates alone. Unknown impact fails closed; unrelated valid coverage
must not be permanently discarded by disjoint acquisitions. Renewal recertifies
current persisted facts under a bounded fair schedule; it does not claim a new
upstream scan or new historical coverage.

Migration validates existing completed runs/windows and joint readback before
issuing certificates. Legacy one-shot proofs must retain their safe behavior
until a supported migration proves their provenance. Rollout activates the new
reader only when all relevant writer paths can maintain/invalidate its proofs.
The old marker may remain a conservative compatibility view, never an invented
all-period union. Design must resolve compatibility, legacy writers and bounded
renewal capacity before implementation.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `core/src/zeler_platform_core/devoluciones_runs.py` | Modified | Receipt-linked certificate lifecycle without changing run binding. |
| `core/src/zeler_platform_core/devoluciones_readiness.py`, `read_model_freshness.py` | Modified | Transactional invalidation, fencing and compatibility guards. |
| `core/src/zeler_platform_core/cli/export_schemas.py`, `infra/mongo/schemas/`, `infra/mongo/indexes/` | Modified | Strict additive certificate contract and bounded query access. |
| `infra/operations/zelerdata_read_model_reconcile.py` | Modified | Non-destructive finalization and certified legacy migration. |
| `modules/sheets/src/zeler_sheets/formulas/read_models.py`, `formulas/handlers_returns_histories_withdrawals.py` | Modified | Multi-proof coverage and snapshot revalidation. |
| `modules/sheets/src/zeler_sheets/devoluciones_runner.py`, `formulas/refresh.py` | Modified | Fair renewal of every eligible proof. |
| `modules/sheets/src/zeler_sheets/consumer.py`, `claim_projection.py`, `event_persistence.py` | Modified | Claims/orders dependencies and complete write-path invalidation. |
| `infra/operations/zelerdata_read_model_status.py`, `modules/sheets/src/zeler_sheets/zelerdata_freshness_alarm.py` | Modified | Truthful period/gap/expiry reporting. |
| Core/Sheets/operations tests and `tests/integration/test_devoluciones_fencing_transactions.py` | Modified/New | Domain, concurrency, migration and compatibility regressions. |
| This change's artifacts and applicable rollout documentation | New/Modified | Scoped activation, readback, rollback and acceptance instructions. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Reusing a completed run as current proof without invalidation | High | Separate certificate state/validity and validate provenance/current facts. |
| Shared orders or concurrent writes invalidate multiple periods | High | Dependency-aware guarded invalidation and proof-vector revalidation; unknown impact fails closed. |
| Old writers change facts without invalidating new certificates | High | Tested mixed-version activation barrier; do not rely on additive fields alone. |
| Growth starves older proofs or silently drops coverage | Medium | Indexed pagination, fair renewal, measured capacity and no hidden history eviction. |
| Migration manufactures coverage or breaks legacy one-shot reads | Medium | Idempotent source-receipt validation; preserve safe fallback until proven migration. |
| A union masks gaps or double-counts rows | Medium | Half-open coverage algorithm, immutable proof references and canonical deduplicated reads. |

## Rollback Plan

Rollout must be additive and staged: validators/indexes, compatible read/write
code, certified migration, then explicit activation. Preserve prior image digests
and legacy compatibility behavior; record runtime mode and migration checkpoints.

Before reverting to an old writer, stop new certificate publication and disable
new-certificate reads using the designed compatibility barrier. Prevent stale
new proofs from remaining readable while old code mutates their facts. Preserve
canonical claims/orders, completed runs, windows and additive certificate data;
do not delete business facts or rewind provider state. Retain expanded validators
unless a separately verified downgrade is needed. Old code may expose only the
legacy certified interval: report this degraded capability rather than promising
transparent multi-period rollback. Resume only after mode, writer compatibility,
coverage and lease safety are verified.

## Dependencies

- Existing gateway-mediated acquisition, normal authorization budgets and Mongo
  replica-set transactions; no additional external service or library is assumed.
- Design must inventory quota, one-shot, bootstrap, event and recovery writers
  before declaring invalidation complete.
- Isolated development/test Mongo for integration tests; production Mongo remains
  restricted to the approved VM/runtime and is not part of implementation tests.
- The user accepted a single local delivery with `size:exception`:
  `delivery_strategy=exception-ok`. Tasks still forecast scope and gates; this
  grants no commit/branch/PR/build/deployment authority. Review mode remains off.
- Preserve unrelated dirty incident/lesson documents and Google diagnostic/test
  files. Their current contents are not part of this implementation's work unit.

## Success Criteria

- [ ] June remains certified/readable after August finalizes; adding an earlier
  or later acquired interval preserves both. No singleton replacement tradeoff.
- [ ] Disjoint ranges are independently readable, but queries crossing a gap
  fail closed. Adjacent/overlapping coverage is exact and never double-counted.
- [ ] Every productive result has seller-scoped source/run provenance and a
  proof vector that remains valid across its canonical fact reads.
- [ ] Renewal extends each valid certificate beyond the original 30-minute
  horizon without inventing acquisition evidence or starving older periods.
- [ ] Mutations, unknown-impact events, expiry and lost leases cannot leave
  affected stale facts certified or let an old owner republish readiness.
- [ ] Migration is idempotent, preserves valid legacy coverage and refuses
  incomplete, foreign or fabricated receipts. Mixed-version/rollback tests pass.
- [ ] RED evidence precedes implementation; focused and isolated Mongo tests,
  all four root gates, schema export and applicable direct-Meli lint pass, with
  pre-existing failures distinguished from regressions.
- [ ] Separately authorized runtime acceptance verifies both native periods,
  rejects their unacquired gap, observes renewal beyond 30 minutes and records
  dependency readiness. Local test success is not reported as this live proof.
