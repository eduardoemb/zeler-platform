from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.refresh import (
    IMPLEMENTED_REFRESH_MODELS,
    ZelerDataRefreshPlanner,
    ZelerDataRefreshSupervisor,
    refresh_sellers,
)

NOW = datetime(2026, 9, 10, 22, 0, tzinfo=UTC)


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    async def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items() if not isinstance(v, dict)):
                return doc
        return None

    def find(self, query: dict[str, Any], projection: Any = None) -> Any:
        docs = self.docs
        for key, value in query.items():
            if isinstance(value, dict) and "$gte" in value:
                docs = [d for d in docs if d.get(key) is not None and d[key] >= value["$gte"]]
            elif not isinstance(value, dict):
                docs = [d for d in docs if d.get(key) == value]

        class Cursor:
            def __init__(self, rows: list[dict[str, Any]]) -> None:
                self.rows = rows

            async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
                return self.rows[:length]

            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    for row in self.rows:
                        yield row

                return gen()

        return Cursor(docs)

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        self.updated.append({"args": args, "kwargs": kwargs})
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    async def enqueue(self, request: Any) -> str:
        self.enqueued.append(request)
        return request.key


class FakeDb:
    def __init__(self, **collections: Any) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> Any:
        return self._collections.setdefault(name, FakeCollection())


def test_refresh_sellers_closed_by_default() -> None:
    assert refresh_sellers(None) == frozenset()
    assert refresh_sellers("") == frozenset()
    assert refresh_sellers("82453304") == frozenset({"82453304"})


def test_refresh_sellers_rejects_non_numeric() -> None:
    with pytest.raises(ValueError):
        refresh_sellers("pilot")


def test_implemented_refresh_models_are_recoverable_models() -> None:
    from zeler_sheets.formulas.recovery import RECOVERABLE_MODELS

    assert IMPLEMENTED_REFRESH_MODELS <= RECOVERABLE_MODELS


@pytest.mark.asyncio
async def test_planner_enqueues_fast_models_with_recent_window() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders", "questions"}),
        now=lambda: NOW,
    )
    await planner.plan(seller_id="82453304", mode="fast")

    models = sorted(request.read_model for request in queue.enqueued)
    assert models == ["orders", "questions"]
    orders = next(r for r in queue.enqueued if r.read_model == "orders")
    assert orders.date_to == NOW
    assert orders.date_to - orders.date_from == timedelta(hours=1)


@pytest.mark.asyncio
async def test_planner_daily_sweep_covers_every_enabled_model() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders", "questions"}),
        now=lambda: NOW,
    )
    await planner.plan(seller_id="82453304", mode="daily")

    models = sorted(request.read_model for request in queue.enqueued)
    assert models == ["orders", "questions"]
    orders = next(r for r in queue.enqueued if r.read_model == "orders")
    assert orders.date_to - orders.date_from == timedelta(days=7)


@pytest.mark.asyncio
async def test_planner_full_review_uses_the_widest_supported_window() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders"}),
        now=lambda: NOW,
    )
    await planner.plan(seller_id="82453304", mode="full")

    orders = queue.enqueued[0]
    assert orders.date_to - orders.date_from == timedelta(days=90)


@pytest.mark.asyncio
async def test_planner_rejects_unknown_mode() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders"}),
        now=lambda: NOW,
    )
    with pytest.raises(ValueError):
        await planner.plan(seller_id="82453304", mode="hourly")


@pytest.mark.asyncio
async def test_planner_deduplicates_within_one_cycle() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders"}),
        now=lambda: NOW,
    )
    await planner.plan(seller_id="82453304", mode="fast")
    await planner.plan(seller_id="82453304", mode="fast")
    assert len(queue.enqueued) == 2


@pytest.mark.asyncio
async def test_planner_skips_when_seller_not_enabled() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders"}),
        allowed_sellers=frozenset({"999"}),
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is False
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_planner_reports_success_when_any_request_admitted() -> None:
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders"}),
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is True


@pytest.mark.asyncio
async def test_planner_survives_one_model_failure() -> None:
    class FlakyQueue(FakeQueue):
        async def enqueue(self, request: Any) -> str:
            if request.read_model == "orders":
                raise ValueError("recovery seller capacity reached")
            return await super().enqueue(request)

    queue = FlakyQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"orders", "questions"}),
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is True
    assert [r.read_model for r in queue.enqueued] == ["questions"]


class FakeIdentitySource:
    def __init__(
        self,
        *,
        catalog_product_ids: tuple[str, ...] = (),
        buybox_item_ids: tuple[str, ...] = (),
    ) -> None:
        self._catalog_product_ids = catalog_product_ids
        self._buybox_item_ids = buybox_item_ids
        self.calls: list[str] = []

    async def catalog_product_ids(self, seller_id: str) -> tuple[str, ...]:
        self.calls.append("catalog_product_ids")
        return self._catalog_product_ids

    async def buybox_item_ids(self, seller_id: str) -> tuple[str, ...]:
        self.calls.append("buybox_item_ids")
        return self._buybox_item_ids


@pytest.mark.asyncio
async def test_planner_emits_inventory_sweep_for_item_formula_rows() -> None:
    """Item rows need the whole-seller inventory sweep, not a rejected range."""
    from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest

    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"item_formula_rows"}),
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is True

    assert len(queue.enqueued) == 1
    request = queue.enqueued[0]
    assert isinstance(request, ItemInventoryRecoveryRequest)
    assert request.seller_id == "82453304"
    assert request.read_model == "item_formula_rows"


@pytest.mark.asyncio
async def test_planner_emits_catalog_intents_from_acquired_identities() -> None:
    """Catalog models demand explicit IDs, so the planner must resolve them."""
    from zeler_sheets.formulas.recovery import CatalogRecoveryRequest

    identities = FakeIdentitySource(
        catalog_product_ids=("MLM24127708", "MLM27325873"),
        buybox_item_ids=("MLM2049378457",),
    )
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"catalog_product_snapshots", "catalog_buybox_snapshots"}),
        identity_source=identities,
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is True

    by_model = {request.read_model: request for request in queue.enqueued}
    assert sorted(by_model) == ["catalog_buybox_snapshots", "catalog_product_snapshots"]
    assert all(isinstance(request, CatalogRecoveryRequest) for request in queue.enqueued)
    assert by_model["catalog_product_snapshots"].ids == ("MLM24127708", "MLM27325873")
    assert by_model["catalog_buybox_snapshots"].ids == ("MLM2049378457",)
    assert sorted(identities.calls) == ["buybox_item_ids", "catalog_product_ids"]


@pytest.mark.asyncio
async def test_planner_skips_catalog_models_without_known_identities() -> None:
    """No acquired identity means no plan; an empty intent is not admissible."""
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"catalog_product_snapshots"}),
        identity_source=FakeIdentitySource(),
        now=lambda: NOW,
    )
    assert await planner.plan(seller_id="82453304", mode="fast") is False
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_planner_requires_identity_source_for_catalog_models() -> None:
    """Catalog models must fail fast instead of silently planning nothing."""
    with pytest.raises(ValueError, match="identity source"):
        ZelerDataRefreshPlanner(
            queue=FakeQueue(),
            enabled_models=frozenset({"catalog_product_snapshots"}),
            now=lambda: NOW,
        )


@pytest.mark.asyncio
async def test_supervisor_starts_and_stops_cleanly() -> None:
    calls: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            calls.append("discover")
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            calls.append(f"plan:{seller_id}:{mode}")
            return True

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        interval_seconds=3600,
    )
    await supervisor.start()
    await asyncio.sleep(0)
    assert await supervisor.wait_for_cycle() is True
    await supervisor.stop()
    assert "discover" in calls
    assert "plan:82453304:fast" in calls
    assert supervisor.health_status == "stopped"


@pytest.mark.asyncio
async def test_supervisor_runs_daily_sweep_once_per_day() -> None:
    seen: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            seen.append(mode)
            return True

    clock = [datetime(2026, 9, 10, 3, 0, tzinfo=UTC)]
    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        interval_seconds=900,
        now=lambda: clock[0],
    )
    await supervisor.run_cycle()
    assert seen == ["fast", "daily"]
    clock[0] = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)
    await supervisor.run_cycle()
    assert seen == ["fast", "daily", "fast"]
    clock[0] = datetime(2026, 9, 11, 3, 0, tzinfo=UTC)
    await supervisor.run_cycle()
    assert seen == ["fast", "daily", "fast", "fast", "daily"]


@pytest.mark.asyncio
async def test_supervisor_runs_full_review_once_per_week() -> None:
    seen: list[str] = []
    weekend_views: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            seen.append(mode)
            if mode == "full":
                weekend_views.append(mode)
            return True

    clock = [datetime(2026, 9, 7, 3, 0, tzinfo=UTC)]  # Monday
    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        interval_seconds=900,
        now=lambda: clock[0],
    )
    await supervisor.run_cycle()
    assert seen == ["fast", "daily", "full"]
    clock[0] = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)
    await supervisor.run_cycle()
    assert seen == ["fast", "daily", "full", "fast", "daily"]
    clock[0] = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
    await supervisor.run_cycle()
    assert seen[-3:] == ["fast", "daily", "full"]


@pytest.mark.asyncio
async def test_supervisor_survives_seller_failure() -> None:
    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            if seller_id == "82453304":
                raise RuntimeError("boom")
            return True

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        interval_seconds=900,
        now=lambda: NOW,
    )
    assert await supervisor.run_cycle() is True
    assert supervisor.health_status == "ok"


class _IndexedDb:
    def __init__(self) -> None:
        self.indexes: list[Any] = []

    def __getitem__(self, name: str) -> Any:
        return _IndexedCollection(self.indexes, name)


class _IndexedCollection:
    def __init__(self, registry: list[Any], name: str) -> None:
        self._registry = registry
        self._name = name

    async def create_index(self, keys: Any, name: str | None = None) -> str:
        self._registry.append((self._name, name))
        return name or "index"

    def find(self, *args: Any, **kwargs: Any) -> Any:
        class Cursor:
            async def to_list(self, length: int | None = None) -> list[Any]:
                return []

            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    return
                    yield  # pragma: no cover - empty async generator

                return gen()

        return Cursor()


@pytest.mark.asyncio
async def test_refresh_builder_requires_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.delenv("ZELERDATA_REFRESH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="explicitly enabled"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


@pytest.mark.asyncio
async def test_refresh_builder_requires_seller_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_REFRESH_SELLERS", raising=False)
    with pytest.raises(RuntimeError, match="REFRESH_SELLERS is required"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


@pytest.mark.asyncio
async def test_refresh_builder_requires_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.delenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="requires formula recovery"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["abc", "0", "-5"])
async def test_refresh_builder_rejects_bad_interval(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_INTERVAL_SECONDS", value)
    with pytest.raises(RuntimeError, match="INTERVAL_SECONDS"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


@pytest.mark.asyncio
async def test_refresh_builder_honors_enabled_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_INTERVAL_SECONDS", "900")

    db = _IndexedDb()
    supervisor = await build_zelerdata_refresh_supervisor(db=db)
    assert isinstance(supervisor, ZelerDataRefreshSupervisor)
    assert supervisor.health_status == "starting"
    assert any(name == "recovery_claim" for _collection, name in db.indexes)


@pytest.mark.asyncio
async def test_refresh_builder_is_off_by_default_even_with_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kill switch is independent: turning recovery off must not start refresh."""
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.delenv("ZELERDATA_REFRESH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="explicitly enabled"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


def test_marker_validity_doubles_the_refresh_interval() -> None:
    """A single missed refresh cycle must not expire the freshness marker."""
    from zeler_sheets.formulas.refresh import (
        DEFAULT_INTERVAL_SECONDS,
        MARKER_VALIDITY,
    )

    assert timedelta(minutes=30) == MARKER_VALIDITY
    assert 2 * timedelta(seconds=DEFAULT_INTERVAL_SECONDS) <= MARKER_VALIDITY


def test_reconciled_marker_covers_two_refresh_cycles() -> None:
    """The published marker must outlive one missed refresh cycle."""
    from zeler_sheets.formulas.refresh import (
        DEFAULT_INTERVAL_SECONDS,
        MARKER_VALIDITY,
        reconciled_marker,
    )

    marker = reconciled_marker(
        seller_id="82453304",
        read_model="orders",
        start=NOW - timedelta(hours=1),
        end=NOW,
        now=NOW,
    )

    assert marker["valid_until"] == NOW + MARKER_VALIDITY
    assert marker["valid_until"] >= NOW + 2 * timedelta(seconds=DEFAULT_INTERVAL_SECONDS)
    assert marker["valid_until"] > marker["reconciled_until"]
    assert marker["fresh_until"] == marker["reconciled_until"] == NOW
    assert marker["state"] == "reconciled"
    assert marker["_id"] == "82453304:orders"
