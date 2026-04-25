from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, Self, cast
from urllib.parse import urlsplit


class RuntimeConfigError(ValueError):
    pass


class MongoDatabase(Protocol):
    def __getitem__(self, collection_name: str) -> Any: ...


class MongoClientFactory(Protocol):
    def __call__(self, uri: str) -> Any: ...


class HttpClientFactory(Protocol):
    def __call__(self, *, base_url: str, headers: dict[str, str], timeout: float) -> Any: ...


_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "BOOTSTRAP_MONGO_URI": ("MONGO_URI",),
    "BOOTSTRAP_MONGO_DB": ("MONGO_DB",),
    "BOOTSTRAP_GATEWAY_BASE_URL": ("GATEWAY_BASE_URL",),
    "BOOTSTRAP_GATEWAY_TOKEN": ("GATEWAY_TOKEN", "INTERNAL_GATEWAY_TOKEN"),
    "BOOTSTRAP_RABBITMQ_URL": ("RABBITMQ_URL",),
}


@dataclass(frozen=True)
class BootstrapRuntimeSettings:
    mongo_uri: str = field(repr=False)
    mongo_db: str
    gateway_base_url: str
    gateway_token: str = field(repr=False)
    rabbitmq_url: str = field(repr=False)
    rabbitmq_exchange: str = "meli.events"
    gateway_path_prefix: str = "/proxy/meli"
    http_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.mongo_db:
            return

        uri_path = urlsplit(self.mongo_uri).path.lstrip("/")
        if uri_path and uri_path != self.mongo_db:
            msg = f"MONGO_URI path '{uri_path}' does not match MONGO_DB '{self.mongo_db}'"
            raise RuntimeConfigError(msg)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        source = env or os.environ
        values = {name: _read_env(source, name, aliases) for name, aliases in _ENV_ALIASES.items()}
        missing = [name for name, value in values.items() if value is None]
        if missing:
            accepted = [
                f"{name}" + (f" (or {', '.join(_ENV_ALIASES[name])})" if _ENV_ALIASES[name] else "")
                for name in missing
            ]
            msg = "missing bootstrap runtime configuration: " + ", ".join(accepted)
            raise RuntimeConfigError(msg)

        exchange = _read_env(
            source,
            "BOOTSTRAP_RABBITMQ_EXCHANGE",
            ("RABBITMQ_EVENTS_EXCHANGE",),
        )
        path_prefix = _read_env(source, "BOOTSTRAP_GATEWAY_PATH_PREFIX", ())
        timeout = _read_env(source, "BOOTSTRAP_HTTP_TIMEOUT_SECONDS", ())

        return cls(
            mongo_uri=cast(str, values["BOOTSTRAP_MONGO_URI"]),
            mongo_db=cast(str, values["BOOTSTRAP_MONGO_DB"]),
            gateway_base_url=cast(str, values["BOOTSTRAP_GATEWAY_BASE_URL"]).rstrip("/"),
            gateway_token=cast(str, values["BOOTSTRAP_GATEWAY_TOKEN"]),
            rabbitmq_url=cast(str, values["BOOTSTRAP_RABBITMQ_URL"]),
            rabbitmq_exchange=exchange or "meli.events",
            gateway_path_prefix=(path_prefix or "/proxy/meli").rstrip("/"),
            http_timeout_seconds=float(timeout or "30.0"),
        )


def _read_env(source: Mapping[str, str], name: str, aliases: tuple[str, ...]) -> str | None:
    for candidate in (name, *aliases):
        value = source.get(candidate)
        if value is not None and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True)
class RuntimeDependencies:
    jobs_collection: Any
    database: Any
    gateway: RuntimeGatewayClient
    publisher: AioPikaBootstrapPublisher


class RuntimeGatewayClient:
    def __init__(self, http_client: Any, *, path_prefix: str = "/proxy/meli") -> None:
        self.http_client = http_client
        self.path_prefix = path_prefix.rstrip("/")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.http_client.get(f"{self.path_prefix}{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            msg = f"gateway returned non-object JSON for bootstrap path: {path}"
            raise ValueError(msg)
        return payload


class AioPikaBootstrapPublisher:
    def __init__(self, *, rabbitmq_url: str, exchange_name: str = "meli.events") -> None:
        self.rabbitmq_url = rabbitmq_url
        self.exchange_name = exchange_name

    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        import aio_pika

        payload = {
            "event_type": "BootstrapCompleted",
            "payload": {"job_id": str(job["_id"]), "seller_id": str(job["seller_id"])},
        }
        connection = await aio_pika.connect_robust(self.rabbitmq_url)
        async with connection:
            channel = await connection.channel(publisher_confirms=True)
            exchange = await channel.declare_exchange(
                self.exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            message = aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=f"bootstrap-completed-{job['_id']}",
            )
            await exchange.publish(message, routing_key="bootstrap.completed")


def build_runtime_dependencies(
    settings: BootstrapRuntimeSettings,
    *,
    mongo_client_factory: MongoClientFactory | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> RuntimeDependencies:
    if mongo_client_factory is None:
        from motor.motor_asyncio import AsyncIOMotorClient

        resolved_mongo_client_factory: MongoClientFactory = cast(
            MongoClientFactory, AsyncIOMotorClient
        )
    else:
        resolved_mongo_client_factory = mongo_client_factory

    if http_client_factory is None:
        import httpx

        resolved_http_client_factory: HttpClientFactory = httpx.AsyncClient
    else:
        resolved_http_client_factory = http_client_factory

    mongo_client = resolved_mongo_client_factory(settings.mongo_uri)
    database = mongo_client[settings.mongo_db]
    http_client = resolved_http_client_factory(
        base_url=settings.gateway_base_url,
        headers={"Authorization": f"Bearer {settings.gateway_token}"},
        timeout=settings.http_timeout_seconds,
    )
    gateway = RuntimeGatewayClient(http_client, path_prefix=settings.gateway_path_prefix)
    publisher = AioPikaBootstrapPublisher(
        rabbitmq_url=settings.rabbitmq_url,
        exchange_name=settings.rabbitmq_exchange,
    )
    return RuntimeDependencies(
        jobs_collection=database["bootstrap_jobs"],
        database=database,
        gateway=gateway,
        publisher=publisher,
    )
