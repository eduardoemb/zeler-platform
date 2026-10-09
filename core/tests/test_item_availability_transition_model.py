from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from zeler_platform_core.models import ItemAvailabilityTransition

OBSERVED_AT = datetime(2026, 10, 9, 21, 15, tzinfo=UTC)


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "_id": "82453304:MLM1:-:2026-10-09T21:15:00+00:00",
        "seller_id": 82453304,
        "item_id": "MLM1",
        "variation_id": None,
        "sku": "SKU-1",
        "available": True,
        "status": "active",
        "available_quantity": 3,
        "observed_at": OBSERVED_AT,
        "source": "sheets_event_persistence",
        **overrides,
    }


def test_item_availability_transition_dumps_the_validated_row() -> None:
    row = ItemAvailabilityTransition.model_validate(_payload(variation_id=181))

    assert row.model_dump(by_alias=True, mode="python") == {
        "_id": "82453304:MLM1:-:2026-10-09T21:15:00+00:00",
        "seller_id": "82453304",
        "item_id": "MLM1",
        "variation_id": "181",
        "sku": "SKU-1",
        "available": True,
        "status": "active",
        "available_quantity": 3,
        "observed_at": OBSERVED_AT,
        "source": "sheets_event_persistence",
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"available_quantity": -1},
        {"item_id": " "},
        {"status": ""},
        {"observed_at": datetime(2026, 10, 9, 21, 15)},  # noqa: DTZ001 - naive on purpose
        {"source": "legacy_history_import"},
    ],
)
def test_item_availability_transition_rejects_untrustworthy_rows(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        ItemAvailabilityTransition.model_validate(_payload(**overrides))
