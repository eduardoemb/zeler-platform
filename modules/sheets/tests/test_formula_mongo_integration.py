from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError, FormulaExecutionContext
from zeler_sheets.formulas.handlers_core import _dashboard_sku_resolver_for_orders
from zeler_sheets.formulas.handlers_orders_questions import (
    OrderQuestionFormulaHandlers,
    _sku_resolver_for_orders,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.unit_costs import UnitCostLookup


@pytest.mark.asyncio
async def test_complete_formula_sources_remain_seller_scoped_in_mongo() -> None:
    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    database = client[f"zeler_formula_test_{uuid4().hex}"]
    created = False
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        created = True
        repository = FormulaReadModelRepository(db=database)
        start = datetime(2026, 8, 8, tzinfo=UTC)
        end = datetime(2026, 9, 7, tzinfo=UTC)
        await database.sheets_read_model_freshness.insert_one(
            {
                "_id": "pilot:orders",
                "seller_id": "pilot",
                "read_model": "orders",
                "state": "reconciled",
                "fresh_until": end,
                "valid_until": datetime.now(UTC) - timedelta(seconds=1),
            }
        )
        with pytest.raises(FormulaDataUnavailableError):
            await repository.require_read_model_productive(
                seller_id="pilot", read_model="orders", date_to=end, formula="ZELERDATA_TEST"
            )
        await database.sheets_read_model_freshness.update_one(
            {"_id": "pilot:orders"},
            {"$set": {"valid_until": datetime.now(UTC) + timedelta(minutes=5)}},
        )
        await repository.require_read_model_productive(
            seller_id="pilot", read_model="orders", date_to=end, formula="ZELERDATA_TEST"
        )
        for method, collection, count, kwargs in (
            ("find_item_formula_rows", "sheets_item_formula_rows", 501, {}),
            ("find_sku_index_rows", "sheets_item_sku_index", 501, {}),
            ("find_orders", "orders", 1001, {"date_from": start, "date_to": end}),
            ("find_questions", "questions", 1001, {"date_from": start, "date_to": end}),
            ("find_catalog_product_snapshots", "sheets_catalog_product_snapshots", 1001, {}),
            ("find_catalog_buybox_snapshots", "sheets_catalog_buybox_snapshots", 1001, {}),
            ("find_stockout_snapshots", "sheets_stockout_snapshots", 1001, {}),
            ("find_price_history_snapshots", "sheets_price_history_snapshots", 1001, {}),
            (
                "find_stock_time_metrics",
                "sheets_stock_time_metrics",
                1001,
                {"date_from": start, "date_to": end},
            ),
            (
                "find_catalog_time_metrics",
                "sheets_catalog_time_metrics",
                1001,
                {"date_from": start, "date_to": end},
            ),
            (
                "find_full_withdrawals",
                "sheets_full_withdrawals",
                1001,
                {"date_from": start, "date_to": end},
            ),
        ):
            await database[collection].insert_many(
                [
                    {
                        "_id": str(i),
                        "seller_id": "pilot",
                        "date_created": start,
                        "created_at": start,
                        "date_from": start,
                        "date_to": end,
                    }
                    for i in range(count)
                ]
                + [
                    {
                        "_id": "foreign",
                        "seller_id": "another-seller",
                        "date_created": start,
                        "created_at": start,
                        "date_from": start,
                        "date_to": end,
                    }
                ]
            )
            rows = await getattr(repository, method)(seller_id="pilot", **kwargs)
            assert len(rows) == count
            assert {row["seller_id"] for row in rows} == {"pilot"}
        await database.sheets_read_model_freshness.insert_one(
            {
                "_id": "pilot:questions",
                "seller_id": "pilot",
                "read_model": "questions",
                "state": "reconciled",
                "date_from": start,
                "reconciled_until": end,
            }
        )
        result = await OrderQuestionFormulaHandlers(repository).sheetseller_preguntas_kpi(
            FormulaExecutionContext(
                contract=FormulaRegistry.default().find_required("ZELERDATA_PREGUNTASKPI"),
                cuenta="PILOT",
                seller_id="pilot",
                seller_nickname="PILOT",
                token_id=uuid4().hex,
                args={"fecha_inicio": "2026-08-08", "fecha_final": "2026-09-06"},
                request_id=None,
            )
        )
        assert ["Total preguntas", 1001] in result.values
        lookups = [
            UnitCostLookup(seller_id="pilot", normalized_sku=f"SKU-{i:04d}") for i in range(1001)
        ]
        await database.seller_unit_costs.insert_many(
            [
                {
                    "_id": str(i),
                    "seller_id": "pilot",
                    "normalized_sku": lookup.normalized_sku,
                    "unit_cost": 7,
                    "effective_from": start,
                    "status": "active",
                    "currency": "MXN",
                }
                for i, lookup in enumerate(lookups)
            ]
        )
        costs = await repository.find_unit_costs(seller_id="pilot", lookups=lookups)
        assert len(costs) == 1001
        assert all(value == 7 for value in costs.values())
        await database.sheets_item_sku_index.insert_many(
            [
                {
                    "_id": f"variant-{i:04d}",
                    "seller_id": "pilot",
                    "item_id": "MLM1",
                    "variation_id": str(i),
                    "normalized_sku": f"SKU-{i:04d}",
                }
                for i in range(501)
            ]
        )
        line = {"item_id": "MLM1", "variation_id": "500"}
        orders = [{"items": [line]}]
        sales = await _sku_resolver_for_orders(
            repository=repository, seller_id="pilot", orders=orders
        )
        dashboard = await _dashboard_sku_resolver_for_orders(
            repository=repository, seller_id="pilot", orders=orders
        )
        assert [sales.resolve(line).sku, dashboard.resolve("MLM1", "500")] == ["SKU-0500"] * 2
    finally:
        if created:
            await client.drop_database(database.name)
        client.close()
