from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModuleDisplayIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    display_name: str = Field(min_length=1)
    legacy_display_name: str | None = None
    availability: Literal["active", "retired"]


_ACTIVE_MODULE_DISPLAY_IDENTITIES: dict[str, ModuleDisplayIdentity] = {
    "sheets": ModuleDisplayIdentity(
        display_name="ZelerData",
        legacy_display_name="SheetsellerApp",
        availability="active",
    ),
    "repricer": ModuleDisplayIdentity(
        display_name="ZelerPricing",
        legacy_display_name="EasyReprice",
        availability="active",
    ),
    "publicador": ModuleDisplayIdentity(
        display_name="ZelerListings",
        legacy_display_name="Autopubli",
        availability="active",
    ),
    "autoreply": ModuleDisplayIdentity(
        display_name="ZelerSupport",
        legacy_display_name="AutoReply",
        availability="active",
    ),
}

_RETIRED_MODULE_DISPLAY_IDENTITIES: dict[str, ModuleDisplayIdentity] = {
    "fulldock": ModuleDisplayIdentity(
        display_name="ZelerStock",
        legacy_display_name="FullDockManager",
        availability="retired",
    ),
}


def active_module_display_identities() -> dict[str, ModuleDisplayIdentity]:
    return dict(_ACTIVE_MODULE_DISPLAY_IDENTITIES)


def retired_module_display_identities() -> dict[str, ModuleDisplayIdentity]:
    return dict(_RETIRED_MODULE_DISPLAY_IDENTITIES)


def resolve_module_display_identity(module_id: str) -> ModuleDisplayIdentity | None:
    return _ACTIVE_MODULE_DISPLAY_IDENTITIES.get(
        module_id
    ) or _RETIRED_MODULE_DISPLAY_IDENTITIES.get(module_id)


def resolve_active_module_display_identity(module_id: str) -> ModuleDisplayIdentity:
    identity = _ACTIVE_MODULE_DISPLAY_IDENTITIES.get(module_id)
    if identity is None:
        raise ValueError(f"active module {module_id!r} has no display identity")
    return identity
