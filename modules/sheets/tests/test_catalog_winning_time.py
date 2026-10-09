# ruff: noqa: S105,S106
"""Catalog winning time is computed at read time from acquired observations."""

from __future__ import annotations

import time as perf_time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.catalog_winning_time import (
    CatalogWinningTime,
    catalog_winning_percent_cell,
    catalog_winning_time_cells,
)
from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    FULL_WITHDRAWALS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry

SELLER = "82453304"
START = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
MEXICO = ZoneInfo("America/Mexico_City")


@pytest_asyncio.fixture
async def database() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    try:
        await client.admin.command("ping")
    except ServerSelectionTimeoutError:
        client.close()
        pytest.skip("dedicated local Mongo on port 27028 is unavailable")
    db = client[f"zeler_test_catalogotiempo_{uuid4().hex}"]
    await db.sheets_catalog_competition_observations.create_index(
        [("seller_id", 1), ("item_id", 1), ("observed_at", 1)],
        name="idx_catalog_competition_seller_item_observed",
    )
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


def _observation(
    item_id: str,
    observed_at: datetime,
    status: str,
    quantity: int = 5,
    *,
    seller_id: str = SELLER,
) -> dict[str, Any]:
    return {
        "_id": f"{seller_id}:{item_id}:{observed_at.isoformat()}",
        "seller_id": seller_id,
        "item_id": item_id,
        "catalog_product_id": "MLM9",
        "observed_at": observed_at,
        "status": status,
        "available_quantity": quantity,
        "coverage_basis": "observed_only",
        "source": "meli_price_to_win",
        "schema_version": 1,
    }


async def _seed(db: AsyncIOMotorDatabase[dict[str, Any]], *docs: dict[str, Any]) -> None:
    await db.sheets_catalog_competition_observations.insert_many(list(docs))


def _hours(value: float) -> timedelta:
    return timedelta(hours=value)


@pytest.mark.asyncio
async def test_winning_time_follows_the_legacy_state_mapping_between_observations(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    end = START + _hours(24)
    await _seed(
        database,
        # MLM1: winning carried into the range, then losing, no stock, winning.
        _observation("MLM1", START - _hours(2), "winning"),
        _observation("MLM1", START + _hours(10), "competing"),
        _observation("MLM1", START + _hours(15), "winning", 0),
        _observation("MLM1", START + _hours(20), "winning"),
        _observation("MLM1", end + _hours(1), "competing"),
        # MLM2: sharing first place is winning; an observation at the start counts.
        _observation("MLM2", START, "sharing_first_place"),
        _observation("MLM2", START + _hours(6), "listed"),
        # MLM3: never competes.
        _observation("MLM3", START - _hours(30), "not_listed"),
        # MLM4: first observed inside the range.
        _observation("MLM4", START + _hours(3), "winning"),
        # Another seller's publication is never read.
        _observation("MLM5", START - _hours(1), "winning", seller_id="999"),
    )

    times = await FormulaReadModelRepository(db=database).find_catalog_winning_times(
        seller_id=SELLER, date_from=START, date_to=end
    )

    assert set(times) == {"MLM1", "MLM2", "MLM3", "MLM4"}
    assert times["MLM1"] == CatalogWinningTime(
        winning=_hours(14), with_stock=_hours(19), covered=True, history_from=START - _hours(2)
    )
    assert times["MLM1"].percent == Decimal("73.68")
    assert times["MLM2"] == CatalogWinningTime(
        winning=_hours(6), with_stock=_hours(6), covered=True, history_from=START
    )
    assert times["MLM2"].percent == Decimal("100.00")
    assert times["MLM3"] == CatalogWinningTime(
        winning=timedelta(0),
        with_stock=timedelta(0),
        covered=True,
        history_from=START - _hours(30),
    )
    assert times["MLM3"].percent is None
    assert times["MLM4"].covered is False
    assert times["MLM4"].history_from == START + _hours(3)


@pytest.mark.asyncio
async def test_winning_time_reads_only_the_requested_publications(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await _seed(
        database,
        _observation("MLM1", START - _hours(1), "winning"),
        _observation("MLM2", START - _hours(1), "winning"),
    )

    times = await FormulaReadModelRepository(db=database).find_catalog_winning_times(
        seller_id=SELLER, date_from=START, date_to=START + _hours(2), item_ids=["MLM2", "MLM7"]
    )

    assert list(times) == ["MLM2"]
    assert times["MLM2"].winning == _hours(2)


def test_cells_present_hours_and_percent_or_a_history_gap_message() -> None:
    covered = CatalogWinningTime(
        winning=timedelta(hours=1, minutes=30),
        with_stock=_hours(4),
        covered=True,
        history_from=START,
    )
    never_stocked = CatalogWinningTime(
        winning=timedelta(0), with_stock=timedelta(0), covered=True, history_from=START
    )
    late = CatalogWinningTime(
        winning=_hours(5), with_stock=_hours(5), covered=False, history_from=START
    )

    assert catalog_winning_time_cells(covered, timezone=MEXICO) == [1.5, 4, 37.5]
    assert catalog_winning_time_cells(never_stocked, timezone=MEXICO) == [0, 0, "NA"]
    message = "Sin histórico antes de 2026-09-20 00:00"
    assert catalog_winning_time_cells(late, timezone=MEXICO) == [message] * 3
    assert catalog_winning_time_cells(None, timezone=MEXICO) == ["Sin histórico de catálogo"] * 3
    assert catalog_winning_percent_cell(covered, timezone=UTC) == 37.5
    assert catalog_winning_percent_cell(late, timezone=UTC) == (
        "Sin histórico antes de 2026-09-20 06:00"
    )


def _context(
    formula: str, args: dict[str, Any], *, timezone: str = "America/Mexico_City"
) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id=SELLER,
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
        seller_timezone=timezone,
    )


def _dispatcher(db: Any, now: datetime) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_remaining_phase4_formula_handlers(
            FormulaReadModelRepository(db=db), now_fn=lambda: now
        )
    )


@pytest.mark.asyncio
async def test_catalogotiempo_uses_seller_days_clips_to_now_and_needs_no_legacy_marker(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    # 2026-09-21 in Mexico City starts at 06:00 UTC; "now" is 12:00 local that day.
    day_start = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    now = day_start + _hours(12)
    await _seed(
        database,
        _observation("MLM1", day_start - _hours(5), "winning"),
        _observation("MLM1", day_start + _hours(3), "competing"),
        _observation("MLM2", day_start + _hours(1), "winning"),
    )
    await database.sheets_item_formula_rows.insert_one(
        {
            "_id": "row-1",
            "seller_id": SELLER,
            "item_id": "MLM1",
            "current": {"title": "Catalog winner", "permalink": "https://meli.example/MLM1"},
        }
    )

    result = await _dispatcher(database, now).execute(
        _context(
            "ZELERDATA_CATALOGOTIEMPO",
            {
                "fecha_inicial": "2026-09-21",
                "fecha_final": "2026-09-21",
                "id_publicaciones": "todos",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        [
            "ID PUBLICACION",
            "TITULO",
            "URL",
            "TIEMPO GANANDO CATALOGO EN HORAS",
            "TOTAL DE HORAS DISPONIBLE EN CATALOGO",
            "% DE TIEMPO GANANDO CATALOGO",
        ],
        ["MLM1", "Catalog winner", "https://meli.example/MLM1", 3, 12, 25],
        ["MLM2", "NA", "NA", *(["Sin histórico antes de 2026-09-21 01:00"] * 3)],
    ]
    assert result.recovery is None
    assert result.meta["rows_count"] == 2
    assert result.meta["coverage_basis"] == "observed_only"
    assert result.meta["uncovered_items"] == 1
    assert result.meta["date_to"] == now.isoformat()


@pytest.mark.asyncio
async def test_catalogotiempo_selected_publications_keep_order_and_report_missing_history(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await _seed(database, _observation("MLM1", START - _hours(48), "competing"))

    result = await _dispatcher(database, START + _hours(400)).execute(
        _context(
            "ZELERDATA_CATALOGOTIEMPO",
            {
                "fecha_inicial": "2026-09-20",
                "fecha_final": "2026-09-21",
                "id_publicaciones": ["MLM8", "MLM1"],
                "encabezados": False,
            },
            timezone="UTC",
        )
    )

    assert result.values == [
        ["MLM8", "NA", "NA", *(["Sin histórico de catálogo"] * 3)],
        ["MLM1", "NA", "NA", 0, 48, 0],
    ]


@pytest.mark.asyncio
async def test_retiros_is_declared_unavailable_without_reading_withdrawals() -> None:
    class UnreadDb:
        def __getitem__(self, name: str) -> Any:
            return _ExplodingCollection(name)

    with pytest.raises(FormulaDataUnavailableError) as error:
        await _dispatcher(UnreadDb(), START).execute(
            _context(
                "ZELERDATA_RETIROS",
                {"fecha_inicial": "2026-09-01", "fecha_final": "2026-09-30"},
            )
        )

    assert error.value.read_model == FULL_WITHDRAWALS_READ_MODEL
    assert "Mercado Libre no expone el identificador del retiro" in error.value.message
    assert "no está disponible" in error.value.message
    assert "freshness" not in error.value.message


class _ExplodingCollection:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attribute: str) -> Any:
        raise AssertionError(f"{self.name}.{attribute} must not be read")


@pytest.mark.asyncio
async def test_thirty_day_window_over_a_pilot_sized_history_stays_fast(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    """About 280k observations of 940 publications, like the pilot on 2026-10-09."""
    now = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
    first = now - timedelta(days=31)
    statuses = ("not_listed",) * 8 + ("winning", "competing")
    batch: list[dict[str, Any]] = []
    item_ids = [f"MLM{1_000_000 + index}" for index in range(940)]
    for index, item_id in enumerate(item_ids):
        for step in range(300):
            batch.append(
                _observation(
                    item_id,
                    first + timedelta(minutes=index % 120 + step * 150),
                    statuses[(index + step // 40) % len(statuses)],
                    step % 7,
                )
            )
        if len(batch) >= 30_000:
            await _seed(database, *batch)
            batch = []
    if batch:
        await _seed(database, *batch)
    repository = FormulaReadModelRepository(db=database)

    elapsed = []
    for _ in range(2):
        started = perf_time.perf_counter()
        times = await repository.find_catalog_winning_times(
            seller_id=SELLER, date_from=now - timedelta(days=30), date_to=now, item_ids=item_ids
        )
        elapsed.append(perf_time.perf_counter() - started)

    assert len(times) == 940
    assert all(value.covered for value in times.values())
    # Measured near 0.4 s locally; the bound only catches a non-indexed plan.
    assert min(elapsed) < 3.0
