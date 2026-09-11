"""Tests for advancing authorized DEVOLUCIONES runs from the refresh loop.

The retired systemd timer used to own this trigger. Q2-b/Q7-a moved it into the
same worker loop that keeps the read models fresh, without widening the
authorization boundary: the loop may only advance a run that already exists,
is still unexpired, and is past its own ``not_before``. It never creates one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.devoluciones_runner import (
    ADVANCEABLE_RUN_STATES,
    advance_due_devoluciones_run,
)

SELLER = "82453304"
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class _Collection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.queries: list[dict[str, Any]] = []

    async def find_one(
        self,
        filter_spec: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        self.queries.append(filter_spec)
        matches = [doc for doc in self.documents if _matches(doc, filter_spec, now=NOW)]
        if sort is not None:
            for field, direction in reversed(sort):
                matches.sort(
                    key=lambda doc: doc.get(field) or datetime.min.replace(tzinfo=UTC),
                    reverse=direction < 0,
                )
        return matches[0] if matches else None


def _matches(document: dict[str, Any], filter_spec: dict[str, Any], *, now: datetime) -> bool:
    for field, expected in filter_spec.items():
        if field == "$or":
            if not any(_matches(document, clause, now=now) for clause in expected):
                return False
            continue
        actual = document.get(field)
        if isinstance(expected, dict):
            if "$exists" in expected:
                # Mongo's $exists reads presence, not truthiness: an explicit
                # null is present.
                present = field in document
                if present is not expected["$exists"]:
                    return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gt" in expected and not (
                isinstance(actual, datetime) and actual > expected["$gt"]
            ):
                return False
            if "$lte" in expected and not (
                isinstance(actual, datetime) and actual <= expected["$lte"]
            ):
                return False
            continue
        if actual != expected:
            return False
    return True


class _Db:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self.runs = _Collection(runs)

    def __getitem__(self, name: str) -> _Collection:
        return self.runs


def _run(**overrides: Any) -> dict[str, Any]:
    run = {
        "_id": "a" * 64,
        "seller_id": SELLER,
        "scope": "devoluciones",
        "state": "active",
        "authorization_id": "prod-20260911-abc",
        "not_before": NOW - timedelta(minutes=10),
        "expires_at": NOW + timedelta(hours=1),
        "created_at": NOW - timedelta(hours=2),
    }
    run.update(overrides)
    return run


@pytest.mark.asyncio
async def test_advances_the_newest_due_authorized_run_once() -> None:
    advanced: list[str] = []
    db = _Db(
        [
            _run(_id="b" * 64, created_at=NOW - timedelta(hours=5)),
            _run(_id="c" * 64, created_at=NOW - timedelta(hours=1)),
        ]
    )

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    moved = await advance_due_devoluciones_run(db, SELLER, now=lambda: NOW, advance=advance)

    assert moved is True
    assert advanced == ["c" * 64]


@pytest.mark.asyncio
async def test_no_authorized_run_means_no_source_work() -> None:
    advanced: list[str] = []
    db = _Db([_run(state="failed")])

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    moved = await advance_due_devoluciones_run(db, SELLER, now=lambda: NOW, advance=advance)

    assert moved is False
    assert advanced == []


@pytest.mark.asyncio
async def test_expired_or_not_yet_due_runs_are_never_advanced() -> None:
    advanced: list[str] = []

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    expired = _Db([_run(expires_at=NOW - timedelta(minutes=1))])
    assert (
        await advance_due_devoluciones_run(expired, SELLER, now=lambda: NOW, advance=advance)
        is False
    )

    early = _Db([_run(not_before=NOW + timedelta(minutes=5))])
    assert (
        await advance_due_devoluciones_run(early, SELLER, now=lambda: NOW, advance=advance) is False
    )

    assert advanced == []


@pytest.mark.asyncio
async def test_another_sellers_run_is_never_advanced() -> None:
    advanced: list[str] = []
    db = _Db([_run(seller_id="999")])

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    assert await advance_due_devoluciones_run(db, SELLER, now=lambda: NOW, advance=advance) is False
    assert advanced == []


def test_only_authorized_and_active_states_are_advanceable() -> None:
    assert frozenset({"authorized", "active"}) == ADVANCEABLE_RUN_STATES
