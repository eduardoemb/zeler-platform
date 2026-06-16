# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    build_item_shipping_catalog_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL,
    CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ORDERS_READ_MODEL,
    SHIPMENTS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(
                key=lambda doc: str(_dotted_value(doc, key) or ""), reverse=direction < 0
            )
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.last_find_filter = dict(filter_spec)
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        del projection
        self.last_find_filter = dict(filter_spec)
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_item_catalog_handlers_use_local_rows_and_catalog_snapshots() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    _mark_read_model_fresh(db, CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL)
    _mark_read_model_fresh(db, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": {
            "_id": "seller-1:SKU-1:MLA1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {
                "title": "Super item",
                "status": "active",
                "available_quantity": 7,
                "base_price": Decimal("120"),
                "catalog_product_id": "CAT-1",
                "tags": ["supermarket_eligible", "catalog_listing"],
                "dimensions": {"length": 30, "height": 20, "width": 10},
            },
        },
        "seller-1:SKU-2:MLA2": {
            "_id": "seller-1:SKU-2:MLA2",
            "seller_id": "seller-1",
            "sku": "sku-2",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "current": {
                "title": "Regular item",
                "status": "active",
                "available_quantity": 3,
                "tags": ["catalog_suggestion"],
                "dimensions": {"length": 11, "height": 22},
            },
        },
    }
    db["sheets_catalog_product_snapshots"].documents = {
        "seller-1:CAT-1": {
            "_id": "seller-1:CAT-1",
            "seller_id": "seller-1",
            "catalog_product_id": "CAT-1",
            "title": "Catalog title",
            "description": "Catalog description",
            "image_url": "https://img.example/catalog.jpg",
            "attributes": {"BRAND": "Acme", "MODEL": "M1", "GTIN": "789"},
        }
    }
    db["sheets_catalog_buybox_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "title": "Super item",
            "item_id": "MLA1",
            "catalog_product_id": "CAT-1",
            "available_quantity": 7,
            "buybox_status": "winning",
            "price": Decimal("120"),
            "winning_price": Decimal("118"),
            "competitor_count": 2,
            "only_competitor": "No",
        }
    }
    dispatcher = _dispatcher(db)

    supermercado = await dispatcher.execute(
        _context("ZELERDATA_SUPERMERCADO", {"id_publicaciones": ["MLA1", "MLA2", "MLA-X"]})
    )
    medidas = await dispatcher.execute(
        _context(
            "ZELERDATA_MEDIDAS",
            {"skus": ["sku-1", "sku-2"], "id_publicaciones": ["MLA1", "MLA2"]},
        )
    )
    medidas_general = await dispatcher.execute(
        _context("ZELERDATA_MEDIDASGENERAL", {"skus": "todos", "encabezados": "si"})
    )
    obtener_catalogo = await dispatcher.execute(
        _context("ZELERDATA_OBTENER_CATALOGO", {"encabezados": "si"})
    )
    catalogo_completo = await dispatcher.execute(
        _context("ZELERDATA_CATALOGO_COMPLETO", {"encabezados": "si"})
    )
    catalogo_buybox = await dispatcher.execute(
        _context("ZELERDATA_CATALOGOBUYBOX", {"encabezados": "si"})
    )
    catalogos_sin_vincular = await dispatcher.execute(
        _context("ZELERDATA_CATALOGOSINVINCULAR", {"encabezados": "si"})
    )

    assert supermercado.values == [["Supermercado"], ["Normal"], ["N/A"]]
    assert medidas.values == [["30 * 20 * 10"], ["NA"]]
    assert medidas_general.values == [
        ["ID PUBLICACION", "SKU", "TITULO", "MEDIDAS (LARGO * ALTO * ANCHO)"],
        ["MLA1", "sku-1", "Super item", "30 * 20 * 10"],
        ["MLA2", "sku-2", "Regular item", "NA"],
    ]
    assert obtener_catalogo.values == [
        ["TITULO", "DESCRIPCION", "IMAGEN"],
        ["Catalog title", "Catalog description", '=IMAGE("https://img.example/catalog.jpg")'],
    ]
    assert catalogo_completo.values == [
        ["TITULO", "DESCRIPCION", "IMAGEN", "MARCA", "MODELO", "GTIN"],
        [
            "Catalog title",
            "Catalog description",
            '=IMAGE("https://img.example/catalog.jpg")',
            "Acme",
            "M1",
            "789",
        ],
    ]
    assert catalogo_buybox.values == [
        [
            "TITULO",
            "ID PUBLICACION",
            "ID CATALOGO",
            "STOCK ACTUAL",
            "STATUS",
            "PRECIO",
            "PRECIO GANADOR",
            "# DE GANADORES",
            "UNICO COMPETIDOR",
        ],
        ["Super item", "MLA1", "CAT-1", 7, "winning", 120, 118, 2, "No"],
    ]
    assert catalogos_sin_vincular.values == [
        ["ID PUBLICACION", "TITULO"],
        ["MLA2", "Regular item"],
    ]


@pytest.mark.asyncio
async def test_catalogo_buybox_uses_schema_valid_competitor_count_for_winner_count_column() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL)
    db["sheets_catalog_buybox_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "title": "Schema-valid buybox item",
            "item_id": "MLA1",
            "catalog_product_id": "CAT-1",
            "available_quantity": 9,
            "buybox_status": "sharing",
            "price": Decimal("119"),
            "winning_price": Decimal("118"),
            "competitor_count": 4,
            "only_competitor": "No",
        }
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(_context("ZELERDATA_CATALOGOBUYBOX", {"encabezados": "si"}))

    assert result.values == [
        [
            "TITULO",
            "ID PUBLICACION",
            "ID CATALOGO",
            "STOCK ACTUAL",
            "STATUS",
            "PRECIO",
            "PRECIO GANADOR",
            "# DE GANADORES",
            "UNICO COMPETIDOR",
        ],
        ["Schema-valid buybox item", "MLA1", "CAT-1", 9, "sharing", 119, 118, 4, "No"],
    ]


@pytest.mark.asyncio
async def test_catalogo_buybox_preserves_legacy_winner_count_fallback() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL)
    db["sheets_catalog_buybox_snapshots"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "title": "Legacy buybox item",
            "item_id": "MLA1",
            "catalog_product_id": "CAT-1",
            "available_quantity": 7,
            "buybox_status": "winning",
            "price": Decimal("120"),
            "winning_price": Decimal("118"),
            "winner_count": 2,
            "only_competitor": "No",
        }
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(_context("ZELERDATA_CATALOGOBUYBOX", {"encabezados": "si"}))

    assert result.values[1] == [
        "Legacy buybox item",
        "MLA1",
        "CAT-1",
        7,
        "winning",
        120,
        118,
        2,
        "No",
    ]


@pytest.mark.asyncio
async def test_costo_envio_vendedor_uses_latest_realized_shipment_cost_per_unit() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)
    _mark_read_model_fresh(db, SHIPMENTS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": {
            "_id": "seller-1:SKU-1:MLA1",
            "seller_id": "seller-1",
            "sku": "sku-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "current": {"seller_shipping_cost": Decimal("999")},
        }
    }
    db["orders"].documents = {
        "old": _order_doc(
            "ORDER-OLD",
            date_created=NOW - timedelta(days=10),
            shipment_id="SHIP-OLD",
            sku="sku-1",
            item_id="MLA1",
            quantity=1,
        ),
        "latest": _order_doc(
            "ORDER-LATEST",
            date_created=NOW - timedelta(days=1),
            shipment_id="SHIP-LATEST",
            sku="sku-1",
            item_id="MLA1",
            quantity=2,
        ),
        "cancelled": _order_doc(
            "ORDER-CANCELLED",
            date_created=NOW,
            shipment_id="SHIP-CANCELLED",
            sku="sku-1",
            item_id="MLA1",
            quantity=1,
            status="cancelled",
        ),
    }
    db["shipments"].documents = {
        "SHIP-OLD": _shipment_doc("SHIP-OLD", seller_cost=Decimal("30")),
        "SHIP-LATEST": _shipment_doc("SHIP-LATEST", seller_cost=Decimal("24.50")),
        "SHIP-CANCELLED": _shipment_doc("SHIP-CANCELLED", seller_cost=Decimal("100")),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_COSTOENVIOVENDEDOR",
            {"skus": ["sku-1", "missing"], "id_publicaciones": ["MLA1", "MLA-X"]},
        )
    )

    assert result.values == [[12.25], ["NA"]]
    assert result.meta == {"partial_misses": 1, "orders_count": 3}


@pytest.mark.asyncio
async def test_envios_mercadoenvios_uses_recent_open_labels_and_official_pack_id() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)
    _mark_read_model_fresh(db, SHIPMENTS_READ_MODEL)
    db["orders"].documents = {
        "open": _order_doc(
            "ORDER-OPEN",
            date_created=NOW - timedelta(days=2),
            shipment_id="SHIP-OPEN",
            sku="sku-1",
            item_id="MLA1",
            quantity=2,
            pack_id="998877",
            title="Open shipment",
        ),
        "missing-pack": _order_doc(
            "ORDER-NO-PACK",
            date_created=NOW - timedelta(days=1),
            shipment_id="SHIP-NO-PACK",
            sku="sku-2",
            item_id="MLA2",
            quantity=1,
            pack_id=None,
            title="No pack shipment",
        ),
        "delivered": _order_doc(
            "ORDER-DELIVERED",
            date_created=NOW - timedelta(days=3),
            shipment_id="SHIP-DELIVERED",
            sku="sku-3",
            item_id="MLA3",
            quantity=1,
        ),
        "old": _order_doc(
            "ORDER-OLD",
            date_created=NOW - timedelta(days=31),
            shipment_id="SHIP-OLD",
            sku="sku-4",
            item_id="MLA4",
            quantity=1,
        ),
        "cancelled": _order_doc(
            "ORDER-CANCELLED",
            date_created=NOW - timedelta(days=1),
            shipment_id="SHIP-CANCELLED",
            sku="sku-5",
            item_id="MLA5",
            quantity=1,
            status="cancelled",
        ),
    }
    db["shipments"].documents = {
        "SHIP-OPEN": _shipment_doc(
            "SHIP-OPEN",
            status="ready_to_ship",
            estimated_shipping_at="2026-06-16T10:00:00+00:00",
            delayed=True,
            carrier="Mercado Envios Flex",
        ),
        "SHIP-NO-PACK": _shipment_doc(
            "SHIP-NO-PACK",
            status="handling",
            estimated_shipping_at="2026-06-17T10:00:00+00:00",
            delayed=False,
            carrier="Mercado Envios",
        ),
        "SHIP-DELIVERED": _shipment_doc("SHIP-DELIVERED", status="delivered"),
        "SHIP-OLD": _shipment_doc("SHIP-OLD", status="ready_to_ship"),
        "SHIP-CANCELLED": _shipment_doc("SHIP-CANCELLED", status="ready_to_ship"),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_ENVIOSMERCADOENVIOS", {"estado_etiqueta": "todos", "encabezados": "si"})
    )

    assert result.values == [
        [
            "ID ORDEN",
            "ID PAQUETE",
            "TITULO",
            "SKU",
            "UNIDADES VENDIDAS",
            "ESTADO",
            "FECHA ENVIO",
            "DEMORADO",
            "PAQUETERIA",
        ],
        [
            "ORDER-OPEN",
            "998877",
            "Open shipment",
            "SKU-1",
            2,
            "ready_to_ship",
            "2026-06-16T10:00:00+00:00",
            "Si",
            "Mercado Envios Flex",
        ],
        [
            "ORDER-NO-PACK",
            "N/A",
            "No pack shipment",
            "SKU-2",
            1,
            "handling",
            "2026-06-17T10:00:00+00:00",
            "No",
            "Mercado Envios",
        ],
    ]
    assert result.meta == {
        "orders_count": 2,
        "status_filter": "todos",
        "columns": "legacy_mercadoenvios",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        ("ZELERDATA_SUPERMERCADO", {"id_publicaciones": ["MLA1"]}, ITEM_FORMULA_ROWS_READ_MODEL),
        (
            "ZELERDATA_MEDIDAS",
            {"skus": ["sku-1"], "id_publicaciones": ["MLA1"]},
            ITEM_FORMULA_ROWS_READ_MODEL,
        ),
        ("ZELERDATA_MEDIDASGENERAL", {"skus": "todos"}, ITEM_FORMULA_ROWS_READ_MODEL),
        ("ZELERDATA_CATALOGOSINVINCULAR", {}, ITEM_FORMULA_ROWS_READ_MODEL),
        ("ZELERDATA_OBTENER_CATALOGO", {}, CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL),
        ("ZELERDATA_CATALOGO_COMPLETO", {}, CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL),
        ("ZELERDATA_CATALOGOBUYBOX", {}, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_COSTOENVIOVENDEDOR",
            {"skus": ["sku-1"], "id_publicaciones": ["MLA1"]},
            ORDERS_READ_MODEL,
        ),
        ("ZELERDATA_ENVIOSMERCADOENVIOS", {}, ORDERS_READ_MODEL),
    ],
)
async def test_item_shipping_catalog_formulas_require_fresh_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    dispatcher = _dispatcher(FakeDb())

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        ("ZELERDATA_SUPERMERCADO", {"id_publicaciones": ["MLA1"]}, ITEM_FORMULA_ROWS_READ_MODEL),
        ("ZELERDATA_OBTENER_CATALOGO", {}, CATALOG_PRODUCT_SNAPSHOTS_READ_MODEL),
        ("ZELERDATA_CATALOGOBUYBOX", {}, CATALOG_BUYBOX_SNAPSHOTS_READ_MODEL),
        (
            "ZELERDATA_COSTOENVIOVENDEDOR",
            {"skus": ["sku-1"], "id_publicaciones": ["MLA1"]},
            ORDERS_READ_MODEL,
        ),
    ],
)
async def test_item_shipping_catalog_formulas_reject_stale_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, read_model, fresh_until=NOW - timedelta(days=1))
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args"),
    [
        ("ZELERDATA_COSTOENVIOVENDEDOR", {"skus": ["sku-1"], "id_publicaciones": ["MLA1"]}),
        ("ZELERDATA_ENVIOSMERCADOENVIOS", {}),
    ],
)
async def test_shipping_formulas_require_fresh_shipments_after_orders_are_fresh(
    formula: str, args: dict[str, Any]
) -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert SHIPMENTS_READ_MODEL in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


def _dispatcher(db: FakeDb) -> FormulaDispatcher:
    repository = FormulaReadModelRepository(db=db)
    return FormulaDispatcher(
        build_item_shipping_catalog_formula_handlers(repository, now_fn=lambda: NOW)
    )


def _mark_read_model_fresh(
    db: FakeDb,
    read_model: str,
    *,
    fresh_until: datetime = NOW + timedelta(days=1),
) -> None:
    db["sheets_read_model_freshness"].documents[f"seller-1:{read_model}"] = {
        "_id": f"seller-1:{read_model}",
        "seller_id": "seller-1",
        "read_model": read_model,
        "state": "fresh",
        "fresh_until": fresh_until,
        "reconciled_until": fresh_until,
        "updated_at": NOW,
        "schema_version": 1,
    }


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
    date_created: datetime,
    shipment_id: str,
    sku: str,
    item_id: str,
    quantity: int,
    status: str = "paid",
    pack_id: str | None = "PACK-1",
    title: str = "Sold item",
) -> dict[str, Any]:
    doc = {
        "_id": order_id,
        "seller_id": "seller-1",
        "date_created": date_created,
        "status": status,
        "shipment_id": shipment_id,
        "items": [
            {
                "sku": sku,
                "item_id": item_id,
                "title": title,
                "quantity": quantity,
            }
        ],
    }
    if pack_id is not None:
        doc["meli_pack_id"] = pack_id
    return doc


def _shipment_doc(
    shipment_id: str,
    *,
    seller_cost: Decimal | None = None,
    status: str = "ready_to_ship",
    estimated_shipping_at: str | None = None,
    delayed: bool | None = None,
    carrier: str | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": shipment_id,
        "seller_id": "seller-1",
        "status": status,
    }
    if seller_cost is not None:
        doc["real_shipping_cost"] = {
            "source": "/shipments/{shipment_id}/costs",
            "seller_cost": seller_cost,
        }
    if estimated_shipping_at is not None:
        doc["estimated_shipping_at"] = estimated_shipping_at
    if delayed is not None:
        doc["delayed"] = delayed
    if carrier is not None:
        doc["carrier"] = carrier
    return doc


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        value = _dotted_value(doc, key)
        if isinstance(expected, dict):
            try:
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
            except TypeError:
                return False
        elif value != expected:
            return False
    return True


def _dotted_value(doc: dict[str, Any], key: str) -> Any:
    current: Any = doc
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
