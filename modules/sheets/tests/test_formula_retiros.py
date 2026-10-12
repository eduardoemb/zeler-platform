# ruff: noqa: S106
"""ZELERDATA_RETIROS pairs notified Full operations at read time."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.full_withdrawals import pair_full_withdrawals
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    RETIROS_HEADERS,
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.matrix_contracts import RETIROS_VISIBLE_HEADERS
from zeler_sheets.formulas.read_models import (
    FULL_WITHDRAWALS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.full_operations import FULL_OPERATIONS_COLLECTION, record_full_operation

ROOT = Path(__file__).resolve().parents[3]
SELLER = "82453304"
NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
COVERAGE_START = "2026-08-29T16:15:00Z"
EXPECTED_HEADERS = [
    "ESTADO RETIRO",
    "ID OPERACION",
    "CODIGO ML",
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "UNIDADES SOLICITADAS",
    "FECHA DE CREACION",
    "FECHA DE ENTREGA",
    "UNIDADES ENTREGADAS",
]


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
    db = client[f"zeler_test_retiros_{uuid4().hex}"]
    for index in json.loads((ROOT / "infra/mongo/indexes/sheets_full_operations.json").read_text()):
        await db[FULL_OPERATIONS_COLLECTION].create_index(
            list(index["keys"].items()), **index["options"]
        )
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


def op(
    operation_id: int,
    kind: str,
    created: str,
    quantity: int,
    *,
    inventory: str = "INVABC",
    seller: int = int(SELLER),
) -> dict[str, Any]:
    sign = 1 if kind == "WITHDRAWAL_RESERVATION" else -1
    detail: dict[str, Any] = {
        "available_quantity": -quantity if sign > 0 else 0,
        "not_available_quantity": sign * quantity,
        "not_available_detail": [{"status": "withdrawal", "quantity": sign * quantity}],
    }
    if not kind.startswith("WITHDRAWAL_"):
        detail = {"available_quantity": -quantity, "not_available_quantity": 0}
    return {
        "id": operation_id,
        "seller_id": seller,
        "date_created": created,
        "type": kind,
        "inventory_id": inventory,
        "detail": detail,
        "result": {},
        "external_references": [],
    }


async def notify(
    db: AsyncIOMotorDatabase[dict[str, Any]], *operations: dict[str, Any], covered: bool = True
) -> None:
    if covered:
        # The first notification the platform saw, as in production (2026-08-29).
        operations = (op(1, "SALE_CONFIRMATION", COVERAGE_START, 1), *operations)
    for operation in operations:
        await record_full_operation(
            db,
            seller_id=SELLER,
            operation_id=str(operation["id"]),
            operation=operation,
            now=NOW,
        )


async def publication(
    db: AsyncIOMotorDatabase[dict[str, Any]],
    item_id: str,
    inventory_id: str,
    *,
    sku: str | None,
    title: str,
    seller: str = SELLER,
    variation_id: str | None = None,
) -> None:
    await db.sheets_item_formula_rows.insert_one(
        {
            "_id": f"{seller}:{item_id}:{variation_id}",
            "seller_id": seller,
            "item_id": item_id,
            "variation_id": variation_id,
            "inventory_id": inventory_id,
            "sku": sku,
            "normalized_sku": (sku or "").upper(),
            "current": {"title": title, "inventory_id": inventory_id},
            "schema_version": 1,
        }
    )


def context(
    fecha_inicial: str, fecha_final: str, *, encabezados: str = ""
) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required("ZELERDATA_RETIROS"),
        cuenta="HOPEMOB",
        seller_id=SELLER,
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args={
            "fecha_inicial": fecha_inicial,
            "fecha_final": fecha_final,
            "encabezados": encabezados,
        },
        request_id="req-1",
        seller_timezone="America/Mexico_City",
    )


async def retiros(
    db: AsyncIOMotorDatabase[dict[str, Any]],
    fecha_inicial: str = "2026-09-01",
    fecha_final: str = "2026-09-30",
    *,
    encabezados: str = "",
) -> Any:
    dispatcher = FormulaDispatcher(
        build_remaining_phase4_formula_handlers(
            FormulaReadModelRepository(db=db), now_fn=lambda: NOW
        )
    )
    return await dispatcher.execute(context(fecha_inicial, fecha_final, encabezados=encabezados))


def test_headers_keep_the_legacy_order_with_the_new_identity_and_delivered_columns() -> None:
    assert RETIROS_HEADERS == EXPECTED_HEADERS
    assert list(RETIROS_VISIBLE_HEADERS) == EXPECTED_HEADERS


@pytest.mark.asyncio
async def test_reservation_paired_with_its_delivery_fills_the_ten_columns(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await notify(
        database,
        op(1001, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 6),
        op(1002, "WITHDRAWAL_DELIVERY", "2026-09-04T18:30:00Z", 6),
    )
    await publication(database, "MLM111", "INVABC", sku="SKU-1", title="Termo 1L")

    result = await retiros(database, encabezados="si")

    assert result.values == [
        EXPECTED_HEADERS,
        [
            "Entregado",
            "1001",
            "INVABC",
            "MLM111",
            "SKU-1",
            "Termo 1L",
            6,
            "2026-09-02T09:00:00-06:00",
            "2026-09-04T12:30:00-06:00",
            6,
        ],
    ]
    assert result.recovery is None
    assert result.meta["rows_count"] == 1
    assert result.meta["coverage_basis"] == "observed_only"
    assert result.meta["coverage_from"] == "2026-08-29T16:15:00+00:00"
    assert result.meta["unmatched_operations"] == {}


@pytest.mark.asyncio
async def test_partial_cancellation_keeps_the_withdrawal_reserved_until_delivery(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await notify(
        database,
        op(1101, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 10),
        op(1102, "WITHDRAWAL_CANCELATION", "2026-09-03T15:00:00Z", 3),
    )

    reserved = await retiros(database)
    await notify(database, op(1103, "WITHDRAWAL_DELIVERY", "2026-09-05T15:00:00Z", 7))
    delivered = await retiros(database)

    assert reserved.values == [
        [
            "Reservado",
            "1101",
            "INVABC",
            "NA",
            "NA",
            "NA",
            10,
            "2026-09-02T09:00:00-06:00",
            "NA",
            0,
        ]
    ]
    assert delivered.values[0][0] == "Entregado"
    assert delivered.values[0][6] == 10
    assert delivered.values[0][8:] == ["2026-09-05T09:00:00-06:00", 7]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("closing", "status"),
    [
        ("WITHDRAWAL_CANCELATION", "Cancelado"),
        ("WITHDRAWAL_DISCARDED", "Descartado"),
        ("WITHDRAWAL_REMOVAL", "Abandonado"),
    ],
)
async def test_a_withdrawal_closed_without_delivery_shows_how_it_ended(
    database: AsyncIOMotorDatabase[dict[str, Any]], closing: str, status: str
) -> None:
    await notify(
        database,
        op(1201, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 4),
        op(1202, closing, "2026-09-20T15:00:00Z", 4),
    )

    result = await retiros(database)

    assert [row[0] for row in result.values] == [status]
    assert result.values[0][8:] == ["NA", 0]


@pytest.mark.asyncio
async def test_unknown_publication_and_another_sellers_inventory_are_not_borrowed(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await notify(
        database,
        op(1301, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 2, inventory="INVOWN"),
        op(1302, "WITHDRAWAL_RESERVATION", "2026-09-03T15:00:00Z", 2, inventory="INVGONE"),
        op(1303, "WITHDRAWAL_RESERVATION", "2026-09-04T15:00:00Z", 2, inventory="INVOTHER"),
    )
    # A catalog listing and its original share one inventory.
    await publication(database, "MLM2", "INVOWN", sku="SKU-2", title="Silla")
    await publication(database, "MLM1", "INVOWN", sku="SKU-2", title="Silla catálogo")
    await publication(database, "MLM9", "INVOTHER", sku="X", title="Ajena", seller="42")

    result = await retiros(database)

    assert [row[:6] for row in result.values] == [
        ["Reservado", "1301", "INVOWN", "MLM1, MLM2", "SKU-2", "Silla catálogo"],
        ["Reservado", "1302", "INVGONE", "NA", "NA", "NA"],
        ["Reservado", "1303", "INVOTHER", "NA", "NA", "NA"],
    ]


@pytest.mark.asyncio
async def test_operations_of_another_seller_never_reach_the_table(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    foreign = op(1401, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 2, seller=42)
    await notify(database, foreign)

    result = await retiros(database)

    assert result.values == []
    assert await database[FULL_OPERATIONS_COLLECTION].count_documents({}) == 0


@pytest.mark.asyncio
async def test_closings_without_an_observed_reservation_do_not_invent_rows(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await notify(
        database,
        # A delivery of a reservation made before the subscription started.
        op(1501, "WITHDRAWAL_DELIVERY", "2026-09-01T15:00:00Z", 5),
        op(1502, "WITHDRAWAL_RESERVATION", "2026-09-02T15:00:00Z", 3),
        # More units than the observed reservation holds: not its delivery.
        op(1503, "WITHDRAWAL_DELIVERY", "2026-09-03T15:00:00Z", 8),
    )

    result = await retiros(database)

    assert [row[:2] + row[6:] for row in result.values] == [
        ["Reservado", "1502", 3, "2026-09-02T09:00:00-06:00", "NA", 0]
    ]
    assert result.meta["unmatched_operations"] == {"WITHDRAWAL_DELIVERY": 2}


@pytest.mark.asyncio
async def test_coverage_starts_at_the_first_notification_and_earlier_ranges_say_so(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    await notify(
        database,
        op(1601, "WITHDRAWAL_RESERVATION", "2026-08-30T15:00:00Z", 2),
        op(1602, "WITHDRAWAL_RESERVATION", "2026-09-10T15:00:00Z", 3),
    )
    notice = ["Sin histórico antes de 2026-08-29 10:15", *(["NA"] * 9)]

    after = await retiros(database, "2026-09-01", "2026-09-30")
    spanning = await retiros(database, "2026-08-01", "2026-09-30")
    before = await retiros(database, "2026-07-01", "2026-07-31", encabezados="si")

    assert [row[1] for row in after.values] == ["1602"]
    assert after.meta["range_covered"] is True
    assert spanning.meta["range_covered"] is False
    assert spanning.values[0] == notice
    assert [row[1] for row in spanning.values[1:]] == ["1601", "1602"]
    assert spanning.meta["rows_count"] == 2
    assert before.values == [EXPECTED_HEADERS, notice]
    assert before.meta["rows_count"] == 0


@pytest.mark.asyncio
async def test_without_any_observed_notification_retiros_is_unavailable_without_recovery(
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    # Operations collected by the onboarding search carry no observed coverage.
    await database[FULL_OPERATIONS_COLLECTION].insert_one(
        {
            "_id": f"{SELLER}:1701",
            "operation_id": "1701",
            "seller_id": SELLER,
            "inventory_id": "INVABC",
            "type": "WITHDRAWAL_RESERVATION",
            "date_created": datetime(2026, 9, 2, tzinfo=UTC),
            "detail": {"not_available_detail": [{"status": "withdrawal", "quantity": 2}]},
            "source": "meli_full_operations_api",
            "schema_version": 1,
        }
    )

    with pytest.raises(FormulaDataUnavailableError) as error:
        await retiros(database)

    assert error.value.read_model == FULL_WITHDRAWALS_READ_MODEL
    assert "notificación" in error.value.message


def test_two_open_reservations_prefer_the_one_whose_units_match_and_flag_the_guess() -> None:
    operations = [
        _stored(1, "WITHDRAWAL_RESERVATION", datetime(2026, 9, 1, tzinfo=UTC), 3),
        _stored(2, "WITHDRAWAL_RESERVATION", datetime(2026, 9, 2, tzinfo=UTC), 5),
        _stored(3, "WITHDRAWAL_DELIVERY", datetime(2026, 9, 3, tzinfo=UTC), 5),
        _stored(4, "WITHDRAWAL_CANCELATION", datetime(2026, 9, 4, tzinfo=UTC), 1),
    ]

    withdrawals, unmatched = pair_full_withdrawals(operations)

    first, second = withdrawals
    assert (second.status, second.delivered, second.approximate) == ("Entregado", 5, True)
    # Without an exact match the oldest open reservation absorbs the units.
    assert (first.status, first.canceled, first.remaining) == ("Reservado", 1, 2)
    assert first.approximate is False
    assert unmatched == []


def test_several_deliveries_complete_one_reservation_at_the_last_delivery() -> None:
    withdrawals, _ = pair_full_withdrawals(
        [
            _stored(1, "WITHDRAWAL_RESERVATION", datetime(2026, 9, 1, tzinfo=UTC), 10),
            _stored(2, "WITHDRAWAL_DELIVERY", datetime(2026, 9, 2, tzinfo=UTC), 4),
            _stored(3, "WITHDRAWAL_DELIVERY", datetime(2026, 9, 3, tzinfo=UTC), 6),
        ]
    )

    (withdrawal,) = withdrawals
    assert withdrawal.status == "Entregado"
    assert withdrawal.delivered == 10
    assert withdrawal.delivered_at == datetime(2026, 9, 3, tzinfo=UTC)


def _stored(operation_id: int, kind: str, created: datetime, quantity: int) -> dict[str, Any]:
    sign = 1 if kind == "WITHDRAWAL_RESERVATION" else -1
    return {
        "operation_id": str(operation_id),
        "inventory_id": "INV",
        "type": kind,
        "date_created": created,
        "detail": {"not_available_detail": [{"status": "withdrawal", "quantity": sign * quantity}]},
    }
