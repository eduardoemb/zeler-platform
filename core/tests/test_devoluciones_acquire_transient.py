"""Aborted-transaction WriteConflict retry is bounded, database-only and identity-stable."""

from __future__ import annotations

import copy
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pymongo.errors import OperationFailure
from pymongo.results import UpdateResult

from zeler_platform_core.devoluciones_readiness import acquire_devoluciones_operation

NOW = datetime(2026, 10, 6, 5, 24, tzinfo=UTC)
TOKEN = "a" * 32


def failure(
    code: int = 112, labels: tuple[str, ...] = ("TransientTransactionError",)
) -> OperationFailure:
    return OperationFailure(
        "synthetic database failure", code=code, details={"code": code, "errorLabels": list(labels)}
    )


class Transaction:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def __aenter__(self) -> Transaction:
        self.session.working = copy.deepcopy(self.session.db.documents)
        self.session.db.started += 1
        return self

    async def __aexit__(self, error_type: Any, error: Any, traceback: Any) -> None:
        db = self.session.db
        if error is not None:
            db.aborted += 1
            return
        if db.commit_error is not None:
            # Unknown commit outcome can already have committed: replay is unsafe.
            db.documents = copy.deepcopy(self.session.working)
            db.committed += 1
            raise db.commit_error
        db.documents = copy.deepcopy(self.session.working)
        db.committed += 1


class Session:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.working: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> Session:
        self.db.sessions += 1
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.db.closed += 1

    def start_transaction(self) -> Transaction:
        return Transaction(self)


class Collection:
    def __init__(self, db: Database, name: str) -> None:
        self.db, self.name = db, name

    async def find_one(self, query: dict[str, Any], *, session: Session) -> dict[str, Any]:
        self.db.reads.append((self.name, self.db.started))
        return copy.deepcopy(session.working[self.name])

    async def update_one(
        self, query: dict[str, Any], update: Any, *, upsert: bool = False, session: Session
    ) -> UpdateResult:
        self.db.writes.append((self.name, self.db.started, copy.deepcopy(update)))
        fields = update[0]["$set"]
        session.working[self.name].update(copy.deepcopy(fields))
        if self.name == "sheets_read_model_freshness" and self.db.started <= len(self.db.errors):
            error = self.db.errors[self.db.started - 1]
            if error is not None:
                raise error
        return UpdateResult({"n": 1, "nModified": 1}, True)


class Database:
    def __init__(
        self, errors: list[OperationFailure | None], *, commit_error: OperationFailure | None = None
    ) -> None:
        self.errors, self.commit_error = errors, commit_error
        self.started = self.aborted = self.committed = self.sessions = self.closed = 0
        self.reads: list[tuple[str, int]] = []
        self.writes: list[tuple[str, int, Any]] = []
        self.documents: dict[str, dict[str, Any]] = {
            "sheets_read_model_freshness": {
                "_id": "82:devoluciones",
                "seller_id": "82",
                "read_model": "devoluciones",
                "state": "reconciled",
                "date_from": NOW - timedelta(days=10),
                "reconciled_until": NOW,
                "valid_until": NOW + timedelta(minutes=20),
            },
            "sheets_devoluciones_operations": {
                "_id": "82:devoluciones",
                "seller_id": "82",
                "scope": "devoluciones",
                "state": "succeeded",
                "fence": 7,
                "coverage_ack_fence": 7,
                "coverage_mode": "active",
                "coverage_epoch": 9,
                "source_fingerprint": "fixture-source",
                "checkpoint": {"kept": 17},
            },
        }
        self.client = self

    def start_session(self) -> Session:
        return Session(self)

    def __getitem__(self, name: str) -> Collection:
        assert name in self.documents, "acquisition may touch only its two DB collections"
        return Collection(self, name)


async def acquire(db: Database) -> Any:
    return await acquire_devoluciones_operation(
        db=db,
        seller_id="82",
        scope="devoluciones",
        operation_id="fixture-stable-operation",
        attempt_token=TOKEN,
        source_fingerprint="fixture-source",
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("transaction fakes cannot access sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize("conflicts", [1, 2])
async def test_aborted_write_conflict_retries_whole_txn_with_same_identity(conflicts: int) -> None:
    db = Database([failure() for _ in range(conflicts)])
    result = await acquire(db)
    assert db.started == db.sessions == db.closed == conflicts + 1
    assert db.aborted == conflicts and db.committed == 1
    assert result.operation_id == "fixture-stable-operation" and result.attempt_token == TOKEN
    assert result.fence == 8 and result.coverage_epoch == 9 and result.checkpoint == {"kept": 17}
    assert len([r for r in db.reads if r[0] == "sheets_read_model_freshness"]) == conflicts + 1
    leases = [
        update[0]["$set"]
        for name, _, update in db.writes
        if name == "sheets_devoluciones_operations"
    ]
    assert len(leases) == 1 and leases[0]["fence"] == 8
    assert (
        leases[0]["attempt_token"] == TOKEN
        and leases[0]["operation_id"] == "fixture-stable-operation"
    )
    assert leases[0]["lease_until"] == {
        "$dateAdd": {"startDate": "$$NOW", "unit": "second", "amount": 120}
    }


@pytest.mark.asyncio
async def test_three_conflicts_exhaust_without_any_committed_side_effect() -> None:
    db = Database([failure(), failure(), failure()])
    before = copy.deepcopy(db.documents)
    with pytest.raises(OperationFailure) as caught:
        await acquire(db)
    assert caught.value.code == 112
    assert db.started == db.aborted == db.closed == 3 and db.committed == 0
    assert db.documents == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "labels"),
    [(112, ()), (121, ("TransientTransactionError",)), (13, ("TransientTransactionError",))],
)
async def test_other_errors_never_retry(code: int, labels: tuple[str, ...]) -> None:
    error = failure(code, labels)
    db = Database([error])
    before = copy.deepcopy(db.documents)
    with pytest.raises(OperationFailure) as caught:
        await acquire(db)
    assert caught.value is error
    assert db.started == db.aborted == db.closed == 1 and db.committed == 0
    assert db.documents == before


@pytest.mark.asyncio
async def test_uncertain_commit_never_replays_an_already_possible_commit() -> None:
    error = failure(112, ("TransientTransactionError", "UnknownTransactionCommitResult"))
    db = Database([], commit_error=error)
    with pytest.raises(OperationFailure) as caught:
        await acquire(db)
    assert caught.value is error
    assert db.started == db.committed == db.closed == 1 and db.aborted == 0
    assert db.documents["sheets_devoluciones_operations"]["fence"] == 8
