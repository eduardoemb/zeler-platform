from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import bson
import pytest
from test_event_persistence import FakeDb

from zeler_sheets.source_gated_read_model_writers import (
    plan_stock_time_metrics_reconcile,
    run_source_gated_read_model_import,
)

RANGE_START = datetime(2026, 6, 1, tzinfo=UTC)
RANGE_END = datetime(2026, 6, 15, tzinfo=UTC)


def _db_with(collections: dict[str, list[dict[str, Any]]]) -> FakeDb:
    db = FakeDb()
    for name, documents in collections.items():
        db[name].documents = {str(document["_id"]): dict(document) for document in documents}
    return db


@pytest.mark.asyncio
async def test_legacy_withdrawal_records_import_deterministic_rows_with_history_basis() -> None:
    db = _db_with(
        {
            "withdrawal_records": [
                {
                    "_id": "legacy-withdrawal-1",
                    "seller_id": "82453304",
                    "id": "RET-1",
                    "bultos": [
                        {
                            "bulto_id": "PKG-1",
                            "date_created": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                            "products": [
                                {
                                    "inventory_id": "INV-1",
                                    "item_id": "MLA1",
                                    "sku": "sku-1",
                                    "title": "Imported withdrawal item",
                                    "quantity": 4,
                                    "date_delivery": datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=RANGE_START,
        date_to=RANGE_END,
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    document = db["sheets_full_withdrawals"].documents["82453304:RET-1:PKG-1:INV-1"]
    assert summary.full_withdrawals_planned == 1
    assert summary.full_withdrawals_updated == 1
    assert summary.coverage_basis["full_withdrawals"] == "legacy_imported"
    assert document == {
        "_id": "82453304:RET-1:PKG-1:INV-1",
        "seller_id": "82453304",
        "withdrawal_id": "RET-1",
        "withdrawal_detail_id": "PKG-1",
        "inventory_id": "INV-1",
        "item_id": "MLA1",
        "sku": "sku-1",
        "title": "Imported withdrawal item",
        "requested_quantity": 4,
        "created_at": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
        "delivered_at": datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        "source": "legacy_history_import",
        "history_basis": "legacy_imported",
        "coverage_basis": "legacy_imported",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_full_withdrawal_coverage_is_incomplete_when_detail_product_cannot_flatten() -> None:
    db = _db_with(
        {
            "withdrawal_records": [
                {
                    "_id": "legacy-withdrawal-partial",
                    "seller_id": "82453304",
                    "id": "RET-PARTIAL",
                    "bultos": [
                        {
                            "bulto_id": "PKG-COMPLETE",
                            "date_created": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                            "products": [
                                {
                                    "inventory_id": "INV-COMPLETE",
                                    "item_id": "MLA-COMPLETE",
                                    "sku": "sku-complete",
                                    "quantity": 1,
                                }
                            ],
                        },
                        {
                            "bulto_id": "PKG-MISSING-PRODUCT-ID",
                            "date_created": datetime(2026, 6, 4, 10, 0, tzinfo=UTC),
                            "products": [{"quantity": 2, "title": "No product identity"}],
                        },
                    ],
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=RANGE_START,
        date_to=RANGE_END,
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.full_withdrawals_planned == 1
    assert summary.source_inventory_counts["full_withdrawals"] == 2
    assert summary.coverage_complete["full_withdrawals"] is False
    assert summary.coverage_basis["full_withdrawals"] == "observed_only"
    assert set(db["sheets_full_withdrawals"].documents) == {
        "82453304:RET-PARTIAL:PKG-COMPLETE:INV-COMPLETE"
    }


@pytest.mark.asyncio
async def test_bounded_import_limits_full_withdrawal_writes_and_blocks_complete_coverage() -> None:
    db = _db_with(
        {
            "withdrawal_records": [
                {
                    "_id": "legacy-withdrawal-1",
                    "seller_id": "82453304",
                    "id": "RET-1",
                    "bultos": [
                        {
                            "bulto_id": "PKG-1",
                            "date_created": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                            "products": [{"inventory_id": "INV-1", "quantity": 1}],
                        }
                    ],
                },
                {
                    "_id": "legacy-withdrawal-2",
                    "seller_id": "82453304",
                    "id": "RET-2",
                    "bultos": [
                        {
                            "bulto_id": "PKG-2",
                            "date_created": datetime(2026, 6, 4, 10, 0, tzinfo=UTC),
                            "products": [{"inventory_id": "INV-2", "quantity": 1}],
                        }
                    ],
                },
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=RANGE_START,
        date_to=RANGE_END,
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
        max_items=1,
    )

    assert summary.full_withdrawals_planned == 1
    assert summary.full_withdrawals_updated == 1
    assert summary.coverage_complete["full_withdrawals"] is False
    assert summary.coverage_basis["full_withdrawals"] == "observed_only"
    assert set(db["sheets_full_withdrawals"].documents) == {"82453304:RET-1:PKG-1:INV-1"}


@pytest.mark.asyncio
async def test_bounded_import_caps_full_withdrawal_output_rows_from_one_source_record() -> None:
    db = _db_with(
        {
            "withdrawal_records": [
                {
                    "_id": "bounded-withdrawal-source",
                    "seller_id": "seller-bounded",
                    "id": "WITHDRAWAL-BOUND",
                    "bultos": [
                        {
                            "bulto_id": "PACKAGE-BOUND",
                            "date_created": datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                            "products": [
                                {"inventory_id": "INV-BOUND-1", "quantity": 1},
                                {"inventory_id": "INV-BOUND-2", "quantity": 1},
                            ],
                        }
                    ],
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="seller-bounded",
        date_from=RANGE_START,
        date_to=RANGE_END,
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
        max_items=1,
    )

    assert summary.full_withdrawals_planned == 1
    assert summary.full_withdrawals_updated == 1
    assert summary.source_inventory_counts["full_withdrawals"] == 2
    assert summary.coverage_complete["full_withdrawals"] is False
    assert summary.coverage_basis["full_withdrawals"] == "observed_only"
    assert set(db["sheets_full_withdrawals"].documents) == {
        "seller-bounded:WITHDRAWAL-BOUND:PACKAGE-BOUND:INV-BOUND-1"
    }


@pytest.mark.asyncio
async def test_catalog_history_imports_complete_interval_without_snapshot_inference() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Catalog item",
                    "permalink": "https://meli.example/MLA1",
                    "catalog_history": [
                        {"status2": "Ganando", "changed_at": datetime(2026, 5, 30, tzinfo=UTC)},
                        {"status2": "Perdiendo", "changed_at": datetime(2026, 6, 2, tzinfo=UTC)},
                        {
                            "status2": "No compitiendo",
                            "changed_at": datetime(2026, 6, 3, tzinfo=UTC),
                        },
                    ],
                }
            ],
            "sheets_catalog_buybox_snapshots": [
                {
                    "_id": "current-snapshot-only",
                    "seller_id": "82453304",
                    "item_id": "MLA2",
                    "catalog_product_id": "CAT-2",
                    "buybox_status": "winning",
                    "snapshot_at": datetime(2026, 6, 14, tzinfo=UTC),
                    "source": "historical_meli_backfill",
                    "schema_version": 1,
                }
            ],
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 4, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.catalog_time_metrics_planned == 1
    assert summary.catalog_time_item_ids == ("MLA1",)
    assert set(db["sheets_catalog_time_metrics"].documents) == {
        "82453304:MLA1:2026-06-01:2026-06-04"
    }
    metric = db["sheets_catalog_time_metrics"].documents["82453304:MLA1:2026-06-01:2026-06-04"]
    assert metric["winning_hours"] == Decimal("24")
    assert metric["available_hours"] == Decimal("48")
    assert metric["winning_percent"] == Decimal("50.0000")
    assert metric["history_basis"] == "legacy_imported"
    assert metric["coverage_basis"] == "legacy_imported"


@pytest.mark.asyncio
async def test_catalog_time_write_document_is_bson_encodable_before_replace() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-bson-catalog",
                    "seller_id": "82453304",
                    "item_id": "MLA-BSON-CATALOG",
                    "catalog_history": [
                        {"status2": "Ganando", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)},
                        {"status2": "Perdiendo", "changed_at": datetime(2026, 6, 1, 2, tzinfo=UTC)},
                    ],
                }
            ]
        }
    )

    await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 1, 3, 30, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    _, replacement, _ = db["sheets_catalog_time_metrics"].replace_calls[0]
    bson.encode(replacement)
    assert replacement["winning_hours"] == 2
    assert replacement["available_hours"] == 3.5
    assert replacement["winning_percent"] == pytest.approx(57.1429)
    assert not isinstance(replacement["winning_hours"], Decimal)
    assert not isinstance(replacement["available_hours"], Decimal)
    assert not isinstance(replacement["winning_percent"], Decimal)


@pytest.mark.asyncio
async def test_catalog_change_imports_interval_without_catalog_history() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-embedded-change",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Embedded catalog change item",
                    "permalink": "https://meli.example/MLA1",
                    "catalog_change": [
                        {
                            "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                            "data": {"new_value": "Ganando"},
                        },
                        {
                            "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                            "data": {"new_value": "Perdiendo"},
                        },
                    ],
                },
                {
                    "_id": "projection-event-change",
                    "seller_id": "82453304",
                    "item_id": "MLA2",
                    "title": "Event catalog change item",
                    "permalink": "https://meli.example/MLA2",
                },
            ],
            "meli_item_events": [
                {
                    "_id": "catalog-change-event-1",
                    "seller_id": "82453304",
                    "item_id": "MLA2",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                    "data": {"status": "Ganando"},
                },
                {
                    "_id": "catalog-change-event-2",
                    "seller_id": "82453304",
                    "item_id": "MLA2",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                    "data": {"status": "Sin_stock"},
                },
                {
                    "_id": "unrelated-event",
                    "seller_id": "82453304",
                    "item_id": "MLA3",
                    "event_type": "price_change",
                    "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                    "data": {"status": "Ganando"},
                },
            ],
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 3, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.catalog_time_metrics_planned == 2
    assert summary.catalog_time_item_ids == ("MLA1", "MLA2")
    embedded_metric = db["sheets_catalog_time_metrics"].documents[
        "82453304:MLA1:2026-06-01:2026-06-03"
    ]
    event_metric = db["sheets_catalog_time_metrics"].documents[
        "82453304:MLA2:2026-06-01:2026-06-03"
    ]
    assert embedded_metric["winning_hours"] == Decimal("24")
    assert embedded_metric["available_hours"] == Decimal("48")
    assert embedded_metric["winning_percent"] == Decimal("50.0000")
    assert event_metric["winning_hours"] == Decimal("24")
    assert event_metric["available_hours"] == Decimal("24")
    assert event_metric["winning_percent"] == Decimal("100.0000")
    assert all(
        metric["history_basis"] == "legacy_imported" for metric in (embedded_metric, event_metric)
    )


@pytest.mark.asyncio
async def test_event_only_catalog_change_imports_without_item_history_projection() -> None:
    db = _db_with(
        {
            "meli_item_events": [
                {
                    "_id": "catalog-change-event-only-1",
                    "seller_id": "82453304",
                    "item_id": "MLA-EVENT-ONLY",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                    "data": {"status": "Ganando"},
                },
                {
                    "_id": "catalog-change-event-only-2",
                    "seller_id": "82453304",
                    "item_id": "MLA-EVENT-ONLY",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                    "data": {"status": "Perdiendo"},
                },
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 3, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.catalog_time_metrics_planned == 1
    assert summary.catalog_time_item_ids == ("MLA-EVENT-ONLY",)
    assert summary.source_inventory_counts["catalog_time_metrics"] == 1
    assert summary.coverage_complete["catalog_time_metrics"] is True
    metric = db["sheets_catalog_time_metrics"].documents[
        "82453304:MLA-EVENT-ONLY:2026-06-01:2026-06-03"
    ]
    assert metric["winning_hours"] == Decimal("24")
    assert metric["available_hours"] == Decimal("48")
    assert metric["coverage_basis"] == "legacy_imported"


@pytest.mark.asyncio
async def test_bounded_import_caps_event_only_catalog_change_output_rows() -> None:
    db = _db_with(
        {
            "meli_item_events": [
                {
                    "_id": "bounded-catalog-event-a-1",
                    "seller_id": "seller-bounded",
                    "item_id": "ITEM-BOUND-A",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                    "data": {"status": "Ganando"},
                },
                {
                    "_id": "bounded-catalog-event-a-2",
                    "seller_id": "seller-bounded",
                    "item_id": "ITEM-BOUND-A",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                    "data": {"status": "Perdiendo"},
                },
                {
                    "_id": "bounded-catalog-event-b-1",
                    "seller_id": "seller-bounded",
                    "item_id": "ITEM-BOUND-B",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 5, 31, tzinfo=UTC),
                    "data": {"status": "Ganando"},
                },
                {
                    "_id": "bounded-catalog-event-b-2",
                    "seller_id": "seller-bounded",
                    "item_id": "ITEM-BOUND-B",
                    "event_type": "catalog_change",
                    "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                    "data": {"status": "Perdiendo"},
                },
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="seller-bounded",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 3, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
        max_items=1,
    )

    assert summary.catalog_time_metrics_planned == 1
    assert summary.catalog_time_metrics_updated == 1
    assert summary.catalog_time_item_ids == ("ITEM-BOUND-A",)
    assert summary.source_inventory_counts["catalog_time_metrics"] == 2
    assert summary.coverage_complete["catalog_time_metrics"] is False
    assert summary.coverage_basis["catalog_time_metrics"] == "observed_only"
    assert set(db["sheets_catalog_time_metrics"].documents) == {
        "seller-bounded:ITEM-BOUND-A:2026-06-01:2026-06-03"
    }


@pytest.mark.asyncio
async def test_stock_variations_history_imports_active_hours_and_week_buckets() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Stock item",
                    "permalink": "https://meli.example/MLA1",
                    "variations_history": {
                        "SKU1": [
                            {"status2": "paused", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)},
                            {"status2": "active", "changed_at": datetime(2026, 6, 2, tzinfo=UTC)},
                            {"status2": "paused", "changed_at": datetime(2026, 6, 4, tzinfo=UTC)},
                            {"status2": "active", "changed_at": datetime(2026, 6, 10, tzinfo=UTC)},
                        ]
                    },
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 15, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    metric = db["sheets_stock_time_metrics"].documents["82453304:MLA1:SKU1:2026-06-01:2026-06-15"]
    assert summary.stock_time_metrics_planned == 1
    assert metric["active_stock_hours"] == Decimal("168")
    assert metric["total_hours"] == Decimal("336")
    assert metric["active_stock_percent"] == Decimal("50.0000")
    assert metric["weeks"] == [
        {"start_day": 1, "end_day": 7, "has_stock": True},
        {"start_day": 8, "end_day": 14, "has_stock": True},
    ]
    assert metric["source"] == "legacy_history_import"
    assert metric["history_basis"] == "legacy_imported"
    assert metric["coverage_basis"] == "legacy_imported"


@pytest.mark.asyncio
async def test_stock_time_write_document_is_bson_encodable_before_replace() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-bson-stock",
                    "seller_id": "82453304",
                    "item_id": "MLA-BSON-STOCK",
                    "variations_history": {
                        "SKU-BSON": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ]
                    },
                }
            ]
        }
    )

    await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 1, 1, 30, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    _, replacement, _ = db["sheets_stock_time_metrics"].replace_calls[0]
    bson.encode(replacement)
    assert replacement["active_stock_hours"] == 1.5
    assert replacement["total_hours"] == 1.5
    assert replacement["active_stock_percent"] == 100
    assert not isinstance(replacement["active_stock_hours"], Decimal)
    assert not isinstance(replacement["total_hours"], Decimal)
    assert not isinstance(replacement["active_stock_percent"], Decimal)


@pytest.mark.asyncio
async def test_bounded_import_caps_stock_time_output_rows_from_multi_sku_projection() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "bounded-stock-source",
                    "seller_id": "seller-bounded",
                    "item_id": "ITEM-STOCK-BOUND",
                    "variations_history": {
                        "SKU-BOUND-1": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ],
                        "SKU-BOUND-2": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ],
                    },
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="seller-bounded",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 8, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
        max_items=1,
    )

    assert summary.stock_time_metrics_planned == 1
    assert summary.stock_time_metrics_updated == 1
    assert summary.stock_time_item_ids == ("ITEM-STOCK-BOUND",)
    assert summary.source_inventory_counts["stock_time_metrics"] == 2
    assert summary.coverage_complete["stock_time_metrics"] is False
    assert summary.coverage_basis["stock_time_metrics"] == "observed_only"
    assert set(db["sheets_stock_time_metrics"].documents) == {
        "seller-bounded:ITEM-STOCK-BOUND:SKU-BOUND-1:2026-06-01:2026-06-08"
    }


@pytest.mark.asyncio
async def test_in_stock_variation_state_counts_as_active_stock_hours() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-in-stock",
                    "seller_id": "82453304",
                    "item_id": "MLA-IN-STOCK",
                    "variations_history": {
                        "SKU-IN-STOCK": [
                            {
                                "status2": "in_stock",
                                "changed_at": datetime(2026, 5, 31, tzinfo=UTC),
                            },
                            {
                                "status2": "out_of_stock",
                                "changed_at": datetime(2026, 6, 2, tzinfo=UTC),
                            },
                        ]
                    },
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 3, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    metric = db["sheets_stock_time_metrics"].documents[
        "82453304:MLA-IN-STOCK:SKU-IN-STOCK:2026-06-01:2026-06-03"
    ]
    assert summary.stock_time_metrics_planned == 1
    assert metric["active_stock_hours"] == Decimal("24")
    assert metric["total_hours"] == Decimal("48")
    assert metric["active_stock_percent"] == Decimal("50.0000")


@pytest.mark.asyncio
async def test_legacy_history_can_be_scoped_by_imported_account_id_mapping() -> None:
    db = _db_with(
        {
            "meli_accounts": [
                {
                    "_id": "account-1",
                    "seller_id": "82453304",
                    "account_id": 10,
                }
            ],
            "item_history_projection": [
                {
                    "_id": "projection-1",
                    "account_id": 10,
                    "item_id": "MLA1",
                    "variations_history": {
                        "SKU1": [
                            {
                                "status2": "active",
                                "changed_at": datetime(2026, 5, 31, tzinfo=UTC),
                            }
                        ]
                    },
                }
            ],
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 8, tzinfo=UTC),
        dry_run=True,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.stock_time_metrics_planned == 1
    assert summary.stock_time_item_ids == ("MLA1",)


@pytest.mark.asyncio
async def test_legacy_history_scope_unions_seller_and_account_identifier_buckets() -> None:
    db = _db_with(
        {
            "meli_accounts": [
                {
                    "_id": "account-1",
                    "seller_id": "82453304",
                    "account_id": 10,
                }
            ],
            "item_history_projection": [
                {
                    "_id": "projection-seller-bucket",
                    "seller_id": "82453304",
                    "item_id": "MLA-SELLER",
                    "variations_history": {
                        "SKU-SELLER": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ]
                    },
                },
                {
                    "_id": "projection-account-bucket",
                    "account_id": 10,
                    "item_id": "MLA-ACCOUNT",
                    "variations_history": {
                        "SKU-ACCOUNT": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ]
                    },
                },
            ],
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 8, tzinfo=UTC),
        dry_run=True,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.stock_time_metrics_planned == 2
    assert summary.stock_time_item_ids == ("MLA-SELLER", "MLA-ACCOUNT")


@pytest.mark.asyncio
async def test_partial_or_absent_legacy_history_remains_observed_only_without_writes() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "partial-projection",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "catalog_history": [
                        {"status2": "Ganando", "changed_at": datetime(2026, 6, 3, tzinfo=UTC)}
                    ],
                    "variations_history": {
                        "SKU1": [
                            {"status2": "active", "changed_at": datetime(2026, 6, 3, tzinfo=UTC)}
                        ]
                    },
                }
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 4, tzinfo=UTC),
        dry_run=False,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.stock_time_metrics_planned == 0
    assert summary.catalog_time_metrics_planned == 0
    assert summary.full_withdrawals_planned == 0
    assert summary.coverage_basis == {
        "stock_time_metrics": "observed_only",
        "catalog_time_metrics": "observed_only",
        "full_withdrawals": "observed_only",
    }
    assert db["sheets_stock_time_metrics"].documents == {}
    assert db["sheets_catalog_time_metrics"].documents == {}
    assert db["sheets_full_withdrawals"].documents == {}


@pytest.mark.asyncio
async def test_missing_stock_and_catalog_history_count_as_incomplete_source_inventory() -> None:
    db = _db_with(
        {
            "item_history_projection": [
                {
                    "_id": "projection-covered",
                    "seller_id": "82453304",
                    "item_id": "MLA-COVERED",
                    "catalog_history": [
                        {"status2": "Ganando", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                    ],
                    "variations_history": {
                        "SKU-COVERED": [
                            {"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}
                        ]
                    },
                },
                {
                    "_id": "projection-missing-history",
                    "seller_id": "82453304",
                    "item_id": "MLA-MISSING-HISTORY",
                },
            ]
        }
    )

    summary = await run_source_gated_read_model_import(
        db=db,
        seller_id="82453304",
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 4, tzinfo=UTC),
        dry_run=True,
        now=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert summary.stock_time_metrics_planned == 1
    assert summary.catalog_time_metrics_planned == 1
    assert summary.source_inventory_counts["stock_time_metrics"] == 2
    assert summary.source_inventory_counts["catalog_time_metrics"] == 2
    assert summary.coverage_complete["stock_time_metrics"] is False
    assert summary.coverage_complete["catalog_time_metrics"] is False
    assert summary.coverage_basis["stock_time_metrics"] == "observed_only"
    assert summary.coverage_basis["catalog_time_metrics"] == "observed_only"


def _stock_plan_db(
    *,
    account_count: int = 1,
    site_id: str = "MLM",
    history: bool = True,
    item_id: str = "MLM1",
    exact_rows: list[dict[str, Any]] | None = None,
) -> FakeDb:
    projection: dict[str, Any] = {
        "_id": "projection-1",
        "seller_id": "seller-1",
        "item_id": item_id,
    }
    if history:
        projection["variations_history"] = {
            "SKU1": [{"status2": "active", "changed_at": datetime(2026, 5, 31, tzinfo=UTC)}]
        }
    return _db_with(
        {
            "meli_accounts": [
                {"_id": f"account-{index}", "seller_id": "seller-1", "site_id": site_id}
                for index in range(account_count)
            ],
            "item_history_projection": [projection],
            "sheets_stock_time_metrics": exact_rows or [],
        }
    )


@pytest.mark.asyncio
async def test_stock_time_reconcile_plan_is_local_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    db = _stock_plan_db()
    plan = await plan_stock_time_metrics_reconcile(
        db=db, seller_id="seller-1", date_from=RANGE_START, date_to=RANGE_END
    )
    assert plan.ready and plan.issue_codes == ()
    assert plan.source_inventory_count == plan.validator_count == 1
    assert all(
        not db[name].replace_calls
        for name in (
            "sheets_stock_time_metrics",
            "sheets_catalog_time_metrics",
            "sheets_full_withdrawals",
        )
    )

    for blocked_db, issue_code in (
        (_stock_plan_db(account_count=0), "seller_account_missing"),
        (_stock_plan_db(account_count=2), "seller_account_ambiguous"),
        (_stock_plan_db(site_id="MLA", item_id="MLA1"), "non_mlm_evidence"),
        (_stock_plan_db(history=False), "source_history_incomplete"),
    ):
        blocked = await plan_stock_time_metrics_reconcile(
            db=blocked_db, seller_id="seller-1", date_from=RANGE_START, date_to=RANGE_END
        )
        assert not blocked.ready and issue_code in blocked.issue_codes
        assert blocked_db["sheets_stock_time_metrics"].replace_calls == []

    exact = {"seller_id": "seller-1", "date_from": RANGE_START, "date_to": RANGE_END}
    drift_db = _stock_plan_db(
        exact_rows=[
            {"_id": "seller-1:MLM1:SKU1:2026-06-01:2026-06-15", **exact},
            {"_id": "extra-exact-row", **exact},
        ]
    )
    monkeypatch.setattr(writers, "_stock_time_document_is_valid", lambda *args, **kwargs: False)
    drift = await plan_stock_time_metrics_reconcile(
        db=drift_db, seller_id="seller-1", date_from=RANGE_START, date_to=RANGE_END
    )
    assert drift.stale_exact_count == drift.extra_exact_count == 1
    assert set(drift.issue_codes) == {
        "exact_interval_extra_rows",
        "exact_interval_stale_rows",
        "validator_count_mismatch",
    }
    assert drift_db["sheets_stock_time_metrics"].replace_calls == []


def _action_document(target_id: str, *, title: str) -> dict[str, Any]:
    return {
        "_id": target_id,
        "seller_id": "seller-1",
        "title": title,
        "date_from": RANGE_START,
        "total_hours": Decimal("336.0000"),
    }


def test_stock_time_action_planner_classifies_and_orders_every_action() -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    planned = [
        _action_document("target-replace", title="new"),
        _action_document("target-no-op", title="same"),
        _action_document("target-insert", title="new"),
    ]
    existing = [
        {**_action_document("target-delete", title="old"), "revision": "d" * 64},
        {**_action_document("target-no-op", title="same"), "revision": "n" * 64},
        {**_action_document("target-replace", title="old"), "revision": "r" * 64},
    ]

    plan = writers._plan_stock_time_actions(
        source_inventory=[{"_id": "source-1", "at": RANGE_START, "value": Decimal("1.00")}],
        planned_documents=planned,
        existing_target_rows=existing,
    )

    assert [(action._target_id, action.action) for action in plan.actions] == [
        ("target-delete", "delete"),
        ("target-insert", "insert"),
        ("target-no-op", "no-op"),
        ("target-replace", "replace"),
    ]
    assert (
        plan.insert_count,
        plan.replace_count,
        plan.delete_count,
        plan.no_op_count,
        plan.preimage_count,
    ) == (1, 1, 1, 1, 3)
    assert plan.action_count == 4
    assert plan.estimated_bson_bytes > 0
    assert plan.estimated_json_bytes > 0
    assert plan.estimated_transaction_payload_bytes == (
        plan.estimated_bson_bytes + plan.estimated_json_bytes
    )
    no_op = plan.actions[2]
    assert no_op._document is not None
    assert no_op._preimage is not None
    assert no_op._document["title"] == "same"
    assert no_op._preimage["revision"] == "n" * 64
    with pytest.raises(TypeError):
        # Deliberately attempt the mutation forbidden by the Mapping type.
        no_op._document["title"] = "mutated"  # type: ignore[index]


def test_stock_time_action_planner_insert_only_has_no_preimage() -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    plan = writers._plan_stock_time_actions(
        source_inventory=[],
        planned_documents=[_action_document("target-insert", title="new")],
        existing_target_rows=[],
    )

    assert plan.insert_count == 1
    assert plan.preimage_count == 0


def test_stock_time_action_planner_no_op_only_has_one_preimage() -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    document = _action_document("target-no-op", title="same")
    plan = writers._plan_stock_time_actions(
        source_inventory=[],
        planned_documents=[document],
        existing_target_rows=[document],
    )

    assert plan.no_op_count == 1
    assert plan.preimage_count == 1


def test_stock_time_action_planner_fingerprints_are_permutation_stable_and_material() -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    source = [
        {"_id": "source-b", "at": RANGE_END, "value": Decimal("2.50")},
        {"_id": "source-a", "at": RANGE_START, "value": Decimal("1.00")},
    ]
    planned = [
        _action_document("target-b", title="same"),
        _action_document("target-a", title="new"),
    ]
    existing = [
        {**_action_document("target-b", title="same"), "revision": "b" * 64},
        _action_document("target-c", title="old"),
    ]
    kwargs = {
        "source_inventory": source,
        "planned_documents": planned,
        "existing_target_rows": existing,
    }

    first = writers._plan_stock_time_actions(**kwargs)
    permuted = writers._plan_stock_time_actions(
        source_inventory=list(reversed(source)),
        planned_documents=list(reversed(planned)),
        existing_target_rows=list(reversed(existing)),
    )
    assert first == permuted
    for fingerprint in (
        first.source_fingerprint,
        first.preimage_fingerprint,
        first.plan_fingerprint,
    ):
        assert len(fingerprint) == 64
        assert fingerprint == fingerprint.lower()

    changed_source = writers._plan_stock_time_actions(
        **{**kwargs, "source_inventory": [{**source[0], "value": Decimal("2.51")}, source[1]]}
    )
    assert changed_source.source_fingerprint != first.source_fingerprint
    changed_target = writers._plan_stock_time_actions(
        **{
            **kwargs,
            "existing_target_rows": [
                {**existing[0], "title": "drifted"},
                existing[1],
            ],
        }
    )
    assert changed_target.preimage_fingerprint != first.preimage_fingerprint
    assert changed_target.plan_fingerprint != first.plan_fingerprint


@pytest.mark.parametrize("bucket", ["planned_documents", "existing_target_rows"])
def test_stock_time_action_planner_rejects_duplicate_and_malformed_target_ids(
    bucket: str,
) -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    duplicate = [
        _action_document("duplicate", title="one"),
        _action_document("duplicate", title="two"),
    ]
    kwargs: dict[str, Any] = {
        "source_inventory": [],
        "planned_documents": [],
        "existing_target_rows": [],
    }
    kwargs[bucket] = duplicate
    expected_code = (
        "DUPLICATE_PLANNED_ID" if bucket == "planned_documents" else "DUPLICATE_EXISTING_ID"
    )
    with pytest.raises(writers._StockTimeActionPlanError, match=f"^{expected_code}$") as error:
        writers._plan_stock_time_actions(**kwargs)
    assert error.value.code == expected_code

    kwargs[bucket] = [{"_id": " ", "title": "private"}]
    with pytest.raises(writers._StockTimeActionPlanError, match="^MALFORMED_TARGET_ID$"):
        writers._plan_stock_time_actions(**kwargs)


def test_stock_time_action_planner_fails_closed_on_row_and_payload_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets import source_gated_read_model_writers as writers

    kwargs = {
        "source_inventory": [],
        "planned_documents": [
            _action_document("target-a", title="a"),
            _action_document("target-b", title="b"),
        ],
        "existing_target_rows": [],
    }
    monkeypatch.setattr(writers, "_STOCK_TIME_MAX_ACTION_ROWS", 1)
    with pytest.raises(writers._StockTimeActionPlanError, match="^ACTION_ROW_LIMIT_EXCEEDED$"):
        writers._plan_stock_time_actions(**kwargs)

    monkeypatch.setattr(writers, "_STOCK_TIME_MAX_ACTION_ROWS", 2)
    monkeypatch.setattr(writers, "_STOCK_TIME_MAX_TRANSACTION_PAYLOAD_BYTES", 1)
    with pytest.raises(writers._StockTimeActionPlanError, match="^PAYLOAD_LIMIT_EXCEEDED$"):
        writers._plan_stock_time_actions(**kwargs)
