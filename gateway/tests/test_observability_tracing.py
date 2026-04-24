from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from zeler_gateway.observability.tracing import configure_tracing


def test_configure_tracing_early_returns_in_test_env() -> None:
    app = FastAPI()

    provider = configure_tracing(
        app,
        service_name="zeler-meli-gateway",
        environment="test",
    )

    assert provider is None
    assert trace.get_tracer_provider().__class__.__name__ == "ProxyTracerProvider"


def test_configure_tracing_is_idempotent() -> None:
    app = FastAPI()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)

    provider = configure_tracing(
        app,
        service_name="zeler-meli-gateway",
        environment="development",
        span_processor=processor,
    )
    second_provider = configure_tracing(
        app,
        service_name="zeler-meli-gateway",
        environment="development",
        span_processor=processor,
    )

    assert provider is second_provider
    assert isinstance(trace.get_tracer_provider(), TracerProvider)


@pytest.mark.asyncio
async def test_fastapi_instrumentation_propagates_trace_id() -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    exporter = InMemorySpanExporter()
    configure_tracing(
        app,
        service_name="zeler-meli-gateway",
        environment="development",
        span_processor=SimpleSpanProcessor(exporter),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    finished_spans = exporter.get_finished_spans()
    assert any(span.name == "GET /health" for span in finished_spans)
    server_span = next(span for span in finished_spans if span.name == "GET /health")
    assert f"{server_span.context.trace_id:032x}" != "0" * 32
