# Apply progress: sustained recovery pacing

Scoped correction after the first layered worker rollout. No commits or runtime
mutations performed by this executor. The parent owns final gates and delivery.

## Cause and correction

Weighted rotation only considered pending requests. An inventory worker awaiting
Mongo/history/projection writes temporarily left the pending set, allowing fast
ID/range producers to consume an entire fixed-window budget before its next
batch. This was bounded request fairness, not sustained inventory throughput.

Explicit-lane acquisition now spaces grants across the shared minute, with a
minimum interval rounded upward to 333334 microseconds at 180 requests/minute.
The existing fixed-window cap also remains enforced. Pending requests retain
1:2:1 rotation; idle lanes reserve no slots and receive no accumulated credits.
A returning inventory batch can compete for the next spaced grant instead of
waiting for a previously exhausted full minute.

Legacy-only instances retain their prior fixed-window contract. Once explicit
lanes use an instance, all callers sharing that instance respect its spacing,
including later legacy calls. Every production recovery lane is explicit.
Budgets, TTL, HTTP deadlines, cancellation ownership and public formulas remain
unchanged.

## TDD evidence

| Step | Evidence |
| --- | --- |
| RED | New sustained-competition test and grant-spacing test both failed: 95 batches did not finish within 900 simulated seconds; initial grants were simultaneous. Command selecting `projection_gaps or spread_across`: 2 failed in 9.07s. |
| GREEN | Pacing plus original legacy tests: 26 passed in 9.49s. The sustained test keeps both competitors running until all 1,900 items complete, with three simulated seconds of persistence delay between each batch. |
| Triangulation | Shared minute spacing across 181 admissions, idle-window rollover, weighted competition, legacy-only compatibility, and explicit/legacy mixed use. Mixed transition plus spacing/fairness selection: 3 passed. |
| Refactor | Consolidated spacing and budget-window waiting into one timer calculation. Ruff check/format, focused mypy and diff checks pass. |

The two previous lane-aware assertions expecting a full-window burst were
updated to require evenly spaced waits. All ten original legacy pacing tests
retain their original assertions and pass.

## Work unit evidence

`MONGO_URI=<verified isolated loopback rs0> uv run pytest modules/sheets/tests/test_formula_layered_pacing.py modules/sheets/tests/test_zelerdata_recovery_pacing.py modules/sheets/tests/test_formula_recovery_http_deadlines.py modules/sheets/tests/test_layered_recovery_worker.py modules/sheets/tests/test_layered_inventory_load.py -o addopts='' -q`

Result: **41 passed in 75.58s**. Output:
`/tmp/zeler-spaced-pacing-focused.log`. This includes the real Mongo 1,900-item
history/projection workload and HTTP/quota classification plus cancellation.
The mixed legacy test was added after this run collected tests and separately
passed in the three-case selection above. Parent final gates include it.

The new sustained competitor regression scales a minute to 0.6 wall seconds;
actual coroutine sleeps model three seconds of between-batch persistence.
It proves the starvation mechanism is removed for this bounded workload, not a
production SLA. The live two-cycle freshness check remains required.

Rollback boundary: only pacing scheduler changes and associated pacing tests;
no queue, acquisition, API, schema or persistence changes. Affected runtime
image: sheets-worker. Parent/peer own independent verification before delivery.
