from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import aio_pika
import pytest
from yarl import URL

from zeler_gateway.routes import health


class Connection(aio_pika.RobustConnection):
    """Real installed state/events, with network establishment controlled locally."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.close_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.failure: Exception | None = None

    async def connect(self, timeout: Any = None) -> None:
        self.started.set()
        await self.release.wait()
        if self.failure is not None:
            raise self.failure
        self.connected.set()

    async def close(self, exc: Any = asyncio.CancelledError) -> None:
        self.close_count += 1
        await super().close(exc)
        if not self._closed.done():
            self._closed.set_result(True)


@pytest.fixture(autouse=True)
def local_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    async def connect(url: str, **kwargs: Any) -> Any:
        factory = kwargs.pop("connection_class", aio_pika.RobustConnection)
        rabbit = factory(URL(url), heartbeat=kwargs.get("heartbeat"))
        await rabbit.connect(timeout=kwargs.get("timeout"))
        return rabbit

    monkeypatch.setattr(aio_pika, "connect_robust", connect)


@pytest.mark.asyncio
async def test_ten_probes_reuse_installed_robust_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    rabbit = Connection(URL("amqp://localhost"))
    rabbit.connected.set()
    assert not hasattr(rabbit, "is_open") and rabbit.is_closed is False
    state = SimpleNamespace(rabbit=rabbit)

    async def unexpected_connect(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Connected readiness must not create another connection")

    monkeypatch.setattr(aio_pika, "connect_robust", unexpected_connect)
    try:
        assert [await health._check_rabbit(state, 0.1, "amqp://localhost") for _ in range(10)] == [
            "ok"
        ] * 10
    finally:
        await rabbit.close()


@pytest.mark.asyncio
async def test_concurrent_missing_connection_has_one_owned_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Connection] = []

    def factory(*args: Any, **kwargs: Any) -> Connection:
        rabbit = Connection(*args, **kwargs)
        rabbit.release.set()
        created.append(rabbit)
        return rabbit

    monkeypatch.setattr(aio_pika, "RobustConnection", factory)
    state = SimpleNamespace(rabbit=None)
    baseline = asyncio.all_tasks()
    try:
        results = await asyncio.gather(
            *(health._check_rabbit(state, 0.2, "amqp://localhost") for _ in range(20))
        )
        assert results == ["ok"] * 20
        assert len(created) == 1 and state.rabbit is created[0]
    finally:
        for rabbit in created:
            await rabbit.close()
    assert asyncio.all_tasks() == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("reconnect", [True, False])
async def test_existing_disconnect_waits_without_replacement(
    reconnect: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    rabbit = Connection(URL("amqp://localhost"))
    state = SimpleNamespace(rabbit=rabbit)

    async def unexpected_connect(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Robust reconnect belongs to the existing connection")

    monkeypatch.setattr(aio_pika, "connect_robust", unexpected_connect)
    probe = asyncio.create_task(health._check_rabbit(state, 0.03, "amqp://localhost"))
    await asyncio.sleep(0)
    if reconnect:
        rabbit.connected.set()
    assert await probe == ("ok" if reconnect else "fail")
    assert state.rabbit is rabbit and rabbit.close_count == 0
    await rabbit.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["source", "dns", "timeout", "cancel"])
async def test_failed_creation_closes_unpublished_connection(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Connection] = []

    def factory(*args: Any, **kwargs: Any) -> Connection:
        rabbit = Connection(*args, **kwargs)
        if failure in {"source", "dns"}:
            rabbit.failure = OSError("sanitized") if failure == "dns" else RuntimeError("sanitized")
            rabbit.release.set()
        created.append(rabbit)
        return rabbit

    monkeypatch.setattr(aio_pika, "RobustConnection", factory)
    state = SimpleNamespace(rabbit=None)
    baseline = asyncio.all_tasks()
    probe = asyncio.create_task(health._check_rabbit(state, 0.03, "amqp://localhost"))
    # The implementation must retain the factory product before awaiting connect.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    if failure == "cancel":
        probe.cancel()
        with pytest.raises(asyncio.CancelledError):
            await probe
    else:
        assert await probe == "fail"
    assert len(created) == 1 and created[0].close_count == 1
    assert state.rabbit is None
    assert asyncio.all_tasks() == baseline


@pytest.mark.asyncio
async def test_shutdown_serializes_with_creation_and_prevents_new_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Connection] = []

    def factory(*args: Any, **kwargs: Any) -> Connection:
        rabbit = Connection(*args, **kwargs)
        created.append(rabbit)
        return rabbit

    monkeypatch.setattr(aio_pika, "RobustConnection", factory)
    state = SimpleNamespace(rabbit=None)
    baseline = asyncio.all_tasks()
    probe = asyncio.create_task(health._check_rabbit(state, 0.2, "amqp://localhost"))
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(health.close_owned_rabbit(state))
    await asyncio.sleep(0)
    assert state.rabbit_shutdown
    created[0].release.set()
    assert await probe == "fail"
    await shutdown
    assert created[0].close_count == 1 and state.rabbit is None
    assert await health._check_rabbit(state, 0.2, "amqp://localhost") == "fail"
    assert len(created) == 1 and asyncio.all_tasks() == baseline


@pytest.mark.asyncio
async def test_cancelled_lock_waiter_does_not_cancel_existing_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rabbit = Connection(URL("amqp://localhost"))
    state = SimpleNamespace(rabbit=rabbit)
    owner = asyncio.create_task(health._check_rabbit(state, 0.2, "amqp://localhost"))
    await asyncio.sleep(0)
    waiter = asyncio.create_task(health._check_rabbit(state, 0.2, "amqp://localhost"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    rabbit.connected.set()
    assert await owner == "ok"
    assert rabbit.close_count == 0 and state.rabbit is rabbit
    await health.close_owned_rabbit(state)


@pytest.mark.asyncio
async def test_failed_startup_cancellation_closes_mongo_and_owned_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI

    import zeler_gateway.app as app_module

    closed: list[str] = []
    candidates: list[Connection] = []

    class Mongo:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __getitem__(self, name: str) -> object:
            return object()

        def close(self) -> None:
            closed.append("mongo")

    def factory(*args: Any, **kwargs: Any) -> Connection:
        rabbit = Connection(*args, **kwargs)
        candidates.append(rabbit)
        return rabbit

    monkeypatch.setenv("RABBITMQ_URL", "amqp://localhost")
    monkeypatch.setattr(aio_pika, "RobustConnection", factory)
    monkeypatch.setattr(app_module, "AsyncIOMotorClient", Mongo)
    app = FastAPI()
    context = app_module.lifespan(app)
    startup = asyncio.create_task(context.__aenter__())
    await asyncio.sleep(0)
    assert app.state.ready is False
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert candidates[0].close_count == 1
    assert closed == ["mongo"] and app.state.rabbit is None


@pytest.mark.asyncio
async def test_closed_connection_replacement_releases_retained_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old: Any = Connection(URL("amqp://localhost"))
    await old.close()
    aborted: list[bool] = []
    old._readiness_transport_owner = SimpleNamespace(abort=lambda: aborted.append(True))
    state = SimpleNamespace(rabbit=old)

    def factory(*args: Any, **kwargs: Any) -> Connection:
        connection = Connection(*args, **kwargs)
        connection.release.set()
        return connection

    monkeypatch.setattr(aio_pika, "RobustConnection", factory)
    try:
        assert await health._check_rabbit(state, 0.2, "amqp://localhost") == "ok"
        assert aborted == [True]
    finally:
        await health.close_owned_rabbit(state)


@pytest.mark.asyncio
async def test_failed_creation_budget_includes_bounded_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = asyncio.Event()

    class SlowClose(Connection):
        async def close(self, exc: Any = asyncio.CancelledError) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await super().close(exc)
                closed.set()

    monkeypatch.setattr(aio_pika, "RobustConnection", SlowClose)
    state = SimpleNamespace(rabbit=None)
    baseline = asyncio.all_tasks()
    started = asyncio.get_running_loop().time()
    assert await health._check_rabbit(state, 0.02, "amqp://localhost") == "fail"
    elapsed = asyncio.get_running_loop().time() - started
    assert 0.1 <= elapsed < 0.22  # operation .02 plus existing aggregate grace .2
    assert closed.is_set() and state.rabbit is None
    assert asyncio.all_tasks() == baseline
