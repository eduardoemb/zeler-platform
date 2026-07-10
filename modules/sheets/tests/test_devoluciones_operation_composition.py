from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from infra.operations import zelerdata_read_model_reconcile as reconcile_operation

import zeler_sheets.consumer as consumer_module
from zeler_bootstrap.stages import ClaimsStage, OrdersStage
from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
from zeler_sheets.claim_projection import project_claim
from zeler_sheets.consumer import SheetsEvent, SheetsEventHandler
from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.historical_meli_backfill import run_historical_meli_backfill
from zeler_sheets.sheetseller_backfill import (
    run_order_identity_repair,
    run_order_normalization,
)


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="stable-operation",
        attempt_token=uuid4().hex,
        fence=7,
        owns_lease=True,
        source_fingerprint="inventory-v1",
    )


def test_every_named_nested_writer_has_explicit_operation_parameter() -> None:
    named_callables = (
        reconcile_operation.execute_reconciliation_write,
        run_historical_meli_backfill,
        SheetsEventPersistence.persist,
        SheetsEventPersistence._persist_order,
        project_claim,
        OrdersStage.run,
        ClaimsStage.run,
        SheetsEventHandler.handle,
        run_order_identity_repair,
        run_order_normalization,
    )

    for callable_ in named_callables:
        assert "operation" in inspect.signature(callable_).parameters, callable_.__qualname__


@pytest.mark.asyncio
async def test_event_persistence_passes_same_context_to_nested_order_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[DevolucionesOperationContext] = []

    async def persist_order(
        self: SheetsEventPersistence,
        *,
        seller_id: str,
        resource: dict[str, Any],
        operation: DevolucionesOperationContext,
    ) -> None:
        del self, seller_id, resource
        captured.append(operation)

    monkeypatch.setattr(SheetsEventPersistence, "_persist_order", persist_order)
    operation = _operation()

    await SheetsEventPersistence(db=object()).persist(
        event_type="orders.updated",
        seller_id="82453304",
        resource={"id": 2001},
        operation=operation,
    )

    assert captured == [operation]
    assert captured[0] is operation


class Gateway:
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        del seller_id, path
        return {"id": 2001}


class OrderedGateway:
    def __init__(self, calls: list[str], *, error: Exception | None = None) -> None:
        self.calls = calls
        self.error = error

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        del seller_id
        self.calls.append(f"fetch:{path}")
        if self.error is not None:
            raise self.error
        return {
            "id": 2001,
            "seller": {"id": 82453304},
            "buyer": {"id": 1},
            "status": "paid",
            "date_created": "2026-06-01T00:00:00Z",
            "total_amount": "10.00",
            "order_items": [
                {
                    "item": {"id": "MLA1", "seller_sku": "SKU-1"},
                    "quantity": 1,
                    "unit_price": "10.00",
                }
            ],
        }


class Persistence:
    def __init__(self) -> None:
        self.operation: DevolucionesOperationContext | None = None

    async def persist(self, **kwargs: Any) -> None:
        self.operation = kwargs["operation"]


class OrderedPersistence(Persistence):
    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self.calls = calls

    async def persist(self, **kwargs: Any) -> None:
        self.calls.append("persist")
        await super().persist(**kwargs)


class Idempotency:
    async def is_duplicate(self, key: str) -> bool:
        del key
        return False

    async def mark_processed(self, key: str) -> None:
        del key


class Collection:
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        del filter_spec
        return None


class Db:
    def __getitem__(self, name: str) -> Collection:
        del name
        return Collection()


class RelevanceCollection(Collection):
    def __init__(self, calls: list[str], *, referenced: bool) -> None:
        self.calls = calls
        self.referenced = referenced

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append("relevance")
        assert filter_spec["seller_id"] == "82453304"
        assert filter_spec["type"] == {"$in": ["returns", "return", "mediations"]}
        return {"_id": "claim-1"} if self.referenced else None


class EventDb(Db):
    def __init__(self, calls: list[str], *, referenced: bool) -> None:
        self.claims = RelevanceCollection(calls, referenced=referenced)

    def __getitem__(self, name: str) -> Collection:
        if name == "claims":
            return self.claims
        return Collection()


class SheetsClient:
    async def append_row(self, **kwargs: Any) -> None:
        del kwargs


@pytest.mark.asyncio
async def test_event_handler_borrows_same_context_without_reacquiring() -> None:
    persistence = Persistence()
    handler = SheetsEventHandler(
        db=Db(),
        gateway_client=Gateway(),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=persistence,
    )
    operation = _operation()
    event = SheetsEvent(
        event_id="event-1",
        event_type="orders.updated",
        seller_id=82453304,
        resource="/orders/2001",
        idempotency_key="orders.updated:event-1",
    )

    result = await handler.handle(event, operation=operation)

    assert result == "no_export"
    assert persistence.operation is operation


@pytest.mark.asyncio
async def test_event_handler_root_heartbeats_until_operation_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persistence = Persistence()
    operation = _operation()
    calls: list[tuple[str, Any]] = []

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        del kwargs
        calls.append(("acquire", operation))
        return operation

    async def finish(**kwargs: Any) -> None:
        calls.append(("finish", kwargs["succeeded"]))

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        calls.append(("heartbeat_enter", kwargs["operation"]))
        try:
            yield
        finally:
            calls.append(("heartbeat_exit", kwargs["operation"]))

    monkeypatch.setattr(consumer_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(consumer_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(
        consumer_module, "maintain_devoluciones_heartbeat", heartbeat, raising=False
    )
    handler = SheetsEventHandler(
        db=Db(),
        gateway_client=Gateway(),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=persistence,
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="event-root",
            event_type="orders.updated",
            seller_id=82453304,
            resource="/orders/2001",
            idempotency_key="orders.updated:event-root",
        )
    )

    assert result == "no_export"
    assert persistence.operation is operation
    assert calls == [
        ("acquire", operation),
        ("heartbeat_enter", operation),
        ("finish", True),
        ("heartbeat_exit", operation),
    ]


@pytest.mark.asyncio
async def test_claim_event_persists_hydrated_order_before_claim_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    persistence_calls: list[dict[str, Any]] = []

    class ClaimGateway:
        async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
            del seller_id
            if path == "/post-purchase/v1/claims/519988001":
                return {"id": "519988001", "order_id": "1999"}
            if path == "/post-purchase/v2/claims/519988001/returns":
                return {"id": "return-1", "orders": []}
            if path == "/orders/1999":
                return {"id": 1999, "seller": {"id": 82453304}}
            raise AssertionError(path)

    class RecordingPersistence:
        async def persist(self, **kwargs: Any) -> None:
            persistence_calls.append(kwargs)

    async def project(**kwargs: Any) -> dict[str, Any]:
        return {"_id": kwargs["claim"]["id"], "status": "closed"}

    monkeypatch.setattr(consumer_module, "project_claim", project)
    handler = SheetsEventHandler(
        db=Db(),
        gateway_client=ClaimGateway(),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=RecordingPersistence(),
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="claim-event",
            event_type="claims.updated",
            seller_id=82453304,
            resource="/post-purchase/v1/claims/519988001",
            idempotency_key="claims.updated:claim-event",
        ),
        operation=operation,
    )

    assert result == "no_export"
    assert len(persistence_calls) == 1
    assert persistence_calls[0]["event_type"] == "orders.updated"
    assert persistence_calls[0]["resource"]["id"] == 1999
    assert persistence_calls[0]["operation"] is operation


@pytest.mark.asyncio
@pytest.mark.parametrize("referenced", [True, False])
async def test_order_event_invalidates_before_fetch_only_when_referenced_by_devoluciones(
    monkeypatch: pytest.MonkeyPatch,
    referenced: bool,
) -> None:
    calls: list[str] = []
    operation = _operation()
    acquire_options: list[bool] = []

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        calls.append("acquire")
        acquire_options.append(bool(kwargs["invalidate_readiness"]))
        return operation

    async def invalidate(**kwargs: Any) -> None:
        assert kwargs["operation"] is operation
        calls.append("invalidate")

    async def finish(**kwargs: Any) -> None:
        calls.append(f"finish:{kwargs['succeeded']}")

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        assert kwargs["operation"] is operation
        calls.append("heartbeat_enter")
        try:
            yield
        finally:
            calls.append("heartbeat_exit")

    monkeypatch.setattr(consumer_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(
        consumer_module, "invalidate_devoluciones_readiness", invalidate, raising=False
    )
    monkeypatch.setattr(consumer_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(consumer_module, "maintain_devoluciones_heartbeat", heartbeat)
    persistence = OrderedPersistence(calls)
    handler = SheetsEventHandler(
        db=EventDb(calls, referenced=referenced),
        gateway_client=OrderedGateway(calls),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=persistence,
    )

    result = await handler.handle(
        SheetsEvent(
            event_id="order-event",
            event_type="orders.updated",
            seller_id=82453304,
            resource="/orders/2001",
            idempotency_key="orders.updated:order-event",
        )
    )

    assert result == "no_export"
    assert acquire_options == [False]
    assert calls.index("acquire") < calls.index("relevance") < calls.index("fetch:/orders/2001")
    if referenced:
        assert (
            calls.index("relevance") < calls.index("invalidate") < calls.index("fetch:/orders/2001")
        )
    else:
        assert "invalidate" not in calls
    assert persistence.operation is operation


@pytest.mark.asyncio
async def test_relevant_event_fetch_failure_leaves_readiness_invalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    operation = _operation()

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        calls.append(f"acquire:{kwargs['invalidate_readiness']}")
        return operation

    async def invalidate(**kwargs: Any) -> None:
        assert kwargs["operation"] is operation
        calls.append("invalidate")

    async def finish(**kwargs: Any) -> None:
        calls.append(f"finish:{kwargs['succeeded']}")

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    monkeypatch.setattr(consumer_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(
        consumer_module, "invalidate_devoluciones_readiness", invalidate, raising=False
    )
    monkeypatch.setattr(consumer_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(consumer_module, "maintain_devoluciones_heartbeat", heartbeat)
    handler = SheetsEventHandler(
        db=EventDb(calls, referenced=True),
        gateway_client=OrderedGateway(calls, error=RuntimeError("gateway unavailable")),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=OrderedPersistence(calls),
    )

    with pytest.raises(RuntimeError, match="gateway unavailable"):
        await handler.handle(
            SheetsEvent(
                event_id="order-event",
                event_type="orders.updated",
                seller_id=82453304,
                resource="/orders/2001",
                idempotency_key="orders.updated:order-event",
            )
        )

    assert calls.index("invalidate") < calls.index("fetch:/orders/2001")
    assert calls[-1] == "finish:False"


@pytest.mark.asyncio
async def test_claim_event_acquires_and_invalidates_before_upstream_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    operation = _operation()

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        calls.append(f"acquire:{kwargs['invalidate_readiness']}")
        return operation

    async def finish(**kwargs: Any) -> None:
        calls.append(f"finish:{kwargs['succeeded']}")

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    monkeypatch.setattr(consumer_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(consumer_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(consumer_module, "maintain_devoluciones_heartbeat", heartbeat)
    handler = SheetsEventHandler(
        db=EventDb(calls, referenced=False),
        gateway_client=OrderedGateway(calls, error=RuntimeError("gateway unavailable")),
        sheets_client=SheetsClient(),
        idempotency_store=Idempotency(),
        event_persistence=OrderedPersistence(calls),
    )

    with pytest.raises(RuntimeError, match="gateway unavailable"):
        await handler.handle(
            SheetsEvent(
                event_id="claim-event",
                event_type="claims.updated",
                seller_id=82453304,
                resource="/post-purchase/v1/claims/claim-1",
                idempotency_key="claims.updated:claim-event",
            )
        )

    assert calls == [
        "acquire:True",
        "fetch:/post-purchase/v1/claims/claim-1",
        "finish:False",
    ]


@pytest.mark.asyncio
async def test_reconciliation_cli_root_owns_one_context_through_write_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    db = object()
    calls: list[tuple[str, Any]] = []
    args = reconcile_operation.build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--write",
            "--confirm-production-write",
        ]
    )
    summary = reconcile_operation.ReconciliationSummary(
        seller_id="82453304",
        date_from="2026-06-01",
        date_to="2026-06-04",
        dry_run=False,
        approved_runtime=True,
        write_enabled=True,
    )

    monkeypatch.setattr(reconcile_operation, "create_runtime_db", lambda: db)

    expected_calls = 0

    async def expected(**kwargs: Any) -> reconcile_operation.ExpectedReadModelCounts:
        nonlocal expected_calls
        del kwargs
        expected_calls += 1
        return reconcile_operation.ExpectedReadModelCounts(
            counts={}, source_fingerprint="inventory-v1"
        )

    async def counts(**kwargs: Any) -> reconcile_operation.ReconciliationSummary:
        del kwargs
        return summary

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        calls.append(("acquire", kwargs["source_fingerprint"]))
        return operation

    async def execute(**kwargs: Any) -> dict[str, int]:
        calls.append(("execute", kwargs["operation"]))
        return {}

    async def finish(**kwargs: Any) -> None:
        calls.append(("finish", (kwargs["operation"], kwargs["succeeded"])))

    async def markers(**kwargs: Any) -> dict[str, int]:
        calls.append(
            (
                "markers",
                (kwargs["operation"], kwargs["expected"].source_fingerprint),
            )
        )
        return {}

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        calls.append(("heartbeat_enter", kwargs["operation"]))
        try:
            yield
        finally:
            calls.append(("heartbeat_exit", kwargs["operation"]))

    monkeypatch.setattr(reconcile_operation, "collect_expected_read_model_counts", expected)
    monkeypatch.setattr(reconcile_operation, "collect_reconciliation_counts", counts)
    monkeypatch.setattr(reconcile_operation, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(reconcile_operation, "execute_reconciliation_write", execute)
    monkeypatch.setattr(reconcile_operation, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(reconcile_operation, "write_complete_read_model_freshness_markers", markers)
    monkeypatch.setattr(reconcile_operation, "maintain_devoluciones_heartbeat", heartbeat)

    result = await reconcile_operation._run_cli(args)

    assert result.write_enabled is True
    assert expected_calls == 2
    assert calls == [
        ("acquire", "inventory-v1"),
        ("heartbeat_enter", operation),
        ("execute", operation),
        ("markers", (operation, "inventory-v1")),
        ("finish", (operation, True)),
        ("heartbeat_exit", operation),
    ]


@pytest.mark.asyncio
async def test_reconciliation_root_rejects_source_drift_before_marker_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    db = object()
    args = reconcile_operation.build_arg_parser().parse_args(
        [
            "--seller-id",
            "82453304",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-04",
            "--confirm-approved-runtime",
            "--write",
            "--confirm-production-write",
        ]
    )
    fingerprints = iter(("inventory-v1", "inventory-v2"))
    marker_calls: list[Any] = []
    finish_calls: list[bool] = []

    monkeypatch.setattr(reconcile_operation, "create_runtime_db", lambda: db)

    async def expected(**kwargs: Any) -> reconcile_operation.ExpectedReadModelCounts:
        del kwargs
        return reconcile_operation.ExpectedReadModelCounts(
            counts={}, source_fingerprint=next(fingerprints)
        )

    async def counts(**kwargs: Any) -> reconcile_operation.ReconciliationSummary:
        request = kwargs["request"]
        return reconcile_operation.ReconciliationSummary(
            seller_id=request.seller_id,
            date_from=request.date_range.date_from,
            date_to=request.date_range.date_to,
            dry_run=False,
            approved_runtime=True,
            write_enabled=True,
        )

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        operation.source_fingerprint = kwargs["source_fingerprint"]
        return operation

    async def finish(**kwargs: Any) -> None:
        finish_calls.append(bool(kwargs["succeeded"]))

    async def markers(**kwargs: Any) -> dict[str, int]:
        marker_calls.append(kwargs)
        return {}

    async def execute(**kwargs: Any) -> dict[str, int]:
        del kwargs
        return {}

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    monkeypatch.setattr(reconcile_operation, "collect_expected_read_model_counts", expected)
    monkeypatch.setattr(reconcile_operation, "collect_reconciliation_counts", counts)
    monkeypatch.setattr(reconcile_operation, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(reconcile_operation, "execute_reconciliation_write", execute)
    monkeypatch.setattr(reconcile_operation, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(reconcile_operation, "write_complete_read_model_freshness_markers", markers)
    monkeypatch.setattr(reconcile_operation, "maintain_devoluciones_heartbeat", heartbeat)

    with pytest.raises(RuntimeError, match="source fingerprint"):
        await reconcile_operation._run_cli(args)

    assert marker_calls == []
    assert finish_calls == [False]


@pytest.mark.asyncio
async def test_reconciliation_write_passes_same_context_to_historical_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    captured: dict[str, Any] = {}
    request = reconcile_operation.build_reconciliation_request(
        reconcile_operation.build_arg_parser().parse_args(
            [
                "--seller-id",
                "82453304",
                "--date-from",
                "2026-06-01",
                "--date-to",
                "2026-06-04",
                "--confirm-approved-runtime",
                "--write",
                "--confirm-production-write",
            ]
        )
    )

    async def historical(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(item_ids=[])

    async def formula(**kwargs: Any) -> Any:
        del kwargs
        return SimpleNamespace()

    monkeypatch.setattr(
        "zeler_sheets.historical_meli_backfill.run_historical_meli_backfill", historical
    )
    monkeypatch.setattr("zeler_sheets.sheetseller_backfill.run_sheetseller_backfill", formula)
    monkeypatch.setattr(
        "zeler_sheets.remaining_read_model_writers.run_remaining_observed_read_model_seed",
        formula,
    )
    monkeypatch.setattr(
        "zeler_sheets.source_gated_read_model_writers.run_source_gated_read_model_import",
        formula,
    )
    monkeypatch.setattr(
        reconcile_operation,
        "create_runtime_historical_meli_gateways",
        lambda: SimpleNamespace(gateway=object(), order_detail_gateway=object()),
    )

    await reconcile_operation.execute_reconciliation_write(
        db=object(), request=request, operation=operation
    )

    assert captured["operation"] is operation
