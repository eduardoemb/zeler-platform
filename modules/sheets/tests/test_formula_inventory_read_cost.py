from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from test_formula_handlers_remaining_phase4 import (
    NOW,
    FakeDb,
    _context,
    _item_row,
    _order_doc,
    _seed_catalog_inventory,
)

from zeler_sheets.formulas.dispatcher import FormulaDispatcher
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    build_item_shipping_catalog_formula_handlers,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import build_remaining_phase4_formula_handlers
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.item_projection import item_source_fingerprint


def _inventory() -> FakeDb:
    db = FakeDb()
    db["sheets_item_formula_rows"].documents["item"] = _item_row(
        item_id="MLA1",
        sku="sku",
        title="Owned publication",
        catalog_product_id="MLA9",
        price=Decimal("100"),
    )
    _seed_catalog_inventory(db)
    return db


def _dispatcher(db: Any) -> FormulaDispatcher:
    repo = FormulaReadModelRepository(db=db)
    return FormulaDispatcher(
        build_remaining_phase4_formula_handlers(repo, now_fn=lambda: NOW)
        | build_item_shipping_catalog_formula_handlers(repo, now_fn=lambda: NOW)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formula",
    [
        "ZELERDATA_CATALOGO",
        "ZELERDATA_CATALOGOBUYBOX",
        "ZELERDATA_CATALOGO_COMPLETO",
        "ZELERDATA_OBTENER_CATALOGO",
    ],
)
async def test_catalog_resolves_owned_source_once_per_invocation(
    formula: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeler_sheets.formulas.read_models as readers

    db = _inventory()
    reads = 0
    fingerprints = 0
    find = db["items"].find

    def counted_find(*args: Any, **kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        return find(*args, **kwargs)

    def counted_fingerprint(source: dict[str, Any]) -> str:
        nonlocal fingerprints
        fingerprints += 1
        return item_source_fingerprint(source)

    monkeypatch.setattr(db["items"], "find", counted_find)
    monkeypatch.setattr(readers, "item_source_fingerprint", counted_fingerprint)
    dispatcher = _dispatcher(db)
    result = await dispatcher.execute(_context(formula, {"encabezados": False}))
    assert result.meta["inventory_enumeration_current"] is True
    assert result.meta["rows_count"] == 1
    assert reads == fingerprints == 1
    # Same repository instance, next invocation: never reuse an earlier source cut.
    db["items"].documents["MLA1"]["title"] = "Concurrent source change"
    result = await dispatcher.execute(_context(formula, {"encabezados": False}))
    assert result.recovery is not None
    assert result.recovery.read_model == "item_formula_rows"
    assert reads == fingerprints == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["title", "seller", "receipt", "rows_count", "future", "expired"]
)
async def test_source_changes_at_rows_source_boundary_fail_closed(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _inventory()
    find = db["items"].find

    def changed_find(*args: Any, **kwargs: Any) -> Any:
        source = db["items"].documents["MLA1"]
        row = db["sheets_item_formula_rows"].documents["item"]
        if mutation == "title":
            source["title"] = "Changed after projection read"
        elif mutation == "seller":
            source["seller_id"] = "other-seller"
        elif mutation == "receipt":
            row["source_snapshot"]["fingerprint"] = "wrong"
        elif mutation == "rows_count":
            row["source_snapshot"]["rows_count"] = 2
        else:
            source["last_meli_sync_at"] = NOW + timedelta(
                minutes=1 if mutation == "future" else -16
            )
        return find(*args, **kwargs)

    monkeypatch.setattr(db["items"], "find", changed_find)
    result = await _dispatcher(db).execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert result.recovery is not None and result.recovery.read_model == "item_formula_rows"
    assert result.values == [["DATA_UNAVAILABLE"] * 24]


@pytest.mark.asyncio
async def test_variant_associations_come_from_the_verified_source_snapshot() -> None:
    db = _inventory()
    source = db["items"].documents["MLA1"]
    source["variations"] = [{"id": "1", "catalog_product_id": "MLA10"}]
    db["sheets_item_formula_rows"].documents["item"]["source_snapshot"]["fingerprint"] = (
        item_source_fingerprint(source)
    )
    for identity in ("MLA9", "MLA10"):
        db["sheets_catalog_product_snapshots"].documents[identity] = {
            "_id": f"82453304:{identity}",
            "seller_id": "82453304",
            "catalog_product_id": identity,
            "snapshot_at": NOW,
            "source": "sheets_backfill",
            "title": identity,
            "description": "Available",
            "image_url": "image",
            "attributes": [],
        }
    result = await _dispatcher(db).execute(
        _context("ZELERDATA_CATALOGO_COMPLETO", {"encabezados": False})
    )
    assert result.meta["available_products"] == 2
    assert result.meta["catalog_products_complete"] is True
    assert len(result.values) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("coverage", [0, 31, 400])
async def test_catalog_only_reads_orders_needed_by_proven_sales_windows(
    coverage: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _inventory()
    if coverage:
        db["sheets_read_model_freshness"].documents["82453304:orders"] = {
            "_id": "82453304:orders",
            "seller_id": "82453304",
            "read_model": "orders",
            "state": "reconciled",
            "date_from": NOW - timedelta(days=coverage),
            "reconciled_until": NOW,
        }
    db["orders"].documents = {
        "recent": _order_doc("recent", days_ago=1, quantity=3),
        "older": _order_doc("older", days_ago=60, quantity=7),
        "cancelled": _order_doc("cancelled", days_ago=1, quantity=11, status="cancelled"),
    }
    reads: list[tuple[dict[str, Any], Any]] = []
    find = db["orders"].find

    def counted_find(filter_spec: dict[str, Any], projection: Any = None) -> Any:
        reads.append((deepcopy(filter_spec), projection))
        return find(filter_spec, projection)

    monkeypatch.setattr(db["orders"], "find", counted_find)
    result = await _dispatcher(db).execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert result.values[0][9:15] == (
        ["DATA_UNAVAILABLE"] * 6
        if not coverage
        else [3, 3, 3, *([10] * 3 if coverage == 400 else ["DATA_UNAVAILABLE"] * 3)]
    )
    if not coverage:
        assert reads == []
    else:
        assert len(reads) == 1
        assert reads[0][0]["$or"][0]["date_created"]["$gte"] == (
            NOW - timedelta(days=365 if coverage == 400 else 30)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        assert reads[0][1] == {
            "_id": 0,
            "status": 1,
            "date_created": 1,
            "items.item_id": 1,
            "items.item.id": 1,
            "items.item.item_id": 1,
            "items.quantity": 1,
            "items.qty": 1,
        }


@pytest.mark.asyncio
async def test_catalog_associations_do_not_mix_later_source_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _inventory()
    source = db["items"].documents["MLA1"]
    db["sheets_catalog_buybox_snapshots"].documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "catalog_product_id": "MLA9",
        "title": source["title"],
        "available_quantity": source["available_quantity"],
        "snapshot_at": NOW,
        "source": "sheets_backfill",
        "winning_user_id": "42",
        "only_competitor": False,
    }
    find = db["sheets_catalog_buybox_snapshots"].find

    def changed_find(*args: Any, **kwargs: Any) -> Any:
        # A database write replaces the durable source, not the previously read
        # detached document; emulate that while joining the competition rows.
        db["items"].documents["MLA1"] = {
            **deepcopy(source),
            "catalog_product_id": "MLA10",
            "title": "Later title",
        }
        return find(*args, **kwargs)

    monkeypatch.setattr(db["sheets_catalog_buybox_snapshots"], "find", changed_find)
    dispatcher = _dispatcher(db)
    first = await dispatcher.execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert first.values[0][0] == "MLA9"
    assert first.values[0][4] == "Owned publication"
    assert first.values[0][20] == "42"
    second = await dispatcher.execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert second.values == [["DATA_UNAVAILABLE"] * 24]
    assert second.recovery is not None and second.recovery.item_ids == ("MLA1",)


@pytest.mark.asyncio
async def test_supplied_inventory_keeps_revalidation_against_changed_source() -> None:
    db = _inventory()
    repo = FormulaReadModelRepository(db=db)
    inventory = await repo.find_recent_item_inventory(seller_id="82453304", formula="test", now=NOW)
    db["items"].documents["MLA1"]["catalog_product_id"] = "MLA10"
    rows, missing, invalid, current = await repo.find_recent_catalog_buybox_inventory(
        seller_id="82453304", formula="test", now=NOW, inventory=inventory
    )
    assert rows == [] and missing == ()
    assert invalid == ("MLA1",) and current


@pytest.mark.asyncio
async def test_empty_catalog_does_not_read_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _inventory()
    source = db["items"].documents["MLA1"]
    source["catalog_listing"] = False
    db["sheets_item_formula_rows"].documents["item"]["source_snapshot"]["fingerprint"] = (
        item_source_fingerprint(source)
    )
    db["sheets_read_model_freshness"].documents["82453304:orders"] = {
        "_id": "82453304:orders",
        "seller_id": "82453304",
        "read_model": "orders",
        "state": "reconciled",
        "date_from": NOW - timedelta(days=400),
        "reconciled_until": NOW,
    }

    def unexpected_read(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Orders cannot affect an empty catalog")

    monkeypatch.setattr(db["orders"], "find", unexpected_read)
    result = await _dispatcher(db).execute(_context("ZELERDATA_CATALOGO", {"encabezados": False}))
    assert result.values == []
    assert result.meta["rows_count"] == 0 and result.recovery is None
