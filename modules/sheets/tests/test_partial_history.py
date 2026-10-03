from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from infra.mongo.apply_validators import _desired_validator, _load_indexes, _load_schema
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.item_projection import item_source_fingerprint
from zeler_sheets.partial_history import advance_partial_history

START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)
OBSERVED = datetime(2026, 7, 2, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


@pytest_asyncio.fixture
async def db() -> Any:
    # Deliberately independent of ambient MONGO_URI: disposable loopback rs0 only.
    client: Any = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?replicaSet=rs0&directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    database = client[f"zeler_history_partial_{uuid4().hex}"]
    try:
        for collection in ("orders", "questions"):
            await database.create_collection(
                collection,
                validator=_desired_validator(
                    _load_schema(ROOT / "infra/mongo/schemas" / f"{collection}.json")
                ),
            )
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


def order(identity: str) -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": 123},
        "buyer": {"id": 321},
        "status": "paid",
        "date_created": "2026-06-04T10:00:00Z",
        "last_updated": "2026-06-04T11:00:00Z",
        "total_amount": 10,
        "tags": ["no_shipping"],
        "order_items": [{"item": {"id": "MLM1"}, "quantity": 1, "unit_price": 10, "sale_fee": 1}],
    }


async def seed(
    db: Any, count: int = 3, read_model: Literal["orders", "questions"] = "orders"
) -> dict[str, Any]:
    for definition in _load_indexes(ROOT / "infra/mongo/indexes/sheets_history_receipts.json"):
        await db.sheets_history_receipts.create_index(
            list(definition["keys"].items()), **definition["options"]
        )
    job = {
        "_id": "job",
        "seller_id": "123",
        "read_model": read_model,
        "history_acquisition_id": "acq",
        "state": "failed",
    }
    head = SheetsHistoryAcquisition(
        _id="acq",
        seller_id="123",
        plan_id="plan",
        job_id="job",
        read_model=read_model,
        scope_id="orders:20260601:20260701" if read_model == "orders" else "seller_scan",
        date_from=START,
        date_to=END,
        created_at=OBSERVED,
        updated_at=OBSERVED,
        phase="hydrate",
        source_total=count,
        discovered_count=count,
    )
    await db.sheets_history_acquisitions.insert_one(head.model_dump(by_alias=True))
    await db.sheets_formula_recovery_jobs.insert_one(job)
    rows = []
    for i in range(1, count + 1):
        source = (
            order(str(i))
            if read_model == "orders"
            else {
                "id": str(i),
                "seller_id": "123",
                "item_id": "MLM1",
                "status": "ANSWERED",
                "date_created": "2026-06-04T10:00:00Z",
            }
        )
        rows.append(
            {
                "_id": f"acq:1:1:membership:{i}",
                "acquisition_id": "acq",
                "seller_id": "123",
                "read_model": read_model,
                "generation": 1,
                "pass_number": 1,
                "kind": "membership",
                "resource_id": str(i),
                "source_payload": source,
                "source_hash": item_source_fingerprint(source),
                "observed_at": OBSERVED,
            }
        )
    await db.sheets_history_receipts.insert_many(rows)
    return job


class Worker:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()
        self.calls: list[str] = []

    async def _order_detail_with_source(
        self,
        seller: str,
        identity: str,
        start: datetime,
        end: datetime,
        *,
        search_row: dict[str, Any],
    ) -> Any:
        self.calls.append(identity)
        if identity in self.missing:
            request = httpx.Request("GET", "https://example.test/private")
            raise httpx.HTTPStatusError(
                "private secret", request=request, response=httpx.Response(404, request=request)
            )
        return SimpleNamespace(
            resource=order(identity),
            source_payload=order(identity),
            unavailable_fields=frozenset(),
            observed_at=OBSERVED,
        )


@pytest.mark.asyncio
async def test_partial_projection_skips_one_missing_and_preserves_closed_exact_range(
    db: Any,
) -> None:
    job = await seed(db)
    before = await db.sheets_history_acquisitions.find_one({"_id": "acq"})
    worker = Worker({"1"})
    result = await advance_partial_history(db=db, worker=worker, job=job, max_details=3)
    assert result["persisted"] == 2
    assert result["pending_count"] == 1
    assert await db.orders.count_documents({"seller_id": "123"}) == 2
    assert await db.sheets_history_acquisitions.find_one({"_id": "acq"}) == before
    repository = FormulaReadModelRepository(db=db)
    available = await repository.find_orders(seller_id="123", date_from=START, date_to=END)
    assert {row["_id"] for row in available} == {"2", "3"}
    with pytest.raises(FormulaDataUnavailableError):
        await repository.require_read_model_reconciled_range(
            seller_id="123",
            read_model="orders",
            date_from=START,
            date_to=END,
            formula="ZELERDATA_ORDENES",
        )
    assert "private secret" not in str(result)
    for _ in range(4):
        saved = await db.sheets_formula_recovery_jobs.find_one({"_id": "job"})
        result = await advance_partial_history(db=db, worker=worker, job=saved)
    assert worker.calls.count("1") == 3
    assert result["state"] == "partial_available"
    assert result["complete"]


@pytest.mark.asyncio
async def test_missing_record_recovery_clears_pending_without_rewriting_valid_inventory(
    db: Any,
) -> None:
    job = await seed(db)
    worker = Worker({"1"})
    await advance_partial_history(db=db, worker=worker, job=job, max_details=3)
    worker.missing.clear()
    saved = await db.sheets_formula_recovery_jobs.find_one({"_id": "job"})
    result = await advance_partial_history(db=db, worker=worker, job=saved)
    assert result["persisted"] == 3
    assert result["pending_count"] == 0
    assert worker.calls.count("2") == 1
    assert result["complete"]


@pytest.mark.asyncio
async def test_partial_cannot_project_other_seller_or_fabricate_enum_completion(db: Any) -> None:
    job = await seed(db)
    await db.sheets_history_acquisitions.update_one({"_id": "acq"}, {"$set": {"next_cursor": 50}})
    worker = Worker()
    result = await advance_partial_history(db=db, worker=worker, job=job)
    assert result["state"] == "pending_dependencies"
    assert not worker.calls
    await db.sheets_history_acquisitions.update_one({"_id": "acq"}, {"$set": {"next_cursor": None}})
    await db.sheets_history_receipts.update_one(
        {"resource_id": "1"}, {"$set": {"source_payload": order("1") | {"seller": {"id": 999}}}}
    )
    result = await advance_partial_history(db=db, worker=worker, job=job)
    assert result["persisted"] == 2
    assert not await db.orders.find_one({"_id": "1"})


@pytest.mark.asyncio
async def test_partial_keeps_independent_healthy_month_proof_unchanged(db: Any) -> None:
    from zeler_sheets.formulas.refresh import reconciled_marker

    job = await seed(db)
    old_start = START.replace(month=5)
    marker = reconciled_marker(
        seller_id="123", read_model="orders", start=old_start, end=START, now=OBSERVED
    )
    await db.sheets_read_model_freshness.insert_one(marker)
    original = await db.sheets_read_model_freshness.find_one({"_id": marker["_id"]})
    await advance_partial_history(db=db, worker=Worker({"1"}), job=job, max_details=3)
    assert await db.sheets_read_model_freshness.find_one({"_id": marker["_id"]}) == original
    await FormulaReadModelRepository(db=db).require_read_model_reconciled_range(
        seller_id="123",
        read_model="orders",
        date_from=old_start,
        date_to=START,
        formula="ZELERDATA_ORDENES",
    )


@pytest.mark.asyncio
async def test_partial_question_without_answer_is_pending_but_valid_answer_is_preserved(
    db: Any,
) -> None:
    job = await seed(db, count=2, read_model="questions")

    class Gateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            identity = path.split("/")[-1].split("?")[0]
            row = {
                "id": identity,
                "seller_id": "123",
                "item_id": "MLM1",
                "text": "private",
                "status": "ANSWERED",
                "from": {"id": 321},
                "date_created": "2026-06-04T10:00:00Z",
            }
            if identity == "2":
                row["answer"] = {
                    "text": "answer",
                    "status": "ACTIVE",
                    "date_created": "2026-06-04T11:00:00Z",
                }
            return row

    result = await advance_partial_history(
        db=db, worker=SimpleNamespace(detail_gateway=Gateway()), job=job, max_details=2
    )
    assert result["pending_count"] == 1
    row = await db.questions.find_one({"_id": "2"})
    assert row["answer"]["text"] == "answer"
    assert not await db.questions.find_one({"_id": "1"})


@pytest.mark.asyncio
async def test_ten_thousand_memberships_one_missing_keeps_9999_usable_without_proof(
    db: Any,
) -> None:
    async with asyncio.timeout(400):
        await seed(db, count=10000)
        worker = Worker({"5000"})
        result: dict[str, Any] = {}
        for _ in range(510):
            saved = await db.sheets_formula_recovery_jobs.find_one({"_id": "job"})
            result = await advance_partial_history(db=db, worker=worker, job=saved, max_details=20)
            if result["complete"]:
                break
        assert result["complete"]
        assert result["persisted"] == 9999
        assert result["pending_count"] == 1
        assert await db.orders.count_documents({"seller_id": "123"}) == 9999
        assert not await db.sheets_read_model_freshness.find_one({"state": "reconciled"})
        repository = FormulaReadModelRepository(db=db)
        available = await repository.find_orders(seller_id="123", date_from=START, date_to=END)
        assert len(available) == 9999
        partial_fees = sum(
            (item["sale_fee"].to_decimal() for row in available for item in row["items"]),
            Decimal(0),
        )
        assert partial_fees == Decimal(9999)
        with pytest.raises(FormulaDataUnavailableError):
            await repository.require_read_model_reconciled_range(
                seller_id="123",
                read_model="orders",
                date_from=START,
                date_to=END,
                formula="ZELERDATA_COMISIONES",
            )
