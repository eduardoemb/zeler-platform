from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from bson.decimal128 import Decimal128

from zeler_sheets.historical_meli_backfill import (
    build_arg_parser,
    parse_inclusive_date_range,
    run_historical_meli_backfill,
    sanitize_historical_meli_summary,
    validate_cli_safety,
)


class FakeReplaceResult:
    def __init__(
        self, *, matched_count: int = 1, modified_count: int = 1, upserted_id: str | None = None
    ) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._documents[:length]

    def __aiter__(self) -> FakeCursor:
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._documents):
            raise StopAsyncIteration
        document = self._documents[self._index]
        self._index += 1
        return dict(document)


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        for document_id, document in self.documents.items():
            if _matches_filter(document, filter_spec):
                self.documents[document_id] = dict(replacement)
                return FakeReplaceResult()
        if upsert:
            document_id = str(replacement["_id"])
            self.documents[document_id] = dict(replacement)
            return FakeReplaceResult(matched_count=0, modified_count=0, upserted_id=document_id)
        return FakeReplaceResult(matched_count=0, modified_count=0)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        for document in self.documents.values():
            if _matches_filter(document, filter_spec):
                for path, value in update.get("$set", {}).items():
                    _set_path(document, path, value)
                for path in update.get("$unset", {}):
                    _unset_path(document, path)
                return FakeReplaceResult()
        if upsert and "$setOnInsert" in update:
            document = dict(update["$setOnInsert"])
            document_id = str(document["_id"])
            self.documents[document_id] = document
            return FakeReplaceResult(matched_count=0, modified_count=0, upserted_id=document_id)
        return FakeReplaceResult(matched_count=0, modified_count=0)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents.values():
            if _matches_filter(document, filter_spec):
                return dict(document)
        return None

    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        del projection
        documents = [
            document
            for document in self.documents.values()
            if _matches_filter(document, filter_spec)
        ]
        return FakeCursor(documents)


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches_filter(document, option) for option in expected):
                return False
            continue
        actual = _nested_value(document, key)
        if isinstance(expected, dict) and "$exists" in expected:
            if (actual is not None) != expected["$exists"]:
                return False
            continue
        if isinstance(expected, dict) and "$ne" in expected:
            if actual == expected["$ne"]:
                return False
            continue
        if isinstance(expected, dict) and "$lte" in expected:
            if actual is None or actual > expected["$lte"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _nested_value(document: dict[str, Any], dotted_path: str) -> Any:
    value: Any = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set_path(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target.get(part), dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value


def _unset_path(document: dict[str, Any], dotted_path: str) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or not isinstance(target.get(part), dict):
            return
        target = target[part]
    if isinstance(target, dict):
        target.pop(parts[-1], None)


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeGateway:
    def __init__(
        self,
        *,
        return_item_detail: bool = True,
        unauthorized_shipment: bool = False,
        shipment_costs_payload: Any | None = None,
        claim_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.return_item_detail = return_item_detail
        self.unauthorized_shipment = unauthorized_shipment
        self.shipment_costs_payload = shipment_costs_payload or _shipment_costs_payload()
        self.claim_payloads = claim_payloads

    async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
        self.calls.append((seller_id, path))
        if path.startswith("/orders/search?"):
            return {"results": [{"id": 2001}], "paging": {"total": 1, "limit": 50, "offset": 0}}
        if path.startswith("/questions/search?"):
            return {
                "questions": [{"id": "Q1"}, {"id": "Q2"}, {"id": "Q3"}],
                "paging": {"total": 3, "limit": 50, "offset": 0},
            }
        if path == "/questions/Q1":
            return _question_detail("Q1", status="ANSWERED", answer_text="Yes")
        if path == "/questions/Q2":
            return _question_detail("Q2", status="UNANSWERED")
        if path == "/questions/Q3":
            return _question_detail(
                "Q3", status="UNANSWERED", date_created="2026-05-02T10:00:00+00:00"
            )
        if path == "/items?ids=MLA1" and self.return_item_detail:
            return [{"code": 200, "body": _item_detail()}]
        if path == "/items?ids=MLA1":
            return [{"code": 404, "body": {"message": "not found"}}]
        if path == "/products/CAT-MLA1":
            return _catalog_product_detail()
        if path == "/items/MLA1/price_to_win?version=v2":
            return _price_to_win_detail()
        if path == "/shipments/3001" and self.unauthorized_shipment:
            return {
                "status": 403,
                "message": "cannot access SENTINEL BUYER NAME, SENTINEL STREET 123",
            }
        if path == "/shipments/3001":
            return _shipment_detail()
        if path == "/shipments/3001/costs":
            return self.shipment_costs_payload
        if path == "/post-purchase/v1/claims/search?order_id=2001":
            return {
                "data": self.claim_payloads
                if self.claim_payloads is not None
                else [
                    {
                        "id": "CLAIM-1",
                        "order_id": "2001",
                        "item_id": "MLA1",
                        "status": "closed",
                        "stage": "claim",
                        "type": "returns",
                        "date_created": "2026-05-01T12:00:00+00:00",
                        "returned_quantity": 1,
                    },
                    {
                        "id": "CLAIM-OUT-OF-RANGE",
                        "order_id": "2001",
                        "status": "closed",
                        "stage": "claim",
                        "type": "returns",
                        "date_created": "2026-05-02T12:00:00+00:00",
                        "returned_quantity": 1,
                    },
                ]
            }
        raise AssertionError(f"Unexpected gateway path: {path}")


class FakeOrderDetailGateway:
    def __init__(
        self,
        *,
        order_status: str = "paid",
        order_items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.order_status = order_status
        self.order_items = order_items

    async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
        self.calls.append((seller_id, path))
        if path == "/orders/2001":
            return _order_detail(status=self.order_status, order_items=self.order_items)
        if path == "/questions/Q1":
            return _question_detail("Q1", status="ANSWERED", answer_text="Yes")
        if path == "/questions/Q2":
            return _question_detail("Q2", status="UNANSWERED")
        if path == "/questions/Q3":
            return _question_detail(
                "Q3", status="UNANSWERED", date_created="2026-05-02T10:00:00+00:00"
            )
        raise AssertionError(f"Unexpected order detail gateway path: {path}")


class FakeCatalogGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
        self.calls.append((seller_id, path))
        if path == "/products/CAT-MLA1":
            return _catalog_product_detail()
        if path == "/items/MLA1/price_to_win?version=v2":
            return _price_to_win_detail()
        raise AssertionError(f"Unexpected catalog gateway path: {path}")


def test_parse_inclusive_date_range_uses_exclusive_next_day() -> None:
    parsed = parse_inclusive_date_range("2026-05-01", "2026-05-01")

    assert parsed.date_from == "2026-05-01"
    assert parsed.date_to == "2026-05-01"
    assert parsed.start == datetime(2026, 5, 1, tzinfo=UTC)
    assert parsed.end_exclusive == datetime(2026, 5, 2, tzinfo=UTC)


def test_parse_inclusive_date_range_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="date-to must be on or after date-from"):
        parse_inclusive_date_range("2026-05-02", "2026-05-01")


def test_cli_defaults_to_bootstrap_search_module_and_sheets_order_detail_module() -> None:
    args = build_arg_parser().parse_args(
        ["--seller-id", "82453304", "--date-from", "2026-05-01", "--date-to", "2026-05-01"]
    )

    assert args.module_id == "bootstrap"
    assert args.order_detail_module_id == "sheets"
    assert args.dry_run is True
    validate_cli_safety(args)


def test_cli_write_requires_approved_runtime_confirmation() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-05-01",
            "--date-to",
            "2026-05-01",
            "--write",
        ]
    )

    with pytest.raises(SystemExit, match="--confirm-approved-runtime is required with --write"):
        validate_cli_safety(args)

    confirmed_args = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-05-01",
            "--date-to",
            "2026-05-01",
            "--write",
            "--confirm-approved-runtime",
        ]
    )

    validate_cli_safety(confirmed_args)


def test_cli_buyer_address_pii_mode_requires_approved_bounded_runtime() -> None:
    parser = build_arg_parser()
    missing_confirmation = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-05-01",
            "--date-to",
            "2026-05-01",
            "--include-buyer-address-pii",
            "--max-orders",
            "1",
        ]
    )

    with pytest.raises(
        SystemExit, match="--confirm-approved-runtime is required with --include-buyer-address-pii"
    ):
        validate_cli_safety(missing_confirmation)

    unbounded = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-05-01",
            "--date-to",
            "2026-05-01",
            "--include-buyer-address-pii",
            "--confirm-approved-runtime",
        ]
    )

    with pytest.raises(
        SystemExit, match="--max-orders is required with --include-buyer-address-pii"
    ):
        validate_cli_safety(unbounded)

    bounded = parser.parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-05-01",
            "--date-to",
            "2026-05-01",
            "--include-buyer-address-pii",
            "--confirm-approved-runtime",
            "--max-orders",
            "1",
        ]
    )

    validate_cli_safety(bounded)


@pytest.mark.asyncio
async def test_runner_write_requires_approved_runtime() -> None:
    with pytest.raises(ValueError, match="approved_runtime is required"):
        await run_historical_meli_backfill(
            db=FakeDb(),
            gateway=FakeGateway(),
            order_detail_gateway=FakeOrderDetailGateway(),
            seller_id="82453304",
            date_from="2026-05-01",
            date_to="2026-05-01",
            dry_run=False,
            max_orders=1,
        )


@pytest.mark.asyncio
async def test_runner_buyer_address_pii_mode_requires_approved_bounded_runtime() -> None:
    with pytest.raises(ValueError, match="approved_runtime is required for buyer/address PII mode"):
        await run_historical_meli_backfill(
            db=FakeDb(),
            gateway=FakeGateway(),
            order_detail_gateway=FakeOrderDetailGateway(),
            seller_id="82453304",
            date_from="2026-05-01",
            date_to="2026-05-01",
            dry_run=True,
            include_buyer_address_pii=True,
            max_orders=1,
        )

    with pytest.raises(ValueError, match="max_orders is required for buyer/address PII mode"):
        await run_historical_meli_backfill(
            db=FakeDb(),
            gateway=FakeGateway(),
            order_detail_gateway=FakeOrderDetailGateway(),
            seller_id="82453304",
            date_from="2026-05-01",
            date_to="2026-05-01",
            dry_run=True,
            approved_runtime=True,
            include_buyer_address_pii=True,
        )


@pytest.mark.asyncio
async def test_historical_backfill_dry_run_does_not_write() -> None:
    db = FakeDb()
    gateway = FakeGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=1,
    )

    assert summary.dry_run is True
    assert summary.orders_found == 1
    assert summary.planned_orders == 1
    assert summary.planned_items == 1
    assert summary.planned_shipments == 1
    assert summary.written_orders == 0
    assert summary.written_items == 0
    assert summary.written_shipments == 0
    assert all(not collection.replace_calls for collection in db.collections.values())


@pytest.mark.asyncio
async def test_buyer_address_pii_dry_run_reports_only_sanitized_aggregate_counts() -> None:
    db = FakeDb()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=FakeGateway(),
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        approved_runtime=True,
        include_buyer_address_pii=True,
        max_orders=1,
    )

    output = summary.as_dict()
    output_json = json.dumps(output, sort_keys=True)
    assert output["buyer_address_pii_mode"] is True
    assert output["output_mode"] == "sanitized_aggregate"
    assert output["address_matched"] == 1
    assert output["address_populated"] == 1
    assert output["address_missing"] == 0
    assert output["address_unauthorized"] == 0
    assert output["redacted_errors"] == 0
    assert "order_ids" not in output
    assert "shipment_ids" not in output
    assert "item_ids" not in output
    assert "missing_item_detail_ids" not in output
    assert "2001" not in output_json
    assert "3001" not in output_json
    assert "SENTINEL BUYER NAME" not in output_json
    assert "SENTINEL STREET" not in output_json
    assert all(not collection.replace_calls for collection in db.collections.values())


@pytest.mark.asyncio
async def test_historical_backfill_operator_summary_is_sanitized_without_pii_mode() -> None:
    summary = await run_historical_meli_backfill(
        db=FakeDb(),
        gateway=FakeGateway(),
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=1,
    )

    output = summary.as_dict()
    output_json = json.dumps(output, sort_keys=True)

    assert output["output_mode"] == "sanitized_aggregate"
    assert output["orders_found"] == 1
    assert output["shipments_fetched"] == 1
    assert "seller_id" not in output
    assert "order_ids" not in output
    assert "shipment_ids" not in output
    assert "item_ids" not in output
    assert "missing_item_detail_ids" not in output
    for forbidden in (
        "82453304",
        "2001",
        "3001",
        "MLA1",
        "SENTINEL BUYER NAME",
        "SENTINEL STREET",
        "raw_payload",
        "access_token",
        "MONGO_URI",
    ):
        assert forbidden not in output_json


def test_sanitize_historical_meli_summary_converts_unsafe_payloads_to_counts() -> None:
    raw_summary = {
        "seller_id": "82453304",
        "order_ids": ["2001", "2002"],
        "item_ids": ["MLA1"],
        "shipment_ids": ["3001"],
        "missing_item_detail_ids": [],
        "orders_found": 2,
        "buyer": {"name": "SENTINEL BUYER NAME"},
        "receiver_address": {"street_name": "SENTINEL STREET"},
        "raw_payload": {"id": "2001", "payload": "SENTINEL PAYLOAD"},
        "env": {"MONGO_URI": "SENTINEL_DB_URI_VALUE"},
        "access_token": "SENTINEL_ACCESS_TOKEN_VALUE",
        "client_secret": "SENTINEL_CLIENT_SECRET_VALUE",
    }

    sanitized = sanitize_historical_meli_summary(raw_summary)
    sanitized_json = json.dumps(sanitized, sort_keys=True)

    assert sanitized["order_count"] == 2
    assert sanitized["item_count"] == 1
    assert sanitized["shipment_count"] == 1
    assert sanitized["missing_item_detail_count"] == 0
    assert sanitized["orders_found"] == 2
    for forbidden in (
        "seller_id",
        "order_ids",
        "item_ids",
        "shipment_ids",
        "missing_item_detail_ids",
        "82453304",
        "2001",
        "2002",
        "3001",
        "MLA1",
        "SENTINEL BUYER NAME",
        "SENTINEL STREET",
        "SENTINEL PAYLOAD",
        "SENTINEL_DB_URI_VALUE",
        "SENTINEL_ACCESS_TOKEN_VALUE",
        "SENTINEL_CLIENT_SECRET_VALUE",
    ):
        assert forbidden not in sanitized_json


@pytest.mark.asyncio
async def test_buyer_address_pii_summary_counts_unauthorized_without_leaking_payload() -> None:
    summary = await run_historical_meli_backfill(
        db=FakeDb(),
        gateway=FakeGateway(unauthorized_shipment=True),
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        approved_runtime=True,
        include_buyer_address_pii=True,
        max_orders=1,
    )

    output_json = json.dumps(summary.as_dict(), sort_keys=True)
    assert summary.address_matched == 1
    assert summary.address_populated == 0
    assert summary.address_unauthorized == 1
    assert summary.redacted_errors == 0
    assert "SENTINEL BUYER NAME" not in output_json
    assert "SENTINEL STREET" not in output_json


@pytest.mark.asyncio
async def test_historical_backfill_fetches_order_details_through_separate_gateway() -> None:
    db = FakeDb()
    gateway = FakeGateway()
    order_detail_gateway = FakeOrderDetailGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=1,
    )

    assert summary.orders_fetched == 1
    assert order_detail_gateway.calls == [("82453304", "/orders/2001")]
    main_paths = [path for _, path in gateway.calls]
    assert any(path.startswith("/orders/search?") for path in main_paths)
    assert "/orders/2001" not in main_paths
    assert "/items?ids=MLA1" in main_paths
    assert "/shipments/3001" in main_paths


@pytest.mark.asyncio
async def test_historical_backfill_fetches_question_details_through_detail_gateway() -> None:
    db = FakeDb()
    gateway = FakeGateway()
    detail_gateway = FakeOrderDetailGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=1,
        include_questions=True,
    )

    assert summary.questions_found == 2
    assert (
        "82453304",
        "/questions/search?api_version=4&seller_id=82453304&offset=0&limit=50",
    ) in gateway.calls
    assert ("82453304", "/questions/Q1") in detail_gateway.calls
    assert ("82453304", "/questions/Q2") in detail_gateway.calls
    assert ("82453304", "/questions/Q3") in detail_gateway.calls
    primary_paths = [path for _, path in gateway.calls]
    assert "/questions/Q1" not in primary_paths
    assert "/questions/Q2" not in primary_paths
    assert "/questions/Q3" not in primary_paths


@pytest.mark.asyncio
async def test_historical_backfill_write_persists_canonical_docs_and_read_models() -> None:
    db = FakeDb()
    gateway = FakeGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_questions=True,
    )

    assert summary.as_dict()["status"] == "write_complete"
    assert summary.order_ids == ["2001"]
    assert summary.item_ids == ["MLA1"]
    assert summary.shipment_ids == ["3001"]
    assert summary.written_orders == 1
    assert summary.written_items == 1
    assert summary.written_shipments == 1

    search_path = gateway.calls[0][1]
    assert search_path.startswith("/orders/search?")
    assert "seller=82453304" in search_path
    assert "order.date_created.from=2026-05-01T00%3A00%3A00Z" in search_path
    assert "order.date_created.to=2026-05-01T23%3A59%3A59.999Z" in search_path

    order = db["orders"].documents["2001"]
    assert order["seller_id"] == "82453304"
    assert order["shipment_id"] == "3001"
    assert order["items"] == [
        {"item_id": "MLA1", "seller_sku": "sku-1", "qty": 2, "unit_price": Decimal128("149.95")}
    ]

    item = db["items"].documents["MLA1"]
    assert item["seller_id"] == "82453304"
    assert item["price"] == Decimal128("149.99")

    shipment = db["shipments"].documents["3001"]
    assert shipment["seller_id"] == "82453304"
    assert shipment["order_id"] == "2001"
    assert "receiver_address" not in shipment

    assert db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:item"]["item_id"] == "MLA1"
    formula_row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert formula_row["current"]["title"] == "Premium widget"
    assert formula_row["current"]["inventory_id"] == "INV-ITEM-1"


@pytest.mark.asyncio
async def test_historical_backfill_reconciles_question_details_for_formula_readiness() -> None:
    db = FakeDb()
    gateway = FakeGateway()
    detail_gateway = FakeOrderDetailGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_questions=True,
    )

    assert summary.questions_found == 2
    assert summary.questions_fetched == 2
    assert summary.planned_questions == 2
    assert summary.written_questions == 2
    assert summary.question_ids == ["Q1", "Q2"]
    assert db["questions"].documents["Q1"]["answer"]["text"] == "Yes"
    assert db["questions"].documents["Q1"]["answer"]["date_created"] == datetime(
        2026, 5, 1, 10, 5, tzinfo=UTC
    )
    assert (
        "82453304",
        "/questions/search?api_version=4&seller_id=82453304&offset=0&limit=50",
    ) in gateway.calls
    assert ("82453304", "/questions/Q1") in detail_gateway.calls
    assert ("82453304", "/questions/Q3") in detail_gateway.calls
    assert "/questions/Q1" not in [path for _, path in gateway.calls]
    assert "/questions/Q3" not in [path for _, path in gateway.calls]
    assert "Q3" not in db["questions"].documents


@pytest.mark.asyncio
async def test_historical_backfill_reconciles_claims_bounded_by_order_scope() -> None:
    db = FakeDb()
    gateway = FakeGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_claims=True,
    )

    assert summary.claims_found == 1
    assert summary.claims_fetched == 1
    assert summary.planned_claims == 1
    assert summary.written_claims == 1
    assert summary.claim_ids == ["CLAIM-1"]
    assert db["claims"].documents["CLAIM-1"] == {
        "_id": "CLAIM-1",
        "seller_id": "82453304",
        "order_id": "2001",
        "item_id": "MLA1",
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        "returned_quantity": 1,
        "schema_version": 1,
    }
    assert (
        "82453304",
        "/post-purchase/v1/claims/search?order_id=2001",
    ) in gateway.calls
    assert "CLAIM-OUT-OF-RANGE" not in db["claims"].documents


@pytest.mark.asyncio
async def test_historical_backfill_derives_claim_returned_quantity_from_scoped_order_line() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        claim_payloads=[
            {
                "id": "CLAIM-1",
                "order_id": "2001",
                "item_id": "MLA1",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "date_created": "2026-05-01T12:00:00+00:00",
            }
        ]
    )

    await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_claims=True,
    )

    assert db["claims"].documents["CLAIM-1"]["returned_quantity"] == 2


@pytest.mark.asyncio
async def test_historical_backfill_skips_explicit_returned_quantity_without_scope() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        claim_payloads=[
            {
                "id": "CLAIM-1",
                "order_id": "2001",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "date_created": "2026-05-01T12:00:00+00:00",
                "returned_quantity": 7,
            }
        ]
    )
    order_detail_gateway = FakeOrderDetailGateway(
        order_items=[
            {
                "item": {"id": "MLA1", "seller_sku": "sku-1"},
                "quantity": 2,
                "unit_price": "149.95",
            },
            {
                "item": {"id": "MLA2", "seller_sku": "sku-2"},
                "quantity": 3,
                "unit_price": "99.95",
            },
        ]
    )

    await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        max_items=1,
        include_claims=True,
    )

    claim = db["claims"].documents["CLAIM-1"]
    assert "returned_quantity" not in claim
    assert "item_id" not in claim


@pytest.mark.asyncio
async def test_historical_backfill_drops_claim_scope_fields_when_item_mismatches_order() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        claim_payloads=[
            {
                "id": "CLAIM-1",
                "order_id": "2001",
                "item_id": "MLA-NOT-IN-ORDER",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "date_created": "2026-05-01T12:00:00+00:00",
                "returned_quantity": 7,
            }
        ]
    )
    order_detail_gateway = FakeOrderDetailGateway(
        order_items=[
            {
                "item": {"id": "MLA1", "seller_sku": "sku-1"},
                "quantity": 2,
                "unit_price": "149.95",
            },
            {
                "item": {"id": "MLA2", "seller_sku": "sku-2"},
                "quantity": 3,
                "unit_price": "99.95",
            },
        ]
    )

    await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        max_items=1,
        include_claims=True,
    )

    claim = db["claims"].documents["CLAIM-1"]
    assert "item_id" not in claim
    assert "returned_quantity" not in claim


@pytest.mark.asyncio
async def test_historical_backfill_keeps_explicit_quantity_after_scope_resolution() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        claim_payloads=[
            {
                "id": "CLAIM-1",
                "order_id": "2001",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "date_created": "2026-05-01T12:00:00+00:00",
                "returned_quantity": 7,
            }
        ]
    )

    await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_claims=True,
    )

    claim = db["claims"].documents["CLAIM-1"]
    assert claim["returned_quantity"] == 7
    assert claim["item_id"] == "MLA1"


@pytest.mark.asyncio
async def test_historical_backfill_filters_non_return_claim_types() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        claim_payloads=[
            {
                "id": "CLAIM-RETURN",
                "order_id": "2001",
                "item_id": "MLA1",
                "status": "closed",
                "stage": "claim",
                "type": "returns",
                "date_created": "2026-05-01T12:00:00+00:00",
            },
            {
                "id": "CLAIM-MEDIATION",
                "order_id": "2001",
                "item_id": "MLA1",
                "status": "closed",
                "stage": "claim",
                "type": "mediations",
                "date_created": "2026-05-01T12:00:00+00:00",
                "returned_quantity": 1,
            },
        ]
    )

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_claims=True,
    )

    assert summary.claims_found == 1
    assert summary.planned_claims == 1
    assert summary.written_claims == 1
    assert summary.claim_ids == ["CLAIM-RETURN"]
    assert set(db["claims"].documents) == {"CLAIM-RETURN"}
    assert db["claims"].documents["CLAIM-RETURN"]["returned_quantity"] == 2


@pytest.mark.asyncio
async def test_historical_backfill_reconciles_catalog_product_and_buybox_snapshots() -> None:
    db = FakeDb()
    gateway = FakeGateway()
    catalog_gateway = FakeCatalogGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        catalog_gateway=catalog_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
        include_catalog_snapshots=True,
    )

    assert summary.catalog_product_snapshots_found == 1
    assert summary.catalog_product_snapshots_fetched == 1
    assert summary.catalog_buybox_snapshots_found == 1
    assert summary.catalog_buybox_snapshots_fetched == 1
    assert summary.written_catalog_product_snapshots == 1
    assert summary.written_catalog_buybox_snapshots == 1
    primary_paths = [path for _, path in gateway.calls]
    catalog_paths = [path for _, path in catalog_gateway.calls]
    assert (
        "82453304",
        "/products/CAT-MLA1",
    ) in catalog_gateway.calls
    assert (
        "82453304",
        "/items/MLA1/price_to_win?version=v2",
    ) in catalog_gateway.calls
    assert catalog_paths == [
        "/products/CAT-MLA1",
        "/items/MLA1/price_to_win?version=v2",
    ]
    assert "/products/CAT-MLA1" not in primary_paths
    assert "/items/MLA1/price_to_win?version=v2" not in primary_paths
    product = db["sheets_catalog_product_snapshots"].documents["82453304:CAT-MLA1"]
    assert product["source"] == "historical_meli_backfill"
    assert product["catalog_product_id"] == "CAT-MLA1"
    assert product["title"] == "Catalog product"
    assert product["description"] == "Complete catalog description"
    assert product["image_url"] == "https://img.example/catalog-product.jpg"
    assert product["attributes"] == [{"id": "BRAND", "value_name": "Acme"}]
    buybox = db["sheets_catalog_buybox_snapshots"].documents["82453304:MLA1"]
    assert buybox["source"] == "historical_meli_backfill"
    assert buybox["item_id"] == "MLA1"
    assert buybox["catalog_product_id"] == "CAT-MLA1"
    assert buybox["title"] == "Catalog buybox item"
    assert buybox["available_quantity"] == 7
    assert buybox["buybox_status"] == "winning"
    assert buybox["price"] == 120
    assert buybox["winning_price"] == 118
    assert buybox["competitor_count"] == 2
    assert buybox["only_competitor"] == "No"


@pytest.mark.asyncio
async def test_historical_backfill_dedupes_shipment_cost_fetches_and_persists_projection() -> None:
    class SharedShipmentGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            self.calls.append((seller_id, path))
            if path.startswith("/orders/search?"):
                return {
                    "results": [{"id": 2001}, {"id": 2002}],
                    "paging": {"total": 2, "limit": 50, "offset": 0},
                }
            if path == "/items?ids=MLA1,MLA2":
                mla1 = _item_detail()
                mla2 = {**_item_detail(), "id": "MLA2"}
                return [{"code": 200, "body": mla1}, {"code": 200, "body": mla2}]
            if path == "/shipments/3001":
                return _shipment_detail()
            if path == "/shipments/3001/costs":
                return _shipment_costs_payload()
            raise AssertionError(f"Unexpected gateway path: {path}")

    class SharedShipmentOrderDetailGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            self.calls.append((seller_id, path))
            if path == "/orders/2001":
                return _order_detail()
            if path == "/orders/2002":
                order = _order_detail()
                order["id"] = 2002
                order["order_items"] = [
                    {
                        "item": {"id": "MLA2", "seller_sku": "sku-2"},
                        "quantity": 1,
                        "unit_price": "49.95",
                    }
                ]
                return order
            raise AssertionError(f"Unexpected order detail gateway path: {path}")

    db = FakeDb()
    gateway = SharedShipmentGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=SharedShipmentOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=2,
    )

    gateway_paths = [path for _, path in gateway.calls]
    assert gateway_paths.count("/shipments/3001") == 1
    assert gateway_paths.count("/shipments/3001/costs") == 1
    assert summary.shipment_costs_requested == 1
    assert summary.shipment_real_shipping_costs_enriched == 1
    assert summary.shipment_real_shipping_costs_unavailable == 0

    shipment = db["shipments"].documents["3001"]
    real_cost = shipment["real_shipping_cost"]
    assert real_cost["source"] == "/shipments/{shipment_id}/costs"
    assert real_cost["seller_cost"].to_decimal() == Decimal128("24.50").to_decimal()
    assert real_cost["receiver_cost"].to_decimal() == Decimal128("100.00").to_decimal()
    assert real_cost["currency_id"] == "MXN"
    assert real_cost["matched_sender_id"] == "82453304"
    serialized_shipment = repr(shipment)
    for forbidden in ("senders", "buyer", "address", "token", "raw_payload"):
        assert forbidden not in serialized_shipment


@pytest.mark.asyncio
async def test_historical_backfill_fails_closed_when_shipment_costs_are_unmatched() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        shipment_costs_payload={
            "currency_id": "MXN",
            "senders": [{"sender_id": "999999", "cost": "24.50"}],
            "receiver": {"cost": "100.00"},
        }
    )

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )

    assert ("82453304", "/shipments/3001/costs") in gateway.calls
    assert summary.shipment_costs_requested == 1
    assert summary.shipment_real_shipping_costs_enriched == 0
    assert summary.shipment_real_shipping_costs_unavailable == 1
    assert "real_shipping_cost" not in db["shipments"].documents["3001"]


@pytest.mark.asyncio
async def test_historical_backfill_fails_closed_on_decimal128_seller_cost_overflow() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        shipment_costs_payload={
            "currency_id": "MXN",
            "senders": [{"sender_id": "82453304", "cost": "1E+10000"}],
            "receiver": {"cost": "100.00"},
        }
    )

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )

    assert ("82453304", "/shipments/3001/costs") in gateway.calls
    assert summary.shipment_costs_requested == 1
    assert summary.shipment_real_shipping_costs_enriched == 0
    assert summary.shipment_real_shipping_costs_unavailable == 1
    assert "real_shipping_cost" not in db["shipments"].documents["3001"]


@pytest.mark.asyncio
async def test_historical_backfill_fails_closed_on_decimal128_receiver_cost_overflow() -> None:
    db = FakeDb()
    gateway = FakeGateway(
        shipment_costs_payload={
            "currency_id": "MXN",
            "senders": [{"sender_id": "82453304", "cost": "24.50"}],
            "receiver": {"cost": "1E+10000"},
        }
    )

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )

    assert ("82453304", "/shipments/3001/costs") in gateway.calls
    assert summary.shipment_costs_requested == 1
    assert summary.shipment_real_shipping_costs_enriched == 0
    assert summary.shipment_real_shipping_costs_unavailable == 1
    assert "real_shipping_cost" not in db["shipments"].documents["3001"]


@pytest.mark.asyncio
async def test_buyer_address_pii_write_persists_snapshot_and_keeps_output_sanitized() -> None:
    db = FakeDb()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=FakeGateway(),
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        include_buyer_address_pii=True,
        max_orders=1,
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {
        "name": "SENTINEL BUYER NAME",
        "street_name": "SENTINEL STREET",
        "street_number": "123",
        "neighborhood": "SENTINEL NEIGHBORHOOD",
        "zip_code": "SENTINEL ZIP",
        "city": "SENTINEL CITY",
        "state": "SENTINEL STATE",
        "country": "SENTINEL COUNTRY",
    }
    output_json = json.dumps(summary.as_dict(), sort_keys=True)
    assert summary.written_shipments == 1
    assert summary.address_populated == 1
    assert "shipment_ids" not in summary.as_dict()
    assert "3001" not in output_json
    assert "SENTINEL BUYER NAME" not in output_json
    assert "SENTINEL STREET" not in output_json


@pytest.mark.asyncio
async def test_historical_backfill_write_accepts_partially_refunded_orders() -> None:
    db = FakeDb()
    gateway = FakeGateway()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(order_status="partially_refunded"),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )

    assert summary.status == "write_complete"
    assert db["orders"].documents["2001"]["status"] == "partially_refunded"


@pytest.mark.asyncio
async def test_historical_backfill_write_reupserts_fetched_docs_even_when_existing() -> None:
    db = FakeDb()
    gateway = FakeGateway()
    await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )
    gateway.calls.clear()

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=False,
        approved_runtime=True,
        max_orders=1,
    )

    assert summary.existing_orders == 1
    assert summary.existing_items == 1
    assert summary.existing_shipments == 1
    assert summary.missing_orders == 0
    assert summary.missing_items == 0
    assert summary.missing_shipments == 0
    assert summary.planned_orders == 1
    assert summary.planned_items == 1
    assert summary.planned_shipments == 1
    assert summary.written_orders == 1
    assert summary.written_items == 1
    assert summary.written_shipments == 1


@pytest.mark.asyncio
async def test_historical_backfill_dry_run_reports_item_detail_misses() -> None:
    db = FakeDb()
    gateway = FakeGateway(return_item_detail=False)

    summary = await run_historical_meli_backfill(
        db=db,
        gateway=gateway,
        order_detail_gateway=FakeOrderDetailGateway(),
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=1,
    )

    assert summary.item_ids == ["MLA1"]
    assert summary.items_fetched == 0
    assert summary.item_detail_missing == 1
    assert summary.missing_item_detail_ids == ["MLA1"]
    assert summary.planned_items == 0
    assert all(not collection.replace_calls for collection in db.collections.values())


@pytest.mark.asyncio
async def test_historical_backfill_applies_bounded_refs_after_private_resume_cursor() -> None:
    class MultiGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            self.calls.append((seller_id, path))
            if path.startswith("/orders/search?"):
                return {
                    "results": [{"id": 2001}, {"id": 2002}, {"id": 2003}],
                    "paging": {"total": 3, "limit": 3, "offset": 0},
                }
            if path == "/items?ids=MLA2":
                return [{"code": 200, "body": {**_item_detail(), "id": "MLA2"}}]
            if path == "/shipments/3002":
                return {**_shipment_detail(), "id": 3002, "order_id": 2002}
            if path == "/shipments/3002/costs":
                return _shipment_costs_payload()
            raise AssertionError(f"Unexpected gateway path: {path}")

    class MultiOrderGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def fetch_resource(self, *, seller_id: str, path: str) -> Any:
            self.calls.append((seller_id, path))
            order_id = path.removeprefix("/orders/")
            if order_id not in {"2002", "2003"}:
                raise AssertionError(f"Unexpected order detail path: {path}")
            order = _order_detail()
            order["id"] = int(order_id)
            order["shipping"] = {"id": int(order_id) + 1000}
            order["order_items"][0]["item"]["id"] = f"MLA{order_id[-1]}"
            return order

    gateway = MultiGateway()
    order_detail_gateway = MultiOrderGateway()

    summary = await run_historical_meli_backfill(
        db=FakeDb(),
        gateway=gateway,
        order_detail_gateway=order_detail_gateway,
        seller_id="82453304",
        date_from="2026-05-01",
        date_to="2026-05-01",
        dry_run=True,
        max_orders=3,
        max_items=1,
        max_shipments=1,
        resume_after_order_id="2001",
    )

    gateway_paths = [path for _, path in gateway.calls]
    assert [path for _, path in order_detail_gateway.calls] == ["/orders/2002", "/orders/2003"]
    assert summary.order_ids == ["2002", "2003"]
    assert summary.item_ids == ["MLA2"]
    assert summary.shipment_ids == ["3002"]
    assert summary.items_fetched == 1
    assert summary.shipments_fetched == 1
    assert "/items?ids=MLA3" not in gateway_paths
    assert "/shipments/3003" not in gateway_paths


@pytest.mark.asyncio
async def test_historical_backfill_write_fails_before_mutation_when_item_details_missing() -> None:
    db = FakeDb()
    gateway = FakeGateway(return_item_detail=False)

    with pytest.raises(ValueError, match="missing item details for 1 item"):
        await run_historical_meli_backfill(
            db=db,
            gateway=gateway,
            order_detail_gateway=FakeOrderDetailGateway(),
            seller_id="82453304",
            date_from="2026-05-01",
            date_to="2026-05-01",
            dry_run=False,
            approved_runtime=True,
            max_orders=1,
        )

    assert all(not collection.replace_calls for collection in db.collections.values())


def _order_detail(
    *, status: str = "paid", order_items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": 2001,
        "status": status,
        "date_created": "2026-05-01T12:00:00+00:00",
        "date_closed": "2026-05-01T12:05:00+00:00",
        "total_amount": "299.90",
        "buyer": {"id": 123},
        "shipping": {"id": 3001},
        "order_items": order_items
        or [
            {
                "item": {"id": "MLA1", "seller_sku": "sku-1"},
                "quantity": 2,
                "unit_price": "149.95",
            }
        ],
        "tags": ["paid"],
    }


def _item_detail() -> dict[str, Any]:
    return {
        "id": "MLA1",
        "title": "Premium widget",
        "price": "149.99",
        "base_price": "159.99",
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA123",
        "permalink": "https://articulo.example/MLA1",
        "thumbnail": "https://img.example/MLA1.jpg",
        "inventory_id": "INV-ITEM-1",
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "catalog_product_id": "CAT-MLA1",
        "variations": [],
        "date_created": "2026-05-01T10:00:00+00:00",
        "last_updated": "2026-05-01T11:00:00+00:00",
    }


def _catalog_product_detail() -> dict[str, Any]:
    return {
        "id": "CAT-MLA1",
        "name": "Catalog product",
        "description": "Complete catalog description",
        "pictures": [{"url": "https://img.example/catalog-product.jpg"}],
        "attributes": [{"id": "BRAND", "value_name": "Acme"}],
        "permalink": "https://catalog.example/CAT-MLA1",
    }


def _price_to_win_detail() -> dict[str, Any]:
    return {
        "item_id": "MLA1",
        "catalog_product_id": "CAT-MLA1",
        "title": "Catalog buybox item",
        "available_quantity": 7,
        "status": "winning",
        "current_price": 120,
        "price_to_win": 118,
        "competitors": [{"item_id": "MLA2"}, {"item_id": "MLA3"}],
        "only_competitor": "No",
    }


def _question_detail(
    question_id: str,
    *,
    status: str,
    answer_text: str | None = None,
    date_created: str = "2026-05-01T10:00:00+00:00",
) -> dict[str, Any]:
    question: dict[str, Any] = {
        "id": question_id,
        "item_id": "MLA1",
        "text": f"Question {question_id}",
        "status": status,
        "from": {"id": 987654321},
        "date_created": date_created,
    }
    if answer_text is not None:
        question["answer"] = {
            "text": answer_text,
            "date_created": "2026-05-01T10:05:00+00:00",
            "status": "ACTIVE",
        }
    return question


def _shipment_detail() -> dict[str, Any]:
    return {
        "id": 3001,
        "order_id": 2001,
        "status": "ready_to_ship",
        "substatus": "printed",
        "tracking_number": "TRACK-1",
        "logistic_type": "drop_off",
        "date_created": "2026-05-01T12:10:00+00:00",
        "last_updated": "2026-05-01T12:30:00+00:00",
        "receiver_address": {
            "receiver_name": "SENTINEL BUYER NAME",
            "street_name": "SENTINEL STREET",
            "street_number": "123",
            "neighborhood": {"name": "SENTINEL NEIGHBORHOOD"},
            "zip_code": "SENTINEL ZIP",
            "city": {"name": "SENTINEL CITY"},
            "state": {"name": "SENTINEL STATE"},
            "country": {"name": "SENTINEL COUNTRY"},
        },
    }


def _shipment_costs_payload() -> dict[str, Any]:
    return {
        "currency_id": "MXN",
        "senders": [
            {"sender_id": "111", "cost": "9.99"},
            {"sender_id": "82453304", "cost": "24.50", "currency_id": "MXN"},
        ],
        "receiver": {"cost": "100.00", "address": {"raw": "must-not-persist"}},
        "buyer": {"name": "must-not-persist"},
        "token": "must-not-persist",
        "raw_payload": {"must": "not persist"},
    }
