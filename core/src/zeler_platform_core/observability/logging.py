from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Literal

import structlog
from opentelemetry import trace

Environment = Literal["production", "test", "development"]
OBSERVABILITY_HANDLER_MARKER = "_zeler_platform_observability"


def configure_logging(environment: Environment = "production") -> None:
    """Configure structlog for environment-aware structured output.

    Production emits JSON for Cloud Logging ingestion. Test/development keep a
    human-readable console renderer so existing caplog/stdout assertions do not
    become coupled to JSON serialization.
    """

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not any(
        getattr(handler, OBSERVABILITY_HANDLER_MARKER, False) for handler in root_logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(handler, OBSERVABILITY_HANDLER_MARKER, True)
        root_logger.addHandler(handler)
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
