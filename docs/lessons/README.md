# Engineering Lessons

This is the minimal, durable record of proven and failed engineering paths for
`zeler-platform`. Consult it before relevant work to reuse evidence, prevent
repeat failures, and promote stable knowledge to its proper operational form.

## Quick path

1. Read this section before planning or changing a relevant area.
2. Search the active index by area and task keywords.
3. Read the matching entries, including the proven path, failed path, and source.
4. Search Engram **also** when the task refers to prior work or runtime state.
   Treat runtime memories as leads; confirm them with current, sanitized evidence.
5. Apply the proven path and avoid the failed path. When work ends, record only a
   durable learning, or promote it using the matrix below.

## What belongs here

- A repeatable path with a clear result and proportional verification.
- A failed or unsafe path that prevents a likely recurrence.
- A compact decision boundary, guardrail, or ordering dependency.
- A reference to the authoritative test, script, runbook, ADR, `AGENTS.md`, or
  Engram record after promotion.

## What does not

- Tutorials, command transcripts, temporary debugging notes, or raw logs.
- Secrets, PII, authorization material, connection strings, or raw production values.
- Unverified claims, one-off preferences, or duplicate content from a runbook.
- Full operational procedures already maintained in `docs/deploy.md` or another
  authoritative location.

## Promotion matrix

| Signal | Promote to | Keep here |
| --- | --- | --- |
| Repeatable behavior that can regress | Test | Short result and test reference |
| Repeated command sequence | Script | Trigger and script reference |
| Operator action with safety gates | Runbook | Guardrail and runbook reference |
| Hard-to-reverse trade-off | ADR, when needed | Decision and ADR reference |
| Always-on repository behavior | `AGENTS.md` | Brief rationale and rule reference |
| Cross-session or runtime context | Engram | Search terms and current status |
| Marginal polish after safe delivery | Follow-up | Scope and reason it was deferred |

## Compact entry template

```text
### L-XXX — Short lesson
- area: <area>
- proven path: <what to do>
- failed path: <what not to do and why>
- verification/source: <proportional evidence or authoritative reference>
- status: active | promoted/reference | refuted | archived
```

## Active index

| ID | Area | Topic | Status |
| --- | --- | --- | --- |
| L-001 | Cloud Build | Temporary build configuration | promoted/reference |
| L-002 | GCP auth | Reauthentication recovery | active |
| L-003 | Cloud Build | One image per verified build | promoted/reference |
| L-004 | VM deploy | Free-space preflight | promoted/reference |
| L-005 | VM deploy | Exact Compose replacement | promoted/reference |
| L-006 | VM deploy | Authorized commit before VM access | promoted/reference |
| L-007 | ZelerData | Enrichment before item write | active |
| L-008 | Python | Exception suppression control flow | active |
| L-009 | Delivery | Good-enough completion boundary | active |
| L-010 | ZelerData | Discovery and detail client scopes | active |
| L-011 | VM deploy | Worker signals and stop deadlines | active |
| L-012 | Local tests | Isolated Mongo replica set and file-descriptor limit | active |
| L-013 | ZelerData | Quota waits and unchanged source freshness | active |
| L-014 | Broker health | Connection ownership before AMQP handshake | promoted/reference |
| L-015 | Bootstrap | Route account-link events before gateway rollout | active |
| L-016 | Bootstrap | Update the linked account without inserting a second record | active |
| L-017 | VM recovery | Inspect metrics before the telemetry cutoff | active |
| L-018 | Observability | Validate Docker log parsing with the installed agent | active |
| L-019 | ZelerData | Bound retries for optional quality 404 and overlapping item jobs | active |
| L-020 | ZelerData | Keep optional buybox offers 404 and overlapping catalog jobs from multiplying work | active |
| L-021 | ZelerData | Do not repeatedly schedule full-seller sweeps faster than they finish | active |
| L-022 | ZelerData | Suppress legacy order history only with completed interval proof | active |
| L-023 | ZelerData | Revalidate locally stored questions omitted by a complete scan | active |
| L-024 | ZelerData | Verify the claims DLQ and binding, not just the source queue | active |
| L-025 | ZelerData | Compare economic tags as membership in formula readers | active |
| L-026 | Gateway OAuth | Keep transient refresh failures eligible for retry | active |
| L-027 | ZelerData | Verify delivery progress, not just consumer readiness | active |
| L-028 | ZelerData | Preserve independent coverage when acquiring another interval | active |
| L-029 | VM pause | Preserve Docker nanosecond proof on the actual host interpreter | active |
| L-030 | ZelerData | Pace immediately before transport, after persisted charge | active |
| L-031 | Isolated restore | Operator UID/tmp, actual CLI libc ABI and PRIMARY gate | active |
| L-032 | ZelerData | Durable work authority and non-fungible physical credit | active |
| L-033 | ZelerData | Abort bounded 429 before collector retries | active |
| L-034 | ZelerData | Commit one shipment and its cursor atomically | active |
| L-035 | Tests | Bound cancellation harness signals | active |
| L-036 | ZelerData | A paused pilot must release ordinary traffic | active |
| L-037 | ZelerData | Size item and catalog sweeps to their readers' age limits | active |
| L-038 | ZelerData | A paused pilot must not freeze certified DEVOLUCIONES coverage | active |
| L-039 | ZelerData | Widening the seller scope must not widen pilots | active |
| L-040 | ZelerData | Retire pre-v2 return rows the tail inventory omits | active |
| L-041 | ZelerData | Bound whole-inventory reads and do not tie snapshots to the re-sync cut | active |
| L-042 | VM deploy | Codify memory mitigations instead of leaving VM-only overlays | active |
| L-043 | ZelerData | Re-check eligibility at claim and cap serial warming in `all` mode | active |
| L-044 | ZelerData | Size reader age limits to on-demand acquisition and compare only stored fields | active |
| L-045 | ZelerData | Serve a source-declared absence as NA instead of recovering it | active |
| L-046 | Shell tests | Keep deploy scripts bash 3.2-safe and sandbox GNU-only calls on macOS | active |
| L-047 | ZelerData | Compute interval metrics from observations at read time, not from import markers | active |
| L-048 | ZelerData | Gate a change-only history on its observation heartbeat | active |
| L-049 | Sheets DLQ | Archive on a per-resource read stamp, not on a window marker | active |

## Cloud Build and VM deployment

### L-001 — Use a verified temporary Cloud Build configuration
- area: Cloud Build
- proven path: Create a temporary configuration file with one image and
  `options.requestedVerifyOption: VERIFIED`.
- failed path: Use `--config=-`, or omit `requestedVerifyOption: VERIFIED`; the
  first fails in this environment and the second can publish an image without
  usable provenance.
- verification/source: `docs/deploy.md`, image build section.
- status: promoted/reference

### L-002 — Stop on GCP reauthentication
- area: GCP authentication
- proven path: Stop and follow the registered `gcp-headless-auth` skill.
- failed path: Blindly retry GCP commands after authentication failure.
- verification/source: `gcp-headless-auth` skill and sanitized authentication failure.
- status: active

### L-003 — Build one deployable image per verified Cloud Build
- area: Cloud Build
- proven path: Produce one deployable image for each verified Cloud Build.
- failed path: Associate multiple deployable images with one verification record;
  provenance becomes ambiguous.
- verification/source: `docs/deploy.md`, image build and immutable-image sections.
- status: promoted/reference

### L-004 — Require VM preflight capacity before pull
- area: VM deploy
- proven path: Run VM preflight and require at least 5 GiB free before pull or
  Docker Compose activity.
- failed path: Pull or run Compose without confirming the free-space floor.
- verification/source: `docs/deploy.md`, root-disk guardrails and single-service deploy.
- status: promoted/reference

### L-005 — Assert one Compose image match before replacement
- area: VM deploy
- proven path: Verify exactly one Compose image occurrence before replacing it.
- failed path: Replace an uncounted or multiply matched image reference.
- verification/source: `docs/deploy.md`, single-service deployment replacement gate.
- status: promoted/reference

### L-006 — Confirm the authorized local ref before touching the VM
- area: VM deploy
- proven path: Confirm the authorized local ref or commit matches the intended
  deployment before VM access or mutation.
- failed path: Operate on the VM from an unverified local checkout or ref.
- verification/source: `docs/deploy.md`, exact-commit Cloud Build path and deployment gates.
- status: promoted/reference

### L-015 — Route account-link events before gateway rollout
- area: OAuth and bootstrap runtime
- proven path: Start a healthy consumer with a durable `accounts.linked` binding
  before deploying the gateway publisher; pass `--seller-id` and `--job-id` as
  Cloud Run Job argument overrides with job-level override permission.
- failed path: A gateway-only fix leaves mandatory event publication unroutable;
  environment overrides do not satisfy the bootstrap Job's CLI arguments.
- verification/source: `docs/deploy.md` section 5b.1, bootstrap dispatcher
  contract tests, and the local RabbitMQ/Mongo OAuth flow smoke.
- status: active

### L-016 — Update the linked account without inserting a second record
- area: OAuth and bootstrap accounts stage
- proven path: Match the OAuth account by numeric or legacy string seller ID
  and platform app ID; update metadata only, without upsert or changing the
  stored identity and credentials. Fail the stage if no linked account matches.
- failed path: Search only the string seller ID and upsert a metadata-only
  document. OAuth stores a numeric ID, so the insert fails the production
  `meli_accounts` validator before bootstrap can continue.
- verification/source: `bootstrap/tests/test_bootstrap_phase3.py` accounts-stage
  regression tests and a disposable local Mongo smoke with the checked-in
  validator; first production rollout record in
  `openspec/changes/bootstrap-accounts-linked-dispatch/verify-report.md`.
- status: active

### L-017 — Inspect metrics before the telemetry cutoff
- area: VM recovery and resource diagnosis
- proven path: When an unresponsive guest stops reporting, query agent memory and
  process metrics before the last successful sample; combine them with hypervisor
  disk/CPU metrics and the previous boot journal after recovery. Preserve disks
  and the exact startup metadata before an authorized stop/start.
- failed path: Query only the blocked interval and infer that agent metrics were
  never configured. Missing telemetry after the cutoff cannot establish resource
  usage, the initiating process, or absence of an OOM event.
- verification/source: `docs/ops/platform-vm-recovery-20260925.md`; historical
  memory/process samples were available until 23:38 UTC even though the guest
  later stopped responding. Post-recovery worker readiness and capacity were
  checked again after settling.
- status: active

### L-018 — Validate Docker log parsing with the installed agent
- area: Ops Agent and log-based alerts
- proven path: Test the complete Docker envelope and application JSON through the
  installed agent engine and Fluent Bit, with synthetic input and stdout-only
  output. Assert the event field, severity, and absence of sensitive fixture
  markers; after rollout, verify actual Cloud Logging fields and continuing
  metrics. Preserve the receiver/pipeline names and keep a configuration backup.
- failed path: A simulation of `modify_fields` passed while the real agent kept
  sensitive fields. Parsing only the outer Docker record left application events
  as text and prevented existing event/severity metric filters from matching.
- verification/source: `docs/ops/platform-vm-prevention-20260926.md` and its tested
  runtime configuration. The original failed and the candidate passed the same
  real-engine fixtures; production subsequently emitted structured events.
- status: active

### L-042 — Codify memory mitigations instead of leaving VM-only overlays
- area: VM deploy and capacity
- proven path: Carry emergency memory mitigations (container `mem_limit`, Mongo
  `--wiredTigerCacheSizeGB`, host swap) into `infra/gce/docker-compose.yml` and
  the startup script, with a contract test, then compare the rendered Compose
  against the live overlays before the next deploy.
- failed path: After the 2026-10-08 freeze, the limits, cache cap and swap
  existed only as overlays under `/var/lib/zeler-platform/` on the VM. A deploy
  from the base Compose would silently drop them and restore the unbounded state.
- verification/source: `tests/test_gce_compose_contract.py` (limits, cache flag,
  sandboxed idempotent swap step), `docs/deploy.md` §5a.1.
- status: active

### L-019 — Bound optional quality retries and overlapping item jobs
- area: ZelerData acquisition and recovery
- proven path: Persist a quality-only retry time bound to the item's source
  version, keep absent quality visibly unavailable, and complete the item chunk.
  Before admitting more work, subtract IDs already covered by active jobs for
  the same seller. Reconcile legacy overlaps from a drained worker with a
  fingerprinted dry run and preserved job records.
- failed path: Retry a full item chunk for every optional performance 404, or
  key large recovery sweeps only by the exact changing ID list. Both multiply
  source calls and queue work without adding source evidence.
- verification/source: `openspec/changes/zelerdata-quality-load-control/`,
  `modules/sheets/tests/test_formula_recovery.py`, and
  `docs/ops/zelerdata-quality-load-control.md`.
- status: active

### L-020 — Keep optional buybox offers 404 and overlapping catalog jobs from multiplying work
- area: ZelerData buybox acquisition and recovery
- proven path: Preserve the verified price-to-win observation when the offers
  listing returns 404, leave unknown competition fields unavailable, and
  complete the chunk. Subtract IDs already covered by active buybox jobs and
  reconcile legacy overlaps from a drained worker using a fingerprinted preview.
- failed path: Treat each optional offers 404 as a failed catalog chunk while
  admitting changing, overlapping ID lists. On 26 September, nine active
  buybox jobs contained 8,368 IDs but only 937 distinct IDs, with hundreds of
  failed chunks and sustained offers 404 traffic.
- verification/source: `openspec/changes/zelerdata-buybox-load-control/`,
  `modules/sheets/tests/test_formula_recovery.py`, and
  `docs/ops/zelerdata-buybox-load-control.md`. The 26 September pilot rollout
  consolidated eight active jobs into one; at 90 minutes it had reached 760/937
  IDs with three incomplete chunks, stable service health and memory, and 39
  offers 404 calls across 38 routes in the last five minutes. Review the
  incomplete chunks and the settled call rate after the backlog finishes.
- status: active

### L-021 — Do not repeatedly schedule full-seller sweeps faster than they finish
- area: ZelerData scheduled refresh and recovery
- proven path: Keep bounded order/question ranges on the scheduled loop and
  require explicit opt-in for periodic whole-seller inventory, catalog and
  shipment sweeps. Formula-triggered recovery continues through the queue.
- failed path: Coalesce only active IDs while a 15-minute planner reopens
  terminal jobs whose full-seller passes take much longer. A superseded 934-ID
  buybox job reopened after the consolidated 937-ID job finished, and the
  inventory sweep restarted after its cooldown, sustaining source traffic.
- verification/source: `openspec/changes/zelerdata-periodic-sweep-control/`,
  the refresh factory tests, and the 27 September pilot worker rollout. The
  settled post-backlog call rate remains to be measured.
- status: active

### L-022 — Suppress legacy order history only with completed interval proof
- area: ZelerData pilot history backfill
- proven path: Before admitting a legacy monthly order request, require the
  exact completed plan-bound history job and a reconciled marker covering that
  interval. Drain the worker and reconcile already admitted duplicates against
  the same proof; keep their terminal records.
- failed path: Queue dedup compares request keys, so it cannot recognize a
  completed protocol job under a different legacy key. After a worker restart,
  four already-proven order months were admitted again and sustained hundreds
  of order-detail gateway calls.
- verification/source: `modules/sheets/tests/test_pilot_history_cutoff_lifecycle.py`
  and `openspec/changes/zelerdata-periodic-sweep-control/verify-report.md`.
- status: active

### L-023 — Revalidate locally stored questions omitted by a complete scan
- area: ZelerData question read-model recovery
- proven path: After a complete question scan, fetch any locally stored
  identity absent from it by detail. Keep a valid 200 response; remove only a
  scoped 404 in the same transaction as refreshed rows, coverage and job
  completion. Also resolve an identity enumerated by discovery whose detail is
  now 404; do not let that stale listing abort every complete scan. Other
  responses leave the previous row and proof intact.
- failed path: Compare the new scan with persisted rows without resolving an
  absent old identity. One stored question no longer appeared in the pilot's
  complete scan and returned 404 by detail; two one-hour jobs each fetched
  the same 229 visible question details, then failed `source_incomplete`.
- verification/source: `modules/sheets/tests/test_formula_recovery.py` and
  `openspec/changes/zelerdata-periodic-sweep-control/verify-report.md`.
- status: active

### L-024 — Verify the claims DLQ and binding, not just the source queue
- area: ZelerData claim notifications and broker health
- proven path: Declare the durable `zeler.sheets.claims.dlq` queue and its
  `zeler.sheets.claims.dlx` binding before either worker consumer starts. A
  failed binding must stop startup; API health probes the DLQ itself. Restore a
  missing queue and binding before rolling out the corrected health check.
- failed path: Treat one healthy consumer and an empty source queue as proof of
  safe dead-lettering. The pilot's source queue pointed to an existing direct
  exchange with no bindings and no destination queue, so rejected claims were
  unroutable while the old API health check reported zero DLQ messages.
- verification/source: Sanitized broker topology inspection and bounded repair
  on 28 September 2026; `modules/sheets/tests/test_health_router.py`,
  `modules/sheets/tests/test_sheets_amqp_consumer_runner.py`, and
  `infra/rabbitmq/sheets_devoluciones_topology.py`.
- status: active

### L-025 — Compare economic tags as membership in formula readers
- area: ZelerData listing fixed-fee projections
- proven path: Use the same `canonical_basis_tags` comparison in acquisition
  and formula readers. Keep malformed tags and genuine price, logistics or tag
  changes unavailable.
- failed path: Compare the order of the `tags` lists in a stored projection and
  current item row. A read-only pilot sample of 100 recent order lines had the
  same tag membership in each pair, but the old order-sensitive reader returned
  `NA` for every fixed fee.
- verification/source: `modules/sheets/tests/test_formula_handlers_core.py`,
  `modules/sheets/tests/test_formula_handlers_orders_questions.py`, and the
  canonical helper in `modules/sheets/src/zeler_sheets/enrichment.py`.
- status: active

## ZelerData

### L-026 — Keep transient refresh failures eligible for retry
- area: Gateway OAuth and ZelerData recovery
- proven path: Keep HTTP 429/5xx and transport refresh failures eligible for the
  next normal refresh pass. Retry historical errors only with exact recognized
  transient diagnostics; recheck eligibility when acquiring the lock. Preserve
  paused/revoked accounts and non-transient failures.
- failed path: Set every refresh failure to `error` while selecting only
  `active`/`refresh_pending` accounts. A 429 then permanently excludes the
  account and produces proxy 412 despite green service health.
- verification/source: `gateway/tests/test_refresh_worker.py` — 37 passing tests,
  including isolated Mongo validators. Gateway deployed 2 October 2026, 15:16 UTC;
  normal refresh restored the pilot to active. Remaining runtime acceptance:
  `docs/ops/platform-vm-recovery-20261002.md`.
- status: active

### L-027 — Verify delivery progress, not just consumer readiness
- area: ZelerData AMQP exception handling and recovery
- proven path: Require ACK/NACK or confirmed bounded retry for every HTTP error;
  preserve the original if retry publication fails. Verify the delay queue,
  binding and effective TTL before rollout, then measure backlog and completions.
  Compare required queue semantics, allowing broker-added defaults such as
  `x-queue-type=classic`; a benign extra argument does not justify another PUT.
- failed path: Re-raise HTTP 412 inside its `except` block: sibling safety-net
  handlers do not catch it. Ten unacked deliveries filled prefetch while the
  connection stayed ready, even after OAuth recovered.
- verification/source: `modules/sheets/tests/test_consumer_error_handling.py` —
  10 RED then 32 GREEN; 56 GREEN with adjacent consumer tests. Scoped delay
  topology and corrected worker deployed on 2 October 2026. Runtime evidence:
  `docs/ops/platform-vm-recovery-20261002.md`.
- status: active

### L-028 — Preserve independent coverage when acquiring another interval
- area: ZelerData DEVOLUCIONES readiness and period acquisition
- proven path: Check the actual reader and current proof before publishing a new
  interval. Preserve previously certified periods and their provenance; reject
  queries across unacquired gaps. Stop a replacement that would remove valid
  coverage and implement the cumulative contract before resuming acquisition.
- failed path: Treat retained rows or completed runs as sufficient evidence that
  both periods remain readable. The former single DEVOLUCIONES marker would
  have made publishing August invalidate June availability even though June's
  data and run survived.
- verification/source: The reader check and bounded dry-run are recorded in
  `docs/ops/platform-vm-recovery-20261002.md`. Cumulative multi-period behavior
  was implemented in `17c30f4`; the subsequent
  [rollout report](../ops/devoluciones-multiperiod-rollout-20261002.md) records
  June migration/activation and two verified renewals, not August acquisition.
  A renewed historical proof does not certify any missing interval between two
  acquired periods.
- status: active

### L-011 — Deliver stop signals to the worker and await Docker completion
- area: VM deployment and worker lifecycle
- proven path: Run the Sheets Python module directly as PID 1; give the deployment wrapper more time than Docker's stop grace, and verify stable running/healthy state after Compose completes.
- failed path: Shell CMD without `exec` plus equal outer/Compose deadlines caused a late SIGKILL after an apparent healthy rollback.
- verification/source: `tests/test_module_dockerfiles.py::test_worker_dockerfile_cmd_matches_contract[sheets]`, worker lifecycle tests, and the runtime evidence in `docs/zelerdata-goal-progress.md`: Python PID 1, clean stop in 1.777 seconds with exit 0, then stable healthy restart.
- status: active

### L-007 — Preserve acquisition prerequisites for full reconciliation
- area: ZelerData
- proven path: For full enrichment reconciliation, complete `items-enrich --enable-sale-price --enable-listing-fixed-fee`, then run `items --write`. Layered base recovery instead acquires current item details and projects them with field-specific enrichment availability preserved; see L-013.
- failed path: Write items before enrichment; formula projections can remain stale.
- verification/source: validated reconciliation sequence and Sheets item enrichment paths.
- status: active

### L-010 — Keep recovery discovery and detail identities distinct
- area: ZelerData gateway recovery
- proven path: Use the Sheets detail client for `/products/*`; bootstrap is the discovery client. Test both as separate clients with their real permission boundary.
- failed path: Share one permissive fake for both clients; catalog tests passed while production bootstrap requests received 403 despite Sheets having the required scope.
- verification/source: `modules/sheets/tests/test_formula_recovery.py::test_catalog_product_worker_persists_available_resources_without_global_coverage`, `infra/mongo/seeds/module_registry.admin_clients.json`, and the read-only two-identity VM probe recorded in `docs/zelerdata-goal-progress.md`.
- status: active

## Local integration tests

### L-012 — Give the isolated test Mongo enough file descriptors
- area: Local Mongo integration tests
- proven path: Use a dedicated loopback Mongo replica set on port 27028 with
  `--ulimit nofile=65536:65536`; verify PRIMARY before tests. Use disposable data,
  not existing development or production volumes. Point `MONGO_URI` at that
  instance with an explicitly named disposable database for the normal suite;
  fixtures using `get_default_database()` cannot use a URI without a database.
  For the protected stock-time rs0 tests, unset
  `MONGO_URI` and set the loopback `ZELER_RS0_TEST_URI` instead.
- failed path: Rely on Docker's default descriptor limit; WiredTiger can abort
  with error 24 during the suite, making later integration tests skip. A prior
  successful ping does not prove the database stayed available throughout tests.
- verification/source: `docs/zelerdata-goal-progress.md` records the earlier
  descriptor exhaustion and protected test workflow;
  `tests/integration/test_stock_time_forward_*_rs0.py` enforces the isolated target.
  `tests/test_phase3_validator_contract.py` requires a default database;
  `openspec/changes/zelerdata-pilot-reliable-sync/apply-progress.md` records the
  full-suite rerun with a named disposable database.
- status: active

## Python safety

### L-008 — Do not suppress an exception around a required return
- area: Python
- proven path: Catch an expected, specific exception such as `ProcessLookupError`
  and return when that probe failure is expected.
- failed path: Use `contextlib.suppress(ProcessLookupError): probe(); return`;
  the return is skipped when `probe()` raises, so it is not equivalent to
  `except ProcessLookupError: return`.
- verification/source: Python control-flow semantics; add a focused regression test
  when this pattern is changed in executable code.
- status: active

## Delivery policy

### L-009 — Deliver when evidence is good enough
- area: Delivery
- proven path: Deliver when the objective, proportional evidence, and critical
  risks are covered. Record marginal polish as a follow-up.
- failed path: Delay safe delivery for low-value polish, or relax safety, data,
  integrity, or reversibility controls to finish faster.
- verification/source: review the objective, evidence, and unresolved critical risks.
- status: active

## Maintenance rules

- Do not store secrets, PII, raw production values, authorization material, or logs.
- Do not duplicate runbooks. Promote detailed operational procedures and retain a
  concise reference here.
- Promote stable lessons, then archive or replace their duplicated detail.
- Review active entries periodically and after relevant incidents or migrations.
- Retire or refute obsolete lessons explicitly; preserve the reason and source.
- Keep this document below 400 lines.


### L-013 — Separate quota waits and renew genuinely reacquired base observations
- area: ZelerData acquisition/recovery
- proven path: Start provider timeouts after quota admission; keep explicit local
  quota evidence across nested deadlines and joined siblings. Reacquiring an
  unchanged owned item renews its base observation through the guarded writer,
  while enrichment keeps its own acquisition cut and dependency basis.
  Test competitors that remain active across persistence gaps for the entire
  inventory sweep; spread lane admissions over the shared budget window so
  returning batches can compete before other lanes consume the whole minute.
- failed path: Include quota waiting in a short HTTP deadline, lose its cause at
  the outer TaskGroup deadline, or skip an unchanged base write because only its
  acquisition timestamp changed. These paths produce false source failures or
  perpetually stale inventory despite successful acquisition.
  A finite competitor workload can also hide fixed-window bursts that starve
  an inventory producer while it writes its preceding batch.
- verification/source: `modules/sheets/tests/test_formula_recovery_http_deadlines.py`,
  `modules/sheets/tests/test_formula_layered_pacing.py`,
  `modules/sheets/tests/test_layered_basic_acquisition.py`, and
  `docs/sheets/zelerdata-layered-recovery-20260914.md`.
- status: active

### L-014 — Test broker probe ownership at the transport boundary
- area: Broker health, gateway readiness, aio_pika/aiormq
- proven path: Check the installed connection interface (`is_closed` and
  `connected`), retain an owned connection during reconnect, and retain its
  transport before handshake completion. Bound both probe work and cleanup;
  start cached-result TTL after completion. Verify timeout and cancellation with
  a real loopback TCP peer that accepts but never completes the AMQP handshake.
- failed path: Test doubles with `is_open` hid gateway reconnection on every
  readiness probe. Creating a robust connection per ephemeral probe could orphan
  reconnect work; closing only the outer connection did not close a socket that
  aiormq had opened but not yet attached during handshake.
- verification/source: `tests/test_broker_probe_ownership.py`,
  `gateway/tests/test_rabbit_readiness_ownership.py`, and
  `gateway/tests/test_rabbit_readiness_transport.py`; implementation and TDD
  evidence in `openspec/changes/zelerdata-live-formula-repairs/`
  `apply-progress-broker-probes.md` and `apply-progress-gateway-ownership.md`.
- status: promoted/reference

### L-029 — Verify pause proof on the actual host interpreter
- area: VM pause and recovery, Docker RFC3339Nano
- proven path: Parse aware Docker timestamps as exact integer nanoseconds and
  test the installed host Python, not only the application interpreter. Accept
  API shell exit143 only with ordered shutdown/finished-PID evidence from the
  same captured container generation; recover marked writers on any rejection.
- failed path: Python3.11 rehearsal masked Python3.10 rejection of eight/nine
  fractional digits. Truncating to microseconds can instead accept a sentinel
  one nanosecond older than its generation. Either is unsafe pause evidence.
- verification/source: `infra/operations/zelerdata_history_pause.py`,
  `tests/test_zelerdata_history_pause.py`, and the sole failed/recovered C cut in
  `docs/sheets/zelerdata-historico-builds-runtime-20261003.md`. A local parser fix
  does not authorize repeating a bounded production cut.
- status: active

### L-030 — Pace at dispatch after persisted budget admission
- area: ZelerData historical acquisition and shared request pacing
- proven path: Charge the persisted policy first, pace immediately before RPC,
  and recheck the charged UTC window without an intervening database await.
  Keep the authenticated gateway's late persisted authority check. A reservation
  that expires while pacing remains consumed but must produce zero HTTP calls.
- failed path: Pace before Mongo admission; concurrent workers can complete
  database waits together and cluster actual RPC starts despite paced grants.
  Do not reset counters or relax spacing assertions to hide this ordering bug.
- verification/source: `modules/sheets/tests/test_history_execution_controls.py`,
  `modules/sheets/tests/test_devoluciones_onboarding.py`, and the strict shared
  coordinator scenario in `modules/sheets/tests/test_history_onboarding_shared_capacity.py`.
- status: active

### L-031 — Check the actual operator UID and CLI ABI before isolated restore
- area: Isolated Mongo restore, COS persistent mounts, Docker operator image
- proven path: Exercise the official entrypoint's effective UID and temporary
  bind permissions, then run the chosen CLI inside the actual operator image.
  Client/daemon API negotiation does not prove libc compatibility. Require a fresh
  owned data directory and PRIMARY before listing databases; code 94 is an
  uninitialized replica set, not proof that the restore database is empty.
- failed path: A root-owned 0700 tmp bind blocks Mongo UID999 before mongod starts;
  a COS CLI can negotiate the daemon API on its host but fail DT_RELR inside an
  older operator image. Neither failure demonstrates inconsistent candidates.
- verification/source: Synthetic UID/command fixtures and actual target-only CLI
  probes; sanitized receipts in
  [candidate rescue report](../sheets/zelerdata-historico-rescate-candidatos-propuesta.md).
  Preserve noexec on the host and use only the private executable container path.
- status: active


### L-032 — Bind work credit to durable purpose and late ownership
- area: ZelerData pilot event/replay maintenance
- proven path: Resolve source from the stored webhook's topic, normalized resource
  and seller; preserve the publisher's actual idempotency key. Bind each prepaid
  attempt to its work nonce. At gateway, transactionally touch live claim/job
  ownership and reserve that nonce without renewing leases or resetting counters.
  Revalidate the physical once interface after unwrapping pacing; defer WAIT with
  confirmed publish before ACK and fenced job backoff.
- failed path: Guess source from `/orders` or a free header; merge work credits
  into fungible historical h1; read ownership without a conditional write in the
  send transaction; fall back to a retrying client hidden by a pacing facade;
  convert local policy WAIT to DLQ or terminal job failure.
- verification/source: `core/tests/test_history_work_intent.py`,
  `tests/integration/test_history_work_send_rs0.py`,
  `modules/sheets/tests/test_history_work_intent.py` and
  `gateway/tests/test_pilot_get_budget_consumers.py`. Local CAS/provider doubles
  do not prove AMQP delivery, Sheets readback or production acceptance.
- status: active


### L-033 — Abort bounded pilot 429 before collector retries
- area: ZelerData bounded historical acquisition
- proven path: Bind the response to the dispatch's validated persisted EID; CAS
  only that execution to paused, retaining charges. A typed abort must cross
  RETURNS' no-retry branch, then become policy WAIT before failure classification.
  Keep remote upstream1, local0 and unknown metadata distinct; ordinary unchanged.
- failed path: Rely only on an outer polling monitor or raise ordinary WAIT inside
  a collector that wraps/retries it. Two scan passes or refreshed timestamps do
  not prove two genuinely changed incremental cycles.
- verification/source: `modules/sheets/tests/test_history_pilot_rate_limit_stop.py`,
  `modules/sheets/tests/test_history_pilot_returns_rate_limit_stop.py`; Mon5 ledger.
- status: active


### L-034 — Commit one shipment and its cursor atomically
- area: ZelerData shipment acquisition/recovery
- proven path: Keep immutable request IDs/key, verify live ownership and strict
  cursor before RPC, then commit each validated resource/readback/cursor together
  with snapshot/majority. Resume only concluded units; archive a completed cursor
  before a legitimate new refresh. Preserve partial cost/cache provenance.
- failed path: Buffer100×3 requests before one commit under a250 request cap,
  seed progress from consumed calls, or reopen a completed cursorlen without a
  new cycle. API/worker changes need compatible ordering and rollback.
- verification/source: `modules/sheets/tests/test_shipment_recovery_durable_cursor.py`,
  `tests/integration/test_shipment_cursor_publication_rs0.py`; future runtime
  validator inspection remains required, not proven by a matching no-op.
- status: active

### L-035 — Bound every cancellation-test signal wait
- area: Async test harness/worker deadline classification
- proven path: Bound the harness event wait and separate manually triggered
  cancellation from an unrelated short outer timer, preserving source/quota
  outcome assertions. Inspect live owned PIDs after a Docker exec caller timeout.
- failed path: Await a signal forever after its worker can already terminate;
  confuse caller termination with child termination, or drop the test to pass.
- verification/source: `modules/sheets/tests/test_formula_recovery_http_deadlines.py`.
- status: active

### L-036 — A paused pilot must release ordinary traffic
- area: ZelerData event consumer / broker quota
- proven path: When history on link is off, ordinary events ignore persisted
  pilot plans and use the ordinary gateway client. A policy WAIT backs off from
  5 s to 10 min after 12 waits. Remove the gateway pilot GET-budget seller list
  when the pilot closes.
- failed path: Pause a pilot but keep its plan, worker routing and gateway guard
  live: 93 ordinary webhooks waited every 5 s forever (~58k requeues/hour),
  exhausted CloudAMQP's monthly quota in 7 days and blocked every product on
  2026-10-07. Also, a worker reporting `rabbitmq: ok` had no AMQP connection.
- verification/source: `modules/sheets/tests/test_history_off_ordinary_events.py`;
  broker refusal read from `Connection.Close` reply code 530 NOT_ALLOWED.
- status: active

### L-037 — Size item and catalog sweeps to their readers' age limits
- area: ZelerData scheduled refresh
- proven path: Item and catalog formulas have no marker; they check each
  acquisition's age (15 minutes, catalog products 4 hours). Space each sweep
  from its own previous pass, never while one is in flight, and keep the base
  inventory off while a buybox job is in progress.
- failed path: A daily sweep keeps them `OK` only for minutes. An inventory pass
  during buybox invalidates its snapshots (`synced <= observed`) and fails its
  unchanged-item check (likely September `source_incomplete`).
- verification/source: `modules/sheets/tests/test_zelerdata_refresh.py`,
  `modules/sheets/tests/test_zelerdata_sweep_status.py`,
  `docs/sheets/zelerdata-refresh.md`. Not yet observed in production.
- status: active

### L-038 — A paused pilot must not freeze certified DEVOLUCIONES coverage
- area: ZelerData DEVOLUCIONES coverage
- proven path: With history on link off, skip onboarding runs and admit one
  ordinary tail run per UTC day (`refresh-tail:v1`) from the latest certificate
  to the settled UTC midnight, capped at 10 days. Finalize its last window in
  the same invocation. Leave pilot plans untouched.
- failed path: Treat certificate renewal as freshness: it keeps old intervals
  valid but never adds days, so coverage froze at the last pilot acquisition
  while the paused plan refused every onboarding run. Leaving finalization to
  the next cycle also fails: a one-window run expires 1070 s after admission,
  and the next cycle runs at least 900 s later.
- verification/source: `modules/sheets/tests/test_devoluciones_ordinary_tail.py`,
  `tests/integration/test_devoluciones_onboarding.py`,
  `docs/sheets/zelerdata-refresh.md`. Not yet observed in production.
- status: active

### L-039 — Widening the seller scope must not widen pilots
- area: ZelerData seller scope (`all` mode)
- proven path: Before widening `ZELERDATA_REFRESH_SELLERS` or
  `ZELERDATA_FORMULA_RECOVERY_SELLERS`, find every consumer of that allowlist.
  Pilot-only work stays bound to named sellers and fails at startup otherwise.
  Eligibility is an active or `refresh_pending` account plus an active
  extension token for that seller, re-read every cycle.
- failed path: The refresh supervisor always wired the legacy 12-month backfill,
  which seeds a plan and 12 months of orders and questions for every seller the
  explorer returns. Reusing the allowlist for `all` would have opened history
  for everyone.
- verification/source: `modules/sheets/tests/test_zelerdata_all_sellers.py`,
  `docs/sheets/zelerdata-refresh.md` ("All eligible sellers"). Not yet
  observed in production.
- status: active

### L-040 — Retire pre-v2 return rows the tail inventory omits
- area: ZelerData DEVOLUCIONES coverage
- proven path: After source revalidation, the tail window archives the exact
  BSON of each non-canonical `returns` row in range that its inventory omits,
  then removes that row in the same fenced transaction. Keep canonical rows the
  source omits, and operator runs, failing closed.
- failed path: Narrowing only the final readback to complete v2 rows: certificate
  publication and every certified read run `verify_devoluciones_read_model`,
  which rejects that row, so finalization raised and the run stayed `active`.
  An unchanged readback failed the tail once a day and froze coverage at 06-11.
- verification/source: `tests/integration/test_devoluciones_onboarding.py`
  (tail quarantine, canonical fail-closed, pilot unchanged),
  `docs/sheets/zelerdata-refresh.md`. Not yet observed in production.
- status: active

### L-041 — Bound whole-inventory reads and do not tie snapshots to the re-sync cut
- area: ZelerData worker memory and buybox freshness
- proven path: Read canonical item documents for a whole inventory in small
  identity chunks and keep only evidence and fingerprints. Judge a buybox
  snapshot by its own age and the fields it carries, never by whether the item
  was re-read after it.
- failed path: `to_list` over every item document peaked near 312 MB for 1.9k
  publications (7 MB kept); the worker's allocator never gave it back, so each
  pass grew the process until the VM froze. The sweep rewrites every
  `last_meli_sync_at`, so `synced <= observed` discarded 934 of 940 snapshots.
- verification/source: `modules/sheets/tests/test_formula_read_memory_bounds.py`,
  `modules/sheets/tests/test_formula_buybox_item_resync.py`,
  `docs/sheets/zelerdata-formulas.md`. Not yet observed in production.

### L-043 — Re-check eligibility at claim and cap serial warming in `all` mode
- area: ZelerData seller scope (`all` mode) / refresh cycle
- proven path: In `all` mode `FormulaRecoveryQueue.claim` closes a job whose
  seller stopped being eligible (`failed`, `seller_not_eligible`) and claims the
  next one, so no request is made for it. The refresh cycle gives the serial
  precalculated warmer half an interval per cycle and resumes from the first
  deferred seller. A cycle plus its rest must stay under the 30-minute marker
  lease. Run `infra/operations/zelerdata_all_sellers_dry_run.py` before
  switching the scope.
- failed path: Relying on the gateway to reject queued work of a paused seller
  (it still cost a claim, an attempt and a request per job), and warming every
  seller inline: about 7 pilot-sized sellers push the cycle past one interval
  and expire every seller's markers.
- verification/source: `modules/sheets/tests/test_formula_recovery.py`
  (`all_mode_claim`, `all_mode_worker`),
  `modules/sheets/tests/test_zelerdata_all_sellers.py` (`warm_budget`),
  `tests/operations/test_zelerdata_all_sellers_dry_run.py`,
  `docs/sheets/zelerdata-refresh.md` ("Scale analysis"). Capacity figures come
  from code, not production.
- status: active

### L-044 — Size reader age limits to on-demand acquisition and compare only stored fields
- area: ZelerData buybox, quality and cost readers
- proven path: Serve an on-demand acquisition (buybox, quality, costs) for as
  long as one pass over the whole inventory can keep it (24 hours), guarded by
  its basis fields and reported age; recover only absent, older or mismatched
  ones. A base-change check compares only fields the canonical item stores.
- failed path: A 15-minute limit on data that only formula recovery acquires,
  in passes that take hours, left buybox 934/935, quality 1,896/1,896 and costs
  on almost every row unavailable while each read re-requested a full pass. The
  quality basis compared `pictures`, which `Item` never stores, so every base
  re-sync invalidated every quality projection.
- verification/source: `test_formula_buybox_item_resync.py`,
  `test_layered_basic_acquisition.py`,
  `test_formula_handlers_quality_calculator.py`,
  `docs/sheets/zelerdata-formulas.md`. Not yet observed in production.
- status: active

### L-045 — Serve a source-declared absence as NA instead of recovering it
- area: ZelerData buybox and quality readers
- proven path: When Mercado Libre answers that a datum does not exist for a
  publication (`not_listed` competition, quality not generated or HTTP 400),
  the reader serves `NA` while that answer is fresh and does not request
  recovery; only absent, expired or failed acquisitions stay
  `DATA_UNAVAILABLE` and recoverable. Decide it in the reader from the stored
  status and its observation time, without changing writers.
- failed path: Treating every non-value as `DATA_UNAVAILABLE`: 657 `not_listed`
  buybox rows and about 1,440 quality rows were re-requested on every read,
  re-acquired and stored with the same answer, and never filled.
  The same absence shows in every column the snapshot lacks: after the
  `only_competitor` flag was served as `NA`, `CATALOGO` still reported 779
  unrecoverable rows because the winning-user column of the same `not_listed`
  snapshots (no `winning_user_id`) stayed `DATA_UNAVAILABLE`. Check each column
  that feeds `recoverable`, not only the one that exposed the loop.
- verification/source: `test_formula_handlers_item_shipping_catalog.py`,
  `test_formula_handlers_remaining_phase4.py`,
  `test_formula_handlers_quality_calculator.py`,
  `docs/sheets/zelerdata-formulas.md`. Not yet observed in production.
- status: active

### L-046 — Keep deploy scripts bash 3.2-safe and sandbox GNU-only calls on macOS
- area: Shell scripts / local tests on macOS
- proven path: Expand a possibly empty array as
  `${arr[@]+"${arr[@]}"}` under `set -u` (macOS bash 3.2 aborts on
  `"${arr[@]}"`; the VM's bash 5 does not). Apply it to every copy:
  `platform-vm-startup.sh` embeds `docker-deploy-preflight.sh` and a test
  requires the copies to be identical. A wrapper test that must run the
  production file on a host without GNU `stat -c`, `sha256sum` or fractional
  `read -t` swaps those calls only in its sandbox copy, and only when the host
  lacks them, so the VM and Linux run the exact production lines.
- failed path: Assuming every macOS failure of a deploy script is the empty
  array: the DLQ snapshot wrapper never had one; it failed on `read -t 0.01`,
  `stat -c` and `sha256sum`. Relaxing `set -u` or rewriting the production
  wrapper's absolute-path commands to make a laptop pass.
- verification/source: `tests/test_deployment_preflight.py`,
  `tests/operations/test_sheets_dlq_snapshot_execute.py`
  (`_host_portability_substitutions`, `_interpreter_injected_names`).
- status: active

### L-047 — Compute interval metrics from observations at read time, not from import markers
- area: ZelerData time formulas (`CATALOGOTIEMPO`, `CATALOGO` winning percent)
- proven path: Sum time per publication from the acquired observations when the
  formula is read: the state at the range start is the last observation at or
  before it (a full reverse index walk with `$first`, served as `DISTINCT_SCAN`),
  and the range is summed by the server with `$setWindowFields`/`$shift` on the
  existing `(seller_id, item_id, observed_at)` index, with no blocking sort.
  About 0.4 s for 270k observations locally. A publication with no observation
  at or before the start reports where its history begins instead of a sum.
- failed path: Requiring the `legacy_imported` marker and a derived metrics
  collection kept these formulas `DATA_UNAVAILABLE` although 260k observations
  existed; the importer's sources do not exist in production.
- verification/source: `modules/sheets/tests/test_catalog_winning_time.py`,
  `docs/sheets/zelerdata-time-metrics-plan.md` ("Avance 2026-10-09"). Not yet
  observed in production.
- status: active

### L-048 — Gate a change-only history on its observation heartbeat
- area: ZelerData availability history (`TIEMPOSTOCKACTIVO`, `SEMANASCONSTOCK`)
- proven path: Accumulate forward a log that writes a row only when a series'
  state changes, keyed by Mercado Libre identity (publication or variation),
  and compute the metrics at read time. Prove freshness with the observation
  heartbeat (`item_status_states` observed-only marker), and show
  `Sin histórico antes de <fecha hora>` for time before a series' first row.
- failed path: Gating on the log's own newest row: a change-only log is silent
  while nothing changes, so a healthy pipeline would look stale. Filling
  uncovered time with the current state presents it as history (rejected
  2026-09-24). Reading at request time instead of from import markers is L-047.
- verification/source: `modules/sheets/tests/test_availability_history_writer.py`
  (real Mongo, strict validator), `test_formula_availability_history.py`,
  `test_availability_metrics.py`, `docs/sheets/zelerdata-formulas.md`
  ("Availability history"). Not yet observed in production.
- status: active

### L-049 — Archive a DLQ message on a per-resource read stamp, not on a window marker
- area: Sheets DLQ archive
- proven path: The event envelope carries no data and the worker always
  re-reads the resource, so a message is safe to archive once the platform's
  own read stamp for that resource is at least 15 minutes after `occurred_at`:
  `items.last_meli_sync_at`, `shipments.formula_observed_at`,
  `orders.items[].sale_fee_synced_at` or the newest competition observation,
  one identity or indexed `find_one` per message. Plan with
  `sheets_dlq_archive_runtime --dry-run`, which requeues everything LIFO and
  prints counts only.
- failed path: Mapping `items` to a read model that does not exist left the
  window rule inert for publications, and the `orders` marker made it unsound:
  its top-level window is only the latest acquisition (one hour for the fast
  sweep), and a formula-triggered window ends at the next UTC midnight, so
  `reconciled_until >= occurred_at` archived updates to orders that window
  never read. The `item_formula_rows` and `catalog_buybox_snapshots` markers
  are legacy claims nothing renews.
- verification/source: `tests/operations/test_sheets_dlq_archive.py`,
  `tests/operations/test_sheets_dlq_archive_runtime.py` (real-Mongo lookup and
  index plan), `docs/ops/sheets-dlq-reconciliation.md`. Not yet run in
  production.
- status: active
