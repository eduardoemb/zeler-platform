from __future__ import annotations

import pytest


class FakeListingLLM:
    def __init__(self) -> None:
        self.prompts: list[dict[str, object]] = []

    async def generate(self, prompt: dict[str, object]) -> dict[str, object]:
        self.prompts.append(prompt)
        return {
            "title": "Zapatillas urbanas livianas",
            "description": "Zapatillas de lona con suela flexible para uso diario.",
            "attributes": {"BRAND": "Zeler", "COLOR": "Negro"},
        }


@pytest.mark.asyncio
async def test_generates_listing_from_product_info_with_mock_llm() -> None:
    from zeler_publicador.generator import ListingGenerator, ProductInfo

    llm = FakeListingLLM()
    generator = ListingGenerator(llm=llm)

    listing = await generator.generate(
        ProductInfo(
            name="Zapatillas urbanas",
            category_id="MLA109027",
            brand="Zeler",
            features=["lona", "suela flexible"],
        )
    )

    assert listing.title == "Zapatillas urbanas livianas"
    assert listing.description == "Zapatillas de lona con suela flexible para uso diario."
    assert listing.attributes == {"BRAND": "Zeler", "COLOR": "Negro"}
    assert llm.prompts == [
        {
            "name": "Zapatillas urbanas",
            "category_id": "MLA109027",
            "brand": "Zeler",
            "features": ["lona", "suela flexible"],
        }
    ]


@pytest.mark.asyncio
async def test_rejects_empty_llm_listing_title() -> None:
    from zeler_publicador.generator import ListingGenerationError, ListingGenerator, ProductInfo

    class EmptyTitleLLM:
        async def generate(self, _prompt: dict[str, object]) -> dict[str, object]:
            return {"title": "", "description": "Detalle suficiente", "attributes": {}}

    generator = ListingGenerator(llm=EmptyTitleLLM())

    with pytest.raises(ListingGenerationError, match="title"):
        await generator.generate(
            ProductInfo(name="Producto", category_id="MLA1", brand=None, features=[])
        )
