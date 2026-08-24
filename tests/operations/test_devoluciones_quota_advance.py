from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from infra.operations import devoluciones_quota_advance as advance_module

from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext

RUN_ID = "a" * 64


def _run(state: str = "authorized") -> dict[str, Any]:
    return {
        "_id": RUN_ID,
        "seller_id": "82453304",
        "scope": "devoluciones",
        "state": state,
    }


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        fence=3,
        owns_lease=True,
    )


class RunCollection:
    def __init__(self, *documents: dict[str, Any]) -> None:
        self.documents = list(documents)

    async def find_one(self, _: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.pop(0) if self.documents else None


class Database:
    def __init__(self, *documents: dict[str, Any]) -> None:
        self.runs = RunCollection(*documents)

    def __getitem__(self, name: str) -> RunCollection:
        assert name == "sheets_devoluciones_runs"
        return self.runs


@pytest.mark.asyncio
async def test_completed_run_is_a_noop_without_acquiring_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected(**_: Any) -> None:
        raise AssertionError("completed run must not acquire a lease")

    monkeypatch.setattr(advance_module, "acquire_devoluciones_operation", unexpected)

    outcome = await advance_module.advance_authorized_quota_run(
        db=Database(_run("completed")),
        run_id=RUN_ID,
        now=lambda: datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert outcome == {"advanced": 0, "finalized": 0}


@pytest.mark.asyncio
async def test_active_run_uses_root_operation_for_window_and_full_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation()
    events: list[tuple[str, Any]] = []

    async def acquire(**kwargs: Any) -> DevolucionesOperationContext:
        events.append(("acquire", kwargs))
        return operation

    async def execute(**kwargs: Any) -> dict[str, Any]:
        events.append(("execute", kwargs))
        return {"window": True}

    async def readback(**kwargs: Any) -> dict[str, Any]:
        events.append(("readback", kwargs))
        return {"range": True}

    async def advance(**kwargs: Any) -> dict[str, int]:
        assert await kwargs["source"](window={"start": 1, "end": 2}) == {"window": True}
        assert await kwargs["readback"](run={"_id": RUN_ID}, windows=[]) == {"range": True}
        return {"advanced": 1, "finalized": 0}

    async def finish(**kwargs: Any) -> None:
        events.append(("finish", kwargs))

    monkeypatch.setattr(advance_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(advance_module, "execute_devoluciones_quota_window", execute)
    monkeypatch.setattr(advance_module, "readback_devoluciones_quota_run", readback)
    monkeypatch.setattr(advance_module, "advance_devoluciones_quota_run", advance)
    monkeypatch.setattr(advance_module, "finish_devoluciones_operation", finish)

    outcome = await advance_module.advance_authorized_quota_run(
        db=Database(_run(), _run("active")),
        run_id=RUN_ID,
        now=lambda: datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert outcome == {"advanced": 1, "finalized": 0}
    assert [event[0] for event in events] == ["acquire", "execute", "readback", "finish"]
    assert events[1][1]["operation"] is operation
    assert events[3][1]["succeeded"] is True


@pytest.mark.asyncio
async def test_failed_run_releases_operation_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finishes: list[dict[str, Any]] = []

    async def acquire(**_: Any) -> DevolucionesOperationContext:
        return _operation()

    async def advance(**_: Any) -> dict[str, int]:
        return {"advanced": 0, "finalized": 0}

    async def finish(**kwargs: Any) -> None:
        finishes.append(kwargs)

    monkeypatch.setattr(advance_module, "acquire_devoluciones_operation", acquire)
    monkeypatch.setattr(advance_module, "advance_devoluciones_quota_run", advance)
    monkeypatch.setattr(advance_module, "finish_devoluciones_operation", finish)

    with pytest.raises(RuntimeError, match="quota run failed"):
        await advance_module.advance_authorized_quota_run(
            db=Database(_run(), _run("failed")),
            run_id=RUN_ID,
            now=lambda: datetime(2026, 6, 1, tzinfo=UTC),
        )

    assert finishes[0]["succeeded"] is False
    assert finishes[0]["error_code"] == "quota_run_advancement_failed"


def test_cli_rejects_missing_or_malformed_run_id() -> None:
    with pytest.raises(SystemExit):
        advance_module.main([])
    with pytest.raises(SystemExit, match="quota_run_advancement_failed"):
        advance_module.main(["--run-id", "not-a-run-id"])


@pytest.mark.asyncio
async def test_full_range_readback_counts_exact_complete_claims() -> None:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 21, tzinfo=UTC)
    filters: list[dict[str, Any]] = []

    class Claims:
        async def count_documents(self, filter_spec: dict[str, Any]) -> int:
            filters.append(filter_spec)
            return 3

    class ClaimsDatabase:
        def __getitem__(self, name: str) -> Claims:
            assert name == "claims"
            return Claims()

    windows = [
        {
            "expected_count": count,
            "source_fingerprint": f"source-{index}",
            "read_model_fingerprint": f"read-{index}",
        }
        for index, count in enumerate((1, 2))
    ]

    proof = await advance_module.readback_devoluciones_quota_run(
        db=ClaimsDatabase(),
        run={"seller_id": "82453304", "start": start, "end": end},
        windows=windows,
    )

    assert proof["expected_count"] == proof["persisted_count"] == proof["complete_count"] == 3
    assert proof["missing_count"] == 0
    assert proof["start"] == start
    assert proof["end"] == end
    assert filters[0] == {
        "seller_id": "82453304",
        "date_created": {"$gte": start, "$lt": end},
    }
    assert filters[1]["$or"] == [
        {
            "productive": True,
            "returned_quantity": {"$gte": 1},
            "return_quantity_basis": "v2_return_order",
        }
    ]
