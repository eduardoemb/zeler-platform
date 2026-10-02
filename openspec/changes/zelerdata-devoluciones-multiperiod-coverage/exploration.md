## Exploration: Cumulative certified DEVOLUCIONES coverage

### Current State

The user requires DEVOLUCIONES to preserve previously acquired, certified periods
while adding any earlier or later period. This is cumulative historical coverage,
not permission to certify gaps, fabricate unavailable history, or read dates that
have not happened. June must remain usable when August is acquired.

The selected artifact store is repository-local OpenSpec. `openspec/config.yaml`
and `openspec/specs/` are absent; there is no existing OpenSpec baseline for this
capability. This does not block exploration of a new capability. Do not substitute
another change's artifacts or create unrelated configuration. The original
`sdd/zeler-platform-greenfield/design.md` provides architectural context: tenant
isolation, strict schemas, UTC dates, referenced one-to-many relationships rather
than unbounded arrays, and gateway-mediated source acquisition. Its old Atlas and
retired-product references do not override current `AGENTS.md`.

Verified code behavior:

- `FormulaReadModelRepository.require_devoluciones_reconciled_range` reads one
  `seller:devoluciones` marker. A read snapshot contains one revision and proof
  fingerprint, rechecked after reading claims and linked orders.
- Quota finalization atomically completes the run and overwrites that marker with
  its exact interval and a 30-minute validity lease. No prior interval is retained.
- `renew_devoluciones_marker_if_proven` follows only the marker's current run ID.
  It certifies contiguous completed windows and persisted completeness; renewal
  is not a new upstream inventory scan and must not be described as one.
- Runs/windows retain authorization, bounds, release/source fingerprints and
  verification counts. `completed` alone has no independently expiring,
  invalidatable read certificate. Run `expires_at` limits acquisition authority,
  not the lifetime of historical data or a renewable certificate.
- `acquire_devoluciones_operation` and `guarded_devoluciones_write` serialize
  seller/scope writers with a lease, fence and transactions. Claim changes and
  relevant/unknown order changes withdraw the single readiness proof.
- Existing `retained_intervals` in the generic freshness schema lacks run identity,
  revision and fingerprints; the DEVOLUCIONES reader does not consume it. Both
  freshness and run validators reject unspecified fields. Current run indexes
  cover authorization identity, not bounded certificate lookup or renewal.

Operational context is historical evidence, not a new live check: the approved
August dry-run used 16 source attempts and found three complete projections. No
August run was admitted because the worker had renewed a valid June 1–11 UTC
exclusive proof. Replacing its marker would have removed June availability.
No production/source calls are part of this exploration; retain that boundary.

### Affected Areas

- `core/src/zeler_platform_core/devoluciones_runs.py` — immutable run identity,
  completed window receipts and separation of acquisition/readiness lifecycles.
- `core/src/zeler_platform_core/devoluciones_readiness.py` and
  `core/src/zeler_platform_core/read_model_freshness.py` — fenced invalidation,
  transaction boundaries and non-productive transitions.
- `core/src/zeler_platform_core/cli/export_schemas.py`,
  `infra/mongo/schemas/` and `infra/mongo/indexes/` — additive certificate schema
  and indexed, paginated lookup/renewal; validator rollout is a separate mutation.
- `infra/operations/zelerdata_read_model_reconcile.py` — finalization, exact
  readback, one-shot compatibility and migration certification.
- `modules/sheets/src/zeler_sheets/formulas/read_models.py` and
  `formulas/handlers_returns_histories_withdrawals.py` — covering proof selection,
  snapshot vector revalidation and duplicate-free canonical reads.
- `modules/sheets/src/zeler_sheets/devoluciones_runner.py`, `formulas/refresh.py`,
  `consumer.py`, `claim_projection.py` and `event_persistence.py` — fair renewal,
  dependency-aware invalidation and every claims/orders write path.
- `infra/operations/zelerdata_read_model_status.py` and
  `modules/sheets/src/zeler_sheets/zelerdata_freshness_alarm.py` — represent actual
  intervals, gaps and expired proofs without claiming a continuous min/max range.
- Existing formula, quota, runner and transaction tests; `docs/deploy.md` and
  the new change's rollout instructions — staged migration and rollback evidence.

### Approaches

1. **Optional certificate on each existing completed run.** Keep run/window
   receipts as provenance; add a separately versioned readiness subdocument with
   state, validity, revision, proof fingerprints and invalidation generation.
   - Pros: reuses existing identities and bounds; no new collection or unbounded
     seller array; independent proofs survive new admissions and finalizations.
   - Cons: acquisition and readiness share a document, so their lifecycles must
     remain explicit; needs validators/indexes and a policy for legacy one-shot
     markers that have no run. Legacy writes still require a safe rollout gate.
   - Effort: medium-to-high across shared lifecycle and reader boundaries.

2. **Dedicated interval-certificate collection referencing runs/windows.**
   - Pros: separates immutable acquisition receipts from mutable read validity;
     naturally supports multiple certified writer types and indexed scheduling.
   - Cons: another entity and migration, duplicated bounds needing enforced
     consistency, and more transactional joins. It does not remove invalidation
     or mixed-version hazards.
   - Effort: high; justified only if multiple provenance types cannot be safely
     represented by the existing run lifecycle.

3. **Extend the singleton marker's retained array or trust all completed runs.**
   - Pros: superficially smaller edit.
   - Cons: an unbounded array violates the original architecture; a fixed cap
     silently drops valid history. Current retained entries lack provenance;
     completed runs lack current validity and invalidation. Neither is a safe
     reader-only shortcut.
   - Effort: deceptively low; reject these shortcuts.

### Recommendation

Proceed to proposal using approach 1 as the minimal candidate; make the final
storage decision in design after enumerating legacy one-shot writers. Preserve
immutable run binding/fingerprints and authorization scopes. Do not implement a
new collection merely to avoid resolving lifecycle semantics.

The required contract spans the complete lifecycle:

1. Publish an independent certificate only after exact source-backed acquisition,
   completed contiguous windows and joint claim/order readback. Finishing a new
   run must not replace or revoke an unrelated valid certificate.
2. Select a finite proof vector covering the requested half-open UTC interval.
   Disjoint proofs can independently serve June and August, but cannot answer a
   query crossing their gap. Adjacent/overlapping proofs may compose only when
   their union covers every requested instant, preserving each provenance and
   revision; query canonical facts once to avoid double-counting.
3. Revalidate every selected proof after fact reads. Preserve fencing and detect
   concurrent invalidation, renewal, expiry, deletion or revision changes. A
   timestamp-only lease extension must not manufacture new acquisition evidence.
4. Invalidate affected proofs using claim membership and shared order dependencies,
   not order dates alone. Unknown impact must fail closed. Disjoint acquisition
   must retain unrelated certificates; temporary exclusion during genuinely
   conflicting writes is different from permanently discarding old coverage.
5. Renew all eligible certificates with indexed pagination and a bounded, fair
   schedule. Do not silently evict old periods or let later proofs starve older
   ones. Capacity and the 30-minute validity horizon need an explicit design gate.
6. Migrate valid June proof idempotently from its real completed run/windows and
   fresh joint readback. Never fabricate a successful run for a legacy marker;
   preserve its existing safe behavior until separately certified migration.
7. Stage additive schemas/indexes, compatible readers, writers/renewers, then
   activation. Keep the legacy marker only as a conservative compatibility view,
   not an invented global union. Old workers cannot invalidate new certificates:
   activation must exclude incompatible writers or couple a proven compatibility
   epoch to all certificates. Plain additive fields are not sufficient safety.
8. Rollback preserves canonical data and receipts. Before reverting writers,
   disable new certificate reads/writes safely; old code may expose only legacy
   coverage. State this degraded capability explicitly, never promise transparent
   multi-period rollback or delete source-backed facts to simulate it.

Verification must start RED and include real isolated Mongo replica-set tests:
June then August then earlier/later acquisition, gaps and UTC boundaries,
contiguous/overlapping deduplication, independent expiry/renewal, failed runs,
foreign sellers, missing provenance, shared-order changes, unknown event impact,
reader/writer races, lease takeover, stale-owner rejection, idempotent migration,
partial deployment and rollback. Reuse
`modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py`,
`test_devoluciones_runner.py`, `test_devoluciones_interval_membership.py`,
`tests/operations/test_zelerdata_read_model_reconcile.py` and
`tests/integration/test_devoluciones_fencing_transactions.py`.
Run all four root quality gates plus schema export and applicable gateway lint.
Local tests do not prove runtime migration or native Sheets behavior; eventual
authorized acceptance must show both intervals, a rejected gap and renewal beyond
30 minutes. No additional source acquisition is authorized by this document.

### Risks

- A minimal reader fallback can resurrect invalid receipts or read mixed revisions.
- The current renewal uses live completeness rather than byte-identical initial
  fingerprints; design must explicitly distinguish acquisition provenance from
  current row certification and audit legitimate changes rather than weaken it.
- Overlapping runs and shared orders invalidate a naive date-only dependency map.
- Unbounded proof growth needs scalable scheduling, not hidden retention limits.
- Mixed worker versions and rollback can leave certificates apparently valid
  while old writers mutate their facts. Activation safety is mandatory.
- Strict validators make field additions operationally significant; schema
  application, image builds and deployment remain separately authorized actions.
- This likely exceeds a small patch. The user explicitly accepted a single local
  delivery with `size:exception`; the resolved strategy is `exception-ok`. Tasks
  must still forecast scope and verification, without creating branches or PRs.
  This exception grants no commit, build or deployment authority.
- Dirty incident/lesson documents and the untracked Google diagnostic/test are
  unrelated work and must remain untouched by this change's implementation.

### Ready for Proposal

Yes. The user has authorized implementation of cumulative earlier/later coverage.
Explain that existing June data and availability will be preserved, August will
be added through certified acquisition, and unacquired gaps remain unavailable.
The behavior is clear enough for proposal; storage, legacy migration and rollout
interlocks belong in design, not an operator workaround. Missing OpenSpec global
config/baseline is recorded, not replaced. This exploration changes no executable
code, production state, acquisition budget or build/deployment authorization.
