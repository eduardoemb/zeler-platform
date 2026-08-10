from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from zeler_sheets.consumer import (
    SheetsAmqpConsumerRunner,
    SyncJobsPollerSupervisor,
    run_worker_lifecycles,
)

_FAKES_SPEC = importlib.util.spec_from_file_location(
    "sync_jobs_amqp_fakes", Path(__file__).with_name("_amqp_fakes.py")
)
assert _FAKES_SPEC is not None and _FAKES_SPEC.loader is not None
_FAKES = importlib.util.module_from_spec(_FAKES_SPEC)
_FAKES_SPEC.loader.exec_module(_FAKES)
FakeConnection = _FAKES.FakeConnection


class _Handler:
    async def handle(self, _event: Any) -> str:
        return "appended"


class _Processor:
    def __init__(
        self,
        runner: SheetsAmqpConsumerRunner,
        *,
        failures: int,
        shutdown: asyncio.Event | None = None,
    ) -> None:
        self.runner = runner
        self.failures = failures
        self.shutdown = shutdown
        self.calls = 0
        self.amqp_ready: list[bool] = []

    async def process_once(self) -> str:
        self.calls += 1
        self.amqp_ready.append(self.runner.is_ready)
        if self.calls <= self.failures:
            raise RuntimeError("poll failed")
        if self.shutdown is not None:
            self.shutdown.set()
        return "idle"


@pytest.mark.asyncio
async def test_co_resident_poller_recovers_without_stopping_amqp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def connect(_url: str) -> Any:
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=_Handler())
    shutdown = asyncio.Event()
    processor = _Processor(runner, failures=1, shutdown=shutdown)
    poller = SyncJobsPollerSupervisor(processor, poll_interval=60, restart_delays=(0,))

    await run_worker_lifecycles(runner, poller, shutdown)

    assert processor.calls == 2
    assert processor.amqp_ready == [True, True]
    assert connection.closed is True


@pytest.mark.asyncio
async def test_co_resident_poller_exhaustion_propagates_after_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()

    async def connect(_url: str) -> Any:
        return connection

    monkeypatch.setattr("zeler_sheets.consumer.aio_pika.connect_robust", connect)
    runner = SheetsAmqpConsumerRunner(rabbitmq_url="amqp://unit-test", handler=_Handler())
    processor = _Processor(runner, failures=3)
    poller = SyncJobsPollerSupervisor(processor, restart_delays=(0, 0))

    with pytest.raises(RuntimeError, match="restart budget exhausted"):
        await run_worker_lifecycles(runner, poller, asyncio.Event())

    assert processor.calls == 3
    assert processor.amqp_ready == [True, True, True]
    assert connection.closed is True


@pytest.mark.asyncio
async def test_poller_stop_waits_for_in_flight_work() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingProcessor:
        async def process_once(self) -> str:
            started.set()
            await release.wait()
            return "idle"

    poller = SyncJobsPollerSupervisor(BlockingProcessor(), poll_interval=60)
    await poller.start()
    await started.wait()
    stopping = asyncio.create_task(poller.stop())
    await asyncio.sleep(0)

    assert stopping.done() is False
    release.set()
    await stopping
    assert poller.health_status == "stopped"


@pytest.mark.asyncio
async def test_ordered_shutdown_stops_poller_before_amqp() -> None:
    calls: list[str] = []
    shutdown = asyncio.Event()
    shutdown.set()

    class Runner:
        async def start(self) -> None:
            calls.append("amqp_start")

        async def close(self) -> None:
            calls.append("amqp_close")

    class Poller:
        async def start(self) -> None:
            calls.append("poller_start")

        async def wait(self) -> None:
            await asyncio.Event().wait()

        async def stop(self) -> None:
            calls.append("poller_stop")

    await run_worker_lifecycles(Runner(), Poller(), shutdown)

    assert calls == ["amqp_start", "poller_start", "poller_stop", "amqp_close"]
