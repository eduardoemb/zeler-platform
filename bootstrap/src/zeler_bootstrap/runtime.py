from __future__ import annotations

import asyncio
import json
import os
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, Self, cast
from urllib.parse import urlsplit

import structlog

from zeler_platform_core.auth.jwt import KmsSigningClient
from zeler_platform_core.auth.meli_gateway_auth import MeliGatewayAuth


class RuntimeConfigError(ValueError):
    pass


class BootstrapPublishError(RuntimeError):
    def __init__(self, *, message_id: str, last_attempt: int, cause: BaseException) -> None:
        super().__init__(
            f"bootstrap publish failed after {last_attempt} attempts (message_id={message_id})"
        )
        self.message_id = message_id
        self.last_attempt = last_attempt
        self.cause = cause


class MongoDatabase(Protocol):
    def __getitem__(self, collection_name: str) -> Any: ...


class MongoClientFactory(Protocol):
    def __call__(self, uri: str) -> Any: ...


class HttpClientFactory(Protocol):
    def __call__(self, *, base_url: str, timeout: float) -> Any: ...


class KmsClientFactory(Protocol):
    def __call__(self) -> KmsSigningClient: ...


_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "BOOTSTRAP_MONGO_URI": ("MONGO_URI",),
    "BOOTSTRAP_MONGO_DB": ("MONGO_DB",),
    "BOOTSTRAP_GATEWAY_BASE_URL": ("GATEWAY_BASE_URL",),
    "BOOTSTRAP_RABBITMQ_URL": ("RABBITMQ_URL",),
}


@dataclass(frozen=True)
class BootstrapRuntimeSettings:
    mongo_uri: str = field(repr=False)
    mongo_db: str
    gateway_base_url: str
    rabbitmq_url: str = field(repr=False)
    gateway_token: str | None = field(default=None, repr=False)
    module_id: str = "bootstrap"
    environment: str = "development"
    rabbitmq_exchange: str = "meli.events"
    gateway_path_prefix: str = "/proxy/meli"
    http_timeout_seconds: float = 30.0
    max_attempts: int = 3
    amqp_publish_max_attempts: int = 3
    amqp_publish_per_attempt_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        environment = _normalize_environment(self.environment)
        object.__setattr__(self, "environment", environment)
        if self.gateway_token and environment == "production":
            msg = "BOOTSTRAP_GATEWAY_TOKEN is not accepted in production; use KMS-signed JWTs"
            raise RuntimeConfigError(msg)

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
        module_id = _read_env(source, "BOOTSTRAP_MODULE_ID", ())
        gateway_token = _read_env(
            source,
            "BOOTSTRAP_GATEWAY_TOKEN",
            ("GATEWAY_TOKEN", "INTERNAL_GATEWAY_TOKEN"),
        )
        environment = _read_env(source, "ENVIRONMENT", ()) or _read_env(source, "ZELER_ENV", ())
        timeout = _read_env(source, "BOOTSTRAP_HTTP_TIMEOUT_SECONDS", ())
        max_attempts = _read_env(source, "BOOTSTRAP_MAX_ATTEMPTS", ())
        amqp_publish_max_attempts = _read_env(source, "BOOTSTRAP_AMQP_PUBLISH_MAX_ATTEMPTS", ())
        amqp_publish_timeout = _read_env(source, "BOOTSTRAP_AMQP_PUBLISH_TIMEOUT_S", ())

        return cls(
            mongo_uri=cast(str, values["BOOTSTRAP_MONGO_URI"]),
            mongo_db=cast(str, values["BOOTSTRAP_MONGO_DB"]),
            gateway_base_url=cast(str, values["BOOTSTRAP_GATEWAY_BASE_URL"]).rstrip("/"),
            gateway_token=gateway_token,
            rabbitmq_url=cast(str, values["BOOTSTRAP_RABBITMQ_URL"]),
            module_id=module_id or "bootstrap",
            environment=environment or "production",
            rabbitmq_exchange=exchange or "meli.events",
            gateway_path_prefix=(path_prefix or "/proxy/meli").rstrip("/"),
            http_timeout_seconds=float(timeout or "30.0"),
            max_attempts=int(max_attempts or "3"),
            amqp_publish_max_attempts=int(amqp_publish_max_attempts or "3"),
            amqp_publish_per_attempt_timeout_s=float(amqp_publish_timeout or "10.0"),
        )


def _read_env(source: Mapping[str, str], name: str, aliases: tuple[str, ...]) -> str | None:
    for candidate in (name, *aliases):
        value = source.get(candidate)
        if value is not None and value.strip():
            return value.strip()
    return None


def _normalize_environment(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized in {"prod", "production"}:
        return "production"
    if normalized == "test":
        return "test"
    return "development"


async def _publish_with_retry(
    *,
    publish_fn: Callable[[str], Awaitable[None]],
    message_id: str,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    factor: float = 2.0,
    jitter_pct: float = 0.2,
    per_sleep_cap: float = 5.0,
    wall_clock_cap: float = 30.0,
    per_attempt_timeout: float = 10.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    jitter: Callable[[], float] = random.random,
) -> None:
    """Publish with bounded retry for transient AMQP failures.

    Retryable failures are aio-pika AMQP exceptions, stdlib ConnectionError, and
    asyncio.TimeoutError. Other exceptions are terminal message/programming errors
    and are wrapped in BootstrapPublishError immediately so callers have one
    uniform publish-failure contract.
    """
    if max_attempts < 1:
        msg = "max_attempts must be at least 1"
        raise ValueError(msg)

    started_at = monotonic()
    last_exception: BaseException | None = None
    log = structlog.get_logger("zeler_bootstrap")
    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.wait_for(publish_fn(message_id), timeout=per_attempt_timeout)
            log.info(
                "bootstrap.amqp.publish_attempt",
                attempt=attempt,
                max_attempts=max_attempts,
                result="ok",
                elapsed_ms=int((monotonic() - started_at) * 1000),
            )
            return
        except BaseException as exc:
            if not _is_retryable_publish_error(exc):
                raise BootstrapPublishError(
                    message_id=message_id,
                    last_attempt=attempt,
                    cause=exc,
                ) from exc
            last_exception = exc
            log.warning(
                "bootstrap.amqp.publish_attempt",
                attempt=attempt,
                max_attempts=max_attempts,
                result="error",
                elapsed_ms=int((monotonic() - started_at) * 1000),
                error_class=type(exc).__name__,
            )
            if attempt >= max_attempts:
                raise BootstrapPublishError(
                    message_id=message_id,
                    last_attempt=attempt,
                    cause=exc,
                ) from exc

            elapsed = monotonic() - started_at
            remaining = wall_clock_cap - elapsed
            if remaining <= 0:
                raise BootstrapPublishError(
                    message_id=message_id,
                    last_attempt=attempt,
                    cause=exc,
                ) from exc

            await sleep(
                min(
                    _retry_delay(attempt, base_delay, factor, jitter_pct, per_sleep_cap, jitter),
                    remaining,
                )
            )

    if last_exception is not None:
        raise BootstrapPublishError(
            message_id=message_id,
            last_attempt=max_attempts,
            cause=last_exception,
        ) from last_exception


def _retry_delay(
    attempt: int,
    base_delay: float,
    factor: float,
    jitter_pct: float,
    per_sleep_cap: float,
    jitter: Callable[[], float],
) -> float:
    raw_delay = base_delay * (factor ** (attempt - 1))
    jitter_multiplier = 1 + ((jitter() * 2) - 1) * jitter_pct
    return min(raw_delay * jitter_multiplier, per_sleep_cap)


def _is_retryable_publish_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | ConnectionError):
        return True

    try:
        from aio_pika.exceptions import AMQPException
    except ImportError:
        return False

    return isinstance(exc, AMQPException)


@dataclass(frozen=True)
class RuntimeDependencies:
    jobs_collection: Any
    database: Any
    gateway: RuntimeGatewayClient
    publisher: AioPikaBootstrapPublisher


class RuntimeGatewayClient:
    def __init__(
        self,
        http_client: Any,
        *,
        token_provider: Callable[[], Awaitable[str]],
        path_prefix: str = "/proxy/meli",
    ) -> None:
        self.http_client = http_client
        self._token_provider = token_provider
        self.path_prefix = path_prefix.rstrip("/")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._token_provider()
        response = await self.http_client.get(
            f"{self.path_prefix}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            msg = f"gateway returned non-object JSON for bootstrap path: {path}"
            raise ValueError(msg)
        return payload


class AioPikaBootstrapPublisher:
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        exchange_name: str = "meli.events",
        amqp_publish_max_attempts: int = 3,
        amqp_publish_per_attempt_timeout_s: float = 10.0,
    ) -> None:
        self.rabbitmq_url = rabbitmq_url
        self.exchange_name = exchange_name
        self.amqp_publish_max_attempts = amqp_publish_max_attempts
        self.amqp_publish_per_attempt_timeout_s = amqp_publish_per_attempt_timeout_s

    async def publish_bootstrap_completed(self, job: dict[str, Any]) -> None:
        if job.get("state") == "failed":
            structlog.get_logger("zeler_bootstrap").info(
                "bootstrap.amqp.publish_skipped",
                job_id=str(job["_id"]),
                state="failed",
                reason="job_already_failed",
            )
            return

        payload = {
            "event_type": "BootstrapCompleted",
            "payload": {"job_id": str(job["_id"]), "seller_id": str(job["seller_id"])},
        }
        message_id = f"bootstrap-completed-{job['_id']}"

        async def publish_attempt(stable_message_id: str) -> None:
            import aio_pika

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
                    message_id=stable_message_id,
                )
                await exchange.publish(message, routing_key="bootstrap.completed")

        await _publish_with_retry(
            publish_fn=publish_attempt,
            message_id=message_id,
            max_attempts=self.amqp_publish_max_attempts,
            per_attempt_timeout=self.amqp_publish_per_attempt_timeout_s,
        )


def build_runtime_dependencies(
    settings: BootstrapRuntimeSettings,
    *,
    seller_id: str,
    mongo_client_factory: MongoClientFactory | None = None,
    http_client_factory: HttpClientFactory | None = None,
    kms_client_factory: KmsClientFactory | None = None,
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
        timeout=settings.http_timeout_seconds,
    )
    token_provider = _build_gateway_token_provider(
        settings=settings,
        seller_id=seller_id,
        kms_client_factory=kms_client_factory,
    )
    gateway = RuntimeGatewayClient(
        http_client,
        token_provider=token_provider,
        path_prefix=settings.gateway_path_prefix,
    )
    publisher = AioPikaBootstrapPublisher(
        rabbitmq_url=settings.rabbitmq_url,
        exchange_name=settings.rabbitmq_exchange,
        amqp_publish_max_attempts=settings.amqp_publish_max_attempts,
        amqp_publish_per_attempt_timeout_s=settings.amqp_publish_per_attempt_timeout_s,
    )
    return RuntimeDependencies(
        jobs_collection=database["bootstrap_jobs"],
        database=database,
        gateway=gateway,
        publisher=publisher,
    )


def _build_gateway_token_provider(
    *,
    settings: BootstrapRuntimeSettings,
    seller_id: str,
    kms_client_factory: KmsClientFactory | None,
) -> Callable[[], Awaitable[str]]:
    if settings.gateway_token is not None:

        async def static_token_provider() -> str:
            return cast(str, settings.gateway_token)

        return static_token_provider

    seller_id_int = int(seller_id)
    if kms_client_factory is None:
        from google.cloud import kms

        resolved_kms_client_factory: KmsClientFactory = kms.KeyManagementServiceClient
    else:
        resolved_kms_client_factory = kms_client_factory

    auth = MeliGatewayAuth(settings.module_id, resolved_kms_client_factory())

    async def jwt_token_provider() -> str:
        return await auth.get_token_for_seller(seller_id_int)

    return jwt_token_provider
