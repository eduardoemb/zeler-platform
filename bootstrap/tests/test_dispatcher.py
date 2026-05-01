from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from zeler_bootstrap.dispatcher import BootstrapDispatcher


class FakeCloudRunJobsClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, str]] = []

    async def run_job(self, *, seller_id: str, job_id: str) -> str:
        self.calls.append({"seller_id": seller_id, "job_id": job_id})
        if self.fail:
            raise RuntimeError("cloud run unavailable")
        return f"executions/{seller_id}-{job_id}"


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, object]] = {}

    async def find_one(self, query: dict[str, object]) -> dict[str, object] | None:
        for doc in self.docs.values():
            if _matches(doc, query):
                return dict(doc)
        return None

    async def find_one_and_update(
        self,
        query: dict[str, object],
        update: dict[str, object],
        **_kwargs: object,
    ) -> dict[str, object] | None:
        doc = await self.find_one(query)
        if doc is None:
            if not _kwargs.get("upsert"):
                return None
            doc = {"_id": query.get("_id")}
            self.docs[str(doc["_id"])] = doc
        stored = self.docs[str(doc["_id"])]
        _apply_update(stored, update)
        return dict(stored)

    async def update_one(self, query: dict[str, object], update: dict[str, object]) -> None:
        doc = await self.find_one(query)
        if doc is not None:
            _apply_update(self.docs[str(doc["_id"])], update)


class FakeDb(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


@pytest.mark.asyncio
async def test_dispatch_calls_cloud_run_jobs_and_marks_running() -> None:
    db = FakeDb()
    db["bootstrap_jobs"].docs["job-1"] = {
        "_id": "job-1",
        "seller_id": "123",
        "state": "pending",
        "dispatch_attempts": 0,
    }
    cloud_run = FakeCloudRunJobsClient()

    result = await BootstrapDispatcher(db, cloud_run).handle_accounts_linked({"seller_id": "123"})

    assert result == "running"
    assert cloud_run.calls == [{"seller_id": "123", "job_id": "job-1"}]
    assert db["bootstrap_jobs"].docs["job-1"]["state"] == "running"
    assert db["bootstrap_jobs"].docs["job-1"]["dispatch_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["running", "dispatched"])
async def test_skips_legacy_dispatched_or_running_jobs(state: str) -> None:
    db = FakeDb()
    db["bootstrap_jobs"].docs["job-1"] = {"_id": "job-1", "seller_id": "123", "state": state}
    cloud_run = FakeCloudRunJobsClient()

    result = await BootstrapDispatcher(db, cloud_run).handle_accounts_linked({"seller_id": "123"})

    assert result == "skipped"
    assert cloud_run.calls == []


@pytest.mark.asyncio
async def test_reverts_state_on_dispatch_failure() -> None:
    db = FakeDb()
    db["bootstrap_jobs"].docs["job-1"] = {
        "_id": "job-1",
        "seller_id": "123",
        "state": "pending",
        "dispatch_attempts": 0,
    }

    with pytest.raises(RuntimeError, match="cloud run unavailable"):
        await BootstrapDispatcher(db, FakeCloudRunJobsClient(fail=True)).handle_accounts_linked(
            {"seller_id": "123"}
        )

    assert db["bootstrap_jobs"].docs["job-1"]["state"] == "pending"
    assert db["bootstrap_dispatcher_locks"].docs["counter"]["count"] == 0


def _matches(doc: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in cast(list[object], expected["$in"]):
                return False
            if "$lt" in expected:
                expected_lt = cast(Any, expected["$lt"])
                actual_lt = cast(Any, actual)
                if actual is None or not actual_lt < expected_lt:
                    return False
        elif actual != expected:
            return False
    return True


def _apply_update(doc: dict[str, object], update: dict[str, object]) -> None:
    set_update = cast(Mapping[str, object], update.get("$set", {}))
    inc_update = cast(Mapping[str, object], update.get("$inc", {}))
    for key, value in set_update.items():
        doc[str(key)] = value
    for key, value in inc_update.items():
        current = cast(int, doc.get(str(key), 0))
        increment = cast(int, value)
        doc[str(key)] = current + increment
