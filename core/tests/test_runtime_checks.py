from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from zeler_platform_core.runtime.checks import mongo_check_factory, rabbitmq_check_factory


class FakeAdmin:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def command(self, command: str) -> dict[str, int]:
        self.calls += 1
        assert command == "ping"
        if self.error is not None:
            raise self.error
        return {"ok": 1}


class FakeMotorClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.admin = FakeAdmin(error=error)


class FakeMotorDatabase:
    def __init__(self) -> None:
        self.client = FakeMotorClient()
        self.admin = object()


@pytest.mark.asyncio
async def test_mongo_check_ok() -> None:
    client = FakeMotorClient()
    check = mongo_check_factory(client, clock=lambda: 100.0)

    assert await check() == (True, "mongo_ok")
    assert client.admin.calls == 1


@pytest.mark.asyncio
async def test_mongo_check_uses_database_client_admin_for_motor_database() -> None:
    database = FakeMotorDatabase()
    check = mongo_check_factory(database, clock=lambda: 100.0)

    assert await check() == (True, "mongo_ok")
    assert database.client.admin.calls == 1


@pytest.mark.asyncio
async def test_mongo_check_caches_within_ttl() -> None:
    now = 100.0
    client = FakeMotorClient()
    check = mongo_check_factory(client, ttl_seconds=5, clock=lambda: now)

    first = await check()
    second = await check()

    assert first == (True, "mongo_ok")
    assert second == (True, "mongo_ok")
    assert client.admin.calls == 1


@pytest.mark.asyncio
async def test_mongo_check_error_on_timeout() -> None:
    client = FakeMotorClient(error=TimeoutError("slow ping"))
    check = mongo_check_factory(client, clock=lambda: 100.0)

    ok, detail = await check()

    assert ok is False
    assert detail == "mongo_unreachable: slow ping"
    assert client.admin.calls == 1


@pytest.mark.asyncio
async def test_mongo_check_enforces_probe_timeout() -> None:
    class SlowAdmin:
        async def command(self, command: str) -> dict[str, int]:
            await asyncio.sleep(10)
            return {"ok": 1}

    class SlowClient:
        admin = SlowAdmin()

    check = mongo_check_factory(SlowClient(), clock=lambda: 100.0, timeout_seconds=0.001)

    ok, detail = await check()

    assert ok is False
    assert detail.startswith("mongo_unreachable:")


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _connect_ok() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return FakeRabbitConnection(is_open=True)

    return connect


def _connect_unreachable() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        raise RuntimeError("amqp://guest:guest@secret-broker:5672 leaked")

    return connect


def _url_source(url: str | None) -> Callable[[], str | None]:
    return lambda: url


@pytest.mark.asyncio
async def test_rabbitmq_check_ok_when_broker_reachable() -> None:
    returned = FakeRabbitConnection(is_open=True)

    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return returned

    check = rabbitmq_check_factory(
        _url_source("amqp://guest:guest@broker:5672/"),
        clock=lambda: 100.0,
        connect=connect,
    )

    ok, detail = await check()

    assert ok is True
    assert detail == "rabbitmq_ok"
    assert returned.closed is True


@pytest.mark.asyncio
async def test_rabbitmq_check_fails_closed_without_url() -> None:
    connect_calls = 0

    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        nonlocal connect_calls
        connect_calls += 1
        return FakeRabbitConnection(is_open=True)

    check = rabbitmq_check_factory(
        _url_source(None),
        clock=lambda: 100.0,
        connect=connect,
    )

    ok, detail = await check()

    assert ok is False
    assert detail == "rabbitmq_url_unconfigured"
    assert connect_calls == 0


@pytest.mark.asyncio
async def test_rabbitmq_check_fails_when_broker_unreachable_without_leaking_url() -> None:
    check = rabbitmq_check_factory(
        _url_source("amqp://guest:guest@broker:5672/"),
        clock=lambda: 100.0,
        connect=_connect_unreachable(),
    )

    ok, detail = await check()

    assert ok is False
    assert detail == "rabbitmq_unreachable"
    assert "amqp://" not in detail
    assert "secret-broker" not in detail


@pytest.mark.asyncio
async def test_rabbitmq_check_fails_when_connection_is_closed() -> None:
    check = rabbitmq_check_factory(
        _url_source("amqp://guest:guest@broker:5672/"),
        clock=lambda: 100.0,
        connect=lambda *_args, **_kwargs: _closed_connection(),
    )

    ok, detail = await check()

    assert ok is False
    assert detail == "rabbitmq_unreachable"


async def _closed_connection() -> FakeRabbitConnection:
    return FakeRabbitConnection(is_open=False)


@pytest.mark.asyncio
async def test_rabbitmq_check_caches_within_ttl() -> None:
    now = 100.0
    connect_calls = 0

    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        nonlocal connect_calls
        connect_calls += 1
        return FakeRabbitConnection(is_open=True)

    check = rabbitmq_check_factory(
        _url_source("amqp://guest:guest@broker:5672/"),
        ttl_seconds=5,
        clock=lambda: now,
        connect=connect,
    )

    first = await check()
    second = await check()

    assert first == (True, "rabbitmq_ok")
    assert second == (True, "rabbitmq_ok")
    assert connect_calls == 1


@pytest.mark.asyncio
async def test_rabbitmq_check_enforces_probe_timeout() -> None:
    async def slow_connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        await asyncio.sleep(10)
        return FakeRabbitConnection(is_open=True)

    check = rabbitmq_check_factory(
        _url_source("amqp://guest:guest@broker:5672/"),
        clock=lambda: 100.0,
        timeout_seconds=0.001,
        connect=slow_connect,
    )

    ok, detail = await check()

    assert ok is False
    assert detail == "rabbitmq_unreachable"
