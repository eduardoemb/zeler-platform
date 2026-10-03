from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from test_event_persistence import FakeCollection, FakeCursor, FakeDb

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
    db = owned_full_db()

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
        db=owned_full_db(), gateway=Gateway([error]), seller_id="123", start=START, end=END
    )
    assert result["blocked_reason"] == "access_denied"
    assert not result["discovery_complete"]
    assert "private secret" not in str(result)


@pytest.mark.asyncio
async def test_full_429_preserves_inventory_type_scroll_and_physical_budget() -> None:
    db = owned_full_db(second=True)
    request = httpx.Request("GET", "https://example.test/")
    error = httpx.HTTPStatusError(
        "private", request=request, response=httpx.Response(429, request=request)
    )
    raw = {
        "id": 1,
        "seller_id": 123,
        "inventory_id": "INV1",
        "type": "WITHDRAWAL_RESERVATION",
        "date_created": "2026-06-04T10:00:00Z",
    }
    gateway = Gateway(
        [
            {"paging": {"scroll": "resume"}, "results": [raw]},
            error,
            {"paging": {"scroll": None}, "results": []},
        ]
    )
    first = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        max_requests=5,
        now=START,
    )
    assert first["requests"] == len(gateway.paths) == 2
    assert len(gateway.pages) == 1  # No retry within this turn.
    assert first["persisted"] == 1 and first["blocked_reason"] == "source_retry_required"
    assert not first["discovery_complete"] and not first["coverage_complete"]
    checkpoint = first["checkpoint"]
    assert checkpoint["inventory_index"] == 0 and checkpoint["type_index"] == 0
    assert checkpoint["scroll"] == "resume"
    assert checkpoint["inventory_targets"][0]["inventory_id"] == "INV1"
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=checkpoint,
        max_requests=1,
        now=START,
    )
    assert second["requests"] == 1 and len(gateway.paths) == 3
    assert parse_qs(urlsplit(gateway.paths[2]).query) == parse_qs(urlsplit(gateway.paths[1]).query)
    assert second["persisted"] == 1 and second["checkpoint"]["type_index"] == 1
    assert second["checkpoint"]["inventory_index"] == 0
    assert not second["coverage_complete"]


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
    db = owned_full_db()
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
    db = owned_full_db()
    legacy = {
        "_id": "123:ret:detail:inventory",
        "seller_id": "123",
        "source": "legacy_history_import",
    }
    db["sheets_full_withdrawals"].documents[legacy["_id"]] = dict(legacy)
    result = await collect_full_operations(
        db=db,
        gateway=Gateway([{"paging": {"scroll": None}, "results": []}] * 5),
        seller_id="123",
        start=START,
        end=END,
        max_requests=5,
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

    db = owned_full_db()
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
        db=owned_full_db(),
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        max_requests=len(WITHDRAWAL_TYPES),
    )
    assert result["discovery_complete"]
    assert {parse_qs(urlsplit(path).query)["type"][0] for path in gateway.paths} == WITHDRAWAL_TYPES


class FullInventoryCollection(FakeCollection):
    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        del projection
        return super().find(filter_spec)


def owned_full_db(*, second: bool = False) -> FakeDb:
    db = FakeDb()
    db.collections["items"] = FullInventoryCollection()
    db["items"].documents = {
        "MLM1": {
            "_id": "MLM1",
            "seller_id": "123",
            "inventory_id": "INV1",
            "shipping": {"logistic_type": "fulfillment"},
            "variations": [{"id": 1, "inventory_id": "INV1"}],
        },
        **(
            {
                "MLM2": {
                    "_id": "MLM2",
                    "seller_id": 123,
                    "shipping": {"logistic_type": "fulfillment"},
                    "variations": [{"id": 2, "inventory_id": "INV2"}],
                }
            }
            if second
            else {}
        ),
    }
    return db


@pytest.mark.asyncio
async def test_full_requests_require_owned_inventory_and_resume_both_inventories() -> None:
    db = owned_full_db(second=True)
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}] * 10)
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, max_requests=3
    )
    assert first["requests"] == 3
    assert all(parse_qs(urlsplit(p).query).get("inventory_id") == ["INV1"] for p in gateway.paths)
    assert first["checkpoint"]["inventory_targets"] == [
        {"item_id": "MLM1", "inventory_id": "INV1"},
        {"item_id": "MLM2", "inventory_id": "INV2"},
    ]
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
        max_requests=7,
    )
    assert second["requests"] == 7
    assert second["discovery_complete"]
    assert not second["coverage_complete"]
    assert [parse_qs(urlsplit(p).query)["inventory_id"][0] for p in gateway.paths] == [
        "INV1"
    ] * 5 + ["INV2"] * 5
    assert second["checkpoint"]["start"] == START.isoformat()
    assert second["checkpoint"]["end"] == END.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["empty", "foreign", "not_full", "no_identity"])
async def test_full_without_owned_inventory_never_calls_unfiltered_provider(case: str) -> None:
    db = owned_full_db()
    if case == "empty":
        db["items"].documents.clear()
    elif case == "foreign":
        db["items"].documents["MLM1"]["seller_id"] = "999"
    elif case == "not_full":
        db["items"].documents["MLM1"]["shipping"]["logistic_type"] = "cross_docking"
    else:
        db["items"].documents["MLM1"].pop("inventory_id")
        db["items"].documents["MLM1"]["variations"] = []
    gateway = Gateway([])
    result = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END
    )
    assert gateway.paths == []
    assert result["requests"] == 0
    assert result["blocked_reason"] == "full_inventory_unavailable"
    assert not result["coverage_complete"]
    assert not db["sheets_full_operations"].documents


@pytest.mark.asyncio
async def test_full_inventory_selection_pages_and_deduplicates_across_local_pages() -> None:
    db = owned_full_db()
    template = db["items"].documents.pop("MLM1")
    for index in range(1, 34):
        identity = f"MLM{index:03}"
        db["items"].documents[identity] = {**template, "_id": identity}
    db["items"].documents["MLM033"]["variations"] = [
        {"inventory_id": "INV1"},
        {"inventory_id": "INV2"},
    ]
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}] * 10)
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, max_requests=5
    )
    assert not first["discovery_complete"]
    assert first["checkpoint"]["inventory_item_after"] == "MLM032"
    assert first["checkpoint"]["inventory_seen"] == ["INV1"]
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
        max_requests=5,
    )
    assert second["discovery_complete"]
    assert second["checkpoint"]["inventory_seen"] == ["INV1", "INV2"]
    assert [parse_qs(urlsplit(p).query)["inventory_id"][0] for p in gateway.paths] == [
        "INV1"
    ] * 5 + ["INV2"] * 5


@pytest.mark.asyncio
async def test_full_zero_request_page_preserves_cursor_without_claiming_acquisition_complete() -> (
    None
):
    db = owned_full_db()
    template = db["items"].documents.pop("MLM1")
    for index in range(1, 34):
        identity = f"MLM{index:03}"
        db["items"].documents[identity] = {
            **template,
            "_id": identity,
            "inventory_id": None,
            "variations": [],
        }
    db["items"].documents["MLM033"]["inventory_id"] = "INV2"
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}])
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END
    )
    assert first["requests"] == 0
    assert not first["discovery_complete"] and first["blocked_reason"] is None
    assert first["checkpoint"]["inventory_item_after"] == "MLM032"
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
    )
    assert second["requests"] == 1
    assert parse_qs(urlsplit(gateway.paths[0]).query)["inventory_id"] == ["INV2"]
    assert not second["coverage_complete"]


@pytest.mark.asyncio
async def test_full_legacy_unfiltered_scroll_is_discarded_without_resetting_range_or_facts() -> (
    None
):
    db = owned_full_db()
    old = {
        "seller_id": "123",
        "source": "full_operations",
        "start": START.isoformat(),
        "end": END.isoformat(),
        "type_index": 3,
        "scroll": "old-unfiltered",
        "scroll_observed_at": START.isoformat(),
        "persisted": 7,
        "discovery_complete": True,
    }
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}])
    result = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=old,
        now=START,
    )
    params = parse_qs(urlsplit(gateway.paths[0]).query)
    assert params["inventory_id"] == ["INV1"]
    assert params["type"] == ["WITHDRAWAL_RESERVATION"] and "scroll" not in params
    assert result["persisted"] == 7
    assert result["checkpoint"]["start"] == old["start"]
    assert result["checkpoint"]["end"] == old["end"]
    assert not result["discovery_complete"]


@pytest.mark.asyncio
async def test_full_inventory_ownership_and_response_are_checked_on_resume() -> None:
    db = owned_full_db(second=True)
    raw = {
        "id": 1,
        "seller_id": 123,
        "inventory_id": "NOT_REQUESTED",
        "type": "WITHDRAWAL_RESERVATION",
        "date_created": "2026-06-04T10:00:00Z",
    }
    gateway = Gateway(
        [
            {"paging": {"scroll": "same"}, "results": [raw]},
            {"paging": {"scroll": None}, "results": []},
        ]
    )
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END
    )
    assert first["issue_count"] == 1 and first["persisted"] == 0
    db["items"].documents["MLM1"]["seller_id"] = "999"
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
    )
    params = parse_qs(urlsplit(gateway.paths[1]).query)
    assert params["inventory_id"] == ["INV2"] and "scroll" not in params
    assert second["requests"] == 1 and second["issue_count"] == 2
    assert not db["sheets_full_operations"].documents


@pytest.mark.asyncio
async def test_full_completed_inventory_checkpoint_is_idempotent() -> None:
    db = owned_full_db()
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}] * 5)
    first = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, max_requests=5
    )
    second = await collect_full_operations(
        db=db,
        gateway=gateway,
        seller_id="123",
        start=START,
        end=END,
        checkpoint=first["checkpoint"],
        max_requests=5,
    )
    assert second["requests"] == 0 and len(gateway.paths) == 5
    assert second["discovery_complete"]
    assert second["blocked_reason"] == "full_withdrawal_contract_incompatible"
    assert not second["coverage_complete"]


@pytest.mark.asyncio
async def test_full_inventory_selection_bound_is_explicit_not_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_sheets.onboarding_sources as sources

    monkeypatch.setattr(sources, "_MAX_FULL_INVENTORIES", 2)
    db = owned_full_db()
    db["items"].documents["MLM1"]["variations"] = [
        {"inventory_id": "INV2"},
        {"inventory_id": "INV3"},
    ]
    gateway = Gateway([{"paging": {"scroll": None}, "results": []}] * 10)
    result = await collect_full_operations(
        db=db, gateway=gateway, seller_id="123", start=START, end=END, max_requests=10
    )
    assert result["checkpoint"]["inventory_seen"] == ["INV1", "INV2"]
    assert result["pending"] == [{"code": "inventory_selection_limit", "id": None}]
    assert result["issue_count"] == 1 and not result["coverage_complete"]
    assert len(gateway.paths) == 10
