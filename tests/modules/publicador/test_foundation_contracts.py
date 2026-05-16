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
        assert upsert is True
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


@pytest.mark.asyncio
async def test_repository_creates_rich_seller_account_scoped_draft() -> None:
    from zeler_publicador.repos import PublicadorRepository
    from zeler_publicador.schemas import DraftCreate

    db = FakeDb()
    repo = PublicadorRepository(
        db,
        clock=lambda: datetime(2026, 5, 16, 18, 40, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-1",
    )

    draft = await repo.create_draft(
        DraftCreate(
            seller_id="seller-1",
            account_id="account-1",
            sku="SKU-1",
            gtin="7501234567890",
            title="Campera técnica",
            price=4500,
            logistics_type="fulfillment",
            listing_type="gold_special",
            free_shipping=True,
            created_by="operator-1",
        )
    )

    stored = db["publicador_drafts"].docs[0]
    assert draft.id == "draft-1"
    assert stored["seller_id"] == "seller-1"
    assert stored["account_id"] == "account-1"
    assert stored["sku"] == "SKU-1"
    assert stored["enrichment_status"] == "pending"
    assert stored["approval_status"] == "draft"
    assert stored["process_status"] == "not_started"
    assert stored["created_by"] == "operator-1"
    assert stored["schema_version"] == 1


@pytest.mark.asyncio
async def test_api_openapi_exposes_batch1_contract_paths_and_blocks_cross_seller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    app = FastAPI()
    app.state.mongo_db = FakeDb()
    app.include_router(build_router(generator=_FakeGenerator(), publisher=_FakePublisher()))

    openapi = app.openapi()
    assert {
        "/publicador/dashboard",
        "/publicador/drafts",
        "/publicador/publications",
        "/publicador/publications/{publication_id}",
        "/publicador/assets",
        "/publicador/ai/generate",
        "/publicador/batches",
        "/publicador/batches/{batch_id}",
        "/publicador/suggestions",
        "/publicador/logs",
        "/publicador/statistics",
        "/publicador/settings",
    }.issubset(openapi["paths"])
    assert "DraftCreate" in openapi["components"]["schemas"]
    assert "PublicadorSettings" in openapi["components"]["schemas"]

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
        response = await client.get(
            "/publicador/dashboard?seller_id=222&account_id=account-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "JWT seller_id must match request seller_id"


@pytest.mark.asyncio
async def test_api_list_drafts_filters_by_seller_and_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = FakeDb()
    db["publicador_drafts"].docs.extend(
        [
            {
                "_id": "draft-visible",
                "seller_id": "111",
                "account_id": "account-a",
                "sku": "SKU-1",
                "source_product": {},
                "generated_listing": {},
                "status": "draft",
                "created_at": "2026-05-16T18:00:00Z",
                "updated_at": "2026-05-16T18:00:00Z",
                "schema_version": 1,
            },
            {
                "_id": "draft-hidden-account",
                "seller_id": "111",
                "account_id": "account-b",
                "sku": "SKU-2",
                "source_product": {},
                "generated_listing": {},
                "status": "draft",
                "created_at": "2026-05-16T18:00:00Z",
                "updated_at": "2026-05-16T18:00:00Z",
                "schema_version": 1,
            },
        ]
    )
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
        response = await client.get(
            "/publicador/drafts?seller_id=111&account_id=account-a",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert [draft["_id"] for draft in response.json()] == ["draft-visible"]


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in foundation contract tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in foundation contract tests")


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
