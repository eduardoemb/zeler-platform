from __future__ import annotations

import pytest

from zeler_bootstrap import dispatcher as dispatcher_module
from zeler_bootstrap.dispatcher import BootstrapDispatcher

from .test_dispatcher import FakeCloudRunJobsClient, FakeDb


class LogSpy:
    def __init__(self) -> None:
        self.errors: list[tuple[str, dict[str, object]]] = []

    def error(self, event: str, **fields: object) -> None:
        self.errors.append((event, fields))


@pytest.mark.asyncio
async def test_dispatch_failed_after_max_attempts_marks_failed_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDb()
    db["bootstrap_jobs"].docs["job-1"] = {
        "_id": "job-1",
        "seller_id": "123",
        "state": "pending",
        "dispatch_attempts": 3,
    }
    log_spy = LogSpy()
    monkeypatch.setattr(dispatcher_module, "logger", log_spy)

    result = await BootstrapDispatcher(db, FakeCloudRunJobsClient()).handle_accounts_linked(
        {"seller_id": "123"}
    )

    assert result == "failed"
    assert db["bootstrap_jobs"].docs["job-1"]["state"] == "failed"
    assert db["bootstrap_jobs"].docs["job-1"]["last_error"] == "max dispatch attempts exceeded"
    assert log_spy.errors == [
        (
            "bootstrap.dispatch.failed",
            {"seller_id": "123", "attempts": 3, "error": "max dispatch attempts exceeded"},
        )
    ]
