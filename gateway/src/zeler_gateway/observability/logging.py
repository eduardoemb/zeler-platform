from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Literal

import structlog
from opentelemetry import trace

Environment = Literal["production", "test", "development"]


def configure_logging(environment: Environment = "production") -> None:
    """Configure structlog for environment-aware structured output.

    Production emits JSON for Cloud Logging ingestion. Test/development keep a
    human-readable console renderer so existing caplog/stdout assertions do not
    become coupled to JSON serialization.
    """

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if environment == "production"
            else structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def _add_trace_context(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return event_dict

    event_dict["trace_id"] = f"{span_context.trace_id:032x}"
    event_dict["span_id"] = f"{span_context.span_id:016x}"
    return event_dict
