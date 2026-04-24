from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ListingGenerationError(ValueError):
    """Raised when the LLM returns an unusable listing draft."""


class ProductInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    category_id: str = Field(min_length=1)
    brand: str | None = None
    features: list[str] = Field(default_factory=list)


class GeneratedListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    attributes: dict[str, str] = Field(default_factory=dict)


class ListingLLM(Protocol):
    async def generate(self, prompt: dict[str, object]) -> dict[str, object]: ...


class ListingGenerator:
    def __init__(self, *, llm: ListingLLM) -> None:
        self._llm = llm

    async def generate(self, product: ProductInfo) -> GeneratedListing:
        raw_listing = await self._llm.generate(
            {
                "name": product.name,
                "category_id": product.category_id,
                "brand": product.brand,
                "features": product.features,
            }
        )
        try:
            return GeneratedListing.model_validate(raw_listing)
        except ValueError as exc:
            raise ListingGenerationError(str(exc)) from exc
