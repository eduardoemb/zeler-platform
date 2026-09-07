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

## Work unit: do not stop order acquisition at a short page

- Three new regressions initially failed: a short first page silently returned
  one order while the source total was two; an empty subsequent page and a
  repeated identity were never inspected. Two further regressions proved a
  changed or disappearing total could also be accepted as complete.
- Order acquisition now advances by the received row count, continues short
  pages when the source total requires more rows, and rejects premature empty
  pages, missing/repeated identities and changes to a previously observed total.
  Explicit max_orders remains an operator cap, not proof of full coverage.
  Sources without total metadata still need a separate completeness contract.
- Verification: historical backfill, event persistence and recovery tests
  **125 passed in 4.22s**; root Ruff, format and mypy pass. The five new
  pagination scenarios use an injected source, not production fault injection.
- Runtime boundary evidence: from the approved worker container, a read-only
  gateway search for the pilot and Aug 8–Sep 6 returned HTTP 200, one requested
  row and total 100. One corresponding order detail returned HTTP 200, no
  X-Content-Missing header, and present buyer/seller/shipping/items/payments/
  created/updated fields. Output contained only status, counts and presence
  booleans. This is not complete interval or HTTP 206 acceptance evidence.
- Rollback boundary: _search_orders pagination/completeness checks and their
  tests; no schema or persisted-data migration. The new code is not deployed.
  Both Sheets images include this module and will need new Cloud Build images
  before productive acceptance of this correction; gateway has no new change.
  Verify complete pilot acquisition and truthful unavailable results after
  that deployment. Field-aware partial detail recovery remains unfinished.

## Work unit: enforce expiration in generic formula freshness checks

- Generic productive-model checks accepted expired or malformed valid_until
  values whenever fresh_until covered the requested end. Four new regressions
  failed for fresh/reconciled markers; two valid-proof controls already passed.
- The generic gate now rejects expired/malformed explicit validity, matching
  the existing reconciled-range gate. Existing markers without valid_until
  are unchanged; migrating those proofs and guarding all order consumers
  remain separate incomplete requirements.
- Verification: repository, item/shipping/catalog, remaining-formula and
  calculator tests plus the actual Mongo boundary harness **82 passed in
  0.94s**. Mongo demonstrates BSON-decoded expired proof rejection followed
  by acceptance after valid renewal in a disposable local test database.
  Root Ruff, format and mypy pass.
- Rollback boundary: four-line validity check and associated regressions;
  no production data writes or schema migration. Not deployed: Sheets API
  needs a new Cloud Build image and live expired/valid proof acceptance after
  this change. Keep it with the pending Sheets release; gateway is unchanged.

## Pilot data comparison — approved runtime, read-only

- Gateway pagination returned 100 unique order IDs in the requested Aug 8–
  Sep 6 range with a stable total. All 100 are present in seller-scoped Mongo;
  the Mongo date-window count is also 100. None of those persisted orders
  lack buyer_id, nonempty items or last_updated. Their 97 unique shipment
  references all resolve in the seller-scoped shipments collection.
- These results contradict an assumption that the degraded status report
  implies absent orders or shipments. Its 17 productive-window blockers are
  marker evidence, not 17 proven underlying data defects. Actual order values,
  shipment fields and the formula-specific date/freshness contracts must be
  checked before repairing or certifying coverage.
- A paced, read-only comparison fetched all 100 order details through the
  gateway, then compared the current canonical projection against Mongo.
  All normalized successfully without partial-content responses. 51 matched
  exactly; 49 differed by list comparison. Differences were confined to tags
  (49) and last_updated (4). Buyer/shipment/pack identifiers, status, creation
  and closing dates, amounts, normalized items and feedback matched in all
  compared documents. Acquisition-only sale_fee_synced_at was excluded;
  list ordering was not normalized. This is not proof that all 49 differences
  are business-value changes, nor proof of new-order-contract completeness.
- A separate search-result tag comparison over the same 100 orders found
  99 identical lists and one changed set: delivered replaced not_delivered.
  Search and detail responses therefore must not be treated interchangeably
  when explaining these differences. No stored order or marker was modified.
- A bounded follow-up of 10 actual detail responses compared tags as sets:
  9 differed only in ordering, 1 had different tag values. Do not report the
  earlier 49 list differences as 49 business-data defects. Future complete
  reconciliation comparisons must normalize set-valued tags; the four
  updated timestamps and any substantive tag drift still need recovery.

## Work unit: retain question coverage through source revalidation

- Approved-runtime preflight found no recovery jobs and automatic recovery
  disabled. The current questions marker is reconciled from June 1 through
  July 11, without an explicit expiration. Recovering only Aug 8–Sep 6 would
  replace that marker and remove previously recognized historical coverage.
  No production job or data write was started during this preflight.
- A new actual-Mongo regression failed: recovery fetched only the August
  question, omitting June and the July gap. The worker now expands acquisition
  to the union of a still-valid prior reconciled interval and the requested
  interval, fetching details throughout the gap as well. Coverage is published
  only after full source acquisition and the existing atomic readback checks.
- The reverse-direction regression also passes: an older query cannot erase
  a newer proven interval. Expired/invalid prior proofs are not promoted by
  this extension. Existing 10,000-source-question and 240-second execution
  bounds remain; preserving a wider interval may require more source calls
  than the requested range. Source failure leaves the prior proof untouched.
- Verification: recovery and read-model suites **36 passed in 4.47s**, with
  real Mongo transactions and mocked MercadoLibre source responses. Root
  Ruff, format and mypy pass. No schema change or extra coverage store.
- Rollback boundary: prior-range acquisition expansion and its bidirectional
  regressions. Not deployed. Build the pending Sheets API/worker release from
  its exact main commit, then run one controlled pilot recovery with automatic
  recovery still disabled, and prove completion, persisted values and a second
  formula query without source calls. Automatic admission controls and the
  other recovery models remain unfinished; this is not global activation.

## Runtime release and first controlled recovery — source 4f65d6d

- Regression: 3,624 passed, 9 skipped in 70.84s; protected replica-set suite
  separately 8 passed in 14.87s. Root Ruff, format and mypy pass.
- Verified Cloud Build source: 4f65d6db950f00e97127ffc546dfb7506ced57ec.
  API build 45e06398-5e7d-4ebd-a31f-dab8db79c57f produced
  sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f;
  worker build e0a08c5b-9cd0-463e-a018-76e25f8bddb3 produced
  sha256:9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5.
  Both passed digest/build/source/connected-repository provenance checks.
- Both running digests now match these images; both healthy, zero restarts.
  API HTTPS health returned 200/ready. Targeted replacements used the runbook
  preflight and exact-one-image checks. Disk free after release: 5.1 GiB;
  recheck before further pulls. No other product was deployed.
- Rollback API digest: b03d53422a57202974f77e70d651731ca01317aa7d3e7448d4592c71364defaf;
  rollback worker digest: ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646.
  Compose backups use suffix .pre-<service>-4f65d6d. Images use the same
  Artifact Registry service repositories recorded above.
- One controlled recovery job was persisted for pilot questions, Aug 8–Sep 6:
  ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d.
  Automatic recovery remains off. It failed source_incomplete after five
  search calls and one detail, 1.281 seconds; no completion was published.
  The existing June 1–July 11 reconciled marker remained unchanged.
- Read-only diagnosis identified matching question/seller identities, valid
  answer/schema, but search/detail creation times differed by 435 microseconds
  within the same BSON millisecond. Exact datetime equality rejected the row.

## Work unit: compare question timestamps at persistent precision

- New actual-Mongo regression reproduced the 435-microsecond failure; exact
  timestamps passed, and a different-millisecond control remained rejected.
- Recovery source dates now normalize to UTC BSON milliseconds, consistent
  with persistent request boundaries. Seller/identity checks and validation
  of explicit timezone remain intact. This is not a general time tolerance.
- Recovery/read-model suites: 38 passed in 4.30s. Ruff, format and mypy pass.
  Test Mongo had stopped during the environment transition; only the task-owned
  current container was restarted, not the old container sharing its data.
- Rollback boundary: source-date millisecond normalization and its regression.
  Worker rebuild and controlled retry still required for live acceptance.
  The failed durable job must not be confused with successful persistence or
  authenticated HTTP/Google Sheets formula verification.

## Corrected worker release — source 0b83408

- Cloud Build 3b766f92-da1d-48ca-ba90-125a32b03e4b succeeded from exact
  source 0b8340864946ab5dfef9c5c11319fcec095e627f. Provenance verifier
  confirmed the connected repository, build, revision and immutable digest
  sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee.
- Only sheets-worker was replaced, after preflight at 5.1 GiB free and an
  exact-one Compose replacement. Running digest matches, container healthy,
  zero restarts, worker health ready; automatic recovery remains disabled.
  Rollback image is the prior worker digest 9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5;
  backup suffix .pre-sheets-worker-0b83408. The API remains on its verified
  4f65d6d image; this correction changes only worker-executed code.
- Post-pull disk free is 4.6 GiB. Restore the 5 GiB preflight margin before
  another pull; no further image build is implied by this operational record.
- Browser-use is installed but the CLI differs from the skill's current
  syntax: it exposes --connect, not a connect subcommand. An isolated
  zeler-goal session using --connect could not find Chrome remote debugging.
  Asked the user whether to enable their Chrome debugging or select a profile
  for managed Chromium. No cookies/credentials were extracted and no UI or
  real Google Sheet acceptance is claimed from this diagnostic.
- Removed only the unused local copy of original Sheets worker digest
  b2f820af4a5b0054ef084512430fb385684a078d918238827d3ffc2896008931 after
  confirming no container referenced it. It remains recoverable from Artifact
  Registry. Recent rollback images and all volumes were retained. Free disk
  returned to 5.1 GiB.
- Retried the same job only after its cooldown elapsed. It fetched six search
  pages and 50 details, then failed source_incomplete in 15.275 seconds.
  A read-only diagnostic stopped before transaction creation and confirmed
  all 50 source details normalize successfully, but Mongo has 52 rows in the
  expanded interval. The marker remained unchanged; no recovery completion.
- Direct detail checks of the two extra numeric question IDs returned HTTP
  200, matching question identities and dates, but explicit nonempty numeric
  seller IDs different from the pilot. Both are ANSWERED. This confirms two
  misattributed question records, not missing API data. Do not drop the scope
  check or silently accept these records to make recovery pass.

## Work unit: reject explicit foreign ownership during question persistence

- A new regression reproduced the write boundary flaw: a resource naming a
  different seller was normalized under the caller's seller without rejection.
- Canonical question normalization now rejects an explicit source seller that
  differs from the requested seller, before any question or marker write.
  Historical callers omitting seller_id remain supported; this does not prove
  ownership for absent-source-owner payloads or close the broader isolation
  audit for other resources.
- Event persistence, historical backfill and real-Mongo recovery tests:
  130 passed in 4.28s.
  Root Ruff, format and mypy pass.
- Rollback boundary: explicit question-owner validation and its regression.
  Worker deployment and backed-up repair of exactly the two confirmed foreign
  rows remain required. No reassignment to another user/account is authorized
  by this repair, and no production row has yet been removed.

## Verified question recovery and ownership repair — source abf84b4

The controlled pilot question recovery now completes, and all 50 persisted
documents match fresh canonical Mercado Libre details. This proves the question
recovery path only; automatic recovery remains disabled and global acceptance
items above remain open.

- Cloud Build `4aa66e34-b70b-4244-965a-4d9ebace97fa` succeeded from exact
  source `abf84b4b00912f16beb5aeae13fd49f7c655abf0`. The provenance verifier
  matched connected repository, revision, build and worker digest
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`.
  Only sheets-worker was replaced. Running digest matches; healthy, zero
  restarts, internal health HTTP 200/ready. API remains on source 4f65d6d.
- Before replacement, exactly two complete original foreign-question rows and
  source ownership proofs were backed up inside the VM at
  `/var/lib/zeler-platform/repairs/question-owner-abf84b4.bson` (root, mode
  0600, parent 0700). No payload or foreign identity left the runtime. This
  restricted backup is not evidence of application-level encryption; account
  for it and its container copy in the final retention/deletion hardening.
- Fresh source detail checks reconfirmed both foreign owners and matching IDs
  and dates. A Mongo transaction compared both full rows against the backup
  before deleting exactly those two pilot-scoped rows. Neither falls inside
  the previously validated June 1–July 11 coverage; the prior marker was
  compared and retained unchanged. Expanded-interval inventory became 50.
  No record was reassigned to another seller. Removal is recoverable from the
  restricted backup, but restoration would require a separately justified,
  ownership-aware repair, not blindly reinserting the misattributed records.
- The same job `ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d`
  was retried after its cooldown, with no other pending/running recovery job.
  Six search calls and 50 detail calls completed in 8.281 seconds. Transactional
  publication recorded 50 questions and coverage June 1–September 7 exclusive;
  exact persisted/source identity sets match. Proof expires after 15 minutes;
  this successful run is not a promise of indefinitely fresh coverage.
- Two subsequent internal PREGUNTASKPI queries for August 8–September 6 read
  Mongo and returned 3 questions, in 0.0171s and 0.0040s. Recovery-client call
  counters did not increase. These are operator diagnostics, not authenticated
  HTTP/Google Sheets acceptance or a measured end-to-end p95.
- An independent read-only pass fetched all 50 details again and compared
  BSON-normalized canonical documents with Mongo: 50 exact matches, no field
  differences, all source sellers match the pilot.
- Rollback worker digest is
  `sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee`;
  Compose backup suffix `.pre-sheets-worker-abf84b4`. A code rollback does not
  restore removed data. Disk free after pull is 4.6 GiB: restore the 5 GiB
  preflight margin before another pull; retain Mongo volumes and rollback images.
- Authenticated smoke remains pending. Its existing host runner requires the
  documented human readiness/authorization gate and an approved platform user
  identity; no runner invocation or credential workaround was performed.
- Post-release regression: `MONGO_URI=<task-owned loopback replica set> uv run
  pytest` finished with 3,627 passed, 9 skipped in 69.24s. The eight protected
  stock-time replica-set tests were then run with MONGO_URI unset and the
  dedicated ZELER_RS0_TEST_URI: 8 passed in 3.54s. The remaining skip is the
  Caddy contract's no-required-keys case. Ruff check, format (500 files), mypy
  (500 files) and diff whitespace checks pass. This evidence-only update needs
  no additional image; the affected worker source already matches its verified
  deployed image.

## Work unit: reject foreign ownership during order persistence

- Following the confirmed question contamination, inspection found that order
  normalization also overwrote the source owner with the caller's seller.
  Four real-Mongo scenarios failed first because foreign orders were accepted.
- Canonical order normalization now checks both `seller_id` and Mercado Libre's
  `seller.id` independently. Either explicit foreign value rejects the write;
  a matching alias cannot conceal a contradictory one. The error contains no
  source payload or seller identity. Missing-owner partial payloads retain their
  existing contract; absence is not proof of ownership or complete source data.
- Real transaction tests exercise both an empty collection and an existing
  same-seller order, proving rejection cannot create or replace an order. The
  matching-owner control persists successfully. Existing sparse buyer/shipping
  fallback remains covered by the adjacent real-Mongo regression.
- Recovery, event persistence and historical backfill suites: 134 passed in
  5.13s. Root Ruff, format and mypy pass (500 files). Runtime harness for this
  unit is the task-owned local Mongo replica set; no production order mutation
  is part of the test.
- Rollback boundary: the ten-line order-owner normalization guard and its
  regression. The worker is the identified runtime consumer; build and verify
  its next exact main image before claiming production protection. This does
  not implement order recovery, field-aware HTTP 206 handling or all-resource
  isolation. Those remain required before global acceptance.

## Order ownership guard deployed — source d145d61

- Worker Cloud Build `b40aeff1-ac67-4c7a-88cd-fa93e77f25d7` succeeded from
  `d145d61d887c2f4b9a036cfbf3ac73b5416f59e7`. Connected repository, exact
  source, build and immutable digest passed provenance verification:
  `sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`.
  Only sheets-worker was replaced. Running digest matches, healthy, zero
  restarts, health HTTP 200/ready. Three pure in-memory owner rejection cases
  also passed inside the deployed image, without production database writes.
- A separate runtime read-only pass checked details for all 100 Mongo orders
  in the August 8–September 6 pilot window. All 100 source owners matched the
  pilot; none were foreign or missing. No production order repair was needed.
- Removed only the unused local worker image
  `sha256:9903cd1ddcb932e6f252f0a95445f60e41e9d2478910407345fff192bcf641e5`
  after verifying no container referenced it and the Artifact Registry copy
  still existed. This restored 5.1 GiB preflight capacity. No volumes were
  removed. After the targeted pull, free space is again 4.6 GiB; restore the
  runbook floor before another image pull.
- Worker rollback digest:
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`.
  Compose backup suffix `.pre-sheets-worker-d145d61`. The previous question
  repair backup remains on the VM, root-owned mode 0600, 1,234 bytes. Automatic
  formula recovery remains disabled. No other product or API was deployed.
- Full regression: 3,631 passed, 9 skipped in 70.26s; protected replica-set
  suite separately 8 passed in 3.36s. Static gates remain clean. This release
  evidence changes no executable source and needs no additional image.

### Next functional gap: complete order ranges and recovery together

Inspection of `handlers_orders_questions.py` found that its eleven order/sales
handlers call `find_orders` without a coverage check; unlike its two question
handlers, they can calculate a successful result from an incomplete range.
The repository method and HTTP dispatcher do not add that check. Other handler
groups already have some generic order freshness checks, so audit per consumer
rather than infer coverage from a single helper.

The next implementation must pair truthful range validation with persistent
order recovery, not just add a gate that leaves recoverable data unavailable.
Reuse the existing guarded order writer and seller isolation. Its transaction
is coupled to the devoluciones operation lease: do not bypass it to reuse the
question transaction implementation. Handle partial source responses and prior
Mongo fields explicitly. The last-sale handler requests from 1970; applying the
queue's 90-day request limit blindly would make it permanently unrecoverable.
All-history absence and latest-known-sale evidence need distinct treatment.

## Work unit: atomic order recovery publication prerequisite

- Four new real-Mongo scenarios first failed because the order writer rejected
  all external sessions. Covered order writes can now join an existing active
  transaction while retaining the same server-time operation lease guard.
  Calls without a session retain the existing owned-transaction path.
- Commit, deliberate rollback, expired lease and session-without-transaction
  cases prove that order, SKU index and a recovery completion record commit
  together or remain absent. No production data was used or changed.
- Recovery, event persistence, historical backfill and core lease suites:
  149 passed in 5.58s. Ruff, format and mypy pass (500 files).
- Rollback boundary: optional session support in guarded_devoluciones_write
  and Sheets order persistence, plus the transaction regression. This is a
  prerequisite, not enabled order recovery. The pending worker implementation
  is its intended runtime consumer; deploy together after its acceptance.
  Existing callers keep their transaction/lease contract unchanged.

## Work unit: complete order inventory recovery worker

- Added order acquisition to the recovery worker, not to automatic admission.
  It follows short search pages to a stable required total, validates detail
  identity/owner/date/items, acquires the existing covered-order operation,
  and publishes rows, SKU indexes, coverage, job completion and operation
  success in one transaction. Empty authoritative inventory is supported.
- Questions and orders reuse coverage-union and atomic-publication code.
  Existing question regressions remain green. Orders additionally verify
  persisted buyer/item availability and the live covered-order operation.
- Real-Mongo scenarios first failed because order acquisition never ran. They
  now prove successful and empty recovery, missing total, foreign detail,
  extra Mongo inventory and refusal to claim an HTTP 206 response complete.
  The negative cases assert source acquisition actually executed, not merely
  that the unimplemented worker rejected the model.
- Recovery, event persistence, historical backfill and core lease suites:
  155 passed in 7.35s.
  Root static checks pass. No production recovery or image deployment yet.
- Rollback boundary: the order acquisition branch and shared coverage/publish
  extraction, with these tests. Automatic admission still enables only
  questions. Field-aware partial-response fallback and formula range checks
  remain required before enabling orders; this worker stage is not the final
  fallback contract or a proof of all eleven order/sales formulas.

## Work unit: partial order response fallback uses owned Mongo state

- A real-Mongo regression first rejected HTTP 206 despite existing normalized
  buyer/shipment identities. Order recovery now consumes X-Content-Missing
  explicitly and passes only its allowlisted field names to the order writer.
  Missing/malformed partial metadata still cannot prove complete recovery.
- Buyer and shipment fallback reads the same seller's current order inside the
  publication transaction, never a detached or other-seller snapshot. A known
  no_shipping state still prevents resurrection. If seller is unavailable in
  detail, the matching search row must explicitly establish its owner; any
  contradictory owner remains rejected.
- Previously stored feedback is retained when upstream marks it unavailable.
  That is last-known data, not newly verified feedback: the existing covered
  order operation invalidates devoluciones readiness, which is not promoted
  by this order inventory recovery. No raw response or auth data is persisted.
- The partial-source regression proves cancelled status updates while buyer,
  shipment and prior feedback survive. The no-cache control does not publish
  completion. Fields declared unavailable are not trusted merely because the
  response body happens to contain a value.
- Focused suites: 156 passed in 7.54s. Full regression initially found one
  test double with the old private writer signature; it now accepts the new
  optional parameters while asserting the unchanged default/context contract.
  Final full regression: 3,642 passed, 9 skipped in 71.55s. The eight protected
  replica-set tests separately passed in 3.44s; the remaining skip is Caddy's
  no-required-keys case. Ruff, format and mypy pass (500 files).
- Rollback boundary: unavailable-field handling in recovery and order
  persistence plus its regression/test-double update. Automatic admission is
  still questions-only and the production flag remains off. No build, deploy
  or production mutation was performed for these three work units.

Before activation, connect truthful range checks and recovery to the eleven
order/sales handlers and prove a missing-data/next-HTTP-query cycle. Do not treat
the current blanket buyer/shipment requirement as final: each formula must
require only the fields needed for its result, so missing buyer information
must not prevent a complete sales-total calculation. Resolve this together
with partial normalized persistence/field availability, not by returning a
misleading zero or discarding the available amounts. The all-history last-sale
case, recovery admission controls and other model dependencies remain open.

The pending runtime consumer is sheets-worker; a verified new image and a
controlled pilot order recovery are required before claiming live support.
Pair the release with the forthcoming API range/admission changes rather than
activate this staging implementation alone. Existing non-session core callers
retain their contract; other product deployments remain out of scope.

## Work unit: unavailable buyer does not erase usable order amounts

- A new real-Mongo test first failed because a partial source order without a
  cached buyer could not be persisted. Order normalization now omits the absent
  buyer ID and explicitly records unavailable_fields. No placeholder identity
  is manufactured. Source-available complete documents retain their old shape.
- Core validation and the exported Mongo order validator require the buyer
  omission to match the unavailable marker. Mongo tests reject undeclared
  absence, unrelated flags, contradictory identity/flag and unknown field names.
  The allowed normalized field names are buyer_id, shipment_id and feedback.
- Recovery can publish an authoritative inventory with explicit field gaps.
  Last-known feedback remains marked unavailable when not freshly sourced;
  existing identity fallback and no_shipping behavior are preserved.
- A validated Mongo recovery test proves sales total 30 remains usable while
  buyer-filtered ORDENES raises structured DATA_UNAVAILABLE instead of silently
  excluding the order. Both buyer-filter call sites share that check. No source
  call occurs during either calculation. This is not yet a range-coverage or
  authenticated HTTP acceptance claim.
- Model, schema export, recovery, order/question formula and persistence suites:
  199 passed in 6.22s. Static checks pass. No production schema/data mutation.
- Rollback boundary: explicit order-field availability, buyer omission model
  and Mongo schema, and buyer-filter guards with their tests. Production rollout
  must apply the compatible order validator before any partial writer is enabled
  and protect all relevant readers. Do not restore the old required-buyer Mongo
  validator while partially populated orders exist; retain the compatible
  validator through a code rollback until those documents are resolved.

## Work unit: bounded sales formulas request persistent recovery

- Nine range-based order/sales handlers now share a coverage-checked read.
  Ten new cases failed first: each of those handlers accepted unproven empty
  inventory, and the local HTTP sales-total request returned success instead
  of requesting recovery. They now emit structured orders/range unavailability.
- Runtime order coverage no longer requires the legacy_imported basis used by
  imported history models. Other models retain that requirement. Existing
  reconciliation interval and expiry checks remain in use.
- The opt-in recovery wiring now admits questions and orders; shipments and
  other unfinished models remain excluded. The production flag has not been
  enabled. Admission quotas and safe global activation remain unfinished.
- Local authenticated ASGI HTTP plus actual Mongo tests cover questions,
  complete orders and HTTP 206 orders with no cached buyer. First query requests
  recovery without source calls; background work persists data/proof; the next
  sales-total query returns 30 without another source call. All three HTTP
  scenarios passed in 1.08s. This does not substitute for production HTTP smoke.
- Calculation/address fixtures now explicitly declare their complete test
  inventory; their fake collection supports find_one. The schema contract test
  checks conditional buyer presence rather than the superseded unconditional
  requirement. Tenant/ID requirements and buyer-address isolation assertions
  remain intact. Negative coverage and conditional-validator behavior are
  exercised against actual Mongo, not mocked away.
- Rollback boundary: shared bounded-order read, runtime-order basis selection,
  orders opt-in admission, and related tests. Pair Sheets API and worker images
  with the compatible order validator; do not activate partial writers first.
- Final regression: 3,655 passed, 9 skipped in 72.18s. Protected replica-set
  suite separately: 8 passed in 2.24s. Remaining skip is Caddy's no-required-keys
  contract case. Ruff check, format, mypy and diff whitespace checks pass.
  No build, deploy, production schema change or production order write was
  performed for these two work units.

### Still required before production order-recovery activation

- DIASDESDEULTIMAVENTA reads all-history; handle the latest-known-sale versus
  unknown-history distinction explicitly. COMPRADORES missing IDs now request
  discovery as documented below, but missing shipment snapshots remain pending.
- Continue the required-field audit beyond the explicit shipment_id guard
  below: missing shipment snapshots and required address/cost fields still need
  their own acquisition and availability handling.
- Ranges beyond the queue's 90-day limit need bounded acquisition scheduling;
  do not claim they are unrecoverable merely because of that internal limit.
- Verify/release the pending schema/API/worker changes in the approved runtime,
  then prove pilot order recovery and production formula reads. The last live
  worker is still source d145d61 and the API source 4f65d6d, not these changes.

## Work unit: retain recovery requests and expose required shipment gaps

- Requests arriving during a completed/failed job's cooldown now remain pending
  with the original deadline. Twenty concurrent requests keep one job; the worker
  can claim it after the deadline without another user recalculation. Both
  terminal-state regression cases failed before the fix.
- ORDENES, ORDENESPORSKU and COMPRADORES reject explicitly unavailable shipment
  identity when needed for shipping cost/address. The structured error identifies
  orders and their creation-time interval for asynchronous recovery. Sales totals
  continue using available amounts; unrelated SKU rows do not require that
  shipment. Genuine optional absence retains existing behavior.
- The actual-Mongo partial-order test failed first for shipping. After the fix,
  recovery and buyer-address suites passed: 56 tests in 8.46s. The gateway fixture
  records no additional source calls during formula evaluation. This is local
  source-fixture/Mongo evidence, not a production HTTP or real Sheet result.
- Rollback boundary: terminal-job requeue behavior and shipment-identity helper,
  its five call sites and associated regression changes. No stored order schema
  change belongs to this unit. Reverting the guard must not accompany activation
  of partial-order writers.
- No build/deploy or production mutation in this unit. Sheets API and worker
  need new verified images once the remaining activation gates above are met;
  verify deployed source/digest, health and controlled pilot recovery then.
- Root regression: 3,657 passed, 9 skipped in 72.98s. The eight protected Mongo
  cases passed separately in 2.48s with the dedicated replica-set test variable;
  the remaining skip is Caddy's no-required-keys case. Ruff check/format, mypy
  (500 source files) and diff whitespace checks passed.

## Work unit: recover explicit COMPRADORES order IDs

- COMPRADORES no longer silently omits requested orders absent from the seller's
  Mongo read model. It raises structured unavailability with private recovery
  targets, without including those IDs or upstream payloads in the public error.
- Opt-in HTTP recovery queues deterministic seller-scoped ID jobs, at most 100
  numeric IDs each, under one total one-second insertion deadline. Existing
  range-job identities and claim/lease/cooldown behavior remain unchanged.
- The worker discovers creation dates, then reuses the existing inventory search,
  detail validation and transactional publication. Discovery alone never proves
  coverage. Every requested ID must occur in the authoritative inventory before
  any publication. Explicit foreign/conflicting ownership is rejected; HTTP 206
  seller omission requires ownership proof from the subsequent search/detail
  validation. The 240-second worker timeout and 10,000-order search cap remain.
- Local authenticated ASGI/Mongo scenarios failed first for absent IDs and for
  recoverable partial seller responses. Both now recover in the background;
  the next COMPRADORES query returns a row without more source calls. Negative
  tests reject foreign/missing ownership, wrong IDs and absent search results
  without persisting an order or coverage marker. Queue tests cover coalescing,
  tenant isolation and invalid/bounded identities.
- Rollback boundary: ID request type, private error targets, API scheduling,
  missing-ID handler guard and worker discovery with its regression cases.
  Deploy API and worker together; do not leave an old worker consuming ID jobs.
  No production write/build/deploy occurred. New Sheets API and worker images
  remain required after the outstanding activation gates, followed by digest,
  health and controlled pilot HTTP recovery verification.
- This does not complete COMPRADORES address acquisition or source freshness,
  wide-history acquisition, global admission controls, or real Google Sheet
  acceptance. Range acquisition may still exceed its worker budget for widely
  separated IDs; independent bounded acquisition remains a follow-up for the goal.
- Final verification: recovery/address suites 63 passed in 10.16s; root suite
  3,664 passed, 9 skipped in 74.59s. Eight protected replica-set cases separately
  passed in 2.42s; remaining skip is Caddy's no-required-keys case. Ruff check,
  format, mypy (500 files) and diff whitespace checks passed.

## Work unit: normalize current shipment detail in recovery transactions

- Current shipment details normalize `logistic.type` and
  `destination.shipping_address` plus `destination.receiver_name` into the
  existing Mongo fields. Legacy-shaped inputs remain supported for proven
  callers. The same eight address fields are retained; raw destination data,
  phone and geolocation are not added to the stored formula projection.
- Source: [Mercado Libre shipment contract](https://developers.mercadolibre.com.mx/envios),
  checked September 7, 2026. It documents `x-format-new: true`, discontinued
  detail `order_id`, and address hiding before confirmed payment. Caller-side
  order linkage still must be established through a verified relationship;
  this normalizer does not invent it or mark hidden addresses optional.
- Shipment persistence now joins an explicitly active caller transaction.
  The actual-Mongo validator test failed first for normalization and unsupported
  transactions, then passed for ordinary write, commit, abort and inactive
  session rejection (4 passed in 0.82s). Committed projections are readable;
  aborted writes remain absent. Existing freshness/tenant write filters remain.
- Persistence and recovery suites before the additional inactive-session case:
  129 passed in 10.47s. Mypy passed for 500 files; Ruff check/format passed.
- Rollback boundary: current-shape extraction and shipment session propagation
  with these regression cases. No Mongo schema change. Do not roll the worker
  back past this boundary while relying on transactional shipment recovery.
- Not activated: shipment recovery jobs, required address/cost availability,
  relationship fetching, current source request headers and formula-triggered
  shipment acquisition. These remain part of the goal, not deferred out of scope.
  No production write/build/deploy occurred. The Sheets worker needs a verified
  Cloud Build image after its acquisition path is completed, followed by source
  digest, health and controlled pilot shipment/formula verification.
- Final root regression: 3,668 passed, 9 skipped in 74.69s. Eight protected
  replica-set tests passed separately in 2.68s; remaining skip is Caddy's
  no-required-keys case. Diff whitespace validation passed.


## Work unit: acquire owned shipment IDs and publish atomically

- The recovery worker can process explicit shipment-ID jobs (up to 100 unique
  normalized numeric IDs). It obtains owned order relationships from
  `/shipments/{id}/orders` with `X-New-Domain: true`, then current detail and costs
  with `x-format-new: true`. Costs reuse the existing seller-matched normalizer.
  Source: [Mercado Libre shipment contract](https://developers.mercadolibre.com.mx/envios),
  checked September 7, 2026.
- The established singular `order_id` projection uses a deterministic owned
  relationship, never a foreign row or invented ID. Full relationship modeling
  and simultaneous multi-seller storage are not claimed: an existing shipment
  document owned by another seller is preserved, not reassigned.
- Normalized shipments and live job completion commit in one Mongo transaction.
  Publication checks persisted BSON-normalized values against the acquisition;
  a newer stored version cannot be overwritten or silently certified as the
  acquired version. Explicit-ID acquisition does not write a history coverage
  marker. Queue completion can join the transaction using the existing lease
  and cooldown logic.
- Initial tests failed because shipment ID requests were unimplemented. The
  actual-Mongo/schema suite now passes 9 scenarios in 1.70s: acquisition,
  foreign relationship, wrong detail ID, partial response, superseded lease,
  invalid second document, foreign cost, preexisting foreign document and newer
  stored snapshot. Failure while publishing the second document rolls back the
  first. Phone/raw destination data are not persisted.
- Activation remains OFF: shipments are not added to runtime IMPLEMENTED_MODELS
  and the HTTP error-to-job path does not yet admit shipment IDs. A range-only
  shipment request is not implemented. Before enabling, add required-field
  availability/freshness and formula-triggered ID scheduling. A hidden/missing
  address must not become optional NA; incomplete costs currently reject the
  acquisition, so preserving independently usable partial fields also remains
  required work. These are goal requirements, not waived acceptance criteria.
- Rollback boundary: shipment-ID request type, transactional queue completion,
  worker shipment branch and its regression cases. No schema migration or
  production mutation/build/deploy occurred. A new verified Sheets worker image
  is required once activation gates are satisfied; verify source/digest, health,
  pilot source equality and formula reads in the approved runtime context.
- Final regression: 3,677 passed, 9 skipped in 76.55s. Eight protected replica-set
  cases passed separately in 2.49s; remaining skip is Caddy's no-required-keys
  case. Ruff check/format, mypy (500 files) and diff whitespace checks passed.

## Work unit: preserve usable shipment fields during partial acquisition

- Shipment documents can record `formula_observed_at` and an allowlisted,
  deduplicated `unavailable_fields` list for receiver address and real shipping
  cost. This timestamp records acquisition, not freshness of flagged fields.
  Core model and schema exporter agree; regeneration changed only shipments.json.
  Legacy canonical documents still omit empty availability metadata.
- Missing or failed seller-cost acquisition no longer discards independently
  acquired address/status data. Hidden/absent address is explicitly unavailable,
  not silently certified as optional absence. Another sender's cost is never
  substituted. Upstream diagnostics are not stored.
- Inside the publication transaction, missing fields can retain the previous
  same-seller Mongo value while remaining flagged. The cached cost's original
  synced_at is preserved, including UTC restoration for naive Mongo decoding;
  no field is stamped freshly sourced merely because fallback found a value.
- Transient cost failures atomically persist usable fields and schedule the
  existing bounded retry. They do not mark the job completed prematurely.
  The regression advances the clock without enqueuing another request, restores
  source availability, and verifies job completion, refreshed cost/address and
  removal of the unavailable flags.
- Tests failed first for missing observation metadata, discarded partial
  acquisition and cancelled retries. The 12 actual-Mongo acquisition scenarios
  now pass in 2.33s, retaining previous tenant, stale-write, lease and rollback
  checks. Ruff check/format and mypy (500 files) pass.
- Rollback boundary: optional shipment availability model/schema fields,
  partial acquisition and transaction-local fallback/retry, with regressions.
  Keep the compatible validator if rolling code back with flagged documents
  present. No build/deploy or production schema/data mutation occurred.
- Not activated: formula readers must honor field availability and observation
  freshness, HTTP must schedule shipment IDs, and readiness/admission controls
  must be verified before enabling. Event-driven shipment writes still need
  equivalent enrichment/retention treatment. This unit does not prove those
  requirements or production/Google Sheet acceptance. Plan a verified Sheets
  worker image and paired API/validator rollout after those gates, then check
  deployed source/digest, health and controlled pilot field recovery.
- Final root regression: 3,680 passed, 9 skipped in 76.87s. Eight protected
  replica-set cases passed separately in 2.58s; remaining skip is Caddy's
  no-required-keys case. Diff whitespace validation passed.

## Work unit: formulas request current required shipment fields

- Receiver-address and realized-cost reads now require a usable seller-scoped
  value, no unavailable flag for that field, and a source observation within
  15 minutes. Addresses use formula_observed_at; costs use their own synced_at.
  Missing, expired, future-dated, malformed and foreign-seller rows produce
  structured shipment-ID recovery targets rather than a successful partial map.
  An unavailable cost does not block an independently usable address, or vice versa.
- HTTP schedules explicit shipment-ID jobs in batches of at most 100 under the
  same total one-second insertion deadline used by order IDs. Shared scheduling
  handles either ID type, not both at once. Opt-in API/worker source admission now
  includes shipments; range-only shipment jobs remain rejected. Production's
  global recovery flag was not changed.
- Twelve scenarios failed first for permissive required-field reads and missing
  HTTP recovery. They passed after the change (1.97s); two additional actual-Mongo
  malformed-field cases pass. Authenticated local ASGI tests cover complete and
  partial-cost shipment acquisition: first query requests recovery without a
  source call, background work persists the address, and the second COMPRADORES
  query returns it with no extra source calls, even while cost retry is pending.
- Calculation fixtures explicitly supply current observations and actual costs
  where those are needed. Obsolete all-NA expectations for absent/foreign/blank
  shipments were replaced with unavailable assertions; tests still verify exact
  safe address fields, seller scope, buyer filters, cart IDs and cost calculations.
  Optional absent individual address fields still render NA. Address suite:
  3 passed in 0.03s; order/item calculation suites: 82 passed in 0.38s.
- Rollback boundary: required shipment field reads/projections, private error ID
  metadata, HTTP scheduling and shipment opt-in admission with their regression
  cases. Retain critical source/tenant validations if reverting UI-facing guards.
  No production write, build or deployment occurred.
- Before rollout, verify admission limits and prepare pilot shipment snapshots;
  old production records without observation evidence will request recovery.
  Build paired verified Sheets API/worker images with the compatible validators,
  verify deployed source/digests and health, then exercise real pilot HTTP reads.
  Remaining work includes non-address/cost shipment surfaces, minimum necessary
  order selection for latest-cost calculations, event-driven refresh/retention,
  wide-history acquisition, global admission controls and real Sheet acceptance.
- Final root regression: 3,694 passed, 9 skipped in 75.13s. Eight protected
  replica-set cases passed separately in 2.42s; remaining skip is Caddy's
  no-required-keys case. Ruff check/format, mypy (500 files) and diff whitespace
  validation passed.
