from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from zeler_bootstrap.runner import BootstrapDagRunner, BootstrapStage, build_default_stages
from zeler_bootstrap.stages import (
    MELI_ITEMS_BATCH_SIZE,
    BootstrapGatewayClient,
    ClaimsStage,
    InMemoryPublisher,
    ItemsStage,
    MessagesStage,
)
from zeler_bootstrap.state_machine import BootstrapStateMachine, InvalidTransitionError

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


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

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
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

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool
    ) -> None:
        self.upserts.append((filter_spec, update, upsert))


class FakeDatabase(dict[str, FakeCollection]):
    def __getitem__(self, collection_name: str) -> FakeCollection:
        return self.setdefault(collection_name, FakeCollection())


class FakeGateway(BootstrapGatewayClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((path, params))
        if path == "/users/123":
            return {"id": 123, "nickname": "TEST_SELLER"}
        if path == "/users/123/items/search":
            cursor = (params or {}).get("scroll_id")
            if cursor is None:
                return {"results": ["MLM1", "MLM2"], "scroll_id": "p2", "paging": {"total": 3}}
            return {"results": ["MLM3"], "scroll_id": None, "paging": {"total": 3}}
        if path == "/items":
            ids = str((params or {}).get("ids", "")).split(",")
            return [
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
            ]
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
                "data": [
                    {
                        "id": 222,
                        "seller_id": 123,
                        "buyer_id": 45,
                        "resource": "order",
                        "resource_id": 987,
                        "status": "opened",
                        "stage": "claim",
                        "type": "mediations",
                        "date_created": NOW,
                    }
                ]
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
    assert database["claims"].upserts[0][0] == {"_id": "222"}
    assert database["claims"].upserts[0][1]["$set"]["order_id"] == "987"
    assert ("/post-purchase/v1/claims/search", {"order_id": "987"}) in gateway.calls
    assert publisher.events == [
        {
            "event_type": "BootstrapCompleted",
            "payload": {"job_id": "job-1", "seller_id": "123"},
        }
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
            return [
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
            ]
        raise AssertionError(path)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ItemsStage(gateway, database).run(collection.document, machine)

    item_calls = [params for path, params in gateway.calls if path == "/items"]
    assert [len(str(params["ids"]).split(",")) for params in item_calls if params] == [20, 20, 3]


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
async def test_claims_stage_skips_missing_claim_search_results() -> None:
    collection = FakeBootstrapJobs()
    collection.document["state"] = "running"
    collection.document["checkpoints"] = {"orders": {"order_ids": ["987"]}}
    database = FakeDatabase()
    gateway = FakeGateway()

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        gateway.calls.append((path, params))
        request = httpx.Request("GET", f"https://gateway.zeler.ai{path}")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    gateway.get = get  # type: ignore[method-assign]
    machine = BootstrapStateMachine(collection, "job-1", now_fn=lambda: NOW)

    await ClaimsStage(gateway, database).run(collection.document, machine)

    assert gateway.calls == [("/post-purchase/v1/claims/search", {"order_id": "987"})]
    assert database["claims"].upserts == []
    assert collection.document["checkpoints"]["claims"] == {
        "claim_ids": [],
        "missing_claim_searches": ["987"],
    }
