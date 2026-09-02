from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

import zeler_sheets
from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload
from zeler_sheets import _stock_time_forward_engine as engine

_COLLECTIONS = tuple(collection for collection, _ in engine._STOCK_TIME_WRITE_EXPECTED_INDEXES)


def _validator(collection: str) -> dict[str, Any]:
    payload = _validator_payload(ENTITY_SCHEMAS[collection])
    return {"$jsonSchema": payload["$jsonSchema"]}


def _indexes(collection: str) -> list[dict[str, Any]]:
    descriptors = dict(engine._STOCK_TIME_WRITE_EXPECTED_INDEXES)[collection]
    return [
        {"name": "_id_", "key": {"_id": 1}},
        *[
            {"name": item.name, "key": dict(item.keys), **({"unique": True} if item.unique else {})}
            for item in descriptors
        ],
    ]


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def to_list(self, *, length: int | None) -> list[dict[str, Any]]:
        assert length is None
        return deepcopy(self.rows)


class _Collection:
    def __init__(self, indexes: Any) -> None:
        self.indexes: Any = indexes
        self.list_indexes_calls = 0

    def list_indexes(self) -> _Cursor:
        self.list_indexes_calls += 1
        if isinstance(self.indexes, Exception):
            raise self.indexes
        return _Cursor(self.indexes)


class _Client:
    def __init__(self, start_session: Any = None) -> None:
        self.start_session_calls = 0
        self.start_session = start_session if start_session is not None else self._start_session

    def _start_session(self) -> None:
        self.start_session_calls += 1
        raise AssertionError("runtime preflight must never start a session")


class _Database:
    def __init__(self) -> None:
        self.client = _Client()
        self.hello: Any = {
            "isWritablePrimary": True,
            "setName": " rs0 ",
            "logicalSessionTimeoutMinutes": 30,
            "maxWireVersion": 7,
        }
        self.collection_options: dict[str, Any] = {
            name: {
                "validator": _validator(name),
                "validationLevel": "strict",
                "validationAction": "error",
            }
            for name in _COLLECTIONS
        }
        self.collections = {name: _Collection(_indexes(name)) for name in _COLLECTIONS}
        self.command_calls: list[tuple[str, dict[str, Any]]] = []

    async def command(self, command: str, **kwargs: Any) -> Any:
        self.command_calls.append((command, kwargs))
        if command == "hello":
            if isinstance(self.hello, Exception):
                raise self.hello
            return deepcopy(self.hello)
        if command == "listCollections":
            name = kwargs["filter"]["name"]
            options = self.collection_options[name]
            if isinstance(options, Exception):
                raise options
            return {
                "cursor": {
                    "firstBatch": [
                        {"name": name, "type": "collection", "options": deepcopy(options)}
                    ]
                }
            }
        raise AssertionError(f"unexpected read: {command}")

    def __getitem__(self, name: str) -> _Collection:
        return self.collections[name]


@pytest.mark.asyncio
async def test_runtime_preflight_accepts_exact_read_only_inventory_and_is_frozen() -> None:
    db = _Database()

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is True
    assert readiness.issues == ()
    assert [call[0] for call in db.command_calls] == ["hello", *("listCollections",) * 4]
    assert all(
        call[1] == {"filter": {"name": name}}
        for call, name in zip(db.command_calls[1:], _COLLECTIONS, strict=True)
    )
    assert [collection.list_indexes_calls for collection in db.collections.values()] == [1, 1, 1, 1]
    assert db.client.start_session_calls == 0
    with pytest.raises(FrozenInstanceError):
        readiness.ready = False  # type: ignore[misc]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hello", "issue"),
    [
        ({"isWritablePrimary": False}, "HELLO_NOT_WRITABLE_PRIMARY"),
        (
            {
                "isWritablePrimary": True,
                "setName": " ",
                "logicalSessionTimeoutMinutes": 1,
                "maxWireVersion": 7,
            },
            "HELLO_INVALID",
        ),
        (
            {
                "isWritablePrimary": True,
                "setName": "rs0",
                "logicalSessionTimeoutMinutes": True,
                "maxWireVersion": 7,
            },
            "HELLO_INVALID",
        ),
        (
            {
                "isWritablePrimary": True,
                "setName": "rs0",
                "logicalSessionTimeoutMinutes": 1,
                "maxWireVersion": 6,
            },
            "HELLO_INVALID",
        ),
        (
            {
                "isWritablePrimary": True,
                "setName": "rs0",
                "logicalSessionTimeoutMinutes": 1,
                "maxWireVersion": 7,
                "msg": "isdbgrid",
            },
            "HELLO_MONGOS",
        ),
        (RuntimeError("mongodb://user:secret@example.test unavailable"), "HELLO_UNAVAILABLE"),
    ],
)
async def test_runtime_preflight_rejects_hello_and_session_modes(hello: Any, issue: str) -> None:
    db = _Database()
    db.hello = hello

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is False
    assert issue in readiness.issues
    assert db.client.start_session_calls == 0


@pytest.mark.asyncio
async def test_runtime_preflight_rejects_session_and_collection_contract_drift() -> None:
    db = _Database()
    db.client.start_session = None
    db.collection_options[_COLLECTIONS[0]]["validationAction"] = "warn"

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is False
    assert readiness.issues == ("COLLECTION_CONTRACT_INVALID", "SESSION_UNAVAILABLE")


@pytest.mark.asyncio
async def test_runtime_preflight_normalizes_only_index_driver_metadata() -> None:
    db = _Database()
    for collection in db.collections.values():
        for index in collection.indexes:
            index.update({"v": 2, "ns": "database.collection"})

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda index: index.update({"sparse": True}),
        lambda index: index.update({"partialFilterExpression": {"state": "prepared"}}),
        lambda index: index.update({"expireAfterSeconds": 60}),
        lambda index: index.update({"collation": {"locale": "en"}}),
        lambda index: index.update({"hidden": True}),
        lambda index: index.update({"background": True}),
        lambda index: index.update({"unexpected": True}),
    ],
)
async def test_runtime_preflight_rejects_index_drift_and_semantic_options(mutation: Any) -> None:
    db = _Database()
    mutation(db.collections[_COLLECTIONS[0]].indexes[1])
    db.collections[_COLLECTIONS[1]].indexes.reverse()

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is False
    assert readiness.issues == ("INDEX_CONTRACT_INVALID",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "indexes",
    [
        [],
        [*_indexes(_COLLECTIONS[0]), {"name": "extra", "key": {"extra": 1}}],
        [object()],
    ],
)
async def test_runtime_preflight_rejects_missing_extra_and_malformed_indexes(indexes: Any) -> None:
    db = _Database()
    db.collections[_COLLECTIONS[0]].indexes = indexes

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is False
    assert readiness.issues == ("INDEX_CONTRACT_INVALID",)


@pytest.mark.asyncio
async def test_runtime_preflight_aggregates_sanitized_driver_failures() -> None:
    db = _Database()
    for name in _COLLECTIONS:
        db.collection_options[name] = RuntimeError("token=top-secret")
        db.collections[name].indexes = RuntimeError("mongodb://secret-host")

    readiness = await engine._preflight_stock_time_runtime(db)

    assert readiness.ready is False
    assert readiness.issues == ("COLLECTION_READ_FAILED", "INDEX_READ_FAILED")
    assert "secret" not in repr(readiness)
    assert not hasattr(zeler_sheets, "_StockTimeRuntimeReadiness")
    assert not hasattr(zeler_sheets, "_preflight_stock_time_runtime")
