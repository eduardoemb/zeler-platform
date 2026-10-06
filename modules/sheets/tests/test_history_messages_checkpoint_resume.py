"""Offline BSON round-trip regressions for frozen message checkpoint continuation."""

from __future__ import annotations

import copy
import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from bson import BSON
from bson.codec_options import CodecOptions
from pymongo.results import UpdateResult

from zeler_sheets.formulas.pacing import HistoryPolicyWaitError
from zeler_sheets.history_onboarding import HistoryOnboardingWorker

SELLER = "82453304"
CUTOFF = datetime(2026, 9, 24, 5, 36, 28, tzinfo=UTC)
NOW = datetime(2026, 10, 6, 4, 30, 30, 123456, tzinfo=UTC)
UNTIL = datetime(2026, 10, 6, 5, 52, 57, 845000, tzinfo=UTC)


def bson(document: dict[str, Any]) -> dict[str, Any]:
    return dict(
        BSON(BSON.encode(document)).decode(codec_options=CodecOptions(tz_aware=True, tzinfo=UTC))
    )


class Plans:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = bson(document)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> UpdateResult:
        assert all(self.document.get(key) == value for key, value in query.items())
        assert set(update) == {"$set"} and set(update["$set"]) == {"message_periodic_recovery"}
        self.document = bson({**self.document, **update["$set"]})
        return UpdateResult({"n": 1, "nModified": 1}, True)


class Orders:
    def __init__(self) -> None:
        self.packs = ["400"]

    async def distinct(self, field: str, query: dict[str, Any]) -> list[str]:
        assert field == "meli_pack_id" and query == {"seller_id": SELLER}
        return list(self.packs)


class Messages:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return copy.deepcopy(self.rows.get(query["_id"]))

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        self.rows[query["_id"]].update(copy.deepcopy(update["$set"]))

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.rows[document["_id"]] = bson(document)


class Database:
    def __init__(self, document: dict[str, Any]) -> None:
        self.plans, self.orders, self.messages = Plans(document), Orders(), Messages()

    def __getitem__(self, name: str) -> Any:
        if name == "sheets_history_backfill_plans":
            return self.plans
        assert name == "messages"
        return self.messages


class Detail:
    def __init__(self, *, wait: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.wait = wait
        self.incremental = False

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        # The production detail is a paced PlanBudgetGateway; this adapter makes
        # its public fetch surface explicit, with one physical call and no retry.
        return await self.fetch_resource_once(seller_id=seller_id, path=path)

    async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == SELLER
        query = parse_qs(urlsplit(path).query)
        assert query["mark_as_read"] == ["false"]
        if self.wait:
            raise HistoryPolicyWaitError("fixture authority wait")
        pack, offset = path.split("/")[3], int(query["offset"][0])
        self.calls.append((pack, offset))
        return {
            "paging": {"total": 151, "offset": offset},
            "messages": [
                {
                    "id": f"{pack}-{i}",
                    "from": {"user_id": "999"},
                    "to": {"user_id": SELLER},
                    "text": "synthetic message",
                    "status": "available",
                    "message_date": {"created": (CUTOFF + timedelta(hours=1)).isoformat()},
                }
                for i in range(offset, min(offset + 50, 151))
            ],
        }


def plan() -> dict[str, Any]:
    return {
        "_id": SELLER,
        "seller_id": SELLER,
        "cutoff": CUTOFF,
        "date_from": datetime(2025, 9, 24, 5, 36, 28, tzinfo=UTC),
        "state": "active",
        "execution_id": "a" * 32,
        "execution_until": UNTIL,
        "execution_utc_day": "2026-10-06",
        "execution_attempt_limit": 2500,
        "execution_consumed": 69,
        "execution_sent": 67,
        "total_consumed": 56,
        "incremental_consumed": 13,
        "lease_token": "fixture-owned",
        "collector_checkpoints": {
            "messages": {
                "pending": [{"code": "invalid_message", "id": "fixture-kept"}],
                "offset": 19,
            }
        },
        "onboarding_sources": {"messages": {"state": "running"}},
    }


def pending(document: dict[str, Any]) -> dict[str, Any]:
    start = CUTOFF - timedelta(minutes=5)
    end = NOW
    document["message_periodic_recovery"] = {
        "sweep_start": start,
        "sweep_end": end,
        "packs_completed": 0,
        "persisted": 0,
        "issue_count": 0,
        "checkpoint": {
            "seller_id": SELLER,
            "source": "messages",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "target_ids": ["400"],
            "target_index": 0,
            "type_index": 0,
            "offset": 100,
            "persisted": 100,
            "issue_count": 1,
            "pending": [{"code": "invalid_message", "id": "fixture-kept"}],
            "discovery_complete": False,
        },
    }
    return document


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if "MONGO" in key or "AMQP" in key or "RABBIT" in key:
            monkeypatch.delenv(key, raising=False)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("message checkpoint tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
async def test_restart_after_bson_roundtrip_resumes_original_microsecond_bounds() -> None:
    db, detail = Database(plan()), Detail()
    original = copy.deepcopy(db.plans.document)
    first = HistoryOnboardingWorker(db, detail, detail, now=lambda: NOW)
    await first._advance_periodic_messages(db.plans.document, detail)
    saved = copy.deepcopy(db.plans.document["message_periodic_recovery"])
    assert saved["sweep_end"].microsecond == 123000
    assert saved["checkpoint"]["end"] == NOW.isoformat()
    assert saved["checkpoint"]["offset"] == 100
    restarted = HistoryOnboardingWorker(db, detail, detail, now=lambda: NOW + timedelta(minutes=1))
    await restarted._advance_periodic_messages(db.plans.document, detail)
    assert detail.calls == [("400", 0), ("400", 50), ("400", 100), ("400", 150)]
    assert len(db.messages.rows) == 151
    assert db.plans.document["message_periodic_recovery"]["sweep_complete"] is True
    assert db.plans.document["message_periodic_recovery"]["sweep_end"] == saved["sweep_end"]
    for key, value in original.items():
        assert db.plans.document[key] == value


@pytest.mark.asyncio
async def test_pending_targets_and_range_remain_frozen_when_inventory_changes() -> None:
    db, detail = Database(pending(plan())), Detail()
    db.orders.packs = ["100", "400", "999"]
    original = copy.deepcopy(db.plans.document)
    worker = HistoryOnboardingWorker(db, detail, detail, now=lambda: NOW + timedelta(minutes=1))
    await worker._advance_periodic_messages(db.plans.document, detail)
    assert detail.calls == [("400", 100), ("400", 150)]
    assert (
        db.plans.document["message_periodic_recovery"]["sweep_end"]
        == original["message_periodic_recovery"]["sweep_end"]
    )
    assert db.plans.document["collector_checkpoints"] == original["collector_checkpoints"]
    assert db.plans.document["execution_until"] == UNTIL


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["seller_id", "source", "start", "end"])
async def test_real_identity_mismatch_never_rewrites_checkpoint_or_sends(field: str) -> None:
    document = pending(plan())
    checkpoint = document["message_periodic_recovery"]["checkpoint"]
    checkpoint[field] = (
        (NOW + timedelta(seconds=1)).isoformat() if field in {"start", "end"} else "foreign"
    )
    db, detail = Database(document), Detail()
    original = copy.deepcopy(db.plans.document)
    worker = HistoryOnboardingWorker(db, detail, detail, now=lambda: NOW)
    with pytest.raises(ValueError):
        await worker._advance_periodic_messages(db.plans.document, detail)
    assert db.plans.document == original and detail.calls == []


@pytest.mark.asyncio
async def test_policy_wait_keeps_pending_range_and_all_existing_counters() -> None:
    db, detail = Database(pending(plan())), Detail(wait=True)
    original = copy.deepcopy(db.plans.document)
    worker = HistoryOnboardingWorker(db, detail, detail, now=lambda: NOW + timedelta(minutes=1))
    await worker._advance_periodic_messages(db.plans.document, detail)
    assert detail.calls == []
    current = db.plans.document["message_periodic_recovery"]
    expected = copy.deepcopy(original["message_periodic_recovery"]["checkpoint"])
    expected["last_error"] = "policy_wait"
    assert current["checkpoint"] == expected
    assert current["sweep_start"] == original["message_periodic_recovery"]["sweep_start"]
    assert current["sweep_end"] == original["message_periodic_recovery"]["sweep_end"]
    for key, value in original.items():
        if key != "message_periodic_recovery":
            assert db.plans.document[key] == value
