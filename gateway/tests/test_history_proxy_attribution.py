"""History trace is bounded nonsecret metadata inside authenticated proxy audit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from zeler_gateway.proxy.router import _write_audit_log

TRACE = "h1-" + "a" * 32 + ":orders:initial"


class Audit:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.docs.append(document)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "tag", "expected"),
    [
        ("bootstrap", TRACE, TRACE),
        ("sheets", TRACE, TRACE),
        ("repricer", TRACE, None),
        ("sheets", "secret-invalid-marker", None),
        ("sheets", "h1-" + "a" * 32 + ":full_withdrawals:initial", None),
    ],
)
async def test_authenticated_history_audit_trace_is_scoped_and_sanitized(
    module: str, tag: str, expected: str | None
) -> None:
    collection = Audit()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy/meli/orders/1",
            "headers": [
                (b"x-zeler-history-trace", tag.encode()),
                (b"x-zeler-proxy-retry", b"disabled"),
            ],
            "app": SimpleNamespace(state=SimpleNamespace(mongo_db={"audit_log": collection})),
        }
    )
    await _write_audit_log(
        request=request,
        module_id=module,
        seller_id=82453304,
        method="GET",
        path="/orders/1",
        upstream_status=502,
        duration_ms=1,
    )
    assert collection.docs[0].get("trace_id") == expected
    assert collection.docs[0]["upstream_status"] == 502


@pytest.mark.asyncio
async def test_history_deadline_rechecked_after_durable_send_reservation() -> None:
    from datetime import UTC, datetime, timedelta

    from zeler_gateway.proxy.router import HistoryPolicyRejectedError, _reserve_history_send

    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    times = iter((now, now + timedelta(seconds=2)))

    class Reservations:
        async def update_one(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(modified_count=1)

        async def find_one_and_update(self, *args: Any, **kwargs: Any) -> Any:
            return {"execution_until": now + timedelta(seconds=1)}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy/meli/orders/1",
            "headers": [
                (b"x-zeler-history-trace", TRACE.encode()),
                (b"x-zeler-proxy-retry", b"disabled"),
            ],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    mongo_db={"sheets_history_backfill_plans": Reservations()},
                    proxy_wait_now=lambda: next(times),
                )
            ),
        }
    )
    request.state.history_module_id = "sheets"
    request.state.history_seller_id = "82453304"
    with pytest.raises(HistoryPolicyRejectedError):
        await _reserve_history_send(request, "orders/1")
    assert getattr(request.state, "history_upstream_attempts", 0) == 0


@pytest.mark.asyncio
async def test_work_reference_uses_owned_atomic_reservation_and_never_reaches_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta

    import zeler_gateway.proxy.router as proxy

    now = datetime(2026, 10, 5, 20, tzinfo=UTC)
    calls: list[Any] = []

    async def reserve(db: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return {
            "execution_until": now + timedelta(minutes=1),
            "execution_utc_day": "2026-10-05",
            "execution_consumed": 1,
            "execution_attempt_limit": 1,
        }

    monkeypatch.setattr(proxy, "reserve_history_work_send", reserve, raising=False)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy/meli/orders/42",
            "headers": [
                (b"x-zeler-history-trace", ("h1-" + "a" * 32 + ":orders:maintenance").encode()),
                (b"x-zeler-proxy-retry", b"disabled"),
                (b"x-zeler-history-work", ("b" * 32).encode()),
            ],
            "app": SimpleNamespace(
                state=SimpleNamespace(mongo_db=object(), proxy_wait_now=lambda: now)
            ),
        }
    )
    request.state.history_module_id = "sheets"
    request.state.history_seller_id = "82"
    await proxy._reserve_history_send(request, "orders/42")
    assert calls == [
        {
            "seller_id": "82",
            "execution": "a" * 32,
            "source": "orders",
            "phase": "maintenance",
            "work_id": "b" * 32,
            "path": "/orders/42",
            "now": now,
        }
    ]
    assert request.state.history_upstream_attempts == 1
    headers = proxy._upstream_headers(request, access_token="synthetic-only")  # noqa: S106
    assert "x-zeler-history-work" not in {key.lower() for key in headers}


@pytest.mark.asyncio
@pytest.mark.parametrize("work", ["free-source:orders", "", "b" * 31])
async def test_invalid_work_reference_cannot_fall_back_to_fungible_h1_credit(work: str) -> None:
    from zeler_gateway.proxy.router import HistoryPolicyRejectedError, _reserve_history_send

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/proxy/meli/orders/42",
            "headers": [
                (b"x-zeler-history-trace", ("h1-" + "a" * 32 + ":orders:maintenance").encode()),
                (b"x-zeler-proxy-retry", b"disabled"),
                (b"x-zeler-history-work", work.encode()),
            ],
            "app": SimpleNamespace(state=SimpleNamespace(mongo_db=object())),
        }
    )
    request.state.history_module_id = "sheets"
    request.state.history_seller_id = "82"
    with pytest.raises(HistoryPolicyRejectedError):
        await _reserve_history_send(request, "orders/42")
    assert not hasattr(request.state, "history_upstream_attempts")
