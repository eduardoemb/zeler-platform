# Layered recovery: queue and worker integration

Authority: approved September14 layered plan; selected checkout and existing
change artifacts. Strict TDD. Prior units1–4 and5.1a/5.3/5.5a remain as recorded
in tasks and their existing progress reports. No production mutations yet. Prior user release authorization is recorded in docs/zelerdata-live-formula-repairs.md; VCS delivery follows final checks.

## TDD cycle evidence

| Behavior | RED | GREEN | Refactor |
| --- | --- | --- | --- |
| Reserved admission, active dedup, lane isolation/cleanup, quota deferral | Four new isolated-Mongo tests failed before implementation | Four passed after implementation | Formatted; recovery/API regression567 passed |
| Independent lane lifecycle and quota/source separation | Three new worker tests failed before implementation | Three passed | Composite watchers shield owned child work during teardown |
| Inventory basic batch through history/projection | Real Mongo worker failed before basic-mode wiring | Real discovery +20 item acquisition/history/projection passed | Basic batch20; explicit enrichment retains four sub-batches |
| API runtime reservation | Factory regression showed0 instead of1 | Passed in combined queue/worker run | Queue default0 remains compatible with explicit legacy callers; runtime API/worker reserve1 |

Safety net before root changes:434 existing recovery/supervisor tests passed on
fresh isolated replica set127.0.0.1:27028. Initial combined regressions exposed request test fixtures lacking Request.state;
all six fixtures were corrected. Recovery/API combined regression:567 passed.

## Work unit evidence

Focused command: `uv run pytest modules/sheets/tests/test_layered_recovery_queue.py modules/sheets/tests/test_layered_recovery_worker.py` (eight cases passed before factory ninth was added).
Runtime harness: actual local Mongo queue claims/admission/defer and worker
acquisition/history/formula reader; no production target. Final local queue/worker nine-case set passed; independent concurrency/factory/cancellation probes also passed.
Rollback: recovery queue admission/claim/defer, recovery worker lane/basic wiring,
consumer composite supervisor and app reservation. Retain other acquisition,
pacing and formula changes as separately evidenced units.

Final integration: full repository4606 passed/9 skipped; protected Mongo8 passed
separately. Ruff check/format, mypy541files, direct-Meli lint and diff checks pass.
Independent factory/concurrency/draining probes:3passed. Runtime acceptance is
pending6.6. Review boundary remains acquisition, pacing and integrated queue/API
units; the integration slice exceeds400lines including behavioral tests and is
reported honestly rather than compressed or requiring an unrequested PR workflow.
