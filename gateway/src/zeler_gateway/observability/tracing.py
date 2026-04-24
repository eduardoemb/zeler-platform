from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

Environment = Literal["production", "test", "development"]

_TRACER_PROVIDER: TracerProvider | None = None
_INSTRUMENTED_APP_IDS: set[int] = set()
_REGISTERED_PROCESSOR_IDS: set[int] = set()
_HTTPX_INSTRUMENTED = False


def configure_tracing(
    app: FastAPI,
    *,
    service_name: str,
    environment: Environment = "production",
    otel_enabled: bool = True,
    gcp_project_id: str = "zeler-platform-dev",
    span_processor: SpanProcessor | None = None,
) -> TracerProvider | None:
    """Configure OpenTelemetry tracing for FastAPI and outbound httpx calls.

    Test environments are explicit no-ops because the Cloud Trace exporter needs
    GCP ADC and network access. Tests that need spans can pass an in-memory span
    processor with a non-test environment.
    """

    if environment == "test" or not otel_enabled:
        return None

    provider = _ensure_tracer_provider(
        service_name=service_name,
        gcp_project_id=gcp_project_id,
        span_processor=span_processor,
    )
    _instrument_fastapi(app, provider)
    _instrument_httpx()
    return provider


def _ensure_tracer_provider(
    *,
    service_name: str,
    gcp_project_id: str,
    span_processor: SpanProcessor | None,
) -> TracerProvider:
    global _TRACER_PROVIDER

    if _TRACER_PROVIDER is None:
        current_provider = trace.get_tracer_provider()
        if current_provider.__class__.__name__ == "ProxyTracerProvider":
            _TRACER_PROVIDER = TracerProvider(
                resource=Resource.create({SERVICE_NAME: service_name})
            )
            trace.set_tracer_provider(_TRACER_PROVIDER)
        elif isinstance(current_provider, TracerProvider):
            _TRACER_PROVIDER = current_provider
        else:  # pragma: no cover - defensive for non-SDK custom providers
            _TRACER_PROVIDER = TracerProvider(
                resource=Resource.create({SERVICE_NAME: service_name})
            )

    if span_processor is None:
        _add_span_processor_once(
            _TRACER_PROVIDER,
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=gcp_project_id)  # type: ignore[no-untyped-call]
            ),
        )
    else:
        _add_span_processor_once(_TRACER_PROVIDER, span_processor)

    return _TRACER_PROVIDER


def _add_span_processor_once(provider: TracerProvider, span_processor: SpanProcessor) -> None:
    processor_id = id(span_processor)
    if processor_id in _REGISTERED_PROCESSOR_IDS:
        return

    provider.add_span_processor(span_processor)
    _REGISTERED_PROCESSOR_IDS.add(processor_id)


def _instrument_fastapi(app: FastAPI, provider: TracerProvider) -> None:
    app_id = id(app)
    if app_id in _INSTRUMENTED_APP_IDS:
        return

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    _INSTRUMENTED_APP_IDS.add(app_id)


def _instrument_httpx() -> None:
    global _HTTPX_INSTRUMENTED

    if _HTTPX_INSTRUMENTED:
        return

    HTTPXClientInstrumentor().instrument()
    _HTTPX_INSTRUMENTED = True
