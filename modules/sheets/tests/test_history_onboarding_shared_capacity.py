"""Representative shared coordinator load; simulated upstream, actual Mongo/proofs.

Unlike the earlier collector-only throughput case, this executes unmodified
process_once with concurrent scheduler instances and one reserved request pacer.
Order/claim acquisition remains in declared backoff: seeded certificates are
known-complete synthetic acquisition fixtures, not evidence of remote throughput.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.devoluciones_certificates import (
    CERTIFICATES,
    make_certificate,
    publish_certificate,
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
from zeler_sheets.devoluciones_reconciliation import current_certificate_facts
from zeler_sheets.formulas.pacing import PacedMeliGateway, RecoveryRequestPacer
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.history_onboarding import HistoryOnboardingWorker

SELLERS = ("99201", "99202")
MEMBERS_PER_CERTIFICATE = 1000
CERTIFICATES_PER_SELLER = 6
MESSAGES_PER_SELLER = 1000
QUESTIONS_PER_SELLER = 25


@pytest_asyncio.fixture
async def shared_capacity_db() -> AsyncIterator[Any]:
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
        pytest.fail("Shared capacity requires dedicated credential-free loopback Mongo27028")
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri, tz_aware=True, serverSelectionTimeoutMS=1500
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    db = client["zeler_shared_capacity_" + uuid4().hex]
    try:
        definitions = Path(__file__).resolve().parents[3] / "infra/mongo"
        for collection in (
            "messages",
            "claims",
            "orders",
            "questions",
            CERTIFICATES,
            "sheets_devoluciones_operations",
            "sheets_history_acquisitions",
            "sheets_history_receipts",
            "sheets_history_order_ranges",
        ):
            schema = json.loads((definitions / "schemas" / f"{collection}.json").read_text())
            await db.create_collection(
                collection,
                validator={
                    key: value for key, value in schema.items() if key in {"$jsonSchema", "$expr"}
                },
                validationLevel="strict",
                validationAction="error",
            )
            indexes = definitions / "indexes" / f"{collection}.json"
            if indexes.exists():
                for index in json.loads(indexes.read_text()):
                    await db[collection].create_index(
                        list(index["keys"].items()), **index.get("options", {})
                    )
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


async def _seed(db: Any, now: datetime) -> list[dict[str, Any]]:
    documents = []
    for seller in SELLERS:
        await admit_history_onboarding(db, seller, now=now)
        await db.meli_accounts.insert_one(
            {"_id": "account-" + seller, "seller_id": int(seller), "status": "active"}
        )
        # Synthetic canonical item: Full searches require a seller-owned inventory.
        await db.items.insert_one(
            {
                "_id": "MLM" + seller,
                "seller_id": seller,
                "inventory_id": "INVENTORY" + seller,
                "shipping": {"logistic_type": "fulfillment"},
            }
        )
        await db[PLAN_COLLECTION].update_one(
            {"_id": seller},
            {
                "$set": {
                    "onboarding_sources.orders": {
                        "state": "pending",
                        "reason": "simulated_provider_backoff",
                        "next_attempt_at": now + timedelta(days=1),
                    },
                    "onboarding_sources.claims_returns": {
                        "state": "pending",
                        "reason": "simulated_provider_backoff",
                        "next_attempt_at": now + timedelta(days=1),
                    },
                    "budget.messages.physical_attempts": 100,
                    "budget.questions.physical_attempts": 100,
                    "budget.full_withdrawals.physical_attempts": 100,
                    "total_budget": 300,
                }
            },
        )
        operation = await acquire_devoluciones_operation(
            db=db,
            seller_id=seller,
            scope="devoluciones",
            operation_id="capacity-fixture",
            attempt_token=uuid4().hex,
            invalidate_readiness=False,
        )
        for index in range(CERTIFICATES_PER_SELLER):
            start = now - timedelta(days=200 - index * 10)
            end = start + timedelta(days=10)
            claims, orders = [], []
            for member in range(MEMBERS_PER_CERTIFICATE):
                identity = f"{seller}-{index}-{member}"
                created = start + timedelta(seconds=member + 1)
                claims.append(
                    {
                        "_id": "claim-" + identity,
                        "seller_id": seller,
                        "type": "returns",
                        "date_created": created,
                        "order_id": "order-" + identity,
                        "item_id": "MLM1",
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
                        "schema_version": 1,
                    }
                )
                orders.append(
                    {
                        "_id": "order-" + identity,
                        "seller_id": seller,
                        "items": [
                            {
                                "item_id": "MLM1",
                                "qty": 2,
                                "unit_price": 1.0,
                                "title": "Capacity fixture",
                            }
                        ],
                        "status": "paid",
                        "date_created": created,
                        "total_amount": 1.0,
                        "schema_version": 1,
                        "meli_pack_id": seller,
                        "buyer_id": "12345",
                    }
                )
            await db.claims.insert_many(claims)
            await db.orders.insert_many(orders)
            facts = await current_certificate_facts(db, seller, start, end)
            assert facts["certified_count"] == MEMBERS_PER_CERTIFICATE
            identity = f"{seller}-{index}"
            document = (
                make_certificate(
                    seller_id=seller,
                    kind="joint_snapshot",
                    source_identity=identity,
                    source_fingerprint="controlled-source-" + identity,
                    acquisition_fingerprint="controlled-acquisition-" + identity,
                    date_from=start,
                    date_to=end,
                    acquired_at=now,
                    expected_count=MEMBERS_PER_CERTIFICATE,
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
            documents.append(document)
        await finish_devoluciones_operation(db=db, operation=operation, succeeded=True)
        await db.sheets_devoluciones_operations.update_one(
            {"seller_id": seller}, {"$set": {"coverage_mode": "active"}}
        )
    return documents


class _Remote:
    def __init__(self, start: datetime, end: datetime, pacing_clock: list[datetime]) -> None:
        self.start, self.end, self.clock = start, end, pacing_clock
        self.calls: list[tuple[str, str, datetime]] = []

    def question(self, seller: str, index: int) -> dict[str, Any]:
        return {
            "id": int(seller) * 1000 + index,
            "seller_id": int(seller),
            "item_id": "MLM1",
            "from": {"id": 12345},
            "text": "Synthetic shared question capacity",
            "status": "UNANSWERED",
            "date_created": (self.end - timedelta(days=100, seconds=index)).isoformat(),
        }

    async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
        route = urlsplit(path)
        query = parse_qs(route.query)
        self.calls.append((seller_id, route.path, self.clock[0]))
        await asyncio.sleep(0.001)
        if route.path.startswith("/messages/packs/"):
            assert query["mark_as_read"] == ["false"]
            offset, limit = int(query["offset"][0]), int(query["limit"][0])
            return {
                "paging": {"total": MESSAGES_PER_SELLER, "offset": offset},
                "messages": [
                    {
                        "id": f"{seller_id}-message-{index}",
                        "pack_id": seller_id,
                        "from": {"user_id": seller_id},
                        "to": {"user_id": "12345"},
                        "text": "Synthetic shared capacity",
                        "status": "available",
                        "date_created": (
                            self.start
                            + (self.end - self.start) * ((index + 0.5) / MESSAGES_PER_SELLER)
                        ).isoformat(),
                    }
                    for index in range(offset, min(offset + limit, MESSAGES_PER_SELLER))
                ],
            }
        if route.path == "/questions/search":
            return {
                "total": QUESTIONS_PER_SELLER,
                "questions": [
                    self.question(seller_id, index) for index in range(QUESTIONS_PER_SELLER)
                ],
                "scroll_id": None,
            }
        if route.path.startswith("/questions/"):
            index = int(route.path.rsplit("/", 1)[1]) - int(seller_id) * 1000
            assert 0 <= index < QUESTIONS_PER_SELLER
            return self.question(seller_id, index)
        if route.path == "/stock/fulfillment/operations/search":
            return {"results": [], "paging": {"scroll": None}}
        raise AssertionError("Unexpected represented remote source: " + route.path)

    async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
        return await self.fetch_resource_once(**kwargs)


@pytest.mark.asyncio
async def test_real_shared_coordinator_acquires_and_renews_populated_certificates(
    shared_capacity_db: Any,
) -> None:
    db = shared_capacity_db
    initial = datetime.now(UTC).replace(microsecond=0)
    originals = await _seed(db, initial)
    source_clock, pacing_clock = [initial], [initial]
    start = (await db[PLAN_COLLECTION].find_one({"_id": SELLERS[0]}))["date_from"]
    remote = _Remote(start, initial, pacing_clock)
    quota_waits = []

    async def quota_sleep(seconds: float) -> None:
        quota_waits.append(seconds)
        pacing_clock[0] += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    pacer = RecoveryRequestPacer(now=lambda: pacing_clock[0], sleep=quota_sleep)
    discovery = PacedMeliGateway(inner=remote, pacer=pacer, lane="ranges")
    detail = PacedMeliGateway(inner=remote, pacer=pacer, lane="ids")
    workers = [
        HistoryOnboardingWorker(db, discovery, detail, now=lambda: source_clock[0]) for _ in SELLERS
    ]
    live_latencies: list[float] = []
    stop = asyncio.Event()

    async def live_mongo() -> None:
        while not stop.is_set():
            before = time.perf_counter()
            await db.capacity_live.update_one({"_id": "live"}, {"$inc": {"turns": 1}}, upsert=True)
            assert await db[PLAN_COLLECTION].count_documents({}) == len(SELLERS)
            live_latencies.append(time.perf_counter() - before)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(live_mongo())
    renewal_durations, renewal_backlogs, message_counts, question_counts = [], [], [], []
    before = time.perf_counter()
    try:
        # A fresh admitted annual source must publish progressively, not only at completion.
        for turn in range(60):
            assert await asyncio.gather(*(worker.process_once() for worker in workers)) == [
                "processed",
                "processed",
            ]
            count = await db.messages.count_documents({})
            message_counts.append(count)
            question_counts.append(await db.questions.count_documents({}))
            plans = await db[PLAN_COLLECTION].find({}).to_list(length=2)
            assert {plan["source_cursor"] for plan in plans} == {turn + 1}
            source_clock[0] += timedelta(seconds=6)
        assert any(0 < count < 2 * MESSAGES_PER_SELLER for count in message_counts)
        assert message_counts == sorted(message_counts)
        assert message_counts[-1] == 2 * MESSAGES_PER_SELLER
        assert question_counts[-1] == 2 * QUESTIONS_PER_SELLER
        assert any(0 < count < 2 * QUESTIONS_PER_SELLER for count in question_counts)
        assert question_counts == sorted(question_counts)
        for seller in SELLERS:
            assert await db.questions.count_documents({"seller_id": seller}) == QUESTIONS_PER_SELLER
            rows = await db.questions.find({"seller_id": seller}).to_list(
                length=QUESTIONS_PER_SELLER
            )
            assert all(row["text"] and row["status"] == "UNANSWERED" for row in rows)
        acquisition_seconds = time.perf_counter() - before
        repository = FormulaReadModelRepository(db=db)
        for minute in (15, 30, 45, 60):
            source_clock[0] = initial + timedelta(minutes=minute)
            renewal_backlogs.append(
                await db[CERTIFICATES].count_documents({"next_check_at": {"$lte": source_clock[0]}})
            )
            cycle_started = time.perf_counter()
            calls_before_renewal = len(remote.calls)
            # Renewal/acquisition share real turns; never invoke renewal directly.
            for _ in range(6):
                assert await asyncio.gather(*(worker.process_once() for worker in workers)) == [
                    "processed",
                    "processed",
                ]
                source_clock[0] += timedelta(seconds=6)
            renewal_durations.append(time.perf_counter() - cycle_started)
            assert len(remote.calls) > calls_before_renewal
            for seller in SELLERS:
                control = await db.sheets_devoluciones_operations.find_one({"seller_id": seller})
                assert control["coverage_renewal"]["attempted"] == CERTIFICATES_PER_SELLER
                assert control["coverage_renewal"]["slowest_seconds"] < 5
            assert (
                await db[CERTIFICATES].count_documents({"next_check_at": {"$lte": source_clock[0]}})
                == 0
            )
            for original in originals:
                current = await db[CERTIFICATES].find_one({"_id": original["_id"]})
                assert (
                    current["state"] == "reconciled"
                    and current["certified_count"] == MEMBERS_PER_CERTIFICATE
                )
                assert current["valid_until"] > source_clock[0] + timedelta(minutes=28)
                assert current["acquisition_fingerprint"] == original["acquisition_fingerprint"]
                snapshot = await repository.require_devoluciones_reconciled_range(
                    seller_id=original["seller_id"],
                    date_from=original["date_from"],
                    date_to=original["date_to"],
                    now=source_clock[0],
                    formula="ZELERDATA_DEVOLUCIONES",
                )
                assert (
                    len(snapshot.claims or [])
                    == len(snapshot.orders or [])
                    == MEMBERS_PER_CERTIFICATE
                )
                await repository.validate_devoluciones_read_snapshot(
                    seller_id=original["seller_id"],
                    date_from=original["date_from"],
                    date_to=original["date_to"],
                    now=source_clock[0],
                    formula="ZELERDATA_DEVOLUCIONES",
                    snapshot=snapshot,
                )
    finally:
        stop.set()
        await task
    assert len(live_latencies) >= 10 and max(live_latencies) < 5
    assert quota_waits
    assert all(
        (later[2] - earlier[2]).total_seconds() >= 0.333333
        for earlier, later in zip(remote.calls, remote.calls[1:], strict=False)
    )
    calls = Counter(seller for seller, _, _ in remote.calls)
    for seller in SELLERS:
        plan = await db[PLAN_COLLECTION].find_one({"_id": seller})
        assert plan["total_consumed"] + plan.get("incremental_consumed", 0) == calls[seller]
        assert plan["total_consumed"] <= plan["total_budget"]
        assert plan.get("incremental_consumed", 0) <= plan["incremental_policy"]["max_daily_total"]
        assert set(plan["onboarding_sources"]) == set(SOURCES)
        assert plan["certificate_renewal"]["failed"] == 0
        family_counts = Counter(
            "messages"
            if route.startswith("/messages/")
            else "questions"
            if route.startswith("/questions/")
            else "full_withdrawals"
            for account, route, _ in remote.calls
            if account == seller
        )
        for source, count in family_counts.items():
            assert (
                plan["budget"][source]["consumed"]
                + plan.get("incremental_source_consumed", {}).get(source, 0)
                == count
            )
        for source in SOURCES:
            assert plan["budget"][source]["consumed"] <= plan["budget"][source]["physical_attempts"]
            assert (
                plan.get("incremental_source_consumed", {}).get(source, 0)
                <= plan["incremental_policy"]["max_daily_source"]
            )
        routes = {route for account, route, _ in remote.calls if account == seller}
        assert {
            "/questions/search",
            "/stock/fulfillment/operations/search",
            f"/messages/packs/{seller}/sellers/{seller}",
        } <= routes
    assert abs(calls[SELLERS[0]] - calls[SELLERS[1]]) <= 2
    assert max(renewal_durations) < 60  # Regression ceiling, not a production SLO.
    print(
        "T22_SHARED_COORDINATOR "
        + json.dumps(
            {
                "accounts": 2,
                "actual_scheduler_turns": 168,
                "messages": message_counts[-1],
                "questions": question_counts[-1],
                "progressive_question_counts": sorted(set(question_counts)),
                "progressive_message_counts": sorted(set(message_counts)),
                "certificates": len(originals),
                "members_per_certificate": MEMBERS_PER_CERTIFICATE,
                "claim_members": len(originals) * MEMBERS_PER_CERTIFICATE,
                "related_orders": len(originals) * MEMBERS_PER_CERTIFICATE,
                "physical_calls_by_account": dict(calls),
                "acquisition_seconds": round(acquisition_seconds, 3),
                "controlled_minutes": 60,
                "due_backlogs": renewal_backlogs,
                "final_due_backlog": 0,
                "max_six_turn_renewal_and_source_cycle_seconds": round(max(renewal_durations), 3),
                "live_mongo_operations": len(live_latencies),
                "max_live_mongo_seconds": round(max(live_latencies), 4),
                "simulated_quota_wait_seconds": round(sum(quota_waits), 3),
            },
            sort_keys=True,
        )
    )
