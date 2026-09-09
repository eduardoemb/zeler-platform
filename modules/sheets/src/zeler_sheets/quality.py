"""Normalize owned item performance into the existing quality formula fields."""

from datetime import datetime
from typing import Any

from zeler_platform_core.models.entities import ItemQualityComponent, ItemQualityProjection

QUALITY_SOURCE = "/item/{id}/performance"
_COMPONENTS = {"GTIN": "gtin", "PICTURES": "images", "TITLE": "title", "ME": "shipping"}


def project_item_quality(
    resource: Any, *, item_id: str, observed_at: datetime, user_product_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(resource, dict) or not (
        resource.get("entity_type") == "ITEM"
        and resource.get("entity_id") == item_id
        or resource.get("entity_type") == "USER_PRODUCT"
        and user_product_id is not None
        and resource.get("entity_id") == user_product_id
    ):
        raise ValueError("quality source identity mismatch")
    buckets = resource.get("buckets")
    if not isinstance(buckets, list) or len(buckets) > 100:
        raise ValueError("quality buckets unavailable")
    components: dict[str, dict[str, Any]] = {}
    actions: set[str] = set()
    for bucket in buckets:
        variables = bucket.get("variables") if isinstance(bucket, dict) else None
        if not isinstance(variables, list) or len(variables) > 100:
            raise ValueError("quality variables unavailable")
        for variable in variables:
            if not isinstance(variable, dict) or not isinstance(variable.get("key"), str):
                raise ValueError("quality variable malformed")
            name = _COMPONENTS.get(variable["key"].removeprefix("UP_"))
            if name:
                component = ItemQualityComponent.model_validate(
                    {"status": variable.get("status"), "score": variable.get("score")}
                ).model_dump()
                if name in components and components[name] != component:
                    raise ValueError("conflicting quality components")
                components[name] = component
            rules = variable.get("rules")
            if not isinstance(rules, list) or len(rules) > 100:
                raise ValueError("quality rules unavailable")
            for rule in rules:
                if not isinstance(rule, dict) or rule.get("status") not in {"PENDING", "COMPLETED"}:
                    raise ValueError("quality rule malformed")
                if rule["status"] == "PENDING":
                    key = rule.get("key")
                    if not isinstance(key, str) or not key.strip() or len(key) > 128:
                        raise ValueError("quality action malformed")
                    actions.add(key)
    return ItemQualityProjection.model_validate(
        {
            "source": QUALITY_SOURCE,
            "entity_type": resource["entity_type"],
            "entity_id": resource["entity_id"],
            "item_id": item_id,
            "score": resource.get("score"),
            "level": resource.get("level"),
            "calculated_at": resource.get("calculated_at"),
            "observed_at": observed_at,
            "components": components,
            "pending_actions": sorted(actions),
        }
    ).model_dump(mode="python")
