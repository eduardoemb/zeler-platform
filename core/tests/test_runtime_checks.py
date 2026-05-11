from __future__ import annotations

import asyncio

import pytest

from zeler_platform_core.runtime.checks import mongo_check_factory


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
