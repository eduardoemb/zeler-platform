"""T-22 local measurements, not production throughput promises.

Message acquisition uses a controlled round-robin harness, the real paginated
collector and Mongo canonical rows for two annual 10,000-record sources.
Certificate load exercises 37 populated annual intervals per account through the
actual onboarding scheduler. These are separate workloads: this does not establish
10,000-order/claim source acquisition throughput, native Sheets behavior, or
production traffic latency.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import tracemalloc
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    make_certificate,
    publish_certificate,
    select_covering_proofs,
    validate_proof_vector,
)
from zeler_platform_core.devoluciones_readiness import (
    acquire_devoluciones_operation,
    finish_devoluciones_operation,
    guarded_devoluciones_write,
)
from zeler_platform_core.history_onboarding import (
    PLAN_COLLECTION,
    SOURCES,
    admit_history_onboarding,
)
from zeler_platform_core.models import Message
from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
from zeler_sheets.history_onboarding import HistoryOnboardingWorker, PlanBudgetGateway
from zeler_sheets.onboarding_sources import collect_pack_messages

SELLERS = ("99101", "99102")
RECORDS_PER_ACCOUNT = 10000
INTERVALS_PER_ACCOUNT = 37


@pytest_asyncio.fixture
async def capacity_db() -> AsyncIterator[Any]:
    # Do not inherit MONGO_URI: a production environment must never pick the target.
    uri = os.environ.get(
        "ZELER_HISTORY_CAPACITY_URI",
        "mongodb://127.0.0.1:27028/?replicaSet=rs0&directConnection=true",
    )
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "mongodb"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port != 27028
        or parsed.username is not None
        or parsed.password is not None
        or "," in parsed.netloc
    ):
        pytest.fail("Capacity tests require the dedicated credential-free loopback Mongo")
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri, tz_aware=True, serverSelectionTimeoutMS=1500
    )
    try:
        hello = await client.admin.command("hello")
        assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
        name = "zeler_history_capacity_" + uuid4().hex
        database = client[name]
        try:
            definitions = Path(__file__).resolve().parents[3] / "infra/mongo"
            for collection in ("messages", CERTIFICATES):
                validator = json.loads((definitions / "schemas" / f"{collection}.json").read_text())
                validator = {
                    key: value
                    for key, value in validator.items()
                    if key in {"$jsonSchema", "$expr"}
                }
                await database.create_collection(
                    collection,
                    validator=validator,
                    validationLevel="strict",
                    validationAction="error",
                )
                indexes = definitions / "indexes" / f"{collection}.json"
                if indexes.exists():
                    for index in json.loads(indexes.read_text()):
                        await database[collection].create_index(
                            list(index["keys"].items()), **index.get("options", {})
                        )
            yield database
        finally:
            await client.drop_database(name)
    finally:
        client.close()


class AnnualMessages:
    def __init__(self, start: datetime, end: datetime) -> None:
        self.start, self.end = start, end
        self.calls: dict[str, int] = dict.fromkeys(SELLERS, 0)

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        self.calls[seller_id] += 1
        route = urlsplit(path)
        query = parse_qs(route.query)
        assert route.path == f"/messages/packs/{seller_id}/sellers/{seller_id}"
        assert query["mark_as_read"] == ["false"]
        offset, limit = int(query["offset"][0]), int(query["limit"][0])
        await asyncio.sleep(0.001)  # A yielding remote source, not a busy local loop.
        return {
            "paging": {"total": RECORDS_PER_ACCOUNT, "offset": offset},
            "messages": [
                {
                    "id": f"{seller_id}-message-{index}",
                    "pack_id": seller_id,
                    "from": {"user_id": seller_id},
                    "to": {"user_id": "12345"},
                    "text": "Synthetic capacity fixture",
                    "status": "available",
                    "date_created": (
                        self.start + (self.end - self.start) * ((index + 0.5) / RECORDS_PER_ACCOUNT)
                    ).isoformat(),
                }
                for index in range(offset, min(offset + limit, RECORDS_PER_ACCOUNT))
            ],
        }


async def admit_accounts(db: Any, clock: datetime) -> None:
    for seller in SELLERS:
        await admit_history_onboarding(db, seller, now=clock)
        await db.meli_accounts.insert_one(
            {"_id": "account-" + seller, "seller_id": int(seller), "status": "active"}
        )


@pytest.mark.asyncio
async def test_annual_message_volume_progress_budget_and_live_mongo(capacity_db: Any) -> None:
    db = capacity_db
    now = datetime.now(UTC).replace(microsecond=0)
    await admit_accounts(db, now)
    start = (await db[PLAN_COLLECTION].find_one({"_id": SELLERS[0]}))["date_from"]
    source = AnnualMessages(start, now)
    gateways = {seller: PlanBudgetGateway(db, source, seller, "messages") for seller in SELLERS}
    # Exact physical budget, including source failures, not an arbitrary large ceiling.
    await db[PLAN_COLLECTION].update_many(
        {}, {"$set": {"budget.messages.physical_attempts": RECORDS_PER_ACCOUNT // 50}}
    )
    checkpoints: dict[str, Any] = dict.fromkeys(SELLERS)
    peak_backlog = len(SELLERS) * RECORDS_PER_ACCOUNT
    live_latencies: list[float] = []
    stop = asyncio.Event()

    async def live_reads_and_writes() -> None:
        while not stop.is_set():
            before = time.perf_counter()
            await db.capacity_live.update_one({"_id": "live"}, {"$inc": {"turns": 1}}, upsert=True)
            assert await db[PLAN_COLLECTION].count_documents({}) == len(SELLERS)
            live_latencies.append(time.perf_counter() - before)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(live_reads_and_writes())
    tracemalloc.start()
    before = time.perf_counter()
    progressive = False
    try:
        for turn in range(RECORDS_PER_ACCOUNT // 50):
            for seller in SELLERS:
                result = await collect_pack_messages(
                    db=db,
                    gateway=gateways[seller],
                    seller_id=seller,
                    targets=(seller,),
                    start=start,
                    end=now,
                    max_requests=1,
                    checkpoint=checkpoints[seller],
                )
                assert result["requests"] == 1
                assert not result["issue_count"]
                await db[PLAN_COLLECTION].update_one(
                    {"_id": seller},
                    {"$set": {"collector_checkpoints.messages": result["checkpoint"]}},
                )
                # Reconstruct from Mongo instead of using private in-memory progress.
                stored = await db[PLAN_COLLECTION].find_one({"_id": seller})
                checkpoints[seller] = stored["collector_checkpoints"]["messages"]
                assert checkpoints[seller]["persisted"] == (turn + 1) * 50
            assert abs(source.calls[SELLERS[0]] - source.calls[SELLERS[1]]) <= 1
            if turn == 0:
                rows = await db.messages.find({}).to_list(length=100)
                assert len(rows) == 100
                assert all(Message.model_validate(row).text for row in rows)
                assert not any(state["discovery_complete"] for state in checkpoints.values())
                progressive = True
        elapsed = time.perf_counter() - before
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        stop.set()
        await task
    assert progressive
    assert all(state["discovery_complete"] for state in checkpoints.values())
    for seller in SELLERS:
        assert await db.messages.count_documents({"seller_id": seller}) == RECORDS_PER_ACCOUNT
        first = await db.messages.find_one({"_id": f"{seller}-message-0"})
        last = await db.messages.find_one({"_id": f"{seller}-message-9999"})
        assert first and last and first["date_created"] < last["date_created"]
        plan = await db[PLAN_COLLECTION].find_one({"_id": seller})
        assert plan["budget"]["messages"]["consumed"] == source.calls[seller] == 200
        with pytest.raises(ValueError, match="budget"):
            await gateways[seller].fetch_resource(
                seller_id=seller, path=f"/messages/packs/{seller}/sellers/{seller}"
            )
        assert source.calls[seller] == 200
    assert len(live_latencies) >= 10
    # A generous regression deadline, not a production SLO.
    assert max(live_latencies) < 5
    print(
        "T22_MESSAGES "
        + json.dumps(
            {
                "accounts": 2,
                "annual_records": RECORDS_PER_ACCOUNT * len(SELLERS),
                "source_calls": sum(source.calls.values()),
                "elapsed_seconds": round(elapsed, 3),
                "python_peak_bytes": peak_bytes,
                "peak_source_backlog": peak_backlog,
                "final_source_backlog": 0,
                "live_mongo_operations": len(live_latencies),
                "max_live_mongo_seconds": round(max(live_latencies), 4),
            },
            sort_keys=True,
        )
    )


@pytest.mark.asyncio
async def test_order_detail_gateway_charges_physical_response(capacity_db: Any) -> None:
    db = capacity_db
    await admit_accounts(db, datetime.now(UTC))
    calls: list[str] = []

    class Detail:
        async def fetch_resource(self, **kwargs: Any) -> Any:
            raise AssertionError("Order hydration must retain HTTP status and unavailable fields")

        async def request(self, **kwargs: Any) -> httpx.Response:
            calls.append(kwargs["path"])
            return httpx.Response(
                200,
                headers={"X-Zeler-Upstream-Attempts": "1"},
                json={"id": 1},
                request=httpx.Request("GET", "https://fixture.invalid"),
            )

    gateway = PlanBudgetGateway(db, Detail(), SELLERS[0], "orders")
    response = await gateway.request(method="GET", seller_id=SELLERS[0], path="/orders/1")
    assert response.status_code == 200 and response.json()["id"] == 1
    assert calls == ["/orders/1"]
    plan = await db[PLAN_COLLECTION].find_one({"_id": SELLERS[0]})
    assert plan["budget"]["orders"]["consumed"] == plan["total_consumed"] == 1


async def populated_annual_certificates(db: Any, now: datetime) -> dict[str, list[dict[str, Any]]]:
    documents: dict[str, list[dict[str, Any]]] = {}
    for seller in SELLERS:
        plan = await db[PLAN_COLLECTION].find_one({"_id": seller})
        start = plan["date_from"]
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id=seller,
            scope="devoluciones",
            operation_id="capacity-fixture",
            attempt_token=uuid4().hex,
            invalidate_readiness=False,
        )
        documents[seller] = []
        for index in range(INTERVALS_PER_ACCOUNT):
            begin = start + timedelta(days=10 * index)
            end = min(now, begin + timedelta(days=10))
            identity = f"{seller}-{index}"
            await db.claims.insert_one(
                {
                    "_id": "claim-" + identity,
                    "seller_id": seller,
                    "type": "returns",
                    "date_created": begin + timedelta(hours=1),
                    "order_id": "order-" + identity,
                    "item_id": "item-" + identity,
                    "status": "closed",
                    "stage": "claim",
                    "claim_version": 1,
                    "last_updated": now,
                    "return_last_updated": now,
                    "productive": True,
                    "return_id": "return-" + identity,
                    "return_status": "closed",
                    "return_subtype": "return",
                    "returned_quantity": 1,
                    "return_quantity_basis": "v2_return_order",
                }
            )
            await db.orders.insert_one(
                {
                    "_id": "order-" + identity,
                    "seller_id": seller,
                    "items": [{"item_id": "item-" + identity, "quantity": 2, "title": "Fixture"}],
                }
            )
            facts = await current_certificate_facts(db, seller, begin, end)
            assert facts["certified_count"] == 1
            document = (
                make_certificate(
                    seller_id=seller,
                    kind="joint_snapshot",
                    source_identity=identity,
                    source_fingerprint="simulated-source-" + identity,
                    acquisition_fingerprint="simulated-acquisition-" + identity,
                    date_from=begin,
                    date_to=end,
                    acquired_at=now,
                    expected_count=1,
                    current_membership_hash=facts["current_membership_hash"],
                    current_read_model_fingerprint=facts["current_read_model_fingerprint"],
                    coverage_epoch=operation.coverage_epoch,
                    now=now,
                )
                | facts
            )

            async def publish(
                session: Any, document: Any = document, owner: Any = operation
            ) -> None:
                await publish_certificate(db, owner, document, session=session)

            await guarded_devoluciones_write(
                db=db, operation=operation, seller_id=seller, checkpoint={}, writer=publish
            )
            documents[seller].append(document)
        await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
        await db.sheets_devoluciones_operations.update_one(
            {"seller_id": seller}, {"$set": {"coverage_mode": "active"}}
        )
    return documents


@pytest.mark.asyncio
async def test_annual_populated_certificates_renew_in_onboarding_turns(capacity_db: Any) -> None:
    db = capacity_db
    now = datetime.now(UTC).replace(microsecond=0)
    await admit_accounts(db, now)
    documents = await populated_annual_certificates(db, now)
    clock = [now]
    seen: list[tuple[str, str]] = []

    class BlockedSources(HistoryOnboardingWorker):
        async def advance_source(self, plan: Any, source: str, gateway: Any, detail: Any) -> Any:
            # Renewal must be independent of all six source outcomes. This fixture
            # intentionally does not substitute acquisition status for real rows.
            seen.append((plan["seller_id"], source))
            return {"state": "pending", "reason": "simulated_source_unavailable"}

    worker = BlockedSources(db, object(), object(), now=lambda: clock[0])
    durations: list[float] = []
    verification_peaks: list[int] = []
    backlogs: list[int] = []
    for minute in (15, 30, 45, 60):
        clock[0] = now + timedelta(minutes=minute)
        backlogs.append(
            await db[CERTIFICATES].count_documents({"next_check_at": {"$lte": clock[0]}})
        )
        for batch in range(2):
            before = time.perf_counter()
            tracemalloc.start()
            try:
                assert await worker.process_once() == "processed"
                assert await worker.process_once() == "processed"
                verification_peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
            durations.append(time.perf_counter() - before)
            assert seen[-2][0] != seen[-1][0]
            if batch == 0:
                clock[0] += timedelta(seconds=6)
        remaining = await db[CERTIFICATES].count_documents({"next_check_at": {"$lte": clock[0]}})
        print(f"T22_RENEW minute={minute} before={backlogs[-1]} remaining={remaining}")
        assert remaining == 0, (
            "Onboarding must drain 37 due certificates/account without waiting for claims lane"
        )
        for seller in SELLERS:
            for original in documents[seller]:
                current = await db[CERTIFICATES].find_one({"_id": original["_id"]})
                assert current["certified_count"] == 1
                assert current["valid_until"] > clock[0] + timedelta(minutes=29)
                assert current["acquisition_fingerprint"] == original["acquisition_fingerprint"]
                vector = await select_covering_proofs(
                    db, seller, original["date_from"], original["date_to"], clock[0]
                )
                await validate_proof_vector(db, vector, clock[0])
            measurement = (await db.sheets_devoluciones_operations.find_one({"seller_id": seller}))[
                "coverage_renewal"
            ]
            assert measurement["attempted"] <= 20
            assert measurement["slowest_seconds"] < 5
    assert await db.claims.count_documents({}) == 74
    assert await db.orders.count_documents({}) == 74
    assert {seller for seller, _ in seen} == set(SELLERS)
    for seller in SELLERS:
        assert {source for account, source in seen if account == seller} == set(SOURCES)
    print(
        "T22_CERTIFICATES "
        + json.dumps(
            {
                "accounts": 2,
                "certificates": 74,
                "nonempty_claims": 74,
                "nonempty_related_orders": 74,
                "controlled_minutes": 60,
                "max_two_account_batch_seconds": round(max(durations), 3),
                "verification_python_peak_bytes": max(verification_peaks),
                "peak_due_backlog": max(backlogs),
                "final_due_backlog": 0,
            },
            sort_keys=True,
        )
    )
