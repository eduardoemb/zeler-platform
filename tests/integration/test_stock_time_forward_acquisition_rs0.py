from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pymongo import monitoring
from pymongo.errors import ConfigurationError, PyMongoError, WriteError
from pymongo.read_concern import ReadConcern
from pymongo.uri_parser import parse_uri
from pymongo.write_concern import WriteConcern

from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner

COLLECTION = "sheets_stock_time_reconciliation_operations"
ROOT = Path(__file__).resolve().parents[2]


class _ConcernListener(monitoring.CommandListener):
    snapshot = False
    majority = False

    def started(self, event: Any) -> None:
        command = event.command
        if command.get("startTransaction") is True:
            self.snapshot |= command.get("readConcern", {}).get("level") == "snapshot"
        if event.command_name == "commitTransaction":
            self.majority |= command.get("writeConcern", {}).get("w") == "majority"

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


def _sealed_plan(seller_id: str) -> Any:
    source = [{"_id": "rs0-acquisition-source"}]
    plan = planner._plan_stock_time_actions(
        source_inventory=source, planned_documents=[], existing_target_rows=[]
    )
    return engine._seal_forward_plan(
        seller_id=seller_id,
        date_from=datetime(2026, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 2, 1, tzinfo=UTC),
        source_inventory=source,
        action_plan=plan,
        marker_preimage=None,
    )


@pytest.mark.asyncio
async def test_stock_time_forward_acquisition_real_rs0(default_mongo_uri: str) -> None:
    motor = pytest.importorskip("motor.motor_asyncio")
    if "MONGO_URI" in os.environ:
        pytest.skip("ambient MONGO_URI rejected before connect; non-acceptance")
    uri = os.environ.get("ZELER_RS0_TEST_URI") or default_mongo_uri
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

        database_name = f"zeler_stfwd_rs0_{uuid4().hex}"
        db = client[database_name]
        schema, indexes = (
            json.loads((ROOT / f"infra/mongo/{kind}/{COLLECTION}.json").read_text(encoding="utf-8"))
            for kind in ("schemas", "indexes")
        )
        validator = {"$jsonSchema": schema["$jsonSchema"]}
        await db.create_collection(
            COLLECTION,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )
        operations = db[COLLECTION]
        for definition in indexes:
            await operations.create_index(list(definition["keys"].items()), **definition["options"])
        listed = await db.command("listCollections", filter={"name": COLLECTION})
        options = listed["cursor"]["firstBatch"][0]["options"]
        assert options["validator"] == validator
        assert (options["validationLevel"], options["validationAction"]) == ("strict", "error")
        installed = await operations.index_information()
        for definition in indexes:
            name = definition["options"]["name"]
            assert installed[name].get("unique") == definition["options"].get("unique")

        sealed = _sealed_plan(uuid4().hex)
        token1, token2, token3 = "1" * 32, "2" * 32, "3" * 32
        before = (await client.admin.command("hello"))["localTime"]
        first = await engine._acquire_forward_operation(db, sealed, token1)
        after = (await client.admin.command("hello"))["localTime"]
        row = await operations.find_one({"_id": sealed.operation_id})
        assert first == engine._ForwardOperationContext(
            sealed.operation_id, "prepared", 1, token1, 1, True
        )
        assert before <= row["lease_acquired_at"].replace(tzinfo=before.tzinfo) <= after
        assert row["heartbeat_at"] == row["lease_acquired_at"]
        assert row["lease_until"] - row["lease_acquired_at"] == timedelta(seconds=120)
        assert await engine._acquire_forward_operation(db, sealed, token1) == first
        with pytest.raises(engine._ForwardEngineError, match="LEASE_CONFLICT"):
            await engine._acquire_forward_operation(db, sealed, token2)

        await operations.update_one(
            {"_id": sealed.operation_id}, [{"$set": {"lease_until": "$$NOW"}}]
        )
        takeover = await engine._acquire_forward_operation(db, sealed, token2)
        assert (takeover.attempt, takeover.fence, takeover.attempt_token) == (2, 2, token2)

        await operations.update_one(
            {"_id": sealed.operation_id}, [{"$set": {"lease_until": "$$NOW"}}]
        )
        gate = asyncio.Event()

        async def contend(token: str) -> Any:
            await gate.wait()
            return await engine._acquire_forward_operation(db, sealed, token)

        tasks = [asyncio.create_task(contend(token)) for token in (token1, token3)]
        gate.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        winners = [
            result for result in results if isinstance(result, engine._ForwardOperationContext)
        ]
        losers = [result for result in results if isinstance(result, BaseException)]
        assert len(winners) == len(losers) == 1
        loser = losers[0]
        if isinstance(loser, engine._ForwardEngineError):
            assert loser.code in {"LEASE_CONFLICT", "TAKEOVER_CONFLICT"}
        else:
            assert isinstance(loser, PyMongoError) and (
                loser.has_error_label("TransientTransactionError")
                or getattr(loser, "code", None) in {112, 244, 251}
            )
        final = await operations.find_one({"_id": sealed.operation_id})
        assert (final["attempt"], final["fence"]) == (3, 3)
        assert final["attempt_token"] == winners[0].attempt_token

        rejected_id = uuid4().hex
        with pytest.raises(WriteError):
            async with await client.start_session() as session:
                async with session.start_transaction(
                    read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
                ):
                    await operations.insert_one({"_id": rejected_id}, session=session)
        assert await operations.count_documents({"_id": rejected_id}) == 0
        assert listener.snapshot and listener.majority
    finally:
        if database_name is not None:
            await client.drop_database(database_name)
        client.close()
