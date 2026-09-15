from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.formulas.pacing import LocalQuotaTimeoutError
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryLimitError
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_orders import HistoryOrdersProducer
from zeler_sheets.item_projection import item_source_fingerprint

NOW = datetime(2026, 9, 15, 12, 30, tzinfo=UTC)


def order(identity: int, **changes: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": 82453304},
        "date_created": (NOW - timedelta(days=1)).isoformat(),
        "date_last_updated": NOW.isoformat(),
        "order_items": [{"quantity": 1}],
        "tags": ["no_shipping"],
        **changes,
    }


@dataclass
class Gateway:
    pages: dict[int, dict[str, Any]] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    detail_headers: dict[str, str] = field(default_factory=dict)
    on_request: Callable[[str], None] | None = None
    on_search: Callable[[dict[str, list[str]]], dict[str, Any]] | None = None

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == "82453304"
        self.calls.append(path)
        if "search" in self.failures:
            raise self.failures.pop("search")
        offset = int(parse_qs(urlsplit(path).query)["offset"][0])
        if self.on_search is not None:
            return self.on_search(parse_qs(urlsplit(path).query))
        return self.pages[offset]

    async def request(
        self,
        *,
        method: str,
        seller_id: str,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        assert method == "GET" and seller_id == "82453304"
        self.calls.append(path)
        if self.on_request is not None:
            self.on_request(path)
        if path in self.failures:
            raise self.failures.pop(path)
        return httpx.Response(
            206 if self.detail_headers else 200,
            headers=self.detail_headers,
            json=self.details[path],
            request=httpx.Request(method, "https://gateway.invalid" + path),
        )


@dataclass
class Harness:
    producer: HistoryOrdersProducer
    head: SheetsHistoryAcquisition
    job: dict[str, Any]
    gateway: Gateway
    clock: list[datetime]


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    name = f"zeler_history_orders_{uuid4().hex}"
    uri = f"mongodb://127.0.0.1:27028/{name}?directConnection=true"
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(uri, tz_aware=True)
    hello = await client.admin.command("hello")
    assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
    root = Path(__file__).resolve().parents[3] / "infra/mongo"
    for directory in ("schemas", "indexes"):
        (tmp_path / directory).mkdir()
        for collection in (
            "sheets_history_acquisitions",
            "sheets_history_receipts",
            "sheets_history_order_ranges",
        ):
            filename = f"{collection}.json"
            (tmp_path / directory / filename).write_text((root / directory / filename).read_text())
    try:
        await asyncio.to_thread(apply_validators, uri, tmp_path / "schemas")
        clock = [NOW]
        queue = FormulaRecoveryQueue(client[name], now=lambda: clock[0])
        request = RecoveryRequest("82453304", "orders", NOW - timedelta(days=31), NOW)
        await queue.enqueue(request)
        job = await queue.claim()
        assert job is not None
        head = SheetsHistoryAcquisition(
            _id="head",
            seller_id="82453304",
            read_model="orders",
            plan_id="plan",
            scope_id="orders:20260815:20260915",
            job_id=job["_id"],
            date_from=request.date_from,
            date_to=request.date_to,
            created_at=NOW,
            updated_at=NOW,
        )
        store = HistoryAcquisitionStore(client[name], queue)
        await store.initialize(job, head)
        gateway = Gateway()
        worker = FormulaRecoveryWorker(db=client[name], gateway=gateway, queue=queue)
        yield Harness(
            HistoryOrdersProducer(worker, HistoryContinuation(store)), head, job, gateway, clock
        )
    finally:
        await client.drop_database(name)
        client.close()


async def advance(harness: Harness) -> None:
    harness.head = await harness.producer.step(harness.job, harness.head)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed


async def begin_verification(harness: Harness, rows: list[dict[str, Any]]) -> None:
    harness.gateway.pages = {0: {"paging": {"total": len(rows)}, "results": rows}}
    harness.gateway.details = {f"/orders/{row['id']}": row for row in rows}
    await advance(harness)
    for _ in rows:
        await advance(harness)
    await advance(harness)
    assert harness.head.phase == "verify"
    assert harness.head.pass_number == 2 and harness.head.next_cursor == 0
    assert harness.head.drift_restarts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_verification_pass_is_durable_and_does_not_publish(
    harness: Harness, empty: bool
) -> None:
    rows = [] if empty else [order(1), order(2)]
    await begin_verification(harness, rows)
    if rows:
        harness.gateway.pages = {
            0: {"paging": {"total": 2}, "results": rows[:1]},
            1: {"paging": {"total": 2}, "results": rows[1:]},
        }
        await advance(harness)
        assert harness.head.next_cursor == 1
        harness.producer = HistoryOrdersProducer(
            harness.producer.worker, HistoryContinuation(harness.producer.continuation.store)
        )
    await advance(harness)
    assert harness.head.phase == "verify" and harness.head.next_cursor is None
    assert harness.head.pass_number == 2 and harness.head.drift_restarts == 0
    assert harness.head.discovered_count == len(rows)
    assert harness.head.published_count == 0
    receipts = harness.producer.continuation.store.receipts
    assert await receipts.count_documents({"pass_number": 1, "kind": "detail"}) == len(rows)
    assert await receipts.count_documents({"pass_number": 2, "kind": "membership"}) == len(rows)
    assert await harness.producer.worker.db.orders.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["identity", "version", "payload", "repeat", "total"])
async def test_verification_restarts_on_full_manifest_drift(harness: Harness, defect: str) -> None:
    await begin_verification(harness, [order(1), order(2)])
    replacement = order(3) if defect == "identity" else order(2)
    if defect == "version":
        replacement["date_last_updated"] = (NOW + timedelta(seconds=1)).isoformat()
    if defect == "payload":
        replacement["status"] = "changed_with_same_version"
    if defect == "repeat":
        replacement = order(1)
    harness.gateway.pages = {
        0: {"paging": {"total": 3 if defect == "total" else 2}, "results": [order(1)]},
        1: {"paging": {"total": 2}, "results": [replacement]},
    }
    await advance(harness)
    if defect != "total":
        assert harness.head.next_cursor == 1
        await advance(harness)
    assert harness.head.phase == "discover" and harness.head.pass_number == 3
    assert harness.head.drift_restarts == 1
    assert (
        await harness.producer.continuation.store.receipts.count_documents(
            {"pass_number": 1, "kind": "detail"}
        )
        == 2
    )


@pytest.mark.asyncio
async def test_verification_interruption_preserves_page_and_resume_offset(harness: Harness) -> None:
    rows = [order(1), order(2)]
    await begin_verification(harness, rows)
    harness.gateway.pages = {
        0: {"paging": {"total": 2}, "results": rows[:1]},
        1: {"paging": {"total": 2}, "results": rows[1:]},
    }
    await advance(harness)
    checkpoint = harness.head
    harness.gateway.failures["search"] = httpx.ReadTimeout("interrupted verification")
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert harness.head == checkpoint
    harness.clock[0] += timedelta(minutes=1)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed
    await advance(harness)
    assert harness.head.next_cursor is None and harness.head.pass_number == 2
    assert harness.head.observed_from == NOW
    assert harness.head.observed_until == NOW + timedelta(minutes=1)
    stored = await harness.producer.continuation.store.receipts.find_one(
        {"pass_number": 2, "resource_id": "1"}
    )
    assert stored is not None and stored["observed_at"] == NOW


@pytest.mark.asyncio
async def test_begin_verification_rolls_back_with_queue_release(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.gateway.pages = {0: {"paging": {"total": 0}, "results": []}}
    await advance(harness)
    before = harness.head
    continuation = harness.producer.continuation

    async def interrupted(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("interrupted transaction")

    with monkeypatch.context() as patch:
        patch.setattr(continuation, "_pending", interrupted)
        with pytest.raises(RuntimeError, match="interrupted transaction"):
            await harness.producer.step(harness.job, harness.head)
    stored = await continuation.store.heads.find_one({"_id": before.id})
    assert stored == before.model_dump(by_alias=True)
    job = await harness.producer.worker.queue.collection.find_one({"_id": harness.job["_id"]})
    assert job is not None and job["state"] == "running"
    await advance(harness)
    assert harness.head.pass_number == 2 and harness.head.drift_restarts == 0


@pytest.mark.asyncio
async def test_expired_verification_owner_cannot_consult_or_advance(harness: Harness) -> None:
    await begin_verification(harness, [order(1)])
    before = harness.head
    calls = len(harness.gateway.calls)
    harness.clock[0] += timedelta(hours=1)
    with pytest.raises(ValueError, match="lease lost"):
        await harness.producer.step(harness.job, before)
    assert len(harness.gateway.calls) == calls
    assert await harness.producer.continuation.store.heads.find_one(
        {"_id": before.id}
    ) == before.model_dump(by_alias=True)


@pytest.mark.asyncio
async def test_verification_retains_hour_boundary_exclusions(harness: Harness) -> None:
    outside = order(9, date_created=NOW.isoformat())
    harness.gateway.pages = {0: {"paging": {"total": 2}, "results": [order(1), outside]}}
    harness.gateway.details = {"/orders/1": order(1)}
    await advance(harness)
    await advance(harness)
    await advance(harness)
    await advance(harness)
    assert harness.head.phase == "verify" and harness.head.next_cursor is None
    assert harness.head.discovered_count == 1
    receipts = harness.producer.continuation.store.receipts
    assert await receipts.count_documents({"resource_id": "9", "kind": "exclusion"}) == 2


@pytest.mark.asyncio
async def test_verification_compares_sets_not_provider_page_order(harness: Harness) -> None:
    await begin_verification(harness, [order(1), order(2)])
    harness.gateway.pages = {0: {"paging": {"total": 2}, "results": [order(2), order(1)]}}
    await advance(harness)
    assert harness.head.phase == "verify" and harness.head.next_cursor is None
    assert harness.head.pass_number == 2 and harness.head.drift_restarts == 0


@pytest.mark.asyncio
async def test_final_manifest_rejects_missing_durable_page_evidence(harness: Harness) -> None:
    await begin_verification(harness, [order(1), order(2)])
    harness.gateway.pages = {
        0: {"paging": {"total": 2}, "results": [order(1)]},
        1: {"paging": {"total": 2}, "results": [order(2)]},
    }
    await advance(harness)
    await harness.producer.continuation.store.receipts.delete_one(
        {"pass_number": 2, "resource_id": "1"}
    )
    await advance(harness)
    assert harness.head.phase == "discover" and harness.head.pass_number == 3
    assert harness.head.drift_restarts == 1


async def known_order(harness: Harness, identity: str, **changes: Any) -> None:
    await harness.producer.worker.db.orders.insert_one(
        {
            "_id": identity,
            "seller_id": "82453304",
            "date_created": NOW - timedelta(days=1),
            "status": "cancelled",
            **changes,
        }
    )


@pytest.mark.asyncio
async def test_known_cancelled_is_staged_once_without_excluding_history(harness: Harness) -> None:
    await begin_verification(harness, [order(1)])
    await advance(harness)
    await known_order(harness, "9")
    raw = order(9, status="cancelled")
    harness.gateway.details["/orders/9"] = raw
    await advance(harness)
    assert harness.head.phase == "verify" and harness.head.next_cursor is None
    assert harness.head.source_total == 1 and harness.head.discovered_count == 2
    assert harness.head.fetched_count == 1 and harness.head.published_count == 0
    records = await harness.producer.continuation.store.receipts.find(
        {"pass_number": 2, "resource_id": "9"}
    ).to_list(length=4)
    assert {record["kind"] for record in records} == {"membership", "detail", "exclusion"}
    assert all(record["source_payload"] == raw for record in records)
    exclusion = next(record for record in records if record["kind"] == "exclusion")
    assert exclusion["exclusion_reason"] == "seller_search_omits_source_confirmed_cancelled_order"
    with pytest.raises(ValueError, match="reconciliation remains"):
        await harness.producer.step(harness.job, harness.head)
    assert harness.gateway.calls.count("/orders/9") == 1
    assert await harness.producer.worker.db.orders.count_documents({"_id": "9"}) == 1
    assert await harness.producer.worker.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["active", "missing", "seller", "date", "status"])
async def test_known_omission_needs_current_source_evidence(harness: Harness, defect: str) -> None:
    await begin_verification(harness, [])
    await advance(harness)
    await known_order(harness, "9")
    raw = order(9, status="paid" if defect == "active" else "cancelled")
    if defect == "seller":
        raw["seller"] = {"id": 999}
    if defect == "date":
        raw["date_created"] = (NOW - timedelta(days=100)).isoformat()
    if defect == "status":
        del raw["status"]
    harness.gateway.details["/orders/9"] = raw
    if defect == "missing":
        request = httpx.Request("GET", "https://gateway.invalid/orders/9")
        harness.gateway.failures["/orders/9"] = httpx.HTTPStatusError(
            "missing", request=request, response=httpx.Response(404, request=request)
        )
    previous = harness.head
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert (
        await harness.producer.continuation.store.receipts.count_documents({"resource_id": "9"})
        == 0
    )
    if defect == "active":
        assert harness.head.phase == "discover" and harness.head.drift_restarts == 1
    else:
        assert harness.head == previous
    assert await harness.producer.worker.db.orders.count_documents({"_id": "9"}) == 1


@pytest.mark.asyncio
async def test_known_scope_and_normalized_duplicate_ids_do_not_repeat_detail(
    harness: Harness,
) -> None:
    await begin_verification(harness, [])
    await advance(harness)
    await known_order(harness, "9")
    await known_order(harness, "duplicate", _id=9)
    await known_order(harness, "8", seller_id="999")
    await known_order(harness, "7", date_created=NOW - timedelta(days=100))
    harness.gateway.details["/orders/9"] = order(9, status="cancelled")
    await advance(harness)
    with pytest.raises(ValueError, match="reconciliation remains"):
        await harness.producer.step(harness.job, harness.head)
    assert [
        path for path in harness.gateway.calls if path.startswith("/orders/") and "?" not in path
    ] == ["/orders/9"]


@pytest.mark.asyncio
async def test_cancelled_detail_interruption_retains_previous_identity(harness: Harness) -> None:
    await begin_verification(harness, [])
    await advance(harness)
    for identity in (8, 9):
        await known_order(harness, str(identity))
        harness.gateway.details[f"/orders/{identity}"] = order(identity, status="cancelled")
    await advance(harness)
    previous = harness.head
    harness.gateway.failures["/orders/9"] = httpx.ReadTimeout("interrupted cancelled detail")
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert harness.head == previous
    harness.clock[0] += timedelta(minutes=1)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed
    await advance(harness)
    assert harness.head.fetched_count == 2
    assert harness.gateway.calls.count("/orders/8") == 1
    assert harness.gateway.calls.count("/orders/9") == 2
    records = await harness.producer.continuation.store.receipts.find(
        {"kind": "detail", "pass_number": 2}
    ).to_list(length=3)
    assert {record["resource_id"] for record in records} == {"8", "9"}


@pytest.mark.asyncio
async def test_cancelled_receipt_triplet_is_atomic_with_checkpoint(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await begin_verification(harness, [])
    await advance(harness)
    await known_order(harness, "9")
    harness.gateway.details["/orders/9"] = order(9, status="cancelled")
    previous = harness.head

    async def interrupted(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("cancelled checkpoint interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(harness.producer.continuation, "_pending", interrupted)
        with pytest.raises(RuntimeError, match="cancelled checkpoint interrupted"):
            await harness.producer.step(harness.job, harness.head)
    store = harness.producer.continuation.store
    assert await store.receipts.count_documents({"resource_id": "9"}) == 0
    assert await store.heads.find_one({"_id": previous.id}) == previous.model_dump(by_alias=True)
    await advance(harness)
    assert await store.receipts.count_documents({"resource_id": "9"}) == 3


@pytest.mark.asyncio
async def test_details_survive_interruption_without_repeating_acquired_work(
    harness: Harness,
) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 2}, "results": [order(1), order(2)]}
    harness.gateway.details = {"/orders/1": order(1), "/orders/2": order(2)}
    await advance(harness)
    assert harness.head.phase == "hydrate" and harness.head.discovered_count == 2
    assert all("/orders/search?" in path for path in harness.gateway.calls)
    await advance(harness)
    assert harness.head.fetched_count == 1
    harness.gateway.failures["/orders/2"] = httpx.ReadTimeout("interrupted")
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert harness.head.fetched_count == 1
    harness.clock[0] += timedelta(minutes=1)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed
    await advance(harness)
    assert harness.head.fetched_count == 2
    await advance(harness)
    assert harness.head.phase == "verify"
    assert harness.gateway.calls.count("/orders/1") == 1
    assert harness.gateway.calls.count("/orders/2") == 2
    assert await harness.producer.worker.db.orders.count_documents({}) == 0
    assert await harness.producer.worker.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_total", [False, True])
async def test_shifted_offset_or_total_restarts_and_retains_prior_page(
    harness: Harness, changed_total: bool
) -> None:
    harness.gateway.pages[0] = {
        "paging": {"total": 100},
        "results": [order(identity) for identity in range(1, 51)],
    }
    harness.gateway.pages[50] = {
        "paging": {"total": 101 if changed_total else 100},
        "results": [order(identity) for identity in range(50, 100)],
    }
    await advance(harness)
    assert harness.head.next_cursor == 50
    await advance(harness)
    assert harness.head.pass_number == 2 and harness.head.drift_restarts == 1
    assert harness.head.discovered_count == 0
    assert await harness.producer.continuation.store.receipts.count_documents({}) == 50


@pytest.mark.asyncio
async def test_hour_superset_keeps_exact_chunk_and_excludes_boundary_rows(harness: Harness) -> None:
    boundary = harness.head.date_from.replace(minute=10)
    harness.gateway.pages[0] = {
        "paging": {"total": 2},
        "results": [order(1, date_created=boundary.isoformat()), order(2)],
    }
    await advance(harness)
    params = parse_qs(urlsplit(harness.gateway.calls[0]).query)
    assert params["order.date_created.from"] == [
        harness.head.date_from.replace(minute=0).isoformat(timespec="milliseconds")
    ]
    assert params["order.date_created.to"] == [
        harness.head.date_to.replace(minute=0).isoformat(timespec="milliseconds")
    ]
    assert not any("date_last_updated" in key for key in params)
    assert harness.head.source_total == 2 and harness.head.discovered_count == 1
    exclusion = await harness.producer.continuation.store.receipts.find_one({"kind": "exclusion"})
    assert exclusion is not None and exclusion["resource_id"] == "1"


@pytest.mark.asyncio
async def test_page_failure_resumes_same_offset_and_quota_does_not_charge(harness: Harness) -> None:
    harness.gateway.failures["search"] = LocalQuotaTimeoutError()
    harness.head = await harness.producer.step(harness.job, harness.head)
    queued = await harness.producer.worker.queue.collection.find_one({"_id": harness.job["_id"]})
    assert queued is not None and queued["attempts"] == 0
    assert harness.head.next_cursor is None and harness.head.discovered_count == 0


@pytest.mark.asyncio
async def test_over_budget_total_persists_subdivision_not_retention_claim(harness: Harness) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 10001}, "results": []}
    await advance(harness)
    assert harness.head.active_range_id is not None
    assert await harness.producer.worker.db.sheets_history_order_ranges.count_documents({}) == 3
    assert await harness.producer.continuation.store.receipts.count_documents({}) == 0


def range_source(harness: Harness, rows: list[dict[str, Any]]) -> None:
    def search(params: dict[str, list[str]]) -> dict[str, Any]:
        lower = datetime.fromisoformat(params["order.date_created.from"][0])
        upper = datetime.fromisoformat(params["order.date_created.to"][0]) + timedelta(hours=1)
        selected = [
            row for row in rows if lower <= datetime.fromisoformat(row["date_created"]) < upper
        ]
        offset = int(params["offset"][0])
        return {"paging": {"total": len(selected)}, "results": selected[offset : offset + 50]}

    harness.gateway.on_search = search
    harness.gateway.details = {f"/orders/{row['id']}": row for row in rows}


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_subdivided_producer_resumes_and_verifies_real_children(
    harness: Harness, drift: bool
) -> None:
    rows = [order(1, date_created=(NOW - timedelta(days=25)).isoformat()), order(2)]
    range_source(harness, rows)
    harness.producer.ranges.result_budget = 1
    await advance(harness)
    await advance(harness)
    assert harness.head.discovered_count == 1
    previous = harness.head
    harness.gateway.failures["search"] = httpx.ReadTimeout("child interrupted")
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert harness.head == previous
    harness.clock[0] += timedelta(minutes=1)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed
    harness.producer = HistoryOrdersProducer(harness.producer.worker, harness.producer.continuation)
    harness.producer.ranges.result_budget = 1
    await advance(harness)
    assert (harness.head.phase, harness.head.source_total) == ("hydrate", 2)
    for _ in range(3):
        await advance(harness)
    assert (harness.head.phase, harness.head.pass_number) == ("verify", 2)
    if drift:
        rows[0]["id"] = 3
    await advance(harness)
    await advance(harness)
    if drift:
        assert harness.head.phase == "discover" and harness.head.pass_number == 3
    else:
        await advance(harness)
        assert harness.head.phase == "verify" and harness.head.next_cursor is None
        assert harness.head.active_range_id is None
    assert (
        await harness.producer.continuation.store.receipts.count_documents(
            {"pass_number": 1, "kind": "detail"}
        )
        == 2
    )
    assert await harness.producer.worker.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_empty_child_uses_response_time_not_later_staging_time(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    range_source(harness, [order(1), order(2)])
    harness.producer.ranges.result_budget = 1
    await advance(harness)
    harness.clock[0] += timedelta(seconds=5)
    response_time = harness.clock[0]
    original = harness.producer.ranges.page

    async def late_stage(*args: Any, **kwargs: Any) -> SheetsHistoryAcquisition:
        harness.clock[0] += timedelta(seconds=30)
        return await original(*args, **kwargs)

    monkeypatch.setattr(harness.producer.ranges, "page", late_stage)
    await advance(harness)
    assert harness.head.discovered_count == 0
    assert harness.head.observed_until == response_time


@pytest.mark.asyncio
async def test_recursive_provider_hour_saturation_stops_explicitly(harness: Harness) -> None:
    range_source(harness, [order(1), order(2)])
    harness.producer.ranges.result_budget = 1
    with pytest.raises(HistoryLimitError, match="single provider hour"):
        for _ in range(40):
            await advance(harness)
    assert harness.head.phase == "discover" and harness.head.published_count == 0


@pytest.mark.asyncio
async def test_changed_child_totals_restart_without_committing_last_page(harness: Harness) -> None:
    rows = [order(1, date_created=(NOW - timedelta(days=25)).isoformat()), order(2)]
    range_source(harness, rows)
    harness.producer.ranges.result_budget = 1
    await advance(harness)
    del rows[0]
    await advance(harness)
    await advance(harness)
    assert harness.head.phase == "discover" and harness.head.pass_number == 2
    assert harness.head.drift_restarts == 1
    assert await harness.producer.continuation.store.receipts.count_documents({}) == 0
    assert await harness.producer.ranges.collection.count_documents({"pass_number": 1}) == 3


@pytest.mark.asyncio
async def test_empty_unsplit_response_time_precedes_delayed_checkpoint(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 0}, "results": []}
    original = harness.producer._save

    async def late_save(*args: Any, **kwargs: Any) -> SheetsHistoryAcquisition:
        harness.clock[0] += timedelta(seconds=30)
        return await original(*args, **kwargs)

    monkeypatch.setattr(harness.producer, "_save", late_save)
    await advance(harness)
    assert harness.head.observed_from == NOW and harness.head.observed_until == NOW
    assert harness.head.updated_at == NOW + timedelta(seconds=30)


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [None, {}, [{}] * 51])
async def test_invalid_count_probe_does_not_create_child_plan(harness: Harness, rows: Any) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 10001}, "results": rows}
    previous = harness.head
    harness.head = await harness.producer.step(harness.job, previous)
    assert harness.head == previous
    assert await harness.producer.ranges.collection.count_documents({}) == 0


@pytest.mark.asyncio
async def test_interrupted_second_page_resumes_its_persisted_offset(harness: Harness) -> None:
    harness.gateway.pages[0] = {
        "paging": {"total": 51},
        "results": [order(identity) for identity in range(1, 51)],
    }
    harness.gateway.pages[50] = {"paging": {"total": 51}, "results": [order(51)]}
    await advance(harness)
    harness.gateway.failures["search"] = httpx.ReadTimeout("interrupted page")
    harness.head = await harness.producer.step(harness.job, harness.head)
    assert harness.head.next_cursor == 50 and harness.head.discovered_count == 50
    harness.clock[0] += timedelta(minutes=1)
    claimed = await harness.producer.worker.queue.claim(history=True)
    assert claimed is not None
    harness.job = claimed
    await advance(harness)
    offsets = [parse_qs(urlsplit(path).query)["offset"][0] for path in harness.gateway.calls]
    assert offsets == ["0", "50", "50"]
    assert harness.head.discovered_count == 51 and harness.head.phase == "hydrate"


@pytest.mark.asyncio
async def test_detail_version_drift_restarts_without_discarding_membership(
    harness: Harness,
) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 1}, "results": [order(1)]}
    harness.gateway.details["/orders/1"] = order(
        1, date_last_updated=(NOW + timedelta(seconds=1)).isoformat()
    )
    await advance(harness)
    await advance(harness)
    assert harness.head.drift_restarts == 1 and harness.head.pass_number == 2
    assert (
        await harness.producer.continuation.store.receipts.count_documents({"kind": "membership"})
        == 1
    )
    assert (
        await harness.producer.continuation.store.receipts.count_documents({"kind": "detail"}) == 0
    )


@pytest.mark.asyncio
async def test_partial_detail_keeps_explicit_unavailable_fields(harness: Harness) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 1}, "results": [order(1)]}
    harness.gateway.details["/orders/1"] = order(1)
    harness.gateway.detail_headers = {"X-Content-Missing": "buyer"}
    await advance(harness)
    await advance(harness)
    detail = await harness.producer.continuation.store.receipts.find_one({"kind": "detail"})
    assert detail is not None and detail["unavailable_fields"] == ["buyer"]
    assert detail["observed_at"] == NOW
    assert detail["source_hash"] == item_source_fingerprint(detail["source_payload"])


@pytest.mark.asyncio
async def test_empty_source_is_staged_but_not_certified_as_coverage(harness: Harness) -> None:
    harness.gateway.pages[0] = {"paging": {"total": 0}, "results": []}
    await advance(harness)
    await advance(harness)
    assert harness.head.phase == "verify" and harness.head.fetched_count == 0
    await advance(harness)
    with pytest.raises(ValueError, match="reconciliation remains"):
        await harness.producer.step(harness.job, harness.head)
    assert await harness.producer.worker.db.sheets_read_model_freshness.count_documents({}) == 0


@pytest.mark.asyncio
async def test_expired_owner_does_not_consult_gateway(harness: Harness) -> None:
    harness.clock[0] += timedelta(hours=1)
    with pytest.raises(ValueError, match="lease lost"):
        await harness.producer.step(harness.job, harness.head)
    assert harness.gateway.calls == []


@pytest.mark.asyncio
async def test_raw_detail_survives_shipment_enrichment_with_original_observation(
    harness: Harness,
) -> None:
    source = order(1, tags=[], shipping={})
    harness.gateway.pages[0] = {"paging": {"total": 1}, "results": [source]}
    harness.gateway.details["/orders/1"] = source
    harness.gateway.details["/orders/1/shipments?hosted=true"] = [
        {"id": 99, "type": "forward", "order_id": 1, "seller_id": 82453304}
    ]

    def advance_secondary_clock(path: str) -> None:
        if "shipments" in path:
            harness.clock[0] += timedelta(seconds=5)

    harness.gateway.on_request = advance_secondary_clock
    await advance(harness)
    await advance(harness)
    detail = await harness.producer.continuation.store.receipts.find_one({"kind": "detail"})
    assert detail is not None and detail["source_payload"] == source
    assert detail["source_hash"] == item_source_fingerprint(source)
    assert detail["payload"]["shipping"]["id"] == "99"
    assert detail["payload_hash"] != detail["source_hash"]
    assert detail["observed_at"] == NOW


@pytest.mark.asyncio
async def test_raw_search_provenance_supports_partial_seller_detail(harness: Harness) -> None:
    source = order(1)
    harness.gateway.pages[0] = {"paging": {"total": 1}, "results": [source]}
    harness.gateway.details["/orders/1"] = order(1, seller={})
    harness.gateway.detail_headers = {"X-Content-Missing": "seller"}
    await advance(harness)
    await advance(harness)
    assert harness.head.fetched_count == 1
    membership = await harness.producer.continuation.store.receipts.find_one({"kind": "membership"})
    assert membership is not None and membership["source_payload"] == source
