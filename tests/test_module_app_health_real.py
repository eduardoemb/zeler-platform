from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from zeler_autoreply.app import build_app as build_autoreply_app
from zeler_publicador.app import build_app as build_publicador_app
from zeler_repricer.app import build_app as build_repricer_app
from zeler_sheets.app import build_app as build_sheets_app

TEST_RABBITMQ_URL = "amqp://guest:guest@broker:5672/"


class FakeRabbitConnection:
    def __init__(self, *, is_open: bool = True) -> None:
        self.is_open = is_open

    async def close(self) -> None:
        return None


def _connect_ok() -> Callable[..., Awaitable[FakeRabbitConnection]]:
    async def connect(*_args: Any, **_kwargs: Any) -> FakeRabbitConnection:
        return FakeRabbitConnection(is_open=True)

    return connect


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        self.documents[str(filter_doc["_id"])] = dict(replacement)

    async def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        document = self.documents.get(str(filter_doc["_id"]))
        return dict(document) if document is not None else None


class FakeMongoDb:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.module_registry = FakeCollection()
        self.sheets_formula_audit = FakeCollection()

    async def command(self, command: str) -> dict[str, int]:
        self.calls += 1
        assert command == "ping"
        if self.error is not None:
            raise self.error
        return {"ok": 1}

    def __getitem__(self, name: str) -> FakeCollection:
        assert name in ("module_registry", "sheets_formula_audit")
        return self.module_registry if name == "module_registry" else self.sheets_formula_audit


MODULE_BUILDERS: tuple[tuple[str, Callable[..., Any]], ...] = (
    ("repricer", build_repricer_app),
    ("sheets", build_sheets_app),
    ("publicador", build_publicador_app),
    ("autoreply", build_autoreply_app),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("module", "builder"), MODULE_BUILDERS)
async def test_health_200_when_mongo_ok(module: str, builder: Callable[..., Any]) -> None:
    db = FakeMongoDb()
    app = _build_app(builder, db)
    for handler in app.router.on_startup:
        await handler()

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
    for handler in app.router.on_startup:
        await handler()

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
    return builder(mongo_db=db, rabbitmq_url=TEST_RABBITMQ_URL, rabbitmq_connect=_connect_ok())
