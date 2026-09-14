from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from test_formula_handlers_remaining_phase4 import NOW, _context
from test_formula_inventory_read_cost import _dispatcher, _inventory
from test_formula_recovery import recovery_db  # noqa: F401 - isolated local replica-set fixture


@pytest.mark.asyncio
async def test_catalog_projected_orders_preserve_all_supported_line_shapes(
    recovery_db: Any,  # noqa: F811 - imported isolated fixture
) -> None:
    fixture = _inventory()
    for name, collection in fixture.collections.items():
        documents = list(collection.documents.values())
        for document in documents:
            for key, value in document.get("current", {}).items():
                if isinstance(value, Decimal):
                    document["current"][key] = str(value)
        if documents:
            await recovery_db[name].insert_many(documents)
    await recovery_db.sheets_read_model_freshness.insert_one(
        {
            "_id": "82453304:orders",
            "seller_id": "82453304",
            "read_model": "orders",
            "state": "reconciled",
            "date_from": NOW - timedelta(days=400),
            "reconciled_until": NOW,
        }
    )
    await recovery_db.orders.insert_many(
        [
            {
                "_id": str(index),
                "seller_id": "82453304",
                "date_created": NOW - timedelta(days=1),
                "status": "cancelled" if index == 3 else "paid",
                "items": [line],
                "unconsumed_payload": {"text": "unused" * 1000},
            }
            for index, line in enumerate(
                [
                    {"item_id": "MLA1", "quantity": 2},
                    {"item": {"id": "MLA1"}, "qty": 3},
                    {"item": {"item_id": "MLA1"}, "quantity": 4},
                    {"item_id": "MLA1", "quantity": 100},
                ]
            )
        ]
    )
    result = await _dispatcher(recovery_db).execute(
        _context("ZELERDATA_CATALOGO", {"encabezados": False})
    )
    assert result.values[0][9:15] == [9] * 6
    assert result.meta["unavailable_sales_windows"] == []
    assert result.values[0][2] == "MLA1"
