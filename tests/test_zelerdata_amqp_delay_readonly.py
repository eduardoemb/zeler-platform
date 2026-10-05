"""AMQP specialist fixtures: GET-only, no sockets, no production configuration.

Prepared before implementation. Run only in the coordinator's AMQP test slot.
Missing reader import is the initial expected RED; do not skip that evidence.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import socket
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from infra.operations.zelerdata_amqp_delay_readonly import (
    ARGS,
    CLAIMS,
    EVENTS,
    EXCHANGES,
    LIVE,
    ROUTES,
    Configuration,
    GateError,
    classify,
    inspect,
    main,
)

SECRET = "synthetic-sensitive-marker"  # noqa: S105 -- synthetic redaction probe, not a credential.


@pytest.fixture(autouse=True)
def forbid_sockets(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def blocked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline test attempted a socket connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    yield


def configuration(base: str = "https://management.test", vhost: str = "/") -> Configuration:
    return Configuration.from_urls(
        f"amqps://{SECRET}:{SECRET}@broker.test/{quote(vhost, safe='')}", base
    )


def snapshot(vhost: str = "/") -> dict[str, Any]:
    bindings: dict[str, list[dict[str, Any]]] = {
        name: [
            {
                "source": "",
                "destination": name,
                "destination_type": "queue",
                "routing_key": name,
                "vhost": vhost,
                "arguments": {},
            }
        ]
        for name in ARGS
    }
    needed = [(LIVE, EVENTS, route) for route in ROUTES] + [
        (LIVE, EVENTS + ".delay", EVENTS + ".delay"),
        (EVENTS + ".dlx", EVENTS + ".dlq", EVENTS + ".dlq"),
        (LIVE, CLAIMS, "claims.updated"),
        (CLAIMS + ".dlx", CLAIMS + ".dlq", CLAIMS + ".dlq"),
    ]
    for source, destination, route in needed:
        bindings[destination].append(
            {
                "source": source,
                "destination": destination,
                "destination_type": "queue",
                "routing_key": route,
                "vhost": vhost,
                "arguments": {},
            }
        )
    return {
        "queues": {
            name: {
                "name": name,
                "vhost": vhost,
                "durable": True,
                "auto_delete": False,
                "exclusive": False,
                "arguments": {**args, "x-queue-type": "classic"},
                "effective_policy_definition": {},
                "policy": None,
                "operator_policy": None,
                "messages_ready": 0,
                "messages_unacknowledged": 0,
                "consumers": int(name in (EVENTS, CLAIMS)),
            }
            for name, args in ARGS.items()
        },
        "bindings": bindings,
        "exchanges": {
            name: {
                "name": name,
                "vhost": vhost,
                "type": kind,
                "durable": True,
                "auto_delete": False,
                "internal": False,
                "arguments": {},
            }
            for name, kind in EXCHANGES.items()
        },
    }


def handler_for(
    doc: dict[str, Any], calls: list[httpx.Request], prefix: str = ""
) -> Callable[[httpx.Request], httpx.Response]:
    vhost = quote(next(iter(doc["queues"].values()))["vhost"], safe="")
    selected: dict[str, Any] = {}
    for name in ARGS:
        path = f"{prefix}/api/queues/{vhost}/{quote(name, safe='')}"
        selected[path] = doc["queues"][name]
        selected[path + "/bindings"] = doc["bindings"][name]
    for name in EXCHANGES:
        selected[f"{prefix}/api/exchanges/{vhost}/{quote(name, safe='')}"] = doc["exchanges"][name]

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and not request.url.query
        path = request.url.raw_path.decode()
        assert path in selected
        return httpx.Response(200, json=selected[path])

    return respond


def assert_sanitized(result: dict[str, Any]) -> None:
    encoded = json.dumps(result)
    for forbidden in (SECRET, "broker.test", "management.test", "Authorization", "traceback"):
        assert forbidden not in encoded
    assert result["amqp_mutations"] == 0
    assert result["runtime_confirmed_publish_verified"] is False
    assert result["message_expiration_timing_verified"] is False


@pytest.mark.asyncio
async def test_library_debug_logs_cannot_leak_vhost_or_transport_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    calls: list[httpx.Request] = []
    respond = handler_for(snapshot(SECRET), calls)

    def transport(request: httpx.Request) -> httpx.Response:
        logging.getLogger("httpcore.connection").debug("transport detail %s", SECRET)
        return respond(request)

    result = await inspect(configuration(vhost=SECRET), transport=httpx.MockTransport(transport))
    assert result["topology_verified"] is True
    assert SECRET not in caplog.text
    assert_sanitized(result)


@pytest.mark.asyncio
async def test_missing_required_binding_stops_on_its_endpoint_not_later_exchange() -> None:
    doc = snapshot()
    doc["bindings"][EVENTS] = []
    calls: list[httpx.Request] = []
    result = await inspect(configuration(), transport=httpx.MockTransport(handler_for(doc, calls)))
    assert result["code"] == "required_binding_missing"
    assert result["requests_started"] == len(calls) == 2
    assert result["requests"][-1]["stage"] == "bindings"
    assert result["requests"][-1]["endpoint"] == EVENTS


@pytest.mark.asyncio
async def test_compressed_body_is_rejected_before_decompression() -> None:
    result = await inspect(
        configuration(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Chunks())
        ),
    )
    assert result["code"] == "metadata_content_encoding_unsupported"
    assert result["requests_started"] == 1 and result["requests_completed"] == 0


@pytest.mark.asyncio
async def test_declared_length_mismatch_is_incomplete_not_green() -> None:
    queue_body = json.dumps(snapshot()["queues"][EVENTS]).encode()
    result = await inspect(
        configuration(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=queue_body, headers={"Content-Length": str(len(queue_body) + 1)}
            )
        ),
    )
    assert result["code"] == "metadata_response_incomplete"
    assert result["requests_started"] == 1 and result["requests_completed"] == 0
    assert result["requests"][-1]["truncated"] is True


@pytest.mark.asyncio
async def test_private_filters_restore_after_failure(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("httpx")
    before = list(logger.filters)
    await inspect(configuration(), transport=CleanupFailure(lambda _: httpx.Response(404)))
    assert logger.filters == before
    caplog.set_level(logging.INFO)
    logger.info("synthetic restored logger")
    assert "synthetic restored logger" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["", "/", "/api", "/api/", "/prefix", "/prefix/api/"])
@pytest.mark.parametrize("vhost", ["/", "space / nested", "literal%2F", "México"])
async def test_exact_23_gets_base_vhost_single_encoding_and_safe_receipt(
    base: str, vhost: str
) -> None:
    calls: list[httpx.Request] = []
    prefix = "/prefix" if base.startswith("/prefix") else ""
    result = await inspect(
        configuration("https://management.test" + base, vhost),
        transport=httpx.MockTransport(handler_for(snapshot(vhost), calls, prefix)),
    )
    assert result["topology_verified"] is True and result["stop"] is False
    assert result["requests_started"] == result["requests_completed"] == 23
    assert result["responses_received"] == len(calls) == len(result["requests"]) == 23
    assert result["elapsed_seconds"] >= 0
    for index, record in enumerate(result["requests"], 1):
        assert record["sequence"] == index
        assert record["operation"] == "GET" and record["status"] == 200
        assert record["elapsed_seconds"] >= 0 and record["bytes_received"] > 0
        assert record["truncated"] is False and record["error"] is None
        assert "{vhost}" in record["route"]
    assert_sanitized(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://not-loopback.test",
        "https://user:password@management.test",
        "https://management.test/api?secret=value",
        "https://management.test/#fragment",
        "ftp://management.test",
        "https://management.test/api/api",
    ],
)
def test_invalid_management_configuration_fails_safely(url: str) -> None:
    with pytest.raises(GateError, match="^management_configuration_invalid$"):
        configuration(url)


@pytest.mark.parametrize("url", ["", "amqps://broker.test/", "https://u:p@broker.test/"])
def test_missing_or_invalid_broker_credentials_no_guest_guess(url: str) -> None:
    with pytest.raises(GateError, match="^broker_configuration_invalid$"):
        Configuration.from_urls(url, "https://management.test")


def test_configuration_repr_never_discloses_target_or_auth() -> None:
    value = repr(configuration(vhost=SECRET))
    assert SECRET not in value and "management.test" not in value and "broker.test" not in value


@pytest.mark.asyncio
async def test_queue_identity_from_another_vhost_is_not_accepted() -> None:
    doc = snapshot()
    doc["queues"][EVENTS]["vhost"] = SECRET
    calls: list[httpx.Request] = []
    # Build transport with the selected vhost before substituting its response.
    respond = handler_for(snapshot(), calls)

    def transport(request: httpx.Request) -> httpx.Response:
        if not calls:
            calls.append(request)
            return httpx.Response(200, json=doc["queues"][EVENTS])
        return respond(request)

    result = await inspect(configuration(), transport=httpx.MockTransport(transport))
    assert result["code"] == "metadata_identity_mismatch"
    assert result["requests_started"] == len(calls) == 1
    assert_sanitized(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 404, 429, 500])
@pytest.mark.parametrize("fail_at", [1, 2, 21, 23])
async def test_http_error_first_stop_exact_endpoint_and_no_retry(status: int, fail_at: int) -> None:
    calls: list[httpx.Request] = []
    respond = handler_for(snapshot(), calls)

    def transport(request: httpx.Request) -> httpx.Response:
        if len(calls) + 1 == fail_at:
            calls.append(request)
            return httpx.Response(
                status, text=SECRET, headers={"Location": "https://" + SECRET + ".test"}
            )
        return respond(request)

    result = await inspect(configuration(), transport=httpx.MockTransport(transport))
    assert result["stop"] is True and result["topology_verified"] is False
    assert result["code"] == f"management_http_{status}"
    assert result["requests_started"] == result["responses_received"] == len(calls) == fail_at
    assert result["requests_completed"] == fail_at - 1
    assert result["requests"][-1]["status"] == status
    assert result["requests"][-1]["sequence"] == fail_at
    assert result["requests"][-1]["error"] == result["code"]
    assert_sanitized(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (httpx.ReadTimeout, "management_timeout"),
        (httpx.ConnectError, "management_transport_failed"),
    ],
)
async def test_exception_details_are_not_logged(failure: Any, code: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure(SECRET, request=request)

    result = await inspect(configuration(), transport=httpx.MockTransport(fail))
    assert result["code"] == code
    assert result["requests_started"] == 1
    assert result["requests_completed"] == result["responses_received"] == 0
    assert result["requests"][-1]["status"] is None
    assert_sanitized(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"not-json", "metadata_json_invalid"),
        (b"\xff", "metadata_json_invalid"),
        (b"[]", "metadata_incomplete"),
        (b'{"items": [], "page_count": 2}', "metadata_incomplete"),
        (b"x" * 65537, "metadata_response_too_large"),
    ],
)
async def test_malformed_incomplete_or_oversize_response_stops_immediately(
    body: bytes, code: str
) -> None:
    result = await inspect(
        configuration(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    assert result["code"] == code and result["requests_started"] == 1
    assert result["responses_received"] == 1
    assert result["requests"][-1]["status"] == 200
    assert result["requests"][-1]["truncated"] == (len(body) > 65536)
    assert_sanitized(result)


@pytest.mark.asyncio
async def test_bindings_pagination_envelope_is_not_a_complete_list() -> None:
    calls: list[httpx.Request] = []
    respond = handler_for(snapshot(), calls)

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bindings"):
            calls.append(request)
            return httpx.Response(200, json={"items": [], "page": 1, "page_count": 2})
        return respond(request)

    result = await inspect(configuration(), transport=httpx.MockTransport(transport))
    assert result["code"] == "metadata_incomplete" and result["requests_started"] == 2
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1, 22])
async def test_request_limit_exhaustion_never_initiates_an_extra_get(limit: int) -> None:
    calls: list[httpx.Request] = []
    result = await inspect(
        configuration(),
        transport=httpx.MockTransport(handler_for(snapshot(), calls)),
        max_requests=limit,
    )
    assert result["code"] == "management_request_limit"
    assert result["requests_started"] == result["requests_completed"] == len(calls) == limit
    assert result["topology_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("read_deadline", [False, True])
async def test_wall_timeout_bounds_mocktransport_and_cancels_request(read_deadline: bool) -> None:
    cancelled: list[bool] = []

    async def stall(_: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
        return httpx.Response(200, json={})

    result = await inspect(
        configuration(),
        transport=httpx.MockTransport(stall),
        read_seconds=0.01 if read_deadline else 1.0,
        request_seconds=1.0 if read_deadline else 0.01,
    )
    assert result["code"] == ("management_deadline" if read_deadline else "management_timeout")
    assert result["requests_started"] == 1 and result["requests_completed"] == 0
    assert result["elapsed_seconds"] < 1.0 and cancelled == [True]
    assert_sanitized(result)


class CleanupFailure(httpx.MockTransport):
    async def aclose(self) -> None:
        raise RuntimeError(SECRET)


@pytest.mark.asyncio
async def test_cleanup_failure_retains_first_error_and_counts_without_traceback() -> None:
    result = await inspect(
        configuration(), transport=CleanupFailure(lambda _: httpx.Response(404, text=SECRET))
    )
    assert result["code"] == "management_http_404"
    assert result["cleanup_error"] == "management_cleanup_failed"
    assert result["requests_started"] == 1
    assert_sanitized(result)


class SlowCleanup(httpx.MockTransport):
    async def aclose(self) -> None:
        await asyncio.sleep(10)


@pytest.mark.asyncio
async def test_cleanup_timeout_is_bounded_and_cannot_turn_success_into_green() -> None:
    calls: list[httpx.Request] = []
    result = await inspect(
        configuration(), transport=SlowCleanup(handler_for(snapshot(), calls)), cleanup_seconds=0.01
    )
    assert result["cleanup_error"] == "management_cleanup_timeout"
    assert result["stop"] is True and result["topology_verified"] is False
    assert result["requests_started"] == 23
    assert result["elapsed_seconds"] < 1.0
    assert_sanitized(result)


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self) -> Any:
        yield b"x" * 40000
        yield b"x" * 40000


@pytest.mark.asyncio
async def test_stream_size_limit_without_content_length_records_lower_bound() -> None:
    result = await inspect(
        configuration(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks())),
    )
    assert result["code"] == "metadata_response_too_large"
    assert result["requests_started"] == 1 and result["requests_completed"] == 0
    assert result["requests"][-1]["truncated"] is True
    assert 65536 < result["requests"][-1]["bytes_received"] <= 80000
    assert_sanitized(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limits",
    [
        {"max_requests": 24},
        {"max_requests": -1},
        {"read_seconds": 61},
        {"request_seconds": 4.1},
        {"cleanup_seconds": 301},
    ],
)
async def test_limits_cannot_be_expanded_by_parameters(limits: dict[str, Any]) -> None:
    calls: list[httpx.Request] = []
    result = await inspect(
        configuration(), transport=httpx.MockTransport(handler_for(snapshot(), calls)), **limits
    )
    assert result["code"] == "management_limits_invalid"
    assert result["requests_started"] == 0 and calls == []


def test_metadata_is_not_publish_timing_proof_and_benign_arguments_are_preserved() -> None:
    doc = snapshot()
    before = copy.deepcopy(doc)
    result = classify(doc)
    assert result["topology_verified"] is True
    assert result["runtime_confirmed_publish_verified"] is False
    assert result["message_expiration_timing_verified"] is False
    assert result["queues"][EVENTS + ".delay"]["ttl_ms"] == 30000
    assert doc == before


@pytest.mark.parametrize(
    "bad",
    [
        "ttl",
        "dlx",
        "binding",
        "default_binding",
        "durable",
        "exclusive",
        "consumer",
        "retry_consumer",
        "bool_count",
        "exchange",
        "effective_policy",
        "operator_policy",
        "missing_policy",
        "queue_expiry",
        "queue_limit",
        "binding_type",
        "binding_arguments",
    ],
)
def test_topology_drift_or_missing_evidence_fails_closed_without_mutation(bad: str) -> None:
    doc = snapshot()
    queue = doc["queues"][EVENTS + ".delay"]
    if bad == "ttl":
        queue["arguments"]["x-message-ttl"] = 25000
    elif bad == "dlx":
        queue["arguments"]["x-dead-letter-routing-key"] = "foreign"
    elif bad == "binding":
        doc["bindings"][EVENTS + ".delay"] = []
    elif bad == "default_binding":
        doc["bindings"][CLAIMS + ".retry.5s"] = []
    elif bad == "durable":
        queue["durable"] = False
    elif bad == "exclusive":
        queue["exclusive"] = True
    elif bad == "consumer":
        doc["queues"][EVENTS]["consumers"] = 0
    elif bad == "retry_consumer":
        queue["consumers"] = 1
    elif bad == "bool_count":
        queue["messages_ready"] = False
    elif bad == "exchange":
        doc["exchanges"][LIVE]["type"] = "direct"
    elif bad == "effective_policy":
        queue["effective_policy_definition"] = {"message-ttl": 25000}
    elif bad == "operator_policy":
        queue["operator_policy"] = SECRET
    elif bad == "missing_policy":
        del queue["effective_policy_definition"]
    elif bad == "queue_expiry":
        queue["arguments"]["x-expires"] = 5000
    elif bad == "queue_limit":
        queue["arguments"]["x-max-length"] = 1
    elif bad == "binding_type":
        doc["bindings"][EVENTS][-1]["destination_type"] = "exchange"
    else:
        doc["bindings"][EVENTS][-1]["arguments"] = {"unexpected": SECRET}
    before = copy.deepcopy(doc)
    with pytest.raises(GateError):
        classify(doc)
    assert doc == before


def test_cli_default_and_invalid_args_never_inspect_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RABBITMQ_URL", SECRET)
    for args in ([], ["--unknown", SECRET]):
        assert main(args) == 2
        result = json.loads(capsys.readouterr().out)
        assert result["executed"] is False
        assert SECRET not in json.dumps(result)


def test_cli_bad_configuration_is_fixed_error_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RABBITMQ_URL", SECRET)
    assert main(["--inspect"]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert json.loads(output.out)["code"] == "broker_configuration_invalid"
