from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from test_event_persistence import FakeDb

from zeler_sheets.onboarding_sources import collect_full_operations, collect_pack_messages

START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)


class Gateway:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages
        self.paths: list[str] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == "123"
        self.paths.append(path)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return cast(dict[str, Any], page)


def message(mid: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "id": mid,
        "from": {"user_id": "321"},
        "to": {"user_id": "123"},
        "status": "available",
        "text": "private fixture content",
        "message_date": {"created": "2026-06-04T10:00:00Z", "read": None},
        **kwargs,
    }


@pytest.mark.asyncio
async def test_messages_paginate_checkpoint_deduplicate_packs_and_preserve_content() -> None:
    db = FakeDb()
    gateway = Gateway(
        [
            {"paging": {"total": 2, "offset": 0}, "messages": [message("m1")]},
            {"paging": {"total": 2, "offset": 1}, "messages": [message("m2")]},
        ]
    )
    first = await collect_pack_messages(
        db=db,
        gateway=gateway,
        seller_id="123",
        targets=["400", "400"],
        start=START,
        end=END,
        max_requests=1,
        page_size=1,
    )
    assert not first["coverage_complete"]
    assert first["checkpoint"]["offset"] == 1
    second = await collect_pack_messages(
        db=db,
        gateway=gateway,
        seller_id="123",
        targets=["400", "400"],
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
        max_requests=1,
        page_size=1,
    )
    assert second["coverage_complete"]
    assert set(db["messages"].documents) == {"m1", "m2"}
    assert db["messages"].documents["m1"]["pack_id"] == "400"
    assert db["messages"].documents["m1"]["date_created"].tzinfo is not None
    assert "private fixture content" not in str(second)
    assert all(parse_qs(urlsplit(p).query)["mark_as_read"] == ["false"] for p in gateway.paths)


@pytest.mark.asyncio
async def test_messages_missing_record_does_not_block_valid_record_or_other_pack() -> None:
    db = FakeDb()
    db["messages"].documents["foreign"] = {"_id": "foreign", "seller_id": "999", "text": "retain"}
    gateway = Gateway(
        [
            {
                "paging": {"total": 3, "offset": 0},
                "messages": [message("m1"), message("bad", text=None), message("foreign")],
            },
            {"paging": {"total": 0, "offset": 0}, "messages": []},
        ]
    )
    result = await collect_pack_messages(
        db=db,
        gateway=gateway,
        seller_id="123",
        targets=["400", "401"],
        start=START,
        end=END,
        max_requests=2,
    )
    assert result["discovery_complete"]
    assert not result["coverage_complete"]
    assert result["persisted"] == 1
    assert db["messages"].documents["foreign"]["seller_id"] == "999"
    assert result["issue_count"] == 2


@pytest.mark.asyncio
async def test_full_same_scroll_token_is_valid_and_operations_never_fabricate_retiros() -> None:
    db = FakeDb()

    def operation(oid: int, kind: str) -> dict[str, Any]:
        return {
            "id": oid,
            "seller_id": 123,
            "inventory_id": "INV1",
            "type": kind,
            "date_created": "2026-06-04T10:00:00Z",
            "detail": {"not_available_quantity": -3},
        }

    gateway = Gateway(
        [
            {
                "paging": {"scroll": "same", "total": 3},
                "results": [operation(1, "WITHDRAWAL_RESERVATION")],
            },
            {
                "paging": {"scroll": "same", "total": 3},
                "results": [operation(2, "WITHDRAWAL_DELIVERY")],
            },
            {
                "paging": {"scroll": None, "total": 3},
                "results": [operation(3, "SALE_CONFIRMATION")],
            },
            *[{"paging": {"scroll": None}, "results": []}] * 4,
        ]
    )
    result = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, max_requests=7
    )
    assert result["discovery_complete"]
    assert not result["coverage_complete"]
    assert result["blocked_reason"] == "full_withdrawal_contract_incompatible"
    assert len(db["sheets_full_operations"].documents) == 2
    assert not db["sheets_full_withdrawals"].documents
    assert db["sheets_full_operations"].documents["123:2"]["type"] == "WITHDRAWAL_DELIVERY"
    assert all(parse_qs(urlsplit(p).query)["seller_id"] == ["123"] for p in gateway.paths)


@pytest.mark.asyncio
async def test_full_forbidden_is_not_no_applica_and_no_secret_in_report() -> None:
    request = httpx.Request("GET", "https://example.test/sensitive-token")
    error = httpx.HTTPStatusError(
        "private secret", request=request, response=httpx.Response(403, request=request)
    )
    result = await collect_full_operations(
        db=FakeDb(), gateway=Gateway([error]), seller_id="123", start=START, end=END
    )
    assert result["blocked_reason"] == "access_denied"
    assert not result["discovery_complete"]
    assert "private secret" not in str(result)


@pytest.mark.asyncio
async def test_checkpoint_cannot_move_between_sellers_or_intervals() -> None:
    with pytest.raises(ValueError):
        await collect_pack_messages(
            db=FakeDb(),
            gateway=Gateway([]),
            seller_id="123",
            targets=["400"],
            start=START,
            end=END,
            checkpoint={"seller_id": "999"},
        )


@pytest.mark.asyncio
async def test_invalid_identity_isolated_and_transient_retry_does_not_poison_coverage() -> None:
    db = FakeDb()
    request = httpx.Request("GET", "https://example.test/")
    error = httpx.HTTPStatusError(
        "private", request=request, response=httpx.Response(429, request=request)
    )
    gateway = Gateway(
        [
            error,
            {"paging": {"total": 2, "offset": 0}, "messages": [message("bad/id"), message("ok")]},
        ]
    )
    first = await collect_pack_messages(
        db=db, gateway=gateway, seller_id="123", targets=["400"], start=START, end=END
    )
    second = await collect_pack_messages(
        db=db,
        gateway=gateway,
        seller_id="123",
        targets=["400"],
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
    )
    assert second["discovery_complete"]
    assert second["issue_count"] == 1
    assert second["persisted"] == 1


@pytest.mark.asyncio
async def test_successful_retry_eventually_certifies_message_discovery() -> None:
    request = httpx.Request("GET", "https://example.test/")
    error = httpx.HTTPStatusError(
        "private", request=request, response=httpx.Response(503, request=request)
    )
    gateway = Gateway([error, {"paging": {"total": 0, "offset": 0}, "messages": []}])
    first = await collect_pack_messages(
        db=FakeDb(), gateway=gateway, seller_id="123", targets=["400"], start=START, end=END
    )
    second = await collect_pack_messages(
        db=FakeDb(),
        gateway=gateway,
        seller_id="123",
        targets=["400"],
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
    )
    assert second["coverage_complete"]


@pytest.mark.asyncio
async def test_full_scroll_expiry_restarts_without_losing_or_duplicating_operations() -> None:
    db = FakeDb()
    raw = {
        "id": 1,
        "seller_id": 123,
        "inventory_id": "INV1",
        "type": "WITHDRAWAL_RESERVATION",
        "date_created": "2026-06-04T10:00:00Z",
        "detail": {"not_available_quantity": 3},
    }
    gateway = Gateway(
        [
            {"paging": {"scroll": "old"}, "results": [raw]},
            {
                "paging": {"scroll": None},
                "results": [{**raw, "detail": {"not_available_quantity": 4}}],
            },
            *[{"paging": {"scroll": None}, "results": []}] * 4,
        ]
    )
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, now=START
    )
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        now=START.replace(minute=6),
        checkpoint=first["checkpoint"],
        max_requests=5,
    )
    assert "scroll=" not in gateway.paths[1]
    assert len(db["sheets_full_operations"].documents) == 1
    assert db["sheets_full_operations"].documents["123:1"]["detail"]["not_available_quantity"] == 4
    assert second["discovery_complete"]


@pytest.mark.asyncio
async def test_full_empty_result_is_not_proven_ineligible_and_preserves_legacy_rows() -> None:
    db = FakeDb()
    legacy = {
        "_id": "123:ret:detail:inventory",
        "seller_id": "123",
        "source": "legacy_history_import",
    }
    db["sheets_full_withdrawals"].documents[legacy["_id"]] = dict(legacy)
    result = await collect_full_operations(
        db=db,
        gateway=Gateway([{"paging": {"scroll": None}, "results": []}]),
        seller_id="123",
        start=START,
        end=END,
    )
    assert result["blocked_reason"] == "full_withdrawal_contract_incompatible"
    assert not result["coverage_complete"]
    assert db["sheets_full_withdrawals"].documents[legacy["_id"]] == legacy


@pytest.mark.asyncio
async def test_message_update_preserves_known_order_and_read_timestamp() -> None:
    db = FakeDb()
    initial = message("m1", order_id=501, read_at="2026-06-05T10:00:00Z")
    later = message("m1", text="changed", message_date={"created": "2026-06-04T10:00:00Z"})
    for raw in (initial, later):
        await collect_pack_messages(
            db=db,
            gateway=Gateway([{"paging": {"total": 1}, "messages": [raw]}]),
            seller_id="123",
            targets=["400"],
            start=START,
            end=END,
        )
    stored = db["messages"].documents["m1"]
    assert stored["order_id"] == "501"
    assert stored["read_at"] == datetime(2026, 6, 5, 10, tzinfo=UTC)
    assert stored["text"] == "changed"


@pytest.mark.asyncio
async def test_api_operations_do_not_unlock_real_retiros_reader() -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.read_models import (
        FULL_WITHDRAWALS_READ_MODEL,
        FormulaReadModelRepository,
    )

    db = FakeDb()
    await collect_full_operations(
        db=db,
        gateway=Gateway(
            [
                {
                    "paging": {"scroll": None},
                    "results": [
                        {
                            "id": 1,
                            "seller_id": 123,
                            "inventory_id": "INV1",
                            "type": "WITHDRAWAL_DELIVERY",
                            "date_created": "2026-06-04T10:00:00Z",
                            "detail": {"not_available_quantity": -3},
                        }
                    ],
                }
            ]
        ),
        seller_id="123",
        start=START,
        end=END,
    )
    repository = FormulaReadModelRepository(db=db)
    with pytest.raises(FormulaDataUnavailableError):
        await repository.require_read_model_reconciled_range(
            seller_id="123",
            read_model=FULL_WITHDRAWALS_READ_MODEL,
            date_from=START,
            date_to=END,
            formula="ZELERDATA_RETIROS",
        )


@pytest.mark.asyncio
async def test_growing_pack_inventory_cannot_shift_frozen_page_cursor() -> None:
    db = FakeDb()
    gateway = Gateway(
        [
            {"paging": {"total": 1}, "messages": [message("m2")]},
            {"paging": {"total": 1}, "messages": [message("m3")]},
        ]
    )
    first = await collect_pack_messages(
        db=db, gateway=gateway, seller_id="123", targets=["402", "403"], start=START, end=END
    )
    second = await collect_pack_messages(
        db=db,
        gateway=gateway,
        seller_id="123",
        targets=["401", "402", "403"],
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
    )
    assert "/packs/403/" in gateway.paths[1]
    assert second["coverage_complete"]
    assert second["checkpoint"]["target_ids"] == ["402", "403"]


@pytest.mark.asyncio
async def test_full_search_is_bounded_to_documented_withdrawal_types() -> None:
    from zeler_sheets.onboarding_sources import WITHDRAWAL_TYPES

    gateway = Gateway([{"paging": {"scroll": None}, "results": []}] * len(WITHDRAWAL_TYPES))
    result = await collect_full_operations(
        db=FakeDb(),
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        max_requests=len(WITHDRAWAL_TYPES),
    )
    assert result["discovery_complete"]
    assert {parse_qs(urlsplit(path).query)["type"][0] for path in gateway.paths} == WITHDRAWAL_TYPES
