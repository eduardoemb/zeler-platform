# ZelerData stabilization evidence

Goal source: user attachment `pasted-text-1.txt`, confirmed grill summary
`grill/estabilizar-zeler-platform/summary`. Execution uses Goal, not SDD.
User authorized commits, Cloud Build, GCP deployment and necessary runtime work.
Keep unrelated `.codegraph/` files untouched in both repositories.

## Acceptance ledger

- [ ] All 52 formulas: contracts, truthful values, HTTP production smoke.
- [ ] Representative formulas in a real Google Sheet and existing app surfaces.
- [ ] Async Mercado Libre recovery persisted in Mongo for subsequent queries.
- [ ] Required coverage/freshness; optional NA; explained unavailability.
- [ ] Mongo schemas/indexes/persistence/isolation and actual service operations.
- [ ] Purpose-complete data and minimum PII controls, including deletion.
- [ ] Current official orders API contract verified/migrated as necessary.
- [ ] Entire custom-function execution below 30 seconds; measured p95 budget.
- [ ] Evidence-backed simplification and preserved verified consumers.
- [ ] Deployed source/image correspondence and final regression/smoke.

Pilot: seller `82453304`; initial historical window 2026-08-08 through
2026-09-06, plus current snapshots. Other products are out of scope.

## Baseline — 2026-09-07

- Backend main: `c5a2e097e765a083fa1fff7fdec3782ef81fd998`.
- GitHub and GCP access verified; platform-vm RUNNING.
- Docker lists gateway, Sheets API/worker and Mongo as healthy. Root disk has
  7.5 GiB free. Health does not prove formula data readiness.
- Runtime read-only command, inside the Sheets worker:
  `/app/.venv/bin/python -m infra.operations.zelerdata_read_model_status
  --seller-id 82453304 --confirm-approved-runtime --readiness`.
- Command returned degraded (exit 1): 7 missing, 9 reconciled, 1 stale;
  all 17 inventory entries fail its current productive-window check.
  Orders/questions coverage ends in July, multiple snapshots in June;
  devoluciones is stale with source `devoluciones_operation_acquire`.
  This is marker evidence, not proof that underlying collections are empty.
- Formula API currently returns DATA_UNAVAILABLE without scheduling recovery
  (`modules/sheets/src/zeler_sheets/api.py`, `_execute_formula_payload`).
- Full baseline pytest completed with exit 0. Several integration checks were
  skipped because local Mongo is not the expected rs0-dev replica set; baseline
  success does not prove Mongo integration. Session handle 72403 is terminal.

## Work unit: complete item, SKU and order reads

- Found silent default truncation: item/SKU readers returned only 500 rows and
  order reads only 1,000, potentially understating formula output and totals.
- Added three boundary regression scenarios: 501 item rows, 501 SKU rows,
  1,001 orders. All failed against the original defaults with observed counts
  500, 500, 1,000 respectively.
- Default reads now consume the complete seller/request-filtered cursor.
  Explicit caller limits remain supported; other explicit and default caps
  still require audit, so this does not close the global completeness gate.
- Focused repository/core/order/calculator tests: 109 passed in 0.32s.
  Ruff check/format and focused mypy pass.
- Production validation pending: larger results must be measured for memory,
  response size and the end-to-end 30-second deadline before release.
- Runtime harness: dedicated local Mongo 7 replica set, loopback port 27028,
  container `zeler-goal-mongo`. Real Motor cursor reads return all 501/501/1,001
  rows and exclude a second seller; 1 integration test passed. Random test DB
  is removed by the test after use, never using production configuration.
- Mongo/schema/drift/formula subset with dedicated local connection:
  46 passed in 2.51s (no skips).
- Rollback boundary: the three default limits in formulas/read_models.py and
  their boundary tests; no schema or persisted-data changes.

## Remaining baseline quality findings

- Root Ruff check passes. Root format check flags the existing
  tests/integration/test_stock_time_forward_execution_rs0.py.
- Root mypy found pre-existing errors in stock-time schema tests (2),
  source-gated writer tests (3), reconciliation quota counter typing (1), and
  quota advance test re-export (1). New Mongo test client annotation fixed.
- Runtime Sheets API digest: cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc.
- Runtime Sheets worker digest: b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931.
- No loaded zelerdata systemd units were listed; this alone does not exclude a
  live manual reconciliation process. Source provenance still needs resolving.

## Next evidence/actions

1. Finish baseline checks and inspect deployed image/source bindings.
2. Inspect actual marker aliases (inventory uses sheets_item_formula_rows,
   formula readers use item_formula_rows) before inferring missing data.
3. Inspect active reconciliation processes before any overlapping repair:
   recent devoluciones acquire could represent another running operation.
4. Implement recovery with failing behavioral tests first, reuse existing
   reconciliation and keep the formula path independent of remote API latency.
5. Continue every acceptance item above; a passing narrow test is not closure.

## Work unit: durable recovery request boundary

- Missing-model exceptions now carry structured model and normalized range.
  Three new scenarios failed first, then passed after adding the metadata.
- Mongo-backed recovery queue coalesces exact seller/model/range requests with
  deterministic IDs, claims jobs atomically, renews leases, fences completions
  from expired attempts and applies a 15-minute terminal cooldown.
- Real Mongo tests verify 20 concurrent requests coalesce, seller separation,
  exclusive claims, expired-attempt fencing and cooldown rescheduling.
- API can use an injected queue only after token/seller validation. Enqueue is
  capped at one second; response remains DATA_UNAVAILABLE with an explicit
  update-requested message. The authorization/API regression failed before
  wiring and passed afterwards.
- 73 focused API, recovery, model and handler tests passed in 1.35s. Focused
  Ruff and mypy pass.
- NOT production-enabled: worker execution, indexes/schema, retry/queue limits,
  full model coverage, startup wiring and end-to-end recovery remain pending.
  No success claim for automatic data recovery until the executor proves it.
- Next reuse point: historical_meli_backfill currently always fetches orders,
  even for questions/catalog; broad reconciliation also acquires a devoluciones
  lease. Avoid blindly invoking that broad path for each missing model.
- Rollback boundary: new recovery module and tests, optional API scheduling
  helper, and exception metadata. No production schema/data changes occurred.

## Work unit: question recovery executor

- Added bounded question scan/detail recovery through gateway clients, reusing
  SheetsEventPersistence for normalized writes. Search and detail clients can
  retain their existing distinct module identities.
- Tests first demonstrated missing execution, false coverage with extra local
  rows, rejection of a valid reused scan cursor, and acceptance of expired
  proof. Each corresponding correction now passes.
- Executor verifies remote total/unique identities, date and seller scope,
  required answer detail, and exact persisted inventory before publication.
  Marker publication and job completion share a Mongo transaction guarded by
  the current lease token. Explicit proof expiry now blocks reconciled reads.
- Real-Mongo recovery + reader + HTTP tests: 44 passed in 1.82s; focused mypy
  and Ruff pass. Gateway calls are controlled doubles in these tests.
- Live read-only verification from approved worker container: scan returned
  total 252, first and second pages 50 each, scroll available. Detail retrieved
  with the existing sheets identity had matching seller/question scope and
  a creation date. No production data was written.
- A prior wider diagnostic ended with HTTPStatusError without a captured
  status; it is not evidence of complete live recovery. Narrow subsequent scan
  and detail checks succeeded. Full date-window counts remain unverified.
- Still pending: other recovery sources, startup wiring, schemas/indexes,
  bounded retries/queue admission, deletion lifecycle and deployment. Do not
  deploy the executor as full ZelerData recovery yet.
- Rollback boundary: recovery_worker.py, its tests and optional valid_until
  enforcement in read_models.py. No production write or deployment occurred.

## Work unit: bounded formula HTTP execution

- Individual and batch endpoints now share a 20-second overall async deadline,
  covering token validation, data reads and execution; batch uses one budget
  for the whole batch. Timeout cancels work and returns retryable INTERNAL/503.
- Tests with a nonterminating handler first failed at the test watchdog and
  now prove cancellation and a stable response for both endpoints.
- Shared payload execution removes duplicated argument wiring between routes.
- Formula API tests: 30 passed in 0.62s; focused Ruff/mypy pass.
- This does not prove the end-to-end 30-second limit: synchronous CPU work,
  JSON serialization, network and Apps Script overhead still need live timing.
- Rollback boundary: deadline constant, two route wrappers/shared execution
  closure, timeout response and the two timeout tests. No data migration.

## Baseline quality corrections

- Corrected mixed-type proof annotations, schema fixture typing, optional
  immutable mapping assertions, canonical readback import and formatting.
- Root Ruff check and format now pass; mypy passes for all 500 source files.
- Focused affected tests: 38 passed in 0.31s. Runtime behavior is unchanged:
  corrections are typing/test expectations/formatting only.
- Full regression is running against the dedicated local Mongo replica set;
  record terminal result before treating the overall gates as satisfied.

## Work unit: real-Mongo regression corrections

- First full replica-set regression: 3,578 passed, 3 failed, 9 skipped in
  66.73s. A separate invocation overriding pytest addopts failed collection
  because it removed the repository's required importlib mode; it is not a
  product defect. Subsequent runs preserve repository options.
- Reproduced all three failures in isolation. The proxy test seeded a limit
  of 60 while runtime defaults to 600; it now explicitly selects its test
  limit. The quarantine assertion now requests timezone-aware BSON decoding.
- Actual recovery defect: prepared-window replay compared naive BSON UTC to
  aware domain dates; read-next also rejected default Mongo decoding. Normalize
  only database-read dates, keeping timezone validation on domain inputs.
- Existing failing transaction test now proves replay, resume and obsolete
  owner rejection against actual Mongo. Focused suite: 13 passed in 0.74s;
  root Ruff, formatting and mypy remain clean (500 source files).
- Rollback boundaries: recovery date decoding is independent of the two test
  fixture corrections. No production data or deployment changed.
- The first rerun was invalidated by the dedicated local Mongo exhausting its
  default file-descriptor limit (WiredTiger error 24), not a disk-space or
  production failure. Preserved its volumes and stopped container as
  `zeler-goal-mongo-low-ulimit`; replacement `zeler-goal-mongo` shares those
  volumes with explicit `nofile=65536:65536`. Never run both concurrently.
- The eight protected stock-time transaction tests require `MONGO_URI` absent
  and a loopback `ZELER_RS0_TEST_URI`. With the repaired local replica set:
  all 8 passed in 3.55s. The normal root invocation skips them by design.
- Final full regression after fixture/decoding corrections and local Mongo
  repair: **3,581 passed, 9 skipped in 66.62s**. Eight skips are covered by the
  separate successful protected invocation; the remaining Caddy parameter has
  no required keys. Existing asyncio/anyio deprecation warnings remain (348).
  Root Ruff check, format check and mypy also exit zero.
- Next functional work remains recovery admission/retries, source coverage and
  worker/API startup integration. These green gates do not prove production
  recovery, 52 live formulas, app surfaces or a real Google Sheet.

## Work unit: bounded automatic recovery retries

- Two new real-Mongo tests failed before implementation: transient gateway
  failures required another formula request, and repeated worker crashes had
  unlimited attempts. Both are now corrected.
- Retry connection/timeouts, HTTP 429/5xx and database failures with persisted
  30/60-second backoff and at most three claims per request cycle. Expired
  third attempts become failed; obsolete owners retain no completion rights.
- Non-transient source rejections and incomplete source inventories fail closed.
  Failure reasons are allowlisted codes, not exception text or remote payloads;
  successful transactional completion clears the prior failure reason.
- Verification: recovery and formula API tests **43 passed in 2.69s**, using
  actual local Mongo and controlled upstream responses. Includes 403 versus
  429/503 retry behavior, automatic resume, coalescing and lease fences.
- Runtime activation remains pending; this changes persisted queue execution
  behavior but does not yet connect the API/worker startup. Rollback boundary:
  retry/attempt logic in recovery.py, worker error classification and associated
  tests; no production migrations or deployments have occurred.
