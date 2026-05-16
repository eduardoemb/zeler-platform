from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs[index] = replacement
                return
        if upsert:
            self.docs.append(replacement)


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


@pytest.mark.asyncio
async def test_reporting_service_filters_events_and_paginates_process_logs() -> None:
    from zeler_publicador.reporting import PublicadorReportingService

    db = _seed_reporting_db()
    service = PublicadorReportingService(db)

    result = await service.list_logs(
        seller_id="111",
        account_id="MLM-1",
        status="failed",
        sku="SKU-FAIL",
        error="timeout",
        page=1,
        page_size=1,
    )

    assert result["pagination"] == {"page": 1, "page_size": 1, "total": 2, "has_next": True}
    assert [event["_id"] for event in result["events"]] == ["event-newest"]
    assert result["events"][0]["operation"] == "draft.publish"
    assert result["events"][0]["retry_eligible"] is True
    assert result["events"][0]["request_summary"] == {"path": "/items"}
    assert "access_token" not in str(result["events"][0])


@pytest.mark.asyncio
async def test_reporting_service_aggregates_dashboard_statistics_and_recent_activity() -> None:
    from zeler_publicador.reporting import PublicadorReportingService

    db = _seed_reporting_db()
    service = PublicadorReportingService(db)

    dashboard = await service.dashboard(seller_id="111", account_id="MLM-1")
    statistics = await service.statistics(
        seller_id="111",
        account_id="MLM-1",
        date_from=datetime(2026, 5, 16, 0, 0, tzinfo=UTC),
        date_to=datetime(2026, 5, 16, 23, 59, tzinfo=UTC),
    )

    assert dashboard["counts"] == {
        "drafts": 3,
        "pending_approval": 1,
        "batches": 2,
        "suggestions": 2,
        "failed_items": 2,
        "published_items": 1,
    }
    assert [event["_id"] for event in dashboard["recent_activity"]] == [
        "event-newest",
        "event-older",
        "event-warning",
    ]
    assert statistics["status_breakdown"]["drafts"] == {"generated": 2, "published": 1}
    assert statistics["status_breakdown"]["batch_items"] == {"publish_failed": 2, "published": 1}
    assert statistics["trend"]["2026-05-16"] == {"failed": 2, "warning": 1}
    assert statistics["error_breakdown"] == {"timeout": 2, "validation": 1}


@pytest.mark.asyncio
async def test_reporting_service_upserts_settings_and_records_history_event() -> None:
    from zeler_publicador.reporting import PublicadorReportingService
    from zeler_publicador.schemas import PublicadorSettings

    db = _seed_reporting_db()
    service = PublicadorReportingService(
        db,
        clock=lambda: datetime(2026, 5, 16, 12, 30, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-settings",
    )

    settings = await service.upsert_settings(
        PublicadorSettings(
            seller_id="111",
            account_id="MLM-1",
            defaults={
                "official_store_id": "store-1",
                "brand": "Zeler",
                "listing_type": "gold_special",
                "logistics_type": "fulfillment",
                "free_shipping": True,
            },
            ai_provider_ref="gcp-secret://publicador/ai/provider",
            catalog_behavior="suggest_when_unmatched",
            updated_by="operator-1",
        )
    )

    assert settings["defaults"]["brand"] == "Zeler"
    assert settings["catalog_behavior"] == "suggest_when_unmatched"
    assert len(db["publicador_settings"].docs) == 1
    event = db["publicador_events"].docs[-1]
    assert event["aggregate_type"] == "settings"
    assert event["operation"] == "settings.updated"
    assert event["actor_id"] == "operator-1"


@pytest.mark.asyncio
async def test_publicador_reporting_api_contracts_are_seller_scoped_and_filterable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = _seed_reporting_db()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router(generator=_FakeGenerator(), publisher=_FakePublisher()))

    def fake_verify(_token: str) -> ModuleClaims:
        return ModuleClaims(
            module_id="publicador",
            seller_id=111,
            iss="module:publicador",
            aud="gateway",
            iat=1,
            exp=2,
            token_type="module_admin",  # noqa: S106 - JWT token type fixture, not a secret
            scopes=["admin:publicador"],
            issued_by="zeler-app",
        )

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        logs = await client.get(
            "/publicador/logs?seller_id=111&account_id=MLM-1&status=failed&sku=SKU-FAIL&page=1&page_size=1",
            headers={"Authorization": "Bearer valid"},
        )
        dashboard = await client.get(
            "/publicador/dashboard?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
        )
        statistics = await client.get(
            "/publicador/statistics?seller_id=111&account_id=MLM-1&date_from=2026-05-16&date_to=2026-05-16",
            headers={"Authorization": "Bearer valid"},
        )
        settings = await client.put(
            "/publicador/settings",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "defaults": {"brand": "Zeler", "listing_type": "gold_special"},
                "ai_provider_ref": "gcp-secret://publicador/ai/provider",
                "catalog_behavior": "manual_only",
                "updated_by": "operator-2",
            },
        )

    assert logs.status_code == 200
    assert logs.json()["pagination"]["total"] == 2
    assert logs.json()["events"][0]["sku"] == "SKU-FAIL"
    assert dashboard.json()["counts"]["failed_items"] == 2
    assert statistics.json()["status_breakdown"]["batch_items"]["publish_failed"] == 2
    assert settings.status_code == 200
    assert settings.json()["defaults"]["brand"] == "Zeler"


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 7 tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 7 tests")


def _seed_reporting_db() -> FakeDb:
    db = FakeDb()
    db["publicador_drafts"].docs.extend(
        [
            _draft(
                "draft-pending", status="generated", approval_status="pending", sku="SKU-PENDING"
            ),
            _draft("draft-failed", status="generated", process_status="failed", sku="SKU-FAIL"),
            _draft("draft-published", status="published", process_status="published", sku="SKU-OK"),
            _draft("other-seller", seller_id="222", account_id="MLM-9", status="published"),
        ]
    )
    db["publicador_batches"].docs.extend(
        [
            _batch("batch-1", status="processed"),
            _batch("batch-2", status="published"),
            _batch("batch-hidden", seller_id="222", account_id="MLM-9", status="published"),
        ]
    )
    db["publicador_batch_items"].docs.extend(
        [
            _batch_item("item-failed-1", status="publish_failed", sku="SKU-FAIL"),
            _batch_item("item-failed-2", status="publish_failed", sku="SKU-FAIL"),
            _batch_item("item-published", status="published", sku="SKU-OK"),
            _batch_item(
                "item-hidden", seller_id="222", account_id="MLM-9", status="publish_failed"
            ),
        ]
    )
    db["publicador_catalog_suggestions"].docs.extend(
        [
            _suggestion("suggestion-1", status="under_review"),
            _suggestion("suggestion-2", status="approved"),
            _suggestion(
                "suggestion-hidden", seller_id="222", account_id="MLM-9", status="approved"
            ),
        ]
    )
    db["publicador_events"].docs.extend(
        [
            _event(
                "event-newest",
                status="failed",
                operation="draft.publish",
                aggregate_type="draft",
                aggregate_id="draft-failed",
                draft_id="draft-failed",
                sku="SKU-FAIL",
                created_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
                error_code="timeout",
                retry_eligible=True,
                request_summary={"path": "/items", "access_token": "must-redact"},
            ),
            _event(
                "event-older",
                status="failed",
                operation="batch_item.publish",
                aggregate_type="batch_item",
                aggregate_id="item-failed-1",
                sku="SKU-FAIL",
                created_at=datetime(2026, 5, 16, 11, 0, tzinfo=UTC),
                error_code="timeout",
                retry_eligible=True,
            ),
            _event(
                "event-warning",
                status="warning",
                operation="draft.validate",
                aggregate_type="draft",
                aggregate_id="draft-pending",
                draft_id="draft-pending",
                sku="SKU-PENDING",
                created_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
                error_code="validation",
            ),
            _event(
                "event-hidden-account",
                status="failed",
                account_id="MLM-2",
                aggregate_id="draft-other-account",
                sku="SKU-FAIL",
                created_at=datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            ),
            _event(
                "event-hidden-seller",
                seller_id="222",
                account_id="MLM-9",
                status="failed",
                aggregate_id="draft-other-seller",
                sku="SKU-FAIL",
                created_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
            ),
        ]
    )
    return db


def _draft(
    draft_id: str,
    *,
    seller_id: str = "111",
    account_id: str = "MLM-1",
    status: str = "generated",
    approval_status: str = "draft",
    process_status: str = "not_started",
    sku: str = "SKU-1",
) -> dict[str, Any]:
    return {
        "_id": draft_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "sku": sku,
        "status": status,
        "approval_status": approval_status,
        "process_status": process_status,
        "created_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def _batch(
    batch_id: str,
    *,
    seller_id: str = "111",
    account_id: str = "MLM-1",
    status: str = "processed",
) -> dict[str, Any]:
    return {
        "_id": batch_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "status": status,
        "counts": {},
        "created_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def _batch_item(
    item_id: str,
    *,
    seller_id: str = "111",
    account_id: str = "MLM-1",
    status: str = "publish_failed",
    sku: str = "SKU-FAIL",
) -> dict[str, Any]:
    return {
        "_id": item_id,
        "batch_id": "batch-1",
        "seller_id": seller_id,
        "account_id": account_id,
        "sku": sku,
        "status": status,
        "errors": ["timeout"] if status == "publish_failed" else [],
        "created_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def _suggestion(
    suggestion_id: str,
    *,
    seller_id: str = "111",
    account_id: str = "MLM-1",
    status: str = "under_review",
) -> dict[str, Any]:
    return {
        "_id": suggestion_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "status": status,
        "created_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def _event(
    event_id: str,
    *,
    seller_id: str = "111",
    account_id: str = "MLM-1",
    status: str,
    operation: str = "draft.publish",
    aggregate_type: str = "draft",
    aggregate_id: str,
    draft_id: str | None = None,
    sku: str | None = None,
    created_at: datetime,
    error_code: str | None = "timeout",
    retry_eligible: bool = False,
    request_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_id": event_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "draft_id": draft_id,
        "sku": sku,
        "operation": operation,
        "status": status,
        "actor_id": "operator-1",
        "error_code": error_code,
        "retry_eligible": retry_eligible,
        "request_summary": request_summary or {},
        "response_summary": {"error": error_code} if error_code else {},
        "created_at": created_at,
        "schema_version": 1,
    }


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
