# Verification diagnostics — DEVOLUCIONES multiperiod coverage

Date: 2026-10-02. Result: **partial; concrete findings require follow-up**.
This is requested SDD verification, not RDD, an approval, a deployment certificate,
or a claim that the overall runtime goal is complete. Code and test changes are
outside this executor's scope. This report preserves the inspected frozen
implementation's findings even if a later writer corrects them.

## Scope and evidence boundary

Read the selected OpenSpec proposal, full specification (14 requirements / 41
scenarios), design, tasks, apply-progress and rollout instructions. Inspected the
new certificate/migration modules and changed reader, writer, renewal, schema,
status and test paths. The status locator was supplied by the parent; the newer
apply-progress locator was supplied explicitly rather than recovered from another
store. No global OpenSpec baseline or configuration was substituted.

The parent owned full repository tests against its isolated Mongo/RabbitMQ runner.
This verifier did not run database tests concurrently. It directly executed two
source-free diagnostic reproductions using production Python entrypoints with
in-memory collaborators; neither connects to Mongo or a provider. No production,
source acquisition, schema application, commit, branch, build or deployment was
performed. The four unrelated incident/Google files were not edited.

## Findings

### V-1 — High: ongoing acquisition excludes renewal of older certificates

**Location:** `modules/sheets/src/zeler_sheets/devoluciones_runner.py:72–100`,
`advance_due_devoluciones_run`.

The function calls `renew_devoluciones_marker_if_proven` only when advancement is
disabled or there is no due authorized run. When an authorized August acquisition
remains due over successive refresh cycles, it calls the advancer and returns
without giving retained June certificates any renewal opportunity. The new
`renew_due_certificates` helper is internally fair, but its outer scheduler can
exclude it indefinitely while newer acquisition work exists. This is not honest
capacity exhaustion: the available renewal work is never attempted.

**Direct reproduction (exit 1):** execute the actual entrypoint at simulated
minutes 0, 15, 30 and 45 with a `Runs.find_one` stub returning one authorized August
run, a no-op async source advancer recording calls, and the renewal helper patched
to record calls. Observed:

```json
{"simulated_refresh_minutes":[0,15,30,45],"advance_calls":4,"renewal_opportunities":0}
```

An assertion requiring any renewal opportunity fails. No database/provider call
is used. The current integration wiring test explicitly uses
`advance_enabled=False`, so it cannot expose this branch.

**Affected contract:** additive historical availability and fair independent
renewal (requirements 1, 8 and 9; tasks 4.2/4.3). Add a RED regression exercising
continuous due acquisitions, then integrate bounded renewal without widening
source authority or creating a second scheduler. Rerun affected and root gates.

### V-2 — Medium: CLI readiness ignores malformed certificates

**Locations:** `infra/operations/zelerdata_read_model_status.py:169–175` and
`core/src/zeler_platform_core/devoluciones_certificates.py:certificate_status`.

`certificate_status` excludes malformed documents from `intervals` and increments
`invalid`. The CLI `--devoluciones-coverage --readiness` condition checks compatible,
sufficient capacity, nonempty intervals and all readable intervals, but omits
`invalid`. Its result can therefore say ready while separately reporting invalid
retained certification. The freshness alarm correctly checks this field; the
CLI disagrees with that existing fail-closed operational behavior.

**Direct reproduction (exit 1):** patch only `certificate_status` in memory to
return active/compatible, one readable interval, `invalid=1`, and sufficient
capacity, then invoke the real status `main` with the coverage/readiness flags.
Observed:

```json
{"invalid":1,"reported_status":"ready","blocking":[]}
```

An assertion expecting degraded fails. No runtime data or production code was
modified. Formula proof validation itself remains stricter; this finding concerns
operator-facing readiness, not a demonstrated unauthorized productive formula.

**Affected contract:** truthful operational status (requirement 13; task 4.4).
Add invalid-certificate triangulation to the status test and align CLI readiness
with the alarm's conservative condition.

### V-3 — Medium: full regression gate fails on the new schema inventory

**Location:** `tests/test_mongo_schemas_placeholder.py:EXPECTED_FILES` and its
inventory assertion at line 169.

The new legitimate `sheets_devoluciones_certificates.json` is absent from the
expected schema filename set. The parent full suite observed exactly this
failure: **1 failed, 5,691 passed, 9 skipped in 260.31 seconds**. This is a change
regression, not an unrelated pre-existing failure. Schema export `--check` passes,
so parity between exporter and generated schema is not the missing check; the
explicit repository inventory also needs the new owned schema recorded.

**Affected contract:** complete root gates (requirement 14; task 6.3). Correct the
inventory expectation without weakening it, then rerun the full suite and any
checks invalidated by fixes for V-1/V-2.

## Critical behavior diagnostics

| Requirements | Observed implementation and tests | Conclusion at inspected snapshot |
|---|---|---|
| 1 Additive periods | Actual quota finalizer test publishes June, August, May and September; publication is per typed source identity with conflict rejection. | Additive persistence is covered locally; V-1 limits ongoing availability. |
| 2 Source eligibility | Quota binding reconstructs run identity and complete exact windows; publication compares current joint fingerprints; non-run paths retain typed source evidence and no fabricated runs. | Substantial local evidence; no new source acquisition asserted. |
| 3 Exact union | Greedy deterministic covering selection rejects the first uncovered instant; pure tests cover disjoint/adjacent/overlapping and invalid bounds. | Local evidence supports no min/max gap fabrication. |
| 4 Deduplication/seller scope | Actual Python formula dispatcher with overlapping proofs and two distinct claims sharing one order returns quantity 3, not duplicated or collapsed claims. | Local integration evidence; this test is not native Google Sheets execution. |
| 5 Snapshot vector | Initial facts use a snapshot transaction; final vector rechecks control plus all proofs in another bounded snapshot, including immutable acquisition fields and current proof revisions. | Real Mongo race/deletion/fence tests support fail-closed behavior; direct shared-order mid-read timing is compositional, not separately injected. |
| 6 Fenced atomicity | Operation guard checks before and after writes; tests abort provisional publication after age/lease failure and roll back externally owned order/proof transactions. | Local transaction evidence supports atomicity. |
| 7 Invalidation | Claim prior/new membership and shared-order dependencies determine affected certificates; unknown/explicit invalidation reaches all potentially affected proofs. | Known production writer paths inspected; runtime version inventory remains unperformed. |
| 8 Independent validity | Certificate validity is separate from acquisition expiry; renewal checks current fingerprint/membership and provenance, not counts alone. | Local helper evidence; outer scheduling fails under V-1. |
| 9 Fair/bounded scale | Due query orders by next-check/id, bounds count/time, and explains an indexed 20-of-41 retrieval; failed/unattempted work is not evicted. | Helper fairness supported; entrypoint starvation V-1 remains. Actual production throughput is unmeasured. |
| 10 Migration | Dry-run does not acquire a lease; explicit writes validate genuine run or recognized valid joint provenance. Real Mongo cases cover idempotence, invalid quota without fallback and interruption. | Local evidence; no production migration performed. |
| 11 Compatibility | Fence-bound acknowledgement detects simulated old writer participation; mismatch invalidates proofs before compatible acknowledgement; renewer cannot conceal mismatch. | Local tripwire tested. Operator compatibility confirmation is not automatic proof of deployed versions. |
| 12 Rollback | Mode withdrawal advances epoch and retains facts/receipts/certificates; reactivation validates current facts and may retain unavailable history. | Safe degraded rollback tested. Implementation does not synthesize a new singleton compatibility projection; rollout honestly permits narrower or unavailable legacy service. |
| 13 Persistence/status | Strict schema and cross-field `$expr` are preserved by exporter/loader; real Mongo rejects invalid bounds/fields and duplicate identity. | Persistence evidence supported; CLI status has V-2. |
| 14 Acceptance | Root test log and separate quality/protected-suite output inspected; native and runtime operations explicitly unperformed. | V-3 prevents full local gate success; runtime acceptance remains separate. |

### Canonical writer inventory checked

- Bootstrap `OrdersStage` raw `_upsert` includes `order_id` in its existing core
  guard; identity and normalization repair do the same. The default guard now
  compares prior/current order and invalidates dependency claim periods.
- Claim event/bootstrap/historical paths use `persist_claim_projection`; stale
  versions are no-ops, while real changes invalidate or exactly recertify old/new
  membership under the existing transaction.
- Event/history/recovery/historical order paths use `SheetsEventPersistence` and
  preserve external sessions. The real external-abort test checks canonical facts
  and both dependent certificates roll back together.
- Unknown event relevance and explicit failed/stale paths reach enhanced shared
  invalidation. Core event-delivery claims are a different collection/lease domain,
  not another canonical return writer.
- This source inventory is bounded to actual existing paths; it does not certify
  arbitrary direct Mongo writes or the versions currently deployed in production.

## Commands and outcomes

| Check | Executor / evidence | Outcome |
|---|---|---|
| Full `pytest` through isolated prepared harness | Parent; `/tmp/zeler-devoluciones-root-gates-20261002.log` read directly | **1 failed, 5691 passed, 9 skipped**; V-3. |
| Protected stock-time rs0 suite without ambient `MONGO_URI` | Parent; `/tmp/zeler-devoluciones-post-pytest-gates-20261002.log` | **8 passed**, `RS0_EXIT:0`; covers the eight deliberate isolation skips above. |
| `ruff check .` | Same post-pytest log | `RUFF_EXIT:0`. |
| `ruff format --check .` | Same log | 627 files already formatted, `FORMAT_EXIT:0`. |
| Full `mypy .` | Same log | No issues in 627 source files, `MYPY_EXIT:0`. |
| Schema export `--check` | Same log | `SCHEMAS_EXIT:0`. |
| Direct-Meli lint | Same log | `MELI_EXIT:0`. |
| Source-free scheduler probe | This verifier, `uv run --no-sync python` stdin | Exit 1; four advancements, zero renewal opportunities. |
| Source-free readiness probe | This verifier, same stdin mechanism | Exit 1; malformed-proof count 1 but reported ready. |
| Diff whitespace and rollout local-link checks | This verifier | Exit 0; no missing rollout links. |

The ninth full-suite skip is the existing Caddy case with no required keys, not
an unexecuted DEVOLUCIONES transaction test. No test result after subsequent
executable fixes is implied by these pre-fix logs.

## Strict TDD and assertion quality

### TDD compliance

The chronological and final **TDD Cycle Evidence** tables exist in apply-progress.
The final table covers eight work groups spanning domain/fence/schema,
publication/writers, reader snapshots, renewal, status and migration, plus docs.
Reported RED includes missing modules/schema/fence fields, accepted malformed
bounds, no additive certificates, missed invalidation/qualified transitions, and
late immutable-vector/snapshot failures. Referenced test files and production
assertions exist. Historical RED command results are reported by the apply agent;
this verifier cannot independently reconstruct pre-edit code or every historical
command and does not relabel test existence as proof of those historical failures.

The parent current root run confirms the related new tests execute, but the full
suite is not green. The verifier directly observed new failing diagnostics for
V-1/V-2. Baseline safety-net counts (53, loader 10, reconcile/formula 495, bootstrap
208, marker 24) are documented in apply-progress rather than independently rerun
here. No historical evidence was fabricated to fill that distinction.

| Check | Assessment |
|---|---|
| Evidence tables reported | Present, chronological plus consolidated. |
| Referenced new test files exist | Confirmed. |
| Historical RED independently replayed | Not replayed; recorded apply evidence only. |
| Current GREEN | Related tests pass in root run; full root fails V-3 and direct diagnostics expose V-1/V-2. |
| Triangulation | Nonempty/empty, success/failure, source identity, real transaction and formula behavior present; ongoing-acquisition renewal and invalid-count readiness missing. |
| Modified-file safety net | Reported in apply evidence; no claim of fresh independent baseline reconstruction. |

### Test layer distribution

Source inspection of the seven new/modified test files associated with this
implementation finds **178 parameter-expanded cases** (including existing tests
in modified files): unit 132 across four files; real-Mongo integration 46 across
three files; native browser/Google Sheets E2E zero. Counts were derived from AST
function/parameter lists, not presented as an additional test execution.

Assertions in authored blocks were inspected alongside a tautology scan of all
seven files. No `assert True` tautologies or empty-iteration ghost assertions were
found in those authored blocks. Empty-result checks have nonempty formula and
mutation companions. Structural session/index assertions are paired with real
transaction/race and output-value tests. The two findings are missing
triangulation, not evidence that the existing assertions are meaningless.

### Changed-file coverage and quality metrics

No `coverage` or `pytest_cov` module is installed in the verifier's local
execution environment, and no coverage tool/config is declared in the inspected
project dependency files. Changed-file line/branch coverage was therefore not
measured; no percentage is invented. Parent's full Ruff/format/mypy/schema/lint
outcomes are recorded above.

## Observed task state and next work

At inspection, tasks showed **33 completed / 2 open**: status task 4.4 had already
been reopened for V-2 and root task 6.3 was pending. V-1 also requires follow-up to
renewal tasks 4.2/4.3; this verifier did not alter checkboxes. Documentation
accurately distinguishes local implementation from unperformed runtime acceptance.
The design's automatic choice of a valid singleton on rollback is not implemented;
the narrower conservative implementation is documented as potentially unavailable,
which remains fail-closed but should not be described as transparent restoration.

Recommended next work: return to the explicitly assigned apply owner for V-1,
V-2 and V-3; preserve RED evidence, correct only owned scope, rerun invalidated
focused and full gates, and append any later diagnostic results without erasing
these findings. Production build/deploy, validator/index rollout, migration,
August acquisition and native June/August/gap/>30-minute proof remain separately
authorized, unperformed operations. This report creates no automatic correction,
review or archive gate.

## Bounded corrective revalidation — 2026-10-02

The original findings above are preserved as the pre-fix diagnostic snapshot.
The orchestrator explicitly requested only V-1/V-2/V-3 revalidation, not another
exhaustive review. The writer froze executable changes before this pass.

### Direct source-free reproductions after the fixes

`uv run --no-sync python` executed both actual entrypoints with in-memory
collaborators, no Mongo target and no provider calls; combined exit **0**.

- **V-1:** The actual scheduler was called at simulated minutes 0/15/30/45
  with a due authorized August run each time. The only additional gate mock was
  the actual `coverage_control` returning active mode; the renewal helper and
  advancer were recorded stubs. Assertion required exactly
  `renew, advance` on every tick, not merely any renewal. Result: **4 renewal
  opportunities before 4 advances**, versus the original 0/4. This directly
  resolves the scheduler starvation reproduction without claiming live capacity.
- **V-2:** The actual readiness CLI received the same readable interval,
  sufficient capacity and `invalid=1` fixture. It now returned **degraded** and
  `blocking=["devoluciones"]`; both were asserted. The implementation explicitly
  includes `coverage["invalid"] == 0` in readiness.
- **V-3:** Source inspection confirms
  `sheets_devoluciones_certificates.json` is now included in both the explicit
  filename inventory and the substantive-schema set. Root execution is recorded
  below when supplied; source inspection alone is not its passing result.

### Corrective test and implementation inspection

The runner now attempts active-certificate renewal before authorized source work,
including compatibility I/O in a 30-second timeout. Local renewal failure is
reported but does not suppress the single authorized advance; source exceptions
still propagate. No new run creation or source authorization path was introduced.
The new parameterized unit test requires the complete ordered renewal/advance
trace for all four ticks with both renewal and source failures. A separate test
injects a bounded compatibility timeout and requires exactly one advance.

The real-Mongo refresh-entry test now covers `disabled`, `due` and `failed`
source modes. It preserves a June proof while the actual scheduler sees a due
August run at all four ticks, asserts renewed validity beyond each tick plus
29 minutes and unchanged acquisition fingerprint, and checks zero or exactly
four authorized advancement calls as appropriate. Its source work remains
stubbed; this is database integration, not live acquisition or native Sheets.
The CLI test includes insufficient/unknown capacity, sufficient plus invalid,
and sufficient valid success cases, with both status and blocker assertions.
No assertions were weakened in these inspected corrective cases.

Final root checks were still running when these reproductions completed. This
executor did not start DB tests concurrently. Their results and any reconciled
rollback wording are appended below once the orchestrator supplies completion.

### Corrective evidence and second full-root attempt

The updated apply-progress records corrective RED **5 failed / 1 passed** for
scheduler/readiness cases, followed by **199 affected tests passed** and the
schema inventory's standalone passing test. These are writer-reported runs;
the verifier independently inspected the tests and directly reran the two
source-free reproductions above. The design rollback step now agrees with the
implementation: preserve the genuine existing singleton unchanged, withdraw new
authority by epoch change, and allow narrower or unavailable legacy reads rather
than automatically manufacture a compatibility projection.

The parent reported the next full-root run as **1 failed, 5,700 passed, 9 skipped
in 265.86 seconds**. V-1/V-2/V-3 regression cases passed. The failure was the
untouched deadline case
`test_formula_recovery_http_deadlines.py::test_inventory_discovery_deadline_distinguishes_local_wait_from_http[True]`,
line 208, observing one upstream attempt instead of zero. The same case passed in
the earlier root run. Its short real-time budgets suggest timing sensitivity,
but that is not a confirmed root cause or permission to call it pre-existing.
The parent is performing a focused deadline-file check and unchanged full rerun;
this intermediate failure is preserved, not replaced by an all-green claim.

### Final bounded revalidation result

**Result: success for the requested local diagnostics; V-1/V-2/V-3 resolved.**
This is not a deployment approval, review certificate or production acceptance.

The parent reports the unchanged deadline-file rerun passed **11 tests**. The
unchanged complete root rerun then passed **5,701 tests, 9 skipped in 257.91s**;
its log was read by this executor:
`/tmp/zeler-devoluciones-root-gates-final-rerun-20261002.log`.
Protected stock-time rs0 cases passed separately: **8 passed in 1.78s**. The eight
ordinary-root ambient-Mongo skips are therefore covered by their required
separate run; the remaining skip is the Caddy contract's no-required-keys case.
The same log shows Ruff check passing, **627 files** already formatted and full
mypy passing on **627 source files**. The parent confirms the set-e gate script
completed exit **0**, including schema export and direct-Meli lint. No executable
changes occurred between the deadline failure and these passing reruns; the
cause of that one-off failure remains unproven and is retained above.

The writer's corrected design now explicitly preserves the original legacy
singleton on rollback and permits honest unavailability; no automatic projection
is claimed. At the last task-file inspection, **34/35 tasks** were checked and
only parent-owned root-result bookkeeping task 6.3 remained open. This verifier
did not edit task state; the now-complete gate result is available to that owner.
The parent also reports all four protected unrelated file hashes preserved.

No unresolved defect remains from the three bounded findings. Existing limits
remain: no measured changed-file coverage, no reconstruction of historical RED,
no production schema/index application, migration/activation, actual capacity or
settling-window observation, native Google Sheets acceptance, build or deploy.
Those are distinct from successful local diagnostics and require their proper
operational authorization. The report retains both failed root attempts and
their subsequent outcomes rather than substituting only the final green run.
