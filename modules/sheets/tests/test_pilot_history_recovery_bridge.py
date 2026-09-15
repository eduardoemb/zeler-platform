from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zeler_sheets.pilot_history import ChunkPriority, HistoryChunk
from zeler_sheets.pilot_history_recovery_bridge import chunk_to_recovery_request

START = datetime(2026, 8, 14, tzinfo=UTC)
END = datetime(2026, 9, 14, tzinfo=UTC)
SELLER = "82453304"


def _chunk(resource: str) -> HistoryChunk:
    return HistoryChunk(
        resource=resource, start=START, end=END, id="test-chunk", priority=ChunkPriority.MIDDLE
    )


def test_orders_chunk_maps_to_orders_recovery_request() -> None:
    request = chunk_to_recovery_request(_chunk("orders"), seller_id=SELLER)
    assert request.seller_id == SELLER
    assert request.read_model == "orders"
    assert request.date_from == START
    assert request.date_to == END


def test_questions_chunk_maps_to_questions_read_model() -> None:
    request = chunk_to_recovery_request(_chunk("questions"), seller_id=SELLER)
    assert request.read_model == "questions"


def test_shipments_chunk_maps_to_shipments_read_model() -> None:
    request = chunk_to_recovery_request(_chunk("shipments"), seller_id=SELLER)
    assert request.read_model == "shipments"


def test_items_chunk_maps_to_item_formula_rows_read_model() -> None:
    request = chunk_to_recovery_request(_chunk("items"), seller_id=SELLER)
    assert request.read_model == "item_formula_rows"


def test_unknown_resource_is_rejected() -> None:
    with pytest.raises(ValueError, match="no recoverable read model"):
        chunk_to_recovery_request(_chunk("unknown_resource"), seller_id=SELLER)


def test_empty_seller_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="seller_id is required"):
        chunk_to_recovery_request(_chunk("orders"), seller_id="")
