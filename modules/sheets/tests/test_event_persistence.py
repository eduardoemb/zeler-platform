from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from bson import BSON
from bson.decimal128 import Decimal128

from zeler_platform_core.models import ItemStatusState, ItemStatusTransition
from zeler_sheets.event_persistence import SheetsEventPersistence, StatusObservationContentionError

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
PAUSED_AT = datetime(2026, 6, 2, 9, 30, tzinfo=UTC)
REOBSERVED_AT = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)
MICROSECOND_OBSERVED_AT = datetime(2026, 6, 2, 9, 30, 0, 987654, tzinfo=UTC)


def _item_resource(status: str) -> dict[str, Any]:
    return {
        "id": "MLA1",
        "title": "Premium widget",
        "price": "149.99",
        "base_price": "159.99",
        "available_quantity": 7,
        "status": status,
        "category_id": "MLA123",
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "date_created": "2026-05-01T10:00:00+00:00",
        "last_updated": "2026-05-30T11:00:00+00:00",
    }


class FakeReplaceResult:
    def __init__(
        self, *, matched_count: int = 1, modified_count: int = 1, upserted_id: str | None = None
    ) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    async def to_list(self, *, length: int | None = None) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            str(document["_id"]): dict(document) for document in documents or []
        }
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        for document_id, document in self.documents.items():
            if _matches_filter(document, filter_spec):
                self.documents[document_id] = dict(replacement)
                return FakeReplaceResult()
        if upsert:
            document_id = str(replacement["_id"])
            self.documents[document_id] = dict(replacement)
            return FakeReplaceResult(matched_count=0, modified_count=0, upserted_id=document_id)
        return FakeReplaceResult(matched_count=0, modified_count=0)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        for document in self.documents.values():
            if _matches_filter(document, filter_spec):
                if "$set" in update:
                    for path, value in update["$set"].items():
                        _set_path(document, path, value)
                if "$unset" in update:
                    for path in update["$unset"]:
                        _unset_path(document, path)
                return FakeReplaceResult()
        if upsert and "$setOnInsert" in update:
            document = dict(update["$setOnInsert"])
            document_id = str(document["_id"])
            self.documents[document_id] = document
            return FakeReplaceResult(matched_count=0, modified_count=0, upserted_id=document_id)
        return FakeReplaceResult(matched_count=0, modified_count=0)

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        documents = [
            document
            for document in self.documents.values()
            if _matches_filter(document, filter_spec)
        ]
        return FakeCursor(documents)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents.values():
            if _matches_filter(document, filter_spec):
                return document
        return None


class RacingStatusCollection(FakeCollection):
    def __init__(self, *, stale_snapshot: dict[str, Any], stale_reads: int) -> None:
        super().__init__()
        self._stale_snapshot = dict(stale_snapshot)
        self._stale_reads = stale_reads

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        if self._stale_reads > 0 and filter_spec.get("_id") == self._stale_snapshot["_id"]:
            self._stale_reads -= 1
            return dict(self._stale_snapshot)
        return await super().find_one(filter_spec)


class SupersedingStatusCollection(FakeCollection):
    def __init__(self, *, superseding_state: dict[str, Any]) -> None:
        super().__init__()
        self._superseding_state = dict(superseding_state)
        self._superseded = False

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        result = await super().replace_one(filter_spec, replacement, upsert=upsert)
        if result.matched_count > 0 and not self._superseded:
            self._superseded = True
            self.documents[str(self._superseding_state["_id"])] = dict(self._superseding_state)
        return result


class SupersedingReplaceCollection(FakeCollection):
    def __init__(self, *, supersede: Any) -> None:
        super().__init__()
        self._supersede = supersede
        self._superseded = False

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        if not self._superseded:
            self._superseded = True
            self._supersede()
        return await super().replace_one(filter_spec, replacement, upsert=upsert)


class CorrectingStatusBeforeReplaceCollection(FakeCollection):
    def __init__(self, *, corrected_state_fields: dict[str, Any]) -> None:
        super().__init__()
        self._corrected_state_fields = dict(corrected_state_fields)
        self._corrected_before_replace = False

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        if not self._corrected_before_replace:
            self._corrected_before_replace = True
            document = self.documents.get(str(replacement["_id"]))
            if document is not None:
                corrected = {**document, **self._corrected_state_fields}
                self.documents[str(corrected["_id"])] = dict(corrected)
        return await super().replace_one(filter_spec, replacement, upsert=upsert)


class AlwaysLosingStatusCollection(FakeCollection):
    def __init__(self, *, winning_states: list[dict[str, Any]]) -> None:
        super().__init__()
        self._winning_states = [dict(state) for state in winning_states]
        self._read_index = 0

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        self.replace_calls.append((dict(filter_spec), dict(replacement), upsert))
        return FakeReplaceResult(matched_count=0, modified_count=0)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        if self._winning_states:
            self.documents[str(self._winning_states[0]["_id"])] = dict(self._winning_states[0])
        return FakeReplaceResult(matched_count=0, modified_count=0)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        if self._read_index < len(self._winning_states):
            state = self._winning_states[self._read_index]
            self._read_index += 1
            self.documents[str(state["_id"])] = dict(state)
            return dict(state)
        return await super().find_one(filter_spec)


class SupersedingFindThenReplaceCollection(FakeCollection):
    def __init__(self, *, stale: dict[str, Any], superseding: dict[str, Any]) -> None:
        super().__init__([stale])
        self._superseding = dict(superseding)
        self._superseded = False

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        if not self._superseded:
            self._superseded = True
            self.documents[str(self._superseding["_id"])] = dict(self._superseding)
        return await super().replace_one(filter_spec, replacement, upsert=upsert)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        if not self._superseded:
            self._superseded = True
            self.documents[str(self._superseding["_id"])] = dict(self._superseding)
        return await super().update_one(filter_spec, update, upsert=upsert)


class CorrectingStatusStateAfterWriteCollection(FakeCollection):
    def __init__(self, *, corrected_state_fields: dict[str, Any]) -> None:
        super().__init__()
        self._corrected_state_fields = dict(corrected_state_fields)
        self._state_write_seen = False

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> FakeReplaceResult:
        result = await super().replace_one(filter_spec, replacement, upsert=upsert)
        if result.matched_count > 0 or result.upserted_id is not None:
            self._state_write_seen = True
        return result

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        document = await super().find_one(filter_spec)
        if self._state_write_seen and document is not None:
            corrected = {**document, **self._corrected_state_fields}
            self.documents[str(corrected["_id"])] = dict(corrected)
            return dict(corrected)
        return document


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$or":
            if not any(_matches_filter(document, option) for option in expected):
                return False
            continue
        actual = _nested_value(document, key)
        if isinstance(expected, dict) and "$exists" in expected:
            exists = actual is not None
            if exists != expected["$exists"]:
                return False
            continue
        if isinstance(expected, dict) and "$lte" in expected:
            if actual is None or not _safe_lte(actual, expected["$lte"]):
                return False
            continue
        if isinstance(expected, dict) and "$gt" in expected:
            if actual is None or not _safe_gt(actual, expected["$gt"]):
                return False
            continue
        if not _values_equal(actual, expected):
            return False
    return True


def _safe_lte(actual: Any, expected: Any) -> bool:
    left = _bson_ms_utc(actual)
    right = _bson_ms_utc(expected)
    if left is not None and right is not None:
        return left <= right
    try:
        return bool(actual <= expected)
    except TypeError:
        return False


def _safe_gt(actual: Any, expected: Any) -> bool:
    left = _bson_ms_utc(actual)
    right = _bson_ms_utc(expected)
    if left is not None and right is not None:
        return left > right
    try:
        return bool(actual > expected)
    except TypeError:
        return False


def _values_equal(actual: Any, expected: Any) -> bool:
    left = _bson_ms_utc(actual)
    right = _bson_ms_utc(expected)
    if left is not None and right is not None:
        return left == right
    return bool(actual == expected)


def _bson_ms_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.replace(microsecond=(aware.microsecond // 1000) * 1000)


def _bson_round_trip(document: dict[str, Any]) -> dict[str, Any]:
    return BSON(BSON.encode(document)).decode()


def _nested_value(document: dict[str, Any], key: str) -> Any:
    value: Any = document
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set_path(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target.get(part), dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value


def _unset_path(document: dict[str, Any], dotted_path: str) -> None:
    target: Any = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or not isinstance(target.get(part), dict):
            return
        target = target[part]
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def test_status_history_models_accept_forward_only_transition_state_documents() -> None:
    transition_payload = {
        "_id": "82453304:MLA1:2026-06-02T09:30:00+00:00:active:paused",
        "seller_id": 82453304,
        "item_id": "MLA1",
        "from_status": "active",
        "to_status": "paused",
        "observed_at": PAUSED_AT,
        "source": "sheets_event_persistence",
        "schema_version": 1,
    }
    transition = ItemStatusTransition.model_validate(transition_payload)
    state = ItemStatusState.model_validate(
        {
            "_id": "82453304:MLA1",
            "seller_id": 82453304,
            "item_id": "MLA1",
            "current_status": "paused",
            "first_observed_at": NOW,
            "last_observed_at": PAUSED_AT,
            "status_started_at": PAUSED_AT,
            "paused_since": PAUSED_AT,
            "last_status_change_at": PAUSED_AT,
            "schema_version": 1,
        }
    )

    assert transition.seller_id == "82453304"
    assert transition.from_status == "active"
    assert transition.to_status == "paused"
    assert state.id == "82453304:MLA1"
    assert state.paused_since == PAUSED_AT

    with pytest.raises(ValueError):
        ItemStatusTransition.model_validate(
            transition_payload | {"source": "sheets_item_detail_enrichment"}
        )


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


@pytest.mark.asyncio
async def test_observed_transition_writes_history_state_and_formula_scalars() -> None:
    moments = iter([NOW, PAUSED_AT])
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: next(moments))

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("active")
    )
    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert len(db["item_status_transitions"].documents) == 1
    transition = next(iter(db["item_status_transitions"].documents.values()))
    assert transition["seller_id"] == "82453304"
    assert transition["item_id"] == "MLA1"
    assert transition["from_status"] == "active"
    assert transition["to_status"] == "paused"
    assert transition["observed_at"] == PAUSED_AT
    assert transition["source"] == "sheets_event_persistence"

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["first_observed_at"] == NOW
    assert state["last_observed_at"] == PAUSED_AT
    assert state["status_started_at"] == PAUSED_AT
    assert state["paused_since"] == PAUSED_AT
    assert state["last_status_change_at"] == PAUSED_AT

    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "paused"
    assert row["current"]["status_started_at"] == PAUSED_AT
    assert row["current"]["paused_since"] == PAUSED_AT
    assert row["current"]["last_status_change_at"] == PAUSED_AT


@pytest.mark.asyncio
async def test_status_timestamps_are_normalized_to_bson_millisecond_utc_precision() -> None:
    first_observed_at = datetime(2026, 5, 30, 12, 0, 0, 123456, tzinfo=UTC)
    expected_first_observed_at = datetime(2026, 5, 30, 12, 0, 0, 123000, tzinfo=UTC)
    expected_paused_at = datetime(2026, 6, 2, 9, 30, 0, 987000, tzinfo=UTC)
    moments = iter([first_observed_at, MICROSECOND_OBSERVED_AT])
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: next(moments))

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("active")
    )
    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["first_observed_at"] == expected_first_observed_at
    assert state["last_observed_at"] == expected_paused_at
    assert state["status_started_at"] == expected_paused_at
    assert state["paused_since"] == expected_paused_at
    assert state["last_status_change_at"] == expected_paused_at
    transition = next(iter(db["item_status_transitions"].documents.values()))
    assert transition["observed_at"] == expected_paused_at
    assert transition["_id"] == ("82453304:MLA1:2026-06-02T09:30:00.987000+00:00:active:paused")
    item = db["items"].documents["MLA1"]
    assert item["status_observed_at"] == expected_paused_at
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status_observed_at"] == expected_paused_at
    assert row["current"]["paused_since"] == expected_paused_at


@pytest.mark.asyncio
async def test_mongo_round_tripped_status_state_uses_utc_bson_ms_for_comparisons() -> None:
    active_at = datetime(2026, 5, 30, 12, 0, 0, 123456, tzinfo=UTC)
    paused_at = datetime(2026, 5, 30, 12, 0, 1, 456789, tzinfo=UTC)
    expected_paused_at = datetime(2026, 5, 30, 12, 0, 1, 456000, tzinfo=UTC)
    moments = iter([active_at, paused_at])
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: next(moments))

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("active")
    )
    state = db["item_status_states"].documents["82453304:MLA1"]
    db["item_status_states"].documents["82453304:MLA1"] = _bson_round_trip(state)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    persisted_state = db["item_status_states"].documents["82453304:MLA1"]
    assert persisted_state["current_status"] == "paused"
    assert persisted_state["last_observed_at"] == expected_paused_at
    assert persisted_state["paused_since"] == expected_paused_at
    assert len(db["item_status_transitions"].documents) == 1


@pytest.mark.asyncio
async def test_older_same_status_paused_observation_preserves_earliest_paused_start() -> None:
    later_paused_at = datetime(2026, 6, 2, 9, 30, 0, 999000, tzinfo=UTC)
    earlier_paused_at = datetime(2026, 6, 2, 9, 29, 59, 111222, tzinfo=UTC)
    expected_earliest = datetime(2026, 6, 2, 9, 29, 59, 111000, tzinfo=UTC)
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": later_paused_at,
        "status_started_at": later_paused_at,
        "paused_since": later_paused_at,
        "last_status_change_at": later_paused_at,
        "schema_version": 1,
    }
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Fresh title",
        "status": "paused",
        "status_observed_at": later_paused_at,
        "status_started_at": later_paused_at,
        "paused_since": later_paused_at,
        "last_status_change_at": later_paused_at,
    }
    db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"] = {
        "_id": "82453304:SKU-1:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "current": {
            "title": "Fresh title",
            "status": "paused",
            "status_observed_at": later_paused_at,
            "status_started_at": later_paused_at,
            "paused_since": later_paused_at,
            "last_status_change_at": later_paused_at,
        },
    }
    stale_resource = {**_item_resource("paused"), "title": "Stale title"}
    persistence = SheetsEventPersistence(db=db, clock=lambda: earlier_paused_at)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=stale_resource
    )

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["last_observed_at"] == later_paused_at
    assert state["paused_since"] == expected_earliest
    assert state["status_started_at"] == expected_earliest
    assert state["last_status_change_at"] == expected_earliest
    item = db["items"].documents["MLA1"]
    assert item["title"] == "Fresh title"
    assert item["status_observed_at"] == later_paused_at
    assert item["paused_since"] == expected_earliest
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["title"] == "Fresh title"
    assert row["current"]["status_observed_at"] == later_paused_at
    assert row["current"]["paused_since"] == expected_earliest
    assert db["item_status_transitions"].documents == {}


@pytest.mark.asyncio
async def test_equal_observed_paused_correction_reconciles_scalar_tuple_read_models() -> None:
    observed_at = datetime(2026, 6, 2, 9, 30, 0, 555000, tzinfo=UTC)
    invalid_later_paused_since = datetime(2026, 6, 2, 9, 30, 1, 111000, tzinfo=UTC)
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": observed_at,
        "status_started_at": invalid_later_paused_since,
        "paused_since": invalid_later_paused_since,
        "last_status_change_at": invalid_later_paused_since,
        "schema_version": 1,
    }
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Fresh title",
        "status": "paused",
        "status_observed_at": observed_at,
        "status_started_at": invalid_later_paused_since,
        "paused_since": invalid_later_paused_since,
        "last_status_change_at": invalid_later_paused_since,
    }
    db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"] = {
        "_id": "82453304:SKU-1:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "current": {
            "title": "Fresh title",
            "status": "paused",
            "status_observed_at": observed_at,
            "status_started_at": invalid_later_paused_since,
            "paused_since": invalid_later_paused_since,
            "last_status_change_at": invalid_later_paused_since,
        },
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: observed_at)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["last_observed_at"] == observed_at
    assert state["status_started_at"] == observed_at
    assert state["paused_since"] == observed_at
    assert state["last_status_change_at"] == observed_at
    item = db["items"].documents["MLA1"]
    assert item["title"] == "Fresh title"
    assert item["status_observed_at"] == observed_at
    assert item["status_started_at"] == observed_at
    assert item["paused_since"] == observed_at
    assert item["last_status_change_at"] == observed_at
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["title"] == "Fresh title"
    assert row["current"]["status_observed_at"] == observed_at
    assert row["current"]["status_started_at"] == observed_at
    assert row["current"]["paused_since"] == observed_at
    assert row["current"]["last_status_change_at"] == observed_at
    assert db["item_status_transitions"].documents == {}


@pytest.mark.asyncio
async def test_same_status_paused_correction_overlays_corrected_state_before_publication() -> None:
    stale_paused_since = datetime(2026, 6, 2, 9, 30, 0, 999000, tzinfo=UTC)
    corrected_paused_since = datetime(2026, 6, 2, 9, 29, 59, 111000, tzinfo=UTC)
    db = FakeDb()
    state_collection = CorrectingStatusStateAfterWriteCollection(
        corrected_state_fields={
            "status_started_at": corrected_paused_since,
            "paused_since": corrected_paused_since,
            "last_status_change_at": corrected_paused_since,
        }
    )
    state_collection.documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": stale_paused_since,
        "status_started_at": stale_paused_since,
        "paused_since": stale_paused_since,
        "last_status_change_at": stale_paused_since,
        "schema_version": 1,
    }
    db.collections["item_status_states"] = state_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: REOBSERVED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["last_observed_at"] == REOBSERVED_AT
    assert state["paused_since"] == corrected_paused_since
    item = db["items"].documents["MLA1"]
    assert item["status_observed_at"] == REOBSERVED_AT
    assert item["paused_since"] == corrected_paused_since
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status_observed_at"] == REOBSERVED_AT
    assert row["current"]["paused_since"] == corrected_paused_since


@pytest.mark.asyncio
async def test_status_state_cas_rejects_equal_observed_stale_scalar_tuple_race() -> None:
    stale_paused_since = datetime(2026, 6, 2, 9, 30, 0, tzinfo=UTC)
    corrected_paused_since = datetime(2026, 6, 2, 9, 29, 59, 111000, tzinfo=UTC)
    state_collection = CorrectingStatusBeforeReplaceCollection(
        corrected_state_fields={
            "status_started_at": corrected_paused_since,
            "paused_since": corrected_paused_since,
            "last_status_change_at": corrected_paused_since,
        }
    )
    state_collection.documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": PAUSED_AT,
        "status_started_at": stale_paused_since,
        "paused_since": stale_paused_since,
        "last_status_change_at": stale_paused_since,
        "schema_version": 1,
    }
    db = FakeDb()
    db.collections["item_status_states"] = state_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: REOBSERVED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    first_filter = state_collection.replace_calls[0][0]
    assert first_filter["status_started_at"] == stale_paused_since
    assert first_filter["paused_since"] == stale_paused_since
    assert first_filter["last_status_change_at"] == stale_paused_since
    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["last_observed_at"] == REOBSERVED_AT
    assert state["status_started_at"] == corrected_paused_since
    assert state["paused_since"] == corrected_paused_since
    assert state["last_status_change_at"] == corrected_paused_since


@pytest.mark.asyncio
async def test_item_read_model_reconciles_scalar_tuple_after_state_correction_race() -> None:
    stale_paused_since = datetime(2026, 6, 2, 9, 30, 0, tzinfo=UTC)
    corrected_paused_since = datetime(2026, 6, 2, 9, 29, 59, 111000, tzinfo=UTC)
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": PAUSED_AT,
        "status_started_at": stale_paused_since,
        "paused_since": stale_paused_since,
        "last_status_change_at": stale_paused_since,
        "schema_version": 1,
    }

    def correct_state() -> None:
        state = db["item_status_states"].documents["82453304:MLA1"]
        state.update(
            {
                "status_started_at": corrected_paused_since,
                "paused_since": corrected_paused_since,
                "last_status_change_at": corrected_paused_since,
            }
        )

    db.collections["items"] = SupersedingReplaceCollection(supersede=correct_state)
    persistence = SheetsEventPersistence(db=db, clock=lambda: REOBSERVED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    item = db["items"].documents["MLA1"]
    assert item["status_observed_at"] == REOBSERVED_AT
    assert item["status_started_at"] == corrected_paused_since
    assert item["paused_since"] == corrected_paused_since
    assert item["last_status_change_at"] == corrected_paused_since
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status_observed_at"] == REOBSERVED_AT
    assert row["current"]["status_started_at"] == corrected_paused_since
    assert row["current"]["paused_since"] == corrected_paused_since
    assert row["current"]["last_status_change_at"] == corrected_paused_since


@pytest.mark.asyncio
async def test_formula_row_reconciles_scalar_tuple_after_state_correction_race() -> None:
    stale_paused_since = datetime(2026, 6, 2, 9, 30, 0, tzinfo=UTC)
    corrected_paused_since = datetime(2026, 6, 2, 9, 29, 59, 111000, tzinfo=UTC)
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "paused",
        "first_observed_at": NOW,
        "last_observed_at": PAUSED_AT,
        "status_started_at": stale_paused_since,
        "paused_since": stale_paused_since,
        "last_status_change_at": stale_paused_since,
        "schema_version": 1,
    }

    def correct_state() -> None:
        state = db["item_status_states"].documents["82453304:MLA1"]
        state.update(
            {
                "status_started_at": corrected_paused_since,
                "paused_since": corrected_paused_since,
                "last_status_change_at": corrected_paused_since,
            }
        )

    db.collections["sheets_item_formula_rows"] = SupersedingReplaceCollection(
        supersede=correct_state
    )
    persistence = SheetsEventPersistence(db=db, clock=lambda: REOBSERVED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    item = db["items"].documents["MLA1"]
    assert item["status_started_at"] == corrected_paused_since
    assert item["paused_since"] == corrected_paused_since
    assert item["last_status_change_at"] == corrected_paused_since
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status_observed_at"] == REOBSERVED_AT
    assert row["current"]["status_started_at"] == corrected_paused_since
    assert row["current"]["paused_since"] == corrected_paused_since
    assert row["current"]["last_status_change_at"] == corrected_paused_since


@pytest.mark.asyncio
async def test_repeated_paused_observation_does_not_append_duplicate_transition() -> None:
    moments = iter([NOW, PAUSED_AT, REOBSERVED_AT])
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: next(moments))

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("active")
    )
    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )
    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert len(db["item_status_transitions"].documents) == 1
    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["last_observed_at"] == REOBSERVED_AT
    assert state["paused_since"] == PAUSED_AT
    assert state["last_status_change_at"] == PAUSED_AT


@pytest.mark.asyncio
async def test_concurrent_status_observations_append_transition_only_for_state_winner() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    db = FakeDb()
    state_collection = RacingStatusCollection(stale_snapshot=active_state, stale_reads=2)
    state_collection.documents["82453304:MLA1"] = dict(active_state)
    db.collections["item_status_states"] = state_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await asyncio.gather(
        persistence._record_item_status_observation(
            {"_id": "MLA1", "status": "paused"},
            seller_id="82453304",
            observed_at=PAUSED_AT,
        ),
        persistence._record_item_status_observation(
            {"_id": "MLA1", "status": "paused"},
            seller_id="82453304",
            observed_at=REOBSERVED_AT,
        ),
    )

    transitions = list(db["item_status_transitions"].documents.values())
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition["from_status"] == "active"
    assert transition["to_status"] == "paused"

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["last_observed_at"] == REOBSERVED_AT
    assert state["paused_since"] == transition["observed_at"]
    assert state["last_status_change_at"] == transition["observed_at"]


@pytest.mark.asyncio
async def test_divergent_concurrent_status_observations_retry_loser() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    db = FakeDb()
    state_collection = RacingStatusCollection(stale_snapshot=active_state, stale_reads=2)
    state_collection.documents["82453304:MLA1"] = dict(active_state)
    db.collections["item_status_states"] = state_collection
    paused_persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)
    closed_persistence = SheetsEventPersistence(db=db, clock=lambda: REOBSERVED_AT)

    await asyncio.gather(
        paused_persistence.persist(
            event_type="items.updated",
            seller_id=82453304,
            resource=_item_resource("paused"),
        ),
        closed_persistence.persist(
            event_type="items.updated",
            seller_id=82453304,
            resource=_item_resource("closed"),
        ),
    )

    transitions = sorted(
        db["item_status_transitions"].documents.values(),
        key=lambda transition: transition["observed_at"],
    )
    assert [(transition["from_status"], transition["to_status"]) for transition in transitions] == [
        ("active", "paused"),
        ("paused", "closed"),
    ]

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "closed"
    assert state["status_started_at"] == REOBSERVED_AT
    assert state["last_status_change_at"] == REOBSERVED_AT
    assert "paused_since" not in state

    item = db["items"].documents["MLA1"]
    assert item["status"] == "closed"
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "closed"
    assert row["current"]["status_started_at"] == REOBSERVED_AT
    assert row["current"]["last_status_change_at"] == REOBSERVED_AT
    assert "paused_since" not in row["current"]


@pytest.mark.asyncio
async def test_status_observation_contention_beyond_retry_limit_raises_retryable_error() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    db = FakeDb()
    state_collection = AlwaysLosingStatusCollection(
        winning_states=[
            {**active_state, "current_status": "closed"},
            {**active_state, "current_status": "under_review"},
            {**active_state, "current_status": "payment_required"},
            {**active_state, "current_status": "inactive"},
        ]
    )
    db.collections["item_status_states"] = state_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    with pytest.raises(StatusObservationContentionError):
        await persistence._record_item_status_observation(
            {"_id": "MLA1", "status": "paused"},
            seller_id="82453304",
            observed_at=PAUSED_AT,
        )

    assert state_collection.replace_calls
    assert db["item_status_transitions"].documents == {}


@pytest.mark.asyncio
async def test_stale_observation_does_not_overwrite_superseding_read_models() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    closed_state = {
        **active_state,
        "current_status": "closed",
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    db = FakeDb()
    state_collection = SupersedingStatusCollection(superseding_state=closed_state)
    state_collection.documents["82453304:MLA1"] = dict(active_state)
    db.collections["item_status_states"] = state_collection
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "status": "closed",
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"] = {
        "_id": "82453304:SKU-1:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "current": {
            "status": "closed",
            "status_started_at": REOBSERVED_AT,
            "last_status_change_at": REOBSERVED_AT,
        },
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "closed"
    item = db["items"].documents["MLA1"]
    assert item["status"] == "closed"
    assert item["status_started_at"] == REOBSERVED_AT
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "closed"
    assert row["current"]["status_started_at"] == REOBSERVED_AT
    assert "paused_since" not in row["current"]


@pytest.mark.asyncio
async def test_older_observation_cannot_supersede_newer_accepted_state() -> None:
    closed_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "closed",
        "first_observed_at": NOW,
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
        "schema_version": 1,
    }
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = dict(closed_state)
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "status": "closed",
        "last_meli_sync_at": REOBSERVED_AT,
        "status_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert db["item_status_states"].documents["82453304:MLA1"] == closed_state
    assert db["item_status_transitions"].documents == {}
    assert db["items"].documents["MLA1"]["status"] == "closed"


@pytest.mark.asyncio
async def test_superseded_observation_repairs_stale_item_write() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    closed_state = {
        **active_state,
        "current_status": "closed",
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = dict(active_state)

    def supersede_state() -> None:
        db["item_status_states"].documents["82453304:MLA1"] = dict(closed_state)

    item_collection = SupersedingReplaceCollection(supersede=supersede_state)
    item_collection.documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "status": "closed",
        "last_meli_sync_at": REOBSERVED_AT,
        "status_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    db.collections["items"] = item_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    item = db["items"].documents["MLA1"]
    assert item["status"] == "closed"
    assert item["status_observed_at"] == REOBSERVED_AT
    assert item["status_started_at"] == REOBSERVED_AT
    assert "paused_since" not in item


@pytest.mark.asyncio
async def test_superseded_observation_repairs_stale_formula_row_write() -> None:
    active_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "active",
        "first_observed_at": NOW,
        "last_observed_at": NOW,
        "schema_version": 1,
    }
    closed_state = {
        **active_state,
        "current_status": "closed",
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = dict(active_state)

    def supersede_state() -> None:
        db["item_status_states"].documents["82453304:MLA1"] = dict(closed_state)

    formula_collection = SupersedingReplaceCollection(supersede=supersede_state)
    formula_collection.documents["82453304:SKU-1:MLA1"] = {
        "_id": "82453304:SKU-1:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "current": {
            "status": "closed",
            "status_observed_at": REOBSERVED_AT,
            "status_started_at": REOBSERVED_AT,
            "last_status_change_at": REOBSERVED_AT,
        },
    }
    db.collections["sheets_item_formula_rows"] = formula_collection
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "closed"
    assert row["current"]["status_observed_at"] == REOBSERVED_AT
    assert row["current"]["status_started_at"] == REOBSERVED_AT
    assert "paused_since" not in row["current"]


@pytest.mark.asyncio
async def test_item_reconciliation_preserves_newer_non_status_fields_during_race() -> None:
    closed_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "closed",
        "first_observed_at": NOW,
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
        "schema_version": 1,
    }
    stale_item = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Stale title",
        "status": "paused",
        "status_observed_at": PAUSED_AT,
        "paused_since": PAUSED_AT,
    }
    superseding_item = {
        **stale_item,
        "title": "Fresh title",
        "status": "closed",
        "status_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
    }
    superseding_item.pop("paused_since")
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = dict(closed_state)
    db.collections["items"] = SupersedingFindThenReplaceCollection(
        stale=stale_item, superseding=superseding_item
    )
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence._reconcile_item_status_fields(item_id="MLA1", seller_id="82453304")

    item = db["items"].documents["MLA1"]
    assert item["title"] == "Fresh title"
    assert item["status"] == "closed"
    assert item["status_observed_at"] == REOBSERVED_AT
    assert "paused_since" not in item


@pytest.mark.asyncio
async def test_formula_row_reconciliation_preserves_newer_non_status_fields_during_race() -> None:
    closed_state = {
        "_id": "82453304:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current_status": "closed",
        "first_observed_at": NOW,
        "last_observed_at": REOBSERVED_AT,
        "status_started_at": REOBSERVED_AT,
        "last_status_change_at": REOBSERVED_AT,
        "schema_version": 1,
    }
    stale_row = {
        "_id": "82453304:SKU-1:MLA1",
        "seller_id": "82453304",
        "item_id": "MLA1",
        "current": {
            "title": "Stale title",
            "status": "paused",
            "status_observed_at": PAUSED_AT,
            "paused_since": PAUSED_AT,
        },
    }
    superseding_row = {
        **stale_row,
        "current": {
            "title": "Fresh title",
            "status": "closed",
            "status_observed_at": REOBSERVED_AT,
            "status_started_at": REOBSERVED_AT,
            "last_status_change_at": REOBSERVED_AT,
        },
    }
    db = FakeDb()
    db["item_status_states"].documents["82453304:MLA1"] = dict(closed_state)
    db.collections["sheets_item_formula_rows"] = SupersedingFindThenReplaceCollection(
        stale=stale_row, superseding=superseding_row
    )
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence._reconcile_formula_row_status_fields(stale_row)

    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["title"] == "Fresh title"
    assert row["current"]["status"] == "closed"
    assert row["current"]["status_observed_at"] == REOBSERVED_AT
    assert "paused_since" not in row["current"]


@pytest.mark.asyncio
async def test_existing_item_snapshot_without_status_state_does_not_create_transition() -> None:
    db = FakeDb()
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "status": "active",
        "last_meli_sync_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: PAUSED_AT)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert db["item_status_transitions"].documents == {}
    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["first_observed_at"] == PAUSED_AT
    assert "status_started_at" not in state
    assert "paused_since" not in state
    assert "last_status_change_at" not in state
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "paused"
    assert "paused_since" not in row["current"]


@pytest.mark.asyncio
async def test_first_seen_paused_item_preserves_unknown_pause_start() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert db["item_status_transitions"].documents == {}
    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["first_observed_at"] == NOW
    assert state["last_observed_at"] == NOW
    assert "status_started_at" not in state
    assert "paused_since" not in state
    assert "last_status_change_at" not in state

    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "paused"
    assert "status_started_at" not in row["current"]
    assert "paused_since" not in row["current"]
    assert "last_status_change_at" not in row["current"]


@pytest.mark.asyncio
async def test_repeated_first_seen_paused_without_truth_stays_unknown() -> None:
    moments = iter([REOBSERVED_AT, PAUSED_AT])
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: next(moments))

    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )
    await persistence.persist(
        event_type="items.updated", seller_id=82453304, resource=_item_resource("paused")
    )

    assert db["item_status_transitions"].documents == {}
    state = db["item_status_states"].documents["82453304:MLA1"]
    assert state["current_status"] == "paused"
    assert state["first_observed_at"] == REOBSERVED_AT
    assert state["last_observed_at"] == REOBSERVED_AT
    assert "status_started_at" not in state
    assert "paused_since" not in state
    assert "last_status_change_at" not in state

    item = db["items"].documents["MLA1"]
    assert item["status"] == "paused"
    assert "status_started_at" not in item
    assert "paused_since" not in item
    assert "last_status_change_at" not in item
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["status"] == "paused"
    assert "status_started_at" not in row["current"]
    assert "paused_since" not in row["current"]
    assert "last_status_change_at" not in row["current"]


@pytest.mark.asyncio
async def test_persists_item_and_refreshes_sheetseller_read_models() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "permalink": "https://articulo.example/MLA1",
            "thumbnail": "https://img.example/MLA1.jpg",
            "catalog_product_id": "CAT-1",
            "inventory_id": "INV-ITEM-1",
            "listing_type_id": "gold_special",
            "shipping": {"logistic_type": "cross_docking", "free_shipping": False},
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "variations": [
                {"id": 101, "seller_custom_field": "var-101", "inventory_id": "INV-VAR-101"}
            ],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    assert item["_id"] == "MLA1"
    assert item["seller_id"] == "82453304"
    assert item["schema_version"] == 2
    assert item["last_meli_sync_at"] == NOW
    assert item["price"] == Decimal128("149.99")
    assert item["listing_type_id"] == "gold_special"
    BSON.encode(item)

    assert sorted(db["sheets_item_sku_index"].documents) == [
        "82453304:SKU-1:MLA1:item",
        "82453304:VAR-101:MLA1:101",
    ]
    assert sorted(db["sheets_item_formula_rows"].documents) == [
        "82453304:SKU-1:MLA1",
        "82453304:VAR-101:MLA1:101",
    ]
    variation_row = db["sheets_item_formula_rows"].documents["82453304:VAR-101:MLA1:101"]
    assert variation_row["inventory_id"] == "INV-VAR-101"
    assert variation_row["current"]["title"] == "Premium widget"
    assert variation_row["current"]["listing_type_id"] == "gold_special"
    assert variation_row["current"]["shipping_logistic_type"] == "cross_docking"
    assert variation_row["current"]["shipping_payer"] == "Comprador"


@pytest.mark.asyncio
async def test_item_event_preserves_trusted_enrichment_and_refreshes_formula_row() -> None:
    db = FakeDb()
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Previous widget",
        "price": Decimal128("149.99"),
        "base_price": Decimal128("159.99"),
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA123",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
        "billable_weight": Decimal128("500"),
        "tags": ["mandatory_free_shipping"],
        "seller_shipping_cost": Decimal128("83.25"),
        "enrichment_state": {
            "seller_shipping_cost": {
                "source": "/users/{seller_id}/shipping_options/free",
                "status": "trusted",
                "synced_at": NOW,
                "basis": {
                    "site_id": "MLA",
                    "category_id": "MLA123",
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "price": Decimal128("149.99"),
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                    "billable_weight": Decimal128("500"),
                    "tags": ["mandatory_free_shipping"],
                },
            }
        },
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "variations": [],
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "currency_id": "ARS",
            "site_id": "MLA",
            "listing_type_id": "gold_special",
            "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
            "billable_weight": "500",
            "tags": ["mandatory_free_shipping"],
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    assert item["seller_shipping_cost"].to_decimal() == Decimal("83.25")
    assert item["enrichment_state"]["seller_shipping_cost"]["status"] == "trusted"
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert row["current"]["seller_shipping_cost"].to_decimal() == Decimal("83.25")


@pytest.mark.asyncio
async def test_item_event_normalizes_preserved_decimal_enrichment_before_mongo_write() -> None:
    db = FakeDb()
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Previous widget",
        "price": Decimal128("149.99"),
        "base_price": Decimal128("159.99"),
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA123",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
        "billable_weight": Decimal128("500"),
        "tags": ["mandatory_free_shipping"],
        "seller_shipping_cost": Decimal("83.25"),
        "current_promotion": {
            "source": "/items/{id}/sale_price",
            "sale_amount": Decimal("99.90"),
            "regular_amount": Decimal("149.90"),
            "discount_percent": Decimal("33.36"),
            "currency_id": "MXN",
            "reference_at": NOW,
            "synced_at": NOW,
        },
        "enrichment_state": {
            "seller_shipping_cost": {
                "source": "/users/{seller_id}/shipping_options/free",
                "status": "trusted",
                "synced_at": NOW,
                "basis": {
                    "site_id": "MLA",
                    "category_id": "MLA123",
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "price": Decimal("149.99"),
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                    "billable_weight": Decimal("500"),
                    "tags": ["mandatory_free_shipping"],
                },
            }
        },
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "variations": [],
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "currency_id": "ARS",
            "site_id": "MLA",
            "listing_type_id": "gold_special",
            "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
            "billable_weight": "500",
            "tags": ["mandatory_free_shipping"],
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    BSON.encode(item)
    BSON.encode(row)
    assert item["seller_shipping_cost"].to_decimal() == Decimal("83.25")
    assert item["current_promotion"]["sale_amount"].to_decimal() == Decimal("99.90")
    assert row["current"]["seller_shipping_cost"].to_decimal() == Decimal("83.25")
    assert row["current"]["current_promotion"]["sale_amount"].to_decimal() == Decimal("99.90")


@pytest.mark.asyncio
async def test_item_event_normalizes_preserved_listing_fee_datetime_before_mongo_write() -> None:
    naive_synced_at = datetime(2026, 6, 9, 18, 51, 7, 716000)
    db = FakeDb()
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Previous widget",
        "price": Decimal128("149.99"),
        "base_price": Decimal128("159.99"),
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA123",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "listing_fee_projection": {
            "source": "/sites/{site}/listing_prices",
            "site_id": "MLA",
            "currency_id": "ARS",
            "price": Decimal128("149.99"),
            "listing_type_id": "gold_special",
            "category_id": "MLA123",
            "sale_fee_amount": Decimal128("155.99"),
            "percentage_fee": Decimal128("12.00"),
            "synced_at": naive_synced_at,
        },
        "variations": [],
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "currency_id": "ARS",
            "site_id": "MLA",
            "listing_type_id": "gold_special",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    expected_synced_at = naive_synced_at.replace(tzinfo=UTC)
    assert item["listing_fee_projection"]["synced_at"] == expected_synced_at
    assert row["current"]["listing_fee_projection"]["synced_at"] == expected_synced_at


@pytest.mark.asyncio
async def test_item_event_clears_trusted_seller_shipping_when_basis_changes() -> None:
    db = FakeDb()
    db["items"].documents["MLA1"] = {
        "_id": "MLA1",
        "seller_id": "82453304",
        "title": "Previous widget",
        "price": Decimal128("149.99"),
        "base_price": Decimal128("159.99"),
        "available_quantity": 7,
        "status": "active",
        "category_id": "MLA123",
        "currency_id": "ARS",
        "site_id": "MLA",
        "listing_type_id": "gold_special",
        "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
        "billable_weight": Decimal128("500"),
        "tags": ["mandatory_free_shipping"],
        "seller_shipping_cost": Decimal128("83.25"),
        "enrichment_state": {
            "seller_shipping_cost": {
                "source": "/users/{seller_id}/shipping_options/free",
                "status": "trusted",
                "synced_at": NOW,
                "basis": {
                    "site_id": "MLA",
                    "category_id": "MLA123",
                    "currency_id": "ARS",
                    "listing_type_id": "gold_special",
                    "price": Decimal128("149.99"),
                    "shipping_mode": "me2",
                    "logistic_type": "fulfillment",
                    "billable_weight": Decimal128("500"),
                    "tags": ["mandatory_free_shipping"],
                },
            }
        },
        "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
        "variations": [],
        "last_meli_sync_at": NOW,
        "date_created": NOW,
        "last_updated": NOW,
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "199.99",
            "base_price": "209.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "currency_id": "ARS",
            "site_id": "MLA",
            "listing_type_id": "gold_special",
            "shipping": {"mode": "me2", "logistic_type": "fulfillment"},
            "billable_weight": "500",
            "tags": ["mandatory_free_shipping"],
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    assert "seller_shipping_cost" not in item
    assert item["enrichment_state"]["seller_shipping_cost"]["status"] == "basis_mismatch"
    assert item["enrichment_state"]["seller_shipping_cost"]["reason"] == "basis_changed"
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert "seller_shipping_cost" not in row["current"]


@pytest.mark.asyncio
async def test_persists_order_for_sheetseller_order_formulas() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "date_closed": "2026-05-29T10:05:00+00:00",
            "total_amount": "299.90",
            "pack_id": 998877,
            "buyer": {"id": 123},
            "shipping": {"id": 555},
            "order_items": [
                {
                    "item": {"id": "MLA1", "seller_sku": "sku-1"},
                    "quantity": 2,
                    "unit_price": "149.95",
                    "sale_fee": "24.50",
                }
            ],
            "tags": ["paid"],
        },
    )

    order = db["orders"].documents["2001"]
    assert order["_id"] == "2001"
    assert order["seller_id"] == "82453304"
    assert order["buyer_id"] == "123"
    assert order["meli_pack_id"] == "998877"
    assert order["shipment_id"] == "555"
    assert order["total_amount"] == Decimal128("299.90")
    BSON.encode(order)
    assert order["items"] == [
        {
            "item_id": "MLA1",
            "seller_sku": "sku-1",
            "qty": 2,
            "unit_price": Decimal128("149.95"),
            "sale_fee": Decimal128("24.50"),
            "sale_fee_source": "/orders/{id}",
            "sale_fee_synced_at": NOW,
        }
    ]


@pytest.mark.asyncio
async def test_order_persistence_does_not_fallback_for_missing_pack_id() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2002,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "total_amount": "99.90",
            "buyer": {"id": 123},
            "shipping": {"id": 555},
            "order_items": [
                {
                    "item": {"id": "MLA1", "seller_sku": "sku-1"},
                    "quantity": 1,
                    "unit_price": "99.90",
                }
            ],
        },
    )

    order = db["orders"].documents["2002"]
    assert "meli_pack_id" not in order
    assert order["_id"] == "2002"
    assert order["shipment_id"] == "555"


@pytest.mark.asyncio
async def test_persisted_order_feeds_live_sku_index_from_order_line_identity() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {"id": "MLA1", "variation_id": 101, "seller_sku": "sku-1"},
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    assert db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] == {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "seller_nickname": None,
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }


@pytest.mark.asyncio
async def test_persisted_order_feeds_sku_index_from_order_line_seller_sku_attribute() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2001,
            "status": "paid",
            "date_created": "2026-05-29T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {
                        "id": "MLA1",
                        "variation_id": 101,
                        "variation_attributes": [{"id": "SELLER_SKU", "value_name": "attr-sku-1"}],
                    },
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    order = db["orders"].documents["2001"]
    assert order["items"] == [
        {
            "item_id": "MLA1",
            "variation_id": "101",
            "seller_sku": "attr-sku-1",
            "qty": 2,
            "unit_price": Decimal128("149.95"),
        }
    ]
    assert (
        db["sheets_item_sku_index"].documents["82453304:ATTR-SKU-1:MLA1:101"]["source"]
        == "order_line"
    )


@pytest.mark.asyncio
async def test_order_line_sku_index_skips_conflicting_live_identity() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] = {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="orders.updated",
        seller_id=82453304,
        resource={
            "id": 2002,
            "status": "paid",
            "date_created": "2026-05-30T10:00:00+00:00",
            "total_amount": "299.90",
            "buyer": {"id": 123},
            "order_items": [
                {
                    "item": {"id": "MLA1", "variation_id": 101, "seller_sku": "sku-2"},
                    "quantity": 2,
                    "unit_price": "149.95",
                }
            ],
        },
    )

    assert sorted(db["sheets_item_sku_index"].documents) == ["82453304:SKU-1:MLA1:101"]


@pytest.mark.asyncio
async def test_item_without_seller_sku_refreshes_formula_rows_from_known_order_line_sku() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:SKU-1:MLA1:101"] = {
        "_id": "82453304:SKU-1:MLA1:101",
        "seller_id": "82453304",
        "sku": "sku-1",
        "normalized_sku": "SKU-1",
        "item_id": "MLA1",
        "variation_id": "101",
        "identity_level": "variation",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget updated",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "permalink": "https://articulo.example/MLA1",
            "thumbnail": "https://img.example/MLA1.jpg",
            "catalog_product_id": "CAT-1",
            "attributes": [],
            "variations": [{"id": 101, "inventory_id": "INV-VAR-101"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    formula_row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1:101"]
    assert formula_row["sku"] == "sku-1"
    assert formula_row["inventory_id"] == "INV-VAR-101"
    assert formula_row["current"]["title"] == "Premium widget updated"
    assert formula_row["current"]["catalog_product_id"] == "CAT-1"
    assert formula_row["current"]["inventory_id"] == "INV-VAR-101"


@pytest.mark.asyncio
async def test_item_with_direct_sku_does_not_create_stale_order_line_duplicate() -> None:
    db = FakeDb()
    db["sheets_item_sku_index"].documents["82453304:STALE-SKU:MLA1:item"] = {
        "_id": "82453304:STALE-SKU:MLA1:item",
        "seller_id": "82453304",
        "sku": "stale-sku",
        "normalized_sku": "STALE-SKU",
        "item_id": "MLA1",
        "variation_id": None,
        "identity_level": "item",
        "source": "order_line",
        "inventory_id": None,
        "updated_at": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "schema_version": 2,
    }
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Premium widget",
            "price": "149.99",
            "base_price": "159.99",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "fresh-sku"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    assert sorted(db["sheets_item_formula_rows"].documents) == ["82453304:FRESH-SKU:MLA1"]


@pytest.mark.asyncio
async def test_item_event_refreshes_formula_rows_from_persisted_current_promotion() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Promoted listing",
            "price": "99.90",
            "base_price": "149.90",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "current_promotion": {
                "source": "/items/{id}/sale_price",
                "sale_amount": "99.90",
                "regular_amount": "149.90",
                "discount_percent": "33.36",
                "currency_id": "MXN",
                "promotion_id": "PROMO-1",
                "promotion_type": "deal",
                "reference_at": NOW,
                "synced_at": NOW,
            },
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert item["current_promotion"]["sale_amount"] == Decimal128("99.90")
    assert row["current"]["current_promotion"]["sale_amount"] == Decimal128("99.90")


@pytest.mark.asyncio
async def test_price_event_does_not_treat_prices_payload_as_promo_source() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="items.price_updated",
        seller_id=82453304,
        resource={
            "id": "MLA1",
            "title": "Price updated listing",
            "price": "99.90",
            "base_price": "149.90",
            "available_quantity": 7,
            "status": "active",
            "category_id": "MLA123",
            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
            "prices": [{"amount": "99.90", "regular_amount": "149.90"}],
            "date_created": "2026-05-01T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    item = db["items"].documents["MLA1"]
    row = db["sheets_item_formula_rows"].documents["82453304:SKU-1:MLA1"]
    assert "current_promotion" not in item
    assert "current_promotion" not in row["current"]


@pytest.mark.asyncio
async def test_persists_shipment_for_live_shipping_notifications() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "substatus": "printed",
            "tracking_number": "TRACK-1",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment == {
        "_id": "3001",
        "seller_id": "82453304",
        "order_id": "2001",
        "status": "ready_to_ship",
        "substatus": "printed",
        "tracking_number": "TRACK-1",
        "logistic_type": "fulfillment",
        "date_created": datetime(2026, 5, 29, 10, 0, tzinfo=UTC),
        "last_updated": datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    BSON.encode(shipment)


@pytest.mark.asyncio
async def test_persists_shipment_real_shipping_cost_projection_only() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "real_shipping_cost": {
                "source": "/shipments/{shipment_id}/costs",
                "seller_cost": "24.50",
                "receiver_cost": "100.00",
                "currency_id": "MXN",
                "matched_sender_id": "82453304",
                "synced_at": NOW,
            },
            "senders": [{"sender_id": "82453304", "cost": "24.50"}],
            "receiver": {"cost": "100.00", "address": "must-not-persist"},
            "buyer": {"name": "must-not-persist"},
            "token": "must-not-persist",
            "raw_payload": {"must": "not persist"},
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["real_shipping_cost"] == {
        "source": "/shipments/{shipment_id}/costs",
        "seller_cost": Decimal128("24.50"),
        "receiver_cost": Decimal128("100.00"),
        "currency_id": "MXN",
        "matched_sender_id": "82453304",
        "synced_at": NOW,
    }
    serialized_shipment = repr(shipment)
    for forbidden in ("senders", "buyer", "address", "token", "raw_payload"):
        assert forbidden not in serialized_shipment
    BSON.encode(shipment)


@pytest.mark.asyncio
async def test_persists_shipment_receiver_address_from_allowlisted_snapshot_only() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "substatus": "printed",
            "tracking_number": "TRACK-1",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": "  Synthetic Buyer  ",
                "street_name": " Sentinel Street ",
                "street_number": 123,
                "neighborhood": {"name": " Test Neighborhood "},
                "zip_code": " 1000 ",
                "city": {"name": " Test City "},
                "state": {"name": " Test State "},
                "country": {"id": "AR", "name": " Argentina "},
                "phone": "+54-PII-PHONE",
                "email": "pii@example.invalid",
                "document": "PII-DOCUMENT",
                "comment": "PII-COMMENT",
                "latitude": "PII-GEO-LAT",
                "longitude": "PII-GEO-LON",
            },
            "receiver": {"name": "RAW-RECEIVER-PII", "phone": "+54-RAW-PHONE"},
            "buyer": {"email": "raw-buyer@example.invalid"},
            "token": "PII-OAUTH-TOKEN",
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {
        "name": "Synthetic Buyer",
        "street_name": "Sentinel Street",
        "street_number": "123",
        "neighborhood": "Test Neighborhood",
        "zip_code": "1000",
        "city": "Test City",
        "state": "Test State",
        "country": "Argentina",
    }
    serialized_shipment = repr(shipment)
    for forbidden in (
        "+54-PII-PHONE",
        "pii@example.invalid",
        "PII-DOCUMENT",
        "PII-COMMENT",
        "PII-GEO-LAT",
        "PII-GEO-LON",
        "RAW-RECEIVER-PII",
        "raw-buyer@example.invalid",
        "PII-OAUTH-TOKEN",
    ):
        assert forbidden not in serialized_shipment
    BSON.encode(shipment)


@pytest.mark.asyncio
async def test_shipment_receiver_address_drops_nested_string_values() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": {"raw": "PII-NESTED-NAME"},
                "street_name": ["PII-NESTED-STREET"],
                "street_number": {"raw": "PII-NESTED-NUMBER"},
                "neighborhood": {"name": ["PII-NESTED-NEIGHBORHOOD"]},
                "zip_code": {"raw": "PII-NESTED-ZIP"},
                "city": {"name": {"raw": "PII-NESTED-CITY"}},
                "state": {"name": " Safe State "},
                "country": {"id": "AR"},
            },
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {"state": "Safe State", "country": "AR"}
    serialized_shipment = repr(shipment)
    for forbidden in (
        "PII-NESTED-NAME",
        "PII-NESTED-STREET",
        "PII-NESTED-NUMBER",
        "PII-NESTED-NEIGHBORHOOD",
        "PII-NESTED-ZIP",
        "PII-NESTED-CITY",
    ):
        assert forbidden not in serialized_shipment


@pytest.mark.asyncio
async def test_shipment_receiver_address_uses_scalar_fallback_when_primary_name_is_nested() -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)

    await persistence.persist(
        event_type="shipments.updated",
        seller_id=82453304,
        resource={
            "id": 3001,
            "order_id": 2001,
            "status": "ready_to_ship",
            "logistic_type": "fulfillment",
            "date_created": "2026-05-29T10:00:00+00:00",
            "last_updated": "2026-05-30T11:00:00+00:00",
            "receiver_address": {
                "receiver_name": {"raw": "PII-NESTED-NAME"},
                "name": " Safe Buyer ",
            },
        },
    )

    shipment = db["shipments"].documents["3001"]
    assert shipment["receiver_address"] == {"name": "Safe Buyer"}
    assert "PII-NESTED-NAME" not in repr(shipment)


@pytest.mark.asyncio
async def test_shipment_persistence_errors_do_not_leak_receiver_address_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = FakeDb()
    persistence = SheetsEventPersistence(db=db, clock=lambda: NOW)
    caplog.set_level("DEBUG")
    resource = {
        "id": 3001,
        "order_id": 2001,
        "status": "invalid-status",
        "logistic_type": "fulfillment",
        "date_created": "2026-05-29T10:00:00+00:00",
        "last_updated": "2026-05-30T11:00:00+00:00",
        "receiver_address": {
            "receiver_name": "PII-SENTINEL-NAME",
            "street_name": "PII-SENTINEL-STREET",
            "phone": "+54-PII-PHONE",
            "email": "pii@example.invalid",
        },
    }

    with pytest.raises(ValueError) as exc_info:
        await persistence.persist(
            event_type="shipments.updated", seller_id=82453304, resource=resource
        )

    error_text = str(exc_info.value)
    assert "shipment resource failed validation" in error_text
    assert exc_info.value.args == ("shipment resource failed validation",)
    assert exc_info.value.__cause__ is None
    assert db["shipments"].replace_calls == []
    captured_logs = "\n".join(
        f"{record.getMessage()} {record.__dict__}" for record in caplog.records
    )
    for forbidden in (
        "PII-SENTINEL-NAME",
        "PII-SENTINEL-STREET",
        "+54-PII-PHONE",
        "pii@example.invalid",
    ):
        assert forbidden not in error_text
        assert forbidden not in captured_logs
