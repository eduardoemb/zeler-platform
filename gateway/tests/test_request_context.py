"""Request correlation, classification, middleware, and sanitization contracts."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from zeler_gateway.observability.logging import configure_logging
from zeler_gateway.observability.request_context import (
    REQUEST_CLASS_SERVER_ERROR,
    REQUEST_ID_HEADER,
    classify_request_class,
    internal_error_handler,
    normalize_request_id,
    request_context_middleware,
    request_log_entry,
)

GENERATED_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LOG_KEYS = {
    "event",
    "level",
    "timestamp",
    "service",
    "request_id",
    "route",
    "method",
    "status_code",
    "request_class",
    "error_class",
}


def _make_classified_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(Exception, internal_error_handler)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom secret-detail")

    @app.post("/boom")
    def boom_post() -> None:
        raise RuntimeError("boom secret-detail")

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _classified_log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    captured = capsys.readouterr()
    lines: list[dict[str, Any]] = []
    for raw_line in captured.out.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "http.request":
            lines.append(payload)
    return lines


@pytest.mark.parametrize("raw", [None, "!!! not allowed !!!", "a" * 65])
def test_unbounded_or_missing_request_id_is_generated(raw: str | None) -> None:
    generated = normalize_request_id(raw)

    assert GENERATED_REQUEST_ID_PATTERN.fullmatch(generated) is not None


def test_bounded_request_id_is_accepted_verbatim() -> None:
    bounded = "abc-123.xyz_9:ABC"

    assert normalize_request_id(bounded) == bounded


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, "ok"), (301, "ok"), (404, "client_error"), (429, "client_error"), (500, "server_error")],
)
def test_classifies_status_codes(status_code: int, expected: str) -> None:
    assert classify_request_class(status_code) == expected


def test_log_entry_emits_only_bounded_keys() -> None:
    entry = request_log_entry(
        request_id="rid-1",
        route="/health",
        method="GET",
        status_code=200,
        request_class="ok",
        error_class=None,
    )

    assert set(entry) == LOG_KEYS - {"event", "level", "timestamp"}


def test_success_response_is_stamped_and_logged_once(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(environment="production")
    response = TestClient(_make_classified_app()).get(
        "/ok", headers={REQUEST_ID_HEADER: "abc-123"}
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "abc-123"
    lines = _classified_log_lines(capsys)
    assert len(lines) == 1
    assert set(lines[0]) == LOG_KEYS
    assert lines[0]["route"] == "/ok"
    assert lines[0]["method"] == "GET"
    assert lines[0]["status_code"] == 200
    assert lines[0]["request_class"] == "ok"
    assert lines[0]["error_class"] is None


def test_unhandled_exception_returns_sanitized_500_and_classified_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(environment="production")
    response = TestClient(_make_classified_app(), raise_server_exceptions=False).get(
        "/boom", headers={REQUEST_ID_HEADER: "inbound-1"}
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal",
        "error_class": "unknown",
        "request_id": "inbound-1",
    }
    assert response.headers[REQUEST_ID_HEADER] == "inbound-1"
    lines = _classified_log_lines(capsys)
    assert len(lines) == 1
    assert lines[0]["request_class"] == REQUEST_CLASS_SERVER_ERROR
    assert lines[0]["error_class"] == "RuntimeError"
    assert "secret-detail" not in capsys.readouterr().out


def test_log_and_500_never_contain_body_query_auth_or_seller(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(environment="production")
    secrets = (
        "topsecret-query",
        "oauthcode-value",
        "topsecret-bearer",
        "82453304",
        "pw-topsecret",
        "secret-detail",
    )

    response = TestClient(_make_classified_app(), raise_server_exceptions=False).post(
        "/boom",
        headers={REQUEST_ID_HEADER: "inbound-1", "Authorization": "Bearer topsecret-bearer"},
        params={"access_token": "topsecret-query", "code": "oauthcode-value"},
        json={"seller_id": 82453304, "password": "pw-topsecret"},
    )

    rendered = json.dumps(response.json())
    captured_output = capsys.readouterr().out
    for secret in secrets:
        assert secret not in rendered
        assert secret not in captured_output
    assert response.json()["error"] == "internal"
