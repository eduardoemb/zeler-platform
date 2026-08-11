from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from zeler_platform_core.runtime.worker_health import WorkerHealthSidecar


@dataclass
class FakeConsumer:
    is_ready: bool
    last_heartbeat_at: datetime | None


@pytest.mark.asyncio
async def test_sidecar_200_when_ready_and_fresh_heartbeat() -> None:
    consumer = FakeConsumer(is_ready=True, last_heartbeat_at=datetime.now(UTC))
    sidecar = WorkerHealthSidecar(consumer, port=0, staleness_seconds=30)
    await sidecar.start()
    try:
        response = await _get_health(sidecar)
    finally:
        await sidecar.stop()

    assert response.status_code == 200
    assert response.json() == {"ready": True, "checks": {"rabbitmq": "ok"}}


@pytest.mark.asyncio
async def test_sidecar_200_when_ready_idle_without_heartbeat() -> None:
    consumer = FakeConsumer(is_ready=True, last_heartbeat_at=None)
    sidecar = WorkerHealthSidecar(consumer, port=0, staleness_seconds=30)
    await sidecar.start()
    try:
        response = await _get_health(sidecar)
    finally:
        await sidecar.stop()

    assert response.status_code == 200
    assert response.json() == {"ready": True, "checks": {"rabbitmq": "ok"}}


@pytest.mark.asyncio
async def test_sidecar_200_when_ready_with_old_message_heartbeat() -> None:
    consumer = FakeConsumer(
        is_ready=True, last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=31)
    )
    sidecar = WorkerHealthSidecar(consumer, port=0, staleness_seconds=30)
    await sidecar.start()
    try:
        response = await _get_health(sidecar)
    finally:
        await sidecar.stop()

    assert response.status_code == 200
    assert response.json() == {"ready": True, "checks": {"rabbitmq": "ok"}}


@pytest.mark.asyncio
async def test_sidecar_503_when_not_ready() -> None:
    consumer = FakeConsumer(is_ready=False, last_heartbeat_at=datetime.now(UTC))
    sidecar = WorkerHealthSidecar(consumer, port=0, staleness_seconds=30)
    await sidecar.start()
    try:
        response = await _get_health(sidecar)
    finally:
        await sidecar.stop()

    assert response.status_code == 503
    assert response.json() == {
        "ready": False,
        "checks": {"rabbitmq": "error", "reason": "not_ready"},
    }


@pytest.mark.asyncio
async def test_sidecar_component_error_returns_503_then_recovers() -> None:
    consumer = FakeConsumer(is_ready=True, last_heartbeat_at=None)
    poller = {"status": "error"}
    sidecar = WorkerHealthSidecar(
        consumer,
        port=0,
        component_status={"sync_jobs_poller": lambda: poller["status"]},
    )
    await sidecar.start()
    try:
        failed = await _get_health(sidecar)
        poller["status"] = "ok"
        recovered = await _get_health(sidecar)
    finally:
        await sidecar.stop()

    assert failed.status_code == 503
    assert failed.json() == {
        "ready": False,
        "checks": {"rabbitmq": "ok", "sync_jobs_poller": "error"},
    }
    assert recovered.status_code == 200
    assert recovered.json() == {
        "ready": True,
        "checks": {"rabbitmq": "ok", "sync_jobs_poller": "ok"},
    }


async def _get_health(sidecar: WorkerHealthSidecar) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        return await client.get(f"http://127.0.0.1:{sidecar.bound_port}/health")
