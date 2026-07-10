from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

import aio_pika
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

LIVE_EXCHANGE = "meli.events"
REPLAY_EXCHANGE = "zeler.sheets.replay"
CLAIMS_ROUTING_KEY = "claims.updated"

CLAIMS_QUEUE = "zeler.sheets.claims"
CLAIMS_DLX = f"{CLAIMS_QUEUE}.dlx"
CLAIMS_DLQ = f"{CLAIMS_QUEUE}.dlq"
QUARANTINE_QUEUE = "zeler.sheets.devoluciones.quarantine"

LEGACY_ORDERS_QUEUE = "zeler.sheets.orders"
LEGACY_ORDERS_DLX = f"{LEGACY_ORDERS_QUEUE}.dlx"

RETRY_DELAYS_MS = {
    "1s": 1_000,
    "5s": 5_000,
    "30s": 30_000,
    "2m": 120_000,
    "10m": 600_000,
}

DEFAULT_MANAGEMENT_URL = "http://127.0.0.1:15672"
DEFAULT_DOCKER_SOCKET = Path("/var/run/docker.sock")
SHEETS_WORKER_SERVICE = "sheets-worker"


class TopologySafetyError(RuntimeError):
    """Raised when a topology transition cannot prove its safety gates."""


def resolve_management_url(amqp_url: str, *, explicit_url: str | None) -> str:
    if explicit_url and explicit_url.strip():
        return explicit_url.strip().rstrip("/")
    parsed = urlparse(amqp_url)
    hostname = parsed.hostname
    if not hostname:
        raise TopologySafetyError("broker configuration has no hostname")
    if parsed.scheme == "amqps":
        return f"https://{hostname}"
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return DEFAULT_MANAGEMENT_URL
    return f"http://{hostname}:15672"


@dataclass(frozen=True)
class QueueState:
    ready: int
    unacked: int
    consumers: int


@dataclass(frozen=True)
class TopologyReport:
    command: str
    ok: bool
    read_only: bool
    mutations_attempted: int
    summary: dict[str, int]

    def render_markdown(self) -> str:
        lines = [
            "# Sheets DEVOLUCIONES Topology",
            "",
            f"- command: {self.command}",
            f"- ok: {str(self.ok).lower()}",
            f"- read_only: {str(self.read_only).lower()}",
            f"- mutations_attempted: {self.mutations_attempted}",
            "- secrecy: credentials and message payloads are never rendered.",
            "",
            "## Summary",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.summary.items()))
        return "\n".join(lines) + "\n"


class TopologyBroker(Protocol):
    async def inspect_queue(self, queue_name: str) -> QueueState | None: ...

    async def declare_exchange(self, name: str, exchange_type: str) -> None: ...

    async def declare_queue(self, name: str, arguments: dict[str, object]) -> None: ...

    async def bind(self, exchange: str, queue_name: str, routing_key: str) -> None: ...

    async def unbind(self, exchange: str, queue_name: str, routing_key: str) -> None: ...

    async def get_message(self, queue_name: str) -> Any | None: ...

    async def publish_confirmed(self, queue_name: str, message: Any) -> None: ...

    async def ack(self, message: Any) -> None: ...

    async def delete_queue(self, queue_name: str) -> None: ...

    async def delete_exchange(self, exchange: str) -> None: ...

    async def close(self) -> None: ...


class RuntimeController(Protocol):
    async def worker_is_stopped(self) -> bool: ...

    async def worker_is_healthy(self) -> bool: ...

    async def stop_worker(self) -> None: ...


@dataclass
class _CommandMetrics:
    mutations: int = 0
    drained_messages: int = 0
    deleted_queues: int = 0
    deleted_exchanges: int = 0


def _retry_queue_names(queue_name: str) -> tuple[str, ...]:
    return tuple(f"{queue_name}.retry.{delay}" for delay in RETRY_DELAYS_MS)


def _dedicated_queue_names() -> tuple[str, ...]:
    return CLAIMS_QUEUE, CLAIMS_DLQ, *_retry_queue_names(CLAIMS_QUEUE)


def _rollback_queue_names() -> tuple[str, ...]:
    # Retry queues can expire into the active queue while the worker is stopped.
    # Drain them first and the active queue last so those in-flight expirations
    # are quarantined rather than stranded or dropped.
    return *_retry_queue_names(CLAIMS_QUEUE), CLAIMS_DLQ, CLAIMS_QUEUE


def _legacy_queue_names() -> tuple[str, ...]:
    return (
        LEGACY_ORDERS_QUEUE,
        f"{LEGACY_ORDERS_QUEUE}.dlq",
        *_retry_queue_names(LEGACY_ORDERS_QUEUE),
    )


async def run_topology_command(
    command: str,
    *,
    execute: bool,
    broker: TopologyBroker,
    runtime: RuntimeController,
    stale_readiness: Callable[[], Awaitable[int]] | None = None,
    fence_operations: Callable[[], Awaitable[int]] | None = None,
    delete_dedicated: bool = False,
    failure_triggered: bool = False,
) -> TopologyReport:
    if command == "plan":
        if execute:
            raise TopologySafetyError("plan is read-only and does not accept --execute")
        return await _plan(broker)
    if command not in {"prestart", "bind-claims", "rollback"}:
        raise TopologySafetyError("unsupported topology command")
    if not execute:
        raise TopologySafetyError(f"{command} requires --execute")

    metrics = _CommandMetrics()
    if command == "prestart":
        await _prestart(broker, runtime, metrics)
        summary = _metrics_summary(metrics)
    elif command == "bind-claims":
        await _bind_claims(broker, runtime, metrics)
        summary = _metrics_summary(metrics)
    else:
        if stale_readiness is None:
            raise TopologySafetyError("rollback requires a readiness invalidation provider")
        if fence_operations is None:
            raise TopologySafetyError("rollback requires an operation fencing provider")
        staled, fenced = await _rollback(
            broker,
            runtime,
            stale_readiness=stale_readiness,
            fence_operations=fence_operations,
            delete_dedicated=delete_dedicated,
            metrics=metrics,
        )
        summary = {
            **_metrics_summary(metrics),
            "readiness_markers_staled": staled,
            "operations_fenced": fenced,
            "failure_triggered": int(failure_triggered),
        }
    return TopologyReport(
        command=command,
        ok=True,
        read_only=False,
        mutations_attempted=metrics.mutations,
        summary=summary,
    )


async def _plan(broker: TopologyBroker) -> TopologyReport:
    present = 0
    ready = 0
    unacked = 0
    consumers = 0
    for queue_name in (*_dedicated_queue_names(), *_legacy_queue_names(), QUARANTINE_QUEUE):
        state = await broker.inspect_queue(queue_name)
        if state is None:
            continue
        present += 1
        ready += state.ready
        unacked += state.unacked
        consumers += state.consumers
    return TopologyReport(
        command="plan",
        ok=True,
        read_only=True,
        mutations_attempted=0,
        summary={
            "managed_queues_present": present,
            "managed_messages_ready": ready,
            "managed_messages_unacknowledged": unacked,
            "managed_consumers": consumers,
        },
    )


async def _prestart(
    broker: TopologyBroker,
    runtime: RuntimeController,
    metrics: _CommandMetrics,
) -> None:
    if not await runtime.worker_is_stopped():
        raise TopologySafetyError("sheets worker must be stopped before prestart")

    await _preflight_queues(broker, _legacy_queue_names())
    await _declare_dedicated_resources(broker, metrics)
    await _unbind_claims(broker, metrics)
    claims_state = await broker.inspect_queue(CLAIMS_QUEUE)
    if claims_state is not None:
        _require_no_inflight(CLAIMS_QUEUE, claims_state)

    for exchange in (LIVE_EXCHANGE, REPLAY_EXCHANGE):
        await broker.unbind(exchange, LEGACY_ORDERS_QUEUE, "orders.*")
        metrics.mutations += 1

    existing_queues = await _preflight_queues(broker, _legacy_queue_names())
    for queue_name in existing_queues:
        await _drain_confirmed(broker, queue_name, metrics)
    for queue_name in existing_queues:
        await _require_empty(broker, queue_name)
    for queue_name in existing_queues:
        await broker.delete_queue(queue_name)
        metrics.mutations += 1
        metrics.deleted_queues += 1

    await broker.delete_exchange(LEGACY_ORDERS_DLX)
    metrics.mutations += 1
    metrics.deleted_exchanges += 1


async def _declare_dedicated_resources(
    broker: TopologyBroker,
    metrics: _CommandMetrics,
) -> None:
    await broker.declare_exchange(CLAIMS_DLX, "direct")
    metrics.mutations += 1
    await broker.declare_queue(
        CLAIMS_QUEUE,
        {
            "x-dead-letter-exchange": CLAIMS_DLX,
            "x-dead-letter-routing-key": CLAIMS_DLQ,
        },
    )
    metrics.mutations += 1
    await broker.declare_queue(CLAIMS_DLQ, {})
    metrics.mutations += 1
    await broker.bind(CLAIMS_DLX, CLAIMS_DLQ, CLAIMS_DLQ)
    metrics.mutations += 1
    for delay_name, ttl_ms in RETRY_DELAYS_MS.items():
        await broker.declare_queue(
            f"{CLAIMS_QUEUE}.retry.{delay_name}",
            {
                "x-message-ttl": ttl_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": CLAIMS_QUEUE,
            },
        )
        metrics.mutations += 1
    await broker.declare_queue(QUARANTINE_QUEUE, {})
    metrics.mutations += 1


async def _bind_claims(
    broker: TopologyBroker,
    runtime: RuntimeController,
    metrics: _CommandMetrics,
) -> None:
    if not await runtime.worker_is_healthy():
        raise TopologySafetyError("sheets worker health gate failed")
    state = await broker.inspect_queue(CLAIMS_QUEUE)
    if state is None or state.consumers < 1:
        raise TopologySafetyError("passive claims consumer is not ready")
    for exchange in (LIVE_EXCHANGE, REPLAY_EXCHANGE):
        await broker.bind(exchange, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY)
        metrics.mutations += 1


async def _rollback(
    broker: TopologyBroker,
    runtime: RuntimeController,
    *,
    stale_readiness: Callable[[], Awaitable[int]],
    fence_operations: Callable[[], Awaitable[int]],
    delete_dedicated: bool,
    metrics: _CommandMetrics,
) -> tuple[int, int]:
    first_staled = await stale_readiness()
    metrics.mutations += 1
    await runtime.stop_worker()
    metrics.mutations += 1
    fenced = 0
    try:
        fenced = await fence_operations()
        metrics.mutations += 1
        await _unbind_claims(broker, metrics)

        existing_queues: list[str] = []
        for queue_name in _rollback_queue_names():
            state = await broker.inspect_queue(queue_name)
            if state is None:
                continue
            _require_no_inflight(queue_name, state)
            existing_queues.append(queue_name)

        if existing_queues:
            await broker.declare_queue(QUARANTINE_QUEUE, {})
            metrics.mutations += 1
        for queue_name in existing_queues:
            await _drain_confirmed(broker, queue_name, metrics)
            await _require_empty(broker, queue_name)

        if delete_dedicated:
            for queue_name in existing_queues:
                await broker.delete_queue(queue_name)
                metrics.mutations += 1
                metrics.deleted_queues += 1
            await broker.delete_exchange(CLAIMS_DLX)
            metrics.mutations += 1
            metrics.deleted_exchanges += 1
    finally:
        final_staled = await stale_readiness()
        metrics.mutations += 1
    return first_staled + final_staled, fenced


async def _unbind_claims(broker: TopologyBroker, metrics: _CommandMetrics) -> None:
    for exchange in (LIVE_EXCHANGE, REPLAY_EXCHANGE):
        await broker.unbind(exchange, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY)
        metrics.mutations += 1


async def _preflight_queues(
    broker: TopologyBroker,
    queue_names: tuple[str, ...],
) -> tuple[str, ...]:
    existing: list[str] = []
    unsafe: list[str] = []
    for queue_name in queue_names:
        state = await broker.inspect_queue(queue_name)
        if state is None:
            continue
        existing.append(queue_name)
        if state.unacked:
            unsafe.append(f"{queue_name} has unacknowledged messages")
        if state.consumers:
            unsafe.append(f"{queue_name} still has consumers")
    if unsafe:
        raise TopologySafetyError("; ".join(unsafe))
    return tuple(existing)


def _require_no_inflight(queue_name: str, state: QueueState) -> None:
    if state.unacked:
        raise TopologySafetyError(f"{queue_name} has unacknowledged messages")
    if state.consumers:
        raise TopologySafetyError(f"{queue_name} still has consumers")


async def _require_empty(broker: TopologyBroker, queue_name: str) -> None:
    state = await broker.inspect_queue(queue_name)
    if state is None:
        return
    _require_no_inflight(queue_name, state)
    if state.ready:
        raise TopologySafetyError(f"{queue_name} still has ready messages")


async def _drain_confirmed(
    broker: TopologyBroker,
    queue_name: str,
    metrics: _CommandMetrics,
) -> None:
    while True:
        message = await broker.get_message(queue_name)
        if message is None:
            return
        await broker.publish_confirmed(QUARANTINE_QUEUE, message)
        metrics.mutations += 1
        await broker.ack(message)
        metrics.mutations += 1
        metrics.drained_messages += 1


def _metrics_summary(metrics: _CommandMetrics) -> dict[str, int]:
    return {
        "messages_confirm_drained": metrics.drained_messages,
        "queues_deleted": metrics.deleted_queues,
        "exchanges_deleted": metrics.deleted_exchanges,
    }


class RabbitMqBroker:
    def __init__(
        self,
        *,
        amqp_url: str,
        management_url: str,
    ) -> None:
        parsed = urlparse(amqp_url)
        username = unquote(parsed.username or "guest")
        password = unquote(parsed.password or "guest")
        self._vhost = unquote(parsed.path[1:]) if parsed.path and parsed.path != "/" else "/"
        self._http = httpx.AsyncClient(
            base_url=management_url.rstrip("/"),
            auth=httpx.BasicAuth(username, password),
            timeout=15.0,
        )
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._queues: dict[str, Any] = {}

    @classmethod
    async def connect(cls, *, amqp_url: str, management_url: str) -> RabbitMqBroker:
        broker = cls(amqp_url=amqp_url, management_url=management_url)
        broker._connection = await aio_pika.connect_robust(amqp_url, heartbeat=60)
        broker._channel = await broker._connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        return broker

    @property
    def _encoded_vhost(self) -> str:
        return quote(self._vhost, safe="")

    @staticmethod
    def _encoded(name: str) -> str:
        return quote(name, safe="")

    async def inspect_queue(self, queue_name: str) -> QueueState | None:
        response = await self._http.get(
            f"/api/queues/{self._encoded_vhost}/{self._encoded(queue_name)}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TopologySafetyError("queue inspection returned an invalid response")
        return QueueState(
            ready=int(payload.get("messages_ready", 0)),
            unacked=int(payload.get("messages_unacknowledged", 0)),
            consumers=int(payload.get("consumers", 0)),
        )

    async def declare_exchange(self, name: str, exchange_type: str) -> None:
        response = await self._http.put(
            f"/api/exchanges/{self._encoded_vhost}/{self._encoded(name)}",
            json={"type": exchange_type, "durable": True, "auto_delete": False, "arguments": {}},
        )
        response.raise_for_status()

    async def declare_queue(self, name: str, arguments: dict[str, object]) -> None:
        response = await self._http.put(
            f"/api/queues/{self._encoded_vhost}/{self._encoded(name)}",
            json={"durable": True, "auto_delete": False, "arguments": arguments},
        )
        response.raise_for_status()

    async def bind(self, exchange: str, queue_name: str, routing_key: str) -> None:
        response = await self._http.post(
            f"/api/bindings/{self._encoded_vhost}/e/{self._encoded(exchange)}/q/"
            f"{self._encoded(queue_name)}",
            json={"routing_key": routing_key, "arguments": {}},
        )
        response.raise_for_status()

    async def unbind(self, exchange: str, queue_name: str, routing_key: str) -> None:
        response = await self._http.get(
            f"/api/queues/{self._encoded_vhost}/{self._encoded(queue_name)}/bindings"
        )
        if response.status_code == 404:
            return
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise TopologySafetyError("queue binding inspection returned an invalid response")
        for raw_binding in payload:
            if not isinstance(raw_binding, dict):
                continue
            if (
                raw_binding.get("source") != exchange
                or raw_binding.get("routing_key") != routing_key
            ):
                continue
            properties_key = str(raw_binding.get("properties_key", ""))
            if not properties_key:
                continue
            delete_response = await self._http.delete(
                f"/api/bindings/{self._encoded_vhost}/e/{self._encoded(exchange)}/q/"
                f"{self._encoded(queue_name)}/{self._encoded(properties_key)}"
            )
            if delete_response.status_code != 404:
                delete_response.raise_for_status()

    async def get_message(self, queue_name: str) -> Any | None:
        if self._channel is None:
            raise TopologySafetyError("broker channel is not connected")
        queue = self._queues.get(queue_name)
        if queue is None:
            queue = await self._channel.declare_queue(queue_name, passive=True)
            self._queues[queue_name] = queue
        return await queue.get(fail=False, no_ack=False)

    async def publish_confirmed(self, queue_name: str, message: Any) -> None:
        if self._channel is None:
            raise TopologySafetyError("broker channel is not connected")
        headers = dict(message.headers or {})
        headers["x-zeler-quarantined-from"] = str(message.routing_key or "managed-queue")
        outgoing = aio_pika.Message(
            body=message.body,
            headers=headers,
            content_type=message.content_type,
            content_encoding=message.content_encoding,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            correlation_id=message.correlation_id,
            message_id=message.message_id,
            timestamp=message.timestamp,
            type=message.type,
            app_id=message.app_id,
        )
        confirmed = await self._channel.default_exchange.publish(
            outgoing,
            routing_key=queue_name,
            mandatory=True,
        )
        if confirmed is False:
            raise TopologySafetyError("quarantine publish was not confirmed")

    async def ack(self, message: Any) -> None:
        await message.ack()

    async def delete_queue(self, queue_name: str) -> None:
        response = await self._http.delete(
            f"/api/queues/{self._encoded_vhost}/{self._encoded(queue_name)}",
            params={"if-unused": "true", "if-empty": "true"},
        )
        if response.status_code != 404:
            response.raise_for_status()
        self._queues.pop(queue_name, None)

    async def delete_exchange(self, exchange: str) -> None:
        response = await self._http.delete(
            f"/api/exchanges/{self._encoded_vhost}/{self._encoded(exchange)}",
            params={"if-unused": "true"},
        )
        if response.status_code != 404:
            response.raise_for_status()

    async def close(self) -> None:
        await self._http.aclose()
        if self._connection is not None:
            await self._connection.close()


class DockerEngineRuntime:
    def __init__(self, *, socket_path: Path = DEFAULT_DOCKER_SOCKET) -> None:
        self._socket_path = socket_path

    async def worker_is_stopped(self) -> bool:
        return not any(
            container.get("State") == "running" for container in await self._containers()
        )

    async def worker_is_healthy(self) -> bool:
        containers = [
            container
            for container in await self._containers()
            if container.get("State") == "running"
        ]
        if len(containers) != 1:
            return False
        response = await self._request("GET", f"/containers/{containers[0]['Id']}/json")
        state = response.json().get("State")
        health = state.get("Health") if isinstance(state, dict) else None
        return isinstance(health, dict) and health.get("Status") == "healthy"

    async def stop_worker(self) -> None:
        for container in await self._containers():
            if container.get("State") != "running":
                continue
            await self._request(
                "POST",
                f"/containers/{container['Id']}/stop",
                params={"t": "30"},
                allowed_statuses={204, 304},
            )

    async def _containers(self) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            "/containers/json",
            params={
                "all": "true",
                "filters": json.dumps(
                    {"label": [f"com.docker.compose.service={SHEETS_WORKER_SERVICE}"]}
                ),
            },
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise TopologySafetyError("runtime control response was invalid")
        containers = [
            container
            for container in payload
            if isinstance(container, dict)
            and str(
                container.get("Labels", {}).get("com.docker.compose.oneoff", "False")
            ).casefold()
            != "true"
        ]
        if len(containers) > 1:
            raise TopologySafetyError("runtime control found multiple sheets workers")
        return containers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        allowed_statuses: set[int] | None = None,
    ) -> httpx.Response:
        if not self._socket_path.exists():
            raise TopologySafetyError("runtime control socket is unavailable")
        transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
        async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
            response = await client.request(method, path, params=params)
        if allowed_statuses is not None:
            if response.status_code not in allowed_statuses:
                raise TopologySafetyError("runtime control command failed")
        else:
            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise TopologySafetyError("runtime control command failed") from exc
        return response


async def stale_devoluciones_readiness() -> int:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db:
        raise TopologySafetyError("rollback requires MONGO_URI and MONGO_DB")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        mongo_uri,
        serverSelectionTimeoutMS=5_000,
        connectTimeoutMS=5_000,
        socketTimeoutMS=30_000,
    )
    try:
        result = await client[mongo_db]["sheets_read_model_freshness"].update_many(
            {"read_model": "devoluciones"},
            [
                {
                    "$set": {
                        "state": "stale",
                        "fresh_until": "$$NOW",
                        "valid_until": "$$NOW",
                        "updated_at": "$$NOW",
                        "source": "devoluciones_topology_rollback",
                    }
                }
            ],
        )
        return int(result.modified_count)
    finally:
        client.close()


async def fence_active_devoluciones_operations() -> int:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db:
        raise TopologySafetyError("rollback requires MONGO_URI and MONGO_DB")
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        mongo_uri,
        serverSelectionTimeoutMS=5_000,
        connectTimeoutMS=5_000,
        socketTimeoutMS=30_000,
    )
    try:
        result = await client[mongo_db]["sheets_devoluciones_operations"].update_many(
            {"scope": "devoluciones", "state": "running"},
            [
                {
                    "$set": {
                        "state": "failed",
                        "fence": {"$add": ["$fence", 1]},
                        "lease_until": "$$NOW",
                        "heartbeat_at": "$$NOW",
                        "updated_at": "$$NOW",
                        "finished_at": "$$NOW",
                        "error_code": "topology_rollback_fenced",
                    }
                }
            ],
        )
        return int(result.modified_count)
    finally:
        client.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely manage the Sheets claims cutover.")
    parser.add_argument("command", choices=("plan", "prestart", "bind-claims", "rollback"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--delete-dedicated", action="store_true")
    parser.add_argument("--failure-triggered", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    amqp_url = os.environ.get("RABBITMQ_URL")
    if not amqp_url:
        _render_error(args.format, "missing_broker_configuration")
        return 2
    broker: RabbitMqBroker | None = None
    cleanup_started = False
    try:
        broker = await RabbitMqBroker.connect(
            amqp_url=amqp_url,
            management_url=resolve_management_url(
                amqp_url,
                explicit_url=os.environ.get("RABBITMQ_MANAGEMENT_URL"),
            ),
        )
        report = await run_topology_command(
            args.command,
            execute=bool(args.execute),
            delete_dedicated=bool(args.delete_dedicated),
            failure_triggered=bool(args.failure_triggered),
            broker=broker,
            runtime=DockerEngineRuntime(
                socket_path=Path(os.environ.get("ZELER_DOCKER_SOCKET", DEFAULT_DOCKER_SOCKET))
            ),
            stale_readiness=(stale_devoluciones_readiness if args.command == "rollback" else None),
            fence_operations=(
                fence_active_devoluciones_operations if args.command == "rollback" else None
            ),
        )
        cleanup_started = True
        await broker.close()
        broker = None
    except Exception:  # noqa: BLE001 - sanitize every CLI boundary failure.
        if broker is not None and not cleanup_started:
            with suppress(Exception):  # Cleanup details must stay sanitized.
                await broker.close()
        _render_error(args.format, "topology_safety_gate_failed")
        return 1
    if args.format == "json":
        print(json.dumps(asdict(report), indent=2), end="\n")
    else:
        print(report.render_markdown(), end="")
    return 0


def _render_error(output_format: str, error_code: str) -> None:
    if output_format == "json":
        print(json.dumps({"ok": False, "error_code": error_code}, indent=2), end="\n")
    else:
        print(
            "# Sheets DEVOLUCIONES Topology\n\n"
            "- ok: false\n"
            f"- error_code: {error_code}\n"
            "- secrecy: credentials and message payloads are never rendered.\n",
            end="",
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
