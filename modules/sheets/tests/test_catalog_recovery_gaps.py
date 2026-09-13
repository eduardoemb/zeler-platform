from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, RecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

NOW = datetime(2026, 9, 13, 0, 5, tzinfo=UTC)
START = datetime(2025, 9, 13, tzinfo=UTC)


def proof(start: datetime, end: datetime, **changes: Any) -> dict[str, Any]:
    return {
        "state": "reconciled",
        "date_from": start,
        "reconciled_until": end,
        "valid_until": NOW - timedelta(days=1),
        **changes,
    }


async def coverage(marker: dict[str, Any] | None, *, now: datetime = NOW) -> Any:
    db = MagicMock()
    db.__getitem__.return_value.find_one = AsyncMock(return_value=marker)
    return await FormulaReadModelRepository(db=db).catalog_sales_coverage(
        seller_id="82453304", formula="ZELERDATA_CATALOGO", now=now, windows=(365,)
    )


@pytest.mark.asyncio
async def test_catalog_history_advances_across_90_day_chunks_to_completion() -> None:
    marker = proof(NOW - timedelta(days=7), NOW)
    cursor = START
    requests = []
    while cursor < NOW - timedelta(days=7):
        as_of, covered, recovery = await coverage(marker)
        assert as_of == NOW
        assert covered == ()
        assert recovery is not None
        assert recovery.date_from == cursor
        end = min(cursor + timedelta(days=90), NOW - timedelta(days=7))
        assert recovery.date_to == end
        request = RecoveryRequest("82453304", "orders", recovery.date_from, recovery.date_to)
        requests.append(request.key)
        marker = proof(cursor, end, retained_intervals=[marker])
        # Production publication flattens retained proofs; preserve that shape.
        previous = marker["retained_intervals"][0]
        marker["retained_intervals"] = [
            {key: value for key, value in previous.items() if key != "retained_intervals"},
            *previous.get("retained_intervals", []),
        ]
        cursor = end
    assert len(requests) == len(set(requests)) == 4
    _, covered, recovery = await coverage(marker)
    assert covered == (365,)
    assert recovery is None


@pytest.mark.asyncio
async def test_gap_stops_at_next_proof_and_ignores_overlaps() -> None:
    marker = proof(
        NOW - timedelta(days=1),
        NOW,
        retained_intervals=[
            proof(START, START + timedelta(days=30)),
            proof(START + timedelta(days=20), START + timedelta(days=45)),
            proof(START + timedelta(days=50), NOW - timedelta(days=1)),
        ],
    )
    _, _, recovery = await coverage(marker)
    assert recovery.date_from == START + timedelta(days=45)
    assert recovery.date_to == START + timedelta(days=50)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"state": "failed"},
        {"date_from": "bad"},
        {"reconciled_until": "bad"},
        {"reconciled_until": START - timedelta(days=1)},
    ],
)
async def test_invalid_retained_proof_cannot_skip_missing_history(invalid: dict[str, Any]) -> None:
    marker = proof(NOW - timedelta(days=1), NOW, retained_intervals=[proof(START, NOW, **invalid)])
    _, _, recovery = await coverage(marker)
    assert recovery.date_from == START
    assert recovery.date_to == START + timedelta(days=90)


@pytest.mark.asyncio
async def test_stale_marker_withdraws_all_retained_proofs() -> None:
    marker = proof(START, NOW, state="stale", retained_intervals=[proof(START, NOW)])
    _, covered, recovery = await coverage(marker)
    assert covered == ()
    assert recovery.date_from == START
    assert recovery.date_to == START + timedelta(days=90)


@pytest.mark.asyncio
async def test_recent_retained_cut_preserves_request_key_across_midnight() -> None:
    cut = NOW.replace(hour=23, minute=59) - timedelta(days=1)
    marker = proof(START, START + timedelta(days=90), retained_intervals=[proof(cut, cut)])
    before = await coverage(marker, now=cut + timedelta(seconds=20))
    after = await coverage(marker, now=cut + timedelta(minutes=2))
    assert before[0] == after[0] == cut
    first, second = before[2], after[2]
    assert RecoveryRequest("82453304", "orders", first.date_from, first.date_to).key == (
        RecoveryRequest("82453304", "orders", second.date_from, second.date_to).key
    )


@pytest.mark.asyncio
async def test_expired_cut_requires_only_unproven_live_tail() -> None:
    end = NOW - timedelta(minutes=16)
    marker = proof(START, end)
    as_of, covered, recovery = await coverage(marker)
    assert as_of == NOW
    assert covered == ()
    assert recovery.date_from == end
    assert recovery.date_to == NOW


@pytest.mark.asyncio
async def test_catalog_planner_and_worker_converge_with_persisted_interval_proofs() -> None:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_catalog_gap_test_{uuid4().hex}"]
    connected = False
    try:
        try:
            hello = await client.admin.command("hello")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        assert hello["isWritablePrimary"]
        now = datetime.now(UTC).replace(microsecond=0)
        recent = proof(now - timedelta(days=7), now, valid_until=now + timedelta(minutes=15))
        await db.sheets_read_model_freshness.insert_one(
            {"_id": "82453304:orders", "seller_id": "82453304", "read_model": "orders", **recent}
        )
        acquired_paths = []

        class Gateway:
            async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
                assert seller_id == "82453304"
                assert path.startswith("/orders/search?")
                acquired_paths.append(path)
                return {"paging": {"total": 0}, "results": []}

        queue = FormulaRecoveryQueue(db, now=lambda: now, enabled_models=frozenset({"orders"}))
        repository = FormulaReadModelRepository(db=db)
        worker = FormulaRecoveryWorker(db=db, queue=queue, gateway=Gateway())
        for _ in range(4):
            _, covered, recovery = await repository.catalog_sales_coverage(
                seller_id="82453304", formula="ZELERDATA_CATALOGO", now=now, windows=(365,)
            )
            assert covered == ()
            assert recovery is not None
            assert recovery.date_from is not None and recovery.date_to is not None
            await queue.enqueue(
                RecoveryRequest("82453304", "orders", recovery.date_from, recovery.date_to)
            )
            assert await worker.process_one()
        _, covered, recovery = await repository.catalog_sales_coverage(
            seller_id="82453304", formula="ZELERDATA_CATALOGO", now=now, windows=(365,)
        )
        assert covered == (365,)
        assert recovery is None
        assert len(acquired_paths) == len(set(acquired_paths)) == 4
        assert await db.sheets_formula_recovery_jobs.count_documents({"state": "completed"}) == 4
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()
