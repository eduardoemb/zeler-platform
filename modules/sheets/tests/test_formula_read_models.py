from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.read_models import (
    FormulaReadModelRepository,
    read_model_reconciliation_marker_covers,
)


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.sort_spec: list[tuple[str, int]] | None = None
        self.to_list_length: int | None | object = _UNSET

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = sort_spec
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: str(doc.get(key, "")), reverse=direction < 0)
        self._docs = sorted_docs
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        self.to_list_length = length
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.last_cursor: FakeCursor | None = None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        del filter_spec
        self.last_cursor = FakeCursor(self._docs)
        return self.last_cursor

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return None


class FakeDb:
    def __init__(self, item_rows: list[dict[str, Any]]) -> None:
        self._collections = {"sheets_item_formula_rows": FakeCollection(item_rows)}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection([]))


_UNSET = object()


def test_expired_recovery_proof_does_not_authorize_formula_reads() -> None:
    now = datetime.now(UTC)
    marker = {
        "state": "reconciled",
        "date_from": now - timedelta(days=30),
        "reconciled_until": now,
        "valid_until": now - timedelta(seconds=1),
    }
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=now - timedelta(days=2),
        date_to=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "read_model", "has_start"),
    [
        ("require_questions_read_model_productive", "questions", True),
        ("require_read_model_productive", "item_formula_rows", False),
        ("require_read_model_reconciled_range", "stock_time_metrics", True),
    ],
)
async def test_missing_model_identifies_exact_recovery_scope(
    method: str, read_model: str, has_start: bool
) -> None:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    end = datetime(2026, 9, 7, tzinfo=UTC)
    kwargs: dict[str, Any] = {"seller_id": "seller-1", "date_to": end, "formula": "ZELERDATA_TEST"}
    if has_start:
        kwargs["date_from"] = start
    if read_model != "questions":
        kwargs["read_model"] = read_model

    with pytest.raises(FormulaDataUnavailableError) as caught:
        await getattr(FormulaReadModelRepository(db=FakeDb([])), method)(**kwargs)

    assert caught.value.read_model == read_model
    assert caught.value.date_from == (start if has_start else None)
    assert caught.value.date_to == end


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "collection", "count", "kwargs"),
    [
        ("find_item_formula_rows", "sheets_item_formula_rows", 501, {}),
        ("find_sku_index_rows", "sheets_item_sku_index", 501, {}),
        (
            "find_orders",
            "orders",
            1001,
            {"date_from": "2026-08-08", "date_to": "2026-09-07"},
        ),
    ],
)
async def test_formula_sources_do_not_silently_truncate_complete_results(
    method: str, collection: str, count: int, kwargs: dict[str, Any]
) -> None:
    db = FakeDb([])
    db._collections[collection] = FakeCollection(
        [{"_id": str(index), "seller_id": "seller-1"} for index in range(count)]
    )
    repository = FormulaReadModelRepository(db=db)

    rows = await getattr(repository, method)(seller_id="seller-1", **kwargs)

    assert len(rows) == count


@pytest.mark.asyncio
async def test_item_formula_rows_can_use_publication_order_without_500_row_truncation() -> None:
    rows = [
        {"_id": f"row-{index}", "seller_id": "seller-1", "item_id": f"MLA{index:03d}"}
        for index in range(501)
    ]
    db = FakeDb(rows)
    repository = FormulaReadModelRepository(db=db)

    result = await repository.find_item_formula_rows(
        seller_id="seller-1",
        sort_by="publication",
        limit=None,
    )

    assert len(result) == 501
    cursor = db["sheets_item_formula_rows"].last_cursor
    assert cursor is not None
    assert cursor.sort_spec == [
        ("item_id", 1),
        ("variation_id", 1),
        ("normalized_sku", 1),
        ("_id", 1),
    ]
    assert cursor.to_list_length is None
