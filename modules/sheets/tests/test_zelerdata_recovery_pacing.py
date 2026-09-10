from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.pacing import (
    DEFAULT_RECOVERY_REQUESTS_PER_MINUTE,
    PacedMeliGateway,
    RecoveryRequestPacer,
    recovery_requests_per_minute,
)

NOW = datetime(2026, 9, 10, 22, 0, tzinfo=UTC)


def test_recovery_requests_per_minute_defaults_to_reserved_share() -> None:
    # The gateway allows 600 requests per minute per module and seller; the
    # agreed reservation leaves roughly 30% to acquisition.
    assert DEFAULT_RECOVERY_REQUESTS_PER_MINUTE == 180
    assert recovery_requests_per_minute(None) == DEFAULT_RECOVERY_REQUESTS_PER_MINUTE
    assert recovery_requests_per_minute("") == DEFAULT_RECOVERY_REQUESTS_PER_MINUTE
    assert recovery_requests_per_minute("120") == 120


@pytest.mark.parametrize("value", ["abc", "0", "-1", "601"])
def test_recovery_requests_per_minute_rejects_out_of_range(value: str) -> None:
    with pytest.raises(ValueError):
        recovery_requests_per_minute(value)


@pytest.mark.asyncio
async def test_pacer_waits_between_requests_beyond_the_budget() -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    clock = [NOW]
    pacer = RecoveryRequestPacer(
        requests_per_minute=2,
        now=lambda: clock[0],
        sleep=sleep,
    )
    assert await pacer.acquire() is False
    assert await pacer.acquire() is False
    assert await pacer.acquire() is True
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_pacer_allows_again_after_the_window_rolls() -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    clock = [NOW]
    pacer = RecoveryRequestPacer(
        requests_per_minute=1,
        now=lambda: clock[0],
        sleep=sleep,
    )
    assert await pacer.acquire() is False
    assert await pacer.acquire() is True
    clock[0] = NOW + timedelta(minutes=1)
    assert await pacer.acquire() is False


@pytest.mark.asyncio
async def test_paced_gateway_applies_pacer_to_request_and_fetch() -> None:
    calls: list[str] = []

    class Inner:
        async def request(self, **kwargs: Any) -> str:
            calls.append("request")
            return "response"

        async def fetch_resource(self, **kwargs: Any) -> dict[str, Any]:
            calls.append("fetch_resource")
            return {"ok": True}

    pacer = RecoveryRequestPacer(requests_per_minute=1, now=lambda: NOW, sleep=_noop)
    gateway = PacedMeliGateway(inner=Inner(), pacer=pacer)

    assert await gateway.request(method="GET", seller_id="1", path="/items") == "response"
    assert await gateway.fetch_resource(seller_id="1", path="/items") == {"ok": True}
    assert calls == ["request", "fetch_resource"]


@pytest.mark.asyncio
async def test_paced_gateway_forwards_unexpected_attributes() -> None:
    class Inner:
        attrs = {"kept": True}

    gateway = PacedMeliGateway(
        inner=Inner(),
        pacer=RecoveryRequestPacer(requests_per_minute=1, now=lambda: NOW, sleep=_noop),
    )
    assert gateway.attrs == {"kept": True}


async def _noop(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_recovery_builder_wraps_gateways_with_the_reserved_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_sheets.consumer import build_formula_recovery_poller

    monkeypatch.setenv("ZELERDATA_RECOVERY_REQUESTS_PER_MINUTE", "120")
    monkeypatch.setenv("ZELERDATA_FORMULA_RECOVERY_SELLERS", "82453304")

    captured: dict[str, Any] = {}

    class _Queue:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["queue_kwargs"] = kwargs

        async def ensure_indexes(self) -> None:
            captured["indexes"] = True

    class _Worker:
        def __init__(self, **kwargs: Any) -> None:
            captured["worker"] = kwargs

    monkeypatch.setattr("zeler_sheets.consumer.FormulaRecoveryQueue", _Queue)
    monkeypatch.setattr("zeler_sheets.consumer.FormulaRecoveryWorker", _Worker)
    monkeypatch.setattr(
        "zeler_sheets.consumer.make_meli_gateway_client",
        lambda **kwargs: _Named("bootstrap"),
    )

    poller = await build_formula_recovery_poller(
        db=object(),
        kms_client=object(),
        detail_gateway=_Named("detail"),
    )

    assert poller is not None
    worker = captured["worker"]
    assert isinstance(worker["gateway"], PacedMeliGateway)
    assert isinstance(worker["detail_gateway"], PacedMeliGateway)
    assert captured["indexes"] is True


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name

    async def request(self, **kwargs: Any) -> Any:
        return self.name

    async def fetch_resource(self, **kwargs: Any) -> Any:
        return {"name": self.name}
