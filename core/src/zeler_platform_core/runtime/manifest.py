from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from zeler_platform_core.runtime.module_identity import (
    ModuleDisplayIdentity,
    resolve_active_module_display_identity,
)

GATEWAY_OWNED_COLLECTIONS = frozenset(
    {
        "meli_accounts",
        "users",
        "items",
        "orders",
        "questions",
        "messages",
        "shipments",
        "claims",
        "events",
        "webhook_events",
        "audit_log",
        "bootstrap_jobs",
        "module_registry",
        "processed_events",
        "rate_limit_counters",
        "competition_snapshots",
        "stock_locations",
    }
)


class ManifestConflictError(ValueError):
    """Raised when a module manifest violates platform ownership boundaries."""


class PassiveConsumer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_name: str = Field(min_length=1)
    routing_keys: list[str] = Field(min_length=1)
    externally_bound: bool = True

    @field_validator("routing_keys")
    @classmethod
    def _routing_keys_must_be_non_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("passive consumer routing keys must be non-blank strings")
        return value


class ModuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    subscribed_events: list[str] = Field(default_factory=list)
    passive_consumers: list[PassiveConsumer] = Field(default_factory=list)
    owned_collections: list[str] = Field(min_length=1)
    allowed_meli_scopes: list[str] = Field(min_length=1)
    health_endpoint: str = Field(min_length=1)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._raise_for_missing_display_identity()
        self._raise_for_owned_collection_collisions()

    @property
    def module_id(self) -> str:
        return self.name

    @property
    def routing_keys(self) -> list[str]:
        passive_keys = (
            routing_key
            for consumer in self.passive_consumers
            for routing_key in consumer.routing_keys
        )
        return list(dict.fromkeys([*self.subscribed_events, *passive_keys]))

    @property
    def active_routing_keys(self) -> list[str]:
        return list(dict.fromkeys(self.subscribed_events))

    @property
    def display_identity(self) -> ModuleDisplayIdentity:
        return resolve_active_module_display_identity(self.module_id)

    @field_validator("health_endpoint")
    @classmethod
    def _health_endpoint_must_be_absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("health_endpoint must start with /")
        return value

    @field_validator("subscribed_events", "owned_collections", "allowed_meli_scopes")
    @classmethod
    def _list_values_must_be_non_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("manifest list values must be non-blank strings")
        return value

    def _raise_for_owned_collection_collisions(self) -> None:
        collisions = sorted(set(self.owned_collections) & GATEWAY_OWNED_COLLECTIONS)
        if collisions:
            joined = ", ".join(collisions)
            raise ManifestConflictError(
                f"owned_collections collide with platform-owned collections: {joined}"
            )

    def _raise_for_missing_display_identity(self) -> None:
        resolve_active_module_display_identity(self.module_id)


def validate_manifest(path: str | Path) -> ModuleManifest:
    manifest_path = Path(path)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("module manifest must be a mapping")
    return ModuleManifest.model_validate(raw)
