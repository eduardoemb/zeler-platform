"""Provider question scan pages keep the live cursor and count semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from zeler_sheets.history_questions import (
    fetch_question_scan_page,
    normalize_question_scan_page,
)

NOW = datetime(2026, 9, 24, 7, tzinfo=UTC)


def response(*, total: int, rows: int, cursor: Any) -> dict[str, Any]:
    return {
        "total": total,
        "questions": [{"id": index + 1} for index in range(rows)],
        "scroll_id": cursor,
    }


def test_final_count_clears_live_provider_cursor() -> None:
    page = normalize_question_scan_page(
        response(total=231, rows=31, cursor="new-opaque-cursor"),
        discovered_count=200,
        observed_at=NOW,
    )
    assert page.terminal is True
    assert page.next_cursor is None
    assert len(page.rows) == 31
    assert page.total == 231


def test_nonterminal_page_keeps_rotated_cursor() -> None:
    page = normalize_question_scan_page(
        response(total=231, rows=50, cursor="replacement-cursor"),
        discovered_count=50,
        observed_at=NOW,
    )
    assert page.terminal is False
    assert page.next_cursor == "replacement-cursor"


@pytest.mark.parametrize(
    "raw,discovered_count",
    [
        (response(total=3, rows=1, cursor=None), 0),
        (response(total=2, rows=1, cursor="opaque"), 2),
        (response(total=10001, rows=1, cursor="opaque"), 0),
        (response(total=52, rows=51, cursor="opaque"), 0),
        ({"total": 1, "questions": [None], "scroll_id": "opaque"}, 0),
    ],
)
def test_normalizer_rejects_incomplete_or_invalid_page(
    raw: dict[str, Any], discovered_count: int
) -> None:
    with pytest.raises(ValueError):
        normalize_question_scan_page(raw, discovered_count=discovered_count, observed_at=NOW)


@pytest.mark.asyncio
async def test_gateway_scan_uses_limit_only_on_first_page_and_rotates_cursor() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.paths: list[str] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            assert seller_id == "82453304"
            self.paths.append(path)
            return response(
                total=2,
                rows=1,
                cursor="first-cursor" if len(self.paths) == 1 else "second-cursor",
            )

    gateway = Gateway()
    first = await fetch_question_scan_page(
        gateway, seller_id="82453304", cursor=None, discovered_count=0, observed_at=NOW
    )
    second = await fetch_question_scan_page(
        gateway,
        seller_id="82453304",
        cursor=first.next_cursor,
        discovered_count=1,
        observed_at=NOW,
    )

    assert parse_qs(urlparse(gateway.paths[0]).query) == {
        "seller_id": ["82453304"],
        "api_version": ["4"],
        "search_type": ["scan"],
        "limit": ["50"],
    }
    assert parse_qs(urlparse(gateway.paths[1]).query) == {
        "seller_id": ["82453304"],
        "api_version": ["4"],
        "search_type": ["scan"],
        "scroll_id": ["first-cursor"],
    }
    assert first.next_cursor == "first-cursor" and not first.terminal
    assert second.next_cursor is None and second.terminal
