from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesOperationContext,
    guarded_devoluciones_write,
)
from zeler_platform_core.models import Claim, current_schema_version


class ClaimProjectionError(RuntimeError):
    pass


def build_claim_projection(
    *,
    seller_id: str,
    claim: Mapping[str, Any],
    returns: Mapping[str, Any],
    order: Mapping[str, Any],
) -> dict[str, Any]:
    seller_id = str(seller_id)
    _validate_claim_respondent(claim, seller_id=seller_id)
    _validate_order_seller(order, seller_id=seller_id)
    return_subtype = _optional_text(returns.get("subtype"))
    return_rows = returns.get("orders")
    if return_subtype == "low_cost" and "orders" in returns and return_rows is None:
        return_rows = []
    if not isinstance(return_rows, list):
        raise ClaimProjectionError("v2 returns orders must be a list")

    order_id = _identity(claim.get("order_id") or claim.get("resource_id"), "order_id")
    item_id = _optional_identity(claim.get("item_id"))
    matching_rows = [
        row
        for row in return_rows
        if isinstance(row, Mapping)
        and _optional_identity(row.get("order_id")) == order_id
        and (item_id is None or _optional_identity(row.get("item_id")) == item_id)
    ]

    return_context_type: str | None = None
    if not matching_rows and return_subtype == "low_cost" and not return_rows:
        productive = False
        returned_quantity = None
        return_quantity_basis = "verified_low_cost_no_row"
    else:
        if len(matching_rows) != 1:
            raise ClaimProjectionError("v2 returns must contain one unique order/item row")
        row = matching_rows[0]
        item_id = _identity(row.get("item_id"), "item_id")
        _validate_order_item(order, item_id=item_id)
        returned_quantity = _positive_integral_return_quantity(row.get("return_quantity"))
        productive = True
        return_quantity_basis = "v2_return_order"
        return_context_type = _optional_text(row.get("context_type"))

    claim_type = str(claim.get("type") or "")
    if claim_type not in {"return", "returns", "mediations"}:
        raise ClaimProjectionError("claim is not a return or return-linked mediation")
    if claim_type == "mediations" and not _has_related_return(claim):
        raise ClaimProjectionError("mediation is not linked to a return")

    model_payload: dict[str, Any] = {
        "_id": _identity(claim.get("id") or claim.get("_id"), "claim_id"),
        "seller_id": seller_id,
        "buyer_id": _claim_buyer_id(claim),
        "item_id": item_id,
        "order_id": order_id,
        "returned_quantity": returned_quantity,
        "claim_version": _optional_integer(claim.get("claim_version"), "claim_version"),
        "last_updated": _optional_datetime(claim.get("last_updated"), "last_updated"),
        "return_id": _optional_identity(returns.get("id")),
        "return_last_updated": _optional_datetime(
            returns.get("last_updated"), "return_last_updated"
        ),
        "return_status": _optional_text(returns.get("status")),
        "return_subtype": return_subtype,
        "return_context_type": return_context_type,
        "return_quantity_basis": return_quantity_basis,
        "productive": productive,
        "status": claim.get("status"),
        "stage": claim.get("stage") or "none",
        "type": "returns",
        "date_created": claim.get("date_created"),
        "resolution": claim.get("resolution"),
        "schema_version": current_schema_version("claims"),
    }
    model = Claim.model_validate(model_payload)
    return model.model_dump(by_alias=True, mode="python", exclude_none=True)


async def project_claim(
    *,
    db: Any,
    seller_id: str,
    claim: Mapping[str, Any],
    returns: Mapping[str, Any],
    order: Mapping[str, Any],
    operation: DevolucionesOperationContext,
) -> dict[str, Any]:
    document = build_claim_projection(
        seller_id=seller_id,
        claim=claim,
        returns=returns,
        order=order,
    )

    await persist_claim_projection(db=db, document=document, operation=operation)
    return document


async def persist_claim_projection(
    *,
    db: Any,
    document: Mapping[str, Any],
    operation: DevolucionesOperationContext,
) -> None:
    seller_id = str(document["seller_id"])
    claim_id = str(document["_id"])
    claim_version = document.get("claim_version")
    last_updated = document.get("last_updated")
    return_last_updated = document.get("return_last_updated")
    if isinstance(claim_version, bool) or not isinstance(claim_version, int):
        raise ClaimProjectionError("claim_version is required for monotonic persistence")
    if not isinstance(last_updated, datetime):
        raise ClaimProjectionError("last_updated is required for monotonic persistence")
    if not isinstance(return_last_updated, datetime):
        raise ClaimProjectionError("return_last_updated is required for monotonic persistence")

    async def write(session: Any) -> None:
        collection = db["claims"]
        session_kwargs = {"session": session} if session is not None else {}
        insert_result = await collection.update_one(
            {"_id": claim_id, "seller_id": seller_id},
            {"$setOnInsert": dict(document)},
            upsert=True,
            **session_kwargs,
        )
        if getattr(insert_result, "upserted_id", None) is not None:
            return
        await collection.replace_one(
            _monotonic_claim_write_filter(
                claim_id=claim_id,
                seller_id=seller_id,
                claim_version=claim_version,
                last_updated=last_updated,
                return_last_updated=return_last_updated,
            ),
            dict(document),
            upsert=False,
            **session_kwargs,
        )

    await guarded_devoluciones_write(
        db=db,
        operation=operation,
        seller_id=seller_id,
        checkpoint={
            "claim_id": claim_id,
            "claim_version": document.get("claim_version"),
            "last_updated": document.get("last_updated"),
        },
        writer=write,
    )


def _monotonic_claim_write_filter(
    *,
    claim_id: str,
    seller_id: str,
    claim_version: int,
    last_updated: datetime,
    return_last_updated: datetime,
) -> dict[str, Any]:
    return {
        "_id": claim_id,
        "seller_id": seller_id,
        "$and": [
            {
                "$or": [
                    {"claim_version": {"$exists": False}},
                    {"claim_version": {"$lt": claim_version}},
                    {
                        "$and": [
                            {"claim_version": claim_version},
                            {
                                "$or": [
                                    {"last_updated": {"$exists": False}},
                                    {"last_updated": {"$lte": last_updated}},
                                ]
                            },
                        ]
                    },
                ]
            },
            {
                "$or": [
                    {"return_last_updated": {"$exists": False}},
                    {"return_last_updated": {"$lte": return_last_updated}},
                ]
            },
        ],
    }


def _validate_claim_respondent(claim: Mapping[str, Any], *, seller_id: str) -> None:
    players = claim.get("players")
    matches = (
        [
            player
            for player in players
            if isinstance(player, Mapping)
            and str(player.get("user_id")) == seller_id
            and player.get("role") == "respondent"
            and player.get("type") == "seller"
        ]
        if isinstance(players, list)
        else []
    )
    if len(matches) != 1:
        raise ClaimProjectionError("claim must have exactly one seller respondent")


def _validate_order_seller(order: Mapping[str, Any], *, seller_id: str) -> None:
    seller = order.get("seller")
    order_seller_id = seller.get("id") if isinstance(seller, Mapping) else order.get("seller_id")
    if str(order_seller_id) != seller_id:
        raise ClaimProjectionError("order seller does not match operation seller")


def _validate_order_item(order: Mapping[str, Any], *, item_id: str) -> None:
    items = order.get("items") or order.get("order_items")
    if not isinstance(items, list):
        raise ClaimProjectionError("order items are unavailable")
    matches = []
    for row in items:
        if not isinstance(row, Mapping):
            continue
        item = row.get("item")
        row_item_id = item.get("id") if isinstance(item, Mapping) else row.get("item_id")
        if str(row_item_id) == item_id:
            matches.append(row)
    if len(matches) != 1:
        raise ClaimProjectionError("order must contain one unique matching item row")


def _positive_integral_return_quantity(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ClaimProjectionError("return_quantity must be a positive integral value")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ClaimProjectionError("return_quantity must be a positive integral value") from exc
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise ClaimProjectionError("return_quantity must be a positive integral value")
    return int(quantity)


def _has_related_return(claim: Mapping[str, Any]) -> bool:
    related = claim.get("related_entities")
    return isinstance(related, Sequence) and any(
        isinstance(entity, Mapping) and entity.get("type") == "return" for entity in related
    )


def _claim_buyer_id(claim: Mapping[str, Any]) -> str | None:
    direct = _optional_identity(claim.get("buyer_id"))
    if direct is not None:
        return direct
    players = claim.get("players")
    if not isinstance(players, list):
        return None
    for player in players:
        if isinstance(player, Mapping) and player.get("type") == "buyer":
            return _optional_identity(player.get("user_id"))
    return None


def _identity(value: Any, field: str) -> str:
    normalized = _optional_identity(value)
    if normalized is None:
        raise ClaimProjectionError(f"{field} is required")
    return normalized


def _optional_identity(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_text(value: Any) -> str | None:
    return _optional_identity(value)


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ClaimProjectionError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ClaimProjectionError(f"{field} must be an integer") from exc


def _optional_datetime(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClaimProjectionError(f"{field} must be an ISO datetime") from exc
    else:
        raise ClaimProjectionError(f"{field} must be an ISO datetime")
    if parsed.tzinfo is None:
        raise ClaimProjectionError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)
