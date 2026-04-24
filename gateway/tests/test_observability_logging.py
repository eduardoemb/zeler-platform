from __future__ import annotations

import json

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from zeler_gateway.observability.logging import configure_logging


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
