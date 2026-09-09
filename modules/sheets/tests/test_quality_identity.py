from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_sheets.formulas.handlers_quality_calculator import _quality_row
from zeler_sheets.quality import project_item_quality

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def resource() -> dict[str, Any]:
    return {
        "entity_type": "USER_PRODUCT",
        "entity_id": "MLAU123",
        "score": 69,
        "level": "Good",
        "calculated_at": NOW.isoformat(),
        "buckets": [],
    }


def test_quality_reader_requires_current_owned_user_product_relationship() -> None:
    quality = project_item_quality(
        resource(), item_id="MLA1", user_product_id="MLAU123", observed_at=NOW
    )
    row: dict[str, Any] = {
        "item_id": "MLA1",
        "current": {"quality_projection": quality, "user_product_id": "MLAU123"},
    }
    assert _quality_row(row, now=NOW)[7] == 69
    row["current"]["user_product_id"] = "MLAU999"
    assert _quality_row(row, now=NOW)[7:] == ["DATA_UNAVAILABLE"] * 12


@pytest.mark.parametrize("linked_id", [None, "MLAU999", "MLBU123"])
def test_quality_rejects_unverified_user_product(linked_id: str | None) -> None:
    with pytest.raises(ValueError):
        project_item_quality(resource(), item_id="MLA1", user_product_id=linked_id, observed_at=NOW)
