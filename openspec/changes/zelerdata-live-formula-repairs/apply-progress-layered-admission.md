# Apply progress: layered formula admission

Assigned task: 6.4 API and formula-intent portion. Queue reservation and runtime
factory configuration remain owned by the coordinating agent. Existing units
1–4, 5.1a, 5.3 and 5.5a retain their recorded status; this note supplements their
existing progress artifacts and does not replace them.

## Implemented behavior

- CALIDAD and CALCULADORA preserve their primary recovery intent and add explicit
  missing-enrichment IDs independently when base inventory also needs recovery.
- A current inventory response requests the next inventory sweep even when an
  explicit item enrichment request is present; a base inventory intent still
  suppresses duplicate inventory admission.
- All intents share a three-second request-local admission deadline, including
  sequential formulas in the batch endpoint, inside the existing 25-second outer
  formula deadline. An already expired deadline rejects even a synchronous queue
  fast path before it starts; cancellation preserves usable values.
- Bounded structured admission events report admitted, capacity, disabled,
  unsupported, invalid_request, storage_unavailable or deadline. No arguments,
  identifiers, tokens or raw exception text are logged. Public response flags
  and formula signatures remain unchanged.
- CALIDAD rejects a quality observation whose acquisition state explicitly says
  basis_mismatch. A still-fresh prior observation survives transient reacquisition
  failures, preserving existing partial-result semantics and its original time.

## TDD cycle evidence

| Behavior | Safety net | RED | GREEN / triangulation | Refactor |
| --- | --- | --- | --- | --- |
| Independent recovery and three-second admission | Existing API/quality suite: 123 passing | New suite: 8 failed, 1 passed before production edits | Initial 9 cases passed: missing/present base, quality/calculator, delayed admission, sanitized failure categories | Shared deadline and outcome helpers; focused suite green |
| Quality basis invalidation | Same baseline | Valid fresh basis_mismatch observation was incorrectly rendered numerically | Trusted, absent legacy state, transient and basis_mismatch cases pass; observation time preserved | No additional refactor |
| Exhausted shared deadline | Initial batch cancellation case passed | Stronger three-formula case admitted a synchronous third request after deadline | First admitted; second cancelled; third rejected before queue call; all usable values retained | Explicit elapsed check; focused suite green |
| Authenticated persistence harness | Existing API and queue integration patterns | Existing independent-intent RED covers changed API branch | Real isolated Mongo receives one inventory and one explicit job after repeated authenticated ASGI calls | No additional refactor |

## Work unit evidence

| Evidence | Result |
| --- | --- |
| Focused command | `MONGO_URI='mongodb://127.0.0.1:27028/zeler_layered_test?replicaSet=rs0&directConnection=true' uv run pytest modules/sheets/tests/test_formula_layered_admission.py modules/sheets/tests/test_formula_layered_admission_mongo.py modules/sheets/tests/test_formula_api.py modules/sheets/tests/test_formula_handlers_quality_calculator.py -o addopts='' -q` — 138 passed in 14.76 seconds |
| Runtime harness | Authenticated HTTP ASGI execution with the actual FormulaRecoveryQueue and isolated Mongo replica set on port 27028; two recalculations persist exactly two seller-scoped pending jobs, one per required acquisition scope. No production mutation. |
| Static checks | Ruff check passes and format check passes for the five owned Python files; mypy passes for API, quality handler and both new test files (four source files). `git diff --check` passes. |
| Rollback boundary | Revert only API admission changes, quality/calculator recovery-intent and basis-state changes, and their test changes. No migrations, queue documents, runtime images or unrelated working-tree changes are part of this unit. |

## Delivery boundary

Uncommitted work in the selected checkout, as authorized. Review as two bounded
behavior slices: handler recovery/basis semantics and API admission/deadline
semantics. The coordinating agent updates task 6.4 only after combining its
reserved-slot and runtime-factory work with this portion. Full repository gates,
independent SDD verification, deployment and live spreadsheet verification remain
outstanding; these focused results do not certify production recovery latency.

## Combined recovery regression follow-up

Root's broader run exposed six direct-helper request fixtures lacking the normal
HTTP request's `.state`. Added state to those fixtures without weakening API
behavior. Updated the four old inventory workflow cases for the approved batch
of 20 and explicit pending quality enrichment; retained membership, stale-source,
failed-ID, retry and coverage assertions. Added assertions that base inventory
makes no cost/quality requests and independently exposes enrichment recovery IDs
while base coverage is incomplete.

The initial selected run reported 4 failed / 72 passed from old sub-batch
expectations. Updated inventory cases then passed 4/4; the complementary recovery
selection passed 353 tests. Final combined verification:

`MONGO_URI='mongodb://127.0.0.1:27028/zeler_layered_test?replicaSet=rs0&directConnection=true' uv run pytest modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_formula_layered_admission.py modules/sheets/tests/test_formula_layered_admission_mongo.py modules/sheets/tests/test_formula_api.py modules/sheets/tests/test_formula_handlers_quality_calculator.py -o addopts='' -q`

Result: **567 passed in 100.60 seconds**, no skips. Ruff check and format check
pass for the updated recovery test file. No further production code changes were
needed for this follow-up.
