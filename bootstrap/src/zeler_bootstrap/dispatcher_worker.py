from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self
from urllib.parse import unquote, urlsplit

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_bootstrap.accounts_consumer import BootstrapAccountsConsumer
from zeler_bootstrap.cloud_run_jobs_client import CloudRunJobsClient
from zeler_bootstrap.dispatcher import BootstrapDispatcher
from zeler_platform_core.observability.logging import configure_logging
from zeler_platform_core.runtime.worker_health import WorkerHealthSidecar


@dataclass(frozen=True)
class DispatcherSettings:
    mongo_uri: str = field(repr=False)
    mongo_db: str
    rabbitmq_url: str = field(repr=False)
    project: str
    region: str
    job_name: str
    health_port: int = 8080

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        source = os.environ if env is None else env
        required = (
            "MONGO_URI",
            "MONGO_DB",
            "RABBITMQ_URL",
            "GCP_PROJECT_ID",
            "BOOTSTRAP_DISPATCH_REGION",
            "BOOTSTRAP_CLOUD_RUN_JOB",
        )
        missing = [name for name in required if not source.get(name, "").strip()]
        if missing:
            raise ValueError("missing dispatcher configuration: " + ", ".join(missing))
        mongo_path = unquote(urlsplit(source["MONGO_URI"].strip()).path.lstrip("/"))
        if mongo_path and mongo_path != source["MONGO_DB"].strip():
            raise ValueError("MONGO_URI database does not match MONGO_DB")
        health_port = int(source.get("WORKER_HEALTH_PORT", "8080"))
        if not 0 < health_port < 65536:
            raise ValueError("WORKER_HEALTH_PORT must be a valid port")
        return cls(
            mongo_uri=source["MONGO_URI"].strip(),
            mongo_db=source["MONGO_DB"].strip(),
            rabbitmq_url=source["RABBITMQ_URL"].strip(),
            project=source["GCP_PROJECT_ID"].strip(),
            region=source["BOOTSTRAP_DISPATCH_REGION"].strip(),
            job_name=source["BOOTSTRAP_CLOUD_RUN_JOB"].strip(),
            health_port=health_port,
        )


class MongoHeartbeat:
    def __init__(self, db: Any) -> None:
        self._db = db
        self.status = "error"

    async def check_once(self) -> None:
        try:
            await self._db.command("ping")
        except Exception:  # noqa: BLE001 - dependency probe must turn any failure into 503.
            self.status = "error"
        else:
            self.status = "ok"

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.check_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=10)
            except TimeoutError:
                continue


async def run_worker(
    settings: DispatcherSettings, *, stop_event: asyncio.Event | None = None
) -> None:
    shutdown = stop_event or asyncio.Event()
    if stop_event is None:
        loop = asyncio.get_running_loop()
        for watched_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(watched_signal, shutdown.set)

    mongo_client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
    )
    db = mongo_client[settings.mongo_db]
    mongo_probe = MongoHeartbeat(db)
    try:
        await mongo_probe.check_once()
        if mongo_probe.status != "ok":
            raise RuntimeError("bootstrap dispatcher Mongo is unavailable")

        async with httpx.AsyncClient(timeout=30) as http_client:
            cloud_run = CloudRunJobsClient(
                project=settings.project,
                location=settings.region,
                job_name=settings.job_name,
                http_client=http_client,
            )
            consumer = BootstrapAccountsConsumer(
                settings.rabbitmq_url, BootstrapDispatcher(db, cloud_run)
            )
            sidecar = WorkerHealthSidecar(
                consumer,
                port=settings.health_port,
                component_status={"mongo": lambda: mongo_probe.status},
            )
            await consumer.start()
            try:
                await sidecar.start()
                probe_task = asyncio.create_task(mongo_probe.run(shutdown))
                try:
                    await shutdown.wait()
                finally:
                    shutdown.set()
                    await probe_task
                    await sidecar.stop()
            finally:
                await consumer.close()
    finally:
        mongo_client.close()


def main() -> None:
    configure_logging("production")
    asyncio.run(run_worker(DispatcherSettings.from_env()))


if __name__ == "__main__":
    main()
