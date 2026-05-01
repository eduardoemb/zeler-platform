from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from zeler_autoreply.app import build_app as build_autoreply_app
from zeler_fulldock.app import build_app as build_fulldock_app
from zeler_publicador.app import build_app as build_publicador_app
from zeler_repricer.app import build_app as build_repricer_app
from zeler_sheets.app import build_app as build_sheets_app


class FakeCollection:
    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        return None


class FakeMongoDb:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.module_registry = FakeCollection()

    async def command(self, command: str) -> dict[str, int]:
        self.calls += 1
        assert command == "ping"
        if self.error is not None:
            raise self.error
        return {"ok": 1}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "module_registry"
        return self.module_registry


MODULE_BUILDERS: tuple[tuple[str, Callable[..., Any]], ...] = (
    ("repricer", build_repricer_app),
    ("sheets", build_sheets_app),
    ("publicador", build_publicador_app),
    ("autoreply", build_autoreply_app),
    ("fulldock", build_fulldock_app),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "builder"), MODULE_BUILDERS)
async def test_health_200_when_mongo_ok(module: str, builder: Callable[..., Any]) -> None:
    db = FakeMongoDb()
    app = _build_app(builder, db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["module_id"] == module
    assert response.json()["checks"]["mongo"] == {"ok": True, "detail": "mongo_ok"}
    assert db.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "builder"), MODULE_BUILDERS)
async def test_health_503_when_mongo_unreachable(module: str, builder: Callable[..., Any]) -> None:
    db = FakeMongoDb(error=RuntimeError("down"))
    app = _build_app(builder, db)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["module_id"] == module
    assert response.json()["checks"]["mongo"] == {
        "ok": False,
        "detail": "mongo_unreachable: down",
    }


def _build_app(builder: Callable[..., Any], db: FakeMongoDb) -> Any:
    if builder in {build_repricer_app, build_sheets_app}:
        return builder(mongo_db=db, rabbitmq_ready=lambda: True)
    return builder(mongo_db=db)
