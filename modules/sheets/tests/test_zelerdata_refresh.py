from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.refresh import (
    IMPLEMENTED_REFRESH_MODELS,
    MARKER_RENEWED_REFRESH_MODELS,
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
        return str(request.key)


class FakeDb:
    def __init__(self, **collections: Any) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> Any:
        return self._collections.setdefault(name, FakeCollection())


class FakeIdentityCollection:
    """Minimal Mongo surface used by the identity source."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []

    async def distinct(self, field: str, query: dict[str, Any]) -> list[Any]:
        selected = [
            doc
            for doc in self.documents
            if all(doc.get(key) == value for key, value in query.items())
        ]
        values = (
            [
                variation.get("catalog_product_id")
                for doc in selected
                for variation in (doc.get("variations") or [])
                if isinstance(variation, dict)
            ]
            if field == "variations.catalog_product_id"
            else [doc.get(field) for doc in selected]
        )
        return [value for value in values if value is not None]

    def find(self, query: dict[str, Any], projection: Any = None) -> Any:
        rows = [
            doc
            for doc in self.documents
            if all(
                doc.get(key) == value for key, value in query.items() if not isinstance(value, dict)
            )
        ]
        for key, value in query.items():
            if isinstance(value, dict) and "$gte" in value:
                rows = [
                    row for row in rows if row.get(key) is not None and row[key] >= value["$gte"]
                ]
            elif isinstance(value, dict) and value.get("$type") == "string":
                rows = [row for row in rows if isinstance(row.get(key), str)]

        class Cursor:
            def __init__(self, items: list[dict[str, Any]]) -> None:
                self._items = list(items)

            def sort(self, spec: Any) -> Cursor:
                for key, direction in reversed(list(spec)):
                    self._items.sort(
                        key=lambda row: str(row.get(key)),
                        reverse=direction < 0,
                    )
                return self

            def limit(self, count: int) -> Cursor:
                self._items = self._items[:count]
                return self

            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    for row in self._items:
                        yield row

                return gen()

        return Cursor(rows)


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
        shipment_ids: tuple[str, ...] = (),
    ) -> None:
        self._catalog_product_ids = catalog_product_ids
        self._buybox_item_ids = buybox_item_ids
        self._shipment_ids = shipment_ids
        self.calls: list[str] = []

    async def catalog_product_ids(self, seller_id: str) -> tuple[str, ...]:
        self.calls.append("catalog_product_ids")
        return self._catalog_product_ids

    async def buybox_item_ids(self, seller_id: str) -> tuple[str, ...]:
        self.calls.append("buybox_item_ids")
        return self._buybox_item_ids

    async def shipment_ids(self, seller_id: str) -> tuple[str, ...]:
        self.calls.append("shipment_ids")
        return self._shipment_ids


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
async def test_planner_chunks_shipment_intents_within_the_admitted_identity_cap() -> None:
    """A seller with more shipments than one intent admits must still be covered."""
    from zeler_sheets.formulas.recovery import ShipmentIdsRecoveryRequest

    identities = FakeIdentitySource(shipment_ids=tuple(str(1000 + i) for i in range(250)))
    queue = FakeQueue()
    planner = ZelerDataRefreshPlanner(
        queue=queue,
        enabled_models=frozenset({"shipments"}),
        identity_source=identities,
        now=lambda: NOW,
    )

    assert await planner.plan(seller_id="82453304", mode="fast") is True

    assert [type(request) for request in queue.enqueued] == [ShipmentIdsRecoveryRequest] * 3
    covered = sorted(identity for request in queue.enqueued for identity in request.shipment_ids)
    assert covered == [str(1000 + i) for i in range(250)]
    assert all(len(request.shipment_ids) <= 100 for request in queue.enqueued)


@pytest.mark.asyncio
async def test_identity_source_reads_every_acquired_identity() -> None:
    """Fixed truncation would refresh the same first N identities forever."""
    from zeler_sheets.formulas.refresh import MongoRefreshIdentitySource

    items = [
        {
            "_id": f"MLM{1000 + i}",
            "seller_id": "82453304",
            "catalog_product_id": f"MLM{2000 + i}",
            "catalog_listing": True,
            "last_meli_sync_at": NOW - timedelta(minutes=5),
        }
        for i in range(350)
    ]
    shipments = [
        {
            "_id": str(5000 + i),
            "seller_id": "82453304",
            "date_created": NOW - timedelta(days=1),
        }
        for i in range(450)
    ]
    source = MongoRefreshIdentitySource(
        db={
            "items": FakeIdentityCollection(items),
            "shipments": FakeIdentityCollection(shipments),
        },
        now=lambda: NOW,
    )

    assert len(await source.catalog_product_ids("82453304")) == 350
    assert len(await source.buybox_item_ids("82453304")) == 350
    assert len(await source.shipment_ids("82453304")) == 450


@pytest.mark.asyncio
async def test_identity_source_drops_malformed_and_foreign_identities() -> None:
    from zeler_sheets.formulas.refresh import MongoRefreshIdentitySource

    source = MongoRefreshIdentitySource(
        db={
            "items": FakeIdentityCollection(
                [
                    {"_id": "MLM1", "seller_id": "82453304", "catalog_product_id": "not-a-product"},
                    {"_id": "MLM2", "seller_id": "999", "catalog_product_id": "MLM200"},
                    {
                        "_id": "MLM3",
                        "seller_id": "82453304",
                        "catalog_product_id": "MLM300",
                        "catalog_listing": True,
                        "last_meli_sync_at": NOW - timedelta(minutes=5),
                    },
                    {"_id": "MLM5", "seller_id": "82453304", "catalog_listing": True},
                    {"_id": "MLM4", "seller_id": "82453304", "catalog_listing": "yes"},
                ]
            ),
            "shipments": FakeIdentityCollection(
                [
                    {
                        "_id": "123",
                        "seller_id": "82453304",
                        "date_created": NOW - timedelta(days=1),
                    },
                    {
                        "_id": "abc",
                        "seller_id": "82453304",
                        "date_created": NOW - timedelta(days=1),
                    },
                    {
                        "_id": "456",
                        "seller_id": "82453304",
                        "date_created": NOW - timedelta(days=90),
                    },
                ]
            ),
        },
        now=lambda: NOW,
    )

    assert await source.catalog_product_ids("82453304") == ("MLM300",)
    assert await source.buybox_item_ids("82453304") == ("MLM3",)
    assert await source.shipment_ids("82453304") == ("123",)


@pytest.mark.asyncio
async def test_catalog_refresh_includes_variation_only_product_identities() -> None:
    from zeler_sheets.formulas.refresh import MongoRefreshIdentitySource

    source = MongoRefreshIdentitySource(
        db={
            "items": FakeIdentityCollection(
                [
                    {
                        "_id": "MLM1",
                        "seller_id": "82453304",
                        "catalog_product_id": "MLM300",
                        "variations": [
                            {"catalog_product_id": "MLM301"},
                            {"catalog_product_id": "MLM302"},
                            {"catalog_product_id": "bad-product"},
                        ],
                    },
                    {
                        "_id": "MLM2",
                        "seller_id": "999",
                        "variations": [{"catalog_product_id": "MLM999"}],
                    },
                ]
            )
        },
        now=lambda: NOW,
    )

    assert await source.catalog_product_ids("82453304") == ("MLM300", "MLM301", "MLM302")


@pytest.mark.asyncio
async def test_identity_source_only_plans_buybox_items_the_worker_can_acquire() -> None:
    """Buybox acquisition rejects publications without a fresh item sync."""
    from zeler_sheets.formulas.refresh import MongoRefreshIdentitySource

    source = MongoRefreshIdentitySource(
        db={
            "items": FakeIdentityCollection(
                [
                    {
                        "_id": "MLM1",
                        "seller_id": "82453304",
                        "catalog_listing": True,
                        "catalog_product_id": "MLM900",
                        "last_meli_sync_at": NOW - timedelta(minutes=5),
                    },
                    {
                        "_id": "MLM2",
                        "seller_id": "82453304",
                        "catalog_listing": True,
                        "catalog_product_id": "MLM901",
                        "last_meli_sync_at": NOW - timedelta(days=30),
                    },
                    {
                        "_id": "MLM3",
                        "seller_id": "82453304",
                        "catalog_listing": True,
                        "catalog_product_id": "MLM902",
                    },
                ]
            ),
            "shipments": FakeIdentityCollection(),
        },
        now=lambda: NOW,
    )

    assert await source.buybox_item_ids("82453304") == ("MLM1",)


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
async def test_supervisor_renews_observed_markers_once_per_seller_and_cycle() -> None:
    published: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return True

    async def publisher(seller_id: str) -> tuple[str, ...]:
        published.append(seller_id)
        return ("shipments",)

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        observed_marker_publisher=publisher,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert published == ["82453304", "999"]


@pytest.mark.asyncio
async def test_supervisor_advances_authorized_devoluciones_run_once_per_seller() -> None:
    """DEVOLUCIONES is absorbed into the refresh loop (Q2-b/Q7-a)."""
    advanced: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return False

    async def devoluciones_runner(seller_id: str) -> bool:
        advanced.append(seller_id)
        return seller_id == "82453304"

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        devoluciones_runner=devoluciones_runner,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert advanced == ["82453304", "999"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_a_failing_devoluciones_runner_does_not_stop_the_refresh_cycle() -> None:
    planned: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            planned.append(mode)
            return True

    async def devoluciones_runner(seller_id: str) -> bool:
        raise RuntimeError("devoluciones maintenance unavailable")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        devoluciones_runner=devoluciones_runner,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert planned == ["fast", "daily"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_a_failing_observed_marker_does_not_stop_the_refresh_cycle() -> None:
    planned: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            planned.append(mode)
            return True

    async def publisher(seller_id: str) -> tuple[str, ...]:
        raise RuntimeError("marker storage unavailable")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        observed_marker_publisher=publisher,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert planned == ["fast", "daily"]
    assert supervisor.health_status == "ok"


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


class _RowsCollection:
    """Minimal read-only collection returning fixed rows for group-by queries."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def find(self, query: dict[str, Any], projection: Any = None) -> Any:
        rows = [row for row in self._rows if row.get("seller_id") == query.get("seller_id")]

        class Cursor:
            async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
                return rows

            def __aiter__(self) -> Any:
                async def gen() -> Any:
                    for row in rows:
                        yield row

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


def test_merge_interval_proofs_unions_contiguous_history() -> None:
    """Overlapping or touching acquisitions merge; a real gap is preserved."""
    from zeler_sheets.formulas.refresh import merge_interval_proofs

    def proof(start_days: int, end_days: int, validity_days: int = 1) -> dict[str, object]:
        return {
            "state": "reconciled",
            "date_from": NOW - timedelta(days=start_days),
            "reconciled_until": NOW - timedelta(days=end_days),
            "valid_until": NOW + timedelta(days=validity_days),
        }

    merged = merge_interval_proofs([proof(60, 40), proof(40, 20), proof(20, 10)])
    assert len(merged) == 1
    assert merged[0]["date_from"] == NOW - timedelta(days=60)
    assert merged[0]["reconciled_until"] == NOW - timedelta(days=10)

    gapped = merge_interval_proofs([proof(60, 40), proof(30, 10)])
    assert len(gapped) == 2

    # Malformed or non-reconciled proofs are dropped, never guessed into
    # coverage; a usable proof alongside them is still retained.
    dropped = merge_interval_proofs([proof(60, 40), {"state": "stale"}])
    assert len(dropped) == 1 and dropped[0]["date_from"] == NOW - timedelta(days=60)
    assert merge_interval_proofs([{"state": "reconciled", "date_from": NOW}]) == []


def test_merge_interval_proofs_bounds_the_marker_document() -> None:
    """Durable proofs are compacted instead of growing without bound."""
    from zeler_sheets.formulas.refresh import MAX_RETAINED_INTERVALS, merge_interval_proofs

    disjoint = [
        {
            "state": "reconciled",
            "date_from": NOW - timedelta(days=3 * index + 3),
            "reconciled_until": NOW - timedelta(days=3 * index + 2),
            "valid_until": NOW + timedelta(minutes=30),
        }
        for index in range(MAX_RETAINED_INTERVALS + 10)
    ]
    merged = merge_interval_proofs(disjoint)
    assert len(merged) == MAX_RETAINED_INTERVALS
    # The newest proofs survive; older history fails closed when it is dropped.
    assert merged[-1]["reconciled_until"] > merged[0]["reconciled_until"]


@pytest.mark.asyncio
async def test_supervisor_reports_freshness_alarms_once_per_seller_and_cycle() -> None:
    """Q21-a: the loop asks the alarm evaluator once per seller per cycle."""
    checked: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return False

    async def reporter(seller_id: str) -> tuple[Any, ...]:
        checked.append(seller_id)
        return ()

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        freshness_alarm_reporter=reporter,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert checked == ["82453304", "999"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_a_failing_alarm_reporter_does_not_stop_the_refresh_cycle() -> None:
    planned: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            planned.append(mode)
            return True

    async def reporter(seller_id: str) -> tuple[Any, ...]:
        raise RuntimeError("alert transport unavailable")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        freshness_alarm_reporter=reporter,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert planned == ["fast", "daily"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_repeated_cycle_failures_are_reported_to_the_alert_sink() -> None:
    """Q21-a: a repeatedly failing refresh asks the sink to alert."""

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            raise RuntimeError("mongo unavailable")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            raise AssertionError("planner must not run when discovery fails")

    attempts: list[int] = []

    async def failure_reporter(count: int) -> None:
        attempts.append(count)

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        refresh_failure_reporter=failure_reporter,
        interval_seconds=0.01,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="restart budget exhausted"):
        await supervisor._run()

    assert attempts == [1, 2, 3]
    assert supervisor.health_status == "error"


@pytest.mark.asyncio
async def test_a_failing_refresh_alarm_sink_does_not_stop_recovery() -> None:
    """Alerting is a side channel: it must never change loop control flow."""

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            raise RuntimeError("mongo unavailable")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return True

    async def failure_reporter(count: int) -> None:
        raise RuntimeError("alert transport down")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        refresh_failure_reporter=failure_reporter,
        interval_seconds=0.01,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="restart budget exhausted"):
        await supervisor._run()


@pytest.mark.asyncio
async def test_refresh_builder_gates_alerts_behind_their_own_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q21-a alerting arrives off and is independent from refresh itself."""
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_FRESHNESS_ALERTS_ENABLED", raising=False)

    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())
    assert supervisor._freshness_alarm_reporter is None
    assert supervisor._refresh_failure_reporter is None

    monkeypatch.setenv("ZELERDATA_FRESHNESS_ALERTS_ENABLED", "true")
    enabled = await build_zelerdata_refresh_supervisor(db=_IndexedDb())
    assert enabled._freshness_alarm_reporter is not None
    assert enabled._refresh_failure_reporter is not None


@pytest.mark.asyncio
async def test_refresh_builder_alerts_for_every_model_the_loop_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The alert contract is derived from live wiring, never a hand list."""
    from zeler_sheets.observed_read_model_markers import OBSERVED_READ_MODEL_SOURCES
    from zeler_sheets.zelerdata_freshness_alarm import refresh_owned_read_models

    expected = refresh_owned_read_models(
        observed_models=OBSERVED_READ_MODEL_SOURCES,
        devoluciones_enabled=True,
    )

    # Only models whose marker the loop actually renews belong to the alert
    # contract. Planning acquisition is not certifying freshness: alerting on a
    # marker the loop never republishes would page an operator forever.
    assert set(MARKER_RENEWED_REFRESH_MODELS) <= set(expected)
    assert set(OBSERVED_READ_MODEL_SOURCES) <= set(expected)
    assert "devoluciones" in expected
    assert set(expected) <= set(IMPLEMENTED_REFRESH_MODELS) | set(OBSERVED_READ_MODEL_SOURCES) | {
        "devoluciones"
    }
    # The loop must not claim ownership of models it never plans.
    assert "claims" not in expected


@pytest.mark.asyncio
async def test_the_loop_reports_alarms_for_models_it_promised_to_keep_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed window on a loop-owned model reaches the alert sink."""
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_FRESHNESS_ALERTS_ENABLED", "true")

    stale = {
        "_id": "82453304:orders",
        "seller_id": "82453304",
        "read_model": "orders",
        "state": "reconciled",
        "fresh_until": datetime.now(UTC) - timedelta(hours=2),
        "valid_until": datetime.now(UTC) - timedelta(hours=1),
    }

    class _DbWithMarkers:
        def __init__(self) -> None:
            self.indexes: list[Any] = []

        def __getitem__(self, name: str) -> Any:
            if name == "sheets_read_model_freshness":
                return _RowsCollection([stale])
            return _IndexedCollection(self.indexes, name)

    supervisor = await build_zelerdata_refresh_supervisor(db=_DbWithMarkers())
    reporter = supervisor._freshness_alarm_reporter
    assert reporter is not None
    assert await reporter("82453304") == ("orders",)


@pytest.mark.asyncio
async def test_supervisor_warms_precalculated_formulas_once_per_seller() -> None:
    """Q3/Q8/Q16: the heavy aggregates are computed by the refresh cycle."""
    warmed: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return False

    async def warmer(seller_id: str) -> int:
        warmed.append(seller_id)
        return 10 if seller_id == "82453304" else 0

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        precalculated_warmer=warmer,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert warmed == ["82453304", "999"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_a_failing_precalculated_warmer_does_not_stop_the_refresh_cycle() -> None:
    planned: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            planned.append(mode)
            return True

    async def warmer(seller_id: str) -> int:
        raise RuntimeError("precalculated warm unavailable")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        precalculated_warmer=warmer,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert planned == ["fast", "daily"]
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_refresh_builder_wires_the_precalculated_warmer_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q3/Q8/Q16: the heavy aggregates are warmed by the refresh cycle."""
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_PRECALCULATED_FORMULAS_ENABLED", "true")

    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())

    assert supervisor._precalculated_warmer is not None


@pytest.mark.asyncio
async def test_refresh_builder_leaves_the_precalculated_warmer_off_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_PRECALCULATED_FORMULAS_ENABLED", raising=False)

    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())

    assert supervisor._precalculated_warmer is None


@pytest.mark.asyncio
async def test_refresh_builder_renews_devoluciones_even_with_advancement_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settled proof must be renewed without any source work or authorization.

    ``ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED`` gates source acquisition only.
    The marker renewal never calls Mercado Libre, so it runs unconditionally and
    keeps an already-proven range productive between authorizations.
    """
    from zeler_sheets import consumer as consumer_module
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    calls: list[dict[str, Any]] = []

    async def runner(
        db: Any, seller_id: str, *, advance_enabled: bool = True, now: Any = None
    ) -> bool:
        calls.append({"seller_id": seller_id, "advance_enabled": advance_enabled})
        return False

    monkeypatch.setattr(consumer_module, "advance_due_devoluciones_run", runner)
    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED", raising=False)

    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())
    await supervisor.run_cycle()

    assert calls == [{"seller_id": "82453304", "advance_enabled": False}]


@pytest.mark.asyncio
async def test_supervisor_runs_the_dlq_auto_archive_once_per_daily_sweep() -> None:
    """Q4-b/Q11-c: the archive must keep running, not only on a manual CLI run.

    The archive rescans the whole queue and redraws every retained message, so
    it rides the daily sweep instead of the 15-minute cycle.
    """
    runs: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304", "999")

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return False

    async def archiver() -> Any:
        runs.append("archive")
        return None

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        dlq_archiver=archiver,
        interval_seconds=900,
        now=lambda: NOW,
    )
    await supervisor.run_cycle()

    assert runs == ["archive"]


@pytest.mark.asyncio
async def test_the_dlq_auto_archive_does_not_run_on_a_fast_only_cycle() -> None:
    """A 15-minute cycle must not redraw the whole queue just to stay automatic."""
    runs: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            return True

    async def archiver() -> Any:
        runs.append("archive")
        return None

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        dlq_archiver=archiver,
        interval_seconds=900,
        now=lambda: datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
    )
    await supervisor.run_cycle()

    assert runs == []


@pytest.mark.asyncio
async def test_a_failing_dlq_archiver_does_not_stop_the_refresh_cycle() -> None:
    planned: list[str] = []

    class Explorer:
        async def discover_sellers(self) -> tuple[str, ...]:
            return ("82453304",)

    class Planner:
        async def plan(self, *, seller_id: str, mode: str = "fast") -> bool:
            planned.append(mode)
            return True

    async def archiver() -> Any:
        raise RuntimeError("broker unavailable")

    supervisor = ZelerDataRefreshSupervisor(
        explorer=Explorer(),
        planner=Planner(),
        dlq_archiver=archiver,
        interval_seconds=900,
        now=lambda: NOW,
    )

    assert await supervisor.run_cycle() is True
    assert "fast" in planned
    assert supervisor.health_status == "ok"


@pytest.mark.asyncio
async def test_the_dlq_auto_archive_is_off_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_DLQ_ARCHIVE_ENABLED", raising=False)

    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())

    assert supervisor._dlq_archiver is None


@pytest.mark.asyncio
async def test_the_dlq_auto_archive_needs_the_broker_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_DLQ_ARCHIVE_ENABLED", "true")
    monkeypatch.delenv("RABBITMQ_URL", raising=False)

    with pytest.raises(RuntimeError, match="RABBITMQ_URL"):
        await build_zelerdata_refresh_supervisor(db=_IndexedDb())


@pytest.mark.asyncio
async def test_refresh_factory_wires_inventory_only_to_scoped_existing_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_zelerdata_refresh_supervisor

    monkeypatch.setenv("ZELERDATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("ZELERDATA_REFRESH_SELLERS", "82453304")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_ENABLED", "true")
    monkeypatch.delenv("ZELERDATA_REFRESH_INTERVAL_SECONDS", raising=False)
    supervisor = await build_zelerdata_refresh_supervisor(db=_IndexedDb())
    assert isinstance(supervisor._planner, ZelerDataRefreshPlanner)
    assert supervisor._inventory_refresher is not None
    assert supervisor._inventory_refresher == supervisor._planner.plan_inventory
    assert supervisor._inventory_interval == 30
    assert supervisor._interval == 900
    assert await supervisor._inventory_refresher("999") is False
