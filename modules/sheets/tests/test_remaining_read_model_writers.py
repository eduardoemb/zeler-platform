from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from bson.decimal128 import Decimal128
from infra.mongo.validator_contract import validate_document_against_schema
from pymongo.errors import DuplicateKeyError
from test_event_persistence import FakeCollection, FakeCursor, FakeDb

from zeler_sheets.remaining_read_model_writers import (
    record_price_history_observation,
    record_stockout_observation,
    run_remaining_observed_read_model_seed,
)

ROOT = Path(__file__).resolve().parents[3]
OBSERVED_AT = datetime(2026, 6, 17, 12, 30, tzinfo=UTC)
DEFAULT_PRICE = Decimal128("149.99")


class ConcurrentFreshInsertCollection(FakeCollection):
    def __init__(self, *, fresh_document: dict[str, Any]) -> None:
        super().__init__()
        self._fresh_document = dict(fresh_document)
        self._interleaved = False

    def _insert_fresh_once(self) -> None:
        if self._interleaved:
            return
        self._interleaved = True
        self.documents[str(self._fresh_document["_id"])] = dict(self._fresh_document)

    async def insert_one(self, document: dict[str, Any]) -> Any:
        del document
        self._insert_fresh_once()
        raise DuplicateKeyError("duplicate key")

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> Any:
        self._insert_fresh_once()
        return await super().replace_one(filter_spec, replacement, upsert=upsert)


class RecordingCursor(FakeCursor):
    def __init__(self, documents: list[dict[str, Any]], lengths: list[int | None]) -> None:
        super().__init__(documents)
        self._lengths = lengths

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        self._lengths.append(length)
        return self._documents if length is None else self._documents[:length]


class RecordingFindCollection(FakeCollection):
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        super().__init__(documents)
        self.to_list_lengths: list[int | None] = []

    def find(self, filter_spec: dict[str, Any]) -> RecordingCursor:
        documents = [
            document
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in filter_spec.items())
        ]
        return RecordingCursor(documents, self.to_list_lengths)


def _db_with(collections: dict[str, list[dict[str, Any]]]) -> FakeDb:
    db = FakeDb()
    for name, documents in collections.items():
        db[name].documents = {str(document["_id"]): dict(document) for document in documents}
    return db


def _formula_row(
    *, item_id: str = "MLA1", price: Any = DEFAULT_PRICE, available_quantity: Any = 7
) -> dict[str, Any]:
    return {
        "_id": f"82453304:SKU-1:{item_id}",
        "seller_id": "82453304",
        "item_id": item_id,
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "current": {
            "title": "Premium widget",
            "status": "active",
            "price": price,
            "available_quantity": available_quantity,
            "updated_at": datetime(2026, 6, 16, 10, 0, tzinfo=UTC),
            "permalink": "https://example.invalid/item",
            "shipping_logistic_type": "fulfillment",
        },
        "updated_at": datetime(2026, 6, 16, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }


def _price_schema() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((ROOT / "infra/mongo/schemas/sheets_price_history_snapshots.json").read_text()),
    )


def _stockout_schema() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((ROOT / "infra/mongo/schemas/sheets_stockout_snapshots.json").read_text()),
    )


@pytest.mark.asyncio
async def test_price_seed_records_current_observed_entry_and_dedupes_latest_three() -> None:
    db = _db_with(
        {
            "sheets_item_formula_rows": [_formula_row()],
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Premium widget",
                    "prices": [
                        {
                            "price": Decimal128("119.99"),
                            "status": "paused",
                            "observed_at": datetime(2026, 6, 14, tzinfo=UTC),
                            "observation_basis": "event_observed",
                        },
                        {
                            "price": Decimal128("109.99"),
                            "status": "active",
                            "observed_at": datetime(2026, 6, 13, tzinfo=UTC),
                            "observation_basis": "event_observed",
                        },
                        {
                            "price": Decimal128("99.99"),
                            "status": "paused",
                            "observed_at": datetime(2026, 6, 12, tzinfo=UTC),
                            "observation_basis": "event_observed",
                        },
                    ],
                    "snapshot_at": datetime(2026, 6, 14, tzinfo=UTC),
                    "source": "sheets_event_persistence",
                    "observation_basis": "event_observed",
                    "schema_version": 1,
                }
            ],
        }
    )

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT
    )

    document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    assert summary.price_snapshots_planned == 1
    assert summary.price_snapshots_updated == 1
    assert document["source"] == "sheets_backfill"
    assert document["observation_basis"] == "current_observed"
    assert [entry["status"] for entry in document["prices"]] == ["active", "paused", "active"]
    assert [entry["price"].to_decimal() for entry in document["prices"]] == [
        Decimal("149.99"),
        Decimal("119.99"),
        Decimal("109.99"),
    ]
    assert document["prices"][0]["observed_at"] == datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    assert document["prices"][0]["observation_basis"] == "current_observed"
    assert validate_document_against_schema(document, _price_schema()).valid is True


@pytest.mark.asyncio
async def test_price_writer_skips_missing_price_without_inventing_history() -> None:
    db = _db_with({"sheets_item_formula_rows": [_formula_row(price=None)]})

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT
    )

    assert summary.price_snapshots_planned == 0
    assert summary.skipped_price_missing_basis == 1
    assert db["sheets_price_history_snapshots"].documents == {}


@pytest.mark.asyncio
async def test_stockout_seed_records_explicit_quantity_and_repair_safe_start_basis() -> None:
    db = _db_with({"sheets_item_formula_rows": [_formula_row(available_quantity=0)]})

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT
    )

    document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert summary.stockout_snapshots_planned == 1
    assert summary.stockout_snapshots_updated == 1
    assert document["stock_state"] == "out_of_stock"
    assert document["current_stock"] == 0
    assert document["out_of_stock_since"] == OBSERVED_AT
    assert document["observed_at"] == OBSERVED_AT
    assert document["source"] == "sheets_backfill"
    assert document["observation_basis"] == "zeler_first_observed"
    assert validate_document_against_schema(document, _stockout_schema()).valid is True


@pytest.mark.asyncio
async def test_stockout_writer_skips_rows_without_explicit_quantity_basis() -> None:
    db = _db_with({"sheets_item_formula_rows": [_formula_row(available_quantity=None)]})

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT
    )

    assert summary.stockout_snapshots_planned == 0
    assert summary.skipped_stockout_missing_basis == 1
    assert db["sheets_stockout_snapshots"].documents == {}


@pytest.mark.asyncio
async def test_variation_formula_rows_do_not_seed_item_level_price_or_stockout() -> None:
    variation_row = {
        **_formula_row(item_id="MLA1", price=Decimal128("79.99"), available_quantity=0),
        "_id": "82453304:VAR-101:MLA1:101",
        "variation_id": "101",
        "identity_level": "variation",
    }
    db = _db_with({"sheets_item_formula_rows": [variation_row]})

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT
    )

    assert summary.items_considered == 0
    assert summary.price_snapshots_planned == 0
    assert summary.stockout_snapshots_planned == 0
    assert db["sheets_price_history_snapshots"].documents == {}
    assert db["sheets_stockout_snapshots"].documents == {}


@pytest.mark.asyncio
async def test_seed_respects_max_items_limit_for_current_observed_candidates() -> None:
    db = _db_with(
        {
            "sheets_item_formula_rows": [
                _formula_row(item_id="MLA1"),
                _formula_row(item_id="MLA2", price=Decimal128("249.99"), available_quantity=3),
            ]
        }
    )

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=False, now=OBSERVED_AT, max_items=1
    )

    assert summary.items_considered == 1
    assert summary.price_snapshots_planned == 1
    assert summary.stockout_snapshots_planned == 1
    assert set(db["sheets_price_history_snapshots"].documents) == {"82453304:MLA1"}
    assert set(db["sheets_stockout_snapshots"].documents) == {"82453304:MLA1"}


@pytest.mark.asyncio
async def test_seed_applies_max_items_limit_before_materializing_all_candidates() -> None:
    formula_rows = RecordingFindCollection(
        [
            _formula_row(item_id="MLA1"),
            _formula_row(item_id="MLA2", price=Decimal128("249.99"), available_quantity=3),
        ]
    )
    items = RecordingFindCollection([{"_id": "MLA3", "seller_id": "82453304"}])
    db = FakeDb()
    db.collections["sheets_item_formula_rows"] = formula_rows
    db.collections["items"] = items

    summary = await run_remaining_observed_read_model_seed(
        db=db, seller_id="82453304", dry_run=True, now=OBSERVED_AT, max_items=1
    )

    assert summary.items_considered == 1
    assert formula_rows.to_list_lengths == [1]
    assert items.to_list_lengths == []


@pytest.mark.asyncio
async def test_stockout_seed_uses_current_observation_when_status_basis_is_missing() -> None:
    db = _db_with({"sheets_item_formula_rows": [_formula_row(available_quantity=0)]})

    await run_remaining_observed_read_model_seed(
        db=db,
        seller_id="82453304",
        dry_run=False,
        now_fn=lambda: OBSERVED_AT,
    )

    document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert document["observed_at"] == OBSERVED_AT
    assert document["out_of_stock_since"] == OBSERVED_AT
    assert document["observation_basis"] == "zeler_first_observed"


@pytest.mark.asyncio
async def test_go_forward_observations_dedupe_price_and_preserve_stockout_start() -> None:
    db = FakeDb()
    item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Premium widget",
        "status": "active",
        "price": Decimal128("149.99"),
        "available_quantity": 0,
    }

    await record_price_history_observation(
        db,
        item,
        seller_id="82453304",
        observed_at=datetime(2026, 6, 17, 10, 0, tzinfo=UTC),
        source="sheets_event_persistence",
        observation_basis="event_observed",
    )
    await record_price_history_observation(
        db,
        item,
        seller_id="82453304",
        observed_at=datetime(2026, 6, 17, 11, 0, tzinfo=UTC),
        source="sheets_event_persistence",
        observation_basis="event_observed",
    )
    await record_stockout_observation(
        db,
        item,
        seller_id="82453304",
        observed_at=datetime(2026, 6, 17, 10, 0, tzinfo=UTC),
        source="sheets_event_persistence",
        observation_basis="event_observed",
    )
    await record_stockout_observation(
        db,
        {**item, "price": Decimal128("159.99")},
        seller_id="82453304",
        observed_at=datetime(2026, 6, 17, 11, 0, tzinfo=UTC),
        source="sheets_event_persistence",
        observation_basis="event_observed",
    )

    price_document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    stockout_document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert len(price_document["prices"]) == 1
    assert stockout_document["out_of_stock_since"] == datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
    assert stockout_document["observed_at"] == datetime(2026, 6, 17, 11, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_older_observations_do_not_regress_newer_price_or_stockout_docs() -> None:
    newer_observed_at = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    older_observed_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
    db = _db_with(
        {
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Premium widget",
                    "prices": [
                        {
                            "price": Decimal128("199.99"),
                            "status": "active",
                            "observed_at": newer_observed_at,
                            "observation_basis": "event_observed",
                        }
                    ],
                    "snapshot_at": newer_observed_at,
                    "source": "sheets_event_persistence",
                    "observation_basis": "event_observed",
                    "schema_version": 1,
                }
            ],
            "sheets_stockout_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "stock_state": "out_of_stock",
                    "current_stock": 0,
                    "out_of_stock_since": newer_observed_at,
                    "observed_at": newer_observed_at,
                    "source": "sheets_event_persistence",
                    "observation_basis": "event_observed",
                    "schema_version": 1,
                }
            ],
        }
    )
    stale_item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Premium widget",
        "status": "paused",
        "price": Decimal128("149.99"),
        "available_quantity": 7,
    }

    price_updated = await record_price_history_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=older_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )
    stockout_updated = await record_stockout_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=older_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    price_document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    stockout_document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert price_updated is False
    assert stockout_updated is False
    assert [entry["price"].to_decimal() for entry in price_document["prices"]] == [
        Decimal("199.99")
    ]
    assert price_document["snapshot_at"] == newer_observed_at
    assert stockout_document["stock_state"] == "out_of_stock"
    assert stockout_document["observed_at"] == newer_observed_at


@pytest.mark.asyncio
async def test_first_write_race_does_not_stale_overwrite_concurrently_inserted_docs() -> None:
    fresher_observed_at = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    stale_observed_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
    fresh_price_doc = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "title": "Fresh widget",
        "prices": [
            {
                "price": Decimal128("199.99"),
                "status": "active",
                "observed_at": fresher_observed_at,
                "observation_basis": "event_observed",
            }
        ],
        "snapshot_at": fresher_observed_at,
        "source": "sheets_event_persistence",
        "observation_basis": "event_observed",
        "schema_version": 1,
    }
    fresh_stockout_doc = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "stock_state": "out_of_stock",
        "current_stock": 0,
        "out_of_stock_since": fresher_observed_at,
        "observed_at": fresher_observed_at,
        "source": "sheets_event_persistence",
        "observation_basis": "event_observed",
        "schema_version": 1,
    }
    db = FakeDb()
    db.collections["sheets_price_history_snapshots"] = ConcurrentFreshInsertCollection(
        fresh_document=fresh_price_doc
    )
    db.collections["sheets_stockout_snapshots"] = ConcurrentFreshInsertCollection(
        fresh_document=fresh_stockout_doc
    )
    stale_item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Stale widget",
        "status": "paused",
        "price": Decimal128("149.99"),
        "available_quantity": 7,
    }

    price_updated = await record_price_history_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=stale_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )
    stockout_updated = await record_stockout_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=stale_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    price_document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    stockout_document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert price_updated is False
    assert stockout_updated is False
    assert price_document["title"] == "Fresh widget"
    assert price_document["prices"][0]["price"].to_decimal() == Decimal("199.99")
    assert price_document["snapshot_at"] == fresher_observed_at
    assert stockout_document["stock_state"] == "out_of_stock"
    assert stockout_document["observed_at"] == fresher_observed_at


@pytest.mark.asyncio
async def test_numeric_seller_legacy_docs_with_newer_observation_are_not_overwritten() -> None:
    newer_observed_at = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    older_observed_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)
    db = _db_with(
        {
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": 82453304,
                    "item_id": "MLA1",
                    "title": "Legacy widget",
                    "prices": [
                        {
                            "price": Decimal128("199.99"),
                            "status": "active",
                            "observed_at": newer_observed_at,
                            "observation_basis": "event_observed",
                        }
                    ],
                    "snapshot_at": newer_observed_at,
                    "source": "sheets_event_persistence",
                    "observation_basis": "event_observed",
                    "schema_version": 1,
                }
            ],
            "sheets_stockout_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": 82453304,
                    "item_id": "MLA1",
                    "stock_state": "out_of_stock",
                    "current_stock": 0,
                    "out_of_stock_since": newer_observed_at,
                    "observed_at": newer_observed_at,
                    "source": "sheets_event_persistence",
                    "observation_basis": "event_observed",
                    "schema_version": 1,
                }
            ],
        }
    )
    stale_item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Premium widget",
        "status": "paused",
        "price": Decimal128("149.99"),
        "available_quantity": 7,
    }

    price_updated = await record_price_history_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=older_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )
    stockout_updated = await record_stockout_observation(
        db,
        stale_item,
        seller_id="82453304",
        observed_at=older_observed_at,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    price_document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    stockout_document = db["sheets_stockout_snapshots"].documents["82453304:MLA1"]
    assert price_updated is False
    assert stockout_updated is False
    assert price_document["seller_id"] == 82453304
    assert price_document["prices"][0]["price"].to_decimal() == Decimal("199.99")
    assert price_document["snapshot_at"] == newer_observed_at
    assert stockout_document["seller_id"] == 82453304
    assert stockout_document["stock_state"] == "out_of_stock"
    assert stockout_document["observed_at"] == newer_observed_at


@pytest.mark.asyncio
async def test_price_writer_normalizes_legacy_entries_missing_observation_basis() -> None:
    db = _db_with(
        {
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Legacy widget",
                    "prices": [
                        {
                            "price": Decimal128("129.99"),
                            "status": "paused",
                            "observed_at": datetime(2026, 6, 16, tzinfo=UTC),
                        }
                    ],
                    "snapshot_at": datetime(2026, 6, 16, tzinfo=UTC),
                    "source": "sheets_backfill",
                    "observation_basis": "current_observed",
                    "schema_version": 1,
                }
            ]
        }
    )

    updated = await record_price_history_observation(
        db,
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Premium widget",
            "status": "active",
            "price": Decimal128("149.99"),
        },
        seller_id="82453304",
        observed_at=OBSERVED_AT,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    assert updated is True
    assert [entry["observation_basis"] for entry in document["prices"]] == [
        "current_observed",
        "current_observed",
    ]
    assert validate_document_against_schema(document, _price_schema()).valid is True


@pytest.mark.asyncio
async def test_same_price_legacy_doc_is_rewritten_with_required_basis_metadata() -> None:
    db = _db_with(
        {
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Legacy widget",
                    "prices": [
                        {
                            "price": Decimal128("149.99"),
                            "status": "active",
                            "observed_at": datetime(2026, 6, 16, tzinfo=UTC),
                        }
                    ],
                    "snapshot_at": datetime(2026, 6, 16, tzinfo=UTC),
                    "source": "sheets_backfill",
                    "schema_version": 1,
                }
            ]
        }
    )

    updated = await record_price_history_observation(
        db,
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Premium widget",
            "status": "active",
            "price": Decimal128("149.99"),
        },
        seller_id="82453304",
        observed_at=OBSERVED_AT,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    assert updated is True
    assert document["observation_basis"] == "current_observed"
    assert [entry["observation_basis"] for entry in document["prices"]] == ["current_observed"]
    assert len(document["prices"]) == 1
    assert validate_document_against_schema(document, _price_schema()).valid is True


@pytest.mark.asyncio
async def test_same_price_writer_normalizes_invalid_legacy_source_and_types() -> None:
    db = _db_with(
        {
            "sheets_price_history_snapshots": [
                {
                    "_id": "82453304:MLA1",
                    "seller_id": "82453304",
                    "item_id": "MLA1",
                    "title": "Legacy widget",
                    "prices": [
                        {
                            "price": "149.99",
                            "status": "active",
                            "observed_at": "2026-06-16T00:00:00Z",
                            "observation_basis": "legacy_scrape",
                        }
                    ],
                    "snapshot_at": "2026-06-16T00:00:00Z",
                    "source": "legacy_sheetseller",
                    "observation_basis": "legacy_scrape",
                    "schema_version": 1,
                }
            ]
        }
    )

    updated = await record_price_history_observation(
        db,
        {
            "_id": "MLA1",
            "seller_id": "82453304",
            "title": "Premium widget",
            "status": "active",
            "price": Decimal128("149.99"),
        },
        seller_id="82453304",
        observed_at=OBSERVED_AT,
        source="sheets_backfill",
        observation_basis="current_observed",
    )

    document = db["sheets_price_history_snapshots"].documents["82453304:MLA1"]
    assert updated is True
    assert document["source"] == "sheets_backfill"
    assert document["observation_basis"] == "current_observed"
    assert document["snapshot_at"] == datetime(2026, 6, 16, tzinfo=UTC)
    assert document["prices"] == [
        {
            "price": Decimal128("149.99"),
            "status": "active",
            "observed_at": datetime(2026, 6, 16, tzinfo=UTC),
            "observation_basis": "current_observed",
        }
    ]
    assert validate_document_against_schema(document, _price_schema()).valid is True
