from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from bson.decimal128 import Decimal128
from pydantic import ValidationError

from zeler_platform_core.models import Item, ItemStatusState, ItemStatusTransition, Order, Shipment
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.sheetseller_backfill import (
    build_formula_row_doc,
    build_order_line_formula_row_docs,
    build_order_line_sku_index_docs,
    build_sku_index_docs,
    build_variation_formula_row_docs,
    extract_safe_order_item_identity,
)
from zeler_sheets.status_history import (
    STATUS_HISTORY_DATETIME_FIELDS,
    bson_ms_utc_datetime,
    normalize_status_history_datetimes,
    require_bson_ms_utc_datetime,
)

_STATUS_STATE_CAS_ATTEMPTS = 3
_STATUS_HISTORY_SCALAR_FIELDS = ("status_started_at", "paused_since", "last_status_change_at")


class StatusObservationContentionError(RuntimeError):
    retryable = True


@dataclass(frozen=True, slots=True)
class _StatusObservationResult:
    state: dict[str, Any]
    applied: bool
    publish_snapshot: bool = True


class SheetsEventPersistence:
    def __init__(self, *, db: Any, clock: Callable[[], datetime] | None = None) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(UTC))

    async def persist(
        self, *, event_type: str, seller_id: int | str, resource: dict[str, Any]
    ) -> None:
        if event_type.startswith("items."):
            await self._persist_item(seller_id=str(seller_id), resource=resource)
            return
        if event_type.startswith("orders."):
            await self._persist_order(seller_id=str(seller_id), resource=resource)
            return
        if event_type.startswith("shipments."):
            await self._persist_shipment(seller_id=str(seller_id), resource=resource)

    async def _persist_item(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        observed_at = require_bson_ms_utc_datetime(self._clock())
        document = _canonical_item_document(resource, seller_id=seller_id, synced_at=observed_at)
        status_observation = await self._record_item_status_observation(
            document, seller_id=seller_id, observed_at=observed_at
        )
        if not status_observation.applied:
            return
        if not status_observation.publish_snapshot:
            await self._reconcile_item_status_fields(
                item_id=str(document["_id"]), seller_id=seller_id
            )
            await self._reconcile_formula_rows_status_fields(
                item_id=str(document["_id"]), seller_id=seller_id
            )
            return
        item = _item_with_status_history(document, status_observation.state)
        item_written = await self._replace_item_if_observation_current(
            item, seller_id=seller_id, status_state=status_observation.state
        )
        if not item_written:
            return
        latest_state = await self._latest_matching_item_status_state(
            item_id=str(item["_id"]),
            seller_id=seller_id,
            status=item.get("status"),
            observed_at=_state_last_observed_at(status_observation.state),
        )
        if latest_state is None:
            await self._reconcile_item_status_fields(item_id=str(item["_id"]), seller_id=seller_id)
            return
        if not _item_status_history_matches_state(item, latest_state):
            await self._reconcile_item_status_fields(item_id=str(item["_id"]), seller_id=seller_id)
        await self._refresh_item_read_models(item, seller_id=seller_id, status_state=latest_state)

    async def _record_item_status_observation(
        self, item: dict[str, Any], *, seller_id: str, observed_at: datetime
    ) -> _StatusObservationResult:
        observed_at = require_bson_ms_utc_datetime(observed_at)
        item_id = str(item["_id"])
        current_status = str(item.get("status") or "").strip()
        state_collection = self._db["item_status_states"]
        transition_collection = self._db["item_status_transitions"]
        state = _normalize_status_state(
            await state_collection.find_one({"_id": _status_state_id(seller_id, item_id)})
        )

        for _ in range(_STATUS_STATE_CAS_ATTEMPTS):
            if state is not None:
                corrected_state = await _preserve_earliest_paused_start_if_expected(
                    state_collection=state_collection,
                    state=state,
                    current_status=current_status,
                    observed_at=observed_at,
                )
                if corrected_state is not None:
                    return _StatusObservationResult(
                        state=corrected_state, applied=True, publish_snapshot=False
                    )
            if _observation_is_older_than_state(observed_at=observed_at, state=state):
                corrected_state = await _preserve_earliest_paused_start_if_expected(
                    state_collection=state_collection,
                    state=cast("dict[str, Any]", state),
                    current_status=current_status,
                    observed_at=observed_at,
                )
                if corrected_state is not None:
                    return _StatusObservationResult(
                        state=corrected_state, applied=True, publish_snapshot=False
                    )
                return _StatusObservationResult(state=cast("dict[str, Any]", state), applied=False)
            prior_status = _optional_string(state.get("current_status")) if state else None
            status_changed = prior_status is not None and prior_status != current_status
            next_state = _status_state_document(
                seller_id=seller_id,
                item_id=item_id,
                current_status=current_status,
                observed_at=observed_at,
                prior_state=state,
                status_changed=status_changed,
            )
            state_write_won = await _replace_status_state_if_expected(
                state_collection=state_collection,
                next_state=next_state,
                prior_state=state,
                expected_prior_status=prior_status,
            )

            if state_write_won:
                if prior_status is not None and prior_status != current_status:
                    transition = _status_transition_document(
                        seller_id=seller_id,
                        item_id=item_id,
                        from_status=prior_status,
                        to_status=current_status,
                        observed_at=observed_at,
                    )
                    await transition_collection.replace_one(
                        {"_id": transition["_id"]}, transition, upsert=True
                    )
                return _StatusObservationResult(state=next_state, applied=True)

            winning_state = _normalize_status_state(
                await state_collection.find_one({"_id": next_state["_id"]})
            )
            if winning_state is None:
                state = None
                continue
            state = winning_state
            corrected_state = await _preserve_earliest_paused_start_if_expected(
                state_collection=state_collection,
                state=state,
                current_status=current_status,
                observed_at=observed_at,
            )
            if corrected_state is not None:
                return _StatusObservationResult(
                    state=corrected_state, applied=True, publish_snapshot=False
                )
            if _observation_is_older_than_state(observed_at=observed_at, state=state):
                corrected_state = await _preserve_earliest_paused_start_if_expected(
                    state_collection=state_collection,
                    state=state,
                    current_status=current_status,
                    observed_at=observed_at,
                )
                if corrected_state is not None:
                    return _StatusObservationResult(
                        state=corrected_state, applied=True, publish_snapshot=False
                    )
                return _StatusObservationResult(state=state, applied=False)
            if _status_state_matches_observation(
                state, status=current_status, observed_at=observed_at
            ):
                return _StatusObservationResult(state=state, applied=True)

        latest_state = _normalize_status_state(
            await state_collection.find_one({"_id": _status_state_id(seller_id, item_id)})
        )
        if latest_state is not None:
            state = latest_state
            corrected_state = await _preserve_earliest_paused_start_if_expected(
                state_collection=state_collection,
                state=state,
                current_status=current_status,
                observed_at=observed_at,
            )
            if corrected_state is not None:
                return _StatusObservationResult(
                    state=corrected_state, applied=True, publish_snapshot=False
                )
            if _observation_is_older_than_state(observed_at=observed_at, state=state):
                corrected_state = await _preserve_earliest_paused_start_if_expected(
                    state_collection=state_collection,
                    state=state,
                    current_status=current_status,
                    observed_at=observed_at,
                )
                if corrected_state is not None:
                    return _StatusObservationResult(
                        state=corrected_state, applied=True, publish_snapshot=False
                    )
                return _StatusObservationResult(state=state, applied=False)
            if _status_state_matches_observation(
                state, status=current_status, observed_at=observed_at
            ):
                return _StatusObservationResult(state=state, applied=True)
        msg = (
            "item status observation could not settle after "
            f"{_STATUS_STATE_CAS_ATTEMPTS} compare-and-swap attempts"
        )
        raise StatusObservationContentionError(msg)

    async def _latest_matching_item_status_state(
        self, *, item_id: str, seller_id: str, status: Any, observed_at: datetime | None = None
    ) -> dict[str, Any] | None:
        latest_state = _normalize_status_state(
            await self._db["item_status_states"].find_one(
                {"_id": _status_state_id(seller_id, item_id)}
            )
        )
        if latest_state is None:
            return None
        if _optional_string(latest_state.get("current_status")) != _optional_string(status):
            return None
        normalized_observed_at = bson_ms_utc_datetime(observed_at)
        if (
            normalized_observed_at is not None
            and _state_last_observed_at(latest_state) != normalized_observed_at
        ):
            return None
        return latest_state

    async def _replace_item_if_observation_current(
        self, item: dict[str, Any], *, seller_id: str, status_state: dict[str, Any]
    ) -> bool:
        observed_at = _state_last_observed_at(status_state)
        if observed_at is None:
            return False
        latest_state = await self._latest_matching_item_status_state(
            item_id=str(item["_id"]),
            seller_id=seller_id,
            status=item.get("status"),
            observed_at=observed_at,
        )
        if latest_state is None:
            await self._reconcile_item_status_fields(item_id=str(item["_id"]), seller_id=seller_id)
            return False
        item = _item_with_status_history(item, latest_state)

        collection = self._db["items"]
        result = await collection.replace_one(
            {
                "_id": item["_id"],
                "seller_id": seller_id,
                "$or": [
                    {"status_observed_at": {"$exists": False}},
                    {"status_observed_at": {"$lte": observed_at}},
                ],
            },
            item,
            upsert=False,
        )
        if result.matched_count > 0:
            return True
        insert_result = await collection.update_one(
            {"_id": item["_id"], "seller_id": seller_id},
            {"$setOnInsert": item},
            upsert=True,
        )
        return insert_result.upserted_id is not None

    async def _refresh_item_read_models(
        self, item: dict[str, Any], *, seller_id: str, status_state: dict[str, Any]
    ) -> None:
        item = _item_with_status_history(item, status_state)
        sku_index_docs = build_sku_index_docs(item, seller_id=seller_id)
        for sku_index_doc in sku_index_docs:
            await self._db["sheets_item_sku_index"].replace_one(
                {"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True
            )

        formula_row_docs: list[dict[str, Any]] = []
        with suppress(ValueError):
            formula_row_docs.append(build_formula_row_doc(item, seller_id=seller_id))

        variation_formula_rows, _, _ = build_variation_formula_row_docs(
            item, sku_index_docs, seller_id=seller_id
        )
        formula_row_docs.extend(variation_formula_rows)
        order_line_identities = await self._load_order_line_sku_identities(
            item_id=str(item["_id"]), seller_id=seller_id
        )
        order_line_identities = _missing_order_line_identities(
            order_line_identities, sku_index_docs
        )
        formula_row_docs.extend(
            build_order_line_formula_row_docs(
                item,
                order_line_identities=order_line_identities,
                seller_id=seller_id,
            )
        )

        for formula_row_doc in formula_row_docs:
            await self._replace_formula_row_if_observation_current(
                formula_row_doc, status_state=status_state, seller_id=seller_id
            )

    async def _replace_formula_row_if_observation_current(
        self, formula_row_doc: dict[str, Any], *, status_state: dict[str, Any], seller_id: str
    ) -> None:
        observed_at = _state_last_observed_at(status_state)
        if observed_at is None:
            return
        latest_state = await self._latest_matching_item_status_state(
            item_id=str(formula_row_doc["item_id"]),
            seller_id=seller_id,
            status=formula_row_doc.get("current", {}).get("status"),
            observed_at=observed_at,
        )
        if latest_state is None:
            await self._reconcile_item_status_fields(
                item_id=str(formula_row_doc["item_id"]), seller_id=seller_id
            )
            await self._reconcile_formula_row_status_fields(formula_row_doc)
            return
        formula_row_doc = _formula_row_with_status_history(formula_row_doc, latest_state)

        collection = self._db["sheets_item_formula_rows"]
        result = await collection.replace_one(
            {
                "_id": formula_row_doc["_id"],
                "$or": [
                    {"current.status_observed_at": {"$exists": False}},
                    {"current.status_observed_at": {"$lte": observed_at}},
                ],
            },
            formula_row_doc,
            upsert=False,
        )
        if result.matched_count == 0:
            await collection.update_one(
                {"_id": formula_row_doc["_id"]},
                {"$setOnInsert": formula_row_doc},
                upsert=True,
            )

        latest_state = await self._latest_matching_item_status_state(
            item_id=str(formula_row_doc["item_id"]),
            seller_id=seller_id,
            status=formula_row_doc.get("current", {}).get("status"),
            observed_at=observed_at,
        )
        if latest_state is None:
            await self._reconcile_item_status_fields(
                item_id=str(formula_row_doc["item_id"]), seller_id=seller_id
            )
            await self._reconcile_formula_row_status_fields(formula_row_doc)
            return
        if not _formula_row_status_history_matches_state(formula_row_doc, latest_state):
            await self._reconcile_item_status_fields(
                item_id=str(formula_row_doc["item_id"]), seller_id=seller_id
            )
            await self._reconcile_formula_row_status_fields(formula_row_doc)

    async def _reconcile_item_status_fields(self, *, item_id: str, seller_id: str) -> None:
        latest_state = _normalize_status_state(
            await self._db["item_status_states"].find_one(
                {"_id": _status_state_id(seller_id, item_id)}
            )
        )
        if latest_state is None:
            return
        collection = self._db["items"]
        observed_at = _state_last_observed_at(latest_state)
        if observed_at is None:
            return
        existing_item = await collection.find_one({"_id": item_id, "seller_id": seller_id})
        if existing_item is not None and _item_status_history_matches_state(
            cast("dict[str, Any]", existing_item), latest_state
        ):
            return
        set_fields, unset_fields = _item_status_history_update_fields(latest_state)
        update_doc: dict[str, Any] = {"$set": set_fields}
        if unset_fields:
            update_doc["$unset"] = unset_fields
        await collection.update_one(
            {
                "_id": item_id,
                "seller_id": seller_id,
                **_status_observed_at_guard("status_observed_at", observed_at),
            },
            update_doc,
            upsert=False,
        )

    async def _reconcile_formula_rows_status_fields(self, *, item_id: str, seller_id: str) -> None:
        cursor = self._db["sheets_item_formula_rows"].find(
            {"seller_id": seller_id, "item_id": item_id}
        )
        formula_rows = await cursor.to_list(length=None)
        for formula_row_doc in formula_rows:
            await self._reconcile_formula_row_status_fields(cast("dict[str, Any]", formula_row_doc))

    async def _reconcile_formula_row_status_fields(self, formula_row_doc: dict[str, Any]) -> None:
        latest_state = _normalize_status_state(
            await self._db["item_status_states"].find_one(
                {
                    "_id": _status_state_id(
                        str(formula_row_doc["seller_id"]), str(formula_row_doc["item_id"])
                    )
                }
            )
        )
        if latest_state is None:
            return
        observed_at = _state_last_observed_at(latest_state)
        if observed_at is None:
            return
        collection = self._db["sheets_item_formula_rows"]
        existing_formula_row = await collection.find_one({"_id": formula_row_doc["_id"]})
        if existing_formula_row is not None and _formula_row_status_history_matches_state(
            cast("dict[str, Any]", existing_formula_row), latest_state
        ):
            return
        set_fields, unset_fields = _formula_row_status_history_update_fields(latest_state)
        update_doc: dict[str, Any] = {"$set": set_fields}
        if unset_fields:
            update_doc["$unset"] = unset_fields
        await collection.update_one(
            {
                "_id": formula_row_doc["_id"],
                **_status_observed_at_guard("current.status_observed_at", observed_at),
            },
            update_doc,
            upsert=False,
        )

    async def _load_order_line_sku_identities(
        self, *, item_id: str, seller_id: str
    ) -> list[dict[str, Any]]:
        collection = self._db["sheets_item_sku_index"]
        cursor = collection.find(
            {
                "seller_id": seller_id,
                "item_id": item_id,
                "source": "order_line",
            }
        )
        return cast("list[dict[str, Any]]", await cursor.to_list(length=None))

    async def _persist_order(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_order_document(resource, seller_id=seller_id)
        await self._db["orders"].replace_one(
            {"_id": document["_id"], "seller_id": seller_id}, document, upsert=True
        )
        await self._refresh_order_line_sku_index(document, seller_id=seller_id)

    async def _refresh_order_line_sku_index(self, order: dict[str, Any], *, seller_id: str) -> None:
        collection = self._db["sheets_item_sku_index"]
        for sku_index_doc in build_order_line_sku_index_docs(order, seller_id=seller_id):
            if await self._has_conflicting_order_line_identity(sku_index_doc):
                continue
            await collection.replace_one({"_id": sku_index_doc["_id"]}, sku_index_doc, upsert=True)

    async def _has_conflicting_order_line_identity(self, sku_index_doc: dict[str, Any]) -> bool:
        collection = self._db["sheets_item_sku_index"]
        cursor = collection.find(
            {
                "seller_id": sku_index_doc["seller_id"],
                "item_id": sku_index_doc["item_id"],
                "variation_id": sku_index_doc.get("variation_id"),
                "source": "order_line",
            }
        )
        existing_docs = await cursor.to_list(length=None)
        normalized_sku = sku_index_doc.get("normalized_sku")
        return any(existing.get("normalized_sku") != normalized_sku for existing in existing_docs)

    async def _persist_shipment(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_shipment_document(resource, seller_id=seller_id)
        await self._db["shipments"].replace_one(
            {"_id": document["_id"], "seller_id": seller_id}, document, upsert=True
        )


def _canonical_item_document(
    resource: dict[str, Any], *, seller_id: str, synced_at: datetime
) -> dict[str, Any]:
    item_id = _string_id(resource.get("_id") or resource.get("id"))
    price = resource.get("price", 0)
    model = Item.model_validate(
        {
            **resource,
            "_id": item_id,
            "seller_id": seller_id,
            "price": price,
            "base_price": resource.get("base_price", price),
            "category_id": str(resource.get("category_id") or ""),
            "date_created": resource.get("date_created") or synced_at,
            "last_updated": resource.get("last_updated") or resource.get("updated_at") or synced_at,
            "last_meli_sync_at": synced_at,
            "schema_version": current_schema_version("items"),
        }
    )
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _canonical_order_document(resource: dict[str, Any], *, seller_id: str) -> dict[str, Any]:
    order_id = _string_id(resource.get("_id") or resource.get("id"))
    model = Order.model_validate(
        {
            **resource,
            "_id": order_id,
            "seller_id": seller_id,
            "buyer_id": _buyer_id(resource),
            "shipment_id": _shipment_id(resource),
            "meli_pack_id": _meli_pack_id(resource),
            "items": _order_items(resource),
            "schema_version": current_schema_version("orders"),
        }
    )
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _canonical_shipment_document(resource: dict[str, Any], *, seller_id: str) -> dict[str, Any]:
    shipment_id = _string_id(resource.get("_id") or resource.get("id"))
    try:
        model = Shipment.model_validate(
            {
                **resource,
                "_id": shipment_id,
                "seller_id": seller_id,
                "order_id": _shipment_order_id(resource),
                "receiver_address": _receiver_address_snapshot(resource),
                "schema_version": current_schema_version("shipments"),
            }
        )
    except ValidationError:
        msg = "shipment resource failed validation"
        raise ValueError(msg) from None
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _status_transition_document(
    *, seller_id: str, item_id: str, from_status: str, to_status: str, observed_at: datetime
) -> dict[str, Any]:
    observed_at = require_bson_ms_utc_datetime(observed_at)
    transition = ItemStatusTransition.model_validate(
        {
            "_id": _status_transition_id(
                seller_id=seller_id,
                item_id=item_id,
                from_status=from_status,
                to_status=to_status,
                observed_at=observed_at,
            ),
            "seller_id": seller_id,
            "item_id": item_id,
            "from_status": from_status,
            "to_status": to_status,
            "observed_at": observed_at,
            "source": "sheets_event_persistence",
            "schema_version": current_schema_version("item_status_transitions"),
        }
    )
    return transition.model_dump(by_alias=True, mode="python")


def _status_state_document(
    *,
    seller_id: str,
    item_id: str,
    current_status: str,
    observed_at: datetime,
    prior_state: dict[str, Any] | None,
    status_changed: bool,
) -> dict[str, Any]:
    observed_at = require_bson_ms_utc_datetime(observed_at)
    prior_state = _normalize_status_state(prior_state)
    first_observed_at = _status_first_observed_at(prior_state=prior_state, observed_at=observed_at)
    state_payload: dict[str, Any] = {
        "_id": _status_state_id(seller_id, item_id),
        "seller_id": seller_id,
        "item_id": item_id,
        "current_status": current_status,
        "first_observed_at": first_observed_at,
        "last_observed_at": observed_at,
        "schema_version": current_schema_version("item_status_states"),
    }
    if status_changed:
        state_payload["status_started_at"] = observed_at
        state_payload["last_status_change_at"] = observed_at
        if current_status == "paused":
            state_payload["paused_since"] = observed_at
    elif prior_state is not None:
        for field in ("status_started_at", "paused_since", "last_status_change_at"):
            if prior_state.get(field) is not None:
                state_payload[field] = prior_state[field]

    state = ItemStatusState.model_validate(state_payload)
    return normalize_status_history_datetimes(
        state.model_dump(by_alias=True, mode="python", exclude_none=True)
    )


async def _preserve_earliest_paused_start_if_expected(
    *,
    state_collection: Any,
    state: dict[str, Any],
    current_status: str,
    observed_at: datetime,
) -> dict[str, Any] | None:
    observed_at = require_bson_ms_utc_datetime(observed_at)
    state = _normalize_status_state(state) or state
    for _ in range(_STATUS_STATE_CAS_ATTEMPTS):
        if not _same_paused_observation_can_preserve_earliest_start(
            state=state, current_status=current_status, observed_at=observed_at
        ):
            return None
        last_observed_at = _state_last_observed_at(state)
        if last_observed_at is None:
            return None
        result = await state_collection.update_one(
            {
                "_id": state["_id"],
                "current_status": "paused",
                "last_observed_at": last_observed_at,
                "paused_since": {"$gt": observed_at},
            },
            {
                "$set": {
                    "status_started_at": observed_at,
                    "paused_since": observed_at,
                    "last_status_change_at": observed_at,
                }
            },
            upsert=False,
        )
        latest_state = _normalize_status_state(
            await state_collection.find_one({"_id": state["_id"]})
        )
        if result.matched_count > 0:
            return latest_state or {
                **state,
                "status_started_at": observed_at,
                "paused_since": observed_at,
                "last_status_change_at": observed_at,
            }
        if latest_state is None:
            return None
        state = latest_state
    msg = (
        "paused status observation could not preserve earliest start after "
        f"{_STATUS_STATE_CAS_ATTEMPTS} compare-and-swap attempts"
    )
    raise StatusObservationContentionError(msg)


def _same_paused_observation_can_preserve_earliest_start(
    *, state: dict[str, Any], current_status: str, observed_at: datetime
) -> bool:
    if _optional_string(current_status) != "paused":
        return False
    if _optional_string(state.get("current_status")) != "paused":
        return False
    last_observed_at = _state_last_observed_at(state)
    if last_observed_at is None or observed_at > last_observed_at:
        return False
    paused_since = bson_ms_utc_datetime(state.get("paused_since"))
    return paused_since is not None and observed_at < paused_since


def _paused_start_at(state: dict[str, Any]) -> datetime | None:
    starts = [
        value
        for field in ("paused_since", "status_started_at", "last_status_change_at")
        if (value := bson_ms_utc_datetime(state.get(field))) is not None
    ]
    return min(starts) if starts else None


async def _replace_status_state_if_expected(
    *,
    state_collection: Any,
    next_state: dict[str, Any],
    prior_state: dict[str, Any] | None,
    expected_prior_status: str | None,
) -> bool:
    expected_last_observed_at = _state_last_observed_at(prior_state)
    if prior_state is None:
        if expected_prior_status is not None:
            filter_spec: dict[str, Any] = {
                "_id": next_state["_id"],
                "current_status": expected_prior_status,
            }
            if expected_last_observed_at is not None:
                filter_spec["last_observed_at"] = expected_last_observed_at
            result = await state_collection.replace_one(
                filter_spec,
                next_state,
                upsert=False,
            )
            if result.matched_count > 0:
                return True
        result = await state_collection.update_one(
            {"_id": next_state["_id"]}, {"$setOnInsert": next_state}, upsert=True
        )
        return result.upserted_id is not None

    filter_spec = {"_id": next_state["_id"], "current_status": expected_prior_status}
    if expected_last_observed_at is not None:
        filter_spec["last_observed_at"] = expected_last_observed_at
    filter_spec.update(_status_history_scalar_tuple_guard(prior_state))
    result = await state_collection.replace_one(filter_spec, next_state, upsert=False)
    return bool(result.matched_count > 0)


def _status_first_observed_at(
    *, prior_state: dict[str, Any] | None, observed_at: datetime
) -> datetime:
    if prior_state is not None:
        first_observed_at = bson_ms_utc_datetime(prior_state.get("first_observed_at"))
        if first_observed_at is not None:
            return first_observed_at
    return require_bson_ms_utc_datetime(observed_at)


def _item_with_status_history(item: dict[str, Any], status_state: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    enriched["status"] = status_state["current_status"]
    for field in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        enriched.pop(field, None)
    if (last_observed_at := _state_last_observed_at(status_state)) is not None:
        enriched["status_observed_at"] = last_observed_at
    for field in ("status_started_at", "paused_since", "last_status_change_at"):
        if (value := bson_ms_utc_datetime(status_state.get(field))) is not None:
            enriched[field] = value
    return enriched


def _formula_row_with_status_history(
    formula_row_doc: dict[str, Any], status_state: dict[str, Any]
) -> dict[str, Any]:
    reconciled = dict(formula_row_doc)
    current = dict(reconciled.get("current") or {})
    current["status"] = status_state["current_status"]
    for field in (
        "status_observed_at",
        "status_started_at",
        "paused_since",
        "last_status_change_at",
    ):
        current.pop(field, None)
    if (last_observed_at := _state_last_observed_at(status_state)) is not None:
        current["status_observed_at"] = last_observed_at
    for field in ("status_started_at", "paused_since", "last_status_change_at"):
        if (value := bson_ms_utc_datetime(status_state.get(field))) is not None:
            current[field] = value
    reconciled["current"] = current
    return reconciled


def _status_observed_at_guard(field: str, observed_at: datetime) -> dict[str, Any]:
    observed_at = require_bson_ms_utc_datetime(observed_at)
    return {
        "$or": [
            {field: {"$exists": False}},
            {field: {"$lte": observed_at}},
        ]
    }


def _status_history_scalar_tuple_guard(status_state: dict[str, Any]) -> dict[str, Any]:
    guard: dict[str, Any] = {}
    for field in _STATUS_HISTORY_SCALAR_FIELDS:
        value = bson_ms_utc_datetime(status_state.get(field))
        guard[field] = value if value is not None else {"$exists": False}
    return guard


def _item_status_history_update_fields(
    status_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    set_fields: dict[str, Any] = {
        "status": status_state["current_status"],
        "status_observed_at": require_bson_ms_utc_datetime(status_state["last_observed_at"]),
    }
    unset_fields: dict[str, str] = {}
    for field in ("status_started_at", "paused_since", "last_status_change_at"):
        if (value := bson_ms_utc_datetime(status_state.get(field))) is not None:
            set_fields[field] = value
        else:
            unset_fields[field] = ""
    return set_fields, unset_fields


def _formula_row_status_history_update_fields(
    status_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    item_set, item_unset = _item_status_history_update_fields(status_state)
    return (
        {f"current.{field}": value for field, value in item_set.items()},
        {f"current.{field}": value for field, value in item_unset.items()},
    )


def _item_status_history_matches_state(item: dict[str, Any], status_state: dict[str, Any]) -> bool:
    if _optional_string(item.get("status")) != _optional_string(status_state.get("current_status")):
        return False
    if bson_ms_utc_datetime(item.get("status_observed_at")) != _state_last_observed_at(
        status_state
    ):
        return False
    return all(
        bson_ms_utc_datetime(item.get(field)) == bson_ms_utc_datetime(status_state.get(field))
        for field in _STATUS_HISTORY_SCALAR_FIELDS
    )


def _formula_row_status_history_matches_state(
    formula_row_doc: dict[str, Any], status_state: dict[str, Any]
) -> bool:
    current = formula_row_doc.get("current")
    if not isinstance(current, dict):
        return False
    return _item_status_history_matches_state(current, status_state)


def _state_last_observed_at(state: dict[str, Any] | None) -> datetime | None:
    if state is None:
        return None
    return bson_ms_utc_datetime(state.get("last_observed_at"))


def _observation_is_older_than_state(
    *, observed_at: datetime, state: dict[str, Any] | None
) -> bool:
    last_observed_at = _state_last_observed_at(state)
    observed_at = require_bson_ms_utc_datetime(observed_at)
    return last_observed_at is not None and observed_at < last_observed_at


def _status_state_matches_observation(
    state: dict[str, Any], *, status: str, observed_at: datetime
) -> bool:
    return _optional_string(state.get("current_status")) == _optional_string(
        status
    ) and _state_last_observed_at(state) == bson_ms_utc_datetime(observed_at)


def _status_state_id(seller_id: str, item_id: str) -> str:
    return f"{seller_id}:{item_id}"


def _status_transition_id(
    *, seller_id: str, item_id: str, from_status: str, to_status: str, observed_at: datetime
) -> str:
    observed_at = require_bson_ms_utc_datetime(observed_at)
    return f"{seller_id}:{item_id}:{observed_at.isoformat()}:{from_status}:{to_status}"


def _normalize_status_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    normalized = normalize_status_history_datetimes(state)
    for field in STATUS_HISTORY_DATETIME_FIELDS:
        if field in normalized and normalized[field] is None:
            normalized.pop(field, None)
    return normalized


def _missing_order_line_identities(
    order_line_identities: Sequence[dict[str, Any]], sku_index_docs: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    direct_identity_keys = {
        (str(doc.get("item_id") or ""), _optional_string(doc.get("variation_id")))
        for doc in sku_index_docs
    }
    return [
        identity
        for identity in order_line_identities
        if (
            str(identity.get("item_id") or ""),
            _optional_string(identity.get("variation_id")),
        )
        not in direct_identity_keys
    ]


def _bson_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, dict):
        return {key: _bson_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_bson_safe(nested) for nested in value]
    return value


def _order_items(resource: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = resource.get("items") or resource.get("order_items") or []
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return []

    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        identity = extract_safe_order_item_identity(raw_item)
        if "item_id" not in identity:
            continue
        normalized: dict[str, Any] = {
            "item_id": identity["item_id"],
            "qty": raw_item.get("qty", raw_item.get("quantity", 1)),
            "unit_price": raw_item.get("unit_price", 0),
        }
        for field in ("variation_id", "sku", "seller_sku", "seller_custom_field"):
            value = identity.get(field)
            if value is not None:
                normalized[field] = str(value).strip()
        items.append(normalized)
    return items


def _buyer_id(resource: dict[str, Any]) -> str:
    buyer = resource.get("buyer")
    if isinstance(buyer, dict):
        return _string_id(buyer.get("id") or buyer.get("buyer_id"))
    return _string_id(resource.get("buyer_id"))


def _shipment_id(resource: dict[str, Any]) -> str | None:
    shipping = resource.get("shipping")
    if isinstance(shipping, dict):
        value = shipping.get("id") or shipping.get("shipment_id")
    else:
        value = resource.get("shipment_id")
    return None if value is None else str(value)


def _meli_pack_id(resource: dict[str, Any]) -> str | None:
    value = resource.get("pack_id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _shipment_order_id(resource: dict[str, Any]) -> str:
    order = resource.get("order")
    if isinstance(order, dict):
        return _string_id(order.get("id") or order.get("order_id"))
    return _string_id(resource.get("order_id"))


def _receiver_address_snapshot(resource: dict[str, Any]) -> dict[str, Any] | None:
    raw_address = resource.get("receiver_address")
    if not isinstance(raw_address, dict):
        return None

    snapshot = {
        "name": _first_receiver_address_string(
            raw_address.get("receiver_name"), raw_address.get("name")
        ),
        "street_name": _receiver_address_string(raw_address.get("street_name")),
        "street_number": _receiver_address_string(raw_address.get("street_number")),
        "neighborhood": _receiver_address_string(_named_value(raw_address.get("neighborhood"))),
        "zip_code": _receiver_address_string(raw_address.get("zip_code")),
        "city": _receiver_address_string(_named_value(raw_address.get("city"))),
        "state": _receiver_address_string(_named_value(raw_address.get("state"))),
        "country": _receiver_address_string(_named_value(raw_address.get("country"))),
    }
    sanitized = {key: value for key, value in snapshot.items() if value is not None}
    return sanitized or None


def _named_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _receiver_address_string(value.get("name")) or _receiver_address_string(
            value.get("id")
        )
    return value


def _receiver_address_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_receiver_address_string(*values: Any) -> str | None:
    for value in values:
        normalized = _receiver_address_string(value)
        if normalized is not None:
            return normalized
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        msg = "resource is missing required id"
        raise ValueError(msg)
    return normalized
