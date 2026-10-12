"""An eligible seller without DEVOLUCIONES coverage gets it from the refresh loop.

Until 2026-10-12 only the pilot advanced. A new seller's bootstrap leaves a
legacy coverage control and a stale marker, the onboarding initializer needs no
control at all, and the ordinary tail needs a certificate to extend, so the
seller never received coverage without an operator quota run (pilot-only) and
``devoluciones_certificate_migrate``. The loop now admits the seller's oldest
window, activates certificate coverage from that window's proof, and lets the
tail catch up the rest, one window per cycle for the whole fleet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from structlog.testing import capture_logs

from zeler_sheets import devoluciones_runner as runner
from zeler_sheets.devoluciones_runner import (
    INITIAL_COVERAGE_AUTHORIZATION,
    ORDINARY_TAIL_AUTHORIZATION,
    admit_initial_devoluciones_coverage,
    advance_due_devoluciones_run,
    initial_coverage_binding,
    initial_coverage_bounds,
)
from zeler_sheets.formulas.refresh import ZelerDataRefreshSupervisor

SELLER = "90000001"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
SETTLED = datetime(2026, 10, 12, tzinfo=UTC)
INITIAL = (SETTLED - timedelta(days=90), SETTLED - timedelta(days=80))


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []

    async def find_one(self, query: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        for document in self.documents:
            if all(document.get(field) == value for field, value in query.items()):
                return document
        return None


class _Db:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self.collections = {name: _Collection(rows) for name, rows in collections.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self.collections.setdefault(name, _Collection())


def _legacy_control() -> dict[str, Any]:
    # What the bootstrap claims stage leaves behind.
    return {
        "_id": f"{SELLER}:devoluciones",
        "seller_id": SELLER,
        "scope": "devoluciones",
        "coverage_mode": "legacy",
        "fence": 1,
        "coverage_ack_fence": 1,
        "coverage_epoch": 0,
    }


def _stale_marker(**proof: Any) -> dict[str, Any]:
    return {
        "_id": f"{SELLER}:devoluciones",
        "seller_id": SELLER,
        "read_model": "devoluciones",
        "state": "stale",
        "source": "devoluciones_operation_acquire",
        **proof,
    }


def _new_seller_db(**collections: list[dict[str, Any]]) -> _Db:
    return _Db(
        sheets_devoluciones_operations=[_legacy_control()],
        sheets_read_model_freshness=[_stale_marker()],
        **collections,
    )


def _gate(*eligible: str) -> Any:
    checked: list[str] = []

    async def gate(seller_id: str) -> bool:
        checked.append(seller_id)
        return seller_id in eligible

    gate.checked = checked  # type: ignore[attr-defined]
    return gate


class _Admission:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, mode: str = "legacy") -> None:
        self.acquired: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        self.created: list[Any] = []
        self.events: list[str] = []
        admission = self

        async def acquire(**kwargs: Any) -> Any:
            admission.acquired.append(kwargs)
            return MagicMock(name="operation", coverage_mode=mode)

        async def finish(**kwargs: Any) -> None:
            admission.finished.append(kwargs)
            admission.events.append("released")

        class Repository:
            def __init__(self, db: Any) -> None:
                self.db = db

            async def create(self, binding: Any, **_: Any) -> bool:
                admission.created.append(binding)
                return True

        monkeypatch.setattr(runner, "_acquire_onboarding_operation", acquire)
        monkeypatch.setattr(runner, "_finish_onboarding_operation", finish)
        monkeypatch.setattr(runner, "_OnboardingRepository", Repository)


def _activations(monkeypatch: pytest.MonkeyPatch, *, result: bool = True) -> list[Any]:
    activated: list[Any] = []

    async def activate(db: Any, seller_id: str, run_id: str) -> bool:
        activated.append((seller_id, run_id))
        return result

    monkeypatch.setattr(runner, "activate_initial_devoluciones_coverage", activate)
    return activated


def test_initial_coverage_is_the_oldest_window_90_days_before_the_settled_midnight() -> None:
    assert initial_coverage_bounds(now=NOW) == INITIAL
    # Like the tail, wait for the settle margin after midnight.
    early = datetime(2026, 10, 12, 0, 30, tzinfo=UTC)
    assert initial_coverage_bounds(now=early)[0] == INITIAL[0] - timedelta(days=1)


def test_initial_binding_is_automatic_and_changes_only_by_bounds_or_day() -> None:
    binding = initial_coverage_binding(SELLER, *INITIAL, admitted_on=NOW.date())
    assert binding.authorization_id == INITIAL_COVERAGE_AUTHORIZATION
    assert binding.end - binding.start == timedelta(days=10)
    same = initial_coverage_binding(SELLER, *INITIAL, admitted_on=NOW.date())
    tomorrow = initial_coverage_binding(
        SELLER, *INITIAL, admitted_on=(NOW + timedelta(days=1)).date()
    )
    assert same.run_id == binding.run_id != tomorrow.run_id


@pytest.mark.asyncio
async def test_admits_the_initial_window_of_a_seller_the_bootstrap_left_in_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    db = _new_seller_db()

    with capture_logs() as logs:
        run_id = await admit_initial_devoluciones_coverage(
            db, SELLER, eligible=_gate(SELLER), now=lambda: NOW
        )

    expected = initial_coverage_binding(SELLER, *INITIAL, admitted_on=NOW.date())
    assert run_id == expected.run_id
    assert admission.created == [expected]
    # Legacy control: no compatible certificate writer is required yet, and the
    # admission never withdraws readiness.
    assert admission.acquired[0]["invalidate_readiness"] is False
    assert admission.acquired[0].get("require_coverage_compatible", False) is False
    assert admission.acquired[0]["source_fingerprint"] == expected.run_id
    assert [call["succeeded"] for call in admission.finished] == [True]
    assert [log["event"] for log in logs] == ["zelerdata.devoluciones_initial_admitted"]

    # A failed or expired window is not retried until the next UTC day.
    db["sheets_devoluciones_runs"].documents.append(
        {"_id": run_id, "seller_id": SELLER, "state": "failed"}
    )
    assert (
        await admit_initial_devoluciones_coverage(
            db, SELLER, eligible=_gate(SELLER), now=lambda: NOW
        )
        is None
    )
    assert len(admission.created) == 1


@pytest.mark.asyncio
async def test_a_seller_without_any_control_is_admitted_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    run_id = await admit_initial_devoluciones_coverage(
        _Db(), SELLER, eligible=_gate(SELLER), now=lambda: NOW
    )
    assert run_id is not None and len(admission.created) == 1


@pytest.mark.asyncio
async def test_never_admits_a_seller_that_is_not_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    gate = _gate()

    assert (
        await admit_initial_devoluciones_coverage(
            _new_seller_db(), SELLER, eligible=gate, now=lambda: NOW
        )
        is None
    )
    assert gate.checked == [SELLER]
    assert admission.acquired == []


@pytest.mark.asyncio
async def test_a_seller_in_certificate_mode_belongs_to_the_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    gate = _gate(SELLER)
    db = _Db(sheets_devoluciones_operations=[_legacy_control() | {"coverage_mode": "active"}])

    assert await admit_initial_devoluciones_coverage(db, SELLER, eligible=gate) is None
    # The pilot pays one control read per cycle, not an eligibility read.
    assert gate.checked == []
    assert admission.acquired == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("collections", "reason"),
    [
        (
            {"sheets_devoluciones_certificates": [{"seller_id": SELLER}]},
            "certificates_need_operator_activation",
        ),
        (
            {
                "sheets_read_model_freshness": [
                    _stale_marker(revision="r" * 64, proof_fingerprint="f" * 64)
                ],
                "sheets_devoluciones_runs": [
                    {
                        "_id": "r" * 64,
                        "seller_id": SELLER,
                        "authorization_id": "operator-20261001",
                        "state": "completed",
                    }
                ],
            },
            "legacy_proof_needs_operator_migration",
        ),
    ],
)
async def test_operator_coverage_is_left_to_the_operator(
    monkeypatch: pytest.MonkeyPatch, collections: dict[str, Any], reason: str
) -> None:
    admission = _Admission(monkeypatch)
    activated = _activations(monkeypatch)
    db = _Db(sheets_devoluciones_operations=[_legacy_control()], **collections)

    with capture_logs() as logs:
        assert (
            await admit_initial_devoluciones_coverage(
                db, SELLER, eligible=_gate(SELLER), now=lambda: NOW
            )
            is None
        )

    assert admission.acquired == [] and activated == []
    assert logs == [
        {
            "event": "zelerdata.devoluciones_initial_refused",
            "log_level": "info",
            "seller_id": SELLER,
            "reason": reason,
        }
    ]


@pytest.mark.asyncio
async def test_retries_the_activation_of_its_own_finalized_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window finalized (legacy proof) but the activation was refused, for
    example because the lease was busy. Activation is local, so it is retried
    every cycle before acquiring the window again.
    """
    admission = _Admission(monkeypatch)
    finalized = initial_coverage_binding(
        SELLER, *INITIAL, admitted_on=(NOW - timedelta(days=1)).date()
    )
    db = _Db(
        sheets_devoluciones_operations=[_legacy_control()],
        sheets_read_model_freshness=[
            _stale_marker(state="reconciled", revision=finalized.run_id, proof_fingerprint="f")
        ],
        sheets_devoluciones_runs=[
            {
                "_id": finalized.run_id,
                "seller_id": SELLER,
                "authorization_id": INITIAL_COVERAGE_AUTHORIZATION,
                "state": "completed",
            }
        ],
    )

    activated = _activations(monkeypatch, result=True)
    assert (
        await admit_initial_devoluciones_coverage(
            db, SELLER, eligible=_gate(SELLER), now=lambda: NOW
        )
        is None
    )
    assert activated == [(SELLER, finalized.run_id)]
    assert admission.created == []

    # The proof no longer holds: the window is acquired again, once a day.
    activated = _activations(monkeypatch, result=False)
    run_id = await admit_initial_devoluciones_coverage(
        db, SELLER, eligible=_gate(SELLER), now=lambda: NOW
    )
    assert activated == [(SELLER, finalized.run_id)]
    assert run_id == initial_coverage_binding(SELLER, *INITIAL, admitted_on=NOW.date()).run_id


def _initial_run(**overrides: Any) -> dict[str, Any]:
    run = {
        "_id": "i" * 64,
        "seller_id": SELLER,
        "scope": "devoluciones",
        "state": "authorized",
        "authorization_id": INITIAL_COVERAGE_AUTHORIZATION,
        "window_count": 1,
        "next_window_index": 0,
        "expires_at": NOW + timedelta(minutes=17),
        "created_at": NOW,
    }
    run.update(overrides)
    return run


def _one_window(monkeypatch: pytest.MonkeyPatch, run: dict[str, Any], *, finalized: int) -> None:
    from infra.operations import zelerdata_read_model_reconcile as reconcile

    async def advance(**kwargs: Any) -> dict[str, int]:
        run.update(state="active", next_window_index=1)
        return {"advanced": 1, "finalized": 0}

    async def finalize(**kwargs: Any) -> dict[str, int]:
        return {"advanced": 0, "finalized": finalized}

    monkeypatch.setattr(reconcile, "advance_devoluciones_quota_run", advance)
    monkeypatch.setattr(reconcile, "_finalize_devoluciones_quota_run", finalize)


@pytest.mark.asyncio
async def test_an_initial_window_finalizes_then_activates_certificate_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _Admission(monkeypatch)
    run = _initial_run()
    _one_window(monkeypatch, run, finalized=1)
    activated: list[Any] = []

    async def activate(db: Any, seller_id: str, run_id: str) -> bool:
        admission.events.append("activated")
        activated.append((seller_id, run_id))
        return True

    monkeypatch.setattr(runner, "activate_initial_devoluciones_coverage", activate)

    outcome = await runner.advance_ordinary_devoluciones_tail(
        _Db(sheets_devoluciones_runs=[run]), run["_id"], now=lambda: NOW
    )

    assert outcome == {"advanced": 1, "finalized": 1}
    # The window runs before certificate mode exists, with the tail's
    # tolerances, and activation acquires its own lease after this one.
    assert admission.acquired[0].get("require_coverage_compatible") is False
    assert activated == [(SELLER, run["_id"])]
    assert admission.events == ["released", "activated"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "finalized", "mode"),
    [
        (ORDINARY_TAIL_AUTHORIZATION, 1, "active"),
        (INITIAL_COVERAGE_AUTHORIZATION, 0, "legacy"),
        # Another worker activated first: the finalize already certified it.
        (INITIAL_COVERAGE_AUTHORIZATION, 1, "active"),
    ],
)
async def test_only_a_finalized_initial_window_of_a_legacy_seller_activates(
    monkeypatch: pytest.MonkeyPatch, authorization: str, finalized: int, mode: str
) -> None:
    _Admission(monkeypatch, mode=mode)
    activated = _activations(monkeypatch)
    run = _initial_run(authorization_id=authorization)
    _one_window(monkeypatch, run, finalized=finalized)

    await runner.advance_ordinary_devoluciones_tail(
        _Db(sheets_devoluciones_runs=[run]), run["_id"], now=lambda: NOW
    )

    assert activated == []


@pytest.mark.asyncio
async def test_runtime_advance_routes_an_initial_run_to_the_ordinary_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routed: list[str] = []

    async def advance(db: Any, run_id: str, *, now: Any = None) -> dict[str, int]:
        routed.append(run_id)
        return {"advanced": 1, "finalized": 1}

    monkeypatch.setattr(runner, "advance_ordinary_devoluciones_tail", advance)
    db = _Db(sheets_devoluciones_runs=[_initial_run()])

    assert await runner._runtime_advance(db=db, run_id="i" * 64, now=lambda: NOW) == {
        "advanced": 1,
        "finalized": 1,
    }
    assert routed == ["i" * 64]


class _DueRuns:
    """No run is due; records which admissions the runner asks for."""

    def __init__(self, tail: str | None, initial: str | None) -> None:
        self.calls: list[str] = []
        self.advanced: list[str] = []
        self.tail, self.initial = tail, initial

    async def admit_tail(self, db: Any, seller_id: str, *, now: Any = None) -> str | None:
        self.calls.append("tail")
        return self.tail

    async def admit_initial(self, db: Any, seller_id: str, *, now: Any = None) -> str | None:
        self.calls.append("initial")
        return self.initial

    async def advance(self, *, db: Any, run_id: str, now: Any = None) -> dict[str, int]:
        self.advanced.append(run_id)
        return {"advanced": 1, "finalized": 1}


def _no_due_run_db() -> Any:
    db = MagicMock()

    async def find_one(*_: Any, **__: Any) -> None:
        return None

    db.__getitem__.return_value.find_one = find_one
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tail", "initial", "calls", "advanced"),
    [
        (None, "i" * 64, ["tail", "initial"], ["i" * 64]),
        ("t" * 64, "i" * 64, ["tail"], ["t" * 64]),
        (None, None, ["tail", "initial"], []),
    ],
)
async def test_the_initial_window_is_admitted_only_when_no_tail_is_due(
    monkeypatch: pytest.MonkeyPatch,
    tail: str | None,
    initial: str | None,
    calls: list[str],
    advanced: list[str],
) -> None:
    renewed: list[str] = []

    async def renew(db: Any, seller_id: str, **_: Any) -> bool:
        renewed.append(seller_id)
        return False

    monkeypatch.setattr(runner, "renew_devoluciones_marker_if_proven", renew)
    due = _DueRuns(tail, initial)

    result = await advance_due_devoluciones_run(
        _no_due_run_db(),
        SELLER,
        now=lambda: NOW,
        advance=due.advance,
        history_work_enabled=False,
        admit_tail=due.admit_tail,
        admit_initial=due.admit_initial,
        renew=False,
    )

    assert result is bool(advanced)
    assert due.calls == calls and due.advanced == advanced
    # The cycle renewed every seller before this source pass.
    assert renewed == []


@pytest.mark.asyncio
async def test_history_on_link_never_admits_an_initial_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def renew(db: Any, seller_id: str, **_: Any) -> bool:
        return False

    monkeypatch.setattr(runner, "renew_devoluciones_marker_if_proven", renew)
    due = _DueRuns(None, "i" * 64)

    assert (
        await advance_due_devoluciones_run(
            _no_due_run_db(),
            SELLER,
            now=lambda: NOW,
            advance=due.advance,
            history_work_enabled=True,
            admit_initial=due.admit_initial,
        )
        is False
    )
    assert due.calls == []


class _Explorer:
    def __init__(self, *sellers: str) -> None:
        self.sellers = sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        return self.sellers


class _Planner:
    async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
        return False


def _supervisor(
    sellers: tuple[str, ...], advancer: Any, renewed: list[str]
) -> ZelerDataRefreshSupervisor:
    async def renew(seller_id: str) -> bool:
        renewed.append(seller_id)
        return False

    return ZelerDataRefreshSupervisor(
        explorer=_Explorer(*sellers),
        planner=_Planner(),
        devoluciones_runner=renew,
        devoluciones_advancer=advancer,
        interval_seconds=900,
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_one_devoluciones_window_per_cycle_and_sellers_take_turns() -> None:
    """Three sellers catching up at once. Each window can take minutes inside
    the serial cycle, so the whole fleet gets one per cycle, in turns.
    """
    served: list[str] = []
    renewed: list[str] = []

    async def advancer(seller_id: str) -> bool:
        served.append(seller_id)
        return True

    supervisor = _supervisor(("1", "2", "3"), advancer, renewed)
    for _ in range(4):
        await supervisor.run_cycle()

    assert served == ["1", "2", "3", "1"]
    # Every seller's proof is still renewed on every cycle.
    assert renewed == ["1", "2", "3"] * 4


@pytest.mark.asyncio
async def test_a_seller_with_nothing_due_passes_the_turn() -> None:
    offered: list[str] = []

    async def advancer(seller_id: str) -> bool:
        offered.append(seller_id)
        return seller_id != "1"

    supervisor = _supervisor(("1", "2", "3"), advancer, [])
    await supervisor.run_cycle()
    await supervisor.run_cycle()

    # The pilot ("1") has nothing due: the first cycle serves "2" and the
    # second starts after it.
    assert offered == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_a_failing_seller_uses_its_turn_and_blocks_no_one() -> None:
    offered: list[str] = []

    async def advancer(seller_id: str) -> bool:
        offered.append(seller_id)
        if seller_id == "1":
            raise RuntimeError("lease busy")
        return True

    supervisor = _supervisor(("1", "2"), advancer, [])
    with capture_logs() as logs:
        await supervisor.run_cycle()
        await supervisor.run_cycle()
        await supervisor.run_cycle()

    assert offered == ["1", "2", "1"]
    failures = [log for log in logs if log["event"] == "zelerdata.devoluciones_run_failed"]
    assert [(log["seller_id"], log["error_type"]) for log in failures] == [
        ("1", "RuntimeError"),
        ("1", "RuntimeError"),
    ]
    completed = [log for log in logs if log["event"] == "zelerdata.refresh_cycle_completed"]
    assert [log["devoluciones_windows"] for log in completed] == [1, 1, 1]


def test_the_cycle_needs_at_least_one_devoluciones_window() -> None:
    with pytest.raises(ValueError, match="at least one window"):
        ZelerDataRefreshSupervisor(
            explorer=_Explorer(),
            planner=_Planner(),
            devoluciones_windows_per_cycle=0,
        )
