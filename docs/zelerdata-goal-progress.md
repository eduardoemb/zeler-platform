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

## Work unit: select relevant latest sales before requiring shipment costs

- COSTOENVIOVENDEDOR selects the newest eligible non-cancelled order line for
  each requested SKU/item pair before reading shipment costs. Positive quantity
  and existing shipment eligibility are preserved; explicit shipment-identity
  gaps participate in selection and request order-ID recovery if selected.
- Only the selected shipment IDs need current costs. Older, cancelled or
  unrelated orders no longer force acquisition. A missing selected cost cannot
  be silently replaced with an older cost. The per-unit arithmetic and response
  metadata remain unchanged.
- Removed this formula's global shipment freshness prerequisite: the required
  per-ID cost checks now provide the relevant evidence. The order readiness gate
  remains; ENVIOSMERCADOENVIOS keeps its existing separate gate. This resolves
  the previously noted minimum-needed selection for latest-cost calculation.
- Four cases failed first. Updated tests verify a latest sale beyond 5,000 older
  orders without their cost snapshot, unrelated/cancelled missing shipments,
  selected missing cost/identity, and successful calculation without a global
  shipment marker. Item-shipping and recovery suites: 117 passed in 15.11s.
  These are local calculation/recovery tests, not a new productive cost-formula
  or real Sheet acceptance result. Static checks pass for 500 source files.
- The order read still scans all available history. Strong absent-sale/history
  completeness evidence and bounded acquisition remain required goal work;
  this optimization does not prove those broader properties.
- Rollback boundary: latest-line selection, required-ID lookup and removed
  global shipment gate in this handler with their regression updates. No schema,
  production data, build or deployment change. Sheets API needs a verified new
  image after the outstanding rollout gates, coordinated with the pending
  recovery worker/validator release; verify deployed source/digest, health and
  pilot COSTOENVIOVENDEDOR with obsolete unrelated shipments unavailable.
- Final root regression: 3,696 passed, 9 skipped in 79.50s. Eight protected
  replica-set tests passed separately in 2.53s; remaining skip is Caddy's
  no-required-keys case. Ruff check/format, mypy and diff whitespace checks pass.

## Work unit: restrict automatic recovery to explicitly configured sellers

- Sheets API and worker now read `ZELERDATA_FORMULA_RECOVERY_SELLERS` alongside
  the existing enable flag. Missing/blank configuration enables no sellers;
  comma-separated numeric IDs are required and wildcards are rejected. The
  deployment runbook names the agreed pilot and paired-image activation gate.
- Queue admission, worker claims and exhausted-lease cleanup obey the seller
  scope. Existing jobs belonging to other sellers remain untouched. Internal
  callers can still explicitly construct an unrestricted queue; production
  entrypoints always supply the parsed scope. This is a pilot gate, not a
  replacement for quotas/fairness before broader activation.
- Five regression cases failed before implementation. The local Mongo harness
  verifies pilot admission/claim, rejection outside scope, preservation of
  foreign expired jobs, and an empty scope. API construction also verifies
  propagation. `uv run pytest modules/sheets/tests/test_formula_recovery.py`
  with the task-owned local replica set: 95 passed in 10.34s.
- Read-only VM inspection reconfirmed Sheets API `f9b07c9de23c`, worker
  `b8edfdf59627` and gateway `2d4a514cab2d` healthy with zero restarts. Recovery
  remains disabled on both Sheets services. Root free space is 4.54 GiB, below
  the required 5 GiB pull/Compose floor. No production mutation or deployment
  occurred; these checks do not constitute formula HTTP acceptance.
- Rollback boundary: this seller parser, API/worker wiring, queue filters and
  corresponding tests/runbook changes. Disable recovery on both services before
  rolling back to images without the gate; otherwise the old flag is unscoped.
  No schemas or persisted records need removal. New verified Cloud Build images
  are required for Sheets API and worker after the remaining validator/event
  ingestion gates and VM capacity preflight. Verify deployed source/digest,
  health, pilot recovery and outside-scope rejection before activation.
- Final root regression (`uv run pytest` with the local replica set): 3,701
  passed, 9 skipped in 75.92s. The protected stock-time-forward suites ran
  separately with `ZELER_RS0_TEST_URI` and no ambient `MONGO_URI`: 8 passed in
  2.57s. Remaining skip is Caddy's no-required-keys case. Ruff check/format,
  mypy (500 source files) and diff whitespace checks passed.

## Work unit: retain recovered shipment fields across ordinary events

- Ordinary shipment writes without a formula observation no longer erase the
  stored address, independent shipping cost, original observation timestamp or
  unavailability flags when those fields are absent from the incoming normalized
  document. A Mongo update pipeline retains only these four fields, then overlays
  the canonical document; unknown legacy/raw fields are not carried forward.
- Retention and the existing seller/freshness guard execute atomically, with no
  read-then-write merge race. Recovery publications containing an observation
  still use their existing transactional replacement path, including clearing
  resolved gaps. Incoming explicit normalized values take precedence; an ordinary
  event does not refresh the retained observation or remove previous gap flags.
- Two Mongo regression cases reproduced missing addresses before the fix, after
  correcting the fixture's required shipment fields. Tests now verify delivered
  status, unchanged cost/address/proof, retained flags, removal of a synthetic raw
  sentinel, and continued DATA_UNAVAILABLE for expired retained fields. Existing
  stale-write and recovery transaction tests remain in the focused suite.
- No build, production data change or deployment occurred. This closes the
  destructive replacement gap, not the outstanding event acquisition/new order
  relationship contract or productive HTTP/Sheet acceptance requirements.
- Rollback boundary: the ordinary shipment update branch and its Mongo/fake
  regression coverage. No schema migration is introduced. Rolling it back can
  again erase enrichment on events, so keep recovery disabled when reverting.
  Sheets worker requires a new verified Cloud Build image with the pending paired
  API/validator release. Verify deployed source/digest, health, and a pilot event
  after recovery: status advances while retained fields and timestamps survive.
- Focused local Mongo harness:
  `uv run pytest modules/sheets/tests/test_formula_recovery.py modules/sheets/tests/test_event_persistence.py`
  with the task-owned replica set: 163 passed in 8.97s. The first root run found
  a historical-backfill fake without pipeline support; after adapting that fake,
  `uv run pytest modules/sheets/tests/test_historical_meli_backfill.py` passed
  all 40 tests in 0.27s. No production behavior was changed to satisfy the fake.
- Final root regression: 3,703 passed, 9 skipped in 78.30s. The eight protected
  stock-time-forward replica-set cases passed separately in 2.62s; the remaining
  skip is Caddy's no-required-keys case. Ruff check/format, mypy (500 files) and
  diff whitespace checks passed. These local results do not close live acceptance.

## Operational checkpoint: restore VM capacity and audit validator compatibility

- Confirmed selected main commit `c82b5bec2a5b8e4896278f1e9d2f28ef91f1ff12` and
  preserved unrelated untracked work. No build, service recreation, data repair
  or validator mutation occurred in this checkpoint.
- Removed only two unused local image copies, after checking every container
  reference and confirming both digests still exist in Artifact Registry:
  Sheets worker `sha256:ab91fe179dd4124e68f3f3ec11e9c7eca0624fe485ab8753f262e8fe26817646`
  and Sheets API `sha256:cd3c541f85a47fa0093fda6958bd1dfb4759263c5c24a3d5b76fd78c8663a8dc`.
  Running images and immediate rollback images were retained. No volumes or
  containers were removed. Both deleted copies are recoverable by digest pull.
- Root free space increased from 4.54 to 5.62 GiB, above the 5 GiB capacity floor.
  Run the full service-specific deploy preflight again immediately before a pull;
  this capacity observation alone is not a deployment authorization receipt.
- Inside the approved worker container, using `/app/.venv/bin/python`, checked
  production documents against main's orders/shipments `$jsonSchema` payloads.
  Existing validators differ from main; both are configured strict/error.
  Orders: 2,429 documents, zero invalid under the proposed schema. Shipments:
  2,374 documents, 47 invalid. All 47 belong to the pilot and have string-valued
  `date_created` and `last_updated`; no other property violations or missing
  required fields were found. Only aggregate counts/types were emitted.
- Diagnostic correction: the first probe mistakenly included deployment metadata
  (`validationLevel`/`validationAction`) as query predicates and reported all
  documents invalid. That result is discarded; the counts above use only the
  `$jsonSchema` validator. System Python also lacked pymongo, so the successful
  probe used the documented runtime virtual environment.
- Next release gate: validate and reversibly normalize those 47 date pairs in
  the approved runtime context, preserving instants and unrelated fields; recheck
  zero invalid documents before applying compatible validators. This does not
  prove source completeness/freshness or replace new-contract acquisition.
- Verification is the production read-only compatibility/count audit plus exact
  image-reference/registry checks and measured capacity. Unit tests are N/A for
  this documentation-only repository change; no executable code changed.
  Pending Sheets API/worker changes still require new verified Cloud Build images,
  exact deployed-source checks and pilot recovery/HTTP verification after the
  outstanding release gates. The full goal remains open.
- Post-cleanup inspection confirmed API `f9b07c9de23c`, worker `b8edfdf59627`
  and gateway `2d4a514cab2d` still healthy with zero restarts and the same images.
  Diff whitespace validation passed. Documentation rollback removes only this
  checkpoint; image recovery is independent and uses the registry digests above.

## Work unit: bounded, reversible shipment date normalization

- Added `infra.operations.shipment_date_repair.repair_shipment_dates` for an
  operator-supplied backup of at most 100 same-seller shipment identities and
  date pairs. It accepts only timezone-aware ISO strings exactly representable
  as BSON milliseconds. One snapshot/majority transaction compares original
  dates and seller identity before each date-only update; any mismatch aborts
  the entire batch. It neither refreshes formula evidence nor contacts Meli.
- Five tests failed first, then passed against local Mongo: exact offset/instant
  conversion, concurrent-date-change rollback, foreign seller, naive date and
  precision-loss rejection. All 102 recovery tests passed in 10.21s with the
  task-owned replica set. Ruff check/format and mypy (501 files) pass.
- Production read-only preflight found exactly 47 pilot shipments and 94
  timezone-aware millisecond dates, with no rejected values. Before mutation,
  created `/var/lib/zeler-platform/repairs/shipment-dates-148c8ae.bson` on the
  approved VM: 7,367 bytes, root-owned mode 0600 in the existing 0700 directory.
  Backup contains only seller/shipment identity and the two original dates;
  no document payload or backup content was emitted outside the VM.
- Execution gate: use the reviewed helper from the exact pushed source inside
  the approved runtime, loading this backup locally on the VM. After execution,
  compare both dates with converted backup values and recheck the main shipment
  schema without altering validators. A failed comparison must stop the rollout.
- Rollback is a separate guarded date-only transaction: for each backup identity
  require the current two dates equal its converted values, then restore only
  its original strings. Abort if any dates changed since repair; never replace
  whole documents or overwrite later events. Do not restore strings after a
  stricter date validator is activated without first resolving compatibility.
  Keep this restricted backup under the goal's retention/deletion hardening scope.
- This operator-only helper is not called by service entrypoints and does not
  itself require a new image. Pending API/worker behavior still requires verified
  Cloud Build images and productive pilot/HTTP/Sheet checks; the goal stays open.
- Final local regression: 3,708 passed, 9 skipped in 79.11s; eight protected
  stock-time-forward Mongo cases passed separately in 1.56s. Remaining skip is
  Caddy's no-required-keys case. Ruff check/format, mypy and whitespace checks pass.
- Executed reviewed source `3f5ee2021838fa77f3a9d085ff10b2b58d9de821` inside
  the existing worker container without changing its image or filesystem.
  The helper's SHA-256 was checked before execution:
  `e482a722d2331ab3e6583ab44feee0bce9687b5d2bb23a4836ab9878f51b7876`.
  The root-only VM backup was piped directly into the runtime; no credentials,
  identities or original date values were printed or transferred locally.
- Production result: 47 shipment documents repaired in one transaction, all 94
  dates independently compared with the converted backup originals, zero shipment
  documents invalid under main's proposed schema afterward. Only the two date
  fields were updated. Validators, formula observation timestamps, feature flags
  and other collections were not modified. The rollback backup remains available.
  This resolves the identified type-compatibility gap, not source completeness or
  productive formula/Sheet acceptance.
- Post-repair inspection: Sheets API `f9b07c9de23c`, worker `b8edfdf59627` and
  gateway `2d4a514cab2d` retained their running images, healthy with zero restarts.
  They still do not include the staged API/worker changes on main. Apply compatible
  validators and verify new images/pilot behavior through the outstanding release
  gates; do not treat this date repair as a completed deployment.

## Operational checkpoint: apply compatible orders and shipments validators

- At main `71f6c1b4178349ff697288811e341a1668a8f750`, rechecked both proposed
  `$jsonSchema` payloads against production: zero invalid documents. Backed up
  both existing validator/options sets to root-only VM file
  `/var/lib/zeler-platform/repairs/formula-validators-71f6c1b.bson` (4,009 bytes,
  mode 0600 under the 0700 repairs directory). It contains schema configuration,
  not document data or credentials.
- Inside the approved worker runtime, compared current options with the backup
  before mutation, then applied only orders and shipments through majority-
  acknowledged `collMod`. Both resulting validators match the committed schemas
  exactly, with strict/error enforcement and zero invalid documents afterward.
  No indexes, document data, other collections, images or feature flags changed.
- Verification: validator application/idempotency/failure suites passed 10 tests
  in 0.06s; the local Mongo recovery suite passed 102 tests in 16.01s. These tests
  include complete/partial order and shipment publication under current schemas.
  The production result is schema compatibility, not formula HTTP acceptance.
- Rollback boundary: only the two backed-up validator/options sets. Before
  reverting either, recheck current configuration and compatibility of every
  document with its old validator. Once partial orders exist, blindly restoring
  the old required-buyer schema can reject valid writes; keep the compatible
  schema when rolling back application images unless safety is proved.
- Started one verified Cloud Build per affected Sheets image from this exact
  connected-repository commit, without uploading the local checkout:
  API `223142bd-0fcb-4196-ac41-2183517d2f8b`; worker
  `07724522-d44f-420c-affa-6604141978dc`. Both were observed WORKING. Build
  completion, immutable digest/provenance verification and deployment are separate
  gates; neither service has been pulled/recreated by this checkpoint.
- Both builds subsequently completed SUCCESS. Using the repository's
  `verify_image_to_commit`, verified each single-image SLSA subject, build,
  connected repository, source commit, project ID and project number. Immutable
  images ready for the controlled rollout:
  - Sheets API: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`.
  - Sheets worker: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d`.
- Local sanitized binding maps are under `/tmp/zeler-recovery-build.IltD0b/`
  as `sheets-api-image_to_commit.json` and `sheets-worker-image_to_commit.json`.
  Build configurations in the same directory requested VERIFIED provenance and
  produced one image each. These files are convenience evidence; authoritative
  build and registry records must be rechecked before deployment.
- After validator activation, Sheets API, worker and gateway remained healthy
  with zero restarts. Recovery remained disabled. Runtime still uses the older
  API/worker images; next run the capacity/provenance preflight, deploy the exact
  verified images through targeted service replacement, check digest/health and
  then prove pilot behavior. No new build is needed for this documentation-only
  checkpoint; the full goal remains unproven until live acceptance is complete.

## Operational checkpoint: deploy the verified recovery-capable Sheets pair

- Confirmed main `df16a8baa460cb48e6d7ae560f59797ae9badb82` differs from the
  verified image source `71f6c1b4178349ff697288811e341a1668a8f750` only in this
  progress document. Rechecked both successful Cloud Build records, exact source
  revision and image digests. No new build or executable repository change.
- VM dry-run and real capacity preflights passed. Replaced exactly one Compose
  image occurrence per service, first worker then API, with targeted pull and
  `up -d --no-deps`. Backups are
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-71f6c1b` and
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-71f6c1b`.
- Worker now runs `sha256:ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d`;
  API now runs `sha256:c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`.
  Both correspond to the verified build IDs recorded immediately above.
- Preserved immediate rollback authorities: worker
  `sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`
  and API `sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f`.
  Restore only the affected service's image, not the entire Compose backup;
  retain compatible Mongo validators and keep recovery disabled on rollback.
- To preserve the 5 GiB floor before the API pull/recreation, removed only unused
  local worker image `sha256:6ac235ab1d3b26dc157998bde42df91ad2963019f10f74417e9a96afba08acee`
  after rechecking all container references and its continued registry presence.
  It is recoverable by digest pull. No containers or volumes were pruned. Free
  space was 5.62 GiB before each pull and 5.12 GiB after the completed pair.
- No feature flags, seller scope, Mongo data or other product services were
  changed. Automatic recovery remains deliberately disabled; deploying code is
  not evidence of background recovery or productive formula/Sheet acceptance.
- Final runtime checks confirmed both exact new digests, Docker health healthy,
  zero restarts, and `/health` HTTP 200 with `ready=true` inside each service.
  Gateway retained digest `2d4a514cab2d`, healthy with zero restarts. No rollback
  was needed. Whitespace validation passed; unit tests are N/A for this
  documentation-only change (the image source's tests are recorded above).
- Runtime now includes the staged Sheets code at the verified source commit;
  current main adds only evidence documentation. No further image rebuild is
  required for this checkpoint. Next prove controlled pilot recovery, real HTTP
  formula behavior, authenticated app surfaces and Google Sheets; all global
  acceptance requirements remain open until the corresponding evidence exists.

## Operational checkpoint: controlled pilot order recovery

- Inspected the pilot queue in the deployed worker: only one completed question
  job existed, with no order jobs. Kept API/worker automatic recovery flags off.
- The first preflight stopped before enqueue because the effective coverage was
  wider than the requested August 8–September 6 dates. Existing order coverage
  starts June 1; the worker preserves it by reacquiring the complete union through
  September 7 exclusive (98 days). A read-only gateway search reported 1,069
  source orders. No marker was deleted or shortened to force the smaller test.
- After explicitly bounding that observed union, enqueued one pilot-only orders
  request: `ebf5decad5d7272397c1cce22e81cd5158259dea80d2d4412eebee0d817297d4`.
  Executed the deployed `FormulaRecoveryWorker.process_one` inside the approved
  runtime, using normal bootstrap search and Sheets detail gateway clients.
  Queue admission/claim is limited to seller 82453304 and orders; no other account
  or model is processed. The existing 240-second acquisition/publication limit
  remains in force. This is an operator-run worker test, not authenticated HTTP
  formula acceptance and not automatic poller activation.
- The controlled attempt finished failed/source_incomplete after 187.233s:
  22 search calls and 1,069 detail calls, one attempt. The order publication did
  not complete; the operation is failed and the old July 10 coverage endpoint
  remains, without a new expiry/proof. No automatic retry or lease override was
  started. Do not report this as successful recovery.
- Independent read-only inventory comparison found 1,069 IDs in the search,
  1,073 stored IDs in the effective interval, six source IDs absent in Mongo and
  ten Mongo IDs absent from search. Direct API detail checks for all ten extras
  confirmed matching pilot ownership and dates inside the interval. These are
  not foreign or out-of-range records and must not be deleted to force equality.
- Official Mercado Libre documentation confirms seller search excludes certain
  cancelled orders: [Search orders](https://developers.mercadolibre.com.mx/en_us/manage-sales).
  The observed discrepancy invalidates the assumption that seller-search IDs
  alone exhaust the authoritative inventory. The precise exclusion reason for
  each of these ten orders was not established by the aggregate owner/date check.
- Next correction must combine bounded search acquisition with direct validation
  of known persisted identities absent from search, retaining only source-proven
  seller/date matches and handling genuinely unavailable detail explicitly. Keep
  atomic publication and source ownership checks; do not remove legitimate orders
  or silently label a search-only partial inventory complete. Also revisit legacy
  no-expiry coverage and union bounds. No new executable code/image changed in
  this checkpoint; rollback of its documentation does not modify stored data.
- This failure is actionable live evidence, not a reason to close or mark the
  whole goal blocked. Required formula HTTP, real Sheet, app and hardening checks
  remain open. Automatic recovery stays disabled until the defect is corrected
  and the controlled worker test passes.

## Work unit: validate known orders omitted from seller search

- Order recovery now augments completed search enumeration with persisted IDs
  in the same seller/date range. IDs absent from search are fetched by detail
  before publication. A shared detail validator checks identity, current source
  owner, date range, nonempty items and supported partial-response metadata.
  Local seller attribution cannot substitute for a missing source owner.
- The existing search/date equality check remains for enumerated rows. Known
  omitted rows are accepted only when their own detail proves scope, then join
  the same normalized publication, inventory comparison and completion transaction.
  No records are deleted to force search-only equality. Missing/invalid detail
  prevents complete coverage; existing records and proof remain unchanged.
- The union of searched/known identities stays within the existing 10,000-order
  budget. The Mongo identity scan is capped at 10,001 and malformed identities
  are rejected before direct acquisition. The 240-second worker limit remains.
- Three cases failed before implementation. Regressions cover a confirmed
  cancelled extra, supported partial buyer detail, empty search with a known
  legitimate order, foreign/missing owner, wrong ID, outside-range dates and 404.
  Additional tests reject malformed/over-budget known IDs without detail calls.
- This corrects the search-only assumption exposed by the productive test,
  but is not yet a successful repetition of that test. Legacy no-expiry markers,
  large coverage unions and genuinely unavailable known detail remain explicit
  limitations; no new productive data, flag or image changes occurred here.
- Rollback boundary: known-ID acquisition and shared order-detail validation in
  the worker plus their regression cases. No schema or data rollback is needed;
  reverting reintroduces the observed inventory failure, so keep automatic
  recovery off. Build a new verified Sheets worker image, deploy it with exact
  digest/health checks, and repeat the pilot job after its normal cooldown.
  Sheets API behavior is unchanged and does not need rebuilding for this unit.
- Local verification: `uv run pytest modules/sheets/tests/test_formula_recovery.py`
  with the task-owned replica set passed 112 tests in 16.29s. Root regression
  passed 3,718 tests with 9 skips in 82.33s; the eight protected Mongo cases passed
  separately in 2.46s. Remaining skip is Caddy's no-required-keys case. Ruff
  check/format, mypy (501 files) and whitespace checks pass. These do not replace
  productive pilot, authenticated HTTP or real Sheet evidence.
- Built the affected worker alone from pushed source
  `9f57afaead67b92ef1ce7d17e83919fc3a28621e` through the connected repository.
  Cloud Build `dd7bfddf-1d71-4284-9b0c-c6f8add91ee9` completed SUCCESS with
  VERIFIED provenance requested. Immutable image:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
  The repository verifier confirmed the SLSA subject, build, exact source,
  connected repository and project identity. Sanitized binding map:
  `/tmp/zeler-known-orders-build.UeJgfe/image_to_commit.json`.
  This image has not been deployed. The currently running worker remains the
  previous `ec056fc54922` image; next deploy this verified fix and repeat the
  controlled job without overriding cooldown or declaring success from local tests.

## Operational checkpoint: deploy known-order fix and repeat the pilot job

- Verified selected main `4e792545a116e698d16bfa9437499238be5145cd` differs from
  image source `9f57afaead67b92ef1ce7d17e83919fc3a28621e` only in this ledger.
  Rechecked successful Cloud Build `dd7bfddf-1d71-4284-9b0c-c6f8add91ee9`, source
  and digest. Deployed only Sheets worker at
  `sha256:98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
- Capacity preflight passed before targeted pull/recreation. To preserve margin,
  removed unused local worker image
  `sha256:03d5a2c2378a7d4e5133bb37185313559d49f21703778e3854dcfd673b011016`
  after checking every container reference and continued registry availability.
  It is recoverable by digest pull; no containers or volumes were pruned.
  Free space was 5.62 GiB before pull and 5.12 GiB afterward.
- Compose backup: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-9f57afa`.
  Immediate rollback is the retained worker image `ec056fc54922`; restore only
  that service's exact prior image, keep compatible validators, and leave
  automatic recovery disabled. API/gateway images and feature flags were not changed.
- Reopened the same pilot order request through normal queue admission:
  `ebf5decad5d7272397c1cce22e81cd5158259dea80d2d4412eebee0d817297d4`.
  Its prior cooldown still had 132 seconds at inspection. The operator process
  polls the deployed worker until this job is due and stops after one processed
  job; it does not change `available_at`, skip ownership checks or enable global
  polling. Effective coverage remains June 1–September 7 exclusive to preserve
  earlier coverage, with the initially requested August range inside it.
- The repeated job completed successfully: 22 search calls, 1,079 detail calls,
  no failure reason. The measured 260.734 seconds include waiting for the
  existing cooldown plus processing; this is not a formula latency or an
  acquisition-only duration. The worker's per-job 240-second timeout was unchanged.
- Independent Mongo readback found exactly 1,079 pilot orders in the effective
  union, completed job state, June 1–September 7 exclusive coverage with an
  unexpired proof, and zero orders with explicit field gaps in that interval.
  The ten valid known orders omitted from search were retained/reacquired; the
  six source orders previously absent could join the atomic publication without
  deleting legitimate records. This resolves the observed inventory mismatch.
- Before completion, the API container's Mongo-only VENTASTOTALES handler for
  August 8–September 6 returned DATA_UNAVAILABLE in 0.0142s. After publication,
  the same handler returned ready over 100 orders in 0.0225s. The diagnostic
  constructed no gateway client and printed no financial values or PII. It is
  explicitly an internal operator read, not authenticated HTTP, real Sheets,
  all-52 acceptance or a p95 benchmark.
- No automatic API/worker recovery flag was enabled. No new repository code or
  tests changed during this operational checkpoint; source regression evidence
  is recorded in the preceding unit. Runtime now has the verified worker fix;
  no further worker build is needed for this ledger-only update. Continue with
  shipment recovery and the outstanding end-to-end/authenticated acceptance gates.
- A second separate API-container Mongo-only read again returned ready over 100
  orders in 0.0277s. Post-recovery API and worker checks were healthy, zero
  restarts, HTTP 200/ready=true, with automatic recovery still disabled.
  Whitespace validation passed. No rollback was needed; do not roll back valid
  source data simply to recreate the prior failure.

## Operational checkpoint: recover pilot shipment addresses and costs

- At main `63b60b9591b1fedb9d45ebd949b50f6853c0ef4d`, preflight found 97 distinct
  shipment IDs referenced by the pilot's August 8–September 6 orders. All 97
  existed in Mongo, none had a recent formula observation, and no shipment
  recovery jobs existed. No identities, addresses or financial values were emitted.
- Ran one shipment-only, pilot-scoped job through the deployed worker inside
  the approved VM/container:
  `d9030f3ecfe275f47bbf3401eec1a3875b88de40ec303f8bf0cd19895c507044`.
  The job completed in 44.739s with no failure reason: 97 relationship, 97 detail
  and 97 cost requests through the normal gateway, all 291 returning HTTP 200.
  This exercised the implemented new shipment relationship/detail headers against
  the live API; it does not prove the entire order-to-shipment migration complete.
- Independent Mongo readback found all 97 requested shipments with addresses,
  costs and observation timestamps, and zero explicit field gaps. Existing
  normalization/owner checks and the transaction remained in force. No historical
  shipment inventory marker was invented from this ID-scoped acquisition.
- Before publication, the API-container Mongo-only ORDENES handler with buyer
  columns returned DATA_UNAVAILABLE for shipments in 0.0961s. After publication,
  the same August-range handler returned ready over 100 orders in 0.0924s.
  These are internal operator reads, not authenticated HTTP, a real Sheet, all-52
  acceptance or a latency percentile. Output values/PII were not printed.
- Automatic recovery remains disabled. No repository executable code, build,
  deployment, feature flag, other account or other product changed in this
  checkpoint. Existing API/worker images remain the intended versions for this
  work; no rebuild is needed for the documentation update. Unit tests are N/A
  for this operational-only checkpoint; runtime evidence is the completed job,
  source response counts and independent stored-data/handler checks.
- Rollback must not delete valid normalized source data merely to restore the
  previous unavailable state. Keep recovery off if a later issue arises and
  diagnose exact affected fields before any guarded repair. The normal previous
  image rollback boundaries and compatible validators remain unchanged.
- Requested the real ZelerData user identity and an authorized test Sheet through
  the user-input channel for the pending authenticated/Google Sheets acceptance.
  No user token was minted, copied or bypassed. The global goal remains open.

## Recovery admission: bound distinct work per seller

- Added an initial cap of 20 pending/running recovery jobs per seller across
  models. Existing active requests still coalesce at capacity; reopening terminal
  jobs consumes capacity without advancing their cooldown. Completion frees
  capacity naturally from job state, without a separate decrement counter.
- A snapshot/majority transaction and one seller identity/revision guard in
  `sheets_formula_recovery_admission` serialize concurrent admission. The new
  seller/state index bounds the active-job lookup. No source payload is stored
  in the guard; authorized seller deletion must include it with admission stopped.
  Cancellation aborts uncommitted admission. The HTTP insertion budget remains
  one second and formulas still do not call Mercado Libre or wait for recovery.
- Evidence: the initial three focused cases failed before implementation.
  `uv run pytest modules/sheets/tests/test_formula_recovery.py` then passed
  **120 tests in 22.66s** against the dedicated local Mongo replica set. Twenty
  concurrent distinct requests admitted exactly three at a configured test cap
  of three; duplicates, another seller, running jobs, terminal cooldown reopening
  and cancellation were independently checked. This is a real local queue
  boundary test, not productive HTTP or a Google Sheet acceptance result.
- Root `uv run pytest` with the dedicated local replica-set test database:
  **3726 passed, 9 skipped, 356 warnings in 83.35s**. The protected stock-time
  acquisition/execution/rollback suite was also run separately with ambient
  `MONGO_URI` unset: **8 passed in 3.09s**. Ruff check/format, mypy over 501
  source files and `git diff --check` passed.
- No productive deployment or feature flag changed in this unit. Both Sheets
  images package the changed queue, so build new verified Cloud Build images for
  `sheets-api` and `sheets-worker`, verify exact source/digest and runtime health,
  then exercise scoped admission before considering automatic pilot activation.
  The cap is not measured throughput, global fairness, API-call quota or retention
  completion. Item/catalog recovery and the global acceptance work remain open.
- Rollback boundary: remove the admission changes in `formulas/recovery.py`,
  their tests and rollout notes together, with recovery disabled. Existing job
  documents stay compatible; the unused index/guard need not be deleted for an
  image rollback. Do not delete normalized customer data or accepted jobs.

## Operational checkpoint: deploy bounded recovery admission

- Built both Sheets images from pushed main
  `f7589c95f95fac93204a9fcf46bd760f10ea38cd`, one image per Cloud Build with
  `requestedVerifyOption: VERIFIED`. The repository provenance verifier accepted
  each exact source commit, connected repository, SLSA subject digest and build:
  - API build `acc5a410-f001-4a64-93cc-517c80f59ab3`, image
    `sheets-api@sha256:f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`.
  - Worker build `6edd910f-a258-4251-a1e1-08165e63b9f2`, image
    `sheets-worker@sha256:603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b`.
  Both use the `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/`
  repository prefix. Temporary build/verification files are under
  `/tmp/zeler-admission-build.TCiSFi`; the checked-in verifier is authoritative.
- VM capacity was 5.11 GiB before deployment. Removed only unused local image
  copies `sheets-worker@sha256:b8edfdf59627d1c24fa9d2594048d145aa94a8aa16d039442b819d2bd097b945`
  and `sheets-api@sha256:f9b07c9de23c1a4f0bc611963ceb4b09c96d25c34715c08f3cb2333c70ac8d0f`
  after checking all container references and confirming both digests remain
  recoverable in Artifact Registry. No volumes, customer data or containers were
  pruned. Capacity rose to 6.12 GiB and ended at 5.11 GiB after both pulls.
- Each service passed dry-run and real deploy preflight plus the 5 GiB checks
  before pull/recreation. Replaced exactly one Compose image at a time, worker
  first and API second. Independent final inspection confirmed both actual
  running image IDs equal their verified digests, Docker health is healthy,
  restart counts are zero, and `/health` responds HTTP 200. An initial probe of
  `/ready` used an unsupported route; the corrected probe used the implemented
  `/health` endpoint and did not require any runtime fix.
- Recovery remains disabled in both containers. This proves image rollout and
  service health, not productive quota enforcement, automatic recovery, all-52
  authenticated HTTP, Google Sheets or frontend acceptance. No repository code,
  production Mongo documents, validators or recovery flags changed in this
  checkpoint. Prior local test evidence remains applicable; new unit tests are
  N/A for this operational-only update. No additional image rebuild is needed
  for this documentation-only record.
- Rollback authorities retained locally are the prior running API digest
  `c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`
  and worker digest `98d5e0e475f53b2cd3287c1b8ffbba8346e2d18eff81521360b26ca576ce64e5`.
  Backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-f7589c9`
  and `.pre-sheets-worker-f7589c9`. Restore only the affected image line and
  verify its health; never restore the entire backup over the other service's
  newer configuration. Keep recovery disabled and retain compatible validators.

## Operational checkpoint: automatic recovery enabled for the pilot

- At main `7e5f0ba3a894be8d14ab35ed334293285c09a927`, runtime preflight
  confirmed the verified admission images, 5.11 GiB free, strict/error orders
  and shipments validators with the required partial-data fields, three
  completed pilot jobs and no active nonpilot jobs. No credentials or source
  payloads were emitted. All Mongo operations ran inside the approved VM/API
  container, never through a local production Mongo client.
- Exercised the deployed queue with an explicit pilot allowlist and default
  capacity 20. A nonpilot request was rejected before mutation. Reopened the
  existing questions job
  `ce00248f852738303b602c86572cda2e8badfcaf369a6edf7e5dfd500b75827d`
  and repeated it under the same one-second admission budget used by HTTP:
  **0.0642s and 0.0106s**, one pending job, unchanged cooldown and no additional
  job documents. Normal index initialization added the seller/state index and
  successful admission created the pilot identity/revision guard. This verifies
  live admission/coalescing/isolation, not a productive saturation test of all
  20 slots or authenticated HTTP.
- Enabled `ZELERDATA_FORMULA_RECOVERY_ENABLED=true` and
  `ZELERDATA_FORMULA_RECOVERY_SELLERS=82453304` on the worker first. The normal
  resident poller claimed and completed the questions job in **one attempt**,
  with no failure reason; independent Mongo inspection showed fresh coverage
  and completion at `2026-09-07T23:16:10.449Z`. No operator `process_one` call
  was used. There remained zero active nonpilot jobs. The total pilot questions
  collection count was 101, which is not a count of rows acquired in this run.
- After that verification, enabled the same exact pilot scope on the API.
  Each change passed dry-run/real preflight, preserved the immutable image,
  changed only the selected service's two environment keys (checked against
  rendered Compose), and recreated only that service. Final independent checks
  showed both runtime environments pilot-only/enabled, both verified image IDs
  unchanged, Docker health healthy, zero restarts and HTTP 200 from `/health`.
  Free capacity remained 5.11 GiB. Other products and sellers were not activated.
- The API-container Mongo-only PREGUNTASKPI handler returned ready with three
  questions for August 8–September 6 in **0.0215s**. The initial operator probe
  mistakenly supplied the orders argument `fecha_inicial`; correcting it to the
  existing questions contract `fecha_inicio` resolved that probe error without
  changing application code. This is not authenticated HTTP, a real Sheet,
  all-52 acceptance or a p95 measurement. Those acceptance gates remain open,
  along with item/catalog recovery and minimum hardening.
- Rollback: set recovery enabled to false on both Sheets services and recreate
  each with normal capacity/health checks; keep the pilot allowlist and current
  images. Stop or allow any already-running job to finish through normal worker
  lifecycle handling. Do not delete queued jobs, guard metadata or normalized
  data. Backups are
  `/opt/zeler-platform/docker-compose.yml.pre-pilot-recovery-sheets-worker-7e5f0ba`
  and `.pre-pilot-recovery-sheets-api-7e5f0ba`; never restore either whole file
  over subsequent service configuration. Validators stay compatible.
- This checkpoint changes runtime configuration, indexes, queue state and
  normally recovered question data, not repository executable code. Prior unit
  evidence applies; the acceptance evidence for this operational unit is live
  admission, automatic completion, stored freshness and independent service
  checks. No new Cloud Build image is needed for this documentation record:
  both deployed images still match executable main source `f7589c9`.

## Catalog recovery prerequisite: bind responses to requested identities

- The existing historical catalog acquisition accepted another product/item's
  identity and silently omitted unnormalizable responses. It now rejects a
  product snapshot unless its identity matches the requested product, and a
  buybox snapshot unless both item and catalog identities match the source row.
  Static errors contain no remote payload. Acquisition fails before backfill
  writes; this does not establish completeness of every optional snapshot field.
- TDD: five cases failed before implementation. The complete historical-backfill
  suite then passed **45 tests in 0.27s**, including the existing successful
  catalog case and five rejection cases checking no backfill collections were
  written. This harness uses fake gateways/storage, not live source acceptance.
  Root tests with the dedicated local replica set: **3731 passed, 9 skipped,
  356 warnings in 85.44s**. Protected stock-time tests separately with ambient
  `MONGO_URI` unset: **8 passed in 2.67s**. Ruff check/format, mypy over 501
  source files and whitespace checks passed.
- Read-only pilot counts from the approved VM/API container: 1,562 stored items,
  2,302 item formula rows, 386 catalog product snapshots and 473 buybox snapshots.
  Stored items link to 761 distinct catalog products through 1,209 items. These
  are stored counts, not verified current source inventory or a freshness proof.
- Automatic item/catalog acquisition is still unimplemented. The historical
  entrypoint derives item work from historical orders and can include claims;
  do not wire that entire operation into a catalog miss. Reuse validated
  normalization with bounded current-source acquisition and honest inventory/
  snapshot coverage. Pilot questions/orders/shipments recovery remains enabled.
- No production code or configuration changed here. Both Sheets images package
  this module and need new verified Cloud Build images before this correction
  runs there; last verified images use executable source `f7589c9`. Verify
  catalog identity rejection, valid acquisition and service health on rollout.
  Rollback is limited to the two fetch-helper checks and their regression tests;
  no schema/data reversal is needed. Keep catalog automatic recovery disabled
  until its complete acquisition/publication path is verified.

## Current item acquisition: live inventory and search omissions

- From main `3b2641a4b11d335cbacb941919ebe686c444b2f0`, performed read-only
  pilot source/Mongo comparison inside the approved VM/API container through
  the normal bootstrap gateway client. No formula request, raw payload logging,
  local production Mongo connection, writes or feature-flag changes were used.
- A bounded scan returned **1,900 unique IDs in 19 pages**, with unchanged total,
  no duplicates and count equal to the source total. Mongo contained **1,562**
  pilot items: **356 source IDs absent from Mongo**, **18 stored IDs absent from
  search**. One multiget verified HTTP 200, requested identities and pilot
  ownership for 20 missing items. Scan plus that sample took **4.928s**; this is
  acquisition latency, not formula HTTP latency or proof of all 1,900 details.
- A separate scan/comparison and detail check of the 18 omissions took **4.023s**:
  **12 HTTP-200 pilot-owned details** (5 paused, 7 closed) and **6 HTTP 404**.
  Do not delete the 18 because search omitted them, or label the six 404s
  permanently unrecoverable. Retain their known data while distinguishing
  current source availability from persisted historical evidence.
- This changes the implementation path: `run_item_detail_enrichment` currently
  loads only existing Mongo items, so it cannot discover the 356 missing IDs.
  Current-item recovery needs source discovery plus known-ID revalidation,
  bounded detail/enrichment, normalized persistence and honest per-field/current
  inventory coverage. A source-search-only equality gate or an all-history
  order backfill would not satisfy this evidence. Do not make six unavailable
  details prevent unrelated available item data from being useful.
- Source contract checked against Mercado Libre's
  [Items and searches documentation](https://developers.mercadolibre.com.mx/es_mx/items-y-busquedas):
  scan pagination for larger inventories and multiget batches up to 20. The
  live results above verify the exercised pilot paths, not every documented
  variant. Unit tests/rollback are N/A for this read-only checkpoint; the only
  repository change is this evidence record. The prior catalog identity fix
  still requires verified Sheets image builds and rollout; no new rebuild is
  required solely for this documentation. The global goal remains open.

## Item discovery now feeds the existing enrichment workflow

- Added opt-in `--discover-current-items` to `--source items-enrich`, and
  `discover_current_items=True` to the existing Python entrypoint. It scans
  current seller IDs, unions them with known Mongo IDs (including search
  omissions), then reuses existing multiget ownership validation, optional
  enrichment and canonical Item normalization. No new collection or alternate
  raw-payload persistence path was added.
- Discovery requires a numeric seller, stable total, unique valid IDs and a
  complete count; it permits short pages/reused cursors and caps the inventory
  at 10,000 IDs, scan at 201 pages/180 seconds, and detail batches at 20.
  Combining discovery with an explicit item filter is rejected. The CLI rejects
  discovery on another source before connecting. These are scan bounds, not a
  deadline for the complete enrichment operation.
- New documents are inserted only after all planned detail/enrichment/schema
  validation; a concurrent insert raises without overwriting that document.
  Existing 404 handling preserves known historical records while available
  items proceed. Dry run does not insert. No formula projection or completeness
  marker is published by this operation; follow the existing enrichment-before-
  projection ordering. `items_read` still counts existing Mongo inputs, while
  validated/planned/updated counts can include discovered new items.
- TDD: initial four real-Mongo scenarios and the CLI-scope case failed before
  their changes. Recovery plus Sheets backfill suites passed **274 tests in
  22.91s**; checks include new-item insertion, dry run, foreign source rejection,
  concurrent insert preservation, historical 404 retention and scan integrity.
  Root: **3743 passed, 9 skipped, 356 warnings in 85.92s**. Protected stock-time
  suite separately: **8 passed in 2.11s**. Ruff check/format, mypy (501 files)
  and whitespace checks passed. The persistence harness uses actual dedicated
  local Mongo and synthetic source responses, not productive acceptance.
- Not deployed or connected to formula recovery yet. Existing-item updates
  retain their previous behavior; review/guard concurrent updates before broad
  productive discovery writes. Still needed: productive discovery/enrichment,
  projected-row verification and asynchronous item/catalog job integration with
  honest coverage. Both Sheets images need verified Cloud Build refreshes and
  runtime verification for this change and the pending catalog identity fix;
  last verified deployed executable source remains `f7589c9`.
- Rollback removes the discovery flag, scanner, union/insert branch and associated
  tests, preserving the prior enrichment path. Do not delete successfully
  normalized discovered data on rollback. Pilot recovery configuration is
  unchanged and the global goal remains active.

## Item enrichment preserves concurrent and newer persisted state

- Existing-item enrichment now writes only while the complete Mongo document
  still equals the original read snapshot, using an atomic `$expr`/`$literal`
  equality guard. Checking only `last_updated` would miss concurrent status or
  enrichment changes at the same timestamp. Deleted documents are not recreated
  and unmatched writes are not reported as successful updates.
- Rejects an older detail timestamp, or a missing comparable source timestamp
  when Mongo already has one. It compares the actual source detail timestamp,
  not the canonical merged document, which could inherit Mongo's timestamp.
  Static failures require retrying from current data; no source payload is
  included. New-item insert-only behavior is unchanged.
- Real local Mongo tests reproduced concurrent price/status changes, deletion,
  stale source and undated source before the checks; they now preserve stored
  state, while an unchanged input still enriches successfully. The recovery and
  backfill suites passed **280 tests in 23.58s**. The consumer suite's fake Mongo
  matcher was extended to evaluate the guard; **8 tests passed in 0.27s**.
  Protected stock-time tests separately passed **8 in 2.29s**. No productive
  execution or deployment occurred in this unit.
- Final root suite with the dedicated local replica set: **3749 passed,
  9 skipped, 356 warnings in 87.82s**. Ruff check/format, mypy over 501 source
  files and `git diff --check` passed on the final executable snapshot.
- The enrichment batch is not an all-or-nothing transaction: a conflict can
  occur after earlier item writes succeeded. No completeness marker is emitted,
  and retries must re-read current state. This is a per-document lost-update
  guard, not automatic job scheduling, projected-row acceptance or proof that all
  required item fields are available.
- Both Sheets images need verified Cloud Build refreshes for the pending
  catalog identity, discovery and update-guard changes; deployed executable
  source was last verified at `f7589c9`. Verify dry-run/source discovery, guarded
  enrichment and independent persisted/projection results in the pilot runtime
  before claiming productive completion. Rollback removes these checks and test
  changes only; no schema or customer-data rollback is required. Keep broad
  discovery writes off if reverting the concurrent-write protection.

## Operational checkpoint: deploy item discovery and guarded enrichment

- Built and verified both images from main
  `d8b3a390291a794f109ff6f5d591bf05f2f85183`, one image per Cloud Build with
  VERIFIED provenance. Exact source/repository/build/SLSA digest checks passed:
  - API build `20122f6a-bed2-4dec-b0cc-3c147ff8ee3d`, image
    `sheets-api@sha256:a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`.
  - Worker build `21831493-15d7-4ba9-9c7e-9c110fdd6682`, image
    `sheets-worker@sha256:64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`.
  Both use the existing Artifact Registry repository prefix. Temporary build
  configs/verifier are in `/tmp/zeler-item-build.HLGhj6`.
- Removed only unused local image copies at worker digest
  `ec056fc549222b97387dec5950b50af213f1224c569a37da1b19ed9b9033734d` and API digest
  `c41c4c4c9bb7105d37de73414c2005b877a2fad9c3d18fb62af2a4c1171408ce`, after checking
  all container references and confirming Artifact Registry recovery. No volumes
  or customer records were deleted. Free space went from 5.10 to 6.11 GiB and
  ended at 5.10 GiB after both pulls.
- No recovery jobs were running or pending for the pilot at the deployment
  precheck. Dry/real preflight and capacity checks passed before each targeted
  worker/API update. Final running image IDs equal the verified digests, both
  services are healthy with zero restarts and HTTP 200 `/health`, and recovery
  remains enabled exclusively for `82453304`. No other product was recreated.
- Backups: `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-d8b3a39`
  and `.pre-sheets-api-d8b3a39`. Rollback images retained locally are worker
  `603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b` and API
  `f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`.
  Restore only the affected image line, preserve the pilot environment and
  compatible validators, and verify health. Keep broad item discovery writes
  off if reverting their guard. Deployment health is not formula acceptance.

## Item inventory uses its authorized gateway client

- The first productive discovery/enrichment dry run failed on its first scan:
  HTTP 403 after 0.885s, no writes. A narrow follow-up confirmed the gateway's
  `out_of_scope` response. Registry seeds authorize `/users/*/items/search` for
  bootstrap, not Sheets; Sheets retains detail/enrichment scopes.
- The existing entrypoint now accepts a separate inventory gateway. The CLI
  creates the bootstrap client only when discovery is requested, sharing the
  existing KMS client; all detail/enrichment calls stay on Sheets. No registry
  scope, OAuth token, user authorization or module permission was bypassed or
  expanded. Four routing/persistence cases failed before this change, then
  passed with explicitly separate source clients; two CLI wiring cases cover
  discovery on/off. The focused six cases passed in 0.91s.
- These routing changes are newer than the deployed `d8b3a39` images. Both
  Sheets images need another verified build/rollout before claiming the normal
  CLI discovery path works productively. The operator-only routed dry run uses
  the existing clients as a diagnostic and is not evidence that the deployed
  CLI already contains this fix. Rollback removes only the inventory-client
  parameter/wiring and its tests; no data/schema reversal is needed.
- Root verification with the dedicated local replica set:
  `MONGO_URI='<dedicated local replica set>' uv run pytest --tb=short` returned
  **3751 passed, 9 skipped, 356 warnings in 87.10s**. The protected stock-time
  suite separately passed **8 tests in 1.96s**. Ruff check/format, mypy over
  501 source files and whitespace checks passed. Productive full enrichment
  remains a read-only diagnostic in progress; this is not persistence or
  formula acceptance.

## Verified inventory-routing images await rollout

- Routing fix and verification are pushed at main
  `016e6bdc7729b95e673caf30df6a2b09796074f7`. Both single-image VERIFIED builds
  succeeded and passed exact repository/source/build/SLSA digest verification:
  - API: build `74f1bed4-1600-462c-b75f-f21e8d40a2e0`, image
    `sheets-api@sha256:d85cbc4e027662461a359c56e0c069293306a6c2534c8ad6fc4fc0475b2c4a54`.
  - Worker: build `cc83f765-0c73-4e65-9e2a-2d2acf4777c0`, image
    `sheets-worker@sha256:6c406b58df0e084a290c194fb45f01f07bf19c0ff5fff3a56be93264ff82e399`.
  Both use the existing Artifact Registry prefix. Configs and verifier are in
  `/tmp/zeler-inventory-route-build.26vQkB`.
- Not deployed at this checkpoint. The current worker is executing the bounded
  read-only diagnostic; do not recreate it or restart the diagnostic blindly.
  At 2026-09-08 00:00 UTC it had attempted 5,000 source calls, including 19 scan
  pages, 63 detail batches and 1,247 sale-price lookups. Acquisition was still
  running, with a 900-second operator timeout. No persistence or completeness
  proof has been produced. Resume the existing process and record its terminal
  result before deciding the next acquisition or rollout step.
- This workload cannot be adopted unchanged into a recovery job with the
  existing 240-second worker budget. Implement bounded, resumable enrichment
  before automatic inventory recovery; retain Mongo-only formula HTTP reads.
  Neither these builds nor the diagnostic replace the remaining authenticated
  52-formula, real-Sheet and current-app acceptance checks.

## Bounded item acquisition after the full-inventory timeout

- The routed productive dry run terminated with `TimeoutError` at **900.003s**:
  6,032 attempted calls (19 scans, 76 detail batches, 824 variation lookups,
  1,498 sale-price lookups, 2,996 listing-price lookups and 619 shipping-option
  lookups). No item/projection writes or completeness markers were produced.
  This is an incomplete acquisition, not proof that remaining data is absent.
  Do not repeat that full workload unchanged or place it in a 240-second job.
- `run_item_detail_enrichment(acquire_item_ids=...)` now accepts an explicit
  batch of 1–20 known or missing IDs. The operator CLI exposes repeated
  `--acquire-item-id` flags with `--source items-enrich`; dry-run remains default.
  It does not scan the inventory. Empty, duplicate, malformed, oversized or
  conflicting scopes fail before storage/network access. Only the selected
  seller/IDs are loaded; the existing `--item-id` missing-ID rejection remains.
- New items use the existing ownership/schema/enrichment checks and insert-only
  persistence. Existing documents retain the full-preimage concurrency guard;
  404s preserve history and never insert placeholders. No batch creates a
  whole-inventory freshness proof. Acquisition completes before writes within
  each batch, but writes remain per-document, not a batch transaction. Retry a
  failed batch from fresh stored state; previously completed batches need not
  be reacquired. This primitive does not itself persist a resumable job cursor,
  implement automatic scheduling or publish projected rows.
- Stricter CLI wiring tests also exposed the unfiltered discovery path passing
  `[]` where the helper requires `None`. The CLI now passes `None` for omitted
  filters. Therefore the verified `016e6bd` images above must not be deployed
  as the finished discovery/acquisition solution; they remain undeployed.
- Initial acquisition tests failed before implementation; strengthened CLI
  tests reproduced the empty-filter defect. The focused recovery/backfill run
  with dedicated local Mongo passed **301 tests in 24.25s**. It includes bounded
  scope, new-item dry-run/write, foreign ownership, concurrent insert, unrelated
  data preservation, 404 absence and retrying a failed batch without rewriting
  a completed batch. Ruff check and mypy over 501 files passed.
- Rollback removes the acquisition argument/CLI wiring, optional missing-ID
  loader behavior and its tests; retain the independent empty-filter correction.
  Never delete successfully normalized items on rollback. Both Sheets images
  need verified builds for this executable snapshot, capacity/preflight-gated
  rollout and pilot batch persistence/projection checks before runtime acceptance.
- Final root run with the dedicated local replica set: **3770 passed, 9 skipped,
  356 warnings in 85.56s**. Protected stock-time cases ran separately with
  `ZELER_RS0_TEST_URI` and no ambient `MONGO_URI`: **8 passed in 2.48s**.
  Final Ruff check/format, mypy (501 files) and whitespace checks passed.

## Operational checkpoint: deploy bounded item acquisition

- Both images were built from pushed main
  `d29ae5218efd92f229edf58f0cfbb37b8d963f96` and verified against exact connected
  repository/source/build/SLSA digest metadata:
  - API build `3e895b8e-5add-44cd-879d-299381ed5815`, image
    `sheets-api@sha256:80df92e6eb2b91e85e9b27c7700df4618b7211c814b1a013749a867ffb9c9433`.
  - Worker build `8fdf089b-1b51-4282-9580-96fdfe209e90`, image
    `sheets-worker@sha256:d885b5117058456430d060d38cc11015995d8f9bcb8172914e6298fdc8abdfe7`.
  Artifact Registry prefix is unchanged. Build configs/verifier are in
  `/tmp/zeler-item-batch-build.odBPPv`; the intermediate `016e6bd` pair was
  never deployed.
- Removed only unreferenced local worker `603dce2137f2952ce9f1f70e18687132a8f7cec771a2f2dbdee1ffc62542eb1b`
  and API `f2c929e3fb43df0fec66eaa59b99cef8c180e39bc375b2e106a23ab4c506bdd3`
  copies after checking all container references and Artifact Registry
  recoverability. No customer records or volumes were deleted. Free space
  increased from 5.09 to 6.10 GiB and finished at 5.09 GiB after both pulls.
- Queue precheck showed zero running jobs and zero pending pilot jobs. Each
  targeted deployment passed dry/real preflight, exact one-line replacement
  and 5 GiB capacity checks. Worker then API were recreated; final probes show
  both running the verified digests, healthy, zero restarts, HTTP 200 `/health`,
  with recovery still enabled only for `82453304`. Other products were untouched.
- Compose backups are `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-d29ae52`
  and `.pre-sheets-api-d29ae52`. Previous running worker `64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`
  and API `a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`
  remain the local rollback authorities. Restore only the affected image line,
  preserve pilot configuration and schemas, and verify health. Retain normalized
  acquired data; do not revert it merely because executable code is rolled back.
- First productive bounded acquisition completed in **29.499s** (operator
  scan + dry-run + fresh acquisition/write + projection, not formula HTTP).
  A current 1,900-ID source scan found 1,562 persisted pilot items; the first
  20 missing IDs were selected in memory. Dry-run validated all 20 in 16.845s.
  Fresh write acquisition then inserted all 20 by 28.854s. Independent Mongo
  checks found 20 refreshed documents and zero violations of the live validator.
- Projecting that persisted batch wrote **24 formula rows and 24 SKU-index
  upserts**, covering all 20 items, with zero projection errors or ambiguous
  identities. Two items lacked parent-level SKU but variation rows supplied
  their identities. All 24 rows had permalink/thumbnail, six had catalog IDs
  and 22 had inventory IDs. The summary's `skipped_missing_source=18` counts
  missing diagnostic fields, not 18 failed writes; all 24 planned rows persisted.
- Read-only audit of the exact latest 20-item sync cohort found trusted shipping
  costs, listing-fee projections and fixed fees for all 20. Promotion state was
  `authoritative_absent/no_trusted_promotion` for all 20; this records persisted
  classification, not independent proof of every upstream absence. The current
  resolver returns the same empty projection for malformed/non-promotional
  sale-price responses, so audit that distinction before claiming optional
  absence is trustworthy. Six variation-detail lookups also enriched successfully.
- No inventory completeness marker was published, and the remaining inventory
  is not acquired by this one batch. Automatic item/catalog recovery, field
  availability semantics and authenticated formula/Sheet/app acceptance remain
  open. The bounded operator process is terminal; do not rerun it blindly as
  a status check because it selects and writes the next missing batch.

## Promotion absence is distinct from acquisition failure

- Sale-price acquisition now requires a well-formed positive amount, currency
  and an explicitly present `regular_amount`. An explicit null regular amount
  or a valid non-discounted price can represent absence; missing/malformed
  fields or a rejected discounted projection produce `malformed_response`, not
  `authoritative_absent`. The official
  [price contract](https://developers.mercadolibre.com.mx/api-de-precios) and
  [sale-price example](https://developers.mercadolibre.com.mx/en_us/en_us/price-apl)
  distinguish nullable regular price from missing required response data.
- Formula-row projection now carries schema-normalized enrichment state into
  `current`. Dashboard promotion cells honor that state: explicit acquisition
  failures yield `DATA_UNAVAILABLE`, and authoritative absence yields `NA`.
  A previously persisted promotion retained after a transient failure remains
  stored, but is no longer displayed as a current promotional price. Acquisition
  reasons remain available in normalized state; no raw API response is retained.
- Seven malformed-response cases initially reproduced false absence; a separate
  transient-failure case reproduced a stale promotional price being displayed.
  The corrected acquisition → projection → dispatcher suite passed **22 focused
  cases in 0.23s**. This changes an unsafe prior test expectation deliberately,
  to honor the goal's prohibition on stale data being presented as current.
- A read-only source audit of the last productive 20-item sync cohort found
  **20 well-formed responses with explicit null regular amounts**, no malformed
  required fields, and no writes. This supports absence for that cohort at the
  audit time; it does not establish freshness for every item or future queries.
- Existing rows without enrichment state retain their legacy reader behavior
  pending acquisition/reprojection; state freshness/expiry and public reason
  reporting still need full acceptance. This unit does not complete automatic
  item/catalog recovery or the 52-formula/real-Sheet/app checks.
- Not deployed in this unit. Both Sheets images require verified Cloud Build
  refreshes from the resulting executable commit, health/source verification,
  and pilot reprojection/HTTP checks. Current deployed executable source remains
  `d29ae5218efd92f229edf58f0cfbb37b8d963f96`. Rollback removes the resolver shape
  checks, projected enrichment state and promo-cell gate with their tests;
  retain acquired customer data and do not treat rollback as approval to display
  failed/stale promotion data.
- A source HTTP 404 also no longer proves promotion absence: the sale-price
  resolver records `malformed/http_404` instead of the generic fetch classifier's
  `authoritative_absent`. The new rejection case failed before this correction;
  final focused promotion/source cases passed **23 tests in 0.23s**. Other
  resources' generic HTTP classification is unchanged.
- Final root suite with the dedicated local replica set: **3779 passed,
  9 skipped, 356 warnings in 87.56s**. Protected stock-time tests separately
  passed **8 in 2.19s**. Ruff check/format, mypy (501 files) and whitespace
  checks passed. The read-model Mongo schema permits this normalized `current`
  metadata; no validator relaxation was made.
- Consumer review found a remaining separate path:
  `handlers_quality_calculator._selected_price` reads the promotion directly
  and falls back to the ordinary price for `tipo_precio=promo`. Apply the same
  availability contract there, including dependent net/margin results, before
  claiming all promotion consumers are correct. This dashboard unit alone is
  not calculator acceptance.

## Calculator shares the promotion availability contract

- `tipo_precio=promo` no longer falls back to the ordinary price when the
  requested promotional price is absent or unavailable. Explicit acquisition
  failure yields `DATA_UNAVAILABLE` in price and dependent estimated net;
  authoritative absence yields `NA` in both. Independently available shipping,
  commission, fixed-fee and total-cost cells remain available. Ordinary/base
  price selection is unchanged.
- Dashboard and calculator now share the existing promotion reader and numeric
  validation in `formulas/pricing.py`; the dashboard no longer owns a separate
  implementation. A trusted state with a missing or malformed projection is
  unavailable, not proof of absence. Legacy unmarked-row behavior remains a
  separate acquisition/reprojection obligation, and temporal freshness still
  requires the outstanding snapshot acceptance work.
- Four calculator cases reproduced stale/fallback prices before implementation.
  A fifth reproduced a trusted marker without its projection being reported as
  absence. Six state scenarios now exercise both promo and ordinary modes through
  the actual dispatcher, including preservation of valid cost totals. Combined
  calculator/core/backfill suites passed **205 tests in 0.39s**; Ruff check/format
  and mypy over 502 source files passed. No productive write occurred in this unit.
- This change and the preceding promotion acquisition fix need verified new
  Sheets API/worker images, pilot reprojection, health/source checks and formula
  HTTP acceptance. Last verified deployed executable source is `d29ae52`.
  Rollback restores the dashboard-local helper and calculator selection/output
  code with their tests; no persisted data deletion is necessary. Reverting is
  not permission to report unavailable promotional prices as actual values.
- Final root regression with the dedicated local replica set: **3785 passed,
  9 skipped, 356 warnings in 94.73s**. Protected stock-time suites separately
  passed **8 tests in 11.91s**. Final Ruff check/format, mypy (502 files) and
  whitespace checks passed; these are local verification, not productive HTTP
  or Google Sheet acceptance.

## Promotion/calculator image provenance

- Built both Sheets images from pushed main
  `ab6e01f60ad7b83402a822ef4325f0014d3bd175`, covering the promotion acquisition
  and shared dashboard/calculator reader changes. Exact connected repository,
  source, successful build and SLSA digest verification passed:
  - API build `d11f4f80-ed24-468f-ab37-2aa049c8ca87`, image
    `sheets-api@sha256:ec894447aa2eae1c5a2d0497938aa38034aafac394641fa7b4d5a1ab70aab9ff`.
  - Worker build `845acd23-c284-47ea-a9e6-334609d4ac91`, image
    `sheets-worker@sha256:1e83c732e90a78ee0464cc62453d4ce93f425c7c358a8d2b1a3a84de4bf6fe92`.
  Existing Artifact Registry prefix is unchanged. Temporary configs/verifier:
  `/tmp/zeler-promo-build.WkS0jv`.
- The local SDK process twice exited with SIGSEGV while reading artifact
  metadata. The existing builds were not restarted. Running the same verifier
  with command-scoped `CLOUDSDK_PYTHON=/usr/bin/python3` completed both checks.
  No credentials, project settings or SDK installation were changed; the
  underlying bundled-interpreter crash cause is not established.
- Before rollout, both existing services were healthy with zero restarts,
  `/health` HTTP 200 and recovery enabled only for `82453304`. There were zero
  running recovery jobs and zero pending pilot jobs. Removed only unreferenced
  local worker `64b87403ec0d3655eedd8d57ee68352fd8ede1c5a9fbb516130fdf5d0867d015`
  and API `a4f62877759b00eedafeddb750735710047edcb68624fa7f215ccb71f2b77cf3`
  image copies after checking all containers and Artifact Registry recovery.
  No data or volumes were deleted. Root free space increased from 5.58 to
  6.59 GiB; the currently running image pair was retained for rollback.
- The worker deployment returned successful dry/real preflight, pull and
  targeted recreation, with backup
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-ab6e01f`.
  The API deployment observation handle disappeared when the execution
  environment changed; it was not restarted. A new read-only VM inspection
  proved both services running the verified `ab6e01f` digests above, healthy,
  zero restarts and `/health` HTTP 200, still enabled only for the pilot.
  Root free space after both deployments is **5.57 GiB**.
- The prior running worker `d885b5117058456430d060d38cc11015995d8f9bcb8172914e6298fdc8abdfe7`
  and API `80df92e6eb2b91e85e9b27c7700df4618b7211c814b1a013749a867ffb9c9433`
  are the rollback authorities. Restore only the affected image line, preserve
  pilot configuration and normalized data, and verify runtime health. Do not
  restore an entire older Compose backup over unrelated service changes.
- The original refresh diagnostic stopped before acquisition/writes because
  the latest-sync cohort had changed to one document. A read-only check found
  1,582 dated pilot items. Selection was changed to the 20 most recently synced
  pilot items, with a deterministic ID tiebreaker and a hard 20-document limit;
  no assumption was made that the original cohort remained unchanged.
- The bounded operator refresh then validated all 20 items in dry-run at
  **11.282s**, reacquired and guardedly updated all 20 by **21.402s**, and completed
  projection plus persisted-row checks in **22.097s**. Independent live-validator
  checks found zero invalid items and all 20 refreshed timestamps. It wrote
  24 formula rows and 24 SKU-index upserts, with zero ambiguous identities or
  projection errors. The diagnostic missing-field count was 17, not 17 failed
  writes; all 24 planned formula rows persisted.
- All 24 persisted rows carried promotion acquisition state. Reading those
  actual Mongo rows through the deployed shared promotion reader and calculator
  row function returned `NA` in all 24 dashboard promotion, calculator promo
  price and dependent net cells, matching authoritative absence. No fallback
  ordinary price was substituted. This is productive persisted-row evidence,
  not authenticated HTTP dispatcher or real-Sheet acceptance, and no whole-
  inventory completeness/freshness marker was published.
- The operator process is terminal. `/tmp/zeler-promo-refresh.py` captures the
  corrected bounded scenario; executing it again performs fresh API acquisition
  and writes and must not be used as a read-only status probe. Remaining work
  still includes full inventory acquisition, asynchronous item/catalog recovery,
  temporal availability and the complete formula/Sheet/app acceptance gates.

## Full pilot ID acquisition: independent readback

- The missing-item operator's observation handle disappeared; it was not
  restarted. A read-only check in the approved worker container found zero
  matching acquisition processes. Two fresh source scans independently found
  **1,900 current IDs**, all present among **1,918 persisted pilot items**,
  preserving 18 historical IDs outside the scan. The live Mongo validator
  rejected zero pilot items. The original final batch totals/timing were not
  captured and are not claimed here.
- There are **2,831 formula rows**, 529 carrying enrichment state. Eleven source
  publications have no formula rows. A scoped dry-run confirmed 11 missing
  parent SKUs and 10 missing variation SKUs; the projector's SKU requirement is
  an unresolved omission for consumers that query by publication ID. No SKU
  was invented, no data deleted and no whole-inventory freshness marker set.
- Persisted current-source states expose remaining field acquisition work:
  promotion: 1,890 authoritative absence, 6 unauthorized, 4 transient;
  shipping: 1,894 trusted, 5 basis mismatch, 1 transient;
  commission: 1,886 trusted, 10 basis mismatch, 2 unauthorized, 2 transient;
  fixed fee: 1,885 trusted, 9 transient, 6 unauthorized. These are stored states,
  not proof of present freshness. Zero missing IDs does not close field coverage,
  reprojection, asynchronous recovery or authenticated formula acceptance.
- The audit script `/tmp/zeler-audit-inventory.py` reads production only inside
  the approved VM/container and prints aggregates. A local SDK exit 139 during
  the second audit was followed by the same read-only check with command-scoped
  system Python, which succeeded; no acquisition writes were repeated.

## Calculator cost availability

- The calculator previously used retained shipping, commission and fixed-fee
  values even when their persisted acquisition state reported failure. It now
  propagates `DATA_UNAVAILABLE` from failed acquisition or trusted-but-missing
  numeric data into the affected cells, total costs and estimated net. Explicit
  authoritative absence yields `NA`; independently valid price/cost cells remain
  visible. Unmarked legacy rows keep their prior behavior pending reprojection
  and temporal coverage work. This does not yet fix the separate dashboard cost
  readers or validate calculator cost projections against current pricing basis.
- Strict TDD reproduced 18 failures before implementation. The parameterized
  dispatcher cases cover all three cost sources and seven state/value scenarios;
  calculator/core/backfill suites passed **226 tests in 0.49s**. Ruff check/format,
  mypy over 502 files and whitespace checks passed. Productive HTTP and real-Sheet
  acceptance remain outstanding; this code has not been deployed.
- Rollback is limited to calculator cost selection, sentinel propagation and the
  associated tests. No data rollback or deletion is required. Both Sheets images
  still have last verified source `ab6e01f`; build the affected API/worker images
  from the next verified pushed main source, verify digest/health and pilot
  cost-cell behavior before claiming runtime correction.
- Final root `uv run pytest --tb=short` against the dedicated local replica set:
  **3,806 passed, 9 skipped, 356 warnings in 90.80s**. The eight protected
  stock-time tests were then run separately with `MONGO_URI` unset and the
  explicit local `ZELER_RS0_TEST_URI`: **8 passed in 3.67s**. An earlier root run
  omitted 19 extra Mongo integration tests because the local container was
  stopped at startup; it is superseded by this fully connected run. Only
  `zeler-goal-mongo` was started, retaining its volume and leaving the older
  low-ulimit container stopped; `rs0-dev` was verified writable primary.

## Calculator preserves actual losses

- The calculator formatted estimated net with the non-negative input validator,
  turning valid losses into `NA`. Only the computed Decimal net now uses the
  signed numeric formatter; price/cost validation and unavailable sentinels are
  unchanged. No new data, schema or projection is introduced.
- Dispatcher regression scenarios first returned `NA` instead of -10 and -0.25;
  break-even already returned zero. All three now pass. The focused command
  `uv run pytest modules/sheets/tests/test_formula_handlers_quality_calculator.py
  modules/sheets/tests/test_formula_handlers_core.py
  modules/sheets/tests/test_sheetseller_backfill.py --tb=short` passed **229 tests
  in 0.42s**. Root Ruff check/format, mypy (502 files), and whitespace checks pass.
- Runtime acceptance remains pending the combined calculator release. Rollback
  touches only the estimated-net output expression and these three regression
  scenarios; no data rollback is needed. The previous cost-state correction and
  this loss fix both require the affected Sheets image release and live checks.
- Final local root regression: **3,809 passed, 9 skipped, 356 warnings in 89.58s**.
  The protected stock-time suites separately passed **8 tests in 3.39s** with
  the explicit local replica-set URI and `MONGO_URI` unset. Before release,
  read-only VM inspection confirmed both prior `ab6e01f` Sheets images healthy
  and 5,976,756,224 bytes free on root; capacity must be checked again before pull.

## Calculator release image provenance

- Built from pushed main `898c91671f72fc0941517c3b2fa947313f0c789c`, covering both
  failed-cost availability and signed estimated-net output. Each successful
  Cloud Build produced one image with `requestedVerifyOption: VERIFIED`; exact
  repository/revision, build and single-subject SLSA checks passed:
  - API build `79634177-c6c1-4a75-90bb-beb50197538a`, image
    `sheets-api@sha256:d9b86c8403e1ac27314893b04be5a5d446215957a006e8c644217061b4370641`.
  - Worker build `8c7af03d-7ab3-4313-adba-6d301588b37d`, image
    `sheets-worker@sha256:2aa013bb375c1d14c5dd516f39f472879336c923d69acf425a34be9e1c97b806`.
  Artifact Registry prefix remains unchanged. Build configs and the verifier
  are under `/tmp/zeler-calculator-build.RzLBZh`; metadata commands used
  command-scoped system Python for the previously observed SDK instability.
- Rollback authorities are the previously running `ab6e01f` API
  `ec894447aa2eae1c5a2d0497938aa38034aafac394641fa7b4d5a1ab70aab9ff`
  and worker `1e83c732e90a78ee0464cc62453d4ce93f425c7c358a8d2b1a3a84de4bf6fe92`.
  Restore only the affected image line and recreate that service if necessary;
  preserve pilot configuration, normalized data and unrelated Compose changes.
- Both targeted deployments passed dry/real preflight, exact-one Compose image
  replacement and the pre-pull 5 GiB floor. Worker recovery had zero running
  jobs before recreation; recovery configuration remained pilot-only. Backups:
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-898c916` and
  `/opt/zeler-platform/docker-compose.yml.pre-sheets-api-898c916`.
  Both exact new digests became healthy with zero restarts and `/health` HTTP
  200. Free bytes after worker were 5,433,823,232; after API, **4,891,086,848**.
  Reclaim narrowly verified unused image space before any further image pull;
  no image, volume or data cleanup was performed in this release.
- A read-only check through the new worker's calculator over 2,831 actual Mongo
  rows independently checked 2,813 numeric net results. It found zero negative
  nets and zero projected failed-cost cells, so it does not prove those branches
  with live data; controlled dispatcher tests cover them. In particular, source
  acquisition failures were not yet represented in those persisted rows.
- The bounded recovery operator then scanned current source IDs and selected
  **all 17 current publications with recorded cost acquisition failures** (hard
  cap 20). It dry-validated 17, freshly acquired and guardedly updated all 17,
  verified zero live-schema violations, and updated/read back 27 formula rows.
  All 27 rows reported trusted shipping, commission and fixed-fee states; none
  of the selected 17 items retained a failed-cost state. Detail-unavailable count
  was zero, and the complete operator took **26.648s**. This is operator duration,
  not formula HTTP latency. No source failure was artificially introduced to
  exercise the unavailable branch.
- `/tmp/zeler-calculator-build.RzLBZh/recover_costs.py` performs fresh production
  acquisition/writes and is terminal; do not execute it as a status probe. This
  repair sets no whole-inventory freshness marker and does not close automatic
  item/catalog recovery, legacy projection, missing-SKU or HTTP/Sheet acceptance.
- Final read-only check through the deployed API container found **2,834 actual
  persisted formula rows**, all with independently checked numeric net arithmetic.
  None exercised a negative net or unavailable cost. This confirms the recovered
  rows are readable by the API image, not authenticated formula dispatch, Google
  Sheets execution, complete SKU coverage or present temporal freshness. Both
  deployment processes and the bounded recovery process are terminal.
