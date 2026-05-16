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
async def test_catalog_search_and_link_publish_persist_catalog_product_id() -> None:
    from zeler_publicador.catalog import CatalogSuggestionService

    db = FakeDb()
    db["publicador_drafts"].docs.append(_draft())
    gateway = _FakeCatalogGateway()
    service = CatalogSuggestionService(
        db,
        gateway=gateway,
        clock=lambda: datetime(2026, 5, 16, 22, 0, tzinfo=UTC),
    )

    candidates = await service.search_catalog(
        seller_id="111",
        account_id="MLM-1",
        query="Campera urbana",
        gtin="7501234567890",
        permalink=None,
    )
    result = await service.publish_catalog_link(
        seller_id="111",
        account_id="MLM-1",
        draft_id="draft-1",
        catalog_product_id="MLM-CATALOG-1",
        actor_id="operator-1",
    )

    publish_payload = next(call[2] for call in gateway.calls if call[:2] == ("POST", "/items"))
    updated_draft = db["publicador_drafts"].docs[0]
    assert candidates == [
        {
            "catalog_product_id": "MLM-CATALOG-1",
            "name": "Campera urbana catálogo",
            "domain_id": "MLM-JACKETS",
            "permalink": "https://meli.example/catalog/MLM-CATALOG-1",
        }
    ]
    assert publish_payload["catalog_product_id"] == "MLM-CATALOG-1"
    assert publish_payload["status"] == "paused"
    assert publish_payload["available_quantity"] == 0
    assert updated_draft["catalog_product_id"] == "MLM-CATALOG-1"
    assert updated_draft["is_catalog"] is True
    assert result["status"] == "published"
    assert db["publicador_events"].docs[-2]["operation"] == "catalog.linked"


@pytest.mark.asyncio
async def test_suggestion_lifecycle_upload_validate_send_refresh_and_notification_events() -> None:
    from zeler_publicador.assets import AssetService, ImageUpload
    from zeler_publicador.catalog import CatalogSuggestionService

    db = FakeDb()
    db["publicador_drafts"].docs.append(_draft(catalog_product_id=None))
    gateway = _FakeCatalogGateway()
    service = CatalogSuggestionService(
        db,
        gateway=gateway,
        clock=lambda: datetime(2026, 5, 16, 22, 5, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db['publicador_catalog_suggestions'].docs) + 1}",
    )
    asset_service = AssetService(
        db,
        picture_gateway=_AlwaysPictureGateway(),
        clock=lambda: datetime(2026, 5, 16, 22, 5, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db['publicador_assets'].docs) + 1}",
    )

    created = await service.create_for_draft(
        seller_id="111", account_id="MLM-1", draft_id="draft-1", actor_id="operator-1"
    )
    assets = await asset_service.register_assets(
        seller_id="111",
        account_id="MLM-1",
        owner_type="suggestion",
        owner_id=created["_id"],
        sku="SKU-1",
        flow="suggestion",
        images=[
            ImageUpload(
                filename=f"suggestion-{index}.jpg",
                content_type="image/jpeg",
                width=800,
                height=800,
                data=f"image-{index}".encode(),
            )
            for index in range(1, 4)
        ],
        actor_id="operator-1",
    )
    for asset in assets:
        await asset_service.upload_to_meli(
            asset_id=asset["_id"], seller_id="111", account_id="MLM-1", actor_id="operator-1"
        )

    validated = await service.validate_suggestion(
        seller_id="111", account_id="MLM-1", suggestion_id=created["_id"], actor_id="operator-2"
    )
    sent = await service.send_suggestion(
        seller_id="111", account_id="MLM-1", suggestion_id=created["_id"], actor_id="operator-3"
    )
    refreshed = await service.refresh_status(
        seller_id="111", account_id="MLM-1", suggestion_id=created["_id"], actor_id="operator-4"
    )
    notified = await service.process_notification(
        seller_id="111",
        account_id="MLM-1",
        payload={
            "suggestion_id": "MELI-SUG-1",
            "status": "approved",
            "catalog_product_id": "MLM-CATALOG-NEW",
        },
    )
    listed = await service.list_suggestions(seller_id="111", account_id="MLM-1", status="approved")

    assert created["status"] == "draft"
    assert validated["status"] == "validated"
    assert validated["meli_picture_ids"] == ["picture-1", "picture-2", "picture-3"]
    assert sent["suggestion_id"] == "MELI-SUG-1"
    assert sent["status"] == "sent"
    assert refreshed["status"] == "under_review"
    assert notified["status"] == "approved"
    assert notified["catalog_product_id"] == "MLM-CATALOG-NEW"
    assert [suggestion["_id"] for suggestion in listed] == [created["_id"]]
    suggestion_events = [
        event["operation"]
        for event in db["publicador_events"].docs
        if event["aggregate_type"] == "catalog_suggestion"
    ]
    assert suggestion_events == [
        "catalog_suggestion.created",
        "catalog_suggestion.validated",
        "catalog_suggestion.sent",
        "catalog_suggestion.status_refreshed",
        "catalog_suggestion.notification_processed",
    ]


@pytest.mark.asyncio
async def test_publicador_catalog_and_suggestion_api_contracts_are_seller_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = FakeDb()
    db["publicador_drafts"].docs.append(_draft())
    app = FastAPI()
    app.state.mongo_db = db
    app.state.publicador_meli_gateway = _FakeCatalogGateway()
    app.include_router(build_router(generator=_FakeGenerator(), publisher=_FakePublisher()))

    def fake_verify(_token: str) -> ModuleClaims:
        return ModuleClaims(
            module_id="publicador",
            seller_id=111,
            iss="module:publicador",
            aud="gateway",
            iat=1,
            exp=2,
            token_type="module_admin",  # noqa: S106 - test fixture token type, not a secret
            scopes=["admin:publicador"],
            issued_by="zeler-app",
        )

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        search = await client.get(
            "/publicador/catalog/search?seller_id=111&account_id=MLM-1&q=Campera&gtin=7501234567890",
            headers={"Authorization": "Bearer valid"},
        )
        linked = await client.post(
            "/publicador/publications/draft-1/catalog-link",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "catalog_product_id": "MLM-CATALOG-1",
                "actor_id": "operator-1",
            },
        )
        created = await client.post(
            "/publicador/suggestions",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "draft_id": "draft-1",
                "actor_id": "operator-2",
            },
        )
        suggestion_id = created.json()["_id"]
        listed = await client.get(
            "/publicador/suggestions?seller_id=111&account_id=MLM-1&status=draft",
            headers={"Authorization": "Bearer valid"},
        )
        detail = await client.get(
            f"/publicador/suggestions/{suggestion_id}?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert search.status_code == 200
    assert search.json()[0]["catalog_product_id"] == "MLM-CATALOG-1"
    assert linked.status_code == 200
    assert linked.json()["catalog_product_id"] == "MLM-CATALOG-1"
    assert created.status_code == 201
    assert listed.json()[0]["_id"] == suggestion_id
    assert detail.json()["draft_id"] == "draft-1"


class _FakeCatalogGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, path, json))
        if method == "GET" and path.startswith("/products/search"):
            return {
                "results": [
                    {
                        "id": "MLM-CATALOG-1",
                        "name": "Campera urbana catálogo",
                        "domain_id": "MLM-JACKETS",
                        "permalink": "https://meli.example/catalog/MLM-CATALOG-1",
                    }
                ]
            }
        if (method, path) == ("GET", "/categories/MLM1430/attributes"):
            return []
        if (method, path) == ("GET", "/users/111/brands"):
            return []
        if (method, path) == ("GET", "/users/111/stores/search"):
            return []
        if (method, path) == ("GET", "/sites/MLM/listing_types"):
            return [{"id": "gold_special", "name": "Premium"}]
        if (method, path) == ("GET", "/users/111/shipping_preferences"):
            return {"logistics": [{"type": "fulfillment", "label": "Full"}]}
        if (method, path) == ("POST", "/items/validate"):
            return {"status": "ok", "field_errors": []}
        if (method, path) == ("POST", "/items"):
            return {"id": "MLM123", "permalink": "https://meli.example/MLM123"}
        if (method, path) == ("POST", "/catalog_suggestions/validate"):
            assert json is not None
            return {"status": "validated", "errors": []}
        if (method, path) == ("POST", "/catalog_suggestions"):
            assert json is not None
            return {"id": "MELI-SUG-1", "status": "sent"}
        if (method, path) == ("GET", "/catalog_suggestions/MELI-SUG-1"):
            return {"id": "MELI-SUG-1", "status": "under_review", "errors": []}
        raise AssertionError(f"unexpected gateway call {method} {path}")


class _AlwaysPictureGateway:
    def __init__(self) -> None:
        self.count = 0

    async def upload_picture(self, _storage_uri: str) -> str:
        self.count += 1
        return f"picture-{self.count}"


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 5 tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 5 tests")


def _draft(**overrides: Any) -> dict[str, Any]:
    draft = {
        "_id": "draft-1",
        "seller_id": "111",
        "account_id": "MLM-1",
        "sku": "SKU-1",
        "gtin": "7501234567890",
        "title": "Campera urbana",
        "description": "Campera impermeable",
        "category_id": "MLM1430",
        "domain_id": "MLM-JACKETS",
        "attributes": {"BRAND": "Zeler"},
        "price": 4500,
        "listing_type": "gold_special",
        "logistics_type": "fulfillment",
        "free_shipping": True,
        "approval_status": "approved",
        "process_status": "not_started",
        "status": "generated",
        "errors": [],
        "created_at": datetime(2026, 5, 16, 22, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 22, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    draft.update(overrides)
    return draft


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
