from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeAlias

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from zeler_gateway.config import Settings

MetricLabels: TypeAlias = tuple[tuple[str, str], ...]

LATENCY_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, math.inf)
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass
class HistogramValue:
    buckets: dict[float, int] = field(
        default_factory=lambda: {bucket: 0 for bucket in LATENCY_BUCKETS_MS}
    )
    count: int = 0
    total: float = 0.0


class MetricsRegistry:
    """Small in-process Prometheus text collector for gateway metrics.

    This intentionally keeps the metric label set bounded. `account_id` is not
    emitted as a Prometheus label because seller/account IDs are high-cardinality
    and would make the Cloud Run metrics endpoint unsafe under many tenants.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[MetricLabels, int]] = defaultdict(dict)
        self._histograms: dict[str, dict[MetricLabels, HistogramValue]] = defaultdict(dict)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    def increment_call_count(
        self, *, module_id: str, endpoint: str, status_code: int | None = None
    ) -> None:
        labels = _labels(
            module_id=module_id,
            endpoint=endpoint,
            status_code=str(status_code) if status_code is not None else None,
        )
        self.increment_counter("zeler_gateway_call_count_total", labels=labels)

    def increment_rate_limit_hit(self, *, module_id: str, endpoint: str) -> None:
        self.increment_counter(
            "zeler_gateway_rate_limit_hits_total",
            labels=_labels(module_id=module_id, endpoint=endpoint),
        )

    def increment_refresh_success(self) -> None:
        self.increment_counter(
            "zeler_gateway_refresh_success_total",
            labels=_labels(module_id="gateway", endpoint="refresh_worker"),
        )

    def increment_refresh_failure(self) -> None:
        self.increment_counter(
            "zeler_gateway_refresh_failure_total",
            labels=_labels(module_id="gateway", endpoint="refresh_worker"),
        )

    def increment_invalid_grant(self) -> None:
        self.increment_counter(
            "zeler_gateway_invalid_grant_total",
            labels=_labels(module_id="gateway", endpoint="refresh_worker"),
        )

    def increment_counter(self, name: str, *, labels: MetricLabels) -> None:
        with self._lock:
            current = self._counters[name].get(labels, 0)
            self._counters[name][labels] = current + 1

    def observe_latency_ms(self, *, module_id: str, endpoint: str, value_ms: float) -> None:
        labels = _labels(module_id=module_id, endpoint=endpoint)
        with self._lock:
            value = self._histograms["zeler_gateway_latency_ms"].setdefault(
                labels, HistogramValue()
            )
            value.count += 1
            value.total += value_ms
            for bucket in LATENCY_BUCKETS_MS:
                if value_ms <= bucket:
                    value.buckets[bucket] += 1

    def render_prometheus(self) -> str:
        with self._lock:
            counters: dict[str, dict[MetricLabels, int]] = {
                name: dict(series) for name, series in sorted(self._counters.items())
            }
            histograms: dict[str, dict[MetricLabels, HistogramValue]] = {
                name: {
                    labels: HistogramValue(
                        buckets=dict(value.buckets), count=value.count, total=value.total
                    )
                    for labels, value in series.items()
                }
                for name, series in sorted(self._histograms.items())
            }

        lines: list[str] = []
        for name, counter_series in counters.items():
            lines.extend(_counter_header(name))
            for labels, value in sorted(counter_series.items()):
                lines.append(f"{name}{_format_labels(labels)} {value}")

        for name, histogram_series in histograms.items():
            lines.extend(_histogram_header(name))
            for labels, histogram_value in sorted(histogram_series.items()):
                for bucket, count in sorted(histogram_value.buckets.items()):
                    bucket_labels = (*labels, ("le", _bucket_name(bucket)))
                    lines.append(f"{name}_bucket{_format_labels(bucket_labels)} {count}")
                lines.append(f"{name}_count{_format_labels(labels)} {histogram_value.count}")
                lines.append(f"{name}_sum{_format_labels(labels)} {histogram_value.total:.3f}")

        return "\n".join(lines) + "\n"


_REGISTRY = MetricsRegistry()
router = APIRouter(tags=["observability"])


def get_metrics_registry() -> MetricsRegistry:
    return _REGISTRY


def record_rate_limit_hit(
    *, registry: MetricsRegistry | None = None, module_id: str, endpoint: str
) -> None:
    (registry or _REGISTRY).increment_rate_limit_hit(module_id=module_id, endpoint=endpoint)


def record_latency(
    *,
    registry: MetricsRegistry | None = None,
    module_id: str,
    endpoint: str,
    started: float,
    now_fn: Callable[[], float] = time.perf_counter,
) -> None:
    duration_ms = max(0.0, (now_fn() - started) * 1000)
    (registry or _REGISTRY).observe_latency_ms(
        module_id=module_id, endpoint=endpoint, value_ms=duration_ms
    )


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    endpoint = _endpoint_label(request)
    _REGISTRY.observe_latency_ms(
        module_id="gateway", endpoint=endpoint, value_ms=(time.perf_counter() - started) * 1000
    )
    return response


@router.get("/metrics")
def metrics_endpoint() -> PlainTextResponse:
    if not Settings().otel_metrics_enabled:
        return PlainTextResponse("metrics disabled\n", status_code=404)
    return PlainTextResponse(
        _REGISTRY.render_prometheus(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )


def _labels(*, module_id: str, endpoint: str, status_code: str | None = None) -> MetricLabels:
    values = {
        "endpoint": _sanitize_label_value(endpoint),
        "module_id": _sanitize_label_value(module_id),
    }
    if status_code is not None:
        values["status_code"] = _sanitize_label_value(status_code)
    return tuple(sorted(values.items()))


def _format_labels(labels: MetricLabels) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape_label_value(value)}"' for key, value in sorted(labels))
    return f"{{{rendered}}}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _sanitize_label_value(value: str) -> str:
    return value if value else "unknown"


def _bucket_name(bucket: float) -> str:
    if math.isinf(bucket):
        return "+Inf"
    return str(int(bucket))


def _counter_header(name: str) -> list[str]:
    help_text = {
        "zeler_gateway_call_count_total": "Gateway request count.",
        "zeler_gateway_rate_limit_hits_total": "Gateway rate-limit rejections.",
        "zeler_gateway_refresh_success_total": "Successful token refresh operations.",
        "zeler_gateway_refresh_failure_total": "Failed token refresh operations.",
        "zeler_gateway_invalid_grant_total": "Meli invalid_grant refresh responses.",
    }.get(name, name)
    return [f"# HELP {name} {help_text}", f"# TYPE {name} counter"]


def _histogram_header(name: str) -> list[str]:
    return [f"# HELP {name} Gateway request latency in milliseconds.", f"# TYPE {name} histogram"]


def _endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path
