from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

MODULES = ("repricer", "sheets", "publicador", "autoreply")
DEFAULT_MONGO_URI = "mongodb://localhost:27017/zeler_platform"
DEFAULT_RABBITMQ_MANAGEMENT_URL = "http://localhost:15672"
DEFAULT_GATEWAY_URL = "http://localhost:8000"


@dataclass(frozen=True)
class RabbitWorkerTopology:
    queue: str
    dlq: str


RABBITMQ_WORKER_TOPOLOGY: dict[str, RabbitWorkerTopology | None] = {
    "repricer": RabbitWorkerTopology("zeler.repricer.items", "zeler.repricer.items.dlq"),
    "sheets": RabbitWorkerTopology("zeler.sheets.events", "zeler.sheets.events.dlq"),
    "publicador": None,
    "autoreply": RabbitWorkerTopology("zeler.autoreply.events", "zeler.autoreply.events.dlq"),
}


def _rabbitmq_worker_topology(module: str) -> RabbitWorkerTopology | None:
    try:
        return RABBITMQ_WORKER_TOPOLOGY[module]
    except KeyError as exc:
        msg = f"unsupported module {module}"
        raise ValueError(msg) from exc


class HealthResponse(Protocol):
    status_code: int


class HealthClient(Protocol):
    async def get(self, path: str) -> HealthResponse: ...


class MongoPreflightClient(Protocol):
    async def ping(self) -> bool: ...

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None: ...


class RabbitPreflightClient(Protocol):
    async def topology_valid(self, module: str) -> bool: ...


HttpClientFactory = Callable[[str], HealthClient]
MongoClientFactory = Callable[[str], MongoPreflightClient]
RabbitClientFactory = Callable[[str, str], RabbitPreflightClient]


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str

    def to_json(self) -> dict[str, bool | str]:
        return {"passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class PreflightResult:
    module: str
    seller_id: str
    checks: dict[str, CheckResult]
    checked_at: str

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks.values())

    @property
    def details(self) -> dict[str, Any]:
        return {name: ("ok" if check.passed else "error") for name, check in self.checks.items()}

    def to_json(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "seller_id": self.seller_id,
            "checks": {name: check.to_json() for name, check in self.checks.items()},
            "passed": self.passed,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class PreflightContext:
    module: str
    seller_id: str
    mongo: MongoPreflightClient
    rabbitmq: RabbitPreflightClient
    gateway_http: HealthClient
    module_http: HealthClient

    @classmethod
    def for_stack(cls, stack: Any, *, seller_id: str = "82453304") -> PreflightContext:
        return cls(
            module=stack.module,
            seller_id=seller_id,
            mongo=stack.mongo,
            rabbitmq=stack.rabbitmq,
            gateway_http=stack.gateway_http,
            module_http=stack.module_http,
        )


async def run_preflight(ctx: PreflightContext) -> PreflightResult:
    checks: dict[str, CheckResult] = {}
    checks["mongo"] = await _check_mongo(ctx.mongo)
    checks["rabbitmq"] = await _check_rabbitmq(ctx.rabbitmq, ctx.module)
    checks["gateway"] = await _check_health(ctx.gateway_http, name="gateway")
    checks["module_health"] = await _check_health(ctx.module_http, name=f"{ctx.module} module")
    checks["meli_account"] = await _check_meli_account(ctx.mongo, ctx.seller_id)
    return PreflightResult(
        module=ctx.module,
        seller_id=ctx.seller_id,
        checks=checks,
        checked_at=datetime.now(UTC).isoformat(),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    http_factory: HttpClientFactory | None = None,
    mongo_factory: MongoClientFactory | None = None,
    rabbitmq_factory: RabbitClientFactory | None = None,
) -> int:
    args = _parse_args(argv)
    http_factory = http_factory or _real_http_factory
    mongo_factory = mongo_factory or _real_mongo_factory
    rabbitmq_factory = rabbitmq_factory or _real_rabbitmq_factory
    result = asyncio.run(
        _run_from_args(
            args,
            http_factory=http_factory,
            mongo_factory=mongo_factory,
            rabbitmq_factory=rabbitmq_factory,
        )
    )
    print(json.dumps(result.to_json(), sort_keys=True))
    if not result.passed:
        failed = ",".join(name for name, check in result.checks.items() if not check.passed)
        print(
            f"preflight failed for {result.module} seller {result.seller_id}: {failed}",
            file=sys.stderr,
        )
        return 1
    return 0


async def _run_from_args(
    args: argparse.Namespace,
    *,
    http_factory: HttpClientFactory,
    mongo_factory: MongoClientFactory,
    rabbitmq_factory: RabbitClientFactory,
) -> PreflightResult:
    module = str(args.module)
    if module == "all":
        return await _run_all_modules(args, http_factory, mongo_factory, rabbitmq_factory)
    ctx = PreflightContext(
        module=module,
        seller_id=str(args.seller_id),
        mongo=mongo_factory(str(args.mongo_uri)),
        rabbitmq=rabbitmq_factory(str(args.rabbitmq_management_url), str(args.rabbitmq_vhost)),
        gateway_http=http_factory(str(args.gateway_url)),
        module_http=http_factory(_module_url(module, str(args.gateway_url))),
    )
    return await run_preflight(ctx)


async def _run_all_modules(
    args: argparse.Namespace,
    http_factory: HttpClientFactory,
    mongo_factory: MongoClientFactory,
    rabbitmq_factory: RabbitClientFactory,
) -> PreflightResult:
    checks: dict[str, CheckResult] = {}
    for module in MODULES:
        module_args = argparse.Namespace(**vars(args))
        module_args.module = module
        result = await _run_from_args(
            module_args,
            http_factory=http_factory,
            mongo_factory=mongo_factory,
            rabbitmq_factory=rabbitmq_factory,
        )
        checks.update({f"{module}.{name}": check for name, check in result.checks.items()})
    return PreflightResult(
        module="all",
        seller_id=str(args.seller_id),
        checks=checks,
        checked_at=datetime.now(UTC).isoformat(),
    )


async def _check_mongo(mongo: MongoPreflightClient) -> CheckResult:
    try:
        if await mongo.ping():
            return CheckResult(True, "mongo ping ok")
    except Exception as exc:  # noqa: BLE001 - CLI must report dependency failures.
        return CheckResult(False, f"mongo ping failed: {type(exc).__name__}")
    return CheckResult(False, "mongo ping failed")


async def _check_rabbitmq(rabbitmq: RabbitPreflightClient, module: str) -> CheckResult:
    try:
        topology = _rabbitmq_worker_topology(module)
    except ValueError as exc:
        return CheckResult(False, str(exc))
    if topology is None:
        return CheckResult(True, f"rabbitmq topology not_required for {module}")
    try:
        if await rabbitmq.topology_valid(module):
            return CheckResult(True, f"{topology.queue} and {topology.dlq} topology ok")
    except Exception as exc:  # noqa: BLE001 - CLI must report dependency failures.
        return CheckResult(False, f"rabbitmq topology failed: {type(exc).__name__}")
    return CheckResult(False, f"missing {topology.dlq} binding")


async def _check_health(client: HealthClient, *, name: str) -> CheckResult:
    try:
        response = await client.get("/health")
    except Exception as exc:  # noqa: BLE001 - CLI must report dependency failures.
        return CheckResult(False, f"{name} /health failed: {type(exc).__name__}")
    if response.status_code == 200:
        return CheckResult(True, f"{name} /health 200")
    return CheckResult(False, f"{name} /health {response.status_code}")


async def _check_meli_account(mongo: MongoPreflightClient, seller_id: str) -> CheckResult:
    try:
        account = await mongo.find_one("meli_accounts", {"seller_id": seller_id})
    except Exception as exc:  # noqa: BLE001 - CLI must report dependency failures.
        return CheckResult(False, f"meli_accounts lookup failed: {type(exc).__name__}")
    if account is None:
        return CheckResult(False, f"meli_accounts document missing for {seller_id}")
    return CheckResult(True, f"meli_accounts document found for {seller_id}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Zeler module pilot preflight checks.")
    parser.add_argument("--module", choices=(*MODULES, "all"), required=True)
    parser.add_argument("--seller-id", "--seller", dest="seller_id", required=True)
    parser.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", DEFAULT_MONGO_URI))
    parser.add_argument(
        "--rabbitmq-management-url",
        default=os.getenv("RABBITMQ_MANAGEMENT_URL", DEFAULT_RABBITMQ_MANAGEMENT_URL),
    )
    parser.add_argument("--rabbitmq-vhost", default=_default_rabbitmq_vhost())
    parser.add_argument("--gateway-url", default=os.getenv("GATEWAY_URL", DEFAULT_GATEWAY_URL))
    return parser.parse_args(argv)


def _default_rabbitmq_vhost() -> str:
    explicit_vhost = os.getenv("RABBITMQ_VHOST")
    if explicit_vhost:
        return explicit_vhost
    for env_name in ("RABBITMQ_URL", "CLOUDAMQP_URL"):
        parsed_vhost = _parse_amqp_vhost(os.getenv(env_name))
        if parsed_vhost:
            return parsed_vhost
    return "/"


def _parse_amqp_vhost(amqp_url: str | None) -> str | None:
    if not amqp_url:
        return None
    path = urlparse(amqp_url).path
    if not path or path == "/":
        return None
    return unquote(path.lstrip("/")) or "/"


def _module_url(module: str, gateway_url: str) -> str:
    env_name = f"{module.upper()}_URL"
    return os.getenv(env_name, gateway_url)


def _real_http_factory(base_url: str) -> HealthClient:
    return _HttpxHealthClient(base_url)


def _real_mongo_factory(uri: str) -> MongoPreflightClient:
    return _PymongoPreflightClient(uri)


def _real_rabbitmq_factory(management_url: str, vhost: str) -> RabbitPreflightClient:
    return _RabbitManagementPreflightClient(management_url, vhost)


class _HttpxHealthClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def get(self, path: str) -> HealthResponse:
        import httpx

        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            return await client.get(path)


class _PymongoPreflightClient:
    def __init__(self, uri: str) -> None:
        from pymongo import MongoClient

        self._client: Any = MongoClient(uri, serverSelectionTimeoutMS=5_000)
        self._db: Any = self._client.get_default_database("zeler_platform")

    async def ping(self) -> bool:
        await asyncio.to_thread(self._client.admin.command, "ping")
        return True

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        result = await asyncio.to_thread(self._db[collection].find_one, query)
        if result is None:
            return None
        return dict(result)


class _RabbitManagementPreflightClient:
    def __init__(self, management_url: str, vhost: str = "/") -> None:
        self._management_url = management_url.rstrip("/")
        self._vhost = vhost or "/"

    async def topology_valid(self, module: str) -> bool:
        import httpx

        try:
            topology = _rabbitmq_worker_topology(module)
        except ValueError:
            return False
        if topology is None:
            return True
        encoded_vhost = quote(self._vhost, safe="")
        encoded_dlq = quote(topology.dlq, safe="")
        async with httpx.AsyncClient(base_url=self._management_url, timeout=5.0) as client:
            queues_response = await client.get(f"/api/queues/{encoded_vhost}")
            if queues_response.status_code != 200:
                return False
            queue_names = {item.get("name") for item in queues_response.json()}
            if not {topology.queue, topology.dlq}.issubset(queue_names):
                return False
            bindings_response = await client.get(
                f"/api/queues/{encoded_vhost}/{encoded_dlq}/bindings"
            )
            if bindings_response.status_code != 200:
                return False
            return any(binding.get("source") for binding in bindings_response.json())


if __name__ == "__main__":
    raise SystemExit(main())
