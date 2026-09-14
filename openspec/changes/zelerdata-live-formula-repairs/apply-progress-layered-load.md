# Apply progress: accelerated inventory acceptance

Task 6.5's bounded load regression is implemented. This supplements task 6.1's
RED/GREEN evidence; it changes no executable product behavior. Repository gates,
independent verification and live certification remain separate obligations.

## Harness

`test_layered_inventory_load.py` executes a real `FormulaRecoveryWorker`, Mongo
queue, canonical writes, status histories, price/stock snapshots and formula
projections for 1,900 synthetic owned publications. Discovery uses 19 pages;
acquisition uses 95 batches of 20. One in ten publications requires a separate
variation lookup: 190 calls recover actual variation SKU identities.

The shared 180-request/minute pacer also serves two claimed competing lanes,
300 requests per lane. Both competing jobs remain occupied while an inventory
batch completes; their workloads then run concurrently with the remaining
inventory. Their HTTP producers exercise the actual shared pacer and claim
boundaries, not complete catalog/order payload parsing.

The controlled source clock includes 0.1 seconds per HTTP call, virtual quota
sleeps, and measured real elapsed Mongo/history/projection time. Assertions
require completed enumeration, all 1,900 identities, all source observations
and membership still within 15 minutes, and 1,900 records in each history
collection. Unexpected cost, promotion or quality requests fail the test.
This workload models source availability; it does not establish a production
latency SLA or cover arbitrary variation cardinality/provider failures.

## Evidence

| Evidence | Result |
| --- | --- |
| Focused command | `MONGO_URI=<verified isolated loopback rs0> uv run pytest modules/sheets/tests/test_layered_inventory_load.py -o addopts='' -q` |
| Result | **1 passed in 86.61 seconds**; logical freshness assertions below 15 minutes passed |
| Runtime harness | Real dedicated local Mongo on port 27028; unique disposable test database, removed by the fixture; all 1,900 histories and projections verified |
| TDD relationship | Acceptance coverage of task 6.1–6.3 behavior already implemented under RED/GREEN; no new product code was changed for this test |
| Static checks | Ruff check, format check and mypy passed for the new test file |
| Rollback boundary | Delete only the new load test and this evidence; no production implementation changes |

Source failure and bounded-attempt behavior belong to the focused recovery
regressions. Passing this all-recoverable workload must not replace those tests,
nor the required two live inventory cycles and original 35-case Sheet retest.
