from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pymongo import monitoring
from pymongo.errors import ConfigurationError, PyMongoError
from pymongo.uri_parser import parse_uri

from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner

ROOT = Path(__file__).resolve().parents[2]
START, END = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
OPERATIONS = "sheets_stock_time_reconciliation_operations"
PREIMAGES = "sheets_stock_time_reconciliation_preimages"
METRICS = "sheets_stock_time_metrics"
FRESHNESS = "sheets_read_model_freshness"
COLLECTIONS = (OPERATIONS, PREIMAGES, METRICS, FRESHNESS)


class _ConcernListener(monitoring.CommandListener):
    def __init__(self) -> None:
        self.snapshot = False
        self.majority = False

    def started(self, event: Any) -> None:
        command = event.command
        if command.get("startTransaction") is True:
            self.snapshot |= command.get("readConcern", {}).get("level") == "snapshot"
        if event.command_name == "commitTransaction":
            self.majority |= command.get("writeConcern", {}).get("w") == "majority"

    def succeeded(self, event: Any) -> None:
        pass

    def failed(self, event: Any) -> None:
        pass


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
        assert options["validator"] == validator
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
        database_name = f"zeler_stfwd_exec_{uuid4().hex}"
        assert len(database_name) <= 63
        db = client[database_name]
        await _install_contract(db)
        yield db, listener
    finally:
        if database_name is not None:
            await client.drop_database(database_name)
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


def _sealed(seller: str) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    existing = [
        _metric(seller, "delete", 1),
        _metric(seller, "noop", 5, revision="7" * 64),
        _metric(seller, "replace", 1),
    ]
    planned = [
        _metric(seller, "insert", 2),
        _metric(seller, "noop", 5),
        _metric(seller, "replace", 3),
    ]
    source = [{"_id": "rs0-forward-execution-source"}]
    plan = planner._plan_stock_time_actions(
        source_inventory=source, planned_documents=planned, existing_target_rows=existing
    )
    marker = _marker(seller)
    sealed = engine._seal_forward_plan(
        seller_id=seller,
        date_from=START,
        date_to=END,
        source_inventory=source,
        action_plan=plan,
        marker_preimage=marker,
    )
    return sealed, existing, marker


async def _seed(db: Any, existing: list[dict[str, Any]], marker: dict[str, Any]) -> None:
    await db[METRICS].insert_many(existing)
    await db[FRESHNESS].insert_one(marker)


async def _all(collection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = await collection.find({}).sort("_id", 1).to_list(length=None)
    return rows


@pytest.mark.asyncio
async def test_stock_time_forward_commit_mixed_plan_real_rs0(default_mongo_uri: str) -> None:
    async with _database(default_mongo_uri) as (db, listener):
        seller, token = uuid4().hex, "1" * 32
        sealed, existing, old_marker = _sealed(seller)
        await _seed(db, existing, old_marker)
        context = await engine._acquire_forward_operation(db, sealed, token)
        committed = await engine._commit_forward_operation(db, sealed, context)

        operation = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
        expected_preimages = engine._preimage_records(sealed, operation["lease_acquired_at"])
        assert await _all(db[PREIMAGES]) == sorted(expected_preimages, key=lambda row: row["_id"])
        final = {row["_id"]: row for row in await _all(db[METRICS])}
        assert final == {row["_id"]: dict(row) for row in sealed._expected_metric_documents}
        assert final["noop"] == _metric(seller, "noop", 5, revision="7" * 64)
        for mutation in sealed._mutations[:-1]:
            if mutation.action in {"insert", "replace"}:
                assert final[mutation._target_id]["revision"] == mutation.expected_forward_revision
        marker = await db[FRESHNESS].find_one({"_id": old_marker["_id"]})
        assert marker == dict(sealed._desired_marker)
        assert marker["proof_fingerprint"] == engine._metric_proof_fingerprint(list(final.values()))
        assert committed == engine._ForwardOperationContext(
            sealed.operation_id, "committed", 1, token, 1, False
        )
        assert engine._validated_committed_operation(operation, sealed, context) == operation
        assert listener.snapshot and listener.majority


@pytest.mark.asyncio
async def test_stock_time_forward_rejects_external_target_drift_real_rs0(
    default_mongo_uri: str,
) -> None:
    async with _database(default_mongo_uri) as (db, _listener):
        seller = uuid4().hex
        sealed, existing, old_marker = _sealed(seller)
        await _seed(db, existing, old_marker)
        context = await engine._acquire_forward_operation(db, sealed, "2" * 32)
        prepared = await db[OPERATIONS].find_one({"_id": sealed.operation_id})
        await db[METRICS].update_one({"_id": "replace"}, {"$set": {"total_hours": 99}})

        with pytest.raises(engine._ForwardEngineError, match="PREIMAGE_MISMATCH"):
            await engine._commit_forward_operation(db, sealed, context)

        assert await db[OPERATIONS].find_one({"_id": sealed.operation_id}) == prepared
        assert await db[PREIMAGES].count_documents({}) == 0
        assert (await db[METRICS].find_one({"_id": "replace"}))["total_hours"] == 99
        assert await db[FRESHNESS].find_one({"_id": old_marker["_id"]}) == old_marker


@pytest.mark.asyncio
async def test_stock_time_forward_validation_failure_rolls_back_real_rs0(
    default_mongo_uri: str,
) -> None:
    async with _database(default_mongo_uri) as (db, _listener):
        seller = uuid4().hex
        sealed, existing, old_marker = _sealed(seller)
        await _seed(db, existing, old_marker)
        context = await engine._acquire_forward_operation(db, sealed, "3" * 32)
        baseline = {name: await _all(db[name]) for name in COLLECTIONS}
        schema = json.loads(
            (ROOT / f"infra/mongo/schemas/{OPERATIONS}.json").read_text(encoding="utf-8")
        )
        narrowed = deepcopy(schema["$jsonSchema"])
        narrowed["properties"]["state"] = {"enum": ["prepared"]}
        await db.command(
            {"collMod": OPERATIONS},
            validator={"$jsonSchema": narrowed},
            validationLevel="strict",
            validationAction="error",
        )

        with pytest.raises(PyMongoError) as caught:
            await engine._commit_forward_operation(db, sealed, context)

        assert getattr(caught.value, "code", None) == 121
        assert {name: await _all(db[name]) for name in COLLECTIONS} == baseline
