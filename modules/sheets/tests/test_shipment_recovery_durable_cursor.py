"""Offline transactions: an unfinished batch retains each concluded identity."""

from __future__ import annotations

import copy
import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pymongo.errors import OperationFailure

from zeler_sheets.event_persistence import _canonical_shipment_document
from zeler_sheets.formulas import recovery_worker as module
from zeler_sheets.formulas.pacing import HistoryPolicyWaitError
from zeler_sheets.formulas.recovery import FormulaRecoveryQueue, ShipmentIdsRecoveryRequest

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
SELLER = "82453304"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def match(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, value in query.items():
        if key == "$and":
            if not all(match(row, part) for part in value):
                return False
        elif isinstance(value, dict):
            for op, expected in value.items():
                if op == "$exists" and (key in row) != expected:
                    return False
                if op == "$in" and row.get(key) not in expected:
                    return False
                if op == "$gt" and not row.get(key, NOW) > expected:
                    return False
        elif row.get(key) != value:
            return False
    return True


class Collection:
    def __init__(self, db: DB, name: str) -> None:
        self.db, self.name = db, name
        self.database = db

    async def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        return next(
            (copy.deepcopy(r) for r in self.db.data[self.name].values() if match(r, query)), None
        )

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> Any:
        if self.db.reject_cursor and "shipment_offset" in update.get("$set", {}):
            raise OperationFailure("synthetic validator refusal", code=121)
        row = next((r for r in self.db.data[self.name].values() if match(r, query)), None)
        if row is None or (
            self.db.lose_at is not None
            and self.db.lose_at == query.get("shipment_offset")
            and kwargs.get("session")
        ):
            return SimpleNamespace(matched_count=0)
        row.update(update.get("$set", {}))
        for field, delta in update.get("$inc", {}).items():
            row[field] = row.get(field, 0) + delta
        for field in update.get("$unset", {}):
            row.pop(field, None)
        for field, value in update.get("$push", {}).items():
            row.setdefault(field, []).append(copy.deepcopy(value))
        return SimpleNamespace(matched_count=1)

    async def count_documents(self, query: dict[str, Any], **kwargs: Any) -> int:
        return sum(match(row, query) for row in self.db.data[self.name].values())


class Session:
    def __init__(self, db: DB) -> None:
        self.db = db
        self.in_transaction = False

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def start_transaction(self, **kwargs: Any) -> Any:
        assert kwargs["read_concern"].document == {"level": "snapshot"}
        assert kwargs["write_concern"].document == {"w": "majority"}
        session = self

        class Tx:
            async def __aenter__(self) -> None:
                session.in_transaction = True
                self.before = copy.deepcopy(session.db.data)

            async def __aexit__(self, kind: Any, error: Any, tb: Any) -> None:
                if error:
                    session.db.data = self.before
                session.in_transaction = False

        return Tx()

    async def with_transaction(self, callback: Any, **kwargs: Any) -> Any:
        async with self.start_transaction(**kwargs):
            return await callback(self)


class DB:
    def __init__(self, ids: tuple[str, ...]) -> None:
        request = ShipmentIdsRecoveryRequest(SELLER, ids)
        self.job: dict[str, Any] = {
            "_id": request.key,
            "seller_id": SELLER,
            "read_model": "shipments",
            "shipment_ids": list(request.shipment_ids),
            "state": "running",
            "attempt_token": "a" * 32,
            "lease_until": NOW + timedelta(minutes=10),
            "attempts": 1,
        }
        self.data: dict[str, dict[str, dict[str, Any]]] = {
            "sheets_formula_recovery_jobs": {request.key: copy.deepcopy(self.job)},
            "shipments": {},
            "sheets_formula_recovery_admission": {},
        }
        self.client = self
        self.reject_cursor = False
        self.lose_at: int | None = None

    def __getitem__(self, name: str) -> Collection:
        return Collection(self, name)

    async def start_session(self) -> Session:
        return Session(self)


class Gateway:
    def __init__(self, budget: int, *, transient_cost: bool = False) -> None:
        self.budget, self.transient_cost = budget, transient_cost
        self.calls: list[str] = []
        self.pause_after: int | None = None

    async def request(self, *, path: str, **kwargs: Any) -> httpx.Response:
        if (
            len(self.calls) >= self.budget
            or self.pause_after is not None
            and len(self.calls) >= self.pause_after
        ):
            raise HistoryPolicyWaitError("synthetic original budget exhausted")
        self.calls.append(path)
        identity = path.split("/")[2]
        if path.endswith("/orders"):
            return httpx.Response(200, json=[{"order_id": 9, "seller_id": int(SELLER)}])
        if path.endswith("/costs"):
            return httpx.Response(503 if self.transient_cost else 404)
        return httpx.Response(
            200,
            json={
                "id": int(identity),
                "seller_id": int(SELLER),
                "order_id": 9,
                "status": "ready_to_ship",
                "logistic_type": "fulfillment",
                "date_created": NOW.isoformat(),
                "last_updated": NOW.isoformat(),
            },
        )


def worker(
    monkeypatch: pytest.MonkeyPatch, db: DB, gateway: Gateway
) -> module.FormulaRecoveryWorker:
    class Writer:
        def __init__(self, *, db: DB, clock: Any) -> None:
            self.db = db

        async def persist(
            self, *, resource: dict[str, Any], seller_id: str, session: Any, **kwargs: Any
        ) -> None:
            assert session.in_transaction
            doc = _canonical_shipment_document(resource, seller_id=seller_id)
            self.db.data["shipments"][str(resource["id"])] = doc

    monkeypatch.setattr(module, "SheetsEventPersistence", Writer)
    queue = FormulaRecoveryQueue(
        db,
        now=lambda: NOW,
        enabled_models=frozenset({"shipments"}),
        allowed_sellers=frozenset({SELLER}),
        max_active_jobs_per_seller=4,
    )
    return module.FormulaRecoveryWorker(db=db, queue=queue, gateway=gateway, detail_gateway=gateway)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ids", "budget", "concluded"),
    [(tuple("123"), 6, 2), (tuple(str(i) for i in range(1, 101)), 250, 83)],
)
async def test_budget_stop_keeps_every_concluded_identity(
    monkeypatch: pytest.MonkeyPatch, ids: tuple[str, ...], budget: int, concluded: int
) -> None:
    db, gateway = DB(ids), Gateway(budget)
    with pytest.raises(HistoryPolicyWaitError):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert len(db.data["shipments"]) == concluded
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    assert row["shipment_offset"] == concluded and row["shipment_ids"] == db.job["shipment_ids"]
    assert len(gateway.calls) == budget and row["_id"] == db.job["_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, None, -1, 4])
async def test_malformed_cursor_refuses_before_rpc(
    monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    db.job["shipment_offset"] = bad
    db.data["sheets_formula_recovery_jobs"][db.job["_id"]]["shipment_offset"] = bad
    with pytest.raises(ValueError):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_validator_rejects_new_field_before_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    db.reject_cursor = True
    with pytest.raises(OperationFailure):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert gateway.calls == [] and db.data["shipments"] == {}


@pytest.mark.asyncio
async def test_current_identity_cas_loss_rolls_back_only_current_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    db.lose_at = 1
    with pytest.raises(ValueError):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert set(db.data["shipments"]) == {"1"}
    assert db.data["sheets_formula_recovery_jobs"][db.job["_id"]]["shipment_offset"] == 1


@pytest.mark.asyncio
async def test_lost_owner_or_mutated_list_refuses_before_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    db.data["sheets_formula_recovery_jobs"][db.job["_id"]]["shipment_ids"] = ["1", "2"]
    with pytest.raises(ValueError):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_transient_cost_publishes_independent_fields_without_concluding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9, transient_cost=True)
    await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    assert row["shipment_offset"] == 0 and row["state"] == "pending"
    assert set(db.data["shipments"]) == {"1"} and len(gateway.calls) == 3
    assert "real_shipping_cost" in db.data["shipments"]["1"]["unavailable_fields"]


@pytest.mark.asyncio
async def test_ordinary_completed_refresh_archives_concluded_cursor_before_new_cycle() -> None:
    db = DB(tuple("123"))
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    row.update(
        state="completed",
        shipment_offset=3,
        updated_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(minutes=1),
    )
    queue = FormulaRecoveryQueue(db, now=lambda: NOW, enabled_models=frozenset({"shipments"}))
    await queue.enqueue(ShipmentIdsRecoveryRequest(SELLER, tuple("123")))
    current = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    assert current["shipment_offset"] == 0 and current["shipment_ids"] == row["shipment_ids"]
    assert current["shipment_cursor_history"][-1]["offset"] == 3
    assert current["shipment_cursor_history"][-1]["completed_at"] == NOW - timedelta(hours=1)


@pytest.mark.asyncio
async def test_failed_partial_reopen_does_not_reset_cursor_or_attempts() -> None:
    db = DB(tuple("123"))
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    row.update(
        state="failed",
        shipment_offset=2,
        attempts=2,
        updated_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(minutes=1),
    )
    queue = FormulaRecoveryQueue(db, now=lambda: NOW, enabled_models=frozenset({"shipments"}))
    await queue.enqueue(ShipmentIdsRecoveryRequest(SELLER, tuple("123")))
    current = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    assert current["shipment_offset"] == 2 and current["attempts"] == 2
    assert "shipment_cursor_history" not in current


@pytest.mark.asyncio
async def test_h1_completed_nonreopen_and_pending_cursor_stay_unchanged() -> None:
    db = DB(tuple("123"))
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    row.update(state="completed", shipment_offset=3, updated_at=NOW - timedelta(hours=1))
    before = copy.deepcopy(row)
    queue = FormulaRecoveryQueue(db, now=lambda: NOW, enabled_models=frozenset({"shipments"}))
    await queue.enqueue(ShipmentIdsRecoveryRequest(SELLER, tuple("123")), reopen_terminal=False)
    assert db.data["sheets_formula_recovery_jobs"][db.job["_id"]] == before


@pytest.mark.asyncio
async def test_completed_cursor_with_wrong_list_cannot_reopen_under_old_key() -> None:
    db = DB(tuple("123"))
    row = db.data["sheets_formula_recovery_jobs"][db.job["_id"]]
    row.update(
        state="completed",
        shipment_offset=3,
        shipment_ids=["1", "2"],
        updated_at=NOW - timedelta(hours=1),
    )
    queue = FormulaRecoveryQueue(db, now=lambda: NOW, enabled_models=frozenset({"shipments"}))
    with pytest.raises(ValueError):
        await queue.enqueue(ShipmentIdsRecoveryRequest(SELLER, tuple("123")))


@pytest.mark.asyncio
async def test_resume_skips_concluded_units_without_changing_original_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    gateway.pause_after = 6
    instance = worker(monkeypatch, db, gateway)
    with pytest.raises(HistoryPolicyWaitError):
        await instance._shipments(copy.deepcopy(db.job))
    gateway.pause_after = None
    current = copy.deepcopy(db.data["sheets_formula_recovery_jobs"][db.job["_id"]])
    await instance._shipments(current)
    assert gateway.budget == 9 and len(gateway.calls) == 9
    assert gateway.calls[6:] == ["/shipments/3/orders", "/shipments/3", "/shipments/3/costs"]
    assert db.data["sheets_formula_recovery_jobs"][db.job["_id"]]["state"] == "completed"


@pytest.mark.asyncio
async def test_expired_lease_and_wrong_request_key_reject_before_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, gateway = DB(tuple("123")), Gateway(9)
    db.data["sheets_formula_recovery_jobs"][db.job["_id"]]["lease_until"] = NOW
    with pytest.raises(ValueError):
        await worker(monkeypatch, db, gateway)._shipments(copy.deepcopy(db.job))
    assert gateway.calls == []
    malformed = copy.deepcopy(db.job)
    malformed["_id"] = "wrong-key"
    with pytest.raises(ValueError):
        await worker(monkeypatch, db, gateway)._shipments(malformed)
    assert gateway.calls == []
