from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [doc for doc in self.docs if all(doc.get(key) == value for key, value in query.items())]
        )

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)


class FakeDb:
    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self.fulldock_inventory_rules = FakeCollection(rules)
        self.fulldock_history = FakeCollection([])

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "fulldock_inventory_rules":
            return self.fulldock_inventory_rules
        if name == "fulldock_history":
            return self.fulldock_history
        raise AssertionError(name)


class FakeGatewayClient:
    def __init__(self, resources: dict[str, dict[str, Any]]) -> None:
        self.resources = resources
        self.requests: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, path, seller_id, json))
        if method == "GET":
            return self.resources[path]
        return {"status": "updated"}


class ErrorGatewayClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.requests: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, path, seller_id, json))
        raise self.error


class FakeIdempotencyStore:
    def __init__(self, duplicates: set[str] | None = None) -> None:
        self.duplicates = duplicates or set()
        self.processed: list[str] = []

    async def is_duplicate(self, key: str) -> bool:
        return key in self.duplicates

    async def mark_processed(self, key: str) -> None:
        self.processed.append(key)


def test_parse_user_product_stock_resource_accepts_exact_stock_paths() -> None:
    from zeler_fulldock.consumer import parse_user_product_stock_resource

    assert parse_user_product_stock_resource("/user-products/UP1/stock") == "UP1"
    assert parse_user_product_stock_resource("/user-products/UP1/stock/") == "UP1"


@pytest.mark.parametrize(
    "resource_path",
    [
        "user-products/UP1/stock",
        "/user-products/UP1",
        "/user-products/UP1/stock/extra",
        "/user-products//stock",
        "/items/stock",
        "/user-products/UP1/locations",
    ],
)
def test_parse_user_product_stock_resource_rejects_malformed_paths(resource_path: str) -> None:
    from zeler_fulldock.consumer import parse_user_product_stock_resource

    assert parse_user_product_stock_resource(resource_path) is None


@pytest.mark.asyncio
async def test_shipment_triggers_stock_update() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-1",
                "seller_id": "123456789",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [
                    {"location_id": "AR-FULL-1", "quantity": 7},
                    {"location_id": "AR-FULL-2", "quantity": 3},
                ],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/shipments/ship-1": {
                "id": "ship-1",
                "items": [{"id": "MLA1"}, {"item_id": "MLA2"}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 14, 0, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-1",
            event_type="shipments.updated",
            seller_id=123456789,
            resource="/shipments/ship-1",
            idempotency_key="idem-1",
        )
    )

    assert outcome == "updated"
    assert gateway.requests == [
        ("GET", "/shipments/ship-1", "123456789", None),
        (
            "PUT",
            "/items/MLA1/stock_locations",
            "123456789",
            {
                "locations": [
                    {"location_id": "AR-FULL-1", "quantity": 7},
                    {"location_id": "AR-FULL-2", "quantity": 3},
                ]
            },
        ),
    ]
    assert db.fulldock_history.docs[0]["outcome"] == "updated"
    assert db.fulldock_history.docs[0]["item_id"] == "MLA1"
    assert idempotency.processed == ["idem-1"]


@pytest.mark.asyncio
async def test_no_rule_skips_update_and_records_history() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb([])
    gateway = FakeGatewayClient({"/items/MLA9": {"id": "MLA9"}})
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 14, 5, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-2",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA9",
            idempotency_key="idem-2",
        )
    )

    assert outcome == "no_rule"
    assert gateway.requests == [("GET", "/items/MLA9", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "no_rule"
    assert idempotency.processed == ["idem-2"]


@pytest.mark.asyncio
async def test_duplicate_event_skipped_without_gateway_calls() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    gateway = FakeGatewayClient({"/items/MLA1": {"id": "MLA1"}})
    handler = FulldockEventHandler(
        db=FakeDb([]),
        gateway_client=gateway,
        idempotency_store=FakeIdempotencyStore({"idem-duplicate"}),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-3",
            event_type="items.updated",
            seller_id=123456789,
            resource="/items/MLA1",
            idempotency_key="idem-duplicate",
        )
    )

    assert outcome == "duplicate"
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_stock_location_malformed_resource_records_noop_without_gateway_call() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb([])
    gateway = FakeGatewayClient({})
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 15, 0, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-malformed",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/locations",
            idempotency_key="idem-stock-malformed",
        )
    )

    assert outcome == "malformed_resource"
    assert gateway.requests == []
    assert db.fulldock_history.docs[0]["outcome"] == "malformed_resource"
    assert db.fulldock_history.docs[0]["item_id"] == "unknown"
    assert idempotency.processed == ["idem-stock-malformed"]


@pytest.mark.asyncio
async def test_stock_location_missing_mapping_records_noop_without_stock_segment_fallback() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb([])
    gateway = FakeGatewayClient(
        {
            "/user-products/UP1/stock": {
                "id": "UP1",
                "locations": [{"location_id": "A", "quantity": 1}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=gateway,
        idempotency_store=idempotency,
        clock=lambda: datetime(2026, 4, 24, 15, 5, tzinfo=UTC),
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-missing-map",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-missing-map",
        )
    )

    assert outcome == "missing_mapping"
    assert gateway.requests == [("GET", "/user-products/UP1/stock", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "missing_mapping"
    assert db.fulldock_history.docs[0]["item_id"] == "unknown"
    assert idempotency.processed == ["idem-stock-missing-map"]


@pytest.mark.asyncio
async def test_stock_location_without_enabled_rule_records_missing_mapping_and_no_put() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-other-seller",
                "seller_id": "999999999",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [{"location_id": "A", "quantity": 1}],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/user-products/UP1/stock": {
                "item_id": "MLA1",
                "locations": [{"location_id": "A", "quantity": 1}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(db=db, gateway_client=gateway, idempotency_store=idempotency)

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-no-rule",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-no-rule",
        )
    )

    assert outcome == "missing_mapping"
    assert gateway.requests == [("GET", "/user-products/UP1/stock", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "missing_mapping"
    assert db.fulldock_history.docs[0]["item_id"] == "MLA1"
    assert idempotency.processed == ["idem-stock-no-rule"]


@pytest.mark.asyncio
async def test_stock_location_malformed_current_locations_records_missing_mapping_no_put() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-1",
                "seller_id": "123456789",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [{"location_id": "A", "quantity": 7}],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/user-products/UP1/stock": {
                "item_id": "MLA1",
                "locations": [{"location_id": "A"}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(db=db, gateway_client=gateway, idempotency_store=idempotency)

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-malformed-locations",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-malformed-locations",
        )
    )

    assert outcome == "missing_mapping"
    assert gateway.requests == [("GET", "/user-products/UP1/stock", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "missing_mapping"
    assert db.fulldock_history.docs[0]["item_id"] == "MLA1"
    assert idempotency.processed == ["idem-stock-malformed-locations"]


@pytest.mark.asyncio
async def test_stock_location_equal_current_and_desired_records_no_drift_without_put() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-1",
                "seller_id": "123456789",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [
                    {"location_id": "B", "quantity": 2},
                    {"location_id": "A", "quantity": 1},
                ],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/user-products/UP1/stock": {
                "item": {"id": "MLA1"},
                "locations": [
                    {"location_id": "A", "quantity": 1},
                    {"location_id": "B", "quantity": 2},
                ],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(db=db, gateway_client=gateway, idempotency_store=idempotency)

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-no-drift",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-no-drift",
        )
    )

    assert outcome == "no_drift"
    assert gateway.requests == [("GET", "/user-products/UP1/stock", "123456789", None)]
    assert db.fulldock_history.docs[0]["outcome"] == "no_drift"
    assert db.fulldock_history.docs[0]["stock_locations"] == [
        {"location_id": "A", "quantity": 1},
        {"location_id": "B", "quantity": 2},
    ]
    assert idempotency.processed == ["idem-stock-no-drift"]


@pytest.mark.asyncio
async def test_stock_location_drift_performs_single_put_and_records_updated() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb(
        [
            {
                "_id": "rule-1",
                "seller_id": "123456789",
                "item_id": "MLA1",
                "enabled": True,
                "stock_locations": [{"location_id": "A", "quantity": 7}],
            }
        ]
    )
    gateway = FakeGatewayClient(
        {
            "/user-products/UP1/stock": {
                "item_id": "MLA1",
                "locations": [{"location_id": "A", "quantity": 1}],
            }
        }
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(db=db, gateway_client=gateway, idempotency_store=idempotency)

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-drift",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-drift",
        )
    )

    assert outcome == "updated"
    assert gateway.requests == [
        ("GET", "/user-products/UP1/stock", "123456789", None),
        (
            "PUT",
            "/items/MLA1/stock_locations",
            "123456789",
            {"locations": [{"location_id": "A", "quantity": 7}]},
        ),
    ]
    assert db.fulldock_history.docs[0]["outcome"] == "updated"
    assert db.fulldock_history.docs[0]["item_id"] == "MLA1"
    assert idempotency.processed == ["idem-stock-drift"]


@pytest.mark.asyncio
async def test_stock_location_404_records_resource_not_found_noop() -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    db = FakeDb([])
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=db,
        gateway_client=ErrorGatewayClient(_http_status_error(404, path="/user-products/UP1/stock")),
        idempotency_store=idempotency,
    )

    outcome = await handler.handle(
        FulldockEvent(
            event_id="event-stock-404",
            event_type="stock_locations.updated",
            seller_id=123456789,
            resource="/user-products/UP1/stock",
            idempotency_key="idem-stock-404",
        )
    )

    assert outcome == "resource_not_found"
    assert db.fulldock_history.docs[0]["outcome"] == "resource_not_found"
    assert idempotency.processed == ["idem-stock-404"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["403", "rate_limit"])
async def test_stock_location_403_and_rate_limit_errors_propagate(error_kind: str) -> None:
    from zeler_fulldock.consumer import FulldockEvent, FulldockEventHandler

    error = (
        _http_status_error(403) if error_kind == "403" else _rate_limit_error(retry_after_seconds=3)
    )
    idempotency = FakeIdempotencyStore()
    handler = FulldockEventHandler(
        db=FakeDb([]),
        gateway_client=ErrorGatewayClient(error),
        idempotency_store=idempotency,
    )

    with pytest.raises(type(error)):
        await handler.handle(
            FulldockEvent(
                event_id="event-stock-error",
                event_type="stock_locations.updated",
                seller_id=123456789,
                resource="/user-products/UP1/stock",
                idempotency_key="idem-stock-error",
            )
        )

    assert idempotency.processed == []


def _http_status_error(
    status_code: int, *, path: str = "/user-products/UP1/stock"
) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://gateway:8080/proxy/meli{path}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} response",
        request=request,
        response=response,
    )


def _rate_limit_error(*, retry_after_seconds: int) -> GatewayRateLimitError:
    response = httpx.Response(429, request=httpx.Request("GET", "http://gateway"))
    return GatewayRateLimitError(retry_after_seconds=retry_after_seconds, response=response)
