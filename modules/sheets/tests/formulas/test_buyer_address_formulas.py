# ruff: noqa: S106

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import FormulaDispatcher, FormulaExecutionContext
from zeler_sheets.formulas.handlers_orders_questions import build_order_question_formula_handlers
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry

ORDER_LINE_LEGACY_HEADERS = [
    "Fecha",
    "ID Orden",
    "Título",
    "SKU",
    "ID Publicación",
    "Unidades Vendidas",
    "Precio",
    "ID Carrito",
    "% Comisión",
    "Comisión",
    "Costo Por Unidad",
    "Costo De Envío",
    "Status",
]
BUYER_ADDRESS_HEADERS = [
    "Nombre Comprador",
    "Calle",
    "Número",
    "Colonia",
    "Código Postal",
    "Ciudad",
    "Estado",
    "País",
]
APPROVED_ADDRESS_VALUES = [
    "SNAPSHOT_BUYER_OK",
    "SNAPSHOT_STREET_OK",
    "SNAPSHOT_NUMBER_OK",
    "SNAPSHOT_NEIGHBORHOOD_OK",
    "SNAPSHOT_ZIP_OK",
    "SNAPSHOT_CITY_OK",
    "SNAPSHOT_STATE_OK",
    "SNAPSHOT_COUNTRY_OK",
]
LEAK_SENTINELS = [
    "ORDER_BUYER_MUST_NOT_LEAK",
    "ORDER_STREET_MUST_NOT_LEAK",
    "BUYER_ID_MUST_NOT_DISPLAY",
    "PACK_ID_MUST_NOT_DISPLAY",
    "PACK_RECEIVER_MUST_NOT_LEAK",
    "RAW_RECEIVER_PHONE_MUST_NOT_LEAK",
]


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: _sort_value(doc.get(key)), reverse=direction < 0)
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None
        self.last_find_projection: dict[str, Any] | None = None
        self.find_calls: list[dict[str, dict[str, Any] | None]] = []

    def find(
        self,
        filter_spec: dict[str, Any],
        projection: dict[str, Any] | None = None,
    ) -> FakeCursor:
        self.last_find_filter = dict(filter_spec)
        self.last_find_projection = dict(projection) if projection is not None else None
        self.find_calls.append(
            {
                "filter": dict(filter_spec),
                "projection": dict(projection) if projection is not None else None,
            }
        )
        docs = [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        if projection is not None:
            docs = [_project(doc, projection) for doc in docs]
        return FakeCursor(docs)


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


@pytest.mark.asyncio
async def test_order_formulas_use_projected_shipment_snapshot_for_exact_buyer_fields() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "order-allowed": _order_doc(
            "order-allowed",
            shipment_id="shipment-allowed",
            buyer_id="BUYER_ID_MUST_NOT_DISPLAY",
            items=[
                {
                    "sku": "sku-allowed",
                    "item_id": "MLA-ALLOWED",
                    "title": "Allowed item",
                    "quantity": 1,
                    "unit_price": 10,
                }
            ],
        )
        | {
            "buyer_name": "ORDER_BUYER_MUST_NOT_LEAK",
            "buyer_address": {"street_name": "ORDER_STREET_MUST_NOT_LEAK"},
            "pack_id": "PACK_ID_MUST_NOT_DISPLAY",
            "pack": {"receiver_name": "PACK_RECEIVER_MUST_NOT_LEAK"},
        }
    }
    db["shipments"].documents = {
        "shipment-allowed": _shipment_doc(
            "shipment-allowed",
            receiver_address=_receiver_address_snapshot(),
        )
        | {"phone": "RAW_RECEIVER_PHONE_MUST_NOT_LEAK"},
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENES",
            {
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "compradores": "si",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_HEADERS,
        [
            "2026-05-10T10:30:00+00:00",
            "order-allowed",
            "Allowed item",
            "SKU-ALLOWED",
            "MLA-ALLOWED",
            1,
            10,
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "paid",
            *APPROVED_ADDRESS_VALUES,
        ],
    ]
    assert result.meta == {
        "orders_count": 1,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "columns": "legacy_order_lines_with_buyers",
    }
    shipment_filter = {
        "seller_id": "seller-1",
        "_id": {"$in": ["shipment-allowed"]},
    }
    assert {"filter": shipment_filter, "projection": _shipment_projection()} in db[
        "shipments"
    ].find_calls
    _assert_no_leaks(result.values, result.meta)


@pytest.mark.asyncio
async def test_order_sku_formula_returns_na_for_missing_blank_or_unauthorized_snapshots() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "missing-snapshot": _order_doc(
            "missing-snapshot",
            shipment_id="shipment-missing",
            items=[{"sku": "sku-a", "item_id": "MLA-A", "title": "Missing", "quantity": 1}],
        ),
        "blank-snapshot": _order_doc(
            "blank-snapshot",
            shipment_id="shipment-blank",
            items=[{"sku": "sku-b", "item_id": "MLA-B", "title": "Blank", "quantity": 1}],
        ),
        "wrong-seller-snapshot": _order_doc(
            "wrong-seller-snapshot",
            shipment_id="shipment-wrong-seller",
            items=[{"sku": "sku-c", "item_id": "MLA-C", "title": "Wrong seller", "quantity": 1}],
        ),
    }
    db["shipments"].documents = {
        "shipment-blank": _shipment_doc(
            "shipment-blank",
            receiver_address={"name": "", "street_name": "   ", "city": None},
        ),
        "shipment-wrong-seller": _shipment_doc(
            "shipment-wrong-seller",
            seller_id="seller-2",
            receiver_address=_receiver_address_snapshot(name="WRONG_SELLER_MUST_NOT_LEAK"),
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_ORDENESPORSKU",
            {
                "skus": [["sku-a"], ["sku-b"], ["sku-c"]],
                "fecha_inicial": "2026-05-10",
                "fecha_final": "2026-05-10",
                "estado": "paid",
                "compradores": "si",
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ORDER_LINE_LEGACY_HEADERS + BUYER_ADDRESS_HEADERS,
        [
            "2026-05-10T10:30:00+00:00",
            "missing-snapshot",
            "Missing",
            "SKU-A",
            "MLA-A",
            1,
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "paid",
            *(["NA"] * len(BUYER_ADDRESS_HEADERS)),
        ],
        [
            "2026-05-10T10:30:00+00:00",
            "blank-snapshot",
            "Blank",
            "SKU-B",
            "MLA-B",
            1,
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "paid",
            *(["NA"] * len(BUYER_ADDRESS_HEADERS)),
        ],
        [
            "2026-05-10T10:30:00+00:00",
            "wrong-seller-snapshot",
            "Wrong seller",
            "SKU-C",
            "MLA-C",
            1,
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "NA",
            "paid",
            *(["NA"] * len(BUYER_ADDRESS_HEADERS)),
        ],
    ]
    assert result.meta == {
        "orders_count": 3,
        "status_filter": "paid",
        "buyer_filter_count": 0,
        "sku_filter_count": 3,
        "columns": "legacy_order_lines_with_buyers",
    }
    assert "WRONG_SELLER_MUST_NOT_LEAK" not in repr(result.values)
    assert "WRONG_SELLER_MUST_NOT_LEAK" not in repr(result.meta)


@pytest.mark.asyncio
async def test_compradores_returns_only_eight_approved_fields_and_safe_metadata() -> None:
    db = FakeDb()
    db["orders"].documents = {
        "pack-order": _order_doc(
            "pack-order",
            shipment_id="shipment-allowed",
            buyer_id="BUYER_ID_MUST_NOT_DISPLAY",
        )
        | {
            "pack_id": "PACK_ID_MUST_NOT_DISPLAY",
            "buyer_name": "ORDER_BUYER_MUST_NOT_LEAK",
            "receiver_address": {"name": "ORDER_RECEIVER_MUST_NOT_LEAK"},
        },
        "missing-order": _order_doc("missing-order", shipment_id="shipment-missing"),
    }
    db["shipments"].documents = {
        "shipment-allowed": _shipment_doc(
            "shipment-allowed",
            receiver_address=_receiver_address_snapshot(),
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_COMPRADORES",
            {"id_ordenes": [["pack-order"], ["missing-order"]], "encabezados": "si"},
        )
    )

    assert result.values == [
        BUYER_ADDRESS_HEADERS,
        APPROVED_ADDRESS_VALUES,
        ["NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA"],
    ]
    assert result.meta == {
        "orders_count": 2,
        "address_available": 1,
        "address_missing": 1,
        "columns": "buyer_address_snapshot",
    }
    assert db["orders"].last_find_filter == {
        "seller_id": "seller-1",
        "_id": {"$in": ["pack-order", "missing-order"]},
    }
    _assert_no_leaks(result.values, result.meta)


def _dispatcher(db: FakeDb) -> FormulaDispatcher:
    return FormulaDispatcher(
        build_order_question_formula_handlers(FormulaReadModelRepository(db=db))
    )


def _context(formula: str, args: dict[str, Any]) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="seller-1",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
    )


def _order_doc(
    order_id: str,
    *,
    shipment_id: str,
    buyer_id: str = "buyer-synthetic",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": "seller-1",
        "buyer_id": buyer_id,
        "status": "paid",
        "date_created": datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
        "shipment_id": shipment_id,
        "total_amount": 10,
        "items": items or [],
        "schema_version": 1,
    }


def _shipment_doc(
    shipment_id: str,
    *,
    seller_id: str = "seller-1",
    receiver_address: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "_id": shipment_id,
        "seller_id": seller_id,
        "receiver_address": receiver_address,
        "schema_version": 1,
    }


def _receiver_address_snapshot(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "SNAPSHOT_BUYER_OK",
        "street_name": "SNAPSHOT_STREET_OK",
        "street_number": "SNAPSHOT_NUMBER_OK",
        "neighborhood": "SNAPSHOT_NEIGHBORHOOD_OK",
        "zip_code": "SNAPSHOT_ZIP_OK",
        "city": "SNAPSHOT_CITY_OK",
        "state": "SNAPSHOT_STATE_OK",
        "country": "SNAPSHOT_COUNTRY_OK",
    } | overrides


def _matches(doc: Mapping[str, Any], filter_spec: Mapping[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        value = doc.get(key)
        if isinstance(expected, Mapping):
            try:
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
            except TypeError:
                return False
            continue
        if value != expected:
            return False
    return True


def _project(doc: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, include in projection.items():
        if not include:
            continue
        if "." not in key and key in doc:
            projected[key] = doc[key]
            continue
        root, _, leaf = key.partition(".")
        nested = doc.get(root)
        if isinstance(nested, Mapping) and leaf in nested:
            projected.setdefault(root, {})[leaf] = nested[leaf]
    return projected


def _shipment_projection() -> dict[str, int]:
    return {
        "_id": 1,
        "receiver_address.name": 1,
        "receiver_address.street_name": 1,
        "receiver_address.street_number": 1,
        "receiver_address.neighborhood": 1,
        "receiver_address.zip_code": 1,
        "receiver_address.city": 1,
        "receiver_address.state": 1,
        "receiver_address.country": 1,
    }


def _assert_no_leaks(values: list[list[Any]], meta: dict[str, Any]) -> None:
    output = repr(values)
    diagnostics = repr(meta)
    for sentinel in LEAK_SENTINELS:
        assert sentinel not in output
        assert sentinel not in diagnostics


def _sort_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value
