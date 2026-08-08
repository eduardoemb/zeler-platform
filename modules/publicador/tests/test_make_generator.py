from __future__ import annotations

from typing import Any

import pytest

from zeler_publicador.ai import AIGenerationService, ProviderConfig, PublicadorConfigError
from zeler_publicador.app import select_listing_generator
from zeler_publicador.generator import ListingGenerator, LLMNotConfiguredError, ProductInfo


@pytest.mark.asyncio
async def test_select_listing_generator_stub_returns_503_stub_contract() -> None:
    generator = select_listing_generator("stub")

    assert isinstance(generator, ListingGenerator)
    with pytest.raises(LLMNotConfiguredError, match="LISTING_LLM"):
        await generator.generate(ProductInfo(name="Zapatillas", category_id="MLA109027"))


@pytest.mark.asyncio
async def test_select_listing_generator_disabled_returns_503_stub_contract() -> None:
    generator = select_listing_generator("disabled")

    assert isinstance(generator, ListingGenerator)
    with pytest.raises(LLMNotConfiguredError, match="LISTING_LLM"):
        await generator.generate(ProductInfo(name="Zapatillas", category_id="MLA109027"))


def test_select_listing_generator_rejects_unknown_provider() -> None:
    with pytest.raises(PublicadorConfigError, match="LISTING_LLM"):
        select_listing_generator("openai")


def test_select_listing_generator_rejects_uppercase_variant() -> None:
    with pytest.raises(PublicadorConfigError, match="LISTING_LLM"):
        select_listing_generator("OpenAI")


def test_select_listing_generator_defaults_to_stub_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTING_LLM", raising=False)

    generator = select_listing_generator()

    assert isinstance(generator, ListingGenerator)


def test_select_listing_generator_reads_legal_value_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LISTING_LLM", "disabled")

    generator = select_listing_generator()

    assert isinstance(generator, ListingGenerator)


def test_build_app_rejects_invalid_listing_llm_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_publicador.app import build_app

    monkeypatch.setenv("LISTING_LLM", "openai")

    with pytest.raises(PublicadorConfigError, match="LISTING_LLM"):
        build_app(mongo_db=object())


class _FakeCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.documents:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None


class _FakeDb:
    def __init__(self, draft: dict[str, Any]) -> None:
        self.collections = {
            "publicador_drafts": _FakeCollection([draft]),
            "publicador_settings": _FakeCollection(),
        }

    def __getitem__(self, name: str) -> _FakeCollection:
        return self.collections[name]


@pytest.mark.asyncio
async def test_ai_service_raises_publicador_config_error_when_provider_absent() -> None:
    db = _FakeDb(
        {
            "_id": "draft-1",
            "seller_id": "seller-1",
            "account_id": "account-1",
            "source_product": {"name": "Campera"},
            "generated_listing": {},
        }
    )
    service = AIGenerationService(
        db,
        providers={},
        platform_default=ProviderConfig(provider="stub", model="disabled"),
    )

    with pytest.raises(PublicadorConfigError, match="provider"):
        await service.generate_for_draft(
            seller_id="seller-1",
            account_id="account-1",
            draft_id="draft-1",
            operation="title",
            actor_id="operator-1",
        )
