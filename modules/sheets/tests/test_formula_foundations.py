# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.extension_tokens import (
    ExtensionTokenService,
    ExtensionTokenValidationError,
    SellerScope,
)
from zeler_sheets.formulas.audit import FormulaAuditService
from zeler_sheets.formulas.rate_limits import FormulaRateLimitService
from zeler_sheets.formulas.read_models import (
    FormulaReadModelRepository,
    require_formula_read_model_available,
)
from zeler_sheets.formulas.registry import FormulaRegistry


class FakeUpdateResult:
    modified_count = 1
    upserted_id: str | None = None


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_args: Any) -> FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.documents[str(doc["_id"])] = dict(doc)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.last_find_filter = dict(filter_spec)
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.last_find_filter = dict(filter_spec)
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        self.last_find_filter = dict(filter_spec)
        for doc_id, doc in self.documents.items():
            if _matches(doc, filter_spec):
                self.documents[doc_id] = dict(replacement)
                return FakeUpdateResult()
        if upsert:
            self.documents[str(replacement["_id"])] = dict(replacement)
            return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        assert upsert is False
        for doc_id, doc in self.documents.items():
            if _matches(doc, filter_spec):
                replacement = dict(doc)
                replacement.update(update_spec.get("$set", {}))
                self.documents[doc_id] = replacement
                return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        value = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_formula_audit_service_persists_redacted_request_decisions() -> None:
    now = datetime(2026, 5, 13, 15, 30, tzinfo=UTC)
    db = FakeDb()
    service = FormulaAuditService(db=db, now_fn=lambda: now)

    await service.record(
        {
            "token_id": "sheets-ext-token-abc",
            "seller_id": "123456789",
            "seller_nickname": "HOPEMOB",
            "formula": "ZELERDATA_PRECIO",
            "request_id": "req-1",
            "outcome": "denied",
            "error_code": "RATE_LIMITED",
            "occurred_at": now,
            "Authorization": "Bearer zs_ext_secret",
            "token_once": "zs_ext_secret",
        }
    )

    docs = list(db["sheets_formula_audit"].documents.values())
    assert docs == [
        {
            "_id": "formula-audit-req-1",
            "token_id": "sheets-ext-token-abc",
            "seller_id": "123456789",
            "seller_nickname": "HOPEMOB",
            "formula": "ZELERDATA_PRECIO",
            "request_id": "req-1",
            "outcome": "denied",
            "error_code": "RATE_LIMITED",
            "occurred_at": now,
            "schema_version": 1,
        }
    ]
    assert "token_once" not in docs[0]
    assert "Authorization" not in docs[0]


@pytest.mark.asyncio
async def test_formula_rate_limiter_is_scoped_by_token_seller_formula_and_window() -> None:
    current_time = datetime(2026, 5, 13, 15, 30, tzinfo=UTC)
    db = FakeDb()
    service = FormulaRateLimitService(
        db=db,
        max_requests=2,
        window_seconds=60,
        now_fn=lambda: current_time,
    )

    context = {
        "token_id": "token-1",
        "seller_id": "seller-1",
        "seller_nickname": "HOPEMOB",
        "formula": "ZELERDATA_PRECIO",
        "request_id": "req-rate",
    }

    assert await service.allow(context) is True
    assert await service.allow(context) is True
    assert await service.allow(context) is False
    assert await service.allow(context | {"formula": "ZELERDATA_SKU"}) is True
    assert await service.allow(context | {"seller_id": "seller-2"}) is True

    current_time = current_time + timedelta(seconds=61)
    assert await service.allow(context) is True

    counter_docs = list(db["rate_limit_counters"].documents.values())
    precio_counter = next(doc for doc in counter_docs if doc["formula"] == "ZELERDATA_PRECIO")
    assert precio_counter["token_id"] == "token-1"
    assert precio_counter["seller_id"] == "seller-1"
    assert precio_counter["count"] == 2
    assert precio_counter["schema_version"] == 1


@pytest.mark.asyncio
async def test_item_formula_repository_uses_seller_scoped_sku_and_item_filters() -> None:
    db = FakeDb()
    rows = db["sheets_item_formula_rows"]
    rows.documents = {
        "row-a": {
            "_id": "row-a",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "title": "First item",
        },
        "row-other-seller": {
            "_id": "row-other-seller",
            "seller_id": "seller-2",
            "normalized_sku": "SKU-1",
            "item_id": "MLA1",
            "title": "Wrong tenant",
        },
        "row-other-item": {
            "_id": "row-other-item",
            "seller_id": "seller-1",
            "normalized_sku": "SKU-2",
            "item_id": "MLA2",
            "title": "Other item",
        },
    }
    repository = FormulaReadModelRepository(db=db)

    found = await repository.find_item_formula_rows(
        seller_id="seller-1",
        skus=[" sku-1 "],
        item_ids=["MLA1"],
    )

    assert found == [rows.documents["row-a"]]
    assert rows.last_find_filter == {
        "seller_id": "seller-1",
        "normalized_sku": {"$in": ["SKU-1"]},
        "item_id": {"$in": ["MLA1"]},
    }


def test_historical_and_catalog_formulas_are_no_longer_batch_gated() -> None:
    registry = FormulaRegistry.default()

    require_formula_read_model_available(registry.find_required("ZELERDATA_PAUSADAS"))
    require_formula_read_model_available(registry.find_required("ZELERDATA_CATALOGO"))


@pytest.mark.asyncio
async def test_extension_token_validation_awaits_persistent_audit_and_rate_limit_hooks() -> None:
    now = datetime(2026, 5, 13, 15, 30, tzinfo=UTC)
    db = FakeDb()
    audit = FormulaAuditService(db=db, now_fn=lambda: now)
    limiter = FormulaRateLimitService(
        db=db,
        max_requests=1,
        window_seconds=60,
        now_fn=lambda: now,
    )
    token_service = ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: now,
        token_factory=lambda: "persistent-hooks",
        audit_hook=audit.record,
        rate_limit_hook=limiter.allow,
    )
    issued = await token_service.create_token(
        owner_user_id="user-1",
        label="Formula sheet",
        seller_scopes=[SellerScope(seller_id="seller-1", nickname="HOPEMOB")],
    )

    allowed = await token_service.validate_token(
        issued.token_once,
        cuenta="HOPEMOB",
        formula="ZELERDATA_PRECIO",
        request_id="req-allowed",
    )
    with pytest.raises(ExtensionTokenValidationError) as exc_info:
        await token_service.validate_token(
            issued.token_once,
            cuenta="HOPEMOB",
            formula="ZELERDATA_PRECIO",
            request_id="req-limited",
        )

    audit_docs = db["sheets_formula_audit"].documents
    assert allowed.seller_id == "seller-1"
    assert exc_info.value.code == "RATE_LIMITED"
    assert audit_docs["formula-audit-req-allowed"]["outcome"] == "allowed"
    assert audit_docs["formula-audit-req-allowed"]["error_code"] is None
    assert audit_docs["formula-audit-req-limited"]["outcome"] == "denied"
    assert audit_docs["formula-audit-req-limited"]["error_code"] == "RATE_LIMITED"
