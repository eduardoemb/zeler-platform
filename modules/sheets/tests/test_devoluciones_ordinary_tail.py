"""DEVOLUCIONES freshness must not depend on a paused history pilot.

2026-10-07: with history on link disabled, the pilot's certified claims coverage
stopped at its last incremental run (2026-10-06T06:52Z). Only the paused plan
could extend it, so ``ZELERDATA_DEVOLUCIONES`` stayed unavailable for every
current range. Same principle as L-036: a paused pilot must not hold ordinary
work. With history on link off, the refresh loop ignores pilot runs and extends
certified coverage with one ordinary bounded run per day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.devoluciones_runner import (
    ORDINARY_TAIL_AUTHORIZATION,
    admit_ordinary_devoluciones_tail,
    advance_due_devoluciones_run,
    ordinary_tail_binding,
    ordinary_tail_bounds,
)

SELLER = "82453304"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
PILOT_END = datetime(2026, 10, 6, 6, 52, tzinfo=UTC)


def _run(**overrides: Any) -> dict[str, Any]:
    run = {
        "_id": "a" * 64,
        "seller_id": SELLER,
        "scope": "devoluciones",
        "state": "authorized",
        "authorization_id": "prod-20261007-abc",
        "expires_at": NOW + timedelta(hours=1),
        "created_at": NOW - timedelta(hours=2),
    }
    run.update(overrides)
    return run


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        actual = document.get(field)
        if not isinstance(expected, dict):
            if actual != expected:
                return False
            continue
        if "$exists" in expected and (field in document) is not expected["$exists"]:
            return False
        if "$in" in expected and actual not in expected["$in"]:
            return False
        if "$gt" in expected and not (isinstance(actual, datetime) and actual > expected["$gt"]):
            return False
        if "$lte" in expected and not (isinstance(actual, datetime) and actual <= expected["$lte"]):
            return False
        if "$not" in expected:
            pattern = expected["$not"]["$regex"]
            assert pattern.startswith("^")
            if str(actual).startswith(pattern[1:]):
                return False
    return True


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []
        self.queries: list[dict[str, Any]] = []

    async def find_one(
        self, query: dict[str, Any], *, sort: list[tuple[str, int]] | None = None
    ) -> dict[str, Any] | None:
        self.queries.append(query)
        matches = [document for document in self.documents if _matches(document, query)]
        for field, direction in reversed(sort or []):
            matches.sort(key=lambda document: document[field], reverse=direction < 0)
        return matches[0] if matches else None


class _Db:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self.collections = {name: _Collection(rows) for name, rows in collections.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self.collections.setdefault(name, _Collection())


def _runs_db(*runs: dict[str, Any]) -> _Db:
    return _Db(sheets_devoluciones_runs=list(runs))


async def _no_renewal(*_: Any, **__: Any) -> bool:
    return False


@pytest.fixture(autouse=True)
def _renewal_is_local(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    renewed: list[str] = []

    async def renew(db: Any, seller_id: str, **_: Any) -> bool:
        renewed.append(seller_id)
        return False

    monkeypatch.setattr(runner, "renew_devoluciones_marker_if_proven", renew)
    monkeypatch.setattr(runner, "_renew_active_before_advance", _no_renewal)
    return renewed


class _Recorder:
    def __init__(self, admitted: str | None = None) -> None:
        self.advanced: list[str] = []
        self.admissions: list[str] = []
        self.admitted = admitted

    async def advance(self, *, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        self.advanced.append(run_id)
        return {"advanced": 1, "finalized": 0}

    async def admit(self, db: Any, seller_id: str, *, now: Any = None) -> str | None:
        self.admissions.append(seller_id)
        return self.admitted


@pytest.mark.asyncio
async def test_history_off_skips_a_paused_pilot_run_and_advances_an_ordinary_one() -> None:
    recorder = _Recorder()
    db = _runs_db(
        _run(_id="o" * 64, created_at=NOW - timedelta(hours=5)),
        _run(_id="p" * 64, authorization_id="onboarding:82453304", created_at=NOW),
    )

    moved = await advance_due_devoluciones_run(
        db,
        SELLER,
        now=lambda: NOW,
        advance=recorder.advance,
        history_work_enabled=False,
        admit_tail=recorder.admit,
    )

    assert moved is True
    assert recorder.advanced == ["o" * 64]
    assert recorder.admissions == []


@pytest.mark.asyncio
async def test_history_off_admits_an_ordinary_tail_when_only_pilot_runs_are_due(
    _renewal_is_local: list[str],
) -> None:
    recorder = _Recorder(admitted="t" * 64)
    db = _runs_db(_run(_id="p" * 64, authorization_id="onboarding:82453304"))

    moved = await advance_due_devoluciones_run(
        db,
        SELLER,
        now=lambda: NOW,
        advance=recorder.advance,
        history_work_enabled=False,
        admit_tail=recorder.admit,
    )

    assert moved is True
    assert recorder.admissions == [SELLER]
    assert recorder.advanced == ["t" * 64]
    # Existing proofs keep renewing even when the cycle does source work.
    assert _renewal_is_local == [SELLER]


@pytest.mark.asyncio
async def test_history_off_without_a_due_tail_does_no_source_work(
    _renewal_is_local: list[str],
) -> None:
    recorder = _Recorder(admitted=None)

    moved = await advance_due_devoluciones_run(
        _runs_db(),
        SELLER,
        now=lambda: NOW,
        advance=recorder.advance,
        history_work_enabled=False,
        admit_tail=recorder.admit,
    )

    assert moved is False
    assert recorder.advanced == []
    assert _renewal_is_local == [SELLER]


@pytest.mark.asyncio
async def test_history_on_keeps_pilot_runs_and_never_admits_a_tail() -> None:
    recorder = _Recorder(admitted="t" * 64)
    db = _runs_db(_run(_id="p" * 64, authorization_id="onboarding:82453304"))

    moved = await advance_due_devoluciones_run(
        db, SELLER, now=lambda: NOW, advance=recorder.advance, admit_tail=recorder.admit
    )
    idle = await advance_due_devoluciones_run(
        _runs_db(), SELLER, now=lambda: NOW, advance=recorder.advance, admit_tail=recorder.admit
    )

    assert (moved, idle) == (True, False)
    assert recorder.advanced == ["p" * 64]
    assert recorder.admissions == []


@pytest.mark.asyncio
async def test_advance_disabled_never_admits_a_tail(_renewal_is_local: list[str]) -> None:
    recorder = _Recorder(admitted="t" * 64)

    moved = await advance_due_devoluciones_run(
        _runs_db(),
        SELLER,
        now=lambda: NOW,
        advance=recorder.advance,
        advance_enabled=False,
        history_work_enabled=False,
        admit_tail=recorder.admit,
    )

    assert moved is False
    assert recorder.admissions == []
    assert _renewal_is_local == [SELLER]


def test_tail_extends_from_the_latest_certificate_to_the_settled_utc_midnight() -> None:
    assert ordinary_tail_bounds(PILOT_END, now=NOW) == (
        PILOT_END,
        datetime(2026, 10, 7, tzinfo=UTC),
    )


def test_tail_waits_for_the_settle_margin_after_midnight() -> None:
    covered = datetime(2026, 10, 7, tzinfo=UTC)

    assert ordinary_tail_bounds(covered, now=datetime(2026, 10, 8, 0, 30, tzinfo=UTC)) is None
    assert ordinary_tail_bounds(covered, now=datetime(2026, 10, 8, 1, 0, tzinfo=UTC)) == (
        covered,
        datetime(2026, 10, 8, tzinfo=UTC),
    )


def test_tail_caps_a_long_gap_at_one_partition_window() -> None:
    covered = datetime(2026, 9, 1, tzinfo=UTC)

    assert ordinary_tail_bounds(covered, now=NOW) == (covered, datetime(2026, 9, 11, tzinfo=UTC))


def test_tail_never_starts_without_certified_coverage() -> None:
    assert ordinary_tail_bounds(None, now=NOW) is None
    # Naive BSON dates are UTC, never local time.
    assert ordinary_tail_bounds(PILOT_END.replace(tzinfo=None), now=NOW) == (
        PILOT_END,
        datetime(2026, 10, 7, tzinfo=UTC),
    )


def test_tail_binding_is_ordinary_and_changes_only_by_bounds_or_day() -> None:
    end = datetime(2026, 10, 7, tzinfo=UTC)
    binding = ordinary_tail_binding(SELLER, PILOT_END, end, admitted_on=date(2026, 10, 7))

    assert binding.authorization_id == ORDINARY_TAIL_AUTHORIZATION
    assert not binding.authorization_id.startswith("onboarding:")
    assert (binding.seller_id, binding.scope) == (SELLER, "devoluciones")
    assert (binding.start, binding.end) == (PILOT_END, end)
    same_day = ordinary_tail_binding(SELLER, PILOT_END, end, admitted_on=date(2026, 10, 7))
    next_day = ordinary_tail_binding(SELLER, PILOT_END, end, admitted_on=date(2026, 10, 8))
    assert same_day.run_id == binding.run_id
    assert next_day.run_id != binding.run_id


def _control(**overrides: Any) -> dict[str, Any]:
    control = {
        "_id": f"{SELLER}:devoluciones",
        "seller_id": SELLER,
        "scope": "devoluciones",
        "coverage_mode": "active",
        "fence": 7,
        "coverage_ack_fence": 7,
        "coverage_epoch": 2,
    }
    control.update(overrides)
    return control


def _certificate(date_to: datetime, *, epoch: int = 2) -> dict[str, Any]:
    return {
        "seller_id": SELLER,
        "coverage_epoch": epoch,
        "date_from": date_to - timedelta(days=1),
        "date_to": date_to,
    }


class _Admission:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.acquired: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        self.created: list[Any] = []
        admission = self

        async def acquire(**kwargs: Any) -> Any:
            admission.acquired.append(kwargs)
            return MagicMock(name="operation")

        async def finish(**kwargs: Any) -> None:
            admission.finished.append(kwargs)

        class Repository:
            def __init__(self, db: Any) -> None:
                self.db = db

            async def create(self, binding: Any, **_: Any) -> bool:
                admission.created.append(binding)
                return True

        monkeypatch.setattr(runner, "_acquire_onboarding_operation", acquire)
        monkeypatch.setattr(runner, "_finish_onboarding_operation", finish)
        monkeypatch.setattr(runner, "_OnboardingRepository", Repository)


@pytest.mark.asyncio
async def test_admission_requires_active_compatible_certificate_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    certificates = [_certificate(PILOT_END)]

    for control in (
        _control(coverage_mode="legacy"),
        _control(coverage_ack_fence=6),
        _control(coverage_epoch=None),
    ):
        db = _Db(
            sheets_devoluciones_operations=[control],
            sheets_devoluciones_certificates=certificates,
        )
        assert await admit_ordinary_devoluciones_tail(db, SELLER, now=lambda: NOW) is None
    assert admission.acquired == []


@pytest.mark.asyncio
async def test_admission_extends_the_current_epoch_once_per_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    db = _Db(
        sheets_devoluciones_operations=[_control()],
        sheets_devoluciones_certificates=[
            _certificate(PILOT_END - timedelta(days=3)),
            _certificate(PILOT_END),
            # A previous epoch's later proof is not current coverage.
            _certificate(PILOT_END + timedelta(hours=12), epoch=1),
        ],
    )

    run_id = await admit_ordinary_devoluciones_tail(db, SELLER, now=lambda: NOW)

    expected = ordinary_tail_binding(
        SELLER, PILOT_END, datetime(2026, 10, 7, tzinfo=UTC), admitted_on=NOW.date()
    )
    assert run_id == expected.run_id
    assert admission.created == [expected]
    assert admission.acquired[0]["invalidate_readiness"] is False
    assert admission.acquired[0]["require_coverage_compatible"] is True
    assert [call["succeeded"] for call in admission.finished] == [True]

    # A failed or expired run is not retried until the next UTC day.
    db["sheets_devoluciones_runs"].documents.append(_run(_id=run_id, state="failed"))
    assert await admit_ordinary_devoluciones_tail(db, SELLER, now=lambda: NOW) is None
    assert len(admission.created) == 1


@pytest.mark.asyncio
async def test_runtime_advance_routes_a_tail_run_without_pilot_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routed: list[str] = []

    async def advance_tail(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        routed.append(run_id)
        return {"advanced": 1, "finalized": 0}

    monkeypatch.setattr(runner, "advance_ordinary_devoluciones_tail", advance_tail)
    db = _Db(
        sheets_devoluciones_runs=[_run(_id="t" * 64, authorization_id=ORDINARY_TAIL_AUTHORIZATION)]
    )

    outcome = await runner._runtime_advance(db=db, run_id="t" * 64, now=lambda: NOW)

    assert outcome == {"advanced": 1, "finalized": 0}
    assert routed == ["t" * 64]
    assert db["sheets_history_backfill_plans"].queries == []


@pytest.mark.asyncio
async def test_tail_advance_uses_the_ordinary_runtime_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    admission = _Admission(monkeypatch)
    executed: list[dict[str, Any]] = []

    async def execute(**kwargs: Any) -> dict[str, Any]:
        executed.append(kwargs)
        return {}

    async def advance(**kwargs: Any) -> dict[str, int]:
        await kwargs["source"](window={"index": 0}, call_budget=104)
        return {"advanced": 1, "finalized": 0}

    monkeypatch.setattr(reconcile, "execute_devoluciones_quota_window", execute)
    monkeypatch.setattr(reconcile, "advance_devoluciones_quota_run", advance)
    db = _Db(
        sheets_devoluciones_runs=[_run(_id="t" * 64, authorization_id=ORDINARY_TAIL_AUTHORIZATION)]
    )

    outcome = await runner.advance_ordinary_devoluciones_tail(db, "t" * 64, now=lambda: NOW)

    assert outcome == {"advanced": 1, "finalized": 0}
    # No source override: the window uses the ordinary runtime gateway, never
    # the pilot plan budget.
    assert "source" not in executed[0]
    assert executed[0]["window"] == {"index": 0}
    # Only the tail retires pre-v2 rows its inventory no longer reports.
    assert executed[0]["quarantine_legacy_claims"] is True
    assert admission.acquired[0]["source_fingerprint"] == "t" * 64
    assert admission.acquired[0]["require_coverage_compatible"] is True
    assert [call["succeeded"] for call in admission.finished] == [True]
    assert db["sheets_history_backfill_plans"].queries == []


@pytest.mark.asyncio
async def test_tail_finalizes_its_last_window_in_the_same_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-window run expires 1070 s after admission, but the next cycle only
    arrives after the cycle's own work plus 900 s. Waiting for it would let the
    tail expire unfinalized on every busy cycle; its readback is local.
    """
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    admission = _Admission(monkeypatch)
    run = _run(
        _id="t" * 64,
        state="authorized",
        authorization_id=ORDINARY_TAIL_AUTHORIZATION,
        window_count=1,
        next_window_index=0,
    )
    finalized: list[dict[str, Any]] = []

    async def advance(**kwargs: Any) -> dict[str, int]:
        run.update(state="active", next_window_index=1, not_before=NOW + timedelta(minutes=10))
        return {"advanced": 1, "finalized": 0}

    async def finalize(**kwargs: Any) -> dict[str, int]:
        finalized.append(kwargs)
        return {"advanced": 0, "finalized": 1}

    monkeypatch.setattr(reconcile, "advance_devoluciones_quota_run", advance)
    monkeypatch.setattr(reconcile, "_finalize_devoluciones_quota_run", finalize)

    outcome = await runner.advance_ordinary_devoluciones_tail(
        _runs_db(run), "t" * 64, now=lambda: NOW
    )

    assert outcome == {"advanced": 1, "finalized": 1}
    assert finalized[0]["run"]["_id"] == "t" * 64
    assert finalized[0]["current"] == NOW
    assert finalized[0]["readback"] is not None
    assert [call["succeeded"] for call in admission.finished] == [True]


@pytest.mark.asyncio
async def test_tail_does_not_finalize_a_failed_or_unfinished_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    _Admission(monkeypatch)
    finalized: list[dict[str, Any]] = []

    async def finalize(**kwargs: Any) -> dict[str, int]:
        finalized.append(kwargs)
        return {"advanced": 0, "finalized": 1}

    monkeypatch.setattr(reconcile, "_finalize_devoluciones_quota_run", finalize)
    for state, next_index, advanced in (("failed", 0, 0), ("active", 1, 1)):
        run = _run(
            _id="t" * 64,
            authorization_id=ORDINARY_TAIL_AUTHORIZATION,
            window_count=2,
            next_window_index=0,
        )

        async def advance(
            run: dict[str, Any] = run,
            state: str = state,
            index: int = next_index,
            moved: int = advanced,
        ) -> dict[str, int]:
            run.update(state=state, next_window_index=index)
            return {"advanced": moved, "finalized": 0}

        monkeypatch.setattr(reconcile, "advance_devoluciones_quota_run", lambda **_: advance())
        outcome = await runner.advance_ordinary_devoluciones_tail(
            _runs_db(run), "t" * 64, now=lambda: NOW
        )
        assert outcome == {"advanced": advanced, "finalized": 0}
    assert finalized == []


@pytest.mark.asyncio
async def test_tail_advance_refuses_a_run_it_does_not_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    db = _runs_db(_run(_id="p" * 64, authorization_id="onboarding:82453304"))

    with pytest.raises(ValueError, match="ordinary tail"):
        await runner.advance_ordinary_devoluciones_tail(db, "p" * 64, now=lambda: NOW)
    assert admission.acquired == []


@pytest.mark.asyncio
async def test_refresh_wiring_passes_history_on_link_to_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets import consumer
    from zeler_sheets.formulas.recovery import FormulaRecoveryQueue

    captured: list[dict[str, Any]] = []

    async def advance_due(db: Any, seller_id: str, **kwargs: Any) -> bool:
        captured.append(kwargs)
        return False

    async def no_indexes(self: Any) -> None:
        return None

    monkeypatch.setattr(consumer, "advance_due_devoluciones_run", advance_due)
    monkeypatch.setattr(FormulaRecoveryQueue, "ensure_indexes", no_indexes)
    for name in (
        "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
        "ZELERDATA_DLQ_ARCHIVE_ENABLED",
        "ZELERDATA_FRESHNESS_ALERTS_ENABLED",
        "ZELERDATA_HISTORY_ON_LINK_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", SELLER)

    supervisor = await consumer.build_zelerdata_refresh_supervisor(db=MagicMock())
    assert supervisor._devoluciones_runner is not None
    await supervisor._devoluciones_runner(SELLER)

    assert captured == [{"advance_enabled": True, "history_work_enabled": False}]
