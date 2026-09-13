from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_formula_handlers_remaining_phase4 import FakeDb, _context

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import build_remaining_phase4_formula_handlers
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    build_returns_histories_withdrawals_formula_handlers,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest
from zeler_sheets.item_projection import item_source_fingerprint

NOW = datetime(2026, 9, 13, 2, tzinfo=UTC)
SELLER = "82453304"


def _seed(db: FakeDb, *, observed: datetime = NOW, status: str = "active") -> None:
    source = {
        "_id": "MLM1",
        "seller_id": SELLER,
        "last_meli_sync_at": observed,
        "status": status,
        "price": 100,
        "available_quantity": 0,
        "title": "Fixture",
    }
    db["items"].documents["MLM1"] = source
    db["sheets_item_formula_rows"].documents["row"] = {
        "seller_id": SELLER,
        "item_id": "MLM1",
        "current": dict(source),
        "source_snapshot": {
            "observed_at": observed,
            "fingerprint": item_source_fingerprint(source),
            "rows_count": 1,
        },
    }
    request = ItemInventoryRecoveryRequest(SELLER)
    db["sheets_formula_recovery_jobs"].documents[request.key] = {
        "_id": request.key,
        "seller_id": SELLER,
        "read_model": "item_formula_rows",
        "inventory_scope": True,
        "inventory_ids": ["MLM1"],
        "inventory_observed_at": observed,
        "state": "completed",
    }
    db["item_status_states"].documents["state"] = {
        "seller_id": SELLER,
        "item_id": "MLM1",
        "current_status": status,
        "last_observed_at": observed,
        "status_started_at": NOW - timedelta(days=3),
    }
    db["sheets_price_history_snapshots"].documents["price"] = {
        "seller_id": SELLER,
        "item_id": "MLM1",
        "title": "Fixture",
        "snapshot_at": NOW - timedelta(days=3),
        "prices": [{"price": 100, "status": status, "observed_at": NOW - timedelta(days=3)}],
    }
    db["sheets_stockout_snapshots"].documents["stock"] = {
        "seller_id": SELLER,
        "item_id": "MLM1",
        "title": "Fixture",
        "observed_at": observed,
        "current_stock": 0,
        "stock_state": "out_of_stock",
        "status": status,
        "out_of_stock_since": NOW - timedelta(days=2),
    }


async def _execute(db: Any, formula: str, *, now: datetime = NOW) -> FormulaExecutionResult:
    repository = FormulaReadModelRepository(db=db)
    handlers = {
        **build_remaining_phase4_formula_handlers(repository, now_fn=lambda: now),
        **build_returns_histories_withdrawals_formula_handlers(repository, now_fn=lambda: now),
    }
    return await FormulaDispatcher(handlers).execute(
        _context(f"ZELERDATA_{formula}", {"id_publicaciones": ["MLM1"], "encabezados": False})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", ["TIEMPOACTIVA", "TIEMPOSINSTOCK", "PRECIOHISTORICO"])
async def test_history_recovers_from_acquired_item_without_global_marker(formula: str) -> None:
    db = FakeDb()
    _seed(db, observed=NOW - timedelta(hours=1))
    with pytest.raises(FormulaDataUnavailableError) as error:
        await _execute(db, formula)
    assert error.value.read_model == "item_formula_rows"
    assert error.value.item_ids == (() if formula == "TIEMPOSINSTOCK" else ("MLM1",))
    _seed(db)
    result = await _execute(db, formula)
    if formula == "TIEMPOACTIVA":
        assert result.values == [[3]]
    elif formula == "PRECIOHISTORICO":
        assert result.values == [["MLM1", "Fixture", 100, "active", "NA", "NA", "NA", "NA"]]
    else:
        assert len(result.values) == 1
        assert result.values[0][0] == "MLM1"
        assert result.values[0][-1] == 2
    assert result.recovery is None
    assert db["sheets_read_model_freshness"].documents == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formula,collection,key,value",
    [
        ("TIEMPOACTIVA", "item_status_states", "current_status", "paused"),
        ("TIEMPOACTIVA", "item_status_states", "status_started_at", NOW + timedelta(days=1)),
        ("TIEMPOACTIVA", "item_status_states", "last_observed_at", NOW - timedelta(minutes=1)),
        (
            "PRECIOHISTORICO",
            "sheets_price_history_snapshots",
            "prices",
            [{"price": 99, "status": "active", "observed_at": NOW}],
        ),
        ("TIEMPOSINSTOCK", "sheets_stockout_snapshots", "current_stock", 5),
        (
            "TIEMPOSINSTOCK",
            "sheets_stockout_snapshots",
            "out_of_stock_since",
            NOW + timedelta(days=1),
        ),
        ("TIEMPOSINSTOCK", "sheets_stockout_snapshots", "observed_at", NOW - timedelta(minutes=1)),
    ],
)
async def test_history_rejects_snapshot_inconsistent_with_acquired_source(
    formula: str, collection: str, key: str, value: Any
) -> None:
    db = FakeDb()
    _seed(db)
    next(iter(db[collection].documents.values()))[key] = value
    result = await _execute(db, formula)
    assert any("DATA_UNAVAILABLE" in row for row in result.values)
    assert result.recovery is not None
    assert result.recovery.read_model == "item_formula_rows"
    assert result.recovery.item_ids == ("MLM1",)


@pytest.mark.asyncio
async def test_stockout_incomplete_membership_is_visible_and_requests_discovery() -> None:
    db = FakeDb()
    _seed(db)
    job = next(iter(db["sheets_formula_recovery_jobs"].documents.values()))
    job["inventory_observed_at"] = NOW - timedelta(hours=1)
    result = await _execute(db, "TIEMPOSINSTOCK")
    assert result.values[0][0] == "MLM1"
    assert result.values[1] == ["DATA_UNAVAILABLE"] * 8
    assert result.recovery is not None
    assert result.recovery.item_ids == ()


@pytest.mark.asyncio
async def test_paused_current_item_has_no_invented_active_interval() -> None:
    db = FakeDb()
    _seed(db, status="paused")
    result = await _execute(db, "TIEMPOACTIVA")
    assert result.values == [["NA"]]
    assert result.recovery is None


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", ["TIEMPOACTIVA", "TIEMPOSINSTOCK", "PRECIOHISTORICO"])
@pytest.mark.parametrize("damage", ["owner", "fingerprint"])
async def test_history_source_must_be_owned_and_bound(formula: str, damage: str) -> None:
    db = FakeDb()
    _seed(db)
    if damage == "owner":
        db["items"].documents["MLM1"]["seller_id"] = "other"
    else:
        db["items"].documents["MLM1"]["price"] = 101
    with pytest.raises(FormulaDataUnavailableError) as error:
        await _execute(db, formula)
    assert error.value.read_model == "item_formula_rows"


@pytest.mark.asyncio
async def test_history_real_mongo_observation_writers_and_expiry() -> None:
    from uuid import uuid4

    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import ServerSelectionTimeoutError

    from zeler_sheets.remaining_read_model_writers import (
        record_price_history_observation,
        record_stockout_observation,
    )

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_history_recovery_test_{uuid4().hex}"]
    connected = False
    try:
        try:
            hello = await client.admin.command("hello")
            connected = True
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        assert hello["isWritablePrimary"]
        staging = FakeDb()
        _seed(staging)
        for name in (
            "items",
            "sheets_item_formula_rows",
            "item_status_states",
            "sheets_formula_recovery_jobs",
        ):
            await db[name].insert_many(list(staging[name].documents.values()))
        source = staging["items"].documents["MLM1"]
        for observed in (NOW - timedelta(days=3), NOW):
            await record_price_history_observation(
                db,
                source,
                seller_id=SELLER,
                observed_at=observed,
                source="sheets_event_persistence",
                observation_basis="event_observed",
            )
        await record_stockout_observation(
            db,
            source,
            seller_id=SELLER,
            observed_at=NOW,
            source="sheets_event_persistence",
            observation_basis="event_observed",
        )
        price = await _execute(db, "PRECIOHISTORICO")
        assert price.values == [["MLM1", "Fixture", 100, "active", "NA", "NA", "NA", "NA"]]
        stock = await _execute(db, "TIEMPOSINSTOCK")
        assert stock.values[0][-1] == 0  # only the first observation is known
        active = await _execute(db, "TIEMPOACTIVA")
        assert active.values == [[3]]
        for formula in ("TIEMPOACTIVA", "TIEMPOSINSTOCK", "PRECIOHISTORICO"):
            with pytest.raises(FormulaDataUnavailableError) as error:
                await _execute(db, formula, now=NOW + timedelta(minutes=16))
            assert error.value.read_model == "item_formula_rows"
        assert await db.sheets_read_model_freshness.count_documents({}) == 0
    finally:
        if connected:
            await client.drop_database(db.name)
        client.close()
