from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import pathlib
import signal
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest
from infra.operations.sheets_dlq_snapshot_adapter import (
    BUFFER_CAPACITY,
    SNAPSHOT_CAP,
    BrokerChannelLostError,
    NackRequeueError,
    PreflightError,
    SameHostExclusionError,
    SnapshotAbortedError,
    SnapshotBroker,
    SnapshotCoordinator,
    SnapshotDelivery,
    completion_proof,
    install_signal_handlers,
    run_preflight,
    same_host_exclusion,
)
from infra.operations.sheets_dlq_snapshot_runtime import (
    EXECUTION_CANCELLED,
    EXECUTION_CLOSE_ERROR,
    EXECUTION_COMPLETED,
    EXECUTION_MESSAGE_ERROR,
    EXECUTION_PREFLIGHT_ERROR,
    EXIT_CLOSE,
    EXIT_CONFIG,
    EXIT_MESSAGE_OR_CANCELLED,
    EXIT_PREFLIGHT,
    EXIT_USAGE,
    MESSAGE_NOT_OBTAINED,
    WORKER_HEALTH_URL,
    AioPikaSnapshotBroker,
    HttpSheetsWorkerRuntime,
    main,
    run_snapshot_runtime,
)
from zeler_platform_test_support.sheets_dlq_snapshot import (
    FakeBroker,
    FakeChannel,
    FakeConnect,
    FakeConnection,
    FakeDecl,
    FakeMessage,
    FakeMsg,
    FakeQueue,
    FakeRuntime,
    queue_state,
)

DLQ = "zeler.sheets.events.dlq"


def _body(index: int) -> bytes:
    return json.dumps({"message_id": f"msg-{index}"}).encode("utf-8")


@pytest.mark.asyncio
async def test_fake_get_one_assigns_ascending_delivery_tags_and_nack_records_tag() -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=3)},
        messages={DLQ: [_body(1), _body(2), _body(3)]},
    )

    first = await broker.get_one(DLQ)
    assert first is not None
    assert first.delivery_tag == 1
    second = await broker.get_one(DLQ)
    assert second is not None
    assert second.delivery_tag == 2

    await broker.nack_requeue(first)
    await broker.nack_requeue(second)

    assert f"get_one:{DLQ}:1:{_body(1).decode()}" in broker.calls
    assert f"get_one:{DLQ}:2:{_body(2).decode()}" in broker.calls
    assert f"nack_requeue:{DLQ}:1" in broker.calls
    assert f"nack_requeue:{DLQ}:2" in broker.calls


@pytest.mark.asyncio
async def test_fake_get_one_returns_none_when_queue_is_empty() -> None:
    broker = FakeBroker(states={DLQ: queue_state(ready=0)}, messages={DLQ: []})

    assert await broker.get_one(DLQ) is None


@pytest.mark.asyncio
async def test_first_run_defaults_bind_k_and_cap_to_twenty_four() -> None:
    assert BUFFER_CAPACITY == 24
    assert SNAPSHOT_CAP == 24


@pytest.mark.asyncio
async def test_acquire_bounds_to_cap_when_thirty_queued() -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=30)},
        messages={DLQ: [_body(i) for i in range(30)]},
    )
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))

    buffered = await coordinator.acquire(DLQ)

    assert len(buffered) == SNAPSHOT_CAP == 24
    assert len(broker.messages[DLQ]) == 6  # 30 ready, 24 moved unacked, 6 remain


@pytest.mark.asyncio
async def test_acquire_stops_on_get_none_when_fewer_than_cap() -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=3)},
        messages={DLQ: [_body(i) for i in range(3)]},
    )
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))

    buffered = await coordinator.acquire(DLQ)

    assert len(buffered) == 3
    assert [item.delivery_tag for item in buffered] == [1, 2, 3]


@pytest.mark.asyncio
async def test_drain_nacks_in_ascending_delivery_tag_order() -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=3)},
        messages={DLQ: [_body(i) for i in range(3)]},
    )
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    # Buffer holds scrambled tags 7, 5, 6; drain must emit ascending 5, 6, 7.
    buffered = [_tagged(tag, i) for i, tag in enumerate((7, 5, 6), start=1)]

    await coordinator.drain(buffered)

    nacks = [call for call in broker.calls if call.startswith("nack_requeue:")]
    assert nacks == [
        f"nack_requeue:{DLQ}:5",
        f"nack_requeue:{DLQ}:6",
        f"nack_requeue:{DLQ}:7",
    ]


def _tagged(tag: int, index: int) -> SnapshotDelivery:
    return FakeMessage(DLQ, _body(index), {}, delivery_tag=tag)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offline_consumers",
    [1, 5],
)
async def test_preflight_fails_closed_on_nonzero_offline_consumers(
    offline_consumers: int,
) -> None:
    broker = FakeBroker(states={DLQ: queue_state(consumers=0)})

    with pytest.raises(PreflightError, match="offline consumer count"):
        await run_preflight(
            broker=_as_broker(broker),
            runtime=FakeRuntime(healthy=True),
            queue_name=DLQ,
            offline_consumers=offline_consumers,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consumers",
    [1, 3],
)
async def test_preflight_fails_closed_on_live_consumers(consumers: int) -> None:
    broker = FakeBroker(states={DLQ: queue_state(consumers=consumers)})

    with pytest.raises(PreflightError, match="live consumer count"):
        await run_preflight(
            broker=_as_broker(broker),
            runtime=FakeRuntime(healthy=True),
            queue_name=DLQ,
        )


@pytest.mark.asyncio
async def test_preflight_fails_closed_when_worker_runtime_is_unhealthy() -> None:
    broker = FakeBroker(states={DLQ: queue_state(consumers=0)})

    with pytest.raises(PreflightError, match="worker runtime is unhealthy"):
        await run_preflight(
            broker=_as_broker(broker),
            runtime=FakeRuntime(healthy=False),
            queue_name=DLQ,
        )


@pytest.mark.asyncio
async def test_preflight_passes_when_all_gates_clear() -> None:
    broker = FakeBroker(states={DLQ: queue_state(consumers=0)})

    await run_preflight(
        broker=_as_broker(broker),
        runtime=FakeRuntime(healthy=True),
        queue_name=DLQ,
    )


@pytest.mark.asyncio
async def test_preflight_fails_closed_when_inspect_queue_returns_none() -> None:
    # No queue state -> inspect_queue returns None; zero-consumers unproven.
    with pytest.raises(PreflightError, match="no consumer proof"):
        await run_preflight(
            broker=_as_broker(FakeBroker(states={})),
            runtime=FakeRuntime(healthy=True),
            queue_name=DLQ,
        )


def test_same_host_exclusion_is_nonblocking_and_fails_closed_on_contention(
    tmp_path: pathlib.Path,
) -> None:
    lock_path = str(tmp_path / "snapshot.lock")
    with (
        same_host_exclusion(lock_path),
        pytest.raises(SameHostExclusionError),
        same_host_exclusion(lock_path),
    ):
        pass


def test_same_host_exclusion_releases_between_acquisitions(tmp_path: pathlib.Path) -> None:
    lock_path = str(tmp_path / "snapshot.lock")
    with same_host_exclusion(lock_path):
        pass
    # After the first guard exits the lock is released; a second acquisition succeeds.
    with same_host_exclusion(lock_path):
        pass


def test_adapter_exposes_no_mongo_or_forbidden_broker_imports() -> None:
    module_path = pathlib.Path("infra/operations/sheets_dlq_snapshot_adapter.py")
    source = module_path.read_text(encoding="utf-8")
    assert "AsyncIOMotorClient" not in source
    assert "motor" not in source
    assert "pymongo" not in source

    members = set(SnapshotBroker.__dict__).union(
        name for name, _ in inspect.getmembers(SnapshotBroker)
    )
    assert {"inspect_queue", "get_one", "nack_requeue", "close_channel"} <= members
    assert not members.intersection(
        {
            "ack",
            "publish",
            "publish_confirmed",
            "declare_queue",
            "delete_queue",
            "quarantine",
            "disposition",
            "replay",
        }
    )


def _make_broker(count: int) -> FakeBroker:
    return FakeBroker(
        states={DLQ: queue_state(ready=count)},
        messages={DLQ: [_body(i) for i in range(count)]},
    )


def _as_broker(broker: FakeBroker) -> SnapshotBroker:
    """Cast a structurally-compatible test double to the narrow protocol."""
    return cast(SnapshotBroker, broker)


class FailingNackBroker(FakeBroker):
    """Fake that raises on a chosen delivery tag during ``nack_requeue``."""

    def __init__(
        self,
        *,
        fail_tag: int,
        exc: Exception,
        count: int = 3,
    ) -> None:
        super().__init__(
            states={DLQ: queue_state(ready=count)},
            messages={DLQ: [_body(i) for i in range(count)]},
        )
        self.fail_tag = fail_tag
        self.exc = exc

    async def nack_requeue(self, delivery: FakeMessage) -> None:
        if delivery.delivery_tag == self.fail_tag:
            self.calls.append(f"nack_requeue:{delivery.queue_name}:{delivery.delivery_tag}")
            raise self.exc
        await super().nack_requeue(delivery)


def test_drain_records_requeue_requested_with_no_confirmation_claim() -> None:
    broker = _make_broker(3)
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    buffered = asyncio.run(coordinator.acquire(DLQ))

    outcomes = asyncio.run(coordinator.drain(buffered))

    assert outcomes == ["requeue_requested", "requeue_requested", "requeue_requested"]
    assert not any("confirm" in item for item in broker.calls)
    assert not any("requeued" in item for item in broker.calls)


def test_drain_on_definite_send_failure_closes_and_stops_without_more_nacks() -> None:
    broker = FailingNackBroker(fail_tag=2, exc=NackRequeueError("local send failure"))
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    buffered = asyncio.run(coordinator.acquire(DLQ))

    with pytest.raises(SnapshotAbortedError):
        asyncio.run(coordinator.drain(buffered))

    assert "channel_close" in broker.calls
    assert f"nack_requeue:{DLQ}:3" not in broker.calls
    assert coordinator.outcomes == ["requeue_requested", "requeue_send_failed"]


def test_drain_on_transport_loss_records_outcome_unknown_and_closes() -> None:
    broker = FailingNackBroker(fail_tag=2, exc=BrokerChannelLostError("transport lost"))
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    buffered = asyncio.run(coordinator.acquire(DLQ))

    with pytest.raises(SnapshotAbortedError):
        asyncio.run(coordinator.drain(buffered))

    assert "channel_close" in broker.calls
    assert f"nack_requeue:{DLQ}:3" not in broker.calls
    assert coordinator.outcomes == ["requeue_requested", "outcome_unknown"]


def test_drain_never_issues_nack_after_an_ambiguous_failure() -> None:
    broker = FailingNackBroker(fail_tag=2, exc=BrokerChannelLostError("connection closed"), count=4)
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    buffered = asyncio.run(coordinator.acquire(DLQ))

    with pytest.raises(SnapshotAbortedError):
        asyncio.run(coordinator.drain(buffered))

    nack_calls = [call for call in broker.calls if call.startswith("nack_requeue:")]
    assert nack_calls == [f"nack_requeue:{DLQ}:1", f"nack_requeue:{DLQ}:2"]
    assert coordinator.outcomes == ["requeue_requested", "outcome_unknown"]


def test_cancellation_during_acquire_issues_best_effort_close_no_completion_claim(
    tmp_path: pathlib.Path,
) -> None:
    class CancellingBroker(FakeBroker):
        async def get_one(self, queue_name: str) -> FakeMessage | None:
            self.calls.append("get_one_called")
            raise asyncio.CancelledError()

    broker = CancellingBroker(states={DLQ: queue_state(ready=3)})
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            coordinator.run(
                queue_name=DLQ,
                lock_path=str(tmp_path / "snapshot.lock"),
                runtime=FakeRuntime(healthy=True),
            )
        )

    assert "channel_close" in broker.calls
    assert coordinator.state == "FAILED"
    assert not any("completion" in item or "proof" in item for item in broker.calls)


def test_handled_exception_during_run_closes_best_effort_and_sets_failed(
    tmp_path: pathlib.Path,
) -> None:
    class ExplodingBroker(FakeBroker):
        async def get_one(self, queue_name: str) -> FakeMessage | None:
            raise RuntimeError("boom")

    broker = ExplodingBroker(states={DLQ: queue_state(ready=3)})
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            coordinator.run(
                queue_name=DLQ,
                lock_path=str(tmp_path / "snapshot.lock"),
                runtime=FakeRuntime(healthy=True),
            )
        )

    assert "channel_close" in broker.calls
    assert coordinator.state == "FAILED"


def test_run_completes_and_closes_channel_after_clean_drain(
    tmp_path: pathlib.Path,
) -> None:
    broker = _make_broker(2)
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))

    asyncio.run(
        coordinator.run(
            queue_name=DLQ,
            lock_path=str(tmp_path / "snapshot.lock"),
            runtime=FakeRuntime(healthy=True),
        )
    )

    assert coordinator.state == "COMPLETE"
    assert "channel_close" in broker.calls
    assert coordinator.outcomes == ["requeue_requested", "requeue_requested"]


@pytest.mark.asyncio
async def test_run_fails_closed_on_contended_lock_before_preflight(
    tmp_path: pathlib.Path,
) -> None:
    lock_path = str(tmp_path / "snapshot.lock")
    broker = FakeBroker(states={DLQ: queue_state(ready=1, consumers=0)})
    coordinator = SnapshotCoordinator(broker=_as_broker(broker))
    # Lock acquired before any preflight inspection (no inspect call on
    # contention) and STATE_LOCKED is only set after acquisition succeeds.
    with same_host_exclusion(lock_path), pytest.raises(SameHostExclusionError):
        await coordinator.run(
            queue_name=DLQ, lock_path=lock_path, runtime=FakeRuntime(healthy=True)
        )
    assert "inspect:" not in broker.calls
    assert coordinator.state != "LOCKED"


def test_sigint_and_sigterm_route_to_cancellation() -> None:
    cancel_calls: list[str] = []
    prev = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    try:
        handled = install_signal_handlers(lambda: cancel_calls.append("cancel"))
        assert handled == (signal.SIGINT, signal.SIGTERM)
        sig_int = cast("Callable[[int, object], None]", signal.getsignal(signal.SIGINT))
        sig_term = cast("Callable[[int, object], None]", signal.getsignal(signal.SIGTERM))
        sig_int(signal.SIGINT, None)
        sig_term(signal.SIGTERM, None)
        assert cancel_calls == ["cancel", "cancel"]
    finally:
        signal.signal(signal.SIGINT, prev[0])
        signal.signal(signal.SIGTERM, prev[1])


def test_completion_proof_exists_only_for_orderly_complete() -> None:
    assert completion_proof("COMPLETE") is not None
    # Abrupt death (SIGKILL/OOM/segfault) can leave ACQUIRING/DRAINING and never
    # reach COMPLETE, so no completion proof exists for those terminations.
    for state in ("INIT", "ACQUIRING", "DRAINING", "FAILED"):
        assert completion_proof(state) is None


# PR 1: sheets_dlq_snapshot_runtime — module separation + narrow adapters.


def _broker(conn: FakeConnection, url: str = "amqp://test") -> AioPikaSnapshotBroker:
    return AioPikaSnapshotBroker(url, connect=FakeConnect(connections=[conn]))


def _runtime(handler: httpx.MockTransport) -> HttpSheetsWorkerRuntime:
    return HttpSheetsWorkerRuntime(
        client_factory=lambda: httpx.AsyncClient(
            transport=handler, timeout=2.0, follow_redirects=False
        )
    )


def test_runtime_module_separate_and_adapter_inert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import infra.operations.sheets_dlq_snapshot_adapter as adapter_mod
    import infra.operations.sheets_dlq_snapshot_runtime as runtime_mod

    assert runtime_mod.__file__ != adapter_mod.__file__
    with pytest.raises(SystemExit) as exc:
        adapter_mod.main(["--lock-path", "snap.lock"], broker=None, runtime=None)
    assert exc.value.code == 2
    assert "injected ports" in capsys.readouterr().err


def test_broker_and_runtime_narrow_surfaces() -> None:
    broker = set(AioPikaSnapshotBroker.__dict__)
    runtime = set(HttpSheetsWorkerRuntime.__dict__)
    assert {"inspect_queue", "get_one", "nack_requeue", "close_channel"} <= broker
    assert "worker_is_healthy" in runtime
    for word in "ack publish purge delete quarantine replay nack mutate".split():  # noqa: SIM905
        assert word not in broker
        assert word not in runtime


def test_runtime_module_hermetic_imports() -> None:
    src = pathlib.Path("infra/operations/sheets_dlq_snapshot_runtime.py").read_text(
        encoding="utf-8"
    )
    for word in ("motor", "pymongo", "subprocess", "os.system", "Popen", "docker", "socket"):
        assert word not in src
    assert "aio_pika.connect" in src
    assert "aio_pika.connect_robust" not in src


@pytest.mark.asyncio
async def test_broker_connects_lazily_and_inspects_passive() -> None:
    connect = FakeConnect()
    lazy = AioPikaSnapshotBroker("amqp://test", connect=connect)
    assert connect.calls == []
    await lazy.inspect_queue(DLQ)
    assert connect.calls == ["amqp://test"]
    ch = FakeChannel(queue=FakeQueue(declaration_result=FakeDecl(message_count=5)))
    inspection = await _broker(FakeConnection(channel=ch)).inspect_queue(DLQ)
    assert inspection is not None
    assert ch.passives == [True]
    assert (inspection.ready, inspection.consumers, inspection.unacked) == (5, 0, -1)


@pytest.mark.asyncio
async def test_get_one_manual_no_ack_and_empty() -> None:
    msg = FakeMsg(body=b'{"a":1}', delivery_tag=7)
    ch = FakeChannel(messages={DLQ: msg})
    delivery = await _broker(FakeConnection(channel=ch)).get_one(DLQ)
    assert delivery is not None and ch.no_acks == [False]
    assert (delivery.delivery_tag, delivery.body) == (7, b'{"a":1}')
    empty = await _broker(FakeConnection(channel=FakeChannel(messages={DLQ: None}))).get_one(DLQ)
    assert empty is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nack_error,expect",
    [
        pytest.param(None, None, id="ok"),
        pytest.param(RuntimeError("boom"), pytest.raises(RuntimeError, match="boom"), id="fail"),
    ],
)
async def test_nack_requeue_requeue_true_multiple_false(
    nack_error: Exception | None, expect: Any
) -> None:
    msg = FakeMsg(body=b"{}", delivery_tag=3, nack_error=nack_error)
    broker = _broker(FakeConnection(channel=FakeChannel(messages={DLQ: msg})))
    delivery = await broker.get_one(DLQ)
    if expect is None:
        await broker.nack_requeue(cast(SnapshotDelivery, delivery))
        assert msg.nacks == [(True, False)]
    else:
        with expect:
            await broker.nack_requeue(cast(SnapshotDelivery, delivery))


@pytest.mark.asyncio
async def test_close_channel_idempotent_dedicated_partial_and_total_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def count_timeout(awaitable: Awaitable[Any], *, timeout: float) -> Any:
        waits.append(timeout)
        return await awaitable

    ch_a = FakeChannel()
    conn_a = FakeConnection(channel=ch_a)
    conn_b = FakeConnection()
    a = _broker(conn_a, "amqp://a")
    b = _broker(conn_b, "amqp://b")
    await a.inspect_queue(DLQ)
    await b.inspect_queue(DLQ)
    monkeypatch.setattr(asyncio, "wait_for", count_timeout)
    await a.close_channel()
    assert waits == [5.0]
    await a.close_channel()
    assert ch_a.calls.count("channel_close") == 1
    assert conn_a.calls.count("connection_close") == 1
    assert conn_b.calls.count("connection_close") == 0
    partial = _broker(FakeConnection(channel_error=RuntimeError("chan")))
    with pytest.raises(RuntimeError, match="chan"):
        await partial.inspect_queue(DLQ)
    await partial.close_channel()
    await AioPikaSnapshotBroker("amqp://x", connect=FakeConnect()).close_channel()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,healthy",
    [
        pytest.param(httpx.Response(200), True, id="200"),
        pytest.param(httpx.Response(500), False, id="500"),
        pytest.param(
            httpx.Response(302, headers={"location": "http://elsewhere"}), False, id="302"
        ),
    ],
)
async def test_worker_health_by_status(response: httpx.Response, healthy: bool) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    assert await _runtime(httpx.MockTransport(handler)).worker_is_healthy() is healthy


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [httpx.ReadTimeout, httpx.ConnectError],
    ids=["timeout", "transport"],
)
async def test_worker_unhealthy_on_timeout_or_transport(
    exc: type[httpx.TransportError],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise exc("boom", request=request)

    assert await _runtime(httpx.MockTransport(handler)).worker_is_healthy() is False


@pytest.mark.asyncio
async def test_worker_uses_fixed_get_url_without_redirects() -> None:
    assert WORKER_HEALTH_URL == "http://sheets-worker:8080/health"
    seen: list[tuple[httpx.URL, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url, request.method))
        return httpx.Response(200)

    assert await _runtime(httpx.MockTransport(handler)).worker_is_healthy() is True
    assert seen == [(httpx.URL(WORKER_HEALTH_URL), "GET")]


# PR 2: runtime coordinator + reporter (tasks 3.1-3.5, 4.1, 4.2, 4.4, 4.5).


class FailingNackFake(FakeBroker):
    def __init__(self, *, fail_tag: int, exc: Exception, count: int) -> None:
        super().__init__(
            states={DLQ: queue_state(ready=count)},
            messages={DLQ: [_body(i) for i in range(count)]},
        )
        self.fail_tag, self.exc = fail_tag, exc

    async def nack_requeue(self, delivery: FakeMessage) -> None:
        if delivery.delivery_tag == self.fail_tag:
            self.calls.append(f"nack_requeue:{delivery.queue_name}:{delivery.delivery_tag}")
            raise self.exc
        await super().nack_requeue(delivery)


class ClosingFailingFake(FakeBroker):
    async def close_channel(self) -> None:
        self.calls.append("channel_close")
        raise RuntimeError("close boom")


class CancellingGetFake(FakeBroker):
    def __init__(self, *, cancel_after: int, count: int) -> None:
        super().__init__(
            states={DLQ: queue_state(ready=count)},
            messages={DLQ: [_body(i) for i in range(count)]},
        )
        self.cancel_after, self.gets = cancel_after, 0

    async def get_one(self, queue_name: str) -> FakeMessage | None:
        self.gets += 1
        if self.gets > self.cancel_after:
            raise asyncio.CancelledError()
        return await super().get_one(queue_name)


def _run(broker: FakeBroker, *, lock: str, healthy: bool = True) -> Awaitable[dict[str, object]]:
    return run_snapshot_runtime(
        broker=cast(SnapshotBroker, broker),
        runtime=FakeRuntime(healthy=healthy),
        queue_name=DLQ,
        limit=24,
        lock_path=lock,
    )


def _results(report: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], report["message_results"])


@pytest.mark.asyncio
async def test_preflight_lock_contention_fails_before_any_io(tmp_path: pathlib.Path) -> None:
    lock = str(tmp_path / "l.lock")
    broker = FakeBroker(states={DLQ: queue_state(consumers=0)})
    with same_host_exclusion(lock):
        report = await _run(broker, lock=lock)
    assert report["execution_outcome"] == EXECUTION_PREFLIGHT_ERROR
    assert report["error_code"] == 5
    assert "inspect:DLQ" not in broker.calls
    assert not any(c.startswith("get_one:") for c in broker.calls)


@pytest.mark.asyncio
async def test_preflight_health_fails_after_connectivity_with_zero_gets(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = str(tmp_path / "l.lock")
    broker = FakeBroker(
        states={DLQ: queue_state(ready=2, consumers=0)},
        messages={DLQ: [_body(i) for i in range(2)]},
    )
    report = await _run(broker, lock=lock, healthy=False)
    assert report["execution_outcome"] == EXECUTION_PREFLIGHT_ERROR
    assert report["error_code"] == 5
    assert f"inspect:{DLQ}" in broker.calls  # connectivity reached
    assert not any(c.startswith("get_one:") for c in broker.calls)  # health blocked get
    monkeypatch.setattr(broker, "inspect_queue", _boomer(ConnectionError("broker unreachable")))
    report = await _run(broker, lock=str(tmp_path / "l2.lock"))
    assert report["execution_outcome"] == EXECUTION_PREFLIGHT_ERROR
    assert not any(c.startswith("get_one:") for c in broker.calls)


@pytest.mark.asyncio
async def test_runtime_preflight_fails_closed_on_live_consumers(
    tmp_path: pathlib.Path,
) -> None:
    lock = str(tmp_path / "l.lock")
    broker = FakeBroker(states={DLQ: queue_state(consumers=2)})
    report = await _run(broker, lock=lock)
    assert report["execution_outcome"] == EXECUTION_PREFLIGHT_ERROR
    assert not any(c.startswith("get_one:") for c in broker.calls)


@pytest.mark.asyncio
async def test_universal_nack_ascending_one_per_delivery_continues_after_failure(
    tmp_path: pathlib.Path,
) -> None:
    broker = FailingNackFake(fail_tag=2, exc=NackRequeueError("fail"), count=3)
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    nacks = [c for c in broker.calls if c.startswith("nack_requeue:")]
    assert nacks == [
        f"nack_requeue:{DLQ}:1",
        f"nack_requeue:{DLQ}:2",
        f"nack_requeue:{DLQ}:3",
    ]
    assert [m["outcome"] for m in _results(report)] == [
        "requeue_requested",
        "requeue_send_failed",
        "requeue_requested",
    ]
    assert report["execution_outcome"] == EXECUTION_MESSAGE_ERROR
    assert report["error_code"] == 6


@pytest.mark.asyncio
async def test_coordinator_maps_transport_loss_to_outcome_unknown(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FailingNackFake(fail_tag=2, exc=BrokerChannelLostError("lost"), count=3)
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    assert [m["outcome"] for m in _results(report)] == [
        "requeue_requested",
        "outcome_unknown",
        "requeue_requested",
    ]
    assert report["execution_outcome"] == EXECUTION_MESSAGE_ERROR
    monkeypatch.setattr("infra.operations.sheets_dlq_snapshot_runtime._NACK_TIMEOUT", 0.01)
    timed_broker = FakeBroker(states={DLQ: queue_state(ready=1)}, messages={DLQ: [_body(0)]})
    monkeypatch.setattr(timed_broker, "nack_requeue", lambda _delivery: asyncio.sleep(0.05))
    report = await _run(timed_broker, lock=str(tmp_path / "l.lock"))
    assert [m["outcome"] for m in _results(report)] == ["outcome_unknown"]


@pytest.mark.asyncio
async def test_cancellation_nacks_acquired_and_closes_reports_cancelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    broker = CancellingGetFake(cancel_after=1, count=3)

    async def blocking_nack(delivery: FakeMessage) -> None:
        started.set()
        await release.wait()
        await FakeBroker.nack_requeue(broker, delivery)

    monkeypatch.setattr(broker, "nack_requeue", blocking_nack)
    task: asyncio.Future[dict[str, object]] = asyncio.ensure_future(
        _run(broker, lock=str(tmp_path / "l.lock"))
    )
    await started.wait()
    task.cancel()
    release.set()
    report = await task
    assert [c for c in broker.calls if c.startswith("nack_requeue:")] == [f"nack_requeue:{DLQ}:1"]
    assert "channel_close" in broker.calls
    assert report["execution_outcome"] == EXECUTION_CANCELLED
    assert report["error_code"] == 6


@pytest.mark.asyncio
async def test_close_error_precedence_reports_close_error(
    tmp_path: pathlib.Path,
) -> None:
    broker = ClosingFailingFake(
        states={DLQ: queue_state(ready=1)},
        messages={DLQ: [_body(0)]},
    )
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    assert report["execution_outcome"] == EXECUTION_CLOSE_ERROR
    assert report["error_code"] == 7


@pytest.mark.asyncio
async def test_empty_queue_reports_message_not_obtained(
    tmp_path: pathlib.Path,
) -> None:
    broker = FakeBroker(states={DLQ: queue_state(ready=0)}, messages={DLQ: []})
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    assert [m["outcome"] for m in _results(report)] == [MESSAGE_NOT_OBTAINED]
    assert report["execution_outcome"] == EXECUTION_COMPLETED
    assert report["error_code"] == 0


@pytest.mark.asyncio
async def test_reporter_completed_sanitized_without_secrets(
    tmp_path: pathlib.Path,
) -> None:
    broker = FakeBroker(
        states={DLQ: queue_state(ready=3)},
        messages={DLQ: [b'{"idempotency_key":"body-secret"}'] * 3},
    )
    broker.messages[DLQ][0].headers["authorization"] = "header-secret"
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    assert report["execution_outcome"] == EXECUTION_COMPLETED
    assert report["preflight"] is True
    assert report["close"] is True
    assert report["requeue_confirmation"] == "unavailable"
    assert report["error_code"] == 0
    assert [m["sequence"] for m in _results(report)] == [1, 2, 3]
    assert [m["outcome"] for m in _results(report)] == ["requeue_requested"] * 3
    assert _results(report)[0]["classification"] == "unknown_append_outcome"
    flat = json.dumps(report)
    for secret in ("idempotency_key", "body-secret", "authorization", "header-secret", "headers"):
        assert secret not in flat


# PR2a native-review correction: unexpected get_one exception must still nack,
# close, and emit a sanitized report (findings R3-001 / R4-001).


class ExplodingGetFake(FakeBroker):
    def __init__(self, *, after: int, count: int, close_error: Exception | None = None) -> None:
        super().__init__(
            states={DLQ: queue_state(ready=count)},
            messages={DLQ: [_body(i) for i in range(count)]},
        )
        self.after, self.gets, self.close_error = after, 0, close_error

    async def get_one(self, queue_name: str) -> FakeMessage | None:
        self.gets += 1
        if self.gets > self.after:
            raise RuntimeError("boom")
        return await super().get_one(queue_name)

    async def close_channel(self) -> None:
        self.calls.append("channel_close")
        if self.close_error is not None:
            raise self.close_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("close_error", "outcome", "error_code"),
    [
        (None, EXECUTION_MESSAGE_ERROR, 6),
        (RuntimeError("boom"), EXECUTION_CLOSE_ERROR, 7),
    ],
    ids=["message", "close"],
)
async def test_unexpected_get_failure_nacks_and_reports(
    tmp_path: pathlib.Path,
    close_error: Exception | None,
    outcome: str,
    error_code: int,
) -> None:
    broker = ExplodingGetFake(after=1, count=3, close_error=close_error)
    report = await _run(broker, lock=str(tmp_path / "l.lock"))
    assert [c for c in broker.calls if c.startswith("nack_requeue:")] == [f"nack_requeue:{DLQ}:1"]
    assert "channel_close" in broker.calls
    assert "outcome_unknown" in [m["outcome"] for m in _results(report)]
    assert report["execution_outcome"] == outcome
    assert report["error_code"] == error_code
    assert not any(s in json.dumps(report) for s in ("boom", "RuntimeError", "msg-", "uri"))


# PR 2b: authorized runtime CLI + auth + exits (tasks 1.3, 1.4, 4.3).

_AUTH_SHA256 = "SHEETS_DLQ_SNAPSHOT_AUTH_SHA256"
_LOCK_PATH = "SHEETS_DLQ_SNAPSHOT_LOCK_PATH"


def _auth_file(tmp_path: pathlib.Path, token: bytes, mode: int = 0o600) -> str:
    path = tmp_path / "auth.token"
    path.write_bytes(token)
    path.chmod(mode)
    return str(path)


def _hash(token: bytes) -> str:
    return hashlib.sha256(token).hexdigest()


def _set_env(monkeypatch: pytest.MonkeyPatch, token: bytes, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv(_AUTH_SHA256, _hash(token))
    monkeypatch.setenv(_LOCK_PATH, str(tmp_path / "l.lock"))


def _boomer(error: Exception) -> Callable[..., Any]:
    def _boom(*_args: object, **_kwargs: object) -> Any:
        raise error

    return _boom


def test_cli_unknown_option_fails_before_io(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--authorization-token-file", _auth_file(tmp_path, b"t"), "--purge"])
    assert exc.value.code == EXIT_USAGE


def test_cli_non_allowlisted_queue_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = b"secret"
    _set_env(monkeypatch, token, tmp_path)
    assert (
        main(["--authorization-token-file", _auth_file(tmp_path, token), "--queue", "other"])
        == EXIT_CONFIG
    )


@pytest.mark.parametrize("limit", [0, 25])
def test_cli_limit_out_of_range_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    token = b"secret"
    _set_env(monkeypatch, token, tmp_path)
    assert (
        main(
            [
                "--authorization-token-file",
                _auth_file(tmp_path, token),
                "--limit",
                str(limit),
            ]
        )
        == EXIT_CONFIG
    )


@pytest.mark.parametrize("amqp_url", [None, "   "], ids=["missing", "blank"])
def test_cli_incomplete_config_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, amqp_url: str | None
) -> None:
    token = b"secret"
    _set_env(monkeypatch, token, tmp_path)
    if amqp_url is None:
        monkeypatch.delenv("SHEETS_DLQ_SNAPSHOT_AMQP_URL", raising=False)
    else:
        monkeypatch.setenv("SHEETS_DLQ_SNAPSHOT_AMQP_URL", amqp_url)
    monkeypatch.setattr(
        "infra.operations.sheets_dlq_snapshot_runtime.AioPikaSnapshotBroker",
        _boomer(AssertionError("broker construction")),
    )
    assert main(["--authorization-token-file", _auth_file(tmp_path, token)]) == EXIT_CONFIG


@pytest.mark.parametrize("problem", ["missing_arg", "missing", "insecure", "wrong"])
def test_cli_authorization_rejected_reports_preflight_error_json(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
) -> None:
    token = b"secret"
    if problem == "missing_arg":
        path = None
    elif problem == "missing":
        path = str(tmp_path / "nope.token")
    elif problem == "insecure":
        path = _auth_file(tmp_path, b"x", mode=0o644)
    else:
        path = _auth_file(tmp_path, b"garbage")
    _set_env(monkeypatch, token, tmp_path)
    args = [] if path is None else ["--authorization-token-file", path]
    assert main(args) == EXIT_PREFLIGHT
    assert json.loads(capsys.readouterr().out)["execution_outcome"] == EXECUTION_PREFLIGHT_ERROR


def test_cli_successful_injected_composition_exit_0_json(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = b"secret"
    _set_env(monkeypatch, token, tmp_path)
    broker = FakeBroker(
        states={DLQ: queue_state(consumers=0)},
        messages={DLQ: [_body(i) for i in range(5)]},
    )
    rc = main(
        ["--authorization-token-file", _auth_file(tmp_path, token), "--limit", "5"],
        broker=cast(SnapshotBroker, broker),
        runtime=FakeRuntime(healthy=True),
        lock_path=str(tmp_path / "l.lock"),
    )
    outer = capsys.readouterr().out
    assert rc == 0
    assert json.loads(outer)["execution_outcome"] == EXECUTION_COMPLETED
    assert [m["outcome"] for m in json.loads(outer)["message_results"]] == ["requeue_requested"] * 5
    assert not any(secret in outer for secret in ("msg-", "secret", "token", "uri", "sha256"))


@pytest.mark.parametrize(
    ("broker", "expected_exit"),
    [
        (FakeBroker(states={DLQ: queue_state(consumers=2)}), EXIT_PREFLIGHT),
        (
            FailingNackFake(fail_tag=1, exc=NackRequeueError("fail"), count=1),
            EXIT_MESSAGE_OR_CANCELLED,
        ),
        (CancellingGetFake(cancel_after=0, count=2), EXIT_MESSAGE_OR_CANCELLED),
        (
            ClosingFailingFake(
                states={DLQ: queue_state(ready=1)},
                messages={DLQ: [_body(0)]},
            ),
            EXIT_CLOSE,
        ),
    ],
)
def test_cli_deterministic_exit_mapping(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    broker: FakeBroker,
    expected_exit: int,
) -> None:
    token = b"secret"
    _set_env(monkeypatch, token, tmp_path)
    args = ["--authorization-token-file", _auth_file(tmp_path, token)]
    rc = main(
        args,
        broker=cast(SnapshotBroker, broker),
        runtime=FakeRuntime(healthy=True),
        lock_path=str(tmp_path / "l.lock"),
    )
    assert rc == expected_exit
    runtime_module = "infra.operations.sheets_dlq_snapshot_runtime."
    lock = str(tmp_path / "fatal.lock")
    injected = dict(broker=cast(SnapshotBroker, broker), runtime=FakeRuntime(), lock_path=lock)
    monkeypatch.setattr(runtime_module + "json.dumps", _boomer(TypeError("boom")))
    assert main(args, **injected) == 8  # type: ignore[arg-type]
    monkeypatch.setattr(runtime_module + "run_snapshot_runtime", _boomer(RuntimeError("loop")))
    assert main(args, **injected) == 70  # type: ignore[arg-type]
