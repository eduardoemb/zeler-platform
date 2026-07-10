from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from urllib.parse import urlencode


class MeliGatewayResourceClient(Protocol):
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]: ...


class GatewayDevolucionesSource:
    """Read the proven DEVOLUCIONES source contract through the gateway proxy."""

    def __init__(self, client: MeliGatewayResourceClient) -> None:
        self._client = client

    async def search_claims(
        self, *, seller_id: str, params: Mapping[str, str | int]
    ) -> dict[str, Any]:
        limit = params.get("limit", 100)
        offset = params.get("offset", 0)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < 9999:
            raise ValueError("offset must be an integer between 0 and 9998")
        path = f"/post-purchase/v1/claims/search?{urlencode(params)}"
        return await self._client.fetch_resource(seller_id=seller_id, path=path)

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        return await self._client.fetch_resource(
            seller_id=seller_id,
            path=f"/post-purchase/v1/claims/{_numeric_id(claim_id, field='claim_id')}",
        )

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        return await self._client.fetch_resource(
            seller_id=seller_id,
            path=f"/post-purchase/v2/claims/{_numeric_id(claim_id, field='claim_id')}/returns",
        )

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        return await self._client.fetch_resource(
            seller_id=seller_id,
            path=f"/orders/{_numeric_id(order_id, field='order_id')}",
        )


def _numeric_id(value: str, *, field: str) -> str:
    normalized = str(value).strip()
    if re.fullmatch(r"[0-9]+", normalized) is None:
        raise ValueError(f"{field} must be numeric")
    return normalized


MAX_CLAIM_SEARCH_LIMIT = 100
MAX_CLAIM_SEARCH_OFFSET = 9999
MIN_SPLIT_WINDOW = timedelta(milliseconds=1)


class ClaimInventoryError(RuntimeError):
    pass


class DevolucionesReadModelVerificationError(RuntimeError):
    pass


class ClaimInventorySource(Protocol):
    async def search_claims(
        self, *, seller_id: str, params: dict[str, str | int]
    ) -> dict[str, Any]: ...


class DevolucionesSource(ClaimInventorySource, Protocol):
    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]: ...

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]: ...

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ClaimInventoryEntry:
    claim_id: str
    last_updated: str
    date_created: str | None
    source: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedClaimInventory:
    entries: tuple[ClaimInventoryEntry, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class CollectedDevolucionesSnapshot:
    projections: tuple[dict[str, Any], ...]
    orders: tuple[dict[str, Any], ...]
    inventory: VerifiedClaimInventory
    source_fingerprint: str
    read_model_fingerprint: str


@dataclass(frozen=True, slots=True)
class VerifiedDevolucionesReadModel:
    expected_claims: int
    persisted_claims: int
    complete_claims: int
    missing_claims: int
    productive_claims: int
    non_productive_claims: int
    verified_orders: int


async def read_devoluciones_claims_keyset(
    *,
    db: Any,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    page_size: int = 500,
    session: Any = None,
) -> list[dict[str, Any]]:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    date_from, date_to = _validated_utc_range(date_from, date_to)
    session_kwargs = {"session": session} if session is not None else {}
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_date: datetime | None = None
    last_id: str | None = None
    while True:
        filter_spec: dict[str, Any] = {
            "seller_id": str(seller_id),
            "type": "returns",
            "date_created": {"$gte": date_from, "$lt": date_to},
        }
        if last_date is not None and last_id is not None:
            filter_spec["$or"] = [
                {"date_created": {"$gt": last_date, "$lt": date_to}},
                {"date_created": last_date, "_id": {"$gt": last_id}},
            ]
        cursor = (
            db["claims"].find(filter_spec, **session_kwargs).sort([("date_created", 1), ("_id", 1)])
        )
        page = cast("list[dict[str, Any]]", await cursor.to_list(length=page_size))
        if not page:
            return documents
        for document in page:
            claim_id = str(document.get("_id") or "").strip()
            created_at = _utc_datetime(document.get("date_created"), field="claim date_created")
            if not claim_id or claim_id in seen_ids:
                raise DevolucionesReadModelVerificationError(
                    "claim keyset contains a missing or duplicate identity"
                )
            if (
                last_date is not None
                and last_id is not None
                and (created_at < last_date or (created_at == last_date and claim_id <= last_id))
            ):
                raise DevolucionesReadModelVerificationError("claim keyset did not advance")
            seen_ids.add(claim_id)
            documents.append(dict(document))
            last_date = created_at
            last_id = claim_id
        if len(page) < page_size:
            return documents


async def read_devoluciones_orders_by_id_keyset(
    *,
    db: Any,
    seller_id: str,
    order_ids: frozenset[str] | set[str] | Sequence[str],
    chunk_size: int = 500,
    session: Any = None,
) -> list[dict[str, Any]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    normalized_ids = sorted(
        {str(order_id).strip() for order_id in order_ids if str(order_id).strip()}
    )
    session_kwargs = {"session": session} if session is not None else {}
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index in range(0, len(normalized_ids), chunk_size):
        chunk = normalized_ids[index : index + chunk_size]
        cursor = (
            db["orders"]
            .find(
                {"seller_id": str(seller_id), "_id": {"$in": chunk}},
                **session_kwargs,
            )
            .sort([("_id", 1)])
        )
        page = cast("list[dict[str, Any]]", await cursor.to_list(length=None))
        for document in page:
            order_id = str(document.get("_id") or "").strip()
            if not order_id or order_id in seen_ids or order_id not in chunk:
                raise DevolucionesReadModelVerificationError(
                    "order keyset contains an unexpected or duplicate identity"
                )
            seen_ids.add(order_id)
            documents.append(dict(document))
    return documents


async def verify_devoluciones_read_model(
    *,
    db: Any,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    expected_claim_ids: frozenset[str] | set[str] | Sequence[str],
    expected_read_model_fingerprint: str | None = None,
    page_size: int = 500,
    order_chunk_size: int = 500,
    session: Any = None,
) -> VerifiedDevolucionesReadModel:
    expected_ids = frozenset(
        str(claim_id).strip() for claim_id in expected_claim_ids if str(claim_id).strip()
    )
    claims = await read_devoluciones_claims_keyset(
        db=db,
        seller_id=seller_id,
        date_from=date_from,
        date_to=date_to,
        page_size=page_size,
        session=session,
    )
    persisted_ids = frozenset(str(claim.get("_id") or "").strip() for claim in claims)
    if persisted_ids != expected_ids:
        raise DevolucionesReadModelVerificationError(
            "persisted claim identities do not match authoritative inventory"
        )

    productive_claims = 0
    non_productive_claims = 0
    required_orders: dict[str, list[str]] = {}
    for claim in claims:
        claim_id = str(claim.get("_id") or "").strip()
        order_id = _required_text(claim.get("order_id"), field="claim order_id")
        item_id = _required_text(claim.get("item_id"), field="claim item_id")
        _required_text(claim.get("status"), field="claim status")
        claim_version = claim.get("claim_version")
        if isinstance(claim_version, bool) or not isinstance(claim_version, int):
            raise DevolucionesReadModelVerificationError("claim source version is required")
        _utc_datetime(claim.get("last_updated"), field="claim last_updated")
        _utc_datetime(claim.get("return_last_updated"), field="claim return_last_updated")
        if str(claim.get("seller_id")) != str(seller_id) or claim.get("type") != "returns":
            raise DevolucionesReadModelVerificationError("claim scope is not canonical")
        productive = claim.get("productive")
        if productive is True:
            quantity = claim.get("returned_quantity")
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity < 1
                or claim.get("return_quantity_basis") != "v2_return_order"
            ):
                raise DevolucionesReadModelVerificationError(
                    "productive claim lacks exact v2 return quantity"
                )
            productive_claims += 1
        elif productive is False:
            if (
                claim.get("return_subtype") != "low_cost"
                or claim.get("return_quantity_basis") != "verified_low_cost_no_row"
                or claim.get("returned_quantity") is not None
            ):
                raise DevolucionesReadModelVerificationError(
                    "non-productive claim is not a verified low-cost exclusion"
                )
            non_productive_claims += 1
        else:
            raise DevolucionesReadModelVerificationError(
                "claim productive classification is uncertain"
            )
        required_orders.setdefault(order_id, []).append(item_id)
        if not claim_id:
            raise DevolucionesReadModelVerificationError("claim identity is required")

    orders = await read_devoluciones_orders_by_id_keyset(
        db=db,
        seller_id=seller_id,
        order_ids=frozenset(required_orders),
        chunk_size=order_chunk_size,
        session=session,
    )
    orders_by_id = {str(order.get("_id") or "").strip(): order for order in orders}
    if set(orders_by_id) != set(required_orders):
        raise DevolucionesReadModelVerificationError("required canonical orders are missing")
    for order_id, claim_item_ids in required_orders.items():
        order = orders_by_id[order_id]
        if str(order.get("seller_id")) != str(seller_id):
            raise DevolucionesReadModelVerificationError("order seller does not match claim seller")
        items = order.get("items")
        if not isinstance(items, list):
            raise DevolucionesReadModelVerificationError("canonical order items are missing")
        for item_id in claim_item_ids:
            matches = [
                item
                for item in items
                if isinstance(item, Mapping) and str(item.get("item_id") or "").strip() == item_id
            ]
            if len(matches) != 1:
                raise DevolucionesReadModelVerificationError(
                    "claim item does not have one unique canonical order line"
                )

    if expected_read_model_fingerprint is not None:
        persisted_fingerprint = devoluciones_read_model_fingerprint(
            seller_id=seller_id,
            claims=claims,
            orders=orders,
        )
        if persisted_fingerprint != expected_read_model_fingerprint:
            raise DevolucionesReadModelVerificationError(
                "persisted DEVOLUCIONES facts differ from hydrated source facts"
            )

    return VerifiedDevolucionesReadModel(
        expected_claims=len(expected_ids),
        persisted_claims=len(claims),
        complete_claims=len(claims),
        missing_claims=0,
        productive_claims=productive_claims,
        non_productive_claims=non_productive_claims,
        verified_orders=len(orders),
    )


def claim_inventory_search_params(
    *, seller_id: str, start: datetime, end: datetime, offset: int, limit: int
) -> dict[str, str | int]:
    start, end = _validated_utc_range(start, end)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < 9999:
        raise ClaimInventoryError("offset must be an integer below 9999")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ClaimInventoryError("limit must be an integer no greater than 100")
    return {
        "players.user_id": str(seller_id),
        "players.role": "respondent",
        "date_created": _format_meli_datetime(start),
        "range": (
            f"date_created:after:{_format_meli_datetime(start - MIN_SPLIT_WINDOW)},"
            f"before:{_format_meli_datetime(end)}"
        ),
        "sort": "date_created:asc",
        "offset": offset,
        "limit": limit,
    }


async def verify_claim_inventory(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int = MAX_CLAIM_SEARCH_LIMIT,
) -> VerifiedClaimInventory:
    start, end = _validated_utc_range(start, end)
    first = await _inventory_pass(
        source=source, seller_id=str(seller_id), start=start, end=end, limit=limit
    )
    second = await _inventory_pass(
        source=source, seller_id=str(seller_id), start=start, end=end, limit=limit
    )
    first_fingerprint = _inventory_fingerprint(first)
    second_fingerprint = _inventory_fingerprint(second)
    if first_fingerprint != second_fingerprint:
        raise ClaimInventoryError("claim inventory fingerprint changed between passes")
    return VerifiedClaimInventory(entries=tuple(first), fingerprint=first_fingerprint)


async def collect_devoluciones_projections(
    *,
    source: DevolucionesSource,
    seller_id: str,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, Any]], VerifiedClaimInventory]:
    snapshot = await collect_devoluciones_snapshot(
        source=source,
        seller_id=seller_id,
        start=start,
        end=end,
    )
    return list(snapshot.projections), snapshot.inventory


async def collect_devoluciones_snapshot(
    *,
    source: DevolucionesSource,
    seller_id: str,
    start: datetime,
    end: datetime,
) -> CollectedDevolucionesSnapshot:
    from zeler_sheets.claim_projection import build_claim_projection

    inventory = await verify_claim_inventory(
        source=source,
        seller_id=seller_id,
        start=start,
        end=end,
    )
    projections: list[dict[str, Any]] = []
    orders_by_id: dict[str, dict[str, Any]] = {}
    for entry in inventory.entries:
        claim = await source.get_claim(seller_id=seller_id, claim_id=entry.claim_id)
        if not _is_return_candidate(claim):
            continue
        returns = await source.get_returns(seller_id=seller_id, claim_id=entry.claim_id)
        order_id = str(claim.get("order_id") or claim.get("resource_id") or "").strip()
        if not order_id:
            raise ClaimInventoryError("return claim is missing order identity")
        order = await source.get_order(seller_id=seller_id, order_id=order_id)
        orders_by_id[order_id] = dict(order)
        projections.append(
            build_claim_projection(
                seller_id=seller_id,
                claim=claim,
                returns=returns,
                order=order,
            )
        )
    read_model_fingerprint = devoluciones_read_model_fingerprint(
        seller_id=seller_id,
        claims=projections,
        orders=tuple(orders_by_id.values()),
    )
    return CollectedDevolucionesSnapshot(
        projections=tuple(projections),
        orders=tuple(orders_by_id.values()),
        inventory=inventory,
        source_fingerprint=_hydrated_source_fingerprint(
            inventory_fingerprint=inventory.fingerprint,
            read_model_fingerprint=read_model_fingerprint,
        ),
        read_model_fingerprint=read_model_fingerprint,
    )


async def _inventory_pass(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[ClaimInventoryEntry]:
    entries = await _inventory_window(
        source=source,
        seller_id=seller_id,
        start=start,
        end=end,
        limit=limit,
    )
    claim_ids = [entry.claim_id for entry in entries]
    if len(claim_ids) != len(set(claim_ids)):
        raise ClaimInventoryError("duplicate claim id across inventory windows")
    return entries


async def _inventory_window(
    *,
    source: ClaimInventorySource,
    seller_id: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[ClaimInventoryEntry]:
    offset = 0
    stable_total: int | None = None
    entries: list[ClaimInventoryEntry] = []
    seen_ids: set[str] = set()
    while True:
        params = claim_inventory_search_params(
            seller_id=seller_id,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )
        try:
            payload = await source.search_claims(seller_id=seller_id, params=params)
        except Exception as exc:
            raise ClaimInventoryError("claim inventory source request failed") from exc
        data, response_offset, _, total = _validated_page(payload, requested_offset=offset)
        if stable_total is None:
            stable_total = total
        elif stable_total != total:
            raise ClaimInventoryError("claim inventory total changed during paging")
        if total >= MAX_CLAIM_SEARCH_OFFSET + 1:
            if end - start <= MIN_SPLIT_WINDOW:
                raise ClaimInventoryError("claim inventory offset cap is unsplittable")
            midpoint = start + (end - start) / 2
            left = await _inventory_window(
                source=source,
                seller_id=seller_id,
                start=start,
                end=midpoint,
                limit=limit,
            )
            right = await _inventory_window(
                source=source,
                seller_id=seller_id,
                start=midpoint,
                end=end,
                limit=limit,
            )
            return [*left, *right]
        for raw_entry in data:
            entry = _inventory_entry(raw_entry)
            if entry.claim_id in seen_ids:
                raise ClaimInventoryError("duplicate claim id in inventory page")
            seen_ids.add(entry.claim_id)
            entries.append(entry)
        next_offset = response_offset + len(data)
        if next_offset == total:
            return entries
        if next_offset > total:
            raise ClaimInventoryError("claim inventory page exceeds stable total")
        if not data or next_offset <= offset:
            raise ClaimInventoryError("claim inventory nonterminal page did not advance")
        if next_offset >= MAX_CLAIM_SEARCH_OFFSET:
            raise ClaimInventoryError("claim inventory offset cap reached before terminal page")
        offset = next_offset


def _validated_page(
    payload: Mapping[str, Any], *, requested_offset: int
) -> tuple[list[dict[str, Any]], int, int, int]:
    paging = payload.get("paging")
    data = payload.get("data")
    if not isinstance(paging, Mapping) or not isinstance(data, list):
        raise ClaimInventoryError("claim inventory response is missing data or paging")
    values = (paging.get("offset"), paging.get("limit"), paging.get("total"))
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ClaimInventoryError("claim inventory paging values must be integers")
    offset = cast(int, values[0])
    limit = cast(int, values[1])
    total = cast(int, values[2])
    if offset != requested_offset:
        raise ClaimInventoryError("claim inventory response offset did not echo request")
    if not 1 <= limit <= MAX_CLAIM_SEARCH_LIMIT:
        raise ClaimInventoryError("claim inventory response limit is invalid")
    if total < 0:
        raise ClaimInventoryError("claim inventory total is invalid")
    if not all(isinstance(entry, dict) for entry in data):
        raise ClaimInventoryError("claim inventory data rows must be objects")
    return data, offset, limit, total


def _inventory_entry(raw_entry: Mapping[str, Any]) -> ClaimInventoryEntry:
    claim_id = str(raw_entry.get("id") or "").strip()
    last_updated = str(raw_entry.get("last_updated") or "").strip()
    if not claim_id or not last_updated:
        raise ClaimInventoryError("claim inventory row is missing id or last_updated")
    date_created = raw_entry.get("date_created")
    return ClaimInventoryEntry(
        claim_id=claim_id,
        last_updated=last_updated,
        date_created=str(date_created) if date_created is not None else None,
        source=dict(raw_entry),
    )


def _inventory_fingerprint(entries: Sequence[ClaimInventoryEntry]) -> str:
    rows = [(entry.claim_id, entry.last_updated) for entry in entries]
    encoded = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def devoluciones_read_model_fingerprint(
    *,
    seller_id: str,
    claims: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
) -> str:
    normalized_seller_id = _required_text(seller_id, field="seller_id")
    orders_by_id: dict[str, Mapping[str, Any]] = {}
    for source_order in orders:
        order_id = _required_text(
            source_order.get("_id") or source_order.get("id"), field="order identity"
        )
        if order_id in orders_by_id:
            raise DevolucionesReadModelVerificationError(
                "hydrated source proof contains duplicate orders"
            )
        orders_by_id[order_id] = source_order

    rows: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = _required_text(claim.get("_id") or claim.get("id"), field="claim identity")
        claim_seller_id = _required_text(claim.get("seller_id"), field="claim seller_id")
        if claim_seller_id != normalized_seller_id:
            raise DevolucionesReadModelVerificationError(
                "claim seller does not match hydrated source proof scope"
            )
        order_id = _required_text(claim.get("order_id"), field="claim order_id")
        item_id = _required_text(claim.get("item_id"), field="claim item_id")
        matched_order = orders_by_id.get(order_id)
        if matched_order is None:
            raise DevolucionesReadModelVerificationError(
                "hydrated source proof is missing a required order"
            )
        order_seller_id = _order_seller_id(matched_order)
        if order_seller_id != normalized_seller_id:
            raise DevolucionesReadModelVerificationError(
                "order seller does not match hydrated source proof scope"
            )
        order_line = _unique_order_line(matched_order, item_id=item_id)
        claim_version = claim.get("claim_version")
        if isinstance(claim_version, bool) or not isinstance(claim_version, int):
            raise DevolucionesReadModelVerificationError(
                "claim source version is required for hydrated source proof"
            )
        productive = claim.get("productive")
        if not isinstance(productive, bool):
            raise DevolucionesReadModelVerificationError(
                "claim productive classification is required for hydrated source proof"
            )
        returned_quantity = claim.get("returned_quantity")
        if productive:
            if (
                isinstance(returned_quantity, bool)
                or not isinstance(returned_quantity, int)
                or returned_quantity < 1
            ):
                raise DevolucionesReadModelVerificationError(
                    "productive claim quantity is required for hydrated source proof"
                )
        elif returned_quantity is not None:
            raise DevolucionesReadModelVerificationError(
                "non-productive claim quantity must be absent from hydrated source proof"
            )

        rows.append(
            {
                "claim": {
                    "id": claim_id,
                    "seller_id": claim_seller_id,
                    "buyer_id": _optional_fingerprint_text(claim.get("buyer_id")),
                    "order_id": order_id,
                    "item_id": item_id,
                    "claim_version": claim_version,
                    "date_created": _fingerprint_datetime(
                        claim.get("date_created"), field="claim date_created"
                    ),
                    "last_updated": _fingerprint_datetime(
                        claim.get("last_updated"), field="claim last_updated"
                    ),
                    "status": _required_text(claim.get("status"), field="claim status"),
                    "stage": _required_text(claim.get("stage"), field="claim stage"),
                    "type": _required_text(claim.get("type"), field="claim type"),
                },
                "return": {
                    "id": _required_text(claim.get("return_id"), field="return identity"),
                    "status": _required_text(claim.get("return_status"), field="return status"),
                    "subtype": _required_text(claim.get("return_subtype"), field="return subtype"),
                    "last_updated": _fingerprint_datetime(
                        claim.get("return_last_updated"), field="return last_updated"
                    ),
                },
                "return_order_row": {
                    "order_id": order_id,
                    "item_id": item_id,
                    "return_quantity": returned_quantity,
                    "context_type": _optional_fingerprint_text(claim.get("return_context_type")),
                    "quantity_basis": _required_text(
                        claim.get("return_quantity_basis"), field="return quantity basis"
                    ),
                    "productive": productive,
                },
                "order": {
                    "id": order_id,
                    "seller_id": order_seller_id,
                    "item_id": item_id,
                    "variation_id": _order_line_variation_id(order_line),
                    "sku": _order_line_formula_sku(order_line),
                    "title": _order_line_formula_title(order_line),
                    "quantity": _order_line_quantity(order_line),
                },
            }
        )
    rows.sort(key=lambda row: str(row["claim"]["id"]))
    return _fingerprint_payload(rows)


def _hydrated_source_fingerprint(*, inventory_fingerprint: str, read_model_fingerprint: str) -> str:
    return _fingerprint_payload(
        {
            "inventory_fingerprint": inventory_fingerprint,
            "read_model_fingerprint": read_model_fingerprint,
        }
    )


def _fingerprint_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_datetime(value: Any, *, field: str) -> str:
    return (
        _utc_datetime(value, field=field).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _optional_fingerprint_text(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _order_seller_id(order: Mapping[str, Any]) -> str:
    seller = order.get("seller")
    value = seller.get("id") if isinstance(seller, Mapping) else order.get("seller_id")
    return _required_text(value, field="order seller_id")


def _unique_order_line(order: Mapping[str, Any], *, item_id: str) -> Mapping[str, Any]:
    raw_items = order.get("items") or order.get("order_items")
    if not isinstance(raw_items, list):
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof order items are missing"
        )
    matches = [
        row for row in raw_items if isinstance(row, Mapping) and _order_line_item_id(row) == item_id
    ]
    if len(matches) != 1:
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof requires one unique order line"
        )
    return matches[0]


def _order_line_item_id(row: Mapping[str, Any]) -> str:
    nested_item = row.get("item")
    value = nested_item.get("id") if isinstance(nested_item, Mapping) else row.get("item_id")
    return str(value or "").strip()


def _order_line_variation_id(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    value = (
        nested_item.get("variation_id")
        if isinstance(nested_item, Mapping)
        else row.get("variation_id")
    )
    return _optional_fingerprint_text(value)


def _order_line_formula_sku(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    nested = nested_item if isinstance(nested_item, Mapping) else {}
    value = (
        row.get("sku")
        or row.get("seller_sku")
        or row.get("seller_custom_field")
        or nested.get("seller_sku")
        or nested.get("seller_custom_field")
    )
    normalized = str(value).strip().upper() if value is not None else ""
    return normalized or None


def _order_line_formula_title(row: Mapping[str, Any]) -> str | None:
    nested_item = row.get("item")
    nested = nested_item if isinstance(nested_item, Mapping) else {}
    return _optional_fingerprint_text(row.get("title") or nested.get("title"))


def _order_line_quantity(row: Mapping[str, Any]) -> int:
    value = row.get("qty", row.get("quantity"))
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DevolucionesReadModelVerificationError(
            "hydrated source proof order line quantity is invalid"
        )
    return cast(int, value)


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise DevolucionesReadModelVerificationError(f"{field} is required")
    return normalized


def _utc_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise DevolucionesReadModelVerificationError(f"{field} must be a datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_return_candidate(claim: Mapping[str, Any]) -> bool:
    claim_type = str(claim.get("type") or "")
    if claim_type in {"return", "returns"}:
        return True
    if claim_type != "mediations":
        return False
    related = claim.get("related_entities")
    return isinstance(related, list) and any(
        isinstance(entity, Mapping) and entity.get("type") == "return" for entity in related
    )


def _validated_utc_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ClaimInventoryError("claim inventory bounds must be timezone-aware")
    normalized_start = start.astimezone(UTC)
    normalized_end = end.astimezone(UTC)
    if normalized_end <= normalized_start:
        raise ClaimInventoryError("claim inventory end must be after start")
    return normalized_start, normalized_end


def _format_meli_datetime(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    milliseconds = utc_value.microsecond // 1000
    return f"{utc_value:%Y-%m-%dT%H:%M:%S}.{milliseconds:03d}+0000"
