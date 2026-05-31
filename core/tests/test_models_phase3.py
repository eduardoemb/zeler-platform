# mypy: ignore-errors
# ruff: noqa: S106 -- model fixtures use inert token-shaped strings, not credentials.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from zeler_platform_core.models import (
    AuditLog,
    BootstrapJob,
    Claim,
    Item,
    MeliAccount,
    Message,
    ModuleRegistry,
    Order,
    Question,
    RepricerHistory,
    RepricerRule,
    Shipment,
    User,
    WebhookEvent,
)

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


def test_meli_account_coerces_numeric_seller_id_and_rejects_bad_status() -> None:
    account = MeliAccount(
        id="507f1f77bcf86cd799439011",
        seller_id=123456789,
        nickname="TEST_SELLER",
        app_id="zeler-platform",
        platform_user_id="platform-user-1",
        access_token_ciphertext="access-ciphertext",
        access_token_dek_wrapped="access-dek",
        refresh_token_ciphertext="refresh-ciphertext",
        refresh_token_dek_wrapped="refresh-dek",
        token_nonce="nonce",
        refresh_token_nonce="refresh-nonce",
        scopes=["read", "write"],
        status="active",
        expires_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        kms_key_version="kms-v1",
    )

    assert account.seller_id == "123456789"
    assert account.schema_version == 1

    with pytest.raises(ValidationError):
        MeliAccount.model_validate({**account.model_dump(), "status": "deleted"})


def test_user_rejects_naive_datetime_and_invalid_auth_provider() -> None:
    valid_user = User(
        id="507f1f77bcf86cd799439012",
        email="operator@example.com",
        name="Operator",
        auth_provider="google",
        meli_account_ids=[123456789],
        module_permissions={"repricer": ["read"]},
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )

    assert valid_user.meli_account_ids == ["123456789"]

    with pytest.raises(ValidationError):
        User.model_validate({**valid_user.model_dump(), "created_at": datetime(2026, 4, 24, 12, 0)})

    with pytest.raises(ValidationError):
        User.model_validate({**valid_user.model_dump(), "auth_provider": "legacy"})


def test_shipment_accepts_meli_not_delivered_status() -> None:
    shipment = Shipment.model_validate(
        {
            "id": 555,
            "seller_id": 123,
            "order_id": 987654,
            "status": "not_delivered",
            "logistic_type": "fulfillment",
            "date_created": NOW,
            "last_updated": NOW,
        }
    )

    assert shipment.status == "not_delivered"


def test_order_accepts_meli_partially_refunded_status() -> None:
    order = Order.model_validate(
        {
            "id": 123,
            "seller_id": 456,
            "buyer_id": 789,
            "status": "partially_refunded",
            "date_created": NOW,
            "total_amount": Decimal("10.00"),
            "items": [],
            "schema_version": 1,
        }
    )

    assert order.status == "partially_refunded"


def test_item_preserves_whitelisted_formula_fields_without_raw_payload_drift() -> None:
    item = Item.model_validate(
        {
            "id": "MLM123",
            "seller_id": 123,
            "title": "Item",
            "price": Decimal("10.50"),
            "base_price": Decimal("12.00"),
            "available_quantity": 5,
            "status": "active",
            "category_id": "MLM-CAT",
            "permalink": "https://articulo.example/MLM123",
            "thumbnail": "https://img.example/MLM123.jpg",
            "catalog_product_id": "MLM-CATALOG-1",
            "inventory_id": "ITEM-INV-1",
            "variations": [
                {"id": 456, "inventory_id": "VAR-INV-456", "seller_custom_field": "sku-456"}
            ],
            "raw_payload_blob": {"must_not": "be persisted"},
            "last_meli_sync_at": NOW,
            "date_created": NOW,
            "last_updated": NOW,
            "schema_version": 2,
        }
    )

    dumped = item.model_dump(by_alias=True, mode="json")

    assert dumped["permalink"] == "https://articulo.example/MLM123"
    assert dumped["thumbnail"] == "https://img.example/MLM123.jpg"
    assert dumped["catalog_product_id"] == "MLM-CATALOG-1"
    assert dumped["inventory_id"] == "ITEM-INV-1"
    assert dumped["variations"][0]["inventory_id"] == "VAR-INV-456"
    assert "raw_payload_blob" not in dumped


def test_item_accepts_nullable_formula_fields() -> None:
    item = Item.model_validate(
        {
            "id": "MLM124",
            "seller_id": 123,
            "title": "Item without enrichments",
            "price": Decimal("10.50"),
            "base_price": Decimal("12.00"),
            "available_quantity": 5,
            "status": "active",
            "category_id": "MLM-CAT",
            "permalink": None,
            "thumbnail": None,
            "catalog_product_id": None,
            "inventory_id": None,
            "last_meli_sync_at": NOW,
            "date_created": NOW,
            "last_updated": NOW,
            "schema_version": 2,
        }
    )

    assert item.permalink is None
    assert item.thumbnail is None
    assert item.catalog_product_id is None
    assert item.inventory_id is None


@pytest.mark.parametrize(
    ("model_cls", "payload", "id_field"),
    [
        (
            Item,
            {
                "id": "MLM123",
                "seller_id": 123,
                "title": "Item",
                "price": Decimal("10.50"),
                "base_price": Decimal("12.00"),
                "available_quantity": 5,
                "status": "active",
                "category_id": "MLM-CAT",
                "last_meli_sync_at": NOW,
                "date_created": NOW,
                "last_updated": NOW,
            },
            "seller_id",
        ),
        (
            Order,
            {
                "id": 987654,
                "seller_id": 123,
                "buyer_id": 456,
                "status": "paid",
                "date_created": NOW,
                "date_closed": NOW,
                "total_amount": Decimal("100.00"),
                "items": [{"item_id": 1234, "qty": 2, "unit_price": Decimal("50.00")}],
                "shipment_id": 555,
            },
            "id",
        ),
        (
            Question,
            {
                "id": 111,
                "seller_id": 123,
                "item_id": 1234,
                "text": "Still available?",
                "status": "UNANSWERED",
                "from_user_id": 456,
                "date_created": NOW,
            },
            "item_id",
        ),
        (
            Message,
            {
                "id": 222,
                "seller_id": 123,
                "pack_id": 333,
                "order_id": 987654,
                "from_user_id": 456,
                "to_user_id": 123,
                "text": "Hello",
                "status": "available",
                "date_created": NOW,
            },
            "pack_id",
        ),
        (
            Shipment,
            {
                "id": 555,
                "seller_id": 123,
                "order_id": 987654,
                "status": "ready_to_ship",
                "substatus": "printed",
                "tracking_number": "TRACK",
                "logistic_type": "fulfillment",
                "date_created": NOW,
                "last_updated": NOW,
            },
            "order_id",
        ),
        (
            Claim,
            {
                "id": 777,
                "seller_id": 123,
                "buyer_id": 456,
                "order_id": 987654,
                "status": "opened",
                "stage": "claim",
                "type": "mediations",
                "date_created": NOW,
            },
            "order_id",
        ),
    ],
)
def test_entity_models_coerce_meli_ids_and_reject_naive_datetimes(
    model_cls: type[Item | Order | Question | Message | Shipment | Claim],
    payload: dict[str, object],
    id_field: str,
) -> None:
    entity = model_cls(**payload)

    assert getattr(entity, id_field) == str(payload[id_field])
    assert entity.schema_version == 1

    with pytest.raises(ValidationError):
        model_cls.model_validate(
            {**entity.model_dump(), "date_created": datetime(2026, 4, 24, 12, 0)}
        )


@pytest.mark.parametrize(
    ("model_cls", "payload", "bad_field"),
    [
        (
            Item,
            {
                "id": "MLM123",
                "seller_id": 123,
                "title": "Item",
                "price": Decimal("10.50"),
                "base_price": Decimal("12.00"),
                "available_quantity": 5,
                "status": "active",
                "category_id": "MLM-CAT",
                "last_meli_sync_at": NOW,
                "date_created": NOW,
                "last_updated": NOW,
            },
            "status",
        ),
        (
            Order,
            {
                "id": 987654,
                "seller_id": 123,
                "buyer_id": 456,
                "status": "paid",
                "date_created": NOW,
                "total_amount": Decimal("100.00"),
            },
            "status",
        ),
        (
            Message,
            {
                "id": 222,
                "seller_id": 123,
                "pack_id": 333,
                "from_user_id": 456,
                "to_user_id": 123,
                "text": "Hello",
                "status": "available",
                "date_created": NOW,
            },
            "status",
        ),
        (
            Shipment,
            {
                "id": 555,
                "seller_id": 123,
                "order_id": 987654,
                "status": "ready_to_ship",
                "logistic_type": "fulfillment",
                "date_created": NOW,
                "last_updated": NOW,
            },
            "status",
        ),
        (
            Claim,
            {
                "id": 777,
                "seller_id": 123,
                "order_id": 987654,
                "status": "opened",
                "stage": "claim",
                "type": "mediations",
                "date_created": NOW,
            },
            "type",
        ),
    ],
)
def test_entity_models_reject_invalid_status_like_fields(
    model_cls: type[Item | Order | Message | Shipment | Claim],
    payload: dict[str, object],
    bad_field: str,
) -> None:
    with pytest.raises(ValidationError):
        model_cls.model_validate({**payload, bad_field: "not-a-real-status"})


def test_operational_models_validate_statuses_ttl_fields_and_uuid_events() -> None:
    webhook_event = WebhookEvent(
        id="notif-1",
        topic="items",
        user_id=123,
        resource="/items/MLM123",
        received_at=NOW,
        raw_body={"_id": "notif-1"},
        source_ip="1.2.3.4",
    )
    bootstrap_job = BootstrapJob(
        id="507f1f77bcf86cd799439013",
        seller_id=123,
        state="pending",
        created_at=NOW,
        updated_at=NOW,
    )
    module_registry = ModuleRegistry(
        id="repricer",
        version="0.1.0",
        allowed_meli_scopes=["GET /items/*"],
        allowed_platform_user_ids=[123, "platform-user-456"],
        allowed_seller_ids=[82453304, "987654321"],
        routing_keys=["items.*"],
        status="enabled",
    )
    repricer_rule = RepricerRule(
        id="507f1f77bcf86cd799439014",
        seller_id=123,
        item_id=1234,
        strategy="min_price",
        min_price=Decimal("10.00"),
        max_price=Decimal("20.00"),
        active=True,
        updated_at=NOW,
    )
    repricer_history = RepricerHistory(
        id="507f1f77bcf86cd799439015",
        seller_id=123,
        item_id=1234,
        old_price=Decimal("10.00"),
        new_price=Decimal("11.00"),
        reason="competition",
        applied_at=NOW,
    )
    audit_log = AuditLog(
        id="507f1f77bcf86cd799439016",
        at=NOW,
        module_id="repricer",
        seller_id=123,
        method="GET",
        path="/items/MLM123",
        status=200,
        duration_ms=15,
        trace_id="trace-1",
    )

    assert webhook_event.user_id == "123"
    assert bootstrap_job.state == "pending"
    assert module_registry.status == "enabled"
    assert module_registry.allowed_platform_user_ids == ["123", "platform-user-456"]
    assert module_registry.allowed_seller_ids == ["82453304", "987654321"]
    assert repricer_rule.item_id == "1234"
    assert repricer_history.item_id == "1234"
    assert audit_log.seller_id == "123"

    with pytest.raises(ValidationError):
        BootstrapJob.model_validate({**bootstrap_job.model_dump(), "state": "completed"})
    with pytest.raises(ValidationError):
        ModuleRegistry.model_validate({**module_registry.model_dump(), "status": "offline"})

    completed = bootstrap_job.to_event(
        event_id=UUID("00000000-0000-4000-8000-000000000001"), occurred_at=NOW
    )
    assert completed.event_type == "BootstrapCompleted"
    assert completed.account_id == "123"


def test_module_registry_defaults_user_and_deprecated_seller_allowlists() -> None:
    module_registry = ModuleRegistry(
        id="zeler-app",
        version="0.1.0",
        allowed_meli_scopes=[],
        routing_keys=[],
        status="enabled",
    )

    assert module_registry.allowed_platform_user_ids == []
    assert module_registry.allowed_seller_ids == []
