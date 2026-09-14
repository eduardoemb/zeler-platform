# Apply progress: layered recovery pacing

Task 6.2, strict TDD, implemented September 14, 2026. This bounded,
uncommitted unit supplements existing apply-progress artifacts; it does not
replace earlier completion evidence. The parent owns the shared task checklist
and integration with worker deadlines and gateway call sites.

## Behavior and interface

- `RecoveryRequestPacer.acquire(lane=None)` shares the configured budget across
  inventory, explicit IDs and ranges with work-conserving weights 1:2:1.
  Legacy callers use the IDs lane. Default budget remains 180/minute.
- The quota timer exists only while requests are pending. Cancellation removes
  waiters; the last departing waiter cancels and joins the timer. Invalid lanes
  fail before consuming budget. Idle windows reset their full budget correctly.
- `PacedMeliGateway(..., lane=None)` paces `request`, `fetch_resource` and
  `fetch_resource_once`. Lane-aware calls default to ten seconds of HTTP time;
  the optional `request_timeout` is consumed internally after quota admission.
  Legacy calls without a lane retain their previous default timeout behavior.
- `recovery_fetch_resource(gateway, request_timeout=5, **kwargs)` applies the
  same HTTP-only deadline to paced gateways and bounds ordinary gateway calls.
- `with recovery_quota_deadline(loop.time() + seconds)` limits only local quota
  waits; expiry raises `LocalQuotaTimeoutError`, separately from source timeout,
  and restores the context at job exit. Worker integration owns durable deferral.

## TDD cycle evidence

| Task | Safety net | RED | GREEN | Triangulation / refactor |
| --- | --- | --- | --- | --- |
| 6.2 fair lanes, lifecycle and deadlines | Existing pacing file: 10 passed | New layered tests: 10 failed on missing interfaces | Combined files: 20 passed | Real 5.05-second quota wait precedes successful five-second HTTP budget; three entrypoints, actual HTTP timeout with/without wrapper, cancellation with/without survivors |
| 6.2 partial-window rollover | Combined: 20 passed | Idle rollover regression failed, invalid-lane companion passed | Combined: 22 passed | Fixed legacy over-admission after an idle partially used window; Ruff format followed by same 22 passing tests |

## Work unit evidence

| Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest modules/sheets/tests/test_formula_layered_pacing.py modules/sheets/tests/test_zelerdata_recovery_pacing.py -q`: exit 0, 22 passed |
| Static checks | `uv run ruff check` on the two files: exit 0; `uv run mypy modules/sheets/src/zeler_sheets/formulas/pacing.py`: exit 0, one source file |
| Runtime harness | Real asyncio scheduler with three competing producers, shared four-request accelerated windows, cancellation, zero remaining scheduler tasks, five-second quota wait, bounded real async provider calls: covered in the focused command. Production/Mongo not accessed by this unit. |
| Rollback boundary | `formulas/pacing.py` and new `test_formula_layered_pacing.py`; parent must roll back dependent lane/deadline integration together. No schema, persisted queue state or production mutation. |

Worker/API integration, 1,900-item mixed workload, full repository gates,
independent SDD verification and live acceptance remain with the parent.

## Caller integration follow-up

Replaced the five worker HTTP timeout blocks (product detail, buybox competition,
offers, winning item, order-shipment relation) with deadline-aware helpers.
`recovery_request` mirrors `recovery_fetch_resource` for response-returning calls.
The catalog batch exception classifier already propagates local quota expiry;
its sibling-joining and worker deferral behavior now have regression coverage.

| Evidence | Result |
| --- | --- |
| Safety net | Existing catalog-product/buybox subset: 11 passed |
| RED | New `test_formula_recovery_http_deadlines.py`: four failed, one passed. Both order-shipment paths timed out before reaching the provider; both catalog modes remained pending. |
| GREEN / triangulation | Six caller tests passed, including actual slow HTTP failure, successful product and all three buybox endpoints, sibling joining, and quota-expired catalog job pending with zero consumed attempts and zero fabricated snapshots. |
| Focused command | `uv run pytest modules/sheets/tests/test_formula_recovery_http_deadlines.py modules/sheets/tests/test_formula_layered_pacing.py modules/sheets/tests/test_zelerdata_recovery_pacing.py -q`: exit 0, 28 passed |
| Existing regressions | `uv run pytest modules/sheets/tests/test_formula_buybox_partial_recovery.py modules/sheets/tests/test_formula_recovery.py -k 'catalog_product_worker or buybox_preserves or shipment' -q`: exit 0, 53 passed |
| Static verification | Ruff check clean; mypy pacing and recovery worker: exit 0, two source files. Formatting and import ordering normalized. |
| Runtime harness | Real worker dispatch, queue leases, persistence and catalog snapshots against the parent's verified isolated Mongo PRIMARY on loopback port 27028; shortened HTTP deadlines expire before simulated quota waits, while corrected callers reach providers successfully. |
| Rollback boundary | The five helper call sites/imports in recovery worker, `recovery_request` helper and new caller test file; preserve unrelated worker lane/acquisition changes. |

## Nested deadline correction

Independent peer verification found discovery's existing outer timeout could
precede the job-wide quota deadline. The discovery owner adds a shorter quota
scope. Pacing now retains the minimum of parent and nested deadlines, so a
nested scope cannot lengthen an already running job's quota allowance.

Strict RED: parent 0.01s / nested 1s exhausted an external 0.1s guard as plain
`TimeoutError`. GREEN: both parent-shorter and nested-shorter cases raise
`LocalQuotaTimeoutError` before that guard (2 passed); the combined pre-second-
parameter pacing/caller suite passed 29 tests. Ruff check/format and mypy for
pacing and its test file pass. No other behavior changed in this correction.

## Quota expiry during sibling drain

Independent peer verification reproduced a known quota failure being masked by
the outer worker timeout while another catalog child was still completing.
Strict RED used the real `_finish_catalog_batch` with quota expiry at 0.03s,
outer deadline at 0.04s, and sibling completion at 0.05s: local quota incorrectly
consumed a source retry (one failed, genuine-source companion passed).

The quota context now yields a per-job `RecoveryQuotaScope`; child tasks and
nested scopes share its `expired` evidence. Only actual quota timeout marks it.
If the outer timeout interrupts sibling draining after known quota expiry,
the worker defers; genuine provider timeout retains normal retry accounting.
The context is restored at job exit, and external cancellation still propagates.

GREEN triangulation: quota deferral, genuine source retry, and external
cancellation with drained sibling all pass; the following job starts unexpired.
Combined pacing, HTTP caller/discovery and worker-lifecycle command:
`uv run pytest modules/sheets/tests/test_formula_layered_pacing.py modules/sheets/tests/test_formula_recovery_http_deadlines.py modules/sheets/tests/test_zelerdata_recovery_pacing.py modules/sheets/tests/test_layered_recovery_worker.py -o addopts='' -q`:
**38 passed in 6.86s**. Ruff check, mypy for all three touched files and diff
check pass. Root/peer own independent confirmation of this correction.
