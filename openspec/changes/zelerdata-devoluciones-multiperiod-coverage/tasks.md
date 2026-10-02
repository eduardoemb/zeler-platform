# Tasks: Cumulative certified DEVOLUCIONES coverage

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated authored changed lines | 1,800–3,500; generated schemas counted separately |
| 400-line budget risk | High |
| Chained PRs recommended | Yes, as an optional review decomposition; not authorized Git work |
| Suggested split | Contracts/fencing → publication/writers → reads/renewal → migration/acceptance |
| Delivery strategy | exception-ok |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

The maintainer explicitly accepted one local delivery with `size:exception`.
Work units below organize implementation and evidence, not commits or PRs. No
branch/worktree, commit/push, build, deployment or production mutation is implied.
Review mode is off. Preserve the four unrelated files in the checksum manifest.

### Suggested Work Units

For focused tests, `H` below means the already prepared command:
`bash /tmp/zeler-focused-tests-20261002-multiperiod.sh`. It executes pytest in the
owned isolated Linux runner with disposable rs0 Mongo/RabbitMQ, never inherited
production targets. Inspect readiness before use; do not start another runner
merely because a tool observation times out.

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Certificates, schemas, fence handshake | Local unit 1 under size exception | `H core/tests/test_devoluciones_certificates.py tests/integration/test_devoluciones_fencing_transactions.py -q` | Real rs0 strict validators, concurrent lease takeover and legacy-fence mismatch | Additive storage/guard code stays inactive in legacy mode; no data deletion. |
| 2 | Additive publication and all fact writers | Local unit 2 | `H tests/operations/test_zelerdata_read_model_reconcile.py modules/sheets/tests/test_devoluciones_operation_composition.py modules/sheets/tests/test_event_persistence.py -q` | Real transaction abort, shared-order and unknown-impact cases | Disable certificate publication in legacy mode before removing integrations; retain canonical facts. |
| 3 | Proof-vector reads and renewal | Local unit 3 | `H modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py modules/sheets/tests/test_devoluciones_runner.py -q` | Snapshot reader/writer race and fake-clock fair renewal with real indexed queries | Legacy read mode before any old writer returns; never keep new proofs active under incompatible writes. |
| 4 | Migration, operational status and acceptance | Local unit 4 | `H tests/operations/test_devoluciones_certificate_migrate.py tests/integration/test_devoluciones_multiperiod.py -q` | Isolated valid June migration + August acquisition fixtures, no source calls | Epoch-invalidated new read authority; preserve receipts/certificates/data and declare singleton downgrade. |

The runtime harness in this table is local verification. Production migration,
source acquisition and native Sheet acceptance remain separately authorized and
are documented, not executed, by the tasks below.

## Phase 1: Baseline, core contracts and guarded ownership

- [x] 1.1 Read `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/proposal.md` (read-only), `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/design.md` (read-only) and `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/specs/devoluciones-multiperiod-coverage/spec.md` (read-only); record their 14 requirements/41 scenarios and baseline test results in `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`. Verify the four unrelated-file hashes against the existing external manifest without modifying those files.
- [x] 1.2 RED: create `core/tests/test_devoluciones_certificates.py` covering exact half-open coverage, gaps, adjacency/overlap, reversed/empty/future-unacquired bounds, foreign sellers, immutable identity, and distinct quota/joint/legacy provenance; capture failures before introducing production behavior.
- [x] 1.3 GREEN: create `core/src/zeler_platform_core/devoluciones_certificates.py` with typed evidence/proof references, strict eligibility, deterministic identities, source/current proof separation and finite gap-free selection. Run 1.2 to green; reject completed-only or count-only readiness.
- [x] 1.4 RED: extend `tests/integration/test_devoluciones_fencing_transactions.py` for active mode, new fence acknowledgements, legacy fence increments, mismatch refusal, interrupted ownership and stale-owner certificate publication; ensure tests run against real verified rs0, not skipped mocks.
- [x] 1.5 GREEN: update `core/src/zeler_platform_core/devoluciones_readiness.py` with mode/epoch/ack-fence fields and transactional mismatch invalidation before a new acknowledgement. Preserve legacy behavior by default; no automatic production activation. Run 1.4 and existing fencing tests to green.
- [x] 1.6 RED→GREEN: add validator/index contract tests in `core/tests/test_devoluciones_certificates.py` and relevant schema tests; update `core/src/zeler_platform_core/cli/export_schemas.py`, generate `infra/mongo/schemas/sheets_devoluciones_certificates.json` and updated operation schema, and add `infra/mongo/indexes/sheets_devoluciones_certificates.json`. Test strict unknown-field rejection, bounds/provenance checks and unique identity in isolated Mongo.
- [x] 1.7 REFACTOR: consolidate pure validation, clock injection and sanitized errors in `core/src/zeler_platform_core/devoluciones_certificates.py`; rerun core/transaction tests and focused Ruff/mypy without altering the public formula contract.

## Phase 2: Additive publication and complete writer impact

- [x] 2.1 RED: extend `tests/operations/test_zelerdata_read_model_reconcile.py` for June then August, earlier/later publication, failed/partial run, exact quota-window proof, idempotency, publication abort and genuine one-shot certificates without synthetic runs. Prove old singleton behavior fails the additive cases.
- [x] 2.2 GREEN: update `infra/operations/zelerdata_read_model_reconcile.py` and `modules/sheets/src/zeler_sheets/devoluciones_reconciliation.py` so quota finalization and authoritative joint-snapshot publication use shared certificate APIs inside their existing fence/transaction/age checks. Preserve source call budgets and immutable receipt provenance; no new provider scan requirement.
- [x] 2.3 RED: add shared-order and claim-membership cases to `modules/sheets/tests/test_devoluciones_operation_composition.py` and `modules/sheets/tests/test_event_persistence.py`: claim moves June→August, old order supports both, stale monotonic no-op, unknown impact, and a proven unrelated certificate surviving a disjoint acquisition failure.
- [x] 2.4 GREEN: implement transactional impact determination and safe invalidation in `core/src/zeler_platform_core/devoluciones_certificates.py`, `modules/sheets/src/zeler_sheets/claim_projection.py` and `modules/sheets/src/zeler_sheets/event_persistence.py`. Resolve affected proofs through prior/new claims and order references, not order dates. Add or reuse an equivalent index in `infra/mongo/indexes/claims.json` after checking its actual contents.
- [x] 2.5 RED→GREEN: test exact qualified pre/post mutation recertification versus unexplained drift in `modules/sheets/tests/test_devoluciones_operation_composition.py`; implement joint identity/fingerprint checks in `modules/sheets/src/zeler_sheets/devoluciones_reconciliation.py` and the core helper. Preserve original acquisition proof; if bounded verification cannot prove a transition, keep affected readiness stale/needs reacquisition rather than renewing by counts alone.
- [x] 2.6 RED→GREEN: wire claim/relevant-order and unknown-relevance paths in `modules/sheets/src/zeler_sheets/consumer.py` and explicit stale/failed operations in `core/src/zeler_platform_core/read_model_freshness.py`; extend `modules/sheets/tests/test_consumer_error_handling.py` and marker tests. Preserve the recently deployed ACK/retry/404 behavior and existing authentication contracts.
- [x] 2.7 Audit actual raw claims/orders writers using source search and record the complete path inventory in `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`; for every path identify transaction owner, impact guard and compatibility behavior. An unguarded path blocks active-mode acceptance, not silently shrinks scope.
- [x] 2.8 RED→GREEN: cover externally owned transactions and integrate `modules/sheets/src/zeler_sheets/formulas/recovery_worker.py`, `modules/sheets/src/zeler_sheets/history_publication.py`, `modules/sheets/src/zeler_sheets/historical_meli_backfill.py` and `modules/sheets/src/zeler_sheets/sheetseller_backfill.py` where the audit requires it; extend their existing test files. Known-unrelated writes retain certificates; unsupported impact fails closed before facts can escape the contract.
- [x] 2.9 REFACTOR: remove duplicated impact/proof logic across the Phase 2 files without adding parallel authority; rerun all affected writer/regression tests and real transaction-abort cases.

## Phase 3: Snapshot-certified formula reads

- [x] 3.1 RED: extend `modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py` for June/August separate reads, cross-gap failure, adjacency, overlap deduplication, distinct claims sharing one order, unchanged output columns and seller isolation. Add deletion/expiry/revision/compatibility changes between fact reads and final validation.
- [x] 3.2 GREEN: update `modules/sheets/src/zeler_sheets/formulas/read_models.py` with snapshot-session certificate/fact reads and a deterministic proof vector; update `modules/sheets/src/zeler_sheets/formulas/handlers_returns_histories_withdrawals.py` to aggregate each canonical claim once and validate the whole vector before returning. Legacy mode remains the old safe path.
- [x] 3.3 RED→GREEN: create `tests/integration/test_devoluciones_multiperiod.py` with real Mongo snapshot races involving claims, shared orders, certificate deletion, validity-only extension, expired/lost owner and fence/epoch transition. Verify no mixed snapshot escapes; compatible validity extension does not invent new source evidence.
- [x] 3.4 REFACTOR: share date/provenance/vector validation without introducing hidden record limits; rerun formula API and returns regressions. Query/runtime budget exhaustion must be unavailable, never a truncated productive result.

## Phase 4: Renewal, scale and operational status

- [x] 4.1 RED: extend `modules/sheets/tests/test_devoluciones_runner.py` for independent expiry, genuine quota versus non-run provenance, missing linked orders, unchanged joint fingerprints, stale/unexplained membership, expired acquisition authority, and renewal under a replaced lease.
- [x] 4.2 GREEN: update `modules/sheets/src/zeler_sheets/devoluciones_runner.py` to renew real independent proofs under a current compatible lease, using strong identity/joint readback. Keep immutable acquisition fingerprints/bounds separate from current facts and validity; never reauthorize a run or call the provider from renewal.
- [x] 4.3 RED→GREEN: add fake-clock fairness/capacity tests to `modules/sheets/tests/test_devoluciones_runner.py` and wiring tests to `modules/sheets/tests/test_zelerdata_refresh.py`; implement indexed due ordering with the design's 20-certificate/30-second batch and 5-second individual budget in `modules/sheets/src/zeler_sheets/devoluciones_runner.py` and `modules/sheets/src/zeler_sheets/formulas/refresh.py`. Unattempted older work stays ahead; no silent eviction or invented lease extensions on overload.
- [x] 4.4 RED→GREEN: extend status/alarm tests and update `infra/operations/zelerdata_read_model_status.py` plus `modules/sheets/src/zeler_sheets/zelerdata_freshness_alarm.py` to expose certified intervals, gaps, expiry, needs-reacquisition, due backlog and measured/unknown capacity. Calculate the explicit revisit estimate against the 1,800-second validity horizon; no unlimited-throughput promise.
- [x] 4.5 Verify index use, batch bounds, overload expiry and recovery in `tests/integration/test_devoluciones_multiperiod.py`; record actual local explain/batch evidence in `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`. Do not add a second timer or change global provider budgets.

## Phase 5: Validated migration, activation and rollback

- [x] 5.1 RED: create `tests/operations/test_devoluciones_certificate_migrate.py` for valid June quota migration twice, interrupted migration, wrong seller/bounds, missing/incomplete windows, orphaned/expired marker, typed genuine legacy-joint proof, invalid quota rejected without legacy fallback, and unchanged canonical data.
- [x] 5.2 GREEN: create `infra/operations/devoluciones_certificate_migrate.py` using existing approved-runtime DB patterns and shared core proof helpers. Default to read-only dry-run; writes and activation require explicit flags. Validate current joint facts against genuine receipts/fingerprints; never synthesize source scans, windows or completed runs from stored row counts.
- [x] 5.3 RED→GREEN: test activation with unmigrated productive coverage, a competing lease, mismatched epoch/fence and old writers; implement guarded activation in the migration module and core helper. A valid legacy one-shot proof must retain safe legacy behavior until its supported provenance-preserving transition succeeds.
- [x] 5.4 RED→GREEN: extend migration and real Mongo tests for rollback to a genuine singleton compatibility view, old writer mutation after rollback, and reactivation requiring fresh validation. Implement mode/epoch withdrawal before incompatible writes; preserve all facts, receipts and certificate documents, explicitly reporting reduced readable coverage.
- [x] 5.5 REFACTOR: verify migration retry/idempotency and redaction, remove duplicate CLI/core checks while keeping explicit authorization gates. Add no subprocess, arbitrary shell, new external system or automatic production activation.

## Phase 6: Integrated verification and delivery record

- [x] 6.1 Complete a requirement/scenario traceability table in `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`, mapping all 14 requirements/41 scenarios to actual tests, unresolved work or unperformed runtime acceptance. Record each RED→GREEN command and result; do not infer tests passed from their existence.
- [x] 6.2 Run the complete focused work-unit suite through the isolated harness and real rs0 suite; fix regressions and rerun invalidated evidence. Verify server PRIMARY/health and that transaction tests actually executed rather than skipped.
- [x] 6.3 Coordinate with the parent for one final root validation when code is stable: complete pytest with isolated Mongo/RabbitMQ, protected rs0 cases separately without ambient MONGO_URI, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, schema export `--check`, and direct-Meli lint. Record full commands/results in `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`; distinguish pre-existing failures from regressions, never reduce gate scope.
- [x] 6.4 Update `docs/deploy.md` and create `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/rollout.md` with exact module/flags, separate schema/build/deploy/migration authorization, writer inventory, compatibility-mode sequence, prior immutable image capture, capacity checks, conservative rollback and native June/August/gap/>30-minute acceptance. These are instructions only; perform no production step.
- [x] 6.5 Perform final artifact/link/coherence validation and unchanged-file checksum verification; update only completed tasks and `openspec/changes/zelerdata-devoluciones-multiperiod-coverage/apply-progress.md`. Report local implementation/gates separately from unperformed deployment, migration and native evidence. Do not archive, commit or mark the overall runtime goal achieved.

## Exact Local Verification Commands

Focused commands are in the work-unit table. With the existing verified runner:

```bash
bash /tmp/zeler-focused-tests-20261002-multiperiod.sh \
  core/tests/test_devoluciones_certificates.py \
  tests/integration/test_devoluciones_fencing_transactions.py \
  tests/integration/test_devoluciones_multiperiod.py -q

bash /tmp/zeler-focused-tests-20261002-multiperiod.sh

docker --context colima-zelerdata-tests-20261002 exec zeler-diag-runner-20261002 \
  sh -lc 'cd /workspace && uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy . && uv run --no-sync python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check && uv run --no-sync python -m infra.lint.check_direct_meli .'
```

The full pytest invocation intentionally passes no selection, not a reduced list.
The harness injects MONGO_URI, so protected stock-time rs0 tests will skip there;
run those separately in the same verified container using `env -u MONGO_URI`
and its confirmed loopback ZELER_RS0_TEST_URI. The parent owns that established
safe environment assembly; do not borrow any host or production database value.
Run exactly:

```text
uv run --no-sync pytest tests/integration/test_stock_time_forward_acquisition_rs0.py tests/integration/test_stock_time_forward_execution_rs0.py tests/integration/test_stock_time_forward_rollback_rs0.py
```

Do not claim root completion until both ordinary and protected suites terminate
successfully with their intended services present. Schema export for regeneration
omits `--check`; schema application to production is never a local test gate.
The design threat matrix is N/A for routing/shell/subprocess boundaries; no
synthetic threat tasks or external process integrations are added.
