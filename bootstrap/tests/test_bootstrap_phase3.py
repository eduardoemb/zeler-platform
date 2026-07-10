from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

import zeler_bootstrap.stages as stages_module
from zeler_bootstrap.runner import BootstrapDagRunner, BootstrapStage, build_default_stages
from zeler_bootstrap.stages import (
    MELI_ITEMS_BATCH_SIZE,
    AccountsStage,
    BootstrapGatewayClient,
    ClaimsStage,
    InMemoryPublisher,
    ItemsStage,
    MessagesStage,
    OrdersStage,
    ShipmentsStage,
)
from zeler_bootstrap.state_machine import BootstrapStateMachine, InvalidTransitionError
from zeler_platform_core.devoluciones_readiness import (
    DevolucionesLeaseLostError,
    DevolucionesOperationContext,
)
from zeler_platform_core.models import OrderItem
from zeler_sheets.devoluciones_reconciliation import VerifiedClaimInventory

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _bootstrap_fencing_test_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        return DevolucionesOperationContext(
            seller_id=str(kwargs["seller_id"]),
            scope="devoluciones",
            operation_id=str(kwargs["operation_id"]),
            attempt_token=uuid4().hex,
            fence=1,
            owns_lease=True,
            source_fingerprint=kwargs.get("source_fingerprint"),
        )

    async def finish(**kwargs: Any) -> None:
        del kwargs

    async def guarded_write(**kwargs: Any) -> None:
        result = kwargs["writer"](None)
        if inspect.isawaitable(result):
            await result

    async def empty_claim_inventory(**kwargs: Any) -> Any:
        del kwargs
        return SimpleNamespace(
            projections=(),
            orders=(),
            inventory=VerifiedClaimInventory(entries=(), fingerprint="0" * 64),
            source_fingerprint="1" * 64,
            read_model_fingerprint="2" * 64,
        )

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    monkeypatch.setattr(stages_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(stages_module, "finish_devoluciones_operation", finish)
    monkeypatch.setattr(stages_module, "guarded_devoluciones_write", guarded_write)
    monkeypatch.setattr(stages_module, "collect_devoluciones_snapshot", empty_claim_inventory)
    monkeypatch.setattr(stages_module, "maintain_devoluciones_heartbeat", heartbeat, raising=False)


class FakeBootstrapJobs:
    def __init__(self) -> None:
        self.document: dict[str, Any] = {
            "_id": "job-1",
            "seller_id": "123",
            "state": "pending",
            "dag": {},
            "checkpoints": {},
            "stage_progress": {},
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }

    async def find_one(self, filter_spec: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        if filter_spec.get("_id") == self.document["_id"]:
            return self.document.copy()
        return None

    async def find_one_and_update(
        self, filter_spec: dict[str, Any], update: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        if filter_spec.get("_id") != self.document["_id"]:
            return None
        allowed_states = filter_spec.get("state")
        allowed_list = (
            allowed_states.get("$in", [allowed_states])
            if isinstance(allowed_states, dict)
            else [allowed_states]
        )
        if allowed_states is not None and self.document["state"] not in allowed_list:
            return None
        for key, value in update.get("$set", {}).items():
            target = self.document
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        for key, value in update.get("$inc", {}).items():
            target = self.document
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = target.get(parts[-1], 0) + value
        return self.document.copy()


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self.documents: dict[str, dict[str, Any]] = {}

    async def update_one(
        self, filter_spec: dict[str, Any], update: Any, *, upsert: bool = False, **_: Any
    ) -> Any:
        self.upserts.append((filter_spec, update, upsert))
        document_id = str(filter_spec.get("_id") or filter_spec.get("seller_id") or "")
        if not document_id:
            return type("FakeUpdateResult", (), {"matched_count": 0, "upserted_id": None})()
        current = dict(self.documents.get(document_id, {}))
        update_stages = update if isinstance(update, list) else [update]
        for update_stage in update_stages:
            current.update(update_stage.get("$setOnInsert", {}))
            current.update(update_stage.get("$set", {}))
            for field in update_stage.get("$unset", {}):
                current.pop(field, None)
        self.documents[document_id] = current
        return type(
            "FakeUpdateResult",
            (),
            {
                "matched_count": 1 if current else 0,
                "upserted_id": document_id if upsert else None,
            },
        )()

    async def replace_one(
        self, filter_spec: dict[str, Any], replacement: dict[str, Any], *, upsert: bool = False
    ) -> Any:
        document_id = str(replacement.get("_id") or filter_spec.get("_id") or "")
        if document_id:
            self.documents[document_id] = dict(replacement)
        return type("FakeReplaceResult", (), {"matched_count": 1, "upserted_id": document_id})()

    async def find_one(self, filter_spec: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        for document in self.documents.values():
            if _matches_filter(document, filter_spec):
                return dict(document)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        documents = [
            dict(document)
            for document in self.documents.values()
            if _matches_filter(document, filter_spec)
        ]
        return FakeCursor(documents)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        documents = list(self._documents)
        for key, direction in reversed(sort_spec):
            documents.sort(
                key=lambda document: str(_nested_value(document, key) or ""),
                reverse=direction < 0,
            )
        return FakeCursor(documents)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        documents = self._documents[:length] if length else self._documents
        return [dict(document) for document in documents]


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeSession:
    def start_transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class FakeClient:
    def start_session(self) -> FakeSession:
        return FakeSession()


class FakeDatabase(dict[str, FakeCollection]):
    def __init__(self) -> None:
        super().__init__()
        self.client = FakeClient()

    def __getitem__(self, collection_name: str) -> FakeCollection:
        return self.setdefault(collection_name, FakeCollection())


def _matches_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        actual = _nested_value(document, key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _nested_value(document: dict[str, Any], dotted_path: str) -> Any:
    value: Any = document
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class FakeGateway(BootstrapGatewayClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, params))
        if path == "/users/123":
            return {"id": 123, "nickname": "TEST_SELLER", "site_id": "MLM"}
        if path == "/users/123/items/search":
            cursor = (params or {}).get("scroll_id")
            if cursor is None:
                return {"results": ["MLM1", "MLM2"], "scroll_id": "p2", "paging": {"total": 3}}
            return {"results": ["MLM3"], "scroll_id": None, "paging": {"total": 3}}
        if path == "/items":
            ids = str((params or {}).get("ids", "")).split(",")
            return cast(
                dict[str, Any],
                [
                    {
                        "code": 200,
                        "body": {
                            "id": item_id,
                            "seller_id": "123",
                            "title": f"Item {item_id}",
                            "price": "10.00",
                            "base_price": "10.00",
                            "available_quantity": 5,
                            "status": "active",
                            "category_id": "MLM-CAT",
                            "date_created": NOW,
                            "last_updated": NOW,
                        },
                    }
                    for item_id in ids
                    if item_id
                ],
            )
        if path == "/orders/search":
            return {
                "results": [
                    {
                        "id": 987,
                        "buyer": {"id": 45},
                        "status": "paid",
                        "date_created": NOW,
                        "total_amount": "20.00",
                        "pack_id": 555,
                        "order_items": [
                            {"item": {"id": "MLM1"}, "quantity": 2, "unit_price": "10.00"}
                        ],
                        "shipping": {"id": 654},
                    }
                ],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            }
        if path == "/questions/search":
            return {
                "questions": [
                    {
                        "id": 333,
                        "seller_id": 123,
                        "item_id": "MLM1",
                        "text": "Stock?",
                        "status": "UNANSWERED",
                        "from": {"id": 77},
                        "date_created": NOW,
                    }
                ],
                "paging": {"total": 1},
            }
        if path == "/messages/packs/555/sellers/123":
            return {
                "messages": [
                    {
                        "id": "msg-1",
                        "from": {"user_id": 1},
                        "to": {"user_id": 2},
                        "text": "hello",
                        "status": "available",
                        "message_date": {"created": NOW, "read": None},
                    }
                ]
            }
        if path == "/shipments/654":
            return {
                "id": 654,
                "order_id": 987,
                "status": "ready_to_ship",
                "logistic_type": "fulfillment",
                "date_created": NOW,
                "last_updated": NOW,
            }
        if path == "/post-purchase/v1/claims/search":
            return {
                "data": [],
                "paging": {"offset": 0, "limit": 100, "total": 0},
            }
        raise AssertionError(f"unexpected gateway path: {path}")


class RecordingStage(BootstrapStage):
    def __init__(self, name: str, cursor: dict[str, Any] | None = None) -> None:
        self.name = name
        self.cursor = cursor or {"page": 1}
        self.calls: list[dict[str, Any]] = []

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        self.calls.append(job.get("checkpoints", {}).get(self.name, {}))
        await state_machine.update_cursor(self.name, self.cursor)


class RecordingPublisher(InMemoryPublisher):
    def __init__(self) -> None:
        super().__init__()
        self.states_at_publish: list[str] = []

    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        self.states_at_publish.append(str(job["state"]))
        await super().publish_bootstrap_completed(job)


@pytest.mark.asyncio
async def test_bootstrap_state_machine_valid_and_invalid_transitions() -> None:
    collection = FakeBootstrapJobs()
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    running = await machine.transition("running")
    assert running["state"] == "running"

    succeeded = await machine.transition("succeeded")
    assert succeeded["state"] == "succeeded"

    with pytest.raises(InvalidTransitionError):
        await machine.transition("running")


@pytest.mark.asyncio
async def test_bootstrap_state_machine_records_cursor_for_crash_resume() -> None:
    collection = FakeBootstrapJobs()
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)
    await machine.transition("running")

    updated = await machine.update_cursor("items", {"scroll_id": "p151", "offset": 150})

    assert updated["current_stage"] == "items"
    assert updated["checkpoints"]["items"] == {"scroll_id": "p151", "offset": 150}


@pytest.mark.asyncio
async def test_bootstrap_dag_runs_in_order_skips_done_and_updates_progress() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    collection.document["dag"] = {"accounts": "done"}
    collection.document["checkpoints"] = {"items": {"scroll_id": "p151"}}
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)
    accounts = RecordingStage("accounts")
    items = RecordingStage("items", {"scroll_id": "p152"})
    orders = RecordingStage("orders", {"cursor": "o1"})
    runner = BootstrapDagRunner(machine, [accounts, items, orders])

    completed = await runner.run()

    assert accounts.calls == []
    assert items.calls == [{"scroll_id": "p151"}]
    assert orders.calls == [{}]
    assert completed["dag"] == {"accounts": "done", "items": "done", "orders": "done"}
    assert completed["checkpoints"]["items"] == {"scroll_id": "p152"}
    assert completed["state"] == "succeeded"


@pytest.mark.asyncio
async def test_default_bootstrap_stages_fetch_paginate_upsert_and_emit_completion_event() -> None:
    collection = FakeBootstrapJobs()
    database = FakeDatabase()
    gateway = FakeGateway()
    publisher = RecordingPublisher()
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)
    runner = BootstrapDagRunner(
        machine, build_default_stages(gateway, database), publisher=publisher
    )

    completed = await runner.run()

    assert completed["state"] == "succeeded"
    assert publisher.states_at_publish == ["running"]
    assert collection.document["dag"] == {
        "accounts": "done",
        "items": "done",
        "orders": "done",
        "questions": "done",
        "messages": "done",
        "shipments": "done",
        "claims": "done",
    }
    assert [call[0] for call in gateway.calls].count("/users/123/items/search") == 2
    assert [filter_spec for filter_spec, _, _ in database["items"].upserts] == [
        {"_id": "MLM1"},
        {"_id": "MLM2"},
        {"_id": "MLM3"},
    ]
    assert database["orders"].upserts[0][0] == {"_id": "987"}
    assert database["orders"].upserts[0][1]["$set"]["meli_pack_id"] == "555"
    assert database["orders"].upserts[0][1]["$set"]["items"] == [
        {"item_id": "MLM1", "qty": 2, "unit_price": "10.00"}
    ]
    assert database["questions"].upserts[0][0] == {"_id": "333"}
    assert ("/questions/search", {"seller_id": "123", "api_version": "4"}) in gateway.calls
    assert (
        "/messages/packs/555/sellers/123",
        {"tag": "post_sale", "mark_as_read": "false"},
    ) in gateway.calls
    assert database["messages"].upserts[0][0] == {"_id": "msg-1"}
    assert database["messages"].upserts[0][1]["$set"]["pack_id"] == "555"
    assert database["messages"].upserts[0][1]["$set"]["order_id"] == "987"
    assert database["messages"].upserts[0][1]["$set"]["from_user_id"] == "1"
    assert database["messages"].upserts[0][1]["$set"]["to_user_id"] == "2"
    assert database["shipments"].upserts[0][0] == {"_id": "654"}
    assert database["claims"].upserts == []
    assert all(
        params != {"order_id": "987"}
        for path, params in gateway.calls
        if path == "/post-purchase/v1/claims/search"
    )
    assert publisher.events == [
        {
            "event_type": "BootstrapCompleted",
            "payload": {"job_id": "job-1", "seller_id": "123"},
        }
    ]


@pytest.mark.asyncio
async def test_claims_stage_persists_hydrated_old_order_with_same_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = DevolucionesOperationContext(
        seller_id="123",
        scope="devoluciones",
        operation_id="bootstrap-claims",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
        source_fingerprint="hydrated-nine",
    )
    projection = {
        "_id": "CLAIM-OLD",
        "seller_id": "123",
        "order_id": "1999",
        "item_id": "MLM1",
        "returned_quantity": 1,
        "claim_version": 9,
        "last_updated": NOW,
        "return_last_updated": NOW,
        "productive": True,
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": NOW,
        "schema_version": 1,
    }
    snapshot = SimpleNamespace(
        projections=(projection,),
        orders=({"id": 1999, "seller": {"id": "123"}, "order_items": []},),
        inventory=VerifiedClaimInventory(entries=(), fingerprint="inventory-nine"),
        source_fingerprint="hydrated-nine",
        read_model_fingerprint="local-proof-nine",
    )
    persistence_calls: list[dict[str, Any]] = []

    async def collect(**kwargs: Any) -> Any:
        del kwargs
        return snapshot

    async def guarded_write(**kwargs: Any) -> None:
        await kwargs["writer"](None)

    class RecordingPersistence:
        def __init__(self, *, db: Any) -> None:
            del db

        async def persist(self, **kwargs: Any) -> None:
            persistence_calls.append(kwargs)

    monkeypatch.setattr(stages_module, "collect_devoluciones_snapshot", collect, raising=False)
    monkeypatch.setattr(
        stages_module,
        "SheetsEventPersistence",
        RecordingPersistence,
        raising=False,
    )
    monkeypatch.setattr("zeler_sheets.claim_projection.guarded_devoluciones_write", guarded_write)
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)
    database = FakeDatabase()

    await ClaimsStage(FakeGateway(), database).run(
        collection.document,
        machine,
        operation=operation,
    )

    assert len(persistence_calls) == 1
    assert persistence_calls[0]["event_type"] == "orders.updated"
    assert persistence_calls[0]["resource"]["id"] == 1999
    assert persistence_calls[0]["operation"] is operation
    assert database["claims"].documents["CLAIM-OLD"]["order_id"] == "1999"


@pytest.mark.asyncio
async def test_accounts_stage_persists_site_id_and_resolved_timezone() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await AccountsStage(gateway, database).run(collection.document, machine)

    filter_spec, update, upsert = database["meli_accounts"].upserts[0]
    assert filter_spec == {"seller_id": "123"}
    assert upsert is True
    assert update["$set"] == {
        "seller_id": "123",
        "nickname": "TEST_SELLER",
        "site_id": "MLM",
        "timezone": "America/Mexico_City",
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_accounts_stage_uses_insert_only_utc_fallback_without_null_overwrite() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/users/123":
            return {"id": 123, "nickname": "TEST_SELLER", "site_id": None}
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await AccountsStage(gateway, database).run(collection.document, machine)

    _, update, _ = database["meli_accounts"].upserts[0]
    assert update["$set"] == {
        "seller_id": "123",
        "nickname": "TEST_SELLER",
        "schema_version": 1,
    }
    assert update["$setOnInsert"] == {"timezone": "UTC"}


def test_order_item_preserves_source_identity_fields_without_synthesizing_absent_values() -> None:
    rich_item = OrderItem.model_validate(
        {
            "item_id": 123,
            "variation_id": 456,
            "sku": "sku-direct",
            "seller_sku": "seller-sku",
            "seller_custom_field": "custom-sku",
            "qty": 2,
            "unit_price": "10.00",
        }
    ).model_dump(mode="json")
    minimal_item = OrderItem.model_validate(
        {"item_id": 789, "qty": 1, "unit_price": "5.00"}
    ).model_dump(mode="json")

    assert rich_item == {
        "item_id": "123",
        "variation_id": "456",
        "sku": "sku-direct",
        "seller_sku": "seller-sku",
        "seller_custom_field": "custom-sku",
        "qty": 2,
        "unit_price": "10.00",
    }
    assert minimal_item == {"item_id": "789", "qty": 1, "unit_price": "5.00"}


@pytest.mark.asyncio
async def test_orders_stage_preserves_variation_and_explicit_sku_fields() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/orders/search":
            return {
                "results": [
                    {
                        "id": 987,
                        "buyer": {"id": 45},
                        "status": "paid",
                        "date_created": NOW,
                        "total_amount": "20.00",
                        "order_items": [
                            {
                                "item": {
                                    "id": "MLM1",
                                    "seller_sku": "nested-seller-sku",
                                    "seller_custom_field": "nested-custom-sku",
                                    "variation_id": 456,
                                },
                                "variation_id": 456,
                                "seller_sku": "line-seller-sku",
                                "sku": "line-sku",
                                "quantity": 2,
                                "unit_price": "10.00",
                            },
                            {"item": {"id": "MLM2"}, "quantity": 1, "unit_price": "5.00"},
                        ],
                    }
                ],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            }
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await OrdersStage(gateway, database).run(collection.document, machine)

    assert database["orders"].upserts[0][1]["$set"]["items"] == [
        {
            "item_id": "MLM1",
            "variation_id": "456",
            "sku": "line-sku",
            "seller_sku": "line-seller-sku",
            "seller_custom_field": "nested-custom-sku",
            "qty": 2,
            "unit_price": "10.00",
        },
        {"item_id": "MLM2", "qty": 1, "unit_price": "5.00"},
    ]


@pytest.mark.asyncio
async def test_orders_stage_persists_realized_sale_fee_metadata() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/orders/search":
            return {
                "results": [
                    {
                        "id": 987,
                        "buyer": {"id": 45},
                        "status": "paid",
                        "date_created": NOW,
                        "date_closed": NOW,
                        "total_amount": "20.00",
                        "order_items": [
                            {
                                "item": {"id": "MLM1", "seller_sku": "sku-1"},
                                "quantity": 2,
                                "unit_price": "10.00",
                                "sale_fee": "4.50",
                            }
                        ],
                    }
                ],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            }
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await OrdersStage(gateway, database).run(collection.document, machine)

    assert database["orders"].upserts[0][1]["$set"]["items"] == [
        {
            "item_id": "MLM1",
            "seller_sku": "sku-1",
            "qty": 2,
            "unit_price": "10.00",
            "sale_fee": "4.50",
            "sale_fee_source": "/orders/{id}",
            "sale_fee_synced_at": "2026-04-24T12:00:00Z",
        }
    ]


@pytest.mark.asyncio
async def test_orders_stage_keeps_message_target_fallback_out_of_displayed_meli_pack_id() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/orders/search":
            return {
                "results": [
                    {
                        "id": 987,
                        "buyer": {"id": 45},
                        "status": "paid",
                        "date_created": NOW,
                        "total_amount": "20.00",
                        "order_items": [
                            {"item": {"id": "MLM1"}, "quantity": 2, "unit_price": "10.00"}
                        ],
                    }
                ],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            }
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await OrdersStage(gateway, database).run(collection.document, machine)

    order_document = database["orders"].upserts[0][1]["$set"]
    assert order_document.get("meli_pack_id") is None
    assert collection.document["checkpoints"]["orders"]["message_targets"] == [
        {"pack_id": "987", "order_id": "987"}
    ]


@pytest.mark.asyncio
async def test_orders_stage_extracts_nested_seller_sku_attributes_without_guessing() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/orders/search":
            return {
                "results": [
                    {
                        "id": 987,
                        "buyer": {"id": 45},
                        "status": "paid",
                        "date_created": NOW,
                        "total_amount": "30.00",
                        "order_items": [
                            {
                                "item": {
                                    "id": "MLM1",
                                    "variation_id": 456,
                                    "variation_attributes": [
                                        {"id": "SELLER_SKU", "value_name": "var-sku"}
                                    ],
                                    "attributes": [{"id": "SELLER_SKU", "value_name": "item-sku"}],
                                },
                                "quantity": 2,
                                "unit_price": "10.00",
                            },
                            {
                                "item": {"id": "MLM2", "attributes": []},
                                "quantity": 1,
                                "unit_price": "5.00",
                            },
                        ],
                    }
                ],
                "paging": {"total": 1, "offset": 0, "limit": 50},
            }
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await OrdersStage(gateway, database).run(collection.document, machine)

    assert database["orders"].upserts[0][1]["$set"]["items"] == [
        {
            "item_id": "MLM1",
            "variation_id": "456",
            "seller_sku": "var-sku",
            "qty": 2,
            "unit_price": "10.00",
        },
        {"item_id": "MLM2", "qty": 1, "unit_price": "5.00"},
    ]


@pytest.mark.asyncio
async def test_items_stage_chunks_item_detail_requests_to_meli_limit() -> None:
    item_ids = [f"MLM{i}" for i in range((MELI_ITEMS_BATCH_SIZE * 2) + 3)]
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/users/123/items/search":
            return {"results": item_ids, "scroll_id": None, "paging": {"total": len(item_ids)}}
        if path == "/items":
            ids = str((params or {}).get("ids", "")).split(",")
            assert len(ids) <= MELI_ITEMS_BATCH_SIZE
            return cast(
                dict[str, Any],
                [
                    {
                        "code": 200,
                        "body": {
                            "id": item_id,
                            "seller_id": "123",
                            "title": f"Item {item_id}",
                            "price": "10.00",
                            "base_price": "10.00",
                            "available_quantity": 5,
                            "status": "active",
                            "category_id": "MLM-CAT",
                            "date_created": NOW,
                            "last_updated": NOW,
                        },
                    }
                    for item_id in ids
                    if item_id
                ],
            )
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ItemsStage(gateway, database).run(collection.document, machine)

    item_calls = [params for path, params in gateway.calls if path == "/items"]
    assert [len(str(params["ids"]).split(",")) for params in item_calls if params] == [20, 20, 3]


@pytest.mark.asyncio
async def test_items_stage_persists_formula_detail_fields_as_schema_v2() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/users/123/items/search":
            return {"results": ["MLM1"], "scroll_id": None, "paging": {"total": 1}}
        if path == "/items":
            return cast(
                dict[str, Any],
                [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLM1",
                            "seller_id": "123",
                            "title": "Item MLM1",
                            "price": "10.00",
                            "base_price": "10.00",
                            "available_quantity": 5,
                            "status": "active",
                            "category_id": "MLM-CAT",
                            "permalink": "https://articulo.example/MLM1",
                            "thumbnail": "https://img.example/MLM1.jpg",
                            "catalog_product_id": "MLM-CATALOG-1",
                            "inventory_id": "ITEM-INV-1",
                            "listing_type_id": "gold_special",
                            "variations": [{"id": 456, "inventory_id": "VAR-INV-456"}],
                            "raw_payload_blob": {"must_not": "be persisted"},
                            "date_created": NOW,
                            "last_updated": NOW,
                        },
                    }
                ],
            )
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ItemsStage(gateway, database).run(collection.document, machine)

    document = database["items"].upserts[0][1]["$set"]
    assert document["schema_version"] == 2
    assert document["permalink"] == "https://articulo.example/MLM1"
    assert document["thumbnail"] == "https://img.example/MLM1.jpg"
    assert document["catalog_product_id"] == "MLM-CATALOG-1"
    assert document["inventory_id"] == "ITEM-INV-1"
    assert document["listing_type_id"] == "gold_special"
    assert document["variations"][0]["inventory_id"] == "VAR-INV-456"
    assert "raw_payload_blob" not in document


@pytest.mark.asyncio
async def test_items_stage_enriches_items_and_populates_formula_rows_for_new_seller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    gateway = FakeGateway()
    monkeypatch.setenv("ZELERDATA_ENRICHMENT_ENABLED", "1")

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/users/123/items/search":
            return {"results": ["MLM1"], "scroll_id": None, "paging": {"total": 1}}
        if path == "/items":
            return cast(
                dict[str, Any],
                [
                    {
                        "code": 200,
                        "body": {
                            "id": "MLM1",
                            "seller_id": "123",
                            "title": "Item MLM1",
                            "price": "10.00",
                            "base_price": "10.00",
                            "available_quantity": 5,
                            "status": "active",
                            "category_id": "MLM-CAT",
                            "site_id": "MLM",
                            "currency_id": "MXN",
                            "listing_type_id": "gold_special",
                            "shipping": {"free_shipping": True, "mode": "me2"},
                            "attributes": [{"id": "SELLER_SKU", "value_name": "sku-1"}],
                            "date_created": NOW,
                            "last_updated": NOW,
                        },
                    }
                ],
            )
        if path == "/users/123/shipping_options/free" and params == {"item_id": "MLM1"}:
            return {"coverage": {"all_country": {"list_cost": "83.25"}}}
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ItemsStage(gateway, database).run(collection.document, machine)

    item = database["items"].documents["MLM1"]
    assert item["seller_shipping_cost"].to_decimal().to_eng_string() == "83.25"
    assert item["enrichment_state"]["seller_shipping_cost"]["status"] == "trusted"
    formula_row = database["sheets_item_formula_rows"].documents["123:SKU-1:MLM1"]
    assert formula_row["current"]["seller_shipping_cost"].to_decimal().to_eng_string() == "83.25"
    assert formula_row["current"]["listing_type_id"] == "gold_special"
    assert ("/users/123/shipping_options/free", {"item_id": "MLM1"}) in gateway.calls


@pytest.mark.asyncio
async def test_shipments_stage_persists_allowlisted_address_and_real_cost_snapshot() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    collection.document["checkpoints"] = {"orders": {"shipment_ids": ["654"]}}
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        if path == "/shipments/654":
            return {
                "id": 654,
                "order_id": 987,
                "status": "ready_to_ship",
                "logistic_type": "fulfillment",
                "date_created": NOW,
                "last_updated": NOW,
                "receiver_address": {
                    "receiver_name": " Safe Buyer ",
                    "street_name": " Safe Street ",
                    "street_number": 123,
                    "city": {"name": " Safe City "},
                    "state": {"name": " Safe State "},
                    "country": {"name": " Safe Country "},
                    "phone": "+54-PII-PHONE",
                    "email": "pii@example.invalid",
                },
                "token": "PII-TOKEN",
            }
        if path == "/shipments/654/costs":
            return {
                "currency_id": "MXN",
                "senders": [{"sender_id": "123", "cost": "24.50"}],
                "receiver": {"cost": "100.00"},
            }
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ShipmentsStage(gateway, database).run(collection.document, machine)

    shipment = database["shipments"].documents["654"]
    assert shipment["receiver_address"] == {
        "name": "Safe Buyer",
        "street_name": "Safe Street",
        "street_number": "123",
        "city": "Safe City",
        "state": "Safe State",
        "country": "Safe Country",
    }
    assert shipment["real_shipping_cost"]["seller_cost"] == "24.50"
    serialized = repr(shipment)
    assert "+54-PII-PHONE" not in serialized
    assert "pii@example.invalid" not in serialized
    assert "PII-TOKEN" not in serialized
    assert ("/shipments/654/costs", None) in gateway.calls


@pytest.mark.asyncio
async def test_messages_stage_skips_missing_pack_conversations() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    collection.document["checkpoints"] = {
        "orders": {"message_targets": [{"pack_id": "555", "order_id": "987"}]}
    }
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        request = httpx.Request("GET", f"https://gateway.zeler.ai{path}")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await MessagesStage(gateway, database).run(collection.document, machine)

    assert gateway.calls == [
        ("/messages/packs/555/sellers/123", {"tag": "post_sale", "mark_as_read": "false"})
    ]
    assert database["messages"].upserts == []
    assert collection.document["checkpoints"]["messages"] == {
        "message_ids": [],
        "missing_packs": ["555"],
    }


@pytest.mark.asyncio
async def test_claims_stage_records_stable_empty_authoritative_inventory() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    collection.document["checkpoints"] = {"orders": {"order_ids": ["987"]}}
    database = FakeDatabase()
    gateway = FakeGateway()

    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ClaimsStage(gateway, database).run(collection.document, machine)

    assert gateway.calls == []
    assert database["claims"].upserts == []
    assert collection.document["checkpoints"]["claims"] == {
        "claim_ids": [],
        "missing_claim_searches": [],
    }


@pytest.mark.asyncio
async def test_claims_stage_root_maintains_heartbeat_until_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        assert len(str(kwargs["operation"].source_fingerprint)) == 64
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    monkeypatch.setattr(stages_module, "maintain_devoluciones_heartbeat", heartbeat)
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"

    await ClaimsStage(FakeGateway(), FakeDatabase()).run(
        collection.document,
        BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW),
    )

    assert calls == ["enter", "exit"]


@pytest.mark.asyncio
async def test_claims_stage_takeover_uses_complete_hydrated_source_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    snapshot = SimpleNamespace(
        projections=(),
        orders=(),
        inventory=VerifiedClaimInventory(entries=(), fingerprint="inventory-only"),
        source_fingerprint="inventory-plus-hydrated-facts",
        read_model_fingerprint="hydrated-facts",
    )

    async def collect(**kwargs: Any) -> Any:
        del kwargs
        return snapshot

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        captured.append(str(kwargs["source_fingerprint"]))
        return DevolucionesOperationContext(
            seller_id="123",
            scope="devoluciones",
            operation_id="bootstrap-claims",
            attempt_token=uuid4().hex,
            fence=1,
            owns_lease=True,
            source_fingerprint=str(kwargs["source_fingerprint"]),
        )

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        del kwargs
        yield

    async def finish(**kwargs: Any) -> None:
        del kwargs

    monkeypatch.setattr(stages_module, "collect_devoluciones_snapshot", collect)
    monkeypatch.setattr(stages_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(stages_module, "maintain_devoluciones_heartbeat", heartbeat)
    monkeypatch.setattr(stages_module, "finish_devoluciones_operation", finish)
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"

    await ClaimsStage(FakeGateway(), FakeDatabase()).run(
        collection.document,
        BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW),
    )

    assert captured == ["inventory-plus-hydrated-facts"]


@pytest.mark.asyncio
async def test_orders_stage_owned_root_fingerprints_heartbeats_and_resumes_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []
    fingerprints: list[str] = []

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        fingerprint = str(kwargs["source_fingerprint"])
        fingerprints.append(fingerprint)
        calls.append(("acquire", fingerprint))
        return DevolucionesOperationContext(
            seller_id="123",
            scope="devoluciones",
            operation_id="bootstrap-orders",
            attempt_token=uuid4().hex,
            fence=1,
            owns_lease=True,
            source_fingerprint=fingerprint,
            checkpoint={"stage": "orders", "order_id": "101"},
        )

    @asynccontextmanager
    async def heartbeat(**kwargs: Any) -> Any:
        calls.append(("heartbeat_enter", kwargs["operation"].operation_id))
        try:
            yield
        finally:
            calls.append(("heartbeat_exit", kwargs["operation"].operation_id))

    async def guarded_write(**kwargs: Any) -> None:
        calls.append(("write", dict(kwargs["checkpoint"])))
        await kwargs["writer"](None)

    async def finish(**kwargs: Any) -> None:
        calls.append(("finish", kwargs["succeeded"]))

    monkeypatch.setattr(stages_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(stages_module, "maintain_devoluciones_heartbeat", heartbeat)
    monkeypatch.setattr(stages_module, "guarded_devoluciones_write", guarded_write)
    monkeypatch.setattr(stages_module, "finish_devoluciones_operation", finish)

    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        assert path == "/orders/search"
        return {
            "results": [
                {
                    "id": order_id,
                    "buyer": {"id": 45},
                    "status": "paid",
                    "date_created": NOW,
                    "last_updated": NOW,
                    "total_amount": "10.00",
                    "order_items": [
                        {"item": {"id": f"MLM{order_id}"}, "quantity": 1, "unit_price": "10"}
                    ],
                }
                for order_id in (101, 102)
            ],
            "paging": {"total": 2, "offset": 0, "limit": 50},
        }

    gateway.get = get  # type: ignore[method-assign]
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    database = FakeDatabase()
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await OrdersStage(gateway, database).run(collection.document, machine)

    assert len(fingerprints) == 1
    assert len(fingerprints[0]) == 64
    assert list(database["orders"].documents) == ["102"]
    assert calls == [
        ("acquire", fingerprints[0]),
        ("heartbeat_enter", "bootstrap-orders"),
        ("write", {"stage": "orders", "order_id": "102"}),
        ("heartbeat_exit", "bootstrap-orders"),
        ("finish", True),
    ]
    assert collection.document["checkpoints"]["orders"]["order_ids"] == ["101", "102"]


def test_orders_stage_rejects_checkpoint_outside_stable_source_inventory() -> None:
    results = [{"id": 101}, {"id": 102}]

    with pytest.raises(DevolucionesLeaseLostError, match="outside source inventory"):
        stages_module._remaining_orders_stage_ids(
            results,
            {"stage": "claims", "order_id": "101"},
        )

    assert stages_module._remaining_orders_stage_ids(
        results,
        {"stage": "orders", "order_id": "101"},
    ) == {"102"}
