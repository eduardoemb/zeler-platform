# Verification diagnostic: ZelerData Pilot Reliable Sync

Date: 2026-09-15. Result: **PARTIAL — specification acceptance not established**.
Reviewed revision: `c05093ff1f058ed7bac87549f7cf5efc8937a02e`.
Observed tasks: **14/37 checked, 23 pending**. No task checkbox was changed.

This is a separate verification phase, not a blind independent-author review:
the executor previously implemented several slices. It does not satisfy an
independent end-to-end acceptance review by itself. The report is diagnostic,
not authorization for deployment or a synthetic completion certificate.

## Scope and methods

Read the selected proposal, specification, design, tasks, apply-progress,
historical evidence audit and current runtime wiring. Inspected representative
production/test paths and reran six focused test files. Reused the completed
full-suite and root-gate artifacts after verifying their hashes and XML counts;
no executable changes intervened in this verification unit. No
`openspec/config.yaml` exists, so no additional `rules.verify` were available.
Unrelated untracked `.codegraph/` was neither read as evidence nor modified.

## Checks and evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Focused diagnostic, newly executed | 125 passed, zero skips/failures/errors, exit 0 | `/tmp/pilot-verify-diagnostic.xml` |
| Full repository suite, reused | 5328 cases: 5319 passed, nine skipped, zero failures/errors, exit 0 | `/tmp/final-suite.xml` |
| Root quality bundle, reused | Ruff passes; format checks 598 files; mypy passes 598 source files; direct-Meli and schema export checks pass; exit 0 | `/tmp/final-quality.log` |
| Documentation whitespace | `git diff --check` passes | Current report patch |
| Production, real provider, Google Sheets, 90-minute observation | Not executed | No acceptance evidence supplied |

SHA256 evidence identifiers:

- Focused XML: `4801c0cdbfedfb4dbcffbcbd10879e0152ba30eae1d6264be5e61f948a812a83`.
- Focused log `/tmp/pilot-verify-diagnostic.log`: `53129bb2c097c43967fbb7b3a5cdc7029e2e161686805cf919cea19f831b4773`.
- Full XML: `48cebba33772d9e565642bdf0e56695dae6a1301a58f997f7b90bf99da6de415`.
- Full log `/tmp/final-suite.log`: `5af7c14dcc7ed734ae46603da67f225bec32d9e514e8e9f0278c815b7848571e`.
- Quality bundle: `b1bccc2f0dbe8fa49142395ef67654233bf7e0331cd5caabbd0453ff530aa482`.

Focused command: `uv run pytest -q` selecting these files under
`modules/sheets/tests/`, with `--junitxml=/tmp/pilot-verify-diagnostic.xml`:

| File | Cases | Evidence layer |
| --- | ---: | --- |
| `test_pilot_old_operation_modification.py` | 3 | Mixed fixture and guarded consumer/Mongo/dispatcher integration |
| `test_history_publication.py` | 12 | Mongo guarded projection integration; publish prerequisite seeded |
| `test_history_orders.py` | 49 | Durable acquisition integration with gateway doubles |
| `test_history_questions.py` | 38 | Durable staging with normalized provider inputs, not real HTTP |
| `test_apps_script_refresh_execution.py` | 13 | Actual JavaScript executed in Node with service doubles |
| `test_pilot_sheets_config_progress.py` | 10 | ASGI/Mongo and authorization rejection; admin JWT signature stubbed |

The named default database was disposable loopback port 27028 with direct
connection; inherited ZELER_RS0_TEST_URI was unset. Mongo fixtures verify local
PRIMARY and clean up their unique databases. No production Mongo was accessed.
Full-suite skips comprise eight protected stock-time rs0 cases rejecting the
ambient MONGO_URI and one Caddy case without required keys. These are not passes;
historical separate protected-suite passes do not establish current execution.

## Requirement comparison

| Specification requirement | Supported local evidence | Remaining acceptance gap |
| --- | --- | --- |
| Complete Formula Acceptance | Registry preserves 52 contracts; local dispatcher matrix and cold-source concurrent batch exist | Representative positive/absent/filter/range source comparisons and actual Sheets observations remain pending |
| Immediate Event Flow | Guarded old-order consumer/projection/dispatcher convergence and stage telemetry have tests | Sustained actual-consumer retries, unfinished-event recovery and visible-cell latency are not proven end to end |
| Reconcile Changes to Old Operations | Exact 24-hour-overlap admission and durable ID/version/hash deduplication | Modification HTTP traversal, durable successful watermark and runtime wiring remain absent |
| Recoverable 12-Month History | Fixed monthly plan, strict models/validators, fenced receipts, continuation, staging and subdivision | Runtime durable-worker routing, cross-resource acquisition, publisher handoff and final reconciled coverage remain incomplete |
| Honest Freshness and Partial Data | Field-preserving readers and bounded publisher tests retain unaffected interval evidence | Seeded publish prerequisites and cold outputs do not establish complete economic totals across the pilot |
| Durable Recovery and No Starvation | Queue capacity/leases/deduplication and bounded continuation are locally exercised | Sustained fairness across event/inventory/query/history lanes remains unmeasured |
| Visible Sheets Synchronization | Manual bounded refresh and truthful pending rendering run in a local JavaScript harness; progress and seller-scoped sync-job status APIs are covered | Real recalculation, automatic reopen, web configuration UI and deployed behavior remain incomplete/unverified |
| Finite Acceptance | Local full repository gates pass subject to disclosed skips | Reconciled history, returns runtime evidence and 90-minute rounds 0/30/60 are missing |

## Actionable findings

1. **High — durable history remains disconnected from runtime admission.**
   `consumer.py:1383` still constructs `FormulaRecoveryWorker` for the normal
   lanes; `history_worker.py:1` explicitly declares the new worker unwired.
   `pilot_history_recovery_bridge.py:48` emits ordinary `RecoveryRequest`, not
   the protocol-specific order/shared-question requests. Local producer tests
   therefore do not prove that supervisor-admitted monthly jobs use receipts.
   Finish routing only after handoff/finalization and compatible rollout design.

2. **High — publication/coverage is not complete.**
   `history_publication.py:91` requires a persisted publish phase; tests seed
   that prerequisite. Orders stop at `HistoryHandoffPendingError`
   (`history_orders.py:346`). Questions lack real HTTP normalization and
   authoritative monthly publication proofs. Shipments/items remain explicit
   unresolved acquisition paths; do not reduce the twelve-month resource scope.

3. **Resolved locally — administrative retry correlation and deduplication.**
   `/sheets/sync-jobs` now reuses active seller jobs, handles concurrent unique
   index collisions, and exposes a seller-scoped status read at
   `/sheets/sync-jobs/{job_id}`. Focused API and schema-contract tests cover the
   sequential and cross-process races. This remains local evidence until the
   affected service image is deployed and observed.

4. **High — visible and automatic Sheets refresh is unproven.**
   `Config.gs:10` adds a manual menu; it does not execute the refresh on reopen.
   Node tests do not establish Google recalculation after same-text setFormula.
   A document lock does not protect against human edits between reread/write.
   Execute the separately scoped disposable-sheet probe before claiming success.

5. **Medium — some planning/evidence wording is stale.**
   The tasks header still says no size exception despite later explicitly
   authorized 650-line units. Design still labels receipt schemas as next and
   calls subprocess changes N/A although a Node test harness now exists.
   The historical audit's unbounded Apps Script finding has since been locally
   corrected. Preserve its history, but do not mistake it for current code.

All source paths in findings are relative to `modules/sheets/src/zeler_sheets/`
except Apps Script paths, which are under `modules/sheets/apps_script/sheetseller/`.
Findings are not permission to change code, trigger scopes or deployed services.

## TDD, assertion quality and coverage limitations

Apply-progress contains staged safety-net/RED/GREEN evidence, including explicitly
identified test-authoring mistakes that were not counted as behavioral RED.
Sampled retained RED logs for manual refresh and pending rendering show failures;
their current executable tests pass in this diagnostic. Historical chronology
and every task's TDD sequence were not independently reconstructed, so blanket
TDD compliance is not certified. Test-file existence alone is not RED evidence.

`test_pilot_formula_matrix_coverage.py:41` searches source strings and does not
execute formulas. Its inventory assertion must not count as behavior acceptance.
The newer 52-formula execution matrix improves this, but returned values and
matching concurrent/sequential cold results still do not prove positive data.
Publisher seeded-phase fixtures and gateway/service doubles likewise establish
bounded component behavior, not source discovery-to-visible-cell completion.
No complete assertion audit or changed-file line/branch coverage measurement was
performed; no coverage percentage or all-tests-real-behavior claim is made.

## Recommended next work

Return to bounded apply units: finish durable producer-to-publisher handoff and
final proof reconciliation; complete shared
question/provider and shipment/item/claims acquisition; then wire workers and
measure sustained lane fairness. Keep all current pending acceptance tasks open.
Obtain a different-author review for independent acceptance. Runtime validation
requires separate authorized rollout and add-on publication plus the full pilot
matrix and observation window. Compare intended commits with deployed
`sheets-api`/`sheets-worker` images when runtime evidence is available; this report
does not establish present image drift. No build, deployment, trigger or Google
resource mutation occurred. The report records unfinished implementation and
does not purport to authorize or forbid archival of that honest state.
