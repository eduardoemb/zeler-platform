from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from zeler_gateway.app import app
from zeler_gateway.observability.metrics import (
    MetricsRegistry,
    get_metrics_registry,
    record_latency,
    record_rate_limit_hit,
)

LATENCY_BUCKET_250_LINE = (
    'zeler_gateway_latency_ms_bucket{endpoint="/proxy/meli/items",le="250",module_id="repricer"} 2'
)
LATENCY_BUCKET_10_LINE = (
    'zeler_gateway_latency_ms_bucket{endpoint="/proxy/meli/items",le="10",module_id="repricer"} 1'
)


def test_metrics_endpoint_returns_prometheus_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_METRICS_ENABLED", "true")
    registry = get_metrics_registry()
    registry.reset()
    registry.increment_call_count(module_id="repricer", endpoint="/proxy/meli/items")

    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP zeler_gateway_call_count_total" in response.text
    assert "# TYPE zeler_gateway_call_count_total counter" in response.text
    assert 'module_id="repricer"' in response.text
    assert 'endpoint="/proxy/meli/items"' in response.text
    assert "zeler_gateway_call_count_total" in response.text


def test_metrics_endpoint_is_gated_by_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_METRICS_ENABLED", "false")

    response = TestClient(app).get("/metrics")

    assert response.status_code == 404
    assert response.text == "metrics disabled\n"


def test_rate_limit_hit_increments_counter() -> None:
    registry = MetricsRegistry()

    record_rate_limit_hit(
        registry=registry,
        module_id="repricer",
        endpoint="/proxy/meli/items",
    )
    record_rate_limit_hit(
        registry=registry,
        module_id="repricer",
        endpoint="/proxy/meli/items",
    )
    record_rate_limit_hit(
        registry=registry,
        module_id="sheets",
        endpoint="/proxy/meli/orders",
    )

    rendered = registry.render_prometheus()
    assert (
        'zeler_gateway_rate_limit_hits_total{endpoint="/proxy/meli/items",module_id="repricer"} 2'
        in rendered
    )
    assert (
        'zeler_gateway_rate_limit_hits_total{endpoint="/proxy/meli/orders",module_id="sheets"} 1'
        in rendered
    )


def test_latency_histogram_records_request_duration() -> None:
    registry = MetricsRegistry()
    started = time.perf_counter() - 0.125

    record_latency(
        registry=registry,
        module_id="repricer",
        endpoint="/proxy/meli/items",
        started=started,
        now_fn=lambda: started + 0.125,
    )
    record_latency(
        registry=registry,
        module_id="repricer",
        endpoint="/proxy/meli/items",
        started=started,
        now_fn=lambda: started + 0.007,
    )

    rendered = registry.render_prometheus()
    assert LATENCY_BUCKET_250_LINE in rendered
    assert LATENCY_BUCKET_10_LINE in rendered
    assert (
        'zeler_gateway_latency_ms_count{endpoint="/proxy/meli/items",module_id="repricer"} 2'
        in rendered
    )
    assert (
        'zeler_gateway_latency_ms_sum{endpoint="/proxy/meli/items",module_id="repricer"} 132.000'
        in rendered
    )
