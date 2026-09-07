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

## Work unit: connect formula recovery to API and worker lifecycles

- `ZELERDATA_FORMULA_RECOVERY_ENABLED` enables the API queue and co-resident
  worker executor; default is disabled. Runtime queues accept/claim only
  implemented sources (currently questions), so unsupported orders/catalog
  cannot falsely report that a working recovery was requested.
- Reuses the existing poller supervisor with concurrent sync/recovery lifecycle
  management and a dedicated recovery health component. Search uses bootstrap
  identity; details reuse the worker's sheets gateway client. Startup ensures
  claim and expired-lease indexes, without adding a new service.
- New integration tests initially failed for absent startup/lifecycle wiring.
  Full authenticated HTTP -> durable Mongo queue -> supervised recovery -> HTTP
  integration exposed BSON precision loss: the recovered range failed to cover
  its original microsecond endpoint. Recovery intervals now round outward to
  BSON milliseconds. The next HTTP request succeeds after persisted proof, and
  the first HTTP request makes zero gateway calls.
- The real gateway raises its own GatewayRateLimitError for HTTP 429, unlike
  the earlier generic HTTP double; added a failing regression then included it
  in bounded transient retry handling.
- Focused recovery, HTTP and worker lifecycle tests: 51 passed in 3.48s;
  root Ruff, formatting and mypy pass. Full local replica-set regression:
  **3,590 passed, 9 skipped in 76.67s**; the same protected stock-time tests
  require their separate invocation, and Caddy has no required-key parameter.
- No production activation yet. Queue admission/schema, write fencing across
  competing recovery intervals/events, remaining sources and productive/live
  acceptance remain necessary before activating recovery as the full solution.
- Rollback boundary: activation flag plumbing, optional extra pollers, queue
  index/source selection, BSON interval rounding and corresponding tests. No
  production configuration/data migration has occurred.

## Work unit: atomic, fenced question recovery writes

- Real-Mongo regressions demonstrated rows persisting after lease expiry and
  partial rows after a later resource failed validation. Previously only the
  final marker/job state shared a transaction; data writes were outside it.
- Normalized question persistence now accepts an explicit session (rejected for
  other event types). Recovery acquires data outside the transaction, then
  commits every row, inventory readback, coverage and job completion together
  under the current attempt's lease. Failures roll back the complete unit.
- A separate regression demonstrated overwriting a coverage marker changed
  during acquisition. Compare the marker captured before remote acquisition
  inside the transaction; competing publication aborts without touching rows
  or the newer marker. Existing question freshness rules still apply.
- Verification: recovery, event-persistence and formula API tests **111 passed
  in 4.02s**, with three new failure scenarios reproduced before correction.
  Root Ruff, formatting and mypy remain clean. Production remains unchanged.
- Rollback boundary: optional question-only session propagation, recovery
  transaction scope/preimage guard and associated tests. Remaining admission,
  schemas, source expansion and live acceptance are not proven by this unit.

## Work unit: complete question and unit-cost reads

- Extended the real-Mongo boundary harness: questions stopped at 1,000 of
  1,001 stored rows; after correcting that, the 1,001st valid unit cost still
  resolved to NA solely because its source query stopped at 1,000 documents.
- Removed default truncation for find_questions and find_unit_costs; explicit
  limits remain an opt-in repository capability. Questions/KPI callers request
  complete ranges and cost callers can resolve all matching persisted costs.
- Harness proves seller isolation, an actual PREGUNTASKPI result of 1,001,
  and resolution of every one of 1,001 valid unit costs, not only list lengths.
- Verification: Mongo boundary, read-model, order/question handler and unit
  cost tests **74 passed in 0.75s**; root Ruff/format/mypy clean. No deployment.
- Remaining fixed/heuristic limits in catalog/history/other handlers still need
  review; this is not proof that all 52 formulas are complete. Large-input CPU,
  memory and live end-to-end response timing also remain unverified.
- Rollback boundary: the two reader default limits and the expanded Mongo
  boundary harness. No persistence schema or production data changed.

## Work unit: complete history rows and catalog sales inputs

- Six formula boundary tests first returned 1,000 of 1,001 rows: stockout
  duration, active-stock time, weekly stock, price history, catalog time and
  withdrawals. Their full-range calls now request all rows; five corresponding
  reader defaults no longer silently cap results. Seller/interval/coverage
  filters remain unchanged.
- Extended the actual local Mongo boundary harness for all five collections,
  including foreign-seller rows, to check more than test-double behavior.
- Catalog sales previously truncated at 5,000 orders. A failing 5,001-order
  case demonstrated undercounting in all six sales windows; that query now
  reads the complete requested range.
- Verification: Mongo boundary, remaining-formula, item/shipping/catalog and
  reader tests **63 passed in 5.09s**. Ruff, formatting and mypy pass globally.
- Other explicit item/shipping/catalog heuristics and source completeness
  guards still require inspection; this is not all-formula/live acceptance.
  Large-result latency/memory measurement remains pending.
- Rollback boundary: seven complete-range caller limits, five reader defaults
  and associated boundary regressions. No production state changed.

## Work unit: complete shipping and catalog snapshot queries

- Five boundary scenarios failed first: three catalog outputs returned only
  1,000 of 1,001 snapshots; seller shipping cost excluded the latest order after
  5,000 earlier ones and returned an old cost; Mercado Envios omitted that
  latest open label. These full-input queries now use no silent row cap.
- Catalog product/buybox reader defaults are complete; extended actual Mongo
  boundary checks for both collections and foreign-seller exclusion.
- Verification: Mongo boundaries, item/shipping/catalog, remaining formulas and
  reader tests **68 passed in 0.76s**. Root Ruff, format and mypy pass.
- This preserves the existing latest-cost, status/date and seller semantics;
  it does not prove productive source coverage or large-input response timing.
  Remaining heuristic SKU/item joins and catalog buybox enrichment are pending.
- Rollback boundary: five handler limit arguments, two reader defaults and
  their boundary tests. No production data or deployment changed.

## Work unit: complete SKU and buybox joins

- Actual Mongo test demonstrated sales and dashboard SKU resolvers both
  returning an empty SKU for a stored variation beyond their 500-row heuristic.
  They now read every seller/item-matching index row; ambiguity rules remain.
- Catalog's buybox join returned NA for stored winner data when 1,000 unrelated
  snapshots sorted first. Reused the exact-output catalog regression with that
  additional inventory; it failed before removal of the heuristic and passes
  afterwards, preserving all winner/price/competitor fields.
- Verification: Mongo boundary, core, order/question and remaining-formula
  tests **134 passed in 1.20s**. Ruff, format and mypy pass globally.
- Rollback boundary: three heuristic limit arguments and their regressions.
  No runtime activation, production data change or live-completeness claim.

## Work unit: preserve order partial-content evidence through gateway

- Official source checked: https://developers.mercadolibre.com.mx/gestiona-ventas
  (indexed text available; direct fetch returned 403). The late-September 2026
  deprecation notice concerns the current order-shipment view; do not interpret
  it as proof that every /orders endpoint is being retired. Hosted shipment
  responses are arrays. Order partial responses use HTTP 206 and
  X-Content-Missing to identify absent fields.
- Current proxy already forwards X-Api-Version/X-New-Domain request headers,
  but stripped X-Content-Missing on responses. New authenticated integration
  test reproduced the missing header; explicitly forward it while keeping
  unrelated response headers excluded. Status and JSON body remain unchanged.
- Verification: gateway-flow and client tests **17 passed in 3.50s** using local
  Mongo and mocked upstream; root Ruff, format and mypy pass.
- Important remaining gap: fetch_resource returns only JSON, so Sheets source
  acquisition still needs explicit partial-content/field-completeness handling.
  No hosted order-shipment acquisition/normalization was found in Sheets. Do
  not mark the new-order-contract requirement verified from this transport fix.
- Rollback boundary: one response header and its authenticated regression.
  Gateway image must eventually be rebuilt/deployed alongside relevant Sheets
  images; no image build, deployment or live contract test happened in this unit.

## Work unit: preserve known identities during sparse order updates

- A regression with an existing order and a newer response containing empty
  buyer/shipping objects failed before saving the new status: buyer identity
  validation ran without consulting known Mongo state.
- Read the same seller/order inside the existing fenced transaction before
  canonical normalization. Missing/empty objects can reuse observed buyer and
  shipment identifiers; explicit null shipping and no_shipping do not revive
  a previous shipment. Existing monotonic write checks and SKU refresh remain.
- No unknown buyer ID is fabricated for a new partial order. Such orders still
  require field-aware recovery; this fix is not complete 206 handling and does
  not establish completeness of any order interval.
- Verification: persistence, historical backfill and recovery tests **120 passed
  in 4.15s**, including actual Mongo transactional fallback, explicit-clear and
  no-shipping controls. Ruff, format and mypy pass globally.
- Rollback boundary: transaction-local identity fallback, checkpoint timestamp
  normalization and associated tests. No schema change or production mutation.

## Runtime release — 2026-09-07, source 35bed8c

- Root regression with local Mongo: **3,611 passed, 9 skipped in 70.99s**.
  Eight protected replica-set scenarios were then run with their explicit local
  URI and no ambient MONGO_URI: **8 passed in 3.55s**. The remaining skip is
  the Caddy service's empty required-key case. Ruff, format (500 files) and
  mypy (500 source files) pass. Deprecation warnings remain.
- Published exact source commit
  `35bed8c8fea1bbaef9bd481f36709dd0128e3e9a` to GitHub main.
  Built only gateway, sheets-api and sheets-worker, one verified Cloud Build
  per image, from the connected repository at that revision; no local image
  build or upload of the dirty checkout.
- All three builds succeeded. The repository provenance verifier confirmed
  each image's digest, successful build, exact source revision and connected
  repository. Build IDs and immutable image digests:

| Service | Cloud Build ID | Image digest |
| --- | --- | --- |
| gateway | 55f419ff-9898-4fc2-af29-2d30af1a70ce | sha256:2d4a514cab2d3ddca7e95109aeedc1e11e41115f8c09fddedd850aa0dc9ef130 |
| sheets-api | 277bbd50-5a8e-48cb-a8d4-917f9f320fbf | sha256:b03d53422a57202974f77e70d651731ca01317aa7d3e7448d4592c71364defaf |
| sheets-worker | 647379f2-4a81-41a5-8d04-86d5b3796316 | sha256:ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646 |

- Image repository prefix:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`.
  Each service was replaced individually with `up -d --no-deps`, after
  free-space preflight and an exact-one Compose image replacement assertion.
  Preflight free space was 7.5 / 7.1 / 6.6 GiB before the successive pulls.
- Rollback authority is each previous running image, not a moving tag:
  gateway `sha256:2e06dd93345e5b3f2cb3f6385e74c5227d3a41fd785de908c06d31402d3c8a68`;
  sheets-api `sha256:cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc`;
  sheets-worker `sha256:b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931`.
  Compose backups remain at
  `/opt/zeler-platform/docker-compose.yml.pre-<service>-35bed8c`.
  Revert only the affected service image using the section 5 runbook, then
  prove its running digest, health and relevant smoke. No Mongo volumes or
  unrelated product services were altered by deployment commands.
- Gateway initially returned HTTP 502 during startup, then became healthy
  with zero restarts and HTTPS health 200. A real authenticated, read-only
  questions scan through the new gateway returned HTTP 200, 50 rows,
  total 252 and a scroll cursor; no question contents or credentials emitted.
- Sheets API became healthy with zero restarts. HTTPS health returns 200;
  Mongo, RabbitMQ, registry and claims-DLQ checks all pass. Live inventory is
  HTTP 200 with 52 implemented formulas. Inventory is not execution proof.
  Recovery flag remains disabled. No smoke credential is configured in the
  API container; authenticated all-formula execution remains unproven.
- Final runtime inspection: all three running digests equal the verified
  images above, all containers healthy, all restart counters zero. The worker
  health endpoint reports ready, RabbitMQ ok and sync_jobs_poller ok; recovery
  is also disabled in the worker. Root disk has 6.1 GiB free after deployment.
- Read-only readiness check inside the new worker remains degraded:
  7 missing, 9 reconciled, 1 stale; 17 productive-window blockers. No missing
  data was repaired merely by deploying code. This release proves image
  correspondence and basic operational boundaries, not global data readiness,
  complete formula execution, new-order migration or the 30-second SLA.
- Next: complete field-aware order acquisition and asynchronous persistent
  recovery, then verify the pilot window and authenticated formula results.
  The final Google Sheet, existing app surfaces and minimum sensitive-data
  controls remain mandatory. A documentation-only follow-up commit does not
  require rebuilding these images; future runtime changes do.
