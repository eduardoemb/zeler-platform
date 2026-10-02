# Apply progress

## Current delivery state — 2026-10-02 19:40 UTC

Local implementation and required root validation complete; **35/35 local tasks checked**.
Final root:5701 passed,9 skipped; protected8 rs0 passed separately; all required
repository quality/schema/direct-Meli gates passed. Final evidence is recorded below.
The later coordinated correction record below resolves the independent status
and renewal findings; earlier checkpoints retain their original evidence.
Earlier checkpoints below are retained as chronological TDD evidence, not current
remaining-work statements. Executable/schema/tests frozen for parent root gates.
No production migration, acquisition, build, deploy or native acceptance performed.
Final focused suite before last hardening: **761 passed in 45.20s**. Final
real-rs0/migration suite after hardening: **42 passed in 6.14s**; standalone
marker/validator regression suite: **30 passed in 0.33s**. Focused Ruff/format,
mypy (22 files), and schema export `--check` passed. No skipped new rs0 cases.


Status: in progress. Native applyState ready consumed; proposal, design, tasks and
14-requirement / 41-scenario specification read. No production/provider/Git/build
operations. Four unrelated SHA256 checks passed before edits. Schema export is
local generation, not validator rollout. Parent owns final root gates.

## TDD Cycle Evidence

| Task | Test file | Layer | Safety net | RED | GREEN | Triangulate | Refactor |
|---|---|---|---|---|---|---|---|
| 1.1 | readiness/runs/composition/runner/fencing | unit + real rs0 | 53 pass, exit 0 | N/A | baseline green | existing cases | N/A |
| 1.2–1.3 | core/tests/test_devoluciones_certificates.py | unit | new | observed missing production module, exit 2 | 19 pass | disjoint/adjacent/overlap/foreign/expired/invalid bounds/typed identity | pending |
| 1.4–1.5 | tests/integration/test_devoluciones_fencing_transactions.py | real rs0 | 2 existing pass | missing coverage_ack_fence, exit 1 | 33 pass including readiness/core/fencing | initial legacy mode + simulated legacy increment invalidates before acknowledgement | pending |
| 1.6 | core/tests/test_devoluciones_certificates.py | unit schema | existing exporter baseline pending | corrected test symbol, then observed missing certificate schema, exit 1 | 30 pass including existing export tests | strict fields + legacy optional compatibility fields | real validators pending |

Commands use `bash /tmp/zeler-focused-tests-20261002-multiperiod.sh` plus test
paths above and `-q`. The prepared runner uses isolated loopback rs0; new real
transaction test asserts hello.isWritablePrimary and does not silently skip.

## Work Unit Evidence

Unit 1 in progress. Domain selection and acknowledgement tests green; complete
provenance validation, persistence validation and stale-owner publication pending.
No unit is represented complete yet. Additive code remains default legacy mode.

## Remaining / acceptance

All lifecycle publication, writer, formula, renewal, migration and operational
acceptance work remains pending. Root gates and native production acceptance have
not run. No historical coverage was changed.

## Implementation checkpoint — 2026-10-02 18:35 UTC

The initial remaining-work paragraph above describes the start, not the current
implementation. Lifecycle foundations now exist; the capability is still NOT
complete/ready for activation.

- Domain suite: 32 passing cases, including full field/type/epoch/version/time
  validation, source kinds, genuine run binding/complete contiguous windows,
  exact union, gaps, and strict export/application contracts.
- Real rs0 tests now cover additive/idempotent independent publication, conflicting
  identity, lost owner, same-count fact drift/missing order, claim membership
  movement preserving unrelated May, stale-version no-op, shared orders across
  June/August, actual quota finalization twice, genuine joint provenance without
  fake runs, snapshot reader/final fence checks, unknown/explicit failed-state
  invalidation, bounded fair renewal and its existing refresh-loop entrypoint.
- Qualified mutation RED observed: valid claim update incorrectly left `stale`;
  GREEN now validates exact pre-state fingerprint/membership and expected post
  identity set, updates current proof/revision only. A companion unexplained
  pre-state drift remains stale. Shared-order qualified-transition RED observed
  (0 versus 2 reconciled proofs); GREEN preserves both bounds/acquisition proofs.
- Raw writer RED observed for both bootstrap `stage/order_id` and repair
  `repair/order_id` checkpoints; GREEN default core guard checks before/after
  facts and dependency claims in the same transaction. The two specialized
  source-backed writers explicitly own their complete impact/transition helper.
- Validator RED observed after eliminating duplicate-key masking in invalid test
  fixtures: Mongo accepted reversed interval bounds. Export now adds a sibling
  `$expr`; `infra/mongo/apply_validators.py` retains it rather than silently
  dropping it. Its 10 existing tests passed before change; real strict Mongo
  validator, provenance types, unique identity, core/export/loader suite GREEN.
- Latest consolidated safety/refactor run: 173 tests passed (real multiperiod,
  core certificates/readiness, runner/composition/event persistence), exit 0.
  Earlier existing publication/reconciliation/formula/event baseline: 495 passed.
  Formula plus real integration check: 43 passed. Bootstrap/backfill baseline:
  208 passed. Explicit marker writer baseline: 24 passed.
- Focused Ruff fixed imports/formatted 15 owned files. Focused mypy revealed only
  new-test annotations plus one getter type; corrected (final rerun pending).
- Migration RED was observed missing module. New default-dry-run migration CLI is
  being tested; first runner attempt exposed a 65-character disposable DB name
  fixture (Mongo limit 63), corrected to the owned `zeler_test_cert_mig_` prefix.
  Migration/activation/rollback coverage and operational capacity remain pending.

### Additional observed TDD cycles

| Task | Test file | Layer | Safety net | RED | GREEN | Triangulate | Refactor |
|---|---|---|---|---|---|---|---|
| 1.3/1.6 | core certificates + real multiperiod | unit/rs0 | 10 loader tests | missing binding API; malformed selector accepted; reversed bounds accepted | 32 unit + real schema checks | invalid kinds/sellers/windows/dates; genuine joint vs quota | focused formatting in progress |
| 2.1–2.4 | real multiperiod | rs0 | 495 existing tests | actual finalizer 0 certificates vs2; claim/order mutation left reconciled | June/August finalized and dependency cases pass | stale-version no-op/unrelated period | shared helpers |
| 2.5 | real multiperiod | rs0 | above | qualified claim/shared-order updates stayed stale | exact pre/post cases pass | unexplained drift remains stale | source/acquisition proof unchanged |
| 2.6/2.8 | real multiperiod | rs0 | 24 marker +208 bootstrap/backfill | unknown/failed and raw guards left proofs reconciled | tested paths pass | bootstrap/repair/explicit/unknown | central default guard |
| 3.1–3.2 | real multiperiod + formula returns | rs0/unit | formula baseline green | active certificate reader unavailable | 43 combined pass | fence change/gap/unmodified legacy formula | snapshot API preserves columns |
| 4.1–4.3 | real multiperiod + runner | rs0/unit | runner baseline green | missing bounded renewal; loop left validity unchanged | 32 combined pass | successive due pages, expired independent proofs, mismatch refusal | same loop/no source client |
| 5.1–5.2 | operations migration | rs0 | new module | missing migration module observed | in progress | invalid quota no legacy fallback, dry-run/idempotency planned | pending |

### Current writer inventory

| Path | Fact writer / transaction owner | Certificate handling |
|---|---|---|
| Quota/focused/generic reconciliation | snapshot -> claim projection / event persistence; existing operation guard | exact invalidation/qualified transition; finalizer publishes under same fence |
| Claims event/bootstrap/historical hydration | `persist_claim_projection` | prior/new membership, monotonic no-op, exact pre/post transition |
| Order events, history publication, recovery, historical hydration | `SheetsEventPersistence._persist_order` | shared-order dependency claims; external session retained |
| Bootstrap OrdersStage raw `_upsert` | core guard `stage/order_id` | default before/after invalidation |
| Identity repair / normalization | core guard `repair/order_id` | default before/after invalidation |
| Explicit stale/failed and unknown event relevance | core marker guard | all potentially affected seller certificates withdrawn |
| `devoluciones_classify_legacy_claims.py` | read-only projected classification | not a canonical writer |
| core events/claims.py | event-delivery lease store, not canonical return claims | not a DEVOLUCIONES fact writer |

Index added: `(seller_id, order_id, type, date_created)` because the existing
order-id-only and seller/type/date indexes were not equivalent. No existing
index removed. Explain evidence, externally owned transaction abort/race coverage,
status/capacity, migration completion, task/scenario reconciliation and root gates
remain to do. Parent owns final root gates; no runtime acceptance has occurred.

## Final implementation record

### Implementation adjustments

- Lifecycle tests are concentrated in `tests/integration/test_devoluciones_multiperiod.py`
  using actual Mongo transactions, real finalizers, canonical writers and formula
  dispatcher, rather than duplicating them across every anticipated unit-test
  file in tasks. Existing related suites remain regression safety nets.
- `consumer.py`, `history_publication.py`, `historical_meli_backfill.py`,
  `sheetseller_backfill.py`, recovery worker and bootstrap needed **no duplicated
  certificate logic**: their existing calls enter the enhanced shared guard,
  claim projection or order persistence. Real externally owned transaction abort
  now proves order+both dependent proofs roll back together. Existing consumer
  ACK/retry/404 behavior was not edited.
- `formulas/refresh.py` already invokes the runner renewal entrypoint. The active
  branch reuses that loop; no second timer or provider-budget change was needed.
- The validator loader is an additional justified file: preserving exported
  `$expr` is necessary for the real persistence contract to match its schema.
- The optional run-id migration path handles genuinely complete historical
  receipts without requiring another source scan. Original source/acquisition
  proof remains immutable; current readiness is independently renewed.
- Final proof-vector comparison now includes all immutable acquisition identity,
  count and provenance fields. It revalidates control and every proof/provenance
  in one bounded snapshot transaction, not separately sampled documents.

### Final TDD and regression evidence

`H` = `bash /tmp/zeler-focused-tests-20261002-multiperiod.sh`. Every command below
ran only in the verified isolated runner. No production connection inherited.
The new integration fixtures assert `hello.isWritablePrimary` before use.

| Task | Test file | Layer | Safety net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
| 1.3–1.7 | core certificates, fencing, real multiperiod | unit + rs0 | initial 53 tests; loader 10 | missing API/schema, missing ack, malformed fields/bounds accepted | domain/schema/fence included in 761; real persistence included in final42 | invalid kinds, future/foreign bounds, incomplete windows, unique identity, legacy mismatch | pure helpers, Ruff/mypy green |
| 2.1–2.4 | real multiperiod | rs0 actual finalizers/writers | existing 495 publication/event/formula tests | finalizer produced0 vs2 certificates; mutations left stale proof productive | final42: June/August/earlier/later, joint source, affected writes | stale monotonic no-op; unrelated May; disjoint proof preserved | common publication and dependency APIs |
| 2.5 | real multiperiod | rs0 | prior writer tests | qualified mutation remained stale; shared order0 vs2 recertified | final42 qualified exact pre/post transitions | unexplained pre-state drift stays stale; original acquisition unchanged | bounded shared transition helpers |
| 2.6–2.9 | real multiperiod + marker/legacy writer suites | rs0 + unit | marker24, bootstrap/backfill208 | unknown/failed/raw bootstrap/repair left proofs reconciled | final42 + marker/validator30 | externally owned transaction abort rolls back facts and both proofs; unsupported impact conservative | centralized default guard, no duplicate consumers |
| 3.1–3.4 | real multiperiod + formula returns | rs0 actual dispatcher + unit | legacy formula baseline | active reader unavailable; final immutable evidence mutation accepted (2 failures); final vector had no shared snapshot (1 failure) | final42 after all fixes; formula regressions in761 | overlap/distinct claims one order; concurrent claim write between claims/orders; deletion/gap/fence/validity-only extension; immutable count/source changes | one initial fact snapshot + one bounded final proof snapshot |
| 4.1–4.3 | runner + real multiperiod | unit + rs0 | existing runner baseline | missing renewal API; refresh left validity unchanged; slow compatibility I/O escaped batch bound | runner included in761; final42 fair cycles | expired acquisition retained; mismatched proof unavailable; unacknowledged old-writer fence refused; deadline reports unknown counts | existing loop, indexed due cursor, one lease |
| 4.4–4.5 | core capacity, status, alarm, real multiperiod | unit + real explain | legacy status/alarm76 | missing capacity/status and active alarm evaluated singleton | core/status/alarm included in761; final42 explain/status | unknown vs measured overload;41 retained expired;20 returned, at most20 examined | sanitized additive opt-in status |
| 5.1–5.5 | operations certificate migrate + real multiperiod | rs0 | missing module | module absent; malformed retained proof accepted; rollback/reactivation initially blocked retained unavailable history | final42 includes12 migration cases | default no-write; idempotency; invalid quota no fallback; complete expired receipt vs completed-only; competing lease; provisional abort; every productive proof rechecked | explicit authority/mode gates; no shell/provider dependency |
| 6.1/6.4/6.5 | artifacts/deploy/rollout | documentation | protected checksum manifest | N/A documentation | links/flags/source inventory checked; manifest all4 OK | runtime evidence explicitly unperformed | cognitive-doc-design quick path |

The late immutable-vector RED command was
`H tests/integration/test_devoluciones_multiperiod.py -k final_vector_rejects`
(**2 failed**, each `DID NOT RAISE`). After adding immutable fields,
`H tests/integration/test_devoluciones_multiperiod.py -k 'final_vector_rejects or known_shared_order'`
was **4 passed, 25 deselected in0.86s**, including external abort triangulation.
The late snapshot RED command was
`H tests/integration/test_devoluciones_multiperiod.py -k final_vector_revalidates`
(**1 failed**, missing transaction session). Final combined42 proves GREEN.
Migration interruption/competing-lease cases are regression triangulation of the
already guarded implementation, not falsely reported as a new failing cycle.
Earlier observed RED details are retained in the chronological checkpoints above.

### Work Unit Evidence

| Unit | Focused command and exact result | Runtime harness result | Rollback boundary |
|---|---|---|---|
| 1 Contracts/fence/schema | final integrated command below:761 passed; final owned Ruff/mypy/schema checks exit0 | strict Mongo rejects extra fields, reversed bounds and conflicting identity; old fence mismatch invalidates before ack | default legacy mode; retain additive schema/documents |
| 2 Publication/writers | `H tests/integration/test_devoluciones_multiperiod.py tests/operations/test_devoluciones_certificate_migrate.py`:42 passed in6.14s | actual quota finalizers preserve4 periods; one-shot age/fence abort; external order+proof transaction abort | withdraw mode before old writer, preserve canonical data/receipts |
| 3 Reader/renewal | integrated761, then final42 after vector hardening | real formula result `[["MLM1","SKU",3,"One"]]`; read race unavailable; fair due renewals; indexed20/41 | legacy mode before removing certificate-aware readers/writers |
| 4 Migration/status | same final42; `H tests/test_read_model_freshness_writer.py tests/test_apply_validators.py`:30 passed in0.33s |12 migration cases, current marker preservation, rollback/legacy mutation/reactivation, status/explain | `--write --rollback` advances epoch and retains facts/runs/certificates |

Integrated focused command (exit0, **761 passed in45.20s**, before last5 safety
cases; the final42 reran every subsequently edited executable path):

```bash
bash /tmp/zeler-focused-tests-20261002-multiperiod.sh \
  core/tests/test_devoluciones_certificates.py \
  core/tests/test_devoluciones_readiness.py \
  core/tests/test_schema_export_phase3.py \
  tests/integration/test_devoluciones_fencing_transactions.py \
  tests/integration/test_devoluciones_multiperiod.py \
  tests/operations/test_devoluciones_certificate_migrate.py \
  tests/operations/test_zelerdata_read_model_reconcile.py \
  tests/operations/test_zelerdata_read_model_status.py \
  modules/sheets/tests/test_devoluciones_reconciliation.py \
  modules/sheets/tests/test_devoluciones_runner.py \
  modules/sheets/tests/test_devoluciones_operation_composition.py \
  modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py \
  modules/sheets/tests/test_event_persistence.py \
  modules/sheets/tests/test_zelerdata_freshness_alarm.py \
  modules/sheets/tests/test_zelerdata_refresh.py
```

Final quality command in `zeler-diag-runner-20261002`,
context `colima-zelerdata-tests-20261002`: `uv run --no-sync ruff format` and
`ruff check` over the22 owned Python files, **all checks passed**;
`uv run --no-sync mypy` same files, **no issues in22 source files**;
`uv run --no-sync python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check`,
**exit0**. `/tmp/devoluciones-owned-python-files` contains that exact file list.
Full root pytest, protected stock-time rs0, repository Ruff/mypy, direct-Meli
lint and schema check are delegated to parent as task6.3; not yet claimed here.

### Full scenario traceability

Abbreviations refer to actual files, not simulated runtime evidence:

- **D** `core/tests/test_devoluciones_certificates.py`
- **I** `tests/integration/test_devoluciones_multiperiod.py`
- **F** `tests/integration/test_devoluciones_fencing_transactions.py`
- **M** `tests/operations/test_devoluciones_certificate_migrate.py`
- **R** `modules/sheets/tests/test_devoluciones_runner.py`
- **L** `modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py`
- **S** `tests/operations/test_zelerdata_read_model_status.py`

| Requirement / scenario | Actual test / evidence | State |
|---|---|---|
|1 August follows June | I `actual_quota_finalizer_preserves_two_periods` (now asserts4 certificates) | local pass |
|1 Earlier/later periods | same test finalizes June,August,May,September | local pass |
|1 Disjoint acquisition unfinished | I `conflicting_identity_and_lost_owner_cannot_publish`, claim mutation retains unrelated; existing reconcile failure/partial-window suite | compositional local coverage; native fail/cancel not exercised |
|2 Complete acquisition | I actual quota finalizer; D `quota_provenance_requires_bound_complete_contiguous_windows` | local pass |
|2 Insufficient receipts/readback | D quota/binding and completed-only; I `joint_readback_detects_same_count_drift_and_missing_order`; M invalid marker | local pass |
|2 Future bounds | D `invalid_or_unacquired_bounds_fail_closed`, `ineligible_proofs_fail_closed` | local pass |
|3 Separate disjoint reads | D `disjoint_periods_remain_independent_and_gap_is_not_coverage`; I additive/selecting proofs | local pass |
|3 Cross-gap request | I `formula_repository_uses_snapshot_proof_vector_and_rejects_gap`; D disjoint | local pass |
|3 Adjacent bounds | D `adjacent_and_overlapping_proofs_are_selected_deterministically`; existing L half-open scoped claims | local pass |
|3 One required proof expired | D ineligible/disjoint; I status/backlog | local pass |
|3 Invalid bounds | D invalid/malformed/missing-field cases; real strict Mongo | local pass |
|4 Overlapping proofs | I `native_formula_overlap_counts_distinct_claims_once` | local pass |
|4 Distinct claims share order | same actual dispatcher case, total3 rather than duplicates or collapsed claim | local pass |
|4 Foreign seller | D ineligible typed seller proof; existing L seller filtering | local pass |
|5 Stable vector | I native formula, additive vector, final snapshot test | local pass |
|5 Selected proof changes | I additive deletion/extension, repository fence, final immutable evidence cases | local pass |
|5 Shared-order read race | I actual claim mutation between claim/order snapshot reads plus shared-order invalidation/recertification and final vector | compositional local coverage; direct shared-order mid-read timing not separately injected |
|6 Owner publishes interval | I actual quota and joint finalizers | local pass |
|6 Owner changes/expiry | I conflicting/lost owner and lease-after-provisional; F original stale-owner cases | local pass |
|6 Provisional publication abort | I age-check and lease-end abort; external order/proof abort; M interrupted publish | local pass |
|7 Claim moves interval | I `claim_mutation_invalidates_old_and_new_membership_not_unrelated` | local pass |
|7 Old shared order | I shared order invalidation and known transition acrossJune/August | local pass |
|7 Unknown impact | I `unknown_and_explicit_failure_withdraw_all_certificates` | local pass |
|7 Unrelated period | I claim mutation preservesMay; exact source-backed transitions retain independentbounds | local pass |
|8 Expired acquisition renewal | I `bounded_renewal_is_fair_and_preserves_acquisition`; M expired genuine receipts; R range receipt checks | local pass |
|8 Independent expiry | D disjoint/expired selection; I status separatedexpiry | local pass |
|8 Missing dependency | I joint readback/missingorder and boundedrenewal mismatch; R rangecertification refusal | local pass |
|9 Fair older periods | I boundedrenewal successive due pages; indexed20-of41 retainedhistory | local pass |
|9 Insufficient capacity | D `capacity_is_unknown_without_measurement_and_honest_on_overload`; R totalbudgetincludescompatibilityIO; I activealarm | local pass; production throughput unmeasured |
|10 Idempotent June migration | M dryrun/idempotent genuinelegacy and expiredcompletequota receipt; I publicationidentity | compositional local pass |
|10 Invalid legacy backing | M invalidmarker matrix, malformed/everyretainedproof validation; noquota fallback | local pass |
|10 Interrupted migration | M `competing_owner_and_interrupted_migration_cannot_publish` + idempotentretry | local pass |
|11 Incompatible writer | F ack mismatch/renewalrefusal; M activationauthority | local pass; deployed writer inventory still requires operator proof |
|11 Older reader remains | I qualifiedsharedorder withdraws singleton; actual finalizer publishes exact scopedlegacyview, neverunion | local pass; mixed deployment not performed |
|11 Compatibility changes | I repository fence and finalsnapshot; M rollbackepoch | local pass |
|12 Rollback singleton | M activationrollback documentsretained | local pass |
|12 Resume after legacy writes | M `rollback_withdraws_retained_proofs_and_reactivation_can_preserve_unavailable_history` | local pass |
|13 Invalid persistent data | I real strict validator/uniqueindex; D export/loaderexpr | local pass |
|13 Honest coverage/backlog | I status/gaps/expiry/alarm; S opt-in coverage | local pass |
|14 Local vs production | this artifact, pending6.3, rollout approval boundaries | local evidence explicit |
|14 Authorized native acceptance | rollout.md acceptance table | **unperformed**, separate authorization required |

### Final writer inventory / unchanged caller rationale

The earlier inventory remains applicable. Source audit confirmed shared-entry
calls in `bootstrap/src/zeler_bootstrap/stages.py` (OrdersStage guard and ClaimsStage
projection), `sheetseller_backfill.py` (identity/normalization guarded writes),
`historical_meli_backfill.py` (claim projection), and
`infra/operations/zelerdata_read_model_reconcile.py` (quota/finalizer guards).
History/recovery order publication uses `SheetsEventPersistence` and propagates
caller sessions; the new external abort test proves facts and dependent proofs
share that caller transaction. No alternate canonical writer was intentionally
left outside active-mode maintenance. `consumer.py` existing unknown/stale paths
reach the enhanced marker/core guard. Source searches are not production proof:
activation must still establish deployed versions for every such caller.

### Remaining / delivery boundaries

- Parent task6.3: full repository gates and protected rs0 execution, then optional
  independent SDD verification. New failures require reopening the writer freeze
  and rerunning affected evidence, not reducing the gate.
- Production: commit/push, exact-source per-service Cloud Builds, validator/index
  application, compatible runtime rollout, migration/activation, acquisition and
  native June/August/gap/>30-minute acceptance remain unperformed/unimplied.
- Genuine previously unsupported legacy history is not fabricated. Capacity is
  honestly unknown until observed, or degraded if retained proof count cannot be
  renewed within the horizon. No upstream scan is introduced by this change.
- Review mode remains disabled/unmanaged. No commit, branch, worktree, PR, build,
  deployment, source/provider call or protected-file edit was made by this apply.

### Independent verification finding during writer freeze

Parent reported an independent finding: `--devoluciones-coverage --readiness`
can return ready when a malformed document increments `invalid` but is excluded
from `intervals`, because its readiness condition does not inspect `invalid`.
The alarm already degrades that state. Task4.4 reopened; **do not claim full
status acceptance**. Parent explicitly requested no executable/test edits while
root gates run; a focused RED and coordinated fix/rerun remain pending.

Final authored size at handoff:5,742 added/deleted lines including generated
schemas, planning/apply/rollout artifacts, and tests (protected unrelated work
excluded). This exceeds the preliminary1,800–3,500 estimate; the accepted single
local `size:exception` is retained. No line compression or Git mutation used.


## Coordinated correction batch after independent verification

Parent first full-root run: **1 failed,5691 passed,9 skipped in260.31s**. The failure
was `tests/test_mongo_schemas_placeholder.py::test_placeholder_schema_files_exist_and_reference_phase_three`,
whose expected-file allowlist omitted the new certificate schema. Post-pytest
parent gates before this correction were green: protected8 rs0 **8 passed in1.85s**;
full Ruff/check+format627, mypy627, schema export and direct-Meli lint exit0.
Those root results are preserved, not misrepresented as a final all-green suite.

Parent authorized a three-defect correction after the test slot was released:

| Task | Test file | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|---|---|---|---|---|---|---|---|
|1.6 /6.3 inventory | tests/test_mongo_schemas_placeholder.py | repo contract | parent5691 passes | actual root allowlist failure | standalone1 passed in0.03s | schema added to expected and active-non-placeholder sets | no schema relaxation |
|4.4 status | tests/operations/test_zelerdata_read_model_status.py | unit CLI | existing status suite | sufficient capacity + invalid1 wrongly returnedready | included in199 impacted passes | unknown capacity degraded; sufficient+invalid0 ready | one explicit invalid-count gate |
|4.3 renewal starvation | modules/sheets/tests/test_devoluciones_runner.py | unit real entrypoint | legacy runner tests |4 cases at0/15/30/45 had no renewal opportunities | included in199 impacted passes | source fail/renew fail combinations; bounded compatibility timeout still advances once | active-only pre-source helper, existing lease and batch budgets |
|4.3 /6.2 durable renewal | tests/integration/test_devoluciones_multiperiod.py | real rs0 fake clock | earlier exact proof renewal | follows above observedRED |3 real entrypoint modes passed | actual June proof renewed at0/15/30/45 with dueAugust, failedAugust, or disabledsource; acquisition fingerprint unchanged | no additional source admissions or timer |

Observed RED command:
`H modules/sheets/tests/test_devoluciones_runner.py tests/operations/test_zelerdata_read_model_status.py -k 'due_authorized_windows or certificate_status_cli'`
returned **5 failed,1 passed,88 deselected in0.22s**.

Final affected command:
`H modules/sheets/tests/test_devoluciones_runner.py modules/sheets/tests/test_zelerdata_refresh.py tests/operations/test_zelerdata_read_model_status.py tests/integration/test_devoluciones_multiperiod.py tests/operations/test_devoluciones_certificate_migrate.py`
returned **199 passed in6.96s**. Owned-file Ruff/format and mypy **23 files** passed;
schema export `--check` exit0. Final source-free simulations do not count as live
45-minute observation. Parent notified of executable freeze/test-slot release for
full root rerun. Task4.4 reclosed; only6.3 remains pending.

The starvation root cause was renewal occurring only in the no-due/disabled-source
branches. Active mode now renews before a due authorized source call, so a long or
failed source attempt cannot prevent that cycle's opportunity. Compatibility
lookup plus renewal is bounded to30 seconds; a local error/timeout is logged
sanitized and the single authorized advancement is still attempted. All ordinary
lease/authorization/window budgets still apply; there is no second admission or
source retry. Legacy singleton due-source behavior is intentionally unchanged.

Independent verification also found a documentation mismatch: design had promised
automatic selection of a valid singleton during rollback. The chosen safe behavior
is narrower: withdraw new authority/advance epoch, preserve every canonical fact,
receipt and certificate, and leave the existing genuine legacy singleton as-is.
It may be stale/expired and therefore unavailable. Design/rollout/deploy wording
now explicitly agrees; no transparent restoration or newly certified legacy view
is claimed. This is consistent with the spec's permitted availability downgrade.

Traceability updates: Requirement9 fairness now includes actual always-due and
failed-advance entrypoint cases above; Requirement13 status includes malformed
certificate count; Requirement12 rollback is intentionally existing-singleton or
unavailable, not an unimplemented automatic projection presented as complete.


## Final local gate closure — 2026-10-02 19:40 UTC

Task6.3 is complete. Parent's final unchanged full-root rerun and every chained
gate finished with overall `set -e` exit0. This closes local implementation only,
not deployment, migration, source acquisition or native runtime acceptance.

| Gate | Exact result |
|---|---|
| Full repository pytest | **5701 passed,9 skipped in257.91s** |
| Protected stock-time rs0, separately without ambient MONGO_URI | **8 passed in1.78s** |
| `uv run --no-sync ruff check .` | All checks passed |
| `uv run --no-sync ruff format --check .` |627 files already formatted |
| `uv run --no-sync mypy .` | No issues in627 source files |
| `uv run --no-sync python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check` | exit0 |
| `uv run --no-sync python -m infra.lint.check_direct_meli .` | exit0 |

Parent command: `bash /tmp/zeler-devoluciones-root-gates-20261002.sh`, using the
already verified isolated runner and its loopback test services. The script runs
`uv run --no-sync pytest` without selection, then the three protected stock-time
rs0 files with `env -u MONGO_URI` and the confirmed isolated test URI, followed by
all quality commands above. It uses `set -eu`; no failed command was hidden.
Final log: `/tmp/zeler-devoluciones-root-gates-final-rerun-20261002.log`.
The9 ordinary skips are8 intentional ambient-MONGO_URI safety guards (all8 then
executed successfully separately) and the existing Caddy contract case lacking
required keys. Neither is represented as production/runtime acceptance.

### Preserve earlier failures and uncertainty

- First root run:1 schema inventory failure,5691 passes,9 skips in260.31s. The
  omitted new-schema allowlist entry was fixed and verified; no schema removed.
- Second root run after corrections: **5700 passed,1 failed,9 skipped in265.86s**.
  An untouched inventory-discovery deadline/quota-wait case reported attempts1
  rather than0. Its entire deadline test file immediately passed **11 tests**
  unchanged. The third full root run above passed unchanged. The intermittent
  failure's **cause remains unconfirmed**; no timing/test/code workaround was
  introduced or asserted as a diagnosis.

All35 local tasks are now checked. Final protected manifest verification reports
all4 unrelated files unchanged; `git diff --check` is clean. This closeout changes
only tasks/progress and the raw phase envelope, not executable code or tests.
Independent final SDD verification is parent-owned; no archive operation performed.
No production/readiness state is inferred from local completion.
