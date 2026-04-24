from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from zeler_bootstrap.runner import BootstrapDagRunner, BootstrapStage
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
        return self.document.copy()


class RecordingStage(BootstrapStage):
    def __init__(self, name: str, cursor: dict[str, Any] | None = None) -> None:
        self.name = name
        self.cursor = cursor or {"page": 1}
        self.calls: list[dict[str, Any]] = []

    async def run(self, job: dict[str, Any], state_machine: BootstrapStateMachine) -> None:
        self.calls.append(job.get("checkpoints", {}).get(self.name, {}))
        await state_machine.update_cursor(self.name, self.cursor)


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
