from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from zeler_sheets.formulas.read_models import FormulaReadModelRepository


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
        for method, collection, count, kwargs in (
            ("find_item_formula_rows", "sheets_item_formula_rows", 501, {}),
            ("find_sku_index_rows", "sheets_item_sku_index", 501, {}),
            ("find_orders", "orders", 1001, {"date_from": start, "date_to": end}),
        ):
            await database[collection].insert_many(
                [{"_id": str(i), "seller_id": "pilot", "date_created": start} for i in range(count)]
                + [{"_id": "foreign", "seller_id": "another-seller", "date_created": start}]
            )
            rows = await getattr(repository, method)(seller_id="pilot", **kwargs)
            assert len(rows) == count
            assert {row["seller_id"] for row in rows} == {"pilot"}
    finally:
        if created:
            await client.drop_database(database.name)
        client.close()
