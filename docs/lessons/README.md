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

## ZelerData

### L-011 — Deliver stop signals to the worker and await Docker completion
- area: VM deployment and worker lifecycle
- proven path: Run the Sheets Python module directly as PID 1; give the deployment wrapper more time than Docker's stop grace, and verify stable running/healthy state after Compose completes.
- failed path: Shell CMD without `exec` plus equal outer/Compose deadlines caused a late SIGKILL after an apparent healthy rollback.
- verification/source: `tests/test_module_dockerfiles.py::test_worker_dockerfile_cmd_matches_contract[sheets]`, worker lifecycle tests, and the runtime evidence in `docs/zelerdata-goal-progress.md`: Python PID 1, clean stop in 1.777 seconds with exit 0, then stable healthy restart.
- status: active

### L-007 — Enrich before writing items
- area: ZelerData
- proven path: Complete reconciliation with `items-enrich --enable-sale-price --enable-listing-fixed-fee`, then run `items --write`.
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
  instance for the normal suite. For the protected stock-time rs0 tests, unset
  `MONGO_URI` and set the loopback `ZELER_RS0_TEST_URI` instead.
- failed path: Rely on Docker's default descriptor limit; WiredTiger can abort
  with error 24 during the suite, making later integration tests skip. A prior
  successful ping does not prove the database stayed available throughout tests.
- verification/source: `docs/zelerdata-goal-progress.md` records the earlier
  descriptor exhaustion and protected test workflow;
  `tests/integration/test_stock_time_forward_*_rs0.py` enforces the isolated target.
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
