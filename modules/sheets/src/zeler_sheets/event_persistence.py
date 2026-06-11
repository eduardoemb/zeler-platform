from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from bson.decimal128 import Decimal128
from pydantic import ValidationError

from zeler_platform_core.models import (
    Item,
    ItemStatusState,
    ItemStatusTransition,
    Order,
    Question,
    Shipment,
)
from zeler_platform_core.models.base import current_schema_version
from zeler_sheets.enrichment import (
    basis_hash,
    bounded_basis,
    enrichment_state,
    schema_safe_enrichment_state,
)
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
            return
        if event_type.startswith("questions."):
            await self._persist_question(seller_id=str(seller_id), resource=resource)

    async def _persist_item(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        observed_at = require_bson_ms_utc_datetime(self._clock())
        document = _canonical_item_document(resource, seller_id=seller_id, synced_at=observed_at)
        present_freshness_fields = _item_present_freshness_fields(resource)
        existing_item = await self._db["items"].find_one(
            {"_id": str(document["_id"]), "seller_id": seller_id}
        )
        if existing_item is not None and not _resource_freshness_allows_write(
            existing_item,
            document,
            freshness_fields=("last_updated",),
            present_freshness_fields=present_freshness_fields,
        ):
            return
        document = _item_with_preserved_enrichment(
            document,
            cast("dict[str, Any] | None", existing_item),
        )
        if existing_item is not None and await self._legacy_status_history_blocks_item_replace(
            cast("dict[str, Any]", existing_item),
            document,
            seller_id=seller_id,
            observed_at=observed_at,
        ):
            await self._persist_legacy_item_with_status_observation_guard(
                document,
                seller_id=seller_id,
                observed_at=observed_at,
                present_freshness_fields=present_freshness_fields,
            )
            return

        item_written = await _replace_resource_if_fresh(
            self._db["items"],
            document,
            seller_id=seller_id,
            freshness_fields=("last_updated",),
            present_freshness_fields=present_freshness_fields,
        )
        if not item_written:
            return

        accepted_item = await self._current_item_if_snapshot_not_superseded(
            document,
            seller_id=seller_id,
            present_freshness_fields=present_freshness_fields,
        )
        if accepted_item is None:
            return

        latest_state = await self._record_status_side_effects_for_accepted_item(
            accepted_item,
            seller_id=seller_id,
            observed_at=observed_at,
        )

        if latest_state is not None:
            await self._reconcile_item_status_fields(
                item_id=str(accepted_item["_id"]),
                seller_id=seller_id,
                item_snapshot=accepted_item,
            )
            item = _item_with_status_history(accepted_item, latest_state)
        else:
            item = accepted_item

        await self._refresh_item_read_models(item, seller_id=seller_id, status_state=latest_state)

    async def _legacy_status_history_blocks_item_replace(
        self,
        existing_item: dict[str, Any],
        item: dict[str, Any],
        *,
        seller_id: str,
        observed_at: datetime,
    ) -> bool:
        if _document_path_value(existing_item, "last_updated") is not None:
            return False
        observed_at = require_bson_ms_utc_datetime(observed_at)
        existing_status_observed_at = _latest_item_status_history_observed_at(existing_item)
        if existing_status_observed_at is not None and existing_status_observed_at >= observed_at:
            return True
        status_state = _normalize_status_state(
            await self._db["item_status_states"].find_one(
                {"_id": _status_state_id(seller_id, str(item["_id"]))}
            )
        )
        state_observed_at = _state_last_observed_at(status_state)
        return state_observed_at is not None and state_observed_at >= observed_at

    async def _persist_legacy_item_with_status_observation_guard(
        self,
        document: dict[str, Any],
        *,
        seller_id: str,
        observed_at: datetime,
        present_freshness_fields: Sequence[str],
    ) -> None:
        if not await self._item_observation_can_mutate_status_side_effects(
            document,
            seller_id=seller_id,
            present_freshness_fields=present_freshness_fields,
        ):
            return
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
            item,
            seller_id=seller_id,
            status_state=status_observation.state,
            present_freshness_fields=present_freshness_fields,
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

    async def _current_item_if_snapshot_not_superseded(
        self,
        item: dict[str, Any],
        *,
        seller_id: str,
        present_freshness_fields: Sequence[str],
    ) -> dict[str, Any] | None:
        current_item = await self._db["items"].find_one(
            {"_id": str(item["_id"]), "seller_id": seller_id}
        )
        if current_item is None:
            return None
        if not _resource_freshness_allows_write(
            cast("dict[str, Any]", current_item),
            item,
            freshness_fields=("last_updated",),
            present_freshness_fields=present_freshness_fields,
        ):
            return None
        return cast("dict[str, Any]", current_item)

    async def _record_status_side_effects_for_accepted_item(
        self, item: dict[str, Any], *, seller_id: str, observed_at: datetime
    ) -> dict[str, Any] | None:
        status_observation = await self._record_item_status_observation(
            item, seller_id=seller_id, observed_at=observed_at
        )
        if not status_observation.applied:
            return None
        latest_state = await self._latest_matching_item_status_state(
            item_id=str(item["_id"]),
            seller_id=seller_id,
            status=item.get("status"),
            observed_at=_state_last_observed_at(status_observation.state),
        )
        if latest_state is None:
            return None
        return latest_state

    async def _item_observation_can_mutate_status_side_effects(
        self,
        item: dict[str, Any],
        *,
        seller_id: str,
        present_freshness_fields: Sequence[str],
    ) -> bool:
        current_item = await self._db["items"].find_one(
            {"_id": str(item["_id"]), "seller_id": seller_id}
        )
        return _resource_freshness_allows_write(
            current_item,
            item,
            freshness_fields=("last_updated",),
            present_freshness_fields=present_freshness_fields,
        )

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
        self,
        item: dict[str, Any],
        *,
        seller_id: str,
        status_state: dict[str, Any],
        present_freshness_fields: Sequence[str],
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
        if await _insert_resource_if_absent(collection, item, seller_id=seller_id):
            return True
        result = await collection.replace_one(
            _merge_write_guards(
                {"_id": item["_id"], "seller_id": seller_id},
                _status_observed_at_guard("status_observed_at", observed_at),
                _freshness_write_guard(
                    item,
                    freshness_fields=("last_updated",),
                    present_freshness_fields=present_freshness_fields,
                ),
            ),
            item,
            upsert=False,
        )
        matched_count = int(result.matched_count)
        return matched_count > 0

    async def _refresh_item_read_models(
        self, item: dict[str, Any], *, seller_id: str, status_state: dict[str, Any] | None
    ) -> None:
        if status_state is not None:
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
            if status_state is None:
                await self._db["sheets_item_formula_rows"].replace_one(
                    {"_id": formula_row_doc["_id"]}, formula_row_doc, upsert=True
                )
            else:
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

    async def _reconcile_item_status_fields(
        self, *, item_id: str, seller_id: str, item_snapshot: dict[str, Any] | None = None
    ) -> None:
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
        filter_spec = _merge_write_guards(
            {
                "_id": item_id,
                "seller_id": seller_id,
            },
            _status_observed_at_guard("status_observed_at", observed_at),
            _freshness_write_guard(item_snapshot, freshness_fields=("last_updated",))
            if item_snapshot is not None
            else {},
        )
        await collection.update_one(
            filter_spec,
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
        observed_at = require_bson_ms_utc_datetime(self._clock())
        document = _canonical_order_document(
            resource, seller_id=seller_id, sale_fee_synced_at=observed_at
        )
        order_written = await _replace_resource_if_fresh(
            self._db["orders"],
            document,
            seller_id=seller_id,
            freshness_fields=("last_updated", "date_closed", "date_created"),
            present_freshness_fields=_order_present_freshness_fields(resource),
        )
        if not order_written:
            return
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
        await _replace_resource_if_fresh(
            self._db["shipments"],
            document,
            seller_id=seller_id,
            freshness_fields=("last_updated",),
        )

    async def _persist_question(self, *, seller_id: str, resource: dict[str, Any]) -> None:
        document = _canonical_question_document(
            resource,
            seller_id=seller_id,
            observed_at=require_bson_ms_utc_datetime(self._clock()),
        )
        await _replace_question_if_fresh(
            self._db["questions"],
            document,
            seller_id=seller_id,
            present_freshness_fields=_question_present_freshness_fields(resource),
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


def _item_with_preserved_enrichment(
    document: dict[str, Any], existing: dict[str, Any] | None
) -> dict[str, Any]:
    if existing is None:
        return document
    merged = dict(document)
    preserved_any = False
    state_changed = False
    existing_state = schema_safe_enrichment_state(existing.get("enrichment_state"))
    incoming_state = schema_safe_enrichment_state(merged.get("enrichment_state"))
    merged_state = dict(incoming_state or {})
    for field in (
        "seller_shipping_cost",
        "current_promotion",
        "listing_fee_projection",
        "listing_price_fixed_fee",
    ):
        if field not in merged and existing.get(field) is not None:
            if field == "seller_shipping_cost" and not _seller_shipping_basis_matches(
                existing_state, basis=_item_shipping_basis(merged)
            ):
                state = existing_state.get(field) if existing_state is not None else None
                merged_state[field] = enrichment_state(
                    source=_state_source(
                        state,
                        fallback="/users/{seller_id}/shipping_options/free",
                    ),
                    status="basis_mismatch",
                    synced_at=_state_synced_at(merged, state),
                    reason="basis_changed",
                    basis=_item_shipping_basis(merged),
                )
                state_changed = True
                continue
            merged[field] = existing[field]
            preserved_any = True
            if existing_state is not None and field in existing_state and field not in merged_state:
                merged_state[field] = existing_state[field]
    if existing_state is not None and (preserved_any or state_changed or incoming_state is None):
        merged_state = {**existing_state, **merged_state}
    if merged_state:
        merged["enrichment_state"] = merged_state
    return merged


def _seller_shipping_basis_matches(
    existing_state: dict[str, Any] | None, *, basis: dict[str, Any]
) -> bool:
    if not basis or existing_state is None:
        return False
    state = existing_state.get("seller_shipping_cost")
    if not isinstance(state, dict) or state.get("status") != "trusted":
        return False
    expected_hash = basis_hash(basis)
    if expected_hash is not None and state.get("basis_hash") == expected_hash:
        return True
    state_basis = state.get("basis")
    return isinstance(state_basis, dict) and bounded_basis(state_basis) == bounded_basis(basis)


def _item_shipping_basis(item: dict[str, Any]) -> dict[str, Any]:
    shipping = item.get("shipping")
    shipping_values = shipping if isinstance(shipping, dict) else {}
    basis: dict[str, Any] = {}
    for key, value in {
        "site_id": item.get("site_id") or _site_from_item_id(str(item.get("_id") or "")),
        "category_id": item.get("category_id"),
        "currency_id": item.get("currency_id"),
        "listing_type_id": item.get("listing_type_id"),
        "price": item.get("price"),
        "shipping_mode": shipping_values.get("mode") or item.get("shipping_mode"),
        "logistic_type": shipping_values.get("logistic_type"),
        "billable_weight": item.get("billable_weight") or shipping_values.get("billable_weight"),
        "tags": item.get("tags"),
    }.items():
        if value is not None:
            basis[key] = value
    return basis


def _site_from_item_id(item_id: str) -> str | None:
    normalized = item_id.strip().upper()
    return normalized[:3] if len(normalized) >= 3 and normalized[:3].isalpha() else None


def _state_source(state: Any, *, fallback: str) -> str:
    if isinstance(state, dict) and isinstance(state.get("source"), str):
        return str(state["source"])
    return fallback


def _state_synced_at(item: dict[str, Any], state: Any) -> datetime:
    synced_at = item.get("last_meli_sync_at")
    if isinstance(synced_at, datetime):
        return synced_at
    state_synced_at = state.get("synced_at") if isinstance(state, dict) else None
    if isinstance(state_synced_at, datetime):
        return state_synced_at
    return datetime.now(UTC)


def _canonical_order_document(
    resource: dict[str, Any], *, seller_id: str, sale_fee_synced_at: datetime
) -> dict[str, Any]:
    order_id = _string_id(resource.get("_id") or resource.get("id"))
    last_updated = (
        resource.get("last_updated")
        or resource.get("date_last_updated")
        or resource.get("updated_at")
    )
    model = Order.model_validate(
        {
            **resource,
            "_id": order_id,
            "seller_id": seller_id,
            "last_updated": last_updated,
            "buyer_id": _buyer_id(resource),
            "shipment_id": _shipment_id(resource),
            "meli_pack_id": _meli_pack_id(resource),
            "items": _order_items(resource, sale_fee_synced_at=sale_fee_synced_at),
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


def _canonical_question_document(
    resource: dict[str, Any], *, seller_id: str, observed_at: datetime
) -> dict[str, Any]:
    question_id = _string_id(resource.get("_id") or resource.get("id"))
    date_updated = (
        resource.get("date_updated") or resource.get("last_updated") or resource.get("updated_at")
    )
    model = Question.model_validate(
        {
            **resource,
            "_id": question_id,
            "seller_id": seller_id,
            "item_id": _question_item_id(resource),
            "text": str(resource.get("text") or ""),
            "status": str(resource.get("status") or "UNANSWERED").upper(),
            "from_user_id": _question_from_user_id(resource),
            "date_created": resource.get("date_created") or observed_at,
            "date_updated": date_updated,
            "schema_version": current_schema_version("questions"),
        }
    )
    return cast(
        "dict[str, Any]",
        _bson_safe(model.model_dump(by_alias=True, mode="python", exclude_none=True)),
    )


def _resource_freshness_allows_write(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    *,
    freshness_fields: Sequence[str],
    present_freshness_fields: Sequence[str] | None = None,
) -> bool:
    if existing is None:
        return True
    return any(
        _freshness_condition_matches(existing, condition)
        for condition in _freshness_write_conditions(
            incoming,
            freshness_fields=freshness_fields,
            present_freshness_fields=present_freshness_fields,
        )
    )


def _freshness_condition_matches(document: dict[str, Any], condition: dict[str, Any]) -> bool:
    for field, expected in condition.items():
        actual = _document_path_value(document, field)
        if isinstance(expected, dict) and "$exists" in expected:
            if (actual is not None) != expected["$exists"]:
                return False
            continue
        if isinstance(expected, dict) and "$lte" in expected:
            actual_observed_at = bson_ms_utc_datetime(actual)
            expected_observed_at = bson_ms_utc_datetime(expected["$lte"])
            if actual_observed_at is None or expected_observed_at is None:
                return False
            if actual_observed_at > expected_observed_at:
                return False
            continue
        if actual != expected:
            return False
    return True


async def _replace_resource_if_fresh(
    collection: Any,
    document: dict[str, Any],
    *,
    seller_id: str,
    freshness_fields: Sequence[str],
    present_freshness_fields: Sequence[str] | None = None,
) -> bool:
    if await _insert_resource_if_absent(collection, document, seller_id=seller_id):
        return True
    result = await collection.replace_one(
        _fresh_resource_write_filter(
            document,
            seller_id=seller_id,
            freshness_fields=freshness_fields,
            present_freshness_fields=present_freshness_fields,
        ),
        document,
        upsert=False,
    )
    matched_count = int(result.matched_count)
    return matched_count > 0


async def _insert_resource_if_absent(
    collection: Any, document: dict[str, Any], *, seller_id: str
) -> bool:
    insert_result = await collection.update_one(
        {"_id": document["_id"], "seller_id": seller_id},
        {"$setOnInsert": document},
        upsert=True,
    )
    return insert_result.upserted_id is not None


def _fresh_resource_write_filter(
    document: dict[str, Any],
    *,
    seller_id: str,
    freshness_fields: Sequence[str],
    present_freshness_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    filter_spec: dict[str, Any] = {"_id": document["_id"], "seller_id": seller_id}
    return _merge_write_guards(
        filter_spec,
        _freshness_write_guard(
            document,
            freshness_fields=freshness_fields,
            present_freshness_fields=present_freshness_fields,
        ),
    )


def _freshness_write_guard(
    document: dict[str, Any],
    *,
    freshness_fields: Sequence[str],
    present_freshness_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    freshness_conditions = _freshness_write_conditions(
        document,
        freshness_fields=freshness_fields,
        present_freshness_fields=present_freshness_fields,
    )
    return {"$or": freshness_conditions} if freshness_conditions else {}


def _freshness_write_conditions(
    document: dict[str, Any],
    *,
    freshness_fields: Sequence[str],
    present_freshness_fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    missing_prior_fields: dict[str, Any] = {}
    present_fields = set(present_freshness_fields) if present_freshness_fields is not None else None
    for field in freshness_fields:
        incoming_observed_at = (
            bson_ms_utc_datetime(_document_path_value(document, field))
            if present_fields is None or field in present_fields
            else None
        )
        if incoming_observed_at is None:
            missing_prior_fields = {**missing_prior_fields, field: {"$exists": False}}
            continue
        conditions.append({**missing_prior_fields, field: {"$lte": incoming_observed_at}})
        missing_prior_fields = {**missing_prior_fields, field: {"$exists": False}}
    if missing_prior_fields:
        conditions.append(dict(missing_prior_fields))
    return conditions


async def _replace_question_if_fresh(
    collection: Any,
    document: dict[str, Any],
    *,
    seller_id: str,
    present_freshness_fields: Sequence[str],
) -> bool:
    if await _insert_resource_if_absent(collection, document, seller_id=seller_id):
        return True
    result = await collection.replace_one(
        _question_write_filter(
            document,
            seller_id=seller_id,
            present_freshness_fields=present_freshness_fields,
        ),
        document,
        upsert=False,
    )
    matched_count = int(result.matched_count)
    return matched_count > 0


def _question_write_filter(
    document: dict[str, Any], *, seller_id: str, present_freshness_fields: Sequence[str]
) -> dict[str, Any]:
    return _fresh_resource_write_filter(
        document,
        seller_id=seller_id,
        freshness_fields=("answer.date_created", "date_updated", "date_created"),
        present_freshness_fields=present_freshness_fields,
    )


def _merge_write_guards(base_filter: dict[str, Any], *guards: dict[str, Any]) -> dict[str, Any]:
    filter_spec = dict(base_filter)
    and_guards = [guard for guard in guards if guard]
    if not and_guards:
        return filter_spec
    if len(and_guards) == 1:
        filter_spec.update(and_guards[0])
        return filter_spec
    filter_spec["$and"] = and_guards
    return filter_spec


def _order_present_freshness_fields(resource: dict[str, Any]) -> tuple[str, ...]:
    fields: list[str] = []
    if any(
        resource.get(field) is not None
        for field in ("last_updated", "date_last_updated", "updated_at")
    ):
        fields.append("last_updated")
    if resource.get("date_closed") is not None:
        fields.append("date_closed")
    if resource.get("date_created") is not None:
        fields.append("date_created")
    return tuple(fields)


def _item_present_freshness_fields(resource: dict[str, Any]) -> tuple[str, ...]:
    if any(resource.get(field) is not None for field in ("last_updated", "updated_at")):
        return ("last_updated",)
    return ()


def _question_present_freshness_fields(resource: dict[str, Any]) -> tuple[str, ...]:
    fields: list[str] = []
    if _document_path_value(resource, "answer.date_created") is not None:
        fields.append("answer.date_created")
    if any(
        resource.get(field) is not None for field in ("date_updated", "last_updated", "updated_at")
    ):
        fields.append("date_updated")
    if resource.get("date_created") is not None:
        fields.append("date_created")
    return tuple(fields)


def _document_path_value(document: dict[str, Any], dotted_path: str) -> Any:
    value: Any = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


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


def _latest_item_status_history_observed_at(item: dict[str, Any]) -> datetime | None:
    observed_values = [
        observed_at
        for field in ("status_observed_at", "status_started_at", "last_status_change_at")
        if (observed_at := bson_ms_utc_datetime(item.get(field))) is not None
    ]
    return max(observed_values) if observed_values else None


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


def _order_items(resource: dict[str, Any], *, sale_fee_synced_at: datetime) -> list[dict[str, Any]]:
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
        sale_fee = _safe_order_sale_fee(raw_item.get("sale_fee"))
        if sale_fee is not None:
            normalized["sale_fee"] = sale_fee
            normalized["sale_fee_source"] = "/orders/{id}"
            normalized["sale_fee_synced_at"] = sale_fee_synced_at
        items.append(normalized)
    return items


def _safe_order_sale_fee(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    if isinstance(value, Decimal128):
        parsed = value.to_decimal()
    elif isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


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


def _question_item_id(resource: dict[str, Any]) -> str:
    item = resource.get("item")
    if isinstance(item, dict):
        return _string_id(item.get("id") or item.get("item_id"))
    return _string_id(resource.get("item_id"))


def _question_from_user_id(resource: dict[str, Any]) -> str:
    from_user = resource.get("from")
    if isinstance(from_user, dict):
        return _string_id(from_user.get("id") or from_user.get("user_id"))
    return _string_id(resource.get("from_user_id") or resource.get("user_id"))


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
