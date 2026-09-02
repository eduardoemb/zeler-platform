from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from pymongo import monitoring
from pymongo.errors import ConfigurationError, PyMongoError
from pymongo.uri_parser import parse_uri

from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner
from zeler_sheets.source_gated_read_model_writers import _canonical_bson_bytes

ROOT = Path(__file__).resolve().parents[2]
START, END = datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)
OPERATIONS = "sheets_stock_time_reconciliation_operations"
PREIMAGES = "sheets_stock_time_reconciliation_preimages"
METRICS = "sheets_stock_time_metrics"
FRESHNESS = "sheets_read_model_freshness"
COLLECTIONS = (OPERATIONS, PREIMAGES, METRICS, FRESHNESS)


class _ConcernListener(monitoring.CommandListener):
    def __init__(self) -> None:
        self.snapshots = 0
        self.majority_commits = 0

    def started(self, event: Any) -> None:
        if (
            event.command.get("startTransaction") is True
            and event.command.get("readConcern", {}).get("level") == "snapshot"
        ):
            self.snapshots += 1
        if (
            event.command_name == "commitTransaction"
            and event.command.get("writeConcern", {}).get("w") == "majority"
        ):
            self.majority_commits += 1

    def succeeded(self, event: Any) -> None:
        pass

    failed = succeeded


def _loopback_uri(uri: str) -> bool:
    try:
        hosts = parse_uri(uri, validate=True).get("nodelist", [])
    except (ConfigurationError, ValueError):
        return False
    if not hosts:
        return False
    for host, _port in hosts:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if host.lower() != "localhost" and not loopback:
            return False
    return True


def _bson_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[bytes, ...]:
    return tuple(_canonical_bson_bytes(row) for row in sorted(rows, key=lambda row: row["_id"]))


async def _all(collection: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], await collection.find({}).sort("_id", 1).to_list(length=None))


async def _install_contract(db: Any) -> None:
    for name in COLLECTIONS:
        schema = json.loads((ROOT / f"infra/mongo/schemas/{name}.json").read_text(encoding="utf-8"))
        indexes = json.loads(
            (ROOT / f"infra/mongo/indexes/{name}.json").read_text(encoding="utf-8")
        )
        validator = {"$jsonSchema": schema["$jsonSchema"]}
        await db.create_collection(
            name, validator=validator, validationLevel="strict", validationAction="error"
        )
        collection = db[name]
        for definition in indexes:
            await collection.create_index(list(definition["keys"].items()), **definition["options"])
        listed = await db.command("listCollections", filter={"name": name})
        options = listed["cursor"]["firstBatch"][0]["options"]
        assert _canonical_bson_bytes(options["validator"]) == _canonical_bson_bytes(validator)
        assert (options["validationLevel"], options["validationAction"]) == ("strict", "error")
        installed = await collection.index_information()
        assert set(installed) == {"_id_", *(item["options"]["name"] for item in indexes)}
        for definition in indexes:
            info = installed[definition["options"]["name"]]
            assert info["key"] == list(definition["keys"].items())
            assert bool(info.get("unique", False)) is bool(
                definition["options"].get("unique", False)
            )


@asynccontextmanager
async def _database(default_uri: str) -> AsyncIterator[tuple[Any, _ConcernListener]]:
    motor = pytest.importorskip("motor.motor_asyncio")
    if "MONGO_URI" in os.environ:
        pytest.skip("ambient MONGO_URI rejected before connect; non-acceptance")
    # The optional ZELER_RS0_TEST_URI or default fixture must target local rs0-dev only.
    uri = os.environ.get("ZELER_RS0_TEST_URI") or default_uri
    if not _loopback_uri(uri):
        pytest.skip("non-loopback MongoDB target rejected before connect; non-acceptance")
    listener = _ConcernListener()
    client = motor.AsyncIOMotorClient(
        uri,
        event_listeners=[listener],
        serverSelectionTimeoutMS=750,
        connectTimeoutMS=750,
        tz_aware=True,
    )
    database_name: str | None = None
    try:
        try:
            hello = await client.admin.command("hello")
        except PyMongoError as exc:
            pytest.skip(f"local rs0 unavailable ({exc.__class__.__name__}); non-acceptance")
        if not (
            hello.get("setName")
            and hello.get("isWritablePrimary") is True
            and hello.get("logicalSessionTimeoutMinutes") is not None
        ):
            pytest.skip("local MongoDB is not a writable session-capable rs0; non-acceptance")
        try:
            async with await client.start_session():
                pass
        except PyMongoError as exc:
            pytest.skip(
                f"local rs0 sessions unavailable ({exc.__class__.__name__}); non-acceptance"
            )
        database_name = f"zeler_strb_rs0_{uuid4().hex}"
        assert len(database_name) <= 63
        db = client[database_name]
        await _install_contract(db)
        yield db, listener
    finally:
        try:
            if database_name is not None:
                await client.drop_database(database_name)
        finally:
            client.close()


def _metric(seller: str, target: str, hours: int, *, revision: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "_id": target,
        "seller_id": seller,
        "item_id": target,
        "date_from": START,
        "date_to": END,
        "total_hours": hours,
        "source": "legacy_history_import",
        "history_basis": "legacy_imported",
        "coverage_basis": "legacy_imported",
        "schema_version": 1,
    }
    if revision is not None:
        row["revision"] = revision
    return row


def _marker(seller: str) -> dict[str, Any]:
    return {
        "_id": f"{seller}:stock_time_metrics",
        "seller_id": seller,
        "read_model": "stock_time_metrics",
        "state": "stale",
        "fresh_until": START,
        "updated_at": START,
        "revision": "8" * 64,
        "schema_version": 1,
    }


def _sealed(seller: str, marker: Mapping[str, Any] | None) -> tuple[Any, list[dict[str, Any]]]:
    original = [
        _metric(seller, "delete", 1),
        _metric(seller, "noop", 5, revision="7" * 64),
        _metric(seller, "replace", 1),
    ]
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "rs0-rollback-source"}],
        planned_documents=[
            _metric(seller, "insert", 2),
            _metric(seller, "noop", 5),
            _metric(seller, "replace", 3),
        ],
        existing_target_rows=original,
    )
    return (
        engine._seal_forward_plan(
            seller_id=seller,
            date_from=START,
            date_to=END,
            source_inventory=[{"_id": "rs0-rollback-source"}],
            action_plan=plan,
            marker_preimage=marker,
        ),
        original,
    )


async def _forward(
    db: Any, sealed: Any, original: Sequence[Mapping[str, Any]], marker: Any
) -> None:
    await db[METRICS].insert_many([dict(row) for row in original])
    if marker is not None:
        await db[FRESHNESS].insert_one(dict(marker))
    context = await engine._acquire_forward_operation(db, sealed, "1" * 32)
    await engine._commit_forward_operation(db, sealed, context)


@pytest.mark.asyncio
async def test_stock_time_forward_rollback_restores_exact_original_real_rs0(
    default_mongo_uri: str,
) -> None:
    for marker_present in (False, True):
        async with _database(default_mongo_uri) as (db, listener):
            seller = uuid4().hex
            original_marker = _marker(seller) if marker_present else None
            sealed, original = _sealed(seller, original_marker)
            await _forward(db, sealed, original, original_marker)
            committed = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
            retained_preimages = await _all(db[PREIMAGES])
            before = (await db.client.admin.command("hello"))["localTime"].replace(tzinfo=UTC)
            assert await engine._rollback_forward_operation(
                db, sealed.operation_id
            ) == engine._ForwardRollbackPlan(sealed.operation_id, "rolled_back", ())
            after = (await db.client.admin.command("hello"))["localTime"].replace(tzinfo=UTC)
            operation = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
            assert _bson_rows(await _all(db[METRICS])) == _bson_rows(original)
            assert _bson_rows(await _all(db[PREIMAGES])) == _bson_rows(retained_preimages)
            expected_marker = [] if original_marker is None else [original_marker]
            assert _bson_rows(await _all(db[FRESHNESS])) == _bson_rows(expected_marker)
            mutable = {
                "state",
                "heartbeat_at",
                "updated_at",
                "terminal_at",
                "lease_until",
                "error_code",
            }
            assert operation["state"] == "rolled_back"
            assert operation["committed_at"] == committed["committed_at"]
            assert all(operation[key] == committed[key] for key in set(committed) - mutable)
            terminal = operation["terminal_at"]
            assert (
                terminal
                == operation["heartbeat_at"]
                == operation["updated_at"]
                == operation["lease_until"]
            )
            assert before <= terminal <= after
            assert listener.snapshots >= 2 and listener.majority_commits >= 2


@pytest.mark.asyncio
async def test_stock_time_forward_rollback_drift_is_terminal_and_noncompensating_real_rs0(
    default_mongo_uri: str,
) -> None:
    async with _database(default_mongo_uri) as (db, _listener):
        seller = uuid4().hex
        original_marker = _marker(seller)
        sealed, original = _sealed(seller, original_marker)
        await _forward(db, sealed, original, original_marker)
        preimages = await _all(db[PREIMAGES])
        owned_marker = await db[FRESHNESS].find_one({"_id": original_marker["_id"]})
        await db[METRICS].update_one({"_id": "replace"}, {"$set": {"total_hours": 99}})
        intentional_drift = await _all(db[METRICS])

        with pytest.raises(engine._ForwardEngineError, match="^ROLLBACK_BLOCKED$"):
            await engine._rollback_forward_operation(db, sealed.operation_id)

        operation = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
        marker = await db[FRESHNESS].find_one({"_id": original_marker["_id"]})
        assert (
            operation["state"] == "rollback_blocked" and operation["error_code"] == "TARGET_DRIFT"
        )
        assert _bson_rows(await _all(db[METRICS])) == _bson_rows(intentional_drift)
        assert _bson_rows(await _all(db[PREIMAGES])) == _bson_rows(preimages)
        assert _bson_rows([marker]) == _bson_rows(
            [{**owned_marker, "state": "stale", "updated_at": operation["updated_at"]}]
        )
        assert marker["source"] == owned_marker["source"]
        assert marker["coverage_basis"] == owned_marker["coverage_basis"]


@pytest.mark.asyncio
async def test_stock_time_forward_rollback_validator_failure_aborts_all_inverses_real_rs0(
    default_mongo_uri: str,
) -> None:
    async with _database(default_mongo_uri) as (db, _listener):
        seller = uuid4().hex
        original_marker = _marker(seller)
        sealed, original = _sealed(seller, original_marker)
        await _forward(db, sealed, original, original_marker)
        forward_snapshot = {name: _bson_rows(await _all(db[name])) for name in COLLECTIONS}
        schema = json.loads(
            (ROOT / f"infra/mongo/schemas/{OPERATIONS}.json").read_text(encoding="utf-8")
        )
        narrowed = deepcopy(schema["$jsonSchema"])
        narrowed["properties"]["state"] = {"enum": ["committed"]}
        await db.command(
            {
                "collMod": OPERATIONS,
                "validator": {"$jsonSchema": narrowed},
                "validationLevel": "strict",
                "validationAction": "error",
            }
        )

        with pytest.raises(PyMongoError) as caught:
            await engine._rollback_forward_operation(db, sealed.operation_id)

        assert getattr(caught.value, "code", None) == 121
        assert {name: _bson_rows(await _all(db[name])) for name in COLLECTIONS} == forward_snapshot
        operation = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
        marker = await db[FRESHNESS].find_one({"_id": original_marker["_id"]})
        assert operation["state"] == "committed" and marker["state"] == "reconciled"
