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
    renew_devoluciones_marker_if_proven,
)

SELLER = "82453304"
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
MARKER_ID = f"{SELLER}:devoluciones"


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


@pytest.mark.asyncio
async def test_the_cycle_renews_a_settled_marker_when_no_window_is_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed run must keep its proof productive between authorizations.

    The finalize publishes the marker once. Without this renewal the 30-minute
    lease expires while the proven rows are still in Mongo, and an acquisition
    that invalidates readiness leaves the formula unavailable indefinitely.
    """
    from zeler_sheets import devoluciones_runner as runner_module

    renewed: list[str] = []
    db = _Db([_run(state="completed")])

    async def renew(database: Any, seller_id: str, **_: Any) -> bool:
        renewed.append(seller_id)
        return True

    monkeypatch.setattr(runner_module, "renew_devoluciones_marker_if_proven", renew)

    moved = await advance_due_devoluciones_run(db, SELLER, now=lambda: NOW)

    assert moved is False
    assert renewed == [SELLER]


@pytest.mark.asyncio
async def test_the_cycle_does_not_renew_while_a_window_still_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets import devoluciones_runner as runner_module

    advanced: list[str] = []
    renewed: list[str] = []
    db = _Db([_run()])

    async def advance(*, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    async def renew(database: Any, seller_id: str, **_: Any) -> bool:
        renewed.append(seller_id)
        return True

    monkeypatch.setattr(runner_module, "renew_devoluciones_marker_if_proven", renew)

    moved = await advance_due_devoluciones_run(db, SELLER, now=lambda: NOW, advance=advance)

    assert moved is True
    assert advanced == ["a" * 64]
    assert renewed == []


class _MarkerCollection:
    """Minimal marker surface: a document plus the CAS updates it received."""

    def __init__(self, document: dict[str, Any] | None) -> None:
        self.document = document
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def find_one(self, filter_spec: dict[str, Any], *_: Any, **__: Any) -> Any:
        assert filter_spec["_id"] == MARKER_ID
        return None if self.document is None else dict(self.document)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], **_: Any
    ) -> Any:
        self.updates.append((filter_spec, update))
        if self.document is None or self.document.get("proof_fingerprint") != filter_spec.get(
            "proof_fingerprint"
        ):
            return _UpdateResult(matched_count=0)
        self.document.update(update["$set"])
        return _UpdateResult(matched_count=1)


class _UpdateResult:
    def __init__(self, *, matched_count: int) -> None:
        self.matched_count = matched_count
        self.modified_count = matched_count


class _MarkerDb:
    def __init__(
        self,
        document: dict[str, Any] | None,
        *,
        runs: list[dict[str, Any]] | None = None,
        operations: list[dict[str, Any]] | None = None,
    ) -> None:
        self.markers = _MarkerCollection(document)
        self.runs = _Collection(runs or [])
        self.operations = _Collection(operations or [])

    def __getitem__(self, name: str) -> Any:
        if name == "sheets_read_model_freshness":
            return self.markers
        if name == "sheets_devoluciones_operations":
            return self.operations
        assert name == "sheets_devoluciones_runs"
        return self.runs


def _proven_marker(**overrides: Any) -> dict[str, Any]:
    marker = {
        "_id": MARKER_ID,
        "seller_id": SELLER,
        "read_model": "devoluciones",
        "state": "stale",
        "fresh_until": NOW - timedelta(minutes=1),
        "valid_until": NOW - timedelta(minutes=1),
        "date_from": datetime(2026, 6, 1, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 11, tzinfo=UTC),
        "last_event_synced_at": datetime(2026, 6, 1, tzinfo=UTC),
        "source": "devoluciones_operation_acquire",
        "revision": "a" * 64,
        "proof_fingerprint": "proven-fingerprint",
        "updated_at": NOW - timedelta(minutes=2),
        "schema_version": 1,
    }
    marker.update(overrides)
    return marker


def _completed_run(**overrides: Any) -> dict[str, Any]:
    run = _run(state="completed", _id="a" * 64)
    run.update(overrides)
    return run


@pytest.mark.asyncio
async def test_marker_renewal_restores_a_proven_devoluciones_marker() -> None:
    """The settled proof must stay productive across the 30-minute marker lease.

    Nothing re-runs the quota finalize until the next authorized run, so without
    a renewal every settled window would expire and ``ZELERDATA_DEVOLUCIONES``
    would fail closed while the proven rows are still in Mongo.
    """
    db = _MarkerDb(_proven_marker(), runs=[_completed_run()])
    calls: list[str] = []

    async def fingerprint(**_: Any) -> str | None:
        calls.append("fingerprint")
        return "proven-fingerprint"

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=fingerprint
    )

    assert renewed is True
    assert calls == ["fingerprint"]
    marker = db.markers.document
    assert marker is not None
    assert marker["state"] == "reconciled"
    assert marker["valid_until"] == NOW + timedelta(minutes=30)
    assert marker["updated_at"] == NOW
    assert marker["source"] == "zelerdata_devoluciones_quota_run"
    assert marker["proof_fingerprint"] == "proven-fingerprint"
    assert marker["revision"] == "a" * 64
    # The formula gate requires fresh_until == reconciled_until; the invalidation
    # had collapsed fresh_until to "now", so renewal must restore the pair.
    assert marker["fresh_until"] == marker["reconciled_until"]
    assert marker["date_from"] == datetime(2026, 6, 1, tzinfo=UTC)
    assert marker["last_event_synced_at"] == marker["date_from"]


@pytest.mark.asyncio
async def test_marker_renewal_refuses_when_the_durable_proof_changed() -> None:
    db = _MarkerDb(_proven_marker(), runs=[_completed_run()])

    async def changed(**_: Any) -> str | None:
        return "a-different-fingerprint"

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=changed
    )

    assert renewed is False
    assert db.markers.updates == []
    stored = db.markers.document
    assert stored is not None and stored["state"] == "stale"


@pytest.mark.asyncio
async def test_marker_renewal_extends_a_still_open_proof_before_it_lapses() -> None:
    """The renewal is a heartbeat, not an expiry repair.

    The refresh cycle only reaches this model once every 15 minutes, so waiting
    for the 30-minute lease to lapse leaves a multi-minute window where the
    proven range is unreadable. Extending a still-open proof on every cycle is
    what keeps ``ZELERDATA_DEVOLUCIONES`` continuously available.
    """
    db = _MarkerDb(
        _proven_marker(
            state="reconciled",
            fresh_until=datetime(2026, 6, 11),
            valid_until=(NOW + timedelta(minutes=20)).replace(tzinfo=None),
        ),
        runs=[_completed_run()],
    )
    calls: list[str] = []

    async def fingerprint(**_: Any) -> str | None:
        calls.append("fingerprint")
        return "proven-fingerprint"

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=fingerprint
    )

    assert renewed is True
    assert calls == ["fingerprint"]
    marker = db.markers.document
    assert marker is not None
    assert marker["state"] == "reconciled"
    assert marker["valid_until"] == NOW + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_marker_renewal_requires_an_exact_fingerprint() -> None:
    db = _MarkerDb(_proven_marker(proof_fingerprint=None), runs=[_completed_run()])

    async def forbidden(**_: Any) -> str | None:
        raise AssertionError("a marker without proof must not be renewed")

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=forbidden
    )

    assert renewed is False
    assert db.markers.updates == []


@pytest.mark.asyncio
async def test_marker_renewal_defers_while_a_withdrawing_acquisition_holds_the_lease() -> None:
    """A live re-acquisition keeps its proof withdrawn.

    ``acquire_devoluciones_operation`` withdraws readiness so no reader consumes
    a proof while claims are being rewritten. A heartbeat that ignored the live
    lease would resurrect exactly what that guard withdrew, so the renewal
    defers until the acquisition releases.
    """
    db = _MarkerDb(
        _proven_marker(state="stale"),
        runs=[_completed_run()],
        operations=[
            {
                "_id": f"{SELLER}:devoluciones",
                "seller_id": SELLER,
                "scope": "devoluciones",
                "state": "running",
                "lease_until": NOW + timedelta(seconds=60),
            }
        ],
    )

    async def forbidden(**_: Any) -> str | None:
        raise AssertionError("a withdrawing acquisition must not be renewed over")

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=forbidden
    )

    assert renewed is False
    assert db.markers.updates == []


@pytest.mark.asyncio
async def test_marker_renewal_extends_a_reconciled_proof_under_a_live_sweep() -> None:
    """An acquisition that does not withdraw readiness must not stall the heartbeat.

    Only ``claims.*`` invalidates readiness when it acquires the shared
    DEVOLUCIONES lease. The ``orders`` sweep takes the same lease without
    withdrawing the proof, so a live acquisition is not by itself evidence that
    the reconciled marker is unsafe to extend.
    """
    db = _MarkerDb(
        _proven_marker(state="reconciled"),
        runs=[_completed_run()],
        operations=[
            {
                "_id": f"{SELLER}:devoluciones",
                "seller_id": SELLER,
                "scope": "devoluciones",
                "state": "running",
                "lease_until": NOW + timedelta(seconds=60),
            }
        ],
    )
    calls: list[str] = []

    async def fingerprint(**_: Any) -> str | None:
        calls.append("fingerprint")
        return "proven-fingerprint"

    renewed = await renew_devoluciones_marker_if_proven(
        db, SELLER, now=lambda: NOW, finalization_fingerprint=fingerprint
    )

    assert renewed is True
    assert calls == ["fingerprint"]
    marker = db.markers.document
    assert marker is not None
    assert marker["valid_until"] == NOW + timedelta(minutes=30)
