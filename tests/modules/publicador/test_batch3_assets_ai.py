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
async def test_asset_service_validates_image_rules_and_registers_metadata_idempotently() -> None:
    from zeler_publicador.assets import AssetService, ImageUpload, validate_image_batch

    invalid = validate_image_batch(
        [
            ImageUpload(
                filename="tiny.gif",
                content_type="image/gif",
                width=320,
                height=320,
                data=b"raw-binary",
            )
        ],
        flow="individual",
    )
    assert invalid.valid is False
    assert invalid.errors == [
        "individual requires at least 3 images",
        "tiny.gif content_type must be image/jpeg, image/png, or image/webp",
        "tiny.gif resolution must be at least 500x500",
    ]

    db = FakeDb()
    db["publicador_drafts"].docs.append(
        {
            "_id": "draft-1",
            "seller_id": "seller-1",
            "account_id": "MLM-1",
            "sku": "SKU-1",
            "asset_ids": [],
            "updated_at": datetime(2026, 5, 16, 20, 0, tzinfo=UTC),
        }
    )
    service = AssetService(
        db,
        storage=_FakeAssetStore(),
        clock=lambda: datetime(2026, 5, 16, 20, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db['publicador_assets'].docs) + 1}",
    )
    images = [
        ImageUpload(
            filename=f"SKU-1-{index}.jpg",
            content_type="image/jpeg",
            width=800,
            height=800,
            data=f"img-{index}".encode(),
        )
        for index in range(1, 4)
    ]

    first = await service.register_assets(
        seller_id="seller-1",
        account_id="MLM-1",
        owner_type="draft",
        owner_id="draft-1",
        sku="SKU-1",
        images=images,
        actor_id="operator-1",
    )
    second = await service.register_assets(
        seller_id="seller-1",
        account_id="MLM-1",
        owner_type="draft",
        owner_id="draft-1",
        sku="SKU-1",
        images=images,
        actor_id="operator-1",
    )

    assert [asset["_id"] for asset in first] == ["asset-1", "asset-2", "asset-3"]
    assert [asset["_id"] for asset in second] == ["asset-1", "asset-2", "asset-3"]
    assert len(db["publicador_assets"].docs) == 3
    assert (
        db["publicador_assets"].docs[0]["storage_uri"]
        == "fake://seller-1/MLM-1/draft-1/SKU-1-1.jpg"
    )
    assert "data" not in db["publicador_assets"].docs[0]
    assert db["publicador_drafts"].docs[0]["asset_ids"] == ["asset-1", "asset-2", "asset-3"]
    assert db["publicador_events"].docs[-1]["operation"] == "asset.registered"


@pytest.mark.asyncio
async def test_asset_meli_upload_retry_keeps_metadata_and_does_not_duplicate_success() -> None:
    from zeler_publicador.assets import AssetService, ImageUpload

    db = FakeDb()
    gateway = _FlakyPictureGateway()
    service = AssetService(
        db,
        storage=_FakeAssetStore(),
        picture_gateway=gateway,
        clock=lambda: datetime(2026, 5, 16, 20, 5, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db['publicador_assets'].docs) + 1}",
    )
    asset = (
        await service.register_assets(
            seller_id="seller-1",
            account_id="MLM-1",
            owner_type="draft",
            owner_id="draft-1",
            sku="SKU-1",
            images=[
                ImageUpload(
                    filename=f"SKU-1-{index}.jpg",
                    content_type="image/jpeg",
                    width=800,
                    height=800,
                    data=b"raw",
                )
                for index in range(1, 4)
            ],
            actor_id="operator-1",
        )
    )[0]

    failed = await service.upload_to_meli(
        asset_id=asset["_id"], seller_id="seller-1", account_id="MLM-1", actor_id="operator-2"
    )
    retried = await service.upload_to_meli(
        asset_id=asset["_id"], seller_id="seller-1", account_id="MLM-1", actor_id="operator-3"
    )
    repeated = await service.upload_to_meli(
        asset_id=asset["_id"], seller_id="seller-1", account_id="MLM-1", actor_id="operator-4"
    )

    assert failed["status"] == "upload_failed"
    assert failed["errors"] == ["meli_picture_upload_failed"]
    assert retried["status"] == "uploaded"
    assert retried["meli_picture_id"] == "meli-picture-1"
    assert repeated["meli_picture_id"] == "meli-picture-1"
    assert gateway.uploaded_uris == [
        "fake://seller-1/MLM-1/draft-1/SKU-1-1.jpg",
        "fake://seller-1/MLM-1/draft-1/SKU-1-1.jpg",
    ]
    assert [event["operation"] for event in db["publicador_events"].docs[-3:]] == [
        "asset.meli_upload_failed",
        "asset.meli_uploaded",
        "asset.meli_upload_skipped",
    ]


@pytest.mark.asyncio
async def test_ai_generation_resolves_configured_provider_and_audits_redacted_payloads() -> None:
    from zeler_publicador.ai import AIGenerationService, ProviderConfig, StaticGenerationProvider

    db = FakeDb()
    db["publicador_drafts"].docs.append(
        {
            "_id": "draft-1",
            "seller_id": "seller-1",
            "account_id": "MLM-1",
            "source_product": {
                "name": "Campera técnica",
                "access_token": "secret-token",
                "nested": {"refresh_token": "secret-refresh"},
            },
            "generated_listing": {},
            "enrichment_status": "pending",
            "updated_at": datetime(2026, 5, 16, 20, 10, tzinfo=UTC),
        }
    )
    db["publicador_settings"].docs.append(
        {
            "seller_id": "seller-1",
            "account_id": "MLM-1",
            "ai_provider_ref": "zeler-default",
            "ai_config": {
                "provider": "stub-ai",
                "model": "listing-v1",
                "api_secret": "do-not-store",
            },
        }
    )
    provider = StaticGenerationProvider(
        provider="stub-ai",
        generated={"title": "Campera IA", "description": "Sin usar token secret-token"},
    )
    service = AIGenerationService(
        db,
        providers={"stub-ai": provider},
        platform_default=ProviderConfig(provider="fallback-ai", model="fallback"),
        clock=lambda: datetime(2026, 5, 16, 20, 10, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-1",
    )

    result = await service.generate_for_draft(
        seller_id="seller-1",
        account_id="MLM-1",
        draft_id="draft-1",
        operation="description",
        prompt_inputs={"operator_note": "usar tono premium", "authorization": "Bearer hidden"},
        actor_id="operator-1",
    )

    audit = db["publicador_ai_generations"].docs[0]
    updated_draft = db["publicador_drafts"].docs[0]
    assert result["provider"] == "stub-ai"
    assert provider.requests[0].config.model == "listing-v1"
    assert updated_draft["generated_listing"]["title"] == "Campera IA"
    assert updated_draft["enrichment_status"] == "generated"
    assert audit["provider"] == "stub-ai"
    assert audit["model"] == "listing-v1"
    assert audit["config_fingerprint"] != "do-not-store"
    assert audit["redacted_input"]["source_product"]["access_token"] == "[REDACTED]"  # noqa: S105
    assert audit["redacted_input"]["source_product"]["nested"]["refresh_token"] == "[REDACTED]"  # noqa: S105
    assert audit["redacted_input"]["prompt_inputs"]["authorization"] == "[REDACTED]"
    assert audit["redacted_output"]["description"] == "Sin usar token [REDACTED]"
    assert audit["retention_until"] > audit["created_at"]


@pytest.mark.asyncio
async def test_publicador_assets_and_ai_api_contracts_persist_batch3_foundations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = FakeDb()
    db["publicador_drafts"].docs.append(
        {
            "_id": "draft-1",
            "seller_id": "111",
            "account_id": "MLM-1",
            "sku": "SKU-1",
            "asset_ids": [],
            "source_product": {"name": "Campera"},
            "generated_listing": {},
            "enrichment_status": "pending",
            "updated_at": datetime(2026, 5, 16, 20, 15, tzinfo=UTC),
        }
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
            token_type="module_admin",  # noqa: S106 - test fixture token type, not a secret
            scopes=["admin:publicador"],
            issued_by="zeler-app",
        )

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assets = await client.post(
            "/publicador/assets",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "owner_type": "draft",
                "owner_id": "draft-1",
                "sku": "SKU-1",
                "images": [
                    {
                        "filename": f"SKU-1-{index}.jpg",
                        "content_type": "image/jpeg",
                        "width": 800,
                        "height": 800,
                        "data_base64": "cmF3",
                    }
                    for index in range(1, 4)
                ],
                "created_by": "operator-1",
            },
        )
        ai = await client.post(
            "/publicador/ai/generate",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "draft_id": "draft-1",
                "operation": "title",
                "prompt_inputs": {"access_token": "hidden"},
                "actor_id": "operator-2",
            },
        )

    assert assets.status_code == 201
    assert [asset["status"] for asset in assets.json()["assets"]] == [
        "registered",
        "registered",
        "registered",
    ]
    assert ai.status_code == 503
    assert ai.json() == {"code": "llm_not_configured"}


class _FakeAssetStore:
    async def store(self, *, seller_id: str, account_id: str, owner_id: str, image: Any) -> str:
        return f"fake://{seller_id}/{account_id}/{owner_id}/{image.filename}"


class _FlakyPictureGateway:
    def __init__(self) -> None:
        self.uploaded_uris: list[str] = []

    async def upload_picture(self, storage_uri: str) -> str:
        self.uploaded_uris.append(storage_uri)
        if len(self.uploaded_uris) == 1:
            raise RuntimeError("gateway unavailable")
        return "meli-picture-1"


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 3 tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 3 tests")


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
