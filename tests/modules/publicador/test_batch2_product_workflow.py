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
async def test_repository_edits_rejects_approves_and_processes_draft_with_events() -> None:
    from zeler_publicador.repos import PublicadorRepository
    from zeler_publicador.schemas import DraftCreate, DraftUpdate

    db = FakeDb()
    repo = PublicadorRepository(
        db,
        clock=lambda: datetime(2026, 5, 16, 19, 5, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-1",
    )
    draft = await repo.create_draft(
        DraftCreate(
            seller_id="seller-1",
            account_id="account-1",
            sku="SKU-1",
            title="Campera",
            price=4500,
            created_by="operator-1",
        )
    )

    edited = await repo.update_draft(
        draft_id=draft.id,
        seller_id="seller-1",
        account_id="account-1",
        update=DraftUpdate(title="Campera premium", price=4990),
        actor_id="operator-2",
    )
    rejected = await repo.transition_draft(
        draft_id=draft.id,
        seller_id="seller-1",
        account_id="account-1",
        action="reject",
        actor_id="operator-3",
        reason="Falta GTIN",
    )
    approved = await repo.transition_draft(
        draft_id=draft.id,
        seller_id="seller-1",
        account_id="account-1",
        action="approve",
        actor_id="operator-4",
    )
    processing = await repo.transition_draft(
        draft_id=draft.id,
        seller_id="seller-1",
        account_id="account-1",
        action="process",
        actor_id="operator-5",
    )

    assert edited is not None
    assert edited["title"] == "Campera premium"
    assert edited["source_product"]["price"] == 4990
    assert rejected is not None
    assert rejected["approval_status"] == "rejected"
    assert rejected["rejection_reason"] == "Falta GTIN"
    assert approved is not None
    assert approved["approval_status"] == "approved"
    assert processing is not None
    assert processing["process_status"] == "processing"
    assert [event["operation"] for event in db["publicador_events"].docs] == [
        "draft.created",
        "draft.updated",
        "draft.rejected",
        "draft.approved",
        "draft.process_requested",
    ]
    assert db["publicador_events"].docs[-1]["actor_id"] == "operator-5"


@pytest.mark.asyncio
async def test_api_publications_lifecycle_is_seller_account_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    app = FastAPI()
    app.state.mongo_db = FakeDb()
    app.include_router(
        build_router(
            generator=_FakeGenerator(),
            publisher=_FakePublisher(),
            clock=lambda: datetime(2026, 5, 16, 19, 15, tzinfo=UTC),
        )
    )

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
        created = await client.post(
            "/publicador/drafts",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "sku": "SKU-1",
                "title": "Campera",
                "price": 4500,
                "created_by": "user-1",
            },
        )
        draft_id = created.json()["draft_id"]
        patched = await client.patch(
            f"/publicador/drafts/{draft_id}?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"title": "Campera premium", "price": 4990, "updated_by": "user-2"},
        )
        approved = await client.post(
            f"/publicador/publications/{draft_id}/approve?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"actor_id": "user-3"},
        )
        processed = await client.post(
            f"/publicador/publications/{draft_id}/process?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"actor_id": "user-4"},
        )
        visible = await client.get(
            "/publicador/publications?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
        )
        hidden = await client.get(
            f"/publicador/publications/{draft_id}?seller_id=111&account_id=MLM-2",
            headers={"Authorization": "Bearer valid"},
        )

    assert created.status_code == 201
    assert patched.status_code == 200
    assert patched.json()["title"] == "Campera premium"
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"
    assert processed.status_code == 200
    assert processed.json()["process_status"] == "processing"
    assert [publication["_id"] for publication in visible.json()] == [draft_id]
    assert visible.json()[0]["history"][-1]["operation"] == "draft.process_requested"
    assert hidden.status_code == 404
    assert hidden.json()["error"] == "publicador_publication_not_found"


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 2 workflow tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 2 workflow tests")


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
