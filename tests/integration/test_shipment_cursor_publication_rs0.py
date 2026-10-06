"""Prepared real rs0 proof. Root alone executes; absent target is non-acceptance."""

from __future__ import annotations

import copy
import ipaddress
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from pymongo import monitoring
from pymongo.errors import OperationFailure
from pymongo.uri_parser import parse_uri
from test_shipment_recovery_durable_cursor import DB, NOW, SELLER, Gateway

from zeler_sheets.formulas.pacing import HistoryPolicyWaitError
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker


class Listener(monitoring.CommandListener):
    def __init__(self) -> None:
        self.snapshot = self.majority = False

    def started(self, event: Any) -> None:
        self.snapshot |= event.command.get("readConcern", {}).get("level") == "snapshot"
        self.majority |= (
            event.command_name == "commitTransaction"
            and event.command.get("writeConcern", {}).get("w") == "majority"
        )

    def succeeded(self, event: Any) -> None:
        pass

    failed = succeeded


@asynccontextmanager
async def target() -> AsyncIterator[tuple[Any, Listener, dict[str, Any]]]:
    if "MONGO_URI" in os.environ:
        pytest.skip("ambient Mongo rejected; no proof")
    uri = os.environ.get("ZELER_RS0_TEST_URI")
    if not uri:
        pytest.skip("explicit loopback rs0 required; no proof")
    try:
        hosts = parse_uri(uri)["nodelist"]
        if not hosts or not all(ipaddress.ip_address(host).is_loopback for host, _ in hosts):
            pytest.skip("non-loopback rejected before connection")
    except ValueError:
        pytest.skip("invalid target rejected before connection")
    from bson.codec_options import CodecOptions
    from motor.motor_asyncio import AsyncIOMotorClient

    listener = Listener()
    client: Any = AsyncIOMotorClient(uri, event_listeners=[listener], serverSelectionTimeoutMS=2000)
    name = "zeler_shipment_cursor_rs0_" + uuid4().hex
    try:
        hello = await client.admin.command("hello")
        assert hello.get("isWritablePrimary") is True and hello.get("setName") == "rs0"
        assert hello.get("logicalSessionTimeoutMinutes") is not None
        db = client[name].with_options(codec_options=CodecOptions(tz_aware=True))
        job = DB(tuple("123")).job
        yield db, listener, job
    finally:
        await client.drop_database(name)
        client.close()


def worker(db: Any, gateway: Gateway) -> FormulaRecoveryWorker:
    queue = FormulaRecoveryQueue(
        db,
        now=lambda: NOW,
        enabled_models=frozenset({"shipments"}),
        allowed_sellers=frozenset({SELLER}),
    )
    return FormulaRecoveryWorker(db=db, queue=queue, gateway=gateway, detail_gateway=gateway)


@pytest.mark.asyncio
async def test_real_budget_stop_retains_two_units_and_snapshot_majority() -> None:
    async with target() as (db, listener, job):
        await db.sheets_formula_recovery_jobs.insert_one(job)
        gateway = Gateway(9)
        gateway.pause_after = 6
        with pytest.raises(HistoryPolicyWaitError):
            await worker(db, gateway)._shipments(copy.deepcopy(job))
        assert await db.shipments.count_documents({"seller_id": SELLER}) == 2
        stored = await db.sheets_formula_recovery_jobs.find_one({"_id": job["_id"]})
        assert stored["shipment_offset"] == 2 and stored["shipment_ids"] == job["shipment_ids"]
        assert listener.snapshot and listener.majority


@pytest.mark.asyncio
async def test_real_validator_refuses_cursor_before_source_rpc() -> None:
    async with target() as (db, _, job):
        await db.create_collection(
            "sheets_formula_recovery_jobs",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "additionalProperties": False,
                    "properties": {key: {} for key in job},
                }
            },
        )
        await db.sheets_formula_recovery_jobs.insert_one(job)
        gateway = Gateway(9)
        with pytest.raises(OperationFailure):
            await worker(db, gateway)._shipments(copy.deepcopy(job))
        assert gateway.calls == [] and await db.shipments.count_documents({}) == 0


@pytest.mark.asyncio
async def test_real_lost_current_cas_rolls_back_publication_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with target() as (db, _, job):
        await db.sheets_formula_recovery_jobs.insert_one(job)
        instance = worker(db, Gateway(9))
        original = instance.queue.checkpoint_shipment_cursor

        async def lose(
            current: dict[str, Any], *, expected_offset: int, next_offset: int, session: Any
        ) -> bool:
            if expected_offset == 1:
                return False
            return await original(
                current, expected_offset=expected_offset, next_offset=next_offset, session=session
            )

        monkeypatch.setattr(instance.queue, "checkpoint_shipment_cursor", lose)
        with pytest.raises(ValueError):
            await instance._shipments(copy.deepcopy(job))
        assert await db.shipments.count_documents({}) == 1
        assert await db.shipments.find_one({"_id": "2"}) is None
        stored = await db.sheets_formula_recovery_jobs.find_one({"_id": job["_id"]})
        assert stored["shipment_offset"] == 1


@pytest.mark.asyncio
async def test_real_resume_skips_only_persisted_concluded_units() -> None:
    async with target() as (db, _, job):
        await db.sheets_formula_recovery_jobs.insert_one(job)
        gateway = Gateway(9)
        gateway.pause_after = 6
        with pytest.raises(HistoryPolicyWaitError):
            await worker(db, gateway)._shipments(copy.deepcopy(job))
        current = await db.sheets_formula_recovery_jobs.find_one({"_id": job["_id"]})
        gateway.pause_after = None
        await worker(db, gateway)._shipments(current)
        assert gateway.calls[6:] == ["/shipments/3/orders", "/shipments/3", "/shipments/3/costs"]
        assert len(gateway.calls) == gateway.budget == 9
        assert await db.shipments.count_documents({}) == 3
        final = await db.sheets_formula_recovery_jobs.find_one({"_id": job["_id"]})
        assert final["shipment_offset"] == 3 and final["state"] == "completed"
