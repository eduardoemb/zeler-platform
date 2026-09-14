# Broker probe ownership — task 7.1 slice

This slice fixes ephemeral broker probes used by the four module APIs and the Sheets claims queue health check. The coordinator owns task completion and the active SDD attempt. No commit, build, deployment, broker mutation, or production query was performed by this executor.

## Result

Each default probe owns a nonrobust `aio_pika.Connection` before connecting. A scoped `OwnedAmqpTransport` delegates to the installed TCP/TLS transport factory and retains its socket before AMQP handshake completion. Cleanup joins a bounded close task and aborts any remaining captured socket, including the installed aiormq early-handshake gap. There is no global library patch or connection pool. Gateway may reuse this transport owner for its separately managed persistent connection.

The operation budget covers connect and all passive queue inspection work. Cleanup has a separate `min(timeout_seconds, 5)` second budget: at the default settings, each attempt allows 5 seconds of operation and up to 5 seconds of cleanup. Cancellation propagates after cleanup. This is a cooperative asyncio budget, not a guarantee against arbitrary injected code suppressing cancellation. Existing injectable connectors must own resources until they return; their public call signatures remain compatible.

Core checks use the real `is_closed` and `connected` interface; legacy injected `is_open` fakes remain supported. Fixed public failure strings also cover cleanup errors. Cache TTL starts at completion, preventing slow failed attempts from causing sequential retries by queued followers. Concurrent cache followers share the completed result; the health router still aggregates its checks sequentially and no endpoint-wide deadline was introduced.

## TDD cycle evidence

| Unit | Safety net | RED | GREEN | Triangulation / refactor |
| --- | --- | --- | --- | --- |
| Socket ownership, full probe budget, state and cleanup | Existing core runtime tests: 11 passed | New lifecycle file: 11 failed, 4 passed before implementation | 15 new cases passed; 26 with baseline | Core and claims silent TCP handshake, plain/TLS delegation, channel/declare/connect timeout, successful depth, cancellation, close timeout/error, real state |
| Completed-result TTL | Prior focused set: 57 passed | Ten concurrent slow failures connected ten times; expected one | New case passes; next request after TTL reconnects | Existing TTL compatibility retained; focused set now 58 passed |

## Work unit evidence

| Evidence | Result |
| --- | --- |
| Focused command | `uv run pytest tests/test_broker_probe_ownership.py core/tests/test_runtime_checks.py modules/sheets/tests/test_health_router.py modules/sheets/tests/test_app_phase6.py modules/repricer/tests/test_app_phase4.py modules/autoreply/tests/test_app_phase6.py modules/publicador/tests/test_app_phase6.py modules/publicador/tests/test_app_router_wiring.py -q` — 58 passed |
| Runtime harness | Two new local TCP server tests accept a real installed-library connection but never start AMQP handshake. Before correction the peer remained open after probe timeout; after correction both core and claims observe EOF. Server writers and handler tasks are joined in test cleanup. No broker or network outside loopback is used. |
| Static checks | Ruff check, Ruff format, and mypy pass for the three owned Python files. |
| Rollback boundary | Core `runtime/checks.py`, Sheets `consumer.py` claims health function/import, and new `tests/test_broker_probe_ownership.py`. If gateway adopts `OwnedAmqpTransport`, revert its importing use with this helper; do not remove the shared class independently. |

## Runtime scope and limits

Core callers are the `sheets`, `repricer`, `publicador`, and `autoreply` APIs. No worker calls this health factory. Claims queue inspection is used by the Sheets API. Image rebuild/deployment and runtime broker-capacity verification remain coordinator-owned. TLS selection/delegation is tested; no external TLS broker was contacted. Existing claims queue depth interpretation is unchanged by this lifecycle fix.

Independent peer review by `apply_basic` passed: source review found no blocking issue and the 16 new lifecycle cases independently passed in 0.47 seconds. Repository-wide gates remain coordinator-owned; this focused slice does not establish full live-formula closure.
