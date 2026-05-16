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
async def test_meli_taxonomy_and_preferences_resolve_gateway_and_cached_settings() -> None:
    from zeler_publicador.meli import MeliPublicationService

    db = FakeDb()
    db["publicador_settings"].docs.append(
        {
            "seller_id": "111",
            "account_id": "MLM-1",
            "defaults": {
                "listing_type": "gold_special",
                "logistics_type": "fulfillment",
                "official_store_id": "store-1",
                "brand": "Zeler",
            },
        }
    )
    gateway = _FakeMeliGateway()
    service = MeliPublicationService(db, gateway=gateway)

    predictions = await service.predict_categories(
        seller_id="111", account_id="MLM-1", query="Campera urbana"
    )
    attributes = await service.required_attributes(
        seller_id="111", account_id="MLM-1", category_id="MLM1430"
    )
    preferences = await service.publication_preferences(seller_id="111", account_id="MLM-1")

    assert predictions[0] == {
        "category_id": "MLM1430",
        "category_name": "Camperas",
        "domain_id": "MLM-JACKETS",
    }
    assert [attribute["id"] for attribute in attributes if attribute["required"]] == [
        "BRAND",
        "MODEL",
    ]
    assert preferences["defaults"] == {
        "listing_type": "gold_special",
        "logistics_type": "fulfillment",
        "official_store_id": "store-1",
        "brand": "Zeler",
    }
    assert preferences["listing_types"] == [{"id": "gold_special", "name": "Premium"}]
    assert preferences["shipping_modes"] == [{"type": "fulfillment", "label": "Full"}]
    assert ("GET", "/users/111/shipping_preferences", None) in gateway.calls


@pytest.mark.asyncio
async def test_validation_blocks_missing_gtin_required_attributes_and_invalid_preferences() -> None:
    from zeler_publicador.meli import MeliPublicationService

    db = FakeDb()
    db["publicador_drafts"].docs.append(
        _draft(
            gtin=None,
            attributes={"BRAND": "Zeler"},
            listing_type="gold_pro",
            logistics_type="drop_off",
        )
    )
    service = MeliPublicationService(
        db,
        gateway=_FakeMeliGateway(),
        clock=lambda: datetime(2026, 5, 16, 21, 0, tzinfo=UTC),
    )

    result = await service.validate_and_publish_draft(
        seller_id="111", account_id="MLM-1", draft_id="draft-1", actor_id="operator-1"
    )

    assert result["status"] == "blocked"
    assert result["field_errors"] == [
        {"field": "gtin", "message": "GTIN is required and must be numeric"},
        {"field": "attributes.MODEL", "message": "Modelo is required by category MLM1430"},
        {"field": "listing_type", "message": "gold_pro is not enabled for this account"},
        {"field": "logistics_type", "message": "drop_off is not enabled for this account"},
    ]
    updated = db["publicador_drafts"].docs[0]
    assert updated["status"] == "validation_failed"
    assert updated["process_status"] == "failed"
    assert db["publicador_events"].docs[-1]["operation"] == "draft.validation_blocked"


@pytest.mark.asyncio
async def test_valid_publish_uses_paused_status_zero_stock_and_stores_meli_response() -> None:
    from zeler_publicador.meli import MeliPublicationService

    db = FakeDb()
    db["publicador_drafts"].docs.append(_draft())
    db["publicador_assets"].docs.extend(
        [
            {
                "_id": "asset-1",
                "seller_id": "111",
                "account_id": "MLM-1",
                "owner_id": "draft-1",
                "meli_picture_id": "pic-1",
            },
            {
                "_id": "asset-2",
                "seller_id": "111",
                "account_id": "MLM-1",
                "owner_id": "draft-1",
                "meli_picture_id": "pic-2",
            },
        ]
    )
    gateway = _FakeMeliGateway()
    service = MeliPublicationService(
        db,
        gateway=gateway,
        clock=lambda: datetime(2026, 5, 16, 21, 5, tzinfo=UTC),
    )

    result = await service.validate_and_publish_draft(
        seller_id="111", account_id="MLM-1", draft_id="draft-1", actor_id="operator-2"
    )

    published_call = next(call for call in gateway.calls if call[0:2] == ("POST", "/items"))
    payload = published_call[2]
    assert result["status"] == "published"
    assert payload["status"] == "paused"
    assert payload["available_quantity"] == 0
    assert payload["category_id"] == "MLM1430"
    assert payload["attributes"] == [
        {"id": "BRAND", "value_name": "Zeler"},
        {"id": "MODEL", "value_name": "Urbana"},
        {"id": "GTIN", "value_name": "7501234567890"},
    ]
    assert payload["pictures"] == [{"id": "pic-1"}, {"id": "pic-2"}]
    updated = db["publicador_drafts"].docs[0]
    assert updated["status"] == "published"
    assert updated["process_status"] == "published"
    assert updated["meli_item_id"] == "MLM123"
    assert updated["permalink"] == "https://meli.example/MLM123"
    assert db["publicador_events"].docs[-1]["operation"] == "draft.published"


@pytest.mark.asyncio
async def test_api_process_action_runs_gateway_validation_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = FakeDb()
    db["publicador_drafts"].docs.append(_draft())
    app = FastAPI()
    app.state.mongo_db = db
    app.state.publicador_meli_gateway = _FakeMeliGateway()
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
        response = await client.post(
            "/publicador/publications/draft-1/process?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"actor_id": "operator-1"},
        )

    assert response.status_code == 200
    assert response.json()["process_status"] == "published"
    assert response.json()["meli_item_id"] == "MLM123"


class _FakeMeliGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, path, json))
        if method == "GET" and path.startswith("/sites/MLM/domain_discovery/search"):
            return [
                {
                    "category_id": "MLM1430",
                    "category_name": "Camperas",
                    "domain_id": "MLM-JACKETS",
                }
            ]
        if (method, path) == ("GET", "/categories/MLM1430/attributes"):
            return [
                {"id": "BRAND", "name": "Marca", "tags": {"required": True}},
                {"id": "MODEL", "name": "Modelo", "tags": {"required": True}},
                {"id": "COLOR", "name": "Color", "tags": {}},
            ]
        if (method, path) == ("GET", "/users/111/brands"):
            return [{"name": "Zeler"}]
        if (method, path) == ("GET", "/users/111/stores/search"):
            return [{"id": "store-1", "name": "Tienda Oficial"}]
        if (method, path) == ("GET", "/sites/MLM/listing_types"):
            return [{"id": "gold_special", "name": "Premium"}]
        if (method, path) == ("GET", "/users/111/shipping_preferences"):
            return {"logistics": [{"type": "fulfillment", "label": "Full"}]}
        if (method, path) == ("POST", "/items/validate"):
            return {"status": "ok", "field_errors": []}
        if (method, path) == ("POST", "/items"):
            return {"id": "MLM123", "permalink": "https://meli.example/MLM123"}
        raise AssertionError(f"unexpected gateway call {method} {path}")


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 4 workflow tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 4 workflow tests")


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
        "attributes": {"BRAND": "Zeler", "MODEL": "Urbana"},
        "price": 4500,
        "listing_type": "gold_special",
        "logistics_type": "fulfillment",
        "free_shipping": True,
        "official_store_id": "store-1",
        "approval_status": "approved",
        "process_status": "not_started",
        "status": "generated",
        "errors": [],
        "created_at": datetime(2026, 5, 16, 21, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 16, 21, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    draft.update(overrides)
    return draft


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
