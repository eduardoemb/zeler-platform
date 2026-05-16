from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

DraftStatus = Literal["draft", "generated", "validation_failed", "published", "failed"]
EnrichmentStatus = Literal["pending", "generated", "failed"]
ApprovalStatus = Literal["draft", "pending", "approved", "rejected"]
ProcessStatus = Literal["not_started", "processing", "published", "failed"]


class ScopedRequest(BaseModel):
    seller_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)


class DraftCreate(ScopedRequest):
    sku: str = Field(min_length=1)
    gtin: str | None = None
    title: str = Field(min_length=1)
    family_name: str | None = None
    description: str | None = None
    category_id: str | None = None
    domain_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    price: float | None = Field(default=None, gt=0)
    logistics_type: str | None = None
    listing_type: str | None = None
    free_shipping: bool = False
    official_store_id: str | None = None
    brand: str | None = None
    catalog_product_id: str | None = None
    warranty: str | None = None
    created_by: str = Field(min_length=1)


class DraftUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1)
    gtin: str | None = None
    title: str | None = Field(default=None, min_length=1)
    family_name: str | None = None
    description: str | None = None
    category_id: str | None = None
    domain_id: str | None = None
    attributes: dict[str, Any] | None = None
    price: float | None = Field(default=None, gt=0)
    logistics_type: str | None = None
    listing_type: str | None = None
    free_shipping: bool | None = None
    official_store_id: str | None = None
    brand: str | None = None
    catalog_product_id: str | None = None
    warranty: str | None = None
    updated_by: str = "module-admin"


class PublicationAction(BaseModel):
    actor_id: str = "module-admin"
    reason: str | None = None


class DraftRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    seller_id: str
    account_id: str
    sku: str | None = None
    status: DraftStatus
    enrichment_status: EnrichmentStatus = "pending"
    approval_status: ApprovalStatus = "draft"
    process_status: ProcessStatus = "not_started"
    source_product: dict[str, Any] = Field(default_factory=dict)
    generated_listing: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None
    schema_version: int = SCHEMA_VERSION


class DashboardSummary(ScopedRequest):
    drafts: int = 0
    pending_approval: int = 0
    batches: int = 0
    suggestions: int = 0
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)


class PublicationSummary(ScopedRequest):
    id: str
    sku: str | None = None
    status: str
    updated_at: datetime | None = None


class AssetCreate(ScopedRequest):
    owner_type: Literal["draft", "batch_item", "suggestion"]
    owner_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    hash: str | None = None


class AssetImagePayload(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    data_base64: str = Field(min_length=1)


class AssetRegisterRequest(ScopedRequest):
    owner_type: Literal["draft", "batch_item", "suggestion"]
    owner_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    images: list[AssetImagePayload] = Field(min_length=1)
    created_by: str = "module-admin"


class BatchCreate(ScopedRequest):
    source_filename: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class BatchUploadRequest(ScopedRequest):
    source_filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class BatchActionRequest(BaseModel):
    actor_id: str = "module-admin"


class SuggestionCreate(ScopedRequest):
    draft_id: str | None = None
    batch_item_id: str | None = None
    catalog_product_id: str | None = None
    actor_id: str = "module-admin"


class CatalogLinkPublishRequest(ScopedRequest):
    catalog_product_id: str = Field(min_length=1)
    actor_id: str = "module-admin"


class CatalogSuggestionNotification(ScopedRequest):
    suggestion_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    catalog_product_id: str | None = None


class AiGenerateRequest(ScopedRequest):
    draft_id: str = Field(min_length=1)
    operation: Literal["title", "description", "category", "attributes", "family"]
    prompt_inputs: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = "module-admin"


class PublicadorSettings(ScopedRequest):
    defaults: dict[str, Any] = Field(default_factory=dict)
    ai_provider_ref: str | None = None
    catalog_behavior: Literal["search_first", "suggest_when_unmatched", "manual_only"] = (
        "search_first"
    )
    updated_by: str | None = None
    schema_version: int = SCHEMA_VERSION


class ContractAccepted(BaseModel):
    status: Literal["contract_stub"] = "contract_stub"
    seller_id: str
    account_id: str
