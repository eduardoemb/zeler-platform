from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.read_models import _read_model_freshness_marker_covers
from zeler_sheets.formulas.refresh import MARKER_VALIDITY
from zeler_sheets.observed_read_model_markers import (
    OBSERVED_MARKER_MAX_AGE,
    OBSERVED_MARKER_SOURCE,
    OBSERVED_ONLY_BASIS,
    OBSERVED_READ_MODEL_SOURCES,
    publish_observed_read_model_markers,
)

SELLER = "82453304"
NOW = datetime(2026, 9, 11, 6, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def sort(self, field: str, direction: int) -> _Cursor:
        return _Cursor(sorted(self._rows, key=lambda row: row[field], reverse=direction < 0))

    def limit(self, count: int) -> _Cursor:
        return _Cursor(self._rows[:count])

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows[:length]]


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = list(documents or [])
        self.upserts: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    def find(self, query: dict[str, Any], projection: Any = None) -> _Cursor:
        rows = [document for document in self.documents if _matches(document, query)]
        return _Cursor(rows)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> Any:
        self.upserts.append({"query": query, "document": dict(update["$set"])})
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                document.update(update["$set"])
                break
        else:
            self.documents.append(dict(update["$set"]))
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class _Db:
    def __init__(self, **collections: _Collection) -> None:
        self._collections = collections
        self._collections.setdefault("sheets_read_model_freshness", _Collection())

    def __getitem__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if isinstance(expected, dict):
            if "$exists" in expected and (key in document) != bool(expected["$exists"]):
                return False
            continue
        if document.get(key) != expected:
            return False
    return True


def _db_with_observations(*, age: timedelta = timedelta(hours=1)) -> _Db:
    observed = NOW - age
    db = _Db()
    db["shipments"].documents = [
        {"_id": "3001", "seller_id": SELLER, "formula_observed_at": observed}
    ]
    db["sheets_price_history_snapshots"].documents = [
        {"_id": f"{SELLER}:MLA1", "seller_id": SELLER, "snapshot_at": observed}
    ]
    db["sheets_stockout_snapshots"].documents = [
        {"_id": f"{SELLER}:MLA1", "seller_id": SELLER, "observed_at": observed}
    ]
    db["item_status_states"].documents = [
        {"_id": f"{SELLER}:MLA1", "seller_id": SELLER, "last_observed_at": observed}
    ]
    return db


@pytest.mark.asyncio
async def test_publishes_a_heartbeat_for_every_observed_model() -> None:
    db = _db_with_observations()

    published = await publish_observed_read_model_markers(db, SELLER, now_fn=lambda: NOW)

    assert published == tuple(sorted(OBSERVED_READ_MODEL_SOURCES))
    markers = db["sheets_read_model_freshness"].documents
    assert len(markers) == len(OBSERVED_READ_MODEL_SOURCES)
    for marker in markers:
        assert marker["state"] == "fresh"
        assert marker["source"] == OBSERVED_MARKER_SOURCE
        assert marker["coverage_basis"] == OBSERVED_ONLY_BASIS
        assert marker["fresh_until"] == NOW
        assert marker["valid_until"] == NOW + MARKER_VALIDITY
        assert marker["last_event_synced_at"] == NOW - timedelta(hours=1)


@pytest.mark.asyncio
async def test_does_not_certify_a_model_without_observations() -> None:
    db = _db_with_observations()
    db["shipments"].documents = []

    published = await publish_observed_read_model_markers(db, SELLER, now_fn=lambda: NOW)

    assert "shipments" not in published
    assert not any(
        marker["read_model"] == "shipments"
        for marker in db["sheets_read_model_freshness"].documents
    )


@pytest.mark.asyncio
async def test_does_not_certify_abandoned_observations() -> None:
    db = _db_with_observations(age=OBSERVED_MARKER_MAX_AGE + timedelta(minutes=1))

    published = await publish_observed_read_model_markers(db, SELLER, now_fn=lambda: NOW)

    assert published == ()
    assert db["sheets_read_model_freshness"].documents == []


@pytest.mark.asyncio
async def test_never_downgrades_a_productive_reconciled_marker() -> None:
    db = _db_with_observations()
    reconciled = {
        "_id": f"{SELLER}:shipments",
        "seller_id": SELLER,
        "read_model": "shipments",
        "state": "reconciled",
        "fresh_until": NOW + MARKER_VALIDITY,
        "valid_until": NOW + MARKER_VALIDITY,
        "source": "zelerdata_read_model_reconcile",
    }
    db["sheets_read_model_freshness"].documents = [reconciled]

    published = await publish_observed_read_model_markers(db, SELLER, now_fn=lambda: NOW)

    assert "shipments" not in published
    assert db["sheets_read_model_freshness"].documents[0] == reconciled


@pytest.mark.asyncio
async def test_heartbeat_opens_the_formula_gate_for_a_now_read() -> None:
    # The heartbeat certifies the audit instant; the reader's two-cycle tolerance
    # serves a read that starts right after it, exactly as with a refresh claim.
    real_now = datetime.now(UTC)
    db = _db_with_observations()

    await publish_observed_read_model_markers(db, SELLER, now_fn=lambda: real_now)

    for marker in db["sheets_read_model_freshness"].documents:
        assert _read_model_freshness_marker_covers(marker, date_to=datetime.now(UTC)) is True
