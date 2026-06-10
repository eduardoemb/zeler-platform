from __future__ import annotations

from typing import Any

import pytest

from zeler_sheets.formulas.read_models import FormulaReadModelRepository


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


class FakeDb:
    def __init__(self, item_rows: list[dict[str, Any]]) -> None:
        self._collections = {"sheets_item_formula_rows": FakeCollection(item_rows)}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection([]))


_UNSET = object()


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
