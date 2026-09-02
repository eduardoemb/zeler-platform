from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import zeler_sheets
from zeler_sheets import _stock_time_forward_engine as engine

ROOT = Path(__file__).resolve().parents[3]


def test_stock_time_index_descriptors_match_canonical_contracts_and_are_private() -> None:
    descriptors = engine._STOCK_TIME_WRITE_EXPECTED_INDEXES

    assert tuple(collection for collection, _ in descriptors) == (
        "sheets_stock_time_metrics",
        "sheets_read_model_freshness",
        "sheets_stock_time_reconciliation_operations",
        "sheets_stock_time_reconciliation_preimages",
    )
    for collection, expected in descriptors:
        canonical = json.loads((ROOT / "infra/mongo/indexes" / f"{collection}.json").read_text())
        assert [(item.name, list(item.keys), item.unique) for item in expected] == [
            (
                item["options"]["name"],
                list(item["keys"].items()),
                item["options"].get("unique", False),
            )
            for item in canonical
        ]

    descriptor = descriptors[0][1][0]
    with pytest.raises(TypeError):
        descriptors[0] = ("other", ())  # type: ignore[index]
    with pytest.raises(TypeError):
        descriptor.keys[0] = ("other", 1)  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "other"  # type: ignore[misc]
    assert not hasattr(zeler_sheets, "_StockTimeIndexDescriptor")
    assert not hasattr(zeler_sheets, "_STOCK_TIME_WRITE_EXPECTED_INDEXES")
