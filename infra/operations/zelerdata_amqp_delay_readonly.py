"""Bounded, opt-in Management GET reader. No AMQP connections or mutations.

Output contains only selected-resource labels, route templates and fixed errors.
Never re-run automatically: a production execution is owned by the coordinator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

EVENTS = "zeler.sheets.events"
CLAIMS = "zeler.sheets.claims"
LIVE = "meli.events"
BINS = {"1s": 1000, "5s": 5000, "30s": 30000, "2m": 120000, "10m": 600000}
ARGS: dict[str, dict[str, Any]] = {
    EVENTS: {
        "x-dead-letter-exchange": EVENTS + ".dlx",
        "x-dead-letter-routing-key": EVENTS + ".dlq",
    },
    EVENTS + ".delay": {
        "x-message-ttl": 30000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": EVENTS,
    },
    EVENTS + ".dlq": {},
    CLAIMS: {
        "x-dead-letter-exchange": CLAIMS + ".dlx",
        "x-dead-letter-routing-key": CLAIMS + ".dlq",
    },
    CLAIMS + ".dlq": {},
}
ARGS.update(
    {
        CLAIMS + ".retry." + name: {
            "x-message-ttl": ttl,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": CLAIMS,
        }
        for name, ttl in BINS.items()
    }
)
EXCHANGES = {LIVE: "topic", EVENTS + ".dlx": "direct", CLAIMS + ".dlx": "direct"}
ROUTES = ("items.*", "orders.*", "shipments.*", "questions.*", "catalog_item_competition_status.*")
MAX_BODY_BYTES = 65536
_PRIVATE_HTTP = ContextVar("amqp_reader_private_http", default=False)


class _PrivateHttpFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (_PRIVATE_HTTP.get() and record.name.startswith(("httpx", "httpcore")))


def _install_log_filter() -> tuple[logging.Filter, list[Any]]:
    # Task-local suppression, including library DEBUG URLs/vhosts. No permanent
    # logger levels or host configuration changes; restore in finally. The CLI
    # owns an isolated process, and tests keep their own logging configuration.
    private_filter = _PrivateHttpFilter()
    targets: list[Any] = [logging.getLogger("httpx"), *logging.getLogger().handlers]
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("httpcore") and isinstance(logger, logging.Logger):
            targets.append(logger)
    for target in targets:
        target.addFilter(private_filter)
    return private_filter, targets


class GateError(ValueError):
    """Internal fixed error codes only; never wrap provider exception text."""


@dataclass(frozen=True, repr=False)
class Configuration:
    base_url: str = field(repr=False)
    vhost: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return "Configuration(<redacted>)"

    @classmethod
    def from_urls(cls, amqp_url: str, management_url: str | None = None) -> Configuration:
        try:
            broker = urlsplit(amqp_url)
            if (
                broker.scheme not in {"amqp", "amqps"}
                or not broker.hostname
                or not broker.username
                or not broker.password
                or broker.query
                or broker.fragment
            ):
                raise GateError("broker_configuration_invalid")
            username = unquote(broker.username)
            password = unquote(broker.password)
            vhost = unquote(broker.path[1:]) if broker.path not in {"", "/"} else "/"
            if not management_url:
                # TLS origin only, not an alternate URL probe. Non-TLS brokers
                # need an explicit loopback Management target.
                if broker.scheme != "amqps":
                    raise GateError("management_configuration_invalid")
                host = broker.hostname
                if ":" in host:
                    host = "[" + host + "]"
                management_url = "https://" + host
        except ValueError as exc:
            if isinstance(exc, GateError):
                raise
            raise GateError("broker_configuration_invalid") from None
        try:
            management = urlsplit(management_url)
            # Validate the port without printing the parsing error/URL.
            _ = management.port
            prefix = management.path.rstrip("/")
            if prefix.endswith("/api"):
                prefix = prefix[:-4]
            if (
                not management.hostname
                or management.username is not None
                or management.password is not None
                or management.query
                or management.fragment
                or (
                    management.scheme != "https"
                    and not (
                        management.scheme == "http"
                        and management.hostname in {"localhost", "127.0.0.1", "::1"}
                    )
                )
                or "api" in prefix.split("/")
                or any(part in {".", ".."} for part in prefix.split("/"))
            ):
                raise GateError("management_configuration_invalid")
            base = urlunsplit((management.scheme, management.netloc, prefix + "/", "", ""))
        except ValueError:
            raise GateError("management_configuration_invalid") from None
        return cls(base, vhost, username, password)


def _identity(value: Any, name: str, vhost: str | None) -> None:
    if type(value) is not dict or any(type(value.get(key)) is not str for key in ("name", "vhost")):
        raise GateError("metadata_incomplete")
    if value.get("name") != name or (vhost is not None and value.get("vhost") != vhost):
        raise GateError("metadata_identity_mismatch")


def _queue(value: Any, name: str, vhost: str | None = None) -> dict[str, Any]:
    _identity(value, name, vhost)
    if (
        value.get("durable") is not True
        or value.get("auto_delete") is not False
        or value.get("exclusive") is not False
        or type(value.get("arguments")) is not dict
        or type(value.get("effective_policy_definition")) is not dict
    ):
        raise GateError("metadata_incomplete")
    if (
        value["effective_policy_definition"]
        or value.get("policy") not in (None, "")
        or value.get("operator_policy") not in (None, "")
    ):
        raise GateError("queue_policy_requires_review")
    args = value["arguments"]
    expected = ARGS[name]
    for key, wanted in expected.items():
        if type(args.get(key)) is not type(wanted) or args.get(key) != wanted:
            raise GateError("ttl_or_dead_letter_drift")
    protected = {
        "x-message-ttl",
        "x-dead-letter-exchange",
        "x-dead-letter-routing-key",
        "x-expires",
        "x-max-length",
        "x-max-length-bytes",
        "x-overflow",
        "x-delivery-limit",
    }
    if (set(args) & protected) - set(expected):
        raise GateError("queue_lifecycle_requires_review")
    for key in ("messages_ready", "messages_unacknowledged", "consumers"):
        if type(value.get(key)) is not int or value[key] < 0:
            raise GateError("counts_missing_or_invalid")
    if name in (EVENTS, CLAIMS) and value["consumers"] < 1:
        raise GateError("consumer_missing")
    if (name == EVENTS + ".delay" or name.startswith(CLAIMS + ".retry.")) and value["consumers"]:
        raise GateError("delay_queue_has_consumer")
    return {
        "ready": value["messages_ready"],
        "unacked": value["messages_unacknowledged"],
        "consumers": value["consumers"],
        "ttl_ms": args.get("x-message-ttl"),
        "expected_ttl_dlx_verified": True,
    }


def _bindings(value: Any, name: str, vhost: str | None = None) -> None:
    if type(value) is not list:
        raise GateError("metadata_incomplete")
    for binding in value:
        if (
            type(binding) is not dict
            or any(
                type(binding.get(key)) is not str
                for key in ("source", "destination", "routing_key", "vhost")
            )
            or type(binding.get("arguments")) is not dict
        ):
            raise GateError("metadata_incomplete")
        if binding["destination"] != name or (vhost is not None and binding["vhost"] != vhost):
            raise GateError("metadata_identity_mismatch")
        if binding.get("destination_type") != "queue":
            raise GateError("binding_shape_invalid")
    needed = [("", name)]
    if name == EVENTS:
        needed.extend((LIVE, route) for route in ROUTES)
    elif name == EVENTS + ".delay":
        needed.append((LIVE, name))
    elif name == EVENTS + ".dlq":
        needed.append((EVENTS + ".dlx", name))
    elif name == CLAIMS:
        needed.append((LIVE, "claims.updated"))
    elif name == CLAIMS + ".dlq":
        needed.append((CLAIMS + ".dlx", name))
    for source, route in needed:
        if not any(
            b["source"] == source and b["routing_key"] == route and b["arguments"] == {}
            for b in value
        ):
            raise GateError("required_binding_missing")


def _exchange(value: Any, name: str, vhost: str | None = None) -> None:
    _identity(value, name, vhost)
    if (
        value.get("durable") is not True
        or value.get("type") != EXCHANGES[name]
        or value.get("auto_delete") is not False
        or value.get("internal") is not False
        or value.get("arguments") != {}
    ):
        raise GateError("exchange_drift")


def classify(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Check selected metadata only, never equate topology with delivery."""
    queues: dict[str, Any] = {}
    try:
        for name in ARGS:
            queues[name] = _queue(snapshot["queues"][name], name)
            _bindings(snapshot["bindings"][name], name)
        for name in EXCHANGES:
            _exchange(snapshot["exchanges"][name], name)
        needed = (
            [("", name, name) for name in ARGS]
            + [(LIVE, EVENTS, route) for route in ROUTES]
            + [
                (LIVE, EVENTS + ".delay", EVENTS + ".delay"),
                (EVENTS + ".dlx", EVENTS + ".dlq", EVENTS + ".dlq"),
                (LIVE, CLAIMS, "claims.updated"),
                (CLAIMS + ".dlx", CLAIMS + ".dlq", CLAIMS + ".dlq"),
            ]
        )
        for source, destination, route in needed:
            if not any(
                b["source"] == source and b["routing_key"] == route and b["arguments"] == {}
                for b in snapshot["bindings"][destination]
            ):
                raise GateError("required_binding_missing")
    except (KeyError, TypeError, AttributeError):
        raise GateError("metadata_incomplete") from None
    return {
        "topology_verified": True,
        "queues": queues,
        "expected_bindings_verified": True,
        "runtime_confirmed_publish_verified": False,
        "message_expiration_timing_verified": False,
        "normal_queue_ttl_can_cap_per_message_delay": True,
    }


def _receipt() -> dict[str, Any]:
    return {
        "read_only": True,
        "executed": True,
        "no_retry": True,
        "stop": False,
        "topology_verified": False,
        "runtime_confirmed_publish_verified": False,
        "message_expiration_timing_verified": False,
        "amqp_mutations": 0,
        "requests_started": 0,
        "responses_received": 0,
        "requests_completed": 0,
        "requests": [],
        "code": None,
        "cleanup_error": None,
        "elapsed_seconds": 0.0,
    }


async def inspect(
    configuration: Configuration,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    max_requests: int = 23,
    request_seconds: float = 4.0,
    read_seconds: float = 60.0,
    cleanup_seconds: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """One attempt; stop on first error. Own and close the HTTP client only."""
    result = _receipt()
    started = clock()
    client: httpx.AsyncClient | None = None
    active: dict[str, Any] | None = None
    if (
        type(max_requests) is not int
        or not 0 <= max_requests <= 23
        or not 0 < request_seconds <= 4
        or not 0 < read_seconds <= 60
        or not 0 < cleanup_seconds <= 5
    ):
        result.update(code="management_limits_invalid", stop=True)
        return result

    async def get(stage: str, name: str) -> Any:
        nonlocal active
        if result["requests_started"] >= max_requests:
            raise GateError("management_request_limit")
        group = "exchanges" if stage == "exchange" else "queues"
        suffix = "/bindings" if stage == "bindings" else ""
        path = f"api/{group}/{quote(configuration.vhost, safe='')}/{quote(name, safe='')}{suffix}"
        record: dict[str, Any] = {
            "sequence": result["requests_started"] + 1,
            "operation": "GET",
            "stage": stage,
            "endpoint": name,
            "route": f"/api/{group}/{{vhost}}/{name}{suffix}",
            "status": None,
            "bytes_received": 0,
            "truncated": False,
            "completed": False,
            "elapsed_seconds": 0.0,
            "error": None,
        }
        active = record
        result["requests"].append(record)
        request_started = clock()

        async def read() -> Any:
            # Increment at the last point before the HTTP operation. The count
            # means initiated, not proof that a packet reached the server.
            result["requests_started"] += 1
            if client is None:
                raise GateError("management_transport_failed")
            async with client.stream("GET", path, follow_redirects=False) as response:
                result["responses_received"] += 1
                record["status"] = response.status_code
                if response.status_code != 200:
                    raise GateError(f"management_http_{response.status_code}")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise GateError("metadata_content_encoding_unsupported")
                declared: int | None = None
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        if not length.isascii() or not length.isdigit():
                            raise ValueError
                        declared = int(length)
                    except ValueError:
                        raise GateError("metadata_response_incomplete") from None
                    if declared > MAX_BODY_BYTES:
                        record["truncated"] = True
                        raise GateError("metadata_response_too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    record["bytes_received"] += len(chunk)
                    if record["bytes_received"] > MAX_BODY_BYTES:
                        record["truncated"] = True
                        raise GateError("metadata_response_too_large")
                    body.extend(chunk)
                if declared is not None and declared != record["bytes_received"]:
                    record["truncated"] = True
                    raise GateError("metadata_response_incomplete")
                result["requests_completed"] += 1
                record["completed"] = True
                try:
                    value = json.loads(body)
                except (ValueError, UnicodeError):
                    raise GateError("metadata_json_invalid") from None
                if stage == "metadata":
                    _queue(value, name, configuration.vhost)
                elif stage == "bindings":
                    _bindings(value, name, configuration.vhost)
                else:
                    _exchange(value, name, configuration.vhost)
                return value

        try:
            return await asyncio.wait_for(read(), timeout=request_seconds)
        except (TimeoutError, httpx.TimeoutException):
            raise GateError("management_timeout") from None
        except httpx.HTTPError:
            raise GateError("management_transport_failed") from None
        finally:
            record["elapsed_seconds"] = max(0.0, clock() - request_started)

    async def collect() -> dict[str, Any]:
        snapshot: dict[str, Any] = {"queues": {}, "bindings": {}, "exchanges": {}}
        for name in ARGS:
            snapshot["queues"][name] = await get("metadata", name)
            snapshot["bindings"][name] = await get("bindings", name)
        for name in EXCHANGES:
            snapshot["exchanges"][name] = await get("exchange", name)
        return classify(snapshot)

    private_filter, targets = _install_log_filter()
    privacy_token = _PRIVATE_HTTP.set(True)
    try:
        client = httpx.AsyncClient(
            base_url=configuration.base_url,
            auth=httpx.BasicAuth(configuration.username, configuration.password),
            transport=transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False),
            headers={"Accept-Encoding": "identity"},
            timeout=request_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        result.update(await asyncio.wait_for(collect(), timeout=read_seconds))
    except GateError as exc:
        result.update(code=str(exc), stop=True)
    except TimeoutError:
        result.update(code="management_deadline", stop=True)
    except Exception:  # noqa: BLE001 -- library exceptions may contain credentials.
        result.update(code="management_access_or_tool_failed", stop=True)
    finally:
        if result["code"] is not None and active is not None:
            # A full body can still have invalid JSON/shape/semantics.
            active["error"] = result["code"]
        if client is not None:
            try:
                await asyncio.wait_for(client.aclose(), timeout=cleanup_seconds)
            except TimeoutError:
                result["cleanup_error"] = "management_cleanup_timeout"
            except Exception:  # noqa: BLE001 -- never expose cleanup details.
                result["cleanup_error"] = "management_cleanup_failed"
        if result["cleanup_error"] is not None:
            result.update(stop=True, topology_verified=False)
            if result["code"] is None:
                result["code"] = result["cleanup_error"]
        result["elapsed_seconds"] = max(0.0, clock() - started)
        _PRIVATE_HTTP.reset(privacy_token)
        for target in targets:
            target.removeFilter(private_filter)
    return result


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    if (sys.argv[1:] if argv is None else argv) != ["--inspect"]:
        print(
            json.dumps(
                {"read_only": True, "executed": False, "required_action": "explicit_inspect"}
            )
        )
        return 2
    result = _receipt()
    try:
        env = os.environ if environ is None else environ
        configuration = Configuration.from_urls(
            env.get("RABBITMQ_URL", ""), env.get("RABBITMQ_MANAGEMENT_URL")
        )
        result = asyncio.run(inspect(configuration))
    except GateError as exc:
        result.update(code=str(exc), stop=True)
    except Exception:  # noqa: BLE001 -- no traceback containing target/auth.
        result.update(code="management_access_or_tool_failed", stop=True)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stop"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
