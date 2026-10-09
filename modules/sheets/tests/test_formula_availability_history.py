# ruff: noqa: S106

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.availability_history import record_availability_observation
from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    ITEM_STATUS_STATES_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.recovery import RECOVERABLE_MODELS
from zeler_sheets.formulas.registry import FormulaRegistry

SELLER = "82453304"
# Friday 2026-10-09 15:15 in Mexico City (UTC-6).
NOW = datetime(2026, 10, 9, 21, 15, tzinfo=UTC)
MEXICO = "America/Mexico_City"


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    database = client[f"zeler_avail_formula_{uuid4().hex}"]
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


async def _seed(db: Any) -> None:
    await db["items"].insert_many(
        [
            {"_id": "MLM1", "seller_id": SELLER, "title": "Uno", "permalink": "https://x/MLM1"},
            {
                "_id": "MLM2",
                "seller_id": SELLER,
                "title": "Dos",
                "permalink": "https://x/MLM2",
                "variations": [{"id": 11, "attributes": []}, {"id": 22, "attributes": []}],
            },
            {"_id": "MLM3", "seller_id": SELLER, "title": "Tres", "permalink": "https://x/MLM3"},
            {"_id": "MLM9", "seller_id": "999", "title": "Ajeno", "permalink": "https://x/MLM9"},
        ]
    )

    def single(stock: int, *, item_id: str = "MLM1", seller: str = SELLER) -> dict[str, Any]:
        return {
            "_id": item_id,
            "seller_id": seller,
            "status": "active",
            "available_quantity": stock,
            "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-1"}],
        }

    async def record(item: dict[str, Any], observed_at: datetime) -> None:
        await record_availability_observation(
            db,
            item,
            seller_id=str(item["seller_id"]),
            observed_at=observed_at,
            source="sheets_event_persistence",
        )

    # MLM1: available from local Oct 1, out Oct 3, back Oct 4 (all local midnights).
    await record(single(5), datetime(2026, 10, 1, 6, 0, tzinfo=UTC))
    await record(single(0), datetime(2026, 10, 3, 6, 0, tzinfo=UTC))
    await record(single(2), datetime(2026, 10, 4, 6, 0, tzinfo=UTC))
    # MLM2: first seen Oct 5 at local noon; red in stock, blue out.
    await record(
        {
            "_id": "MLM2",
            "seller_id": SELLER,
            "status": "active",
            "available_quantity": 1,
            "variations": [
                {
                    "id": 11,
                    "available_quantity": 1,
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-RED"}],
                },
                {
                    "id": 22,
                    "available_quantity": 0,
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-BLUE"}],
                },
            ],
        },
        datetime(2026, 10, 5, 18, 0, tzinfo=UTC),
    )
    # Another seller's history must never leak.
    await record(single(3, item_id="MLM9", seller="999"), datetime(2026, 9, 1, tzinfo=UTC))


async def _mark_status_observations_fresh(db: Any) -> None:
    await db["sheets_read_model_freshness"].insert_one(
        {
            "_id": f"{SELLER}:{ITEM_STATUS_STATES_READ_MODEL}",
            "seller_id": SELLER,
            "read_model": ITEM_STATUS_STATES_READ_MODEL,
            "state": "fresh",
            "date_from": datetime(2026, 6, 7, tzinfo=UTC),
            "fresh_until": NOW + timedelta(days=1),
            "reconciled_until": None,
            "last_event_synced_at": NOW,
            "coverage_basis": "observed_only",
            "source": "zelerdata_observed_read_model",
            "updated_at": NOW,
            "schema_version": 1,
        }
    )


def _dispatcher(db: Any) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_remaining_phase4_formula_handlers(
            FormulaReadModelRepository(db=db), now_fn=lambda: NOW
        )
    )


def _context(formula: str, args: dict[str, Any]) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id=SELLER,
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
        seller_timezone=MEXICO,
    )


@pytest.mark.asyncio
async def test_tiempo_stock_activo_computes_observed_time_and_names_missing_history(
    db: Any,
) -> None:
    await _seed(db)
    await _mark_status_observations_fresh(db)

    result = await _dispatcher(db).execute(
        _context(
            "ZELERDATA_TIEMPOSTOCKACTIVO",
            {"fecha_inicial": "2026-10-01", "fecha_final": "2026-10-09", "encabezados": "si"},
        )
    )

    # Oct 1 00:00 local to now is 207.25 h; MLM1 was out of stock for 24 h of it.
    assert result.values == [
        [
            "ID PUBLICACION",
            "SKU",
            "TITULO",
            "URL",
            "TIEMPO ACTIVA",
            "TIEMPO TOTAL",
            "% TIEMPO ACTIVA",
        ],
        ["MLM1", "SKU-1", "Uno", "https://x/MLM1", 183.25, 207.25, 88.42],
        [
            "MLM2",
            "SKU-RED",
            "Dos",
            "https://x/MLM2",
            "Sin histórico antes de 2026-10-05 12:00",
            "NA",
            "NA",
        ],
        [
            "MLM2",
            "SKU-BLUE",
            "Dos",
            "https://x/MLM2",
            "Sin histórico antes de 2026-10-05 12:00",
            "NA",
            "NA",
        ],
        ["MLM3", "NA", "Tres", "https://x/MLM3", "Sin histórico", "NA", "NA"],
    ]
    assert result.recovery is None
    assert result.meta == {
        "rows_count": 4,
        "rows_without_history": 3,
        "columns": "availability_history",
    }


@pytest.mark.asyncio
async def test_tiempo_stock_activo_serves_covered_variations_and_selected_ids(db: Any) -> None:
    await _seed(db)
    await _mark_status_observations_fresh(db)

    result = await _dispatcher(db).execute(
        _context(
            "ZELERDATA_TIEMPOSTOCKACTIVO",
            {
                "fecha_inicial": "2026-10-06",
                "fecha_final": "2026-10-31",
                "id_publicaciones": [["MLM2"], ["MLM404"], ["MLM9"]],
            },
        )
    )

    # Oct 6 00:00 local to now is 87.25 h; the range end is clipped to now.
    assert result.values == [
        ["MLM2", "SKU-RED", "Dos", "https://x/MLM2", 87.25, 87.25, 100],
        ["MLM2", "SKU-BLUE", "Dos", "https://x/MLM2", 0, 87.25, 0],
        ["MLM404", "NA", "NA", "NA", "Sin histórico", "NA", "NA"],
        ["MLM9", "NA", "NA", "NA", "Sin histórico", "NA", "NA"],
    ]


@pytest.mark.asyncio
async def test_semanas_con_stock_reports_iso_weeks_from_the_log(db: Any) -> None:
    await _seed(db)
    await _mark_status_observations_fresh(db)
    dispatcher = _dispatcher(db)
    args = {"fecha_inicial": "2026-09-28", "fecha_final": "2026-10-18", "encabezados": "si"}

    every_sku = await dispatcher.execute(_context("ZELERDATA_SEMANASCONSTOCK", args))
    blue = await dispatcher.execute(
        _context("ZELERDATA_SEMANASCONSTOCK", {**args, "skus": "sku-blue", "encabezados": ""})
    )

    assert every_sku.values == [
        ["ID PUBLICACION", "SKU", "TITULO", "2026 - 40", "2026 - 41", "2026 - 42"],
        ["MLM1", "SKU-1", "Uno", "Con stock", "Con stock", "NA"],
        ["MLM2", "SKU-RED", "Dos", "Sin histórico antes de 2026-10-05 12:00", "Con stock", "NA"],
        ["MLM2", "SKU-BLUE", "Dos", "Sin histórico antes de 2026-10-05 12:00", "Sin stock", "NA"],
        ["MLM3", "NA", "Tres", "Sin histórico", "Sin histórico", "NA"],
    ]
    # Every row lacks history at the range start (Sep 28), even MLM1 (first seen Oct 1).
    assert every_sku.meta == {
        "rows_count": 4,
        "rows_without_history": 4,
        "columns": "weekly_stock_presence",
    }
    assert blue.values == [
        ["MLM2", "SKU-BLUE", "Dos", "Sin histórico antes de 2026-10-05 12:00", "Sin stock", "NA"]
    ]


@pytest.mark.asyncio
async def test_history_formulas_serve_more_than_a_thousand_publications(db: Any) -> None:
    await db["items"].insert_many(
        [
            {"_id": f"MLM{index}", "seller_id": SELLER, "title": "x", "permalink": "u"}
            for index in range(1001)
        ]
    )
    await _mark_status_observations_fresh(db)
    dispatcher = _dispatcher(db)

    for formula in ("ZELERDATA_TIEMPOSTOCKACTIVO", "ZELERDATA_SEMANASCONSTOCK"):
        result = await dispatcher.execute(
            _context(formula, {"fecha_inicial": "2026-10-01", "fecha_final": "2026-10-09"})
        )
        assert result.meta["rows_count"] == 1001
        assert len(result.values) == 1001


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", ["ZELERDATA_TIEMPOSTOCKACTIVO", "ZELERDATA_SEMANASCONSTOCK"])
async def test_history_formulas_require_live_status_observations(db: Any, formula: str) -> None:
    await _seed(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await _dispatcher(db).execute(
            _context(formula, {"fecha_inicial": "2026-10-01", "fecha_final": "2026-10-09"})
        )

    assert error.value.read_model == ITEM_STATUS_STATES_READ_MODEL
    assert ITEM_STATUS_STATES_READ_MODEL not in RECOVERABLE_MODELS
    assert "disponibilidad" in str(error.value)
