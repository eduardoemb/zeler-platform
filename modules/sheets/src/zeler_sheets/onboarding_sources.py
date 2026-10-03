"""Bounded, resumable, read-only upstream collectors for account onboarding.

Official contracts checked 2026-10-02:
https://developers.mercadolibre.com.mx/es_ar/mensajeria-post-venta
https://developers.mercadolibre.com.mx/es_mx/envios-fulfillment

Full search requires inventory_id alongside seller/date filters; bounded owned
canonical item selection supplies it without provider catalog lookups. A
five-minute scroll (the same token can continue across pages) supports up to
1000 rows; date_to excludes that day. Its documented
operations do not supply legacy withdrawal/detail IDs or original requested
quantity. Retain authentic operations, but never claim they satisfy RETIROS or
overwrite legacy withdrawals. Operation retention is not documented by the
twelve-month stock note. Messages use offset/limit and never mark anything read.
Caller owns durable checkpoint persistence, leases and account eligibility.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from zeler_platform_core.models import Message
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError, recovery_fetch_resource

FULL_OPERATIONS_COLLECTION = "sheets_full_operations"
WITHDRAWAL_TYPES = frozenset(
    {
        "WITHDRAWAL_RESERVATION",
        "WITHDRAWAL_CANCELATION",
        "WITHDRAWAL_DELIVERY",
        "WITHDRAWAL_REMOVAL",
        "WITHDRAWAL_DISCARDED",
    }
)
_MAX_PENDING = 128
_FULL_SEARCH_TYPES = (
    "WITHDRAWAL_RESERVATION",
    "WITHDRAWAL_CANCELATION",
    "WITHDRAWAL_DELIVERY",
    "WITHDRAWAL_REMOVAL",
    "WITHDRAWAL_DISCARDED",
)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("an aware timestamp is required")
    return value.astimezone(UTC)


def _identifier(value: Any) -> str:
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not text or len(text) > 128 or "/" in text:
        raise ValueError("invalid source identity")
    return text


def _safe_identifier(value: Any) -> str | None:
    try:
        return _identifier(value)
    except ValueError:
        return None


def _state(
    seller_id: str,
    start: datetime,
    end: datetime,
    source: str,
    checkpoint: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not seller_id.isascii() or not seller_id.isdecimal():
        raise ValueError("numeric seller required")
    if _timestamp(start) >= _timestamp(end):
        raise ValueError("invalid interval")
    identity = {
        "seller_id": seller_id,
        "source": source,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    if checkpoint is not None and any(checkpoint.get(k) != v for k, v in identity.items()):
        raise ValueError("checkpoint identity mismatch")
    state = {
        **identity,
        "target_index": 0,
        "type_index": 0,
        "offset": 0,
        "pending": [],
        "issue_count": 0,
        "persisted": 0,
        "discovery_complete": False,
        **dict(checkpoint or {}),
    }
    state["pending"] = list(state["pending"])
    for field in ("target_index", "type_index", "offset", "issue_count", "persisted"):
        if type(state[field]) is not int or state[field] < 0:
            raise ValueError("invalid checkpoint cursor")
    if len(state["pending"]) > _MAX_PENDING:
        raise ValueError("invalid checkpoint pending budget")
    state.pop("last_error", None)
    return state


def _pending(state: dict[str, Any], code: str, identity: str | None = None) -> None:
    state["issue_count"] += 1
    if len(state["pending"]) < _MAX_PENDING:
        state["pending"].append({"code": code, "id": identity})


def _report(state: dict[str, Any], requests: int, *, blocked: str | None = None) -> dict[str, Any]:
    return {
        "checkpoint": state,
        "requests": requests,
        "persisted": state["persisted"],
        "pending": state["pending"],
        "issue_count": state["issue_count"],
        "discovery_complete": state["discovery_complete"],
        "coverage_complete": state["discovery_complete"]
        and not state["issue_count"]
        and not blocked,
        "blocked_reason": blocked,
    }


async def _upsert(db: Any, collection: str, document: dict[str, Any]) -> bool:
    """Never reassign a globally keyed canonical document to another seller."""
    target = db[collection]
    identity = {"_id": document["_id"]}
    existing = await target.find_one(identity)
    if existing is not None:
        if str(existing.get("seller_id")) != document["seller_id"]:
            return False
        await target.update_one(
            {**identity, "seller_id": existing["seller_id"]},
            {"$set": {k: v for k, v in document.items() if k != "_id"}},
        )
        return True
    try:
        await target.insert_one(document)
    except DuplicateKeyError:
        existing = await target.find_one(identity)
        if existing is None or str(existing.get("seller_id")) != document["seller_id"]:
            return False
        await target.update_one(
            {**identity, "seller_id": existing["seller_id"]},
            {"$set": {k: v for k, v in document.items() if k != "_id"}},
        )
    return True


def _message_document(raw: dict[str, Any], seller: str, pack: str) -> dict[str, Any]:
    dates = raw.get("message_date") or {}
    sender = _identifier((raw.get("from") or {}).get("user_id"))
    recipient = _identifier((raw.get("to") or {}).get("user_id"))
    if seller not in {sender, recipient} or str(raw.get("pack_id", pack)) != pack:
        raise ValueError("message ownership mismatch")
    for resource in raw.get("message_resources") or []:
        expected = {"packs": pack, "sellers": seller}.get(resource.get("name"))
        if expected is not None and str(resource.get("id")) != expected:
            raise ValueError("message resource mismatch")
    text = raw.get("text")
    if isinstance(text, dict):
        text = text.get("plain")
    data = {
        "_id": _identifier(raw.get("id")),
        "seller_id": seller,
        "pack_id": pack,
        "from_user_id": sender,
        "to_user_id": recipient,
        "text": text,
        "status": raw.get("status"),
        "date_created": _timestamp(raw.get("date_created") or dates.get("created")),
        "schema_version": 1,
    }
    if raw.get("order_id") is not None:
        data["order_id"] = _identifier(raw["order_id"])
    if "read_at" in raw or "read" in dates:
        data["read_at"] = raw.get("read_at") or dates.get("read")
    doc = Message.model_validate(data).model_dump(by_alias=True, mode="python")
    # Unknown optional values must not erase previously acquired relationships.
    return {k: v for k, v in doc.items() if v is not None}


async def collect_pack_messages(
    *,
    db: Any,
    gateway: Any,
    seller_id: str,
    targets: Sequence[str],
    start: datetime,
    end: datetime,
    max_requests: int = 1,
    page_size: int = 50,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance bounded pack pages; never send/respond/mark read or report text."""
    if not 1 <= max_requests <= 100 or not 1 <= page_size <= 50:
        raise ValueError("invalid message request budget")
    state = _state(seller_id, start, end, "messages", checkpoint)
    # Freeze this acquisition's inventory: newly discovered packs belong to the
    # next incremental snapshot, never shift an in-flight positional cursor.
    source_targets = state.get("target_ids", targets)
    packs = list(dict.fromkeys(_identifier(pack) for pack in source_targets))
    if len(packs) > 10000:
        raise ValueError("pack inventory exceeds the local 10000-pack batch budget")
    if any(not pack.isascii() or not pack.isdecimal() for pack in packs):
        raise ValueError("numeric pack/order IDs required")
    state["target_ids"] = packs
    requests = 0
    while state["target_index"] < len(packs) and requests < max_requests:
        pack = packs[state["target_index"]]
        offset = state["offset"]
        params = {"tag": "post_sale", "mark_as_read": "false", "limit": page_size, "offset": offset}
        path = f"/messages/packs/{pack}/sellers/{seller_id}?{urlencode(params)}"
        requests += 1
        try:
            page = await recovery_fetch_resource(gateway, seller_id=seller_id, path=path)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {400, 404}:
                _pending(state, f"http_{code}", pack)
                state["target_index"] += 1
                state["offset"] = 0
                continue
            state["last_error"] = f"http_{code}"
            return _report(
                state,
                requests,
                blocked="access_denied" if code in {401, 403} else "source_retry_required",
            )
        except HistoryPolicyWaitError:
            requests -= 1
            state["last_error"] = "policy_wait"
            return _report(state, requests, blocked="policy_wait")
        except ValueError as error:
            if "budget exhausted" not in str(error):
                raise
            # A denied pre-dispatch charge is not a physical request. Preserve
            # any preceding successful page so a small daily quota does not
            # restart the same pack forever at the next UTC day.
            requests -= 1
            reason = (
                "daily_budget_exhausted"
                if getattr(gateway, "incremental", False)
                else "initial_budget_exhausted"
            )
            state["last_error"] = reason
            return _report(state, requests, blocked=reason)
        except (httpx.RequestError, TimeoutError):
            state["last_error"] = "source_retry_required"
            return _report(state, requests, blocked="source_retry_required")
        paging = page.get("paging") if isinstance(page, dict) else None
        rows = page.get("messages") if isinstance(page, dict) else None
        if (
            not isinstance(paging, dict)
            or not isinstance(rows, list)
            or type(paging.get("total")) is not int
            or paging["total"] < 0
            or paging.get("offset", offset) != offset
            or len(rows) > page_size
        ):
            state["last_error"] = "invalid_page"
            return _report(state, requests, blocked="invalid_page")
        for raw in rows:
            try:
                doc = _message_document(raw, seller_id, pack)
            except (ValueError, TypeError, AttributeError, ValidationError):
                _pending(
                    state,
                    "invalid_message",
                    _safe_identifier(raw.get("id")) if isinstance(raw, dict) else None,
                )
                continue
            if not start <= doc["date_created"] < end:
                continue
            if await _upsert(db, "messages", doc):
                state["persisted"] += 1
            else:
                _pending(state, "seller_conflict", doc["_id"])
        next_offset = offset + len(rows)
        if next_offset >= paging["total"]:
            state["target_index"] += 1
            state["offset"] = 0
        elif not rows:
            state["last_error"] = "incomplete_page"
            return _report(state, requests, blocked="incomplete_page")
        else:
            state["offset"] = next_offset
    state["discovery_complete"] = state["target_index"] == len(packs)
    return _report(state, requests)


_FULL_ITEM_PAGE_SIZE = 32
_MAX_FULL_INVENTORIES = 4096


def _item_full_inventories(item: Mapping[str, Any], seller: str) -> list[str]:
    shipping = item.get("shipping")
    if (
        str(item.get("seller_id")) != seller
        or not isinstance(shipping, Mapping)
        or shipping.get("logistic_type") != "fulfillment"
    ):
        return []
    variations = item.get("variations")
    resources = [item, *(variations if isinstance(variations, list) else [])]
    return list(
        dict.fromkeys(
            identity
            for resource in resources
            if isinstance(resource, Mapping)
            and (identity := _safe_identifier(resource.get("inventory_id"))) is not None
        )
    )


def _full_inventory_checkpoint(state: dict[str, Any]) -> None:
    if state.get("inventory_selection_version") != 1:
        # Old checkpoints contain an unfiltered seller-only scroll. It has no
        # inventory authority and must never be reused for a selected inventory.
        state.update(
            inventory_selection_version=1,
            inventory_targets=[],
            inventory_index=0,
            inventory_seen=[],
            inventory_scan_complete=False,
            type_index=0,
            discovery_complete=False,
        )
        for field in ("scroll", "scroll_observed_at", "inventory_item_after"):
            state.pop(field, None)
    targets, seen = state.get("inventory_targets"), state.get("inventory_seen")
    index = state.get("inventory_index")
    if (
        not isinstance(targets, list)
        or len(targets) > _MAX_FULL_INVENTORIES
        or not isinstance(seen, list)
        or len(seen) > _MAX_FULL_INVENTORIES
        or type(index) is not int
        or not 0 <= index <= len(targets)
        or type(state.get("inventory_scan_complete")) is not bool
    ):
        raise ValueError("invalid Full inventory checkpoint")
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"item_id", "inventory_id"}:
            raise ValueError("invalid Full inventory target")
        _identifier(target["item_id"])
        _identifier(target["inventory_id"])
    for identity in seen:
        _identifier(identity)
    if state.get("inventory_item_after") is not None:
        _identifier(state["inventory_item_after"])


async def _select_full_inventory_page(db: Any, state: dict[str, Any]) -> None:
    # One bounded local page per turn, never a provider lookup/catalog rescan.
    query: dict[str, Any] = {
        "seller_id": {"$in": [state["seller_id"], int(state["seller_id"])]},
        "shipping.logistic_type": "fulfillment",
    }
    if state.get("inventory_item_after"):
        query["_id"] = {"$gt": state["inventory_item_after"]}
    rows = (
        await db["items"]
        .find(
            query,
            {
                "_id": 1,
                "seller_id": 1,
                "inventory_id": 1,
                "variations.inventory_id": 1,
                "shipping.logistic_type": 1,
            },
        )
        .sort([("_id", 1)])
        .to_list(length=_FULL_ITEM_PAGE_SIZE + 1)
    )
    state["inventory_scan_complete"] = len(rows) <= _FULL_ITEM_PAGE_SIZE
    targets: list[dict[str, str]] = []
    seen = set(state["inventory_seen"])
    for item in rows[:_FULL_ITEM_PAGE_SIZE]:
        item_id = _identifier(item.get("_id"))
        state["inventory_item_after"] = item_id
        for inventory in _item_full_inventories(item, state["seller_id"]):
            if inventory in seen:
                continue
            if len(seen) == _MAX_FULL_INVENTORIES:
                _pending(state, "inventory_selection_limit")
                state["inventory_scan_complete"] = True
                break
            seen.add(inventory)
            targets.append({"item_id": item_id, "inventory_id": inventory})
    state.update(
        inventory_targets=targets, inventory_index=0, inventory_seen=sorted(seen), type_index=0
    )


def _advance_full_inventory(state: dict[str, Any]) -> None:
    state["inventory_index"] += 1
    state["type_index"] = 0
    state.pop("scroll", None)
    state.pop("scroll_observed_at", None)
    state["discovery_complete"] = (
        state["inventory_index"] == len(state["inventory_targets"])
        and state["inventory_scan_complete"]
    )


async def collect_full_operations(
    *,
    db: Any,
    gateway: Any,
    seller_id: str,
    start: datetime,
    end: datetime,
    max_requests: int = 1,
    page_size: int = 1000,
    checkpoint: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keep real Full withdrawal operation evidence, fail closed for RETIROS."""
    if not 1 <= max_requests <= 100 or not 1 <= page_size <= 1000:
        raise ValueError("invalid Full request budget")
    state = _state(seller_id, start, end, "full_operations", checkpoint)
    if state["type_index"] > len(_FULL_SEARCH_TYPES):
        raise ValueError("invalid Full type cursor")
    _full_inventory_checkpoint(state)
    if state["inventory_index"] == len(state["inventory_targets"]):
        if not state["inventory_scan_complete"]:
            await _select_full_inventory_page(db, state)
        state["discovery_complete"] = (
            state["inventory_index"] == len(state["inventory_targets"])
            and state["inventory_scan_complete"]
        )
        if state["discovery_complete"] or not state["inventory_targets"]:
            return _report(
                state,
                0,
                blocked=(
                    (
                        "full_withdrawal_contract_incompatible"
                        if state["inventory_seen"]
                        else "full_inventory_unavailable"
                    )
                    if state["discovery_complete"]
                    else None
                ),
            )
    clock = _timestamp(now or datetime.now(UTC))
    if state.get("scroll_observed_at") and clock - _timestamp(
        state["scroll_observed_at"]
    ) >= timedelta(minutes=5):
        # Expired scroll restarts the search; idempotent writes preserve prior pages.
        state.pop("scroll", None)
        state.pop("scroll_observed_at", None)
    requests = 0
    while state["inventory_index"] < len(state["inventory_targets"]) and requests < max_requests:
        target = state["inventory_targets"][state["inventory_index"]]
        item = await db["items"].find_one(
            {
                "_id": target["item_id"],
                "seller_id": {"$in": [seller_id, int(seller_id)]},
            }
        )
        if item is None or target["inventory_id"] not in _item_full_inventories(item, seller_id):
            _pending(state, "inventory_no_longer_owned", target["inventory_id"])
            _advance_full_inventory(state)
            continue
        params = {
            "seller_id": seller_id,
            "inventory_id": target["inventory_id"],
            "date_from": start.date().isoformat(),
            "date_to": (end if end.time() == datetime.min.time() else end + timedelta(days=1))
            .date()
            .isoformat(),
            "limit": str(page_size),
            "type": _FULL_SEARCH_TYPES[state["type_index"]],
        }
        if state.get("scroll"):
            params["scroll"] = state["scroll"]
        requests += 1
        try:
            page = await recovery_fetch_resource(
                gateway,
                seller_id=seller_id,
                path=f"/stock/fulfillment/operations/search?{urlencode(params)}",
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            state["last_error"] = f"http_{code}"
            return _report(
                state,
                requests,
                blocked="access_denied" if code in {401, 403} else "source_retry_required",
            )
        except (httpx.RequestError, TimeoutError):
            state["last_error"] = "source_retry_required"
            return _report(state, requests, blocked="source_retry_required")
        rows = page.get("results") if isinstance(page, dict) else None
        paging = page.get("paging") if isinstance(page, dict) else None
        if (
            not isinstance(rows, list)
            or len(rows) > page_size
            or not isinstance(paging, dict)
            or "scroll" not in paging
            or (paging["scroll"] is not None and not isinstance(paging["scroll"], str))
        ):
            state["last_error"] = "invalid_page"
            return _report(state, requests, blocked="invalid_page")
        for raw in rows:
            try:
                if (
                    not isinstance(raw, dict)
                    or str(raw.get("seller_id")) != seller_id
                    or raw.get("inventory_id") != target["inventory_id"]
                ):
                    raise ValueError("operation ownership mismatch")
                kind = str(raw.get("type", "")).upper()
                if kind not in WITHDRAWAL_TYPES:
                    continue
                operation_id = _identifier(raw.get("id"))
                created = _timestamp(raw.get("date_created"))
                if not start <= created < end:
                    continue
                doc = {
                    "_id": f"{seller_id}:{operation_id}",
                    "operation_id": operation_id,
                    "seller_id": seller_id,
                    "inventory_id": _identifier(raw.get("inventory_id")),
                    "type": kind,
                    "date_created": created,
                    "detail": raw.get("detail"),
                    "external_references": raw.get("external_references"),
                    "source": "meli_full_operations_api",
                    "synced_at": clock,
                    "schema_version": 1,
                }
            except (ValueError, TypeError):
                _pending(state, "invalid_operation")
                continue
            if await _upsert(db, FULL_OPERATIONS_COLLECTION, doc):
                state["persisted"] += 1
            else:
                _pending(state, "seller_conflict", operation_id)
        if paging["scroll"] != state.get("scroll"):
            state["scroll_observed_at"] = clock.isoformat()
        state["scroll"] = paging["scroll"]
        if paging["scroll"] is None:
            state["type_index"] += 1
            state.pop("scroll_observed_at", None)
        if state["type_index"] == len(_FULL_SEARCH_TYPES):
            _advance_full_inventory(state)
    return _report(
        state,
        requests,
        blocked=("full_withdrawal_contract_incompatible" if state["discovery_complete"] else None),
    )
