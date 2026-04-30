from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from zeler_platform_core.observability import configure_logging as package_configure_logging
from zeler_platform_core.observability.logging import configure_logging

_OBSERVABILITY_HANDLER_MARKER = "_zeler_platform_observability"


@pytest.fixture(autouse=True)
def reset_logging_configuration() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    for handler in logging.getLogger().handlers[:]:
        if getattr(handler, _OBSERVABILITY_HANDLER_MARKER, False):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_package_reexports_configure_logging() -> None:
    assert package_configure_logging is configure_logging


def test_production_emits_json_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(environment="production")

    structlog.get_logger("test").info("observability.ready", component="gateway")

    captured = capsys.readouterr()
    log_line = captured.out.strip()
    payload = json.loads(log_line)
    assert payload["event"] == "observability.ready"
    assert payload["component"] == "gateway"
    assert payload["level"] == "info"
    assert isinstance(payload["timestamp"], str)


def test_test_environment_emits_console_renderer(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(environment="test")

    structlog.get_logger("test").info("observability.ready", component="gateway")

    captured = capsys.readouterr()
    log_line = captured.out.strip()
    try:
        json.loads(log_line)
    except json.JSONDecodeError:
        decoded_as_json = False
    else:
        decoded_as_json = True
    assert decoded_as_json is False
    assert "observability.ready" in log_line
    assert "component" in log_line


def test_configure_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(environment="test")
    configure_logging(environment="test")

    structlog.get_logger("test").info("observability.ready", component="gateway")

    captured = capsys.readouterr()
    log_lines = [line for line in captured.out.splitlines() if "observability.ready" in line]
    assert len(log_lines) == 1


def test_trace_context_processor_enriches_when_span_active(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(environment="production")

    span_context = SpanContext(
        trace_id=int("1" * 32, 16),
        span_id=int("2" * 16, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=trace.DEFAULT_TRACE_STATE,
    )
    with use_span(NonRecordingSpan(span_context), end_on_exit=False):
        structlog.get_logger("test").info("inside.span")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["trace_id"] == "1" * 32
    assert payload["span_id"] == "2" * 16


def test_trace_context_processor_omits_when_no_span(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(environment="production")

    structlog.get_logger("test").info("outside.span")

    payload = json.loads(capsys.readouterr().out.strip())
    assert "trace_id" not in payload
    assert "span_id" not in payload
