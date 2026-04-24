from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol


class InvalidTransitionError(ValueError):
    pass


class BootstrapJobsCollection(Protocol):
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...

    async def find_one_and_update(
        self,
        filter_spec: dict[str, Any],
        update: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"paused", "succeeded", "failed", "cancelled"},
    "paused": {"running", "cancelled"},
    "failed": {"pending", "cancelled"},
    "succeeded": set(),
    "cancelled": set(),
}


class BootstrapStateMachine:
    def __init__(
        self,
        collection: BootstrapJobsCollection,
        job_id: str,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.collection = collection
        self.job_id = job_id
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    async def load(self) -> dict[str, Any]:
        document = await self.collection.find_one({"_id": self.job_id})
        if document is None:
            msg = f"bootstrap job not found: {self.job_id}"
            raise KeyError(msg)
        return document

    async def transition(self, new_state: str) -> dict[str, Any]:
        current = await self.load()
        current_state = str(current["state"])
        if new_state not in ALLOWED_TRANSITIONS[current_state]:
            msg = f"invalid bootstrap transition: {current_state} -> {new_state}"
            raise InvalidTransitionError(msg)

        now = self._now_fn()
        update: dict[str, Any] = {"state": new_state, "updated_at": now}
        if new_state == "running" and current.get("started_at") is None:
            update["started_at"] = now
        if new_state in {"succeeded", "failed", "cancelled"}:
            update["finished_at"] = now

        updated = await self.collection.find_one_and_update(
            {"_id": self.job_id, "state": current_state}, {"$set": update}
        )
        if updated is None:
            msg = f"bootstrap transition raced: {current_state} -> {new_state}"
            raise InvalidTransitionError(msg)
        return updated

    async def update_cursor(self, stage: str, cursor_data: dict[str, Any]) -> dict[str, Any]:
        updated = await self.collection.find_one_and_update(
            {"_id": self.job_id, "state": {"$in": ["running", "paused", "failed"]}},
            {
                "$set": {
                    "current_stage": stage,
                    f"checkpoints.{stage}": cursor_data,
                    "updated_at": self._now_fn(),
                }
            },
        )
        if updated is None:
            msg = f"cannot update cursor unless job is active: {self.job_id}"
            raise InvalidTransitionError(msg)
        return updated

    async def mark_stage_done(self, stage: str) -> dict[str, Any]:
        updated = await self.collection.find_one_and_update(
            {"_id": self.job_id, "state": "running"},
            {
                "$set": {
                    f"dag.{stage}": "done",
                    "current_stage": stage,
                    "updated_at": self._now_fn(),
                }
            },
        )
        if updated is None:
            msg = f"cannot mark stage done unless job is running: {self.job_id}"
            raise InvalidTransitionError(msg)
        return updated
