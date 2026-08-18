from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import signal
from collections.abc import Callable
from typing import cast

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
from zeler_platform_test_support.sheets_dlq_snapshot import (
    FakeBroker,
    FakeMessage,
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
