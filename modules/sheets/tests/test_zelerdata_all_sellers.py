"""ZelerData refresh and recovery for every eligible seller (`all` mode)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    RecoveryRequest,
    recovery_sellers,
)
from zeler_sheets.formulas.refresh import (
    MongoSellerExplorer,
    ZelerDataRefreshPlanner,
    ZelerDataRefreshSupervisor,
    refresh_sellers,
)
from zeler_sheets.formulas.seller_scope import (
    EligibleSellerGate,
    eligible_sellers,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
PARSERS = [refresh_sellers, recovery_sellers]


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return self._rows[:length]

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for row in self._rows:
                yield row

        return gen()


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            if set(expected) != {"$in"}:
                raise AssertionError(f"unsupported operator in {expected}")
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


class _Collection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def find(self, query: dict[str, Any], projection: Any = None) -> _Cursor:
        return _Cursor([doc for doc in self.docs if _matches(doc, query)])

    async def create_index(self, *args: Any, **kwargs: Any) -> str:
        return str(kwargs.get("name") or "index")


class _Db:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self._collections = {name: _Collection(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection([]))


def _token(
    sellers: list[str],
    *,
    status: str = "active",
    expires_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "status": status,
        "seller_scopes": [{"seller_id": seller, "nickname": f"n{seller}"} for seller in sellers],
        "expires_at": expires_at,
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    return doc


def _eligibility_db(now: datetime = NOW) -> _Db:
    return _Db(
        meli_accounts=[
            {"seller_id": "1", "status": "active"},
            # Legacy integer IDs and a token refresh in flight stay eligible.
            {"seller_id": 2, "status": "refresh_pending"},
            {"seller_id": "3", "status": "paused"},
            {"seller_id": "4", "status": "revoked"},
            {"seller_id": "5", "status": "invalid_grant"},
            {"seller_id": "6", "status": "error"},
            # Linked, but ZelerData was never enabled for these sellers.
            {"seller_id": "7", "status": "active"},
            {"seller_id": "8", "status": "active"},
            {"seller_id": "9", "status": "active"},
            {"seller_id": "10", "status": "active"},
        ],
        sheets_extension_tokens=[
            _token(["1", "2", "3", "4", "5", "6"]),
            _token(["1"], expires_at=now + timedelta(days=1)),
            _token(["8"], status="revoked"),
            _token(["9"], expires_at=now - timedelta(seconds=1)),
            _token(["10"], deleted_at=now),
        ],
    )


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize("value", ["all", " all ", "ALL"])
def test_all_mode_selects_every_eligible_seller(
    parse: Callable[[str | None], frozenset[str] | None], value: str
) -> None:
    assert parse(value) is None


@pytest.mark.parametrize("parse", PARSERS)
def test_explicit_and_empty_scopes_keep_their_behavior(
    parse: Callable[[str | None], frozenset[str] | None],
) -> None:
    assert parse(None) == frozenset()
    assert parse("  ") == frozenset()
    assert parse(" 82453304, 42 ") == frozenset({"82453304", "42"})
    for value in ("all,82453304", "*", "every"):
        with pytest.raises(ValueError):
            parse(value)


@pytest.mark.asyncio
async def test_eligible_sellers_are_linked_unpaused_and_zelerdata_enabled() -> None:
    assert await eligible_sellers(_eligibility_db(), now=NOW) == ("1", "2")


@pytest.mark.asyncio
async def test_explorer_rereads_eligibility_every_cycle() -> None:
    db = _eligibility_db(datetime.now(UTC))
    explorer = MongoSellerExplorer(db=db, allowed_sellers=None)

    assert await explorer.discover_sellers() == ("1", "2")
    db["meli_accounts"].docs[0]["status"] = "paused"
    assert await explorer.discover_sellers() == ("2",)


@pytest.mark.asyncio
async def test_explicit_allowlist_explorer_is_unchanged() -> None:
    explorer = MongoSellerExplorer(db=_eligibility_db(), allowed_sellers=frozenset({"7", "3"}))

    assert await explorer.discover_sellers() == ("3", "7")


@pytest.mark.asyncio
async def test_seller_gate_caches_eligibility_briefly() -> None:
    db = _eligibility_db(datetime.now(UTC))
    clock = [100.0]
    gate = EligibleSellerGate(db, ttl_seconds=30, monotonic=lambda: clock[0])

    assert await gate("1") is True
    assert await gate("7") is False
    db["meli_accounts"].docs[0]["status"] = "paused"
    assert await gate("1") is True
    clock[0] += 31
    assert await gate("1") is False


class _UntouchedCollection:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"an ineligible seller must not reach storage ({name})")


class _UntouchedDb:
    def __getitem__(self, name: str) -> _UntouchedCollection:
        return _UntouchedCollection()


def _range(seller_id: str) -> RecoveryRequest:
    return RecoveryRequest(seller_id, "orders", NOW - timedelta(hours=1), NOW)


@pytest.mark.asyncio
async def test_queue_gate_rejects_ineligible_seller_before_storage() -> None:
    async def deny(_seller_id: str) -> bool:
        return False

    queue = FormulaRecoveryQueue(_UntouchedDb(), allowed_sellers=None, seller_gate=deny)

    with pytest.raises(ValueError, match="recovery seller is not enabled"):
        await queue.enqueue(_range("7"))


@pytest.mark.asyncio
async def test_queue_gate_admits_eligible_seller() -> None:
    seen: list[str] = []
    request = _range("1")

    async def allow(seller_id: str) -> bool:
        seen.append(seller_id)
        return True

    class _Jobs:
        async def find_one(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"_id": request.key}

    class _JobsDb:
        def __getitem__(self, name: str) -> _Jobs:
            return _Jobs()

    queue = FormulaRecoveryQueue(_JobsDb(), allowed_sellers=None, seller_gate=allow)

    assert await queue.enqueue(request) == request.key
    assert seen == ["1"]


def _enable_refresh(monkeypatch: pytest.MonkeyPatch, sellers: str) -> None:
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", sellers)
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", sellers)
    monkeypatch.delenv("ZELERDATA_DLQ_ARCHIVE_ENABLED", raising=False)


@pytest.mark.asyncio
async def test_refresh_builder_all_mode_discovers_eligible_sellers_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    _enable_refresh(monkeypatch, "all")
    supervisor = await build_zelerdata_refresh_supervisor(db=_eligibility_db(datetime.now(UTC)))

    assert await supervisor._explorer.discover_sellers() == ("1", "2")
    # The 12-month pilot backfill stays closed: `all` must never seed history
    # plans for every linked seller.
    assert supervisor._history_backfill is None
    assert isinstance(supervisor._planner, ZelerDataRefreshPlanner)
    assert supervisor._planner._queue.seller_gate is not None


@pytest.mark.asyncio
async def test_refresh_all_mode_requires_recovery_all_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh only plans: jobs for sellers recovery cannot claim would strand."""
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    _enable_refresh(monkeypatch, "all")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "82453304")

    with pytest.raises(RuntimeError, match="ZELERDATA_FORMULA_RECOVERY_SELLERS=all"):
        await build_zelerdata_refresh_supervisor(db=_eligibility_db())


@pytest.mark.asyncio
async def test_refresh_builder_numeric_allowlist_keeps_pilot_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    _enable_refresh(monkeypatch, "82453304")
    supervisor = await build_zelerdata_refresh_supervisor(db=_eligibility_db())

    assert await supervisor._explorer.discover_sellers() == ("82453304",)
    assert supervisor._history_backfill is not None
    assert isinstance(supervisor._planner, ZelerDataRefreshPlanner)
    assert supervisor._planner._queue.seller_gate is None


@pytest.mark.asyncio
async def test_all_mode_cycle_isolates_failing_and_skips_ineligible_sellers() -> None:
    """A revoked, 429-limited or otherwise failing seller never stops the rest."""
    db = _eligibility_db(datetime.now(UTC))
    db["sheets_extension_tokens"].docs.append(_token(["7"]))
    planned: list[str] = []
    markers: list[str] = []

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            if seller_id == "1":
                raise httpx.HTTPStatusError(
                    "rate limited",
                    request=httpx.Request("GET", "http://gateway/orders"),
                    response=httpx.Response(429),
                )
            planned.append(seller_id)
            return True

    async def publish(seller_id: str) -> tuple[str, ...]:
        if seller_id == "2":
            raise RuntimeError("account revoked mid-cycle")
        markers.append(seller_id)
        return ()

    supervisor = ZelerDataRefreshSupervisor(
        explorer=MongoSellerExplorer(db=db, allowed_sellers=None),
        planner=Planner(),
        observed_marker_publisher=publish,
        interval_seconds=900,
        now=lambda: NOW,
    )

    assert await supervisor.run_cycle() is True
    assert supervisor.health_status == "ok"
    assert sorted(set(planned)) == ["2", "7"]
    assert markers == ["1", "7"]


@pytest.mark.asyncio
async def test_recovery_worker_isolates_rate_limited_and_rejected_sellers() -> None:
    from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker

    jobs = [
        {"_id": "a", "seller_id": "1", "read_model": "orders", "attempts": 1},
        {"_id": "b", "seller_id": "3", "read_model": "orders", "attempts": 1},
        {"_id": "c", "seller_id": "2", "read_model": "orders", "attempts": 1},
    ]
    finished: list[tuple[str, bool, bool, str]] = []

    class Queue:
        async def claim(self, **kwargs: Any) -> dict[str, Any] | None:
            return jobs.pop(0) if jobs else None

        async def finish(
            self,
            job: dict[str, Any],
            *,
            succeeded: bool,
            retryable: bool = False,
            failure_reason: str = "recovery_failed",
        ) -> bool:
            finished.append((job["seller_id"], succeeded, retryable, failure_reason))
            return True

    worker = FormulaRecoveryWorker(db=object(), gateway=object(), queue=Queue())  # type: ignore[arg-type]
    statuses = {"1": 429, "3": 423}

    async def orders(job: dict[str, Any]) -> None:
        status = statuses.get(job["seller_id"])
        if status is not None:
            raise httpx.HTTPStatusError(
                "gateway",
                request=httpx.Request("GET", "http://gateway/orders/search"),
                response=httpx.Response(status),
            )
        finished.append((job["seller_id"], True, False, ""))

    worker._orders = orders  # type: ignore[method-assign]

    assert [await worker.process_one() for _ in range(4)] == [True, True, True, False]
    assert finished == [
        ("1", False, True, "source_temporarily_unavailable"),
        ("3", False, False, "source_rejected"),
        ("2", True, False, ""),
    ]


def _capture_recovery_queues(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    class _Queue:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.append(kwargs)

        async def ensure_indexes(self) -> None:
            return None

    class _Worker:
        def __init__(self, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr("zeler_sheets.consumer.FormulaRecoveryQueue", _Queue)
    monkeypatch.setattr("zeler_sheets.consumer.FormulaRecoveryWorker", _Worker)
    monkeypatch.setattr("zeler_sheets.consumer.make_meli_gateway_client", lambda **kwargs: object())
    return captured


@pytest.mark.asyncio
async def test_recovery_builder_all_mode_gates_every_seller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_formula_recovery_poller

    for flag in (
        "ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED",
    ):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "all")
    captured = _capture_recovery_queues(monkeypatch)

    await build_formula_recovery_poller(db=_Db(), kms_client=object(), detail_gateway=object())

    assert captured and all(kwargs["allowed_sellers"] is None for kwargs in captured)
    assert all(isinstance(kwargs["seller_gate"], EligibleSellerGate) for kwargs in captured)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag",
    [
        "ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED",
        "ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED",
    ],
)
async def test_pilot_history_protocols_refuse_all_mode(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    from zeler_sheets.consumer import build_formula_recovery_poller

    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "all")
    monkeypatch.setenv(flag, "true")
    _capture_recovery_queues(monkeypatch)

    with pytest.raises(RuntimeError, match="explicit numeric ZELERDATA_FORMULA_RECOVERY_SELLERS"):
        await build_formula_recovery_poller(db=_Db(), kms_client=object(), detail_gateway=object())


@pytest.mark.parametrize(("value", "gated"), [("all", True), ("82453304", False)])
def test_api_factory_accepts_all_mode(
    monkeypatch: pytest.MonkeyPatch, value: str, gated: bool
) -> None:
    from google.cloud import kms
    from motor import motor_asyncio

    import zeler_sheets.app as app_module

    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27028")
    monkeypatch.setenv("MONGO_DB", "unit_test")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", value)
    monkeypatch.setattr(motor_asyncio, "AsyncIOMotorClient", lambda uri: {"unit_test": _Db()})
    monkeypatch.setattr(kms, "KeyManagementServiceClient", lambda: object())
    monkeypatch.setattr(app_module, "get_settings", lambda: object())
    monkeypatch.setattr(app_module, "build_app", lambda **kwargs: kwargs)

    wiring: dict[str, Any] = app_module.make_app()  # type: ignore[assignment]

    expected = None if gated else frozenset({"82453304"})
    assert wiring["formula_recovery_sellers"] == expected
    gate = wiring["formula_recovery_seller_gate"]
    assert isinstance(gate, EligibleSellerGate) if gated else gate is None


def test_api_queue_uses_the_seller_gate() -> None:
    from zeler_sheets.app import build_app

    async def gate(_seller_id: str) -> bool:
        return True

    app = build_app(
        mongo_db=_Db(),
        formula_recovery_enabled=True,
        formula_recovery_sellers=None,
        formula_recovery_seller_gate=gate,
    )

    assert app.state.formula_recovery_queue.allowed_sellers is None
    assert app.state.formula_recovery_queue.seller_gate is gate


@pytest.mark.asyncio
async def test_dlq_archiver_all_mode_reads_eligible_sellers_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import infra.operations.sheets_dlq_archive_runtime as runtime

    from zeler_sheets.dlq_auto_archive import build_dlq_auto_archiver

    requested: list[tuple[str, ...]] = []

    async def coverages(db: Any, seller_ids: Any) -> dict[str, Any]:
        requested.append(tuple(seller_ids))
        return {}

    class Report:
        def as_dict(self) -> dict[str, int]:
            return {}

    async def run_archive(**kwargs: Any) -> Report:
        return Report()

    monkeypatch.setenv("RABBITMQ_URL", "amqp://unit-test")
    monkeypatch.setattr(runtime, "load_reconciled_coverages", coverages)
    monkeypatch.setattr(runtime, "run_archive", run_archive)
    monkeypatch.setattr(runtime, "AioPikaArchiveBroker", lambda url: object())
    monkeypatch.setattr(runtime, "mongo_archive_store", lambda db: object())
    db = _eligibility_db(datetime.now(UTC))

    archive = build_dlq_auto_archiver(db, sellers=None)
    await archive()
    db["meli_accounts"].docs[0]["status"] = "paused"
    await archive()

    assert requested == [("1", "2"), ("2",)]


@pytest.mark.asyncio
async def test_refresh_cycle_reports_seller_count_and_duration() -> None:
    """Shared capacity is visible: the cycle must stay well inside its interval."""
    import structlog

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("1", "2", "7")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            clock[0] += 2.5
            return True

    clock = [10.0]
    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        interval_seconds=900,
        monotonic=lambda: clock[0],
        now=lambda: datetime(2026, 10, 7, 1, 0, tzinfo=UTC),
    )

    with structlog.testing.capture_logs() as entries:
        await supervisor.run_cycle()

    completed = [e for e in entries if e["event"] == "zelerdata.refresh_cycle_completed"]
    assert completed == [
        {
            "event": "zelerdata.refresh_cycle_completed",
            "log_level": "info",
            "sellers": 3,
            "warm_deferred": 0,
            "elapsed_seconds": 7.5,
        }
    ]


@pytest.mark.asyncio
async def test_eligibility_queries_match_real_mongo_semantics() -> None:
    """Missing `deleted_at`, integer IDs and `$in` must behave as in the fake."""
    from uuid import uuid4

    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import ServerSelectionTimeoutError

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_all_sellers_test_{uuid4().hex}"]
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        source = _eligibility_db()
        await db.meli_accounts.insert_many([dict(doc) for doc in source["meli_accounts"].docs])
        await db.sheets_extension_tokens.insert_many(
            [dict(doc) for doc in source["sheets_extension_tokens"].docs]
        )
        assert await eligible_sellers(db, now=NOW) == ("1", "2")
        await client.drop_database(db.name)
    finally:
        client.close()


class _Sellers:
    def __init__(self, sellers: tuple[str, ...]) -> None:
        self._sellers = sellers

    async def discover_sellers(self) -> tuple[str, ...]:
        return self._sellers


class _NoPlan:
    async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
        return False


def _warm_supervisor(
    sellers: tuple[str, ...], clock: list[float], warmed: list[str], markers: list[str]
) -> ZelerDataRefreshSupervisor:
    async def warm(seller_id: str) -> int:
        warmed.append(seller_id)
        clock[0] += 200  # a pilot-sized seller costs minutes of serial CPU
        return 1

    async def publish(seller_id: str) -> tuple[str, ...]:
        markers.append(seller_id)
        return ()

    return ZelerDataRefreshSupervisor(
        explorer=_Sellers(sellers),
        planner=_NoPlan(),
        observed_marker_publisher=publish,
        precalculated_warmer=warm,
        interval_seconds=900,
        monotonic=lambda: clock[0],
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_precalculated_warm_budget_caps_the_cycle_and_rotates_fairly() -> None:
    """Warming is serial per seller; it must not push marker renewal past its lease.

    A cycle that lasts D renews each marker every D + interval, and markers last
    two intervals, so D has to stay under one interval whatever N is.
    """
    clock = [0.0]
    warmed: list[str] = []
    markers: list[str] = []
    supervisor = _warm_supervisor(("1", "2", "3", "4", "5"), clock, warmed, markers)

    await supervisor.run_cycle()

    # Budget is half an interval (450 s): the check runs before each seller, so
    # three 200 s warms fit and the rest wait. Cheap steps still cover everyone.
    assert warmed == ["1", "2", "3"]
    assert markers == ["1", "2", "3", "4", "5"]
    assert clock[0] == 600

    warmed.clear()
    await supervisor.run_cycle()

    # The next cycle resumes where the last one stopped, so nobody starves.
    assert warmed == ["4", "5", "1"]


@pytest.mark.asyncio
async def test_precalculated_warm_budget_does_not_touch_a_small_fleet() -> None:
    clock = [0.0]
    warmed: list[str] = []
    supervisor = _warm_supervisor(("1", "2"), clock, warmed, [])

    await supervisor.run_cycle()
    await supervisor.run_cycle()

    assert warmed == ["1", "2", "1", "2"]
