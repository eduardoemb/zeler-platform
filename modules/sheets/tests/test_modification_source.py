from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from zeler_sheets.modification_recovery import (
    ModificationEnumerationDriftError,
    fetch_modification_page,
)

NOW = datetime(2026, 9, 15, 12, 17, tzinfo=UTC)
WATERMARK = NOW - timedelta(hours=1)
START = WATERMARK - timedelta(hours=24)


def order(identity: int, modified: datetime, *, seller: int = 82453304) -> dict[str, Any]:
    return {
        "id": identity,
        "seller": {"id": seller},
        "date_created": "2026-02-01T00:00:00Z",
        "date_last_updated": modified.isoformat(),
    }


class Gateway:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, list[str]]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == "82453304"
        assert urlsplit(path).path == "/orders/search"
        query = parse_qs(urlsplit(path).query)
        self.calls.append(query)
        return self.pages[int(query["offset"][0])]


def response(rows: list[dict[str, Any]], *, total: int, offset: int = 0) -> dict[str, Any]:
    return {"paging": {"total": total, "offset": offset, "limit": 50}, "results": rows}


@pytest.mark.asyncio
async def test_modification_page_queries_hour_superset_and_keeps_exact_window() -> None:
    outside_start = order(1, START - timedelta(minutes=10))
    inside = order(2, START)
    outside_end = order(3, NOW)
    gateway = Gateway({0: response([outside_start, inside, outside_end], total=3)})

    result = await fetch_modification_page(
        gateway, seller_id="82453304", watermark=WATERMARK, cutoff=NOW
    )

    assert result.page.rows == [outside_start, inside, outside_end]
    assert result.page.watermark == WATERMARK and result.page.cutoff == NOW
    assert result.source_total == 3 and result.next_offset is None
    query = gateway.calls[0]
    assert query["seller"] == ["82453304"]
    assert query["order.date_last_updated.from"] == [
        START.replace(minute=0, second=0, microsecond=0).isoformat(timespec="milliseconds")
    ]
    assert query["order.date_last_updated.to"] == [
        NOW.replace(minute=0, second=0, microsecond=0).isoformat(timespec="milliseconds")
    ]
    assert query["offset"] == ["0"] and query["limit"] == ["50"]
    assert "order.date_created.from" not in query


@pytest.mark.asyncio
async def test_modification_page_exposes_bounded_continuation_with_total_check() -> None:
    rows = [order(index, START + timedelta(minutes=1)) for index in range(1, 52)]
    gateway = Gateway(
        {0: response(rows[:50], total=51), 50: response(rows[50:], total=51, offset=50)}
    )
    first = await fetch_modification_page(
        gateway, seller_id="82453304", watermark=WATERMARK, cutoff=NOW
    )
    assert first.next_offset == 50
    second = await fetch_modification_page(
        gateway,
        seller_id="82453304",
        watermark=WATERMARK,
        cutoff=NOW,
        offset=first.next_offset,
        expected_total=first.source_total,
    )
    assert len(first.page.rows) == 50 and first.next_offset == 50
    assert len(second.page.rows) == 1 and second.next_offset is None


@pytest.mark.asyncio
async def test_modification_page_excludes_the_unstarted_upper_hour() -> None:
    cutoff = NOW.replace(minute=0)
    gateway = Gateway({0: response([], total=0)})
    result = await fetch_modification_page(
        gateway, seller_id="82453304", watermark=WATERMARK, cutoff=cutoff
    )
    assert result.next_offset is None
    assert gateway.calls[0]["order.date_last_updated.to"] == [
        (cutoff - timedelta(hours=1)).isoformat(timespec="milliseconds")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad_page", "expected_total"),
    [
        (response([], total=1), None),
        (response([order(1, START)], total=2, offset=1), None),
        (response([order(1, START), order(1, START)], total=2), None),
        (response([order(1, START, seller=99)], total=1), None),
        (response([order(1, START - timedelta(hours=2))], total=1), None),
        (response([order(1, START)], total=1), 2),
        ({"paging": {"total": 0, "offset": False, "limit": 50}, "results": []}, None),
    ],
)
async def test_modification_page_rejects_drift_and_invalid_source(
    bad_page: dict[str, Any], expected_total: int | None
) -> None:
    gateway = Gateway({0: bad_page})
    with pytest.raises(ModificationEnumerationDriftError):
        await fetch_modification_page(
            gateway,
            seller_id="82453304",
            watermark=WATERMARK,
            cutoff=NOW,
            expected_total=expected_total,
        )


@pytest.mark.asyncio
async def test_modification_page_rejects_invalid_offset_before_source_call() -> None:
    gateway = Gateway({})
    with pytest.raises(ValueError):
        await fetch_modification_page(
            gateway, seller_id="82453304", watermark=WATERMARK, cutoff=NOW, offset=-1
        )
    assert gateway.calls == []
