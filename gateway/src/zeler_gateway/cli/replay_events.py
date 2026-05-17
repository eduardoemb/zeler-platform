from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.request import urlopen
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient

from zeler_gateway.config import Settings
from zeler_gateway.webhooks.classifier import classify_webhook_event
from zeler_gateway.webhooks.publisher import (
    AioPikaWebhookPublisher,
    WebhookPublisher,
    publish_webhook_event,
)

ALLOWED_TOPICS = ("price_suggestion", "user-products-families")
BASELINE_COUNTS = {
    "price_suggestion": 35,
    "user-products-families": 5,
}
COALESCED_TOPICS = {"price_suggestion"}
WEBHOOK_EVENTS_PROJECTION = {
    "_id": 1,
    "topic": 1,
    "user_id": 1,
    "resource": 1,
    "received_at": 1,
    "published_at": 1,
    "schema_version": 1,
}
DEFAULT_MAX_TIME_MS = 5000
TOPIC_REQUIRED_GATE_QUEUES = {
    "price_suggestion": ("zeler.repricer.items",),
}
TOPIC_NO_GO_REASONS = {
    "user-products-families": (
        "Sheets user_products.* handler/consumer behavior is not defined; "
        "there is no active Sheets consumer path for user_products.*; "
        "approval flags do not define functional safety."
    ),
}
LEGACY_REMEDIATION_QUEUES = {
    "price_suggestion": ("zeler.repricer.price_suggestion",),
}
TOPIC_ROUTING_KEYS = {
    "price_suggestion": "price_suggestion.updated",
    "user-products-families": "user_products.families_updated",
}

DedupePolicy = Literal["latest-per-resource", "none", "replay-all"]


class ReplayConfigError(ValueError):
    pass


class ReplayAbortError(RuntimeError):
    pass


@dataclass(frozen=True)
class CliOptions:
    execute: bool
    run_id: str
    topics: tuple[str, ...]
    limits: dict[str, int]
    rate_per_sec: float
    concurrency: int
    dedupe_policy: DedupePolicy
    allow_user_products_families: bool = False
    plan_path: Path | None = None
    failure_ledger_path: Path | None = None
    rabbit_management_url: str | None = None
    rabbit_management_export: Path | None = None
    max_queue_ready: int = 100
    max_dlq_delta: int = 0
    require_consumer_health: bool = True
    abort_file: Path | None = None
    output_format: Literal["json", "markdown"] = "json"
    max_publish_attempts: int = 2


@dataclass(frozen=True)
class PlanOptions:
    run_id: str
    topics: tuple[str, ...]
    limits: dict[str, int] = field(default_factory=dict)
    max_time_ms: int = DEFAULT_MAX_TIME_MS
    dedupe_policy: DedupePolicy = "latest-per-resource"
    allow_user_products_families: bool = False
    expected_counts: dict[str, int] | None = None


@dataclass(frozen=True)
class PlannedEvent:
    id: str
    topic: str
    user_id: int
    resource: str
    received_at: datetime
    routing_key: str
    idempotency_key: str
    event: dict[str, Any]
    skip_reason: str | None = None

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "_id": self.id,
            "topic": self.topic,
            "user_id": self.user_id,
            "resource": self.resource,
            "received_at": self.received_at.isoformat(),
            "routing_key": self.routing_key,
            "idempotency_key": self.idempotency_key,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class TopicPlanCount:
    total: int
    selected: int
    skipped: int


@dataclass(frozen=True)
class ReplayPlan:
    run_id: str
    selected: tuple[PlannedEvent, ...]
    skipped: tuple[PlannedEvent, ...]
    topic_counts: dict[str, TopicPlanCount]
    created_at: datetime

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "topic_counts": {
                topic: {
                    "total": count.total,
                    "selected": count.selected,
                    "skipped": count.skipped,
                }
                for topic, count in self.topic_counts.items()
            },
            "selected": [event.to_sanitized_dict() for event in self.selected],
            "skipped": [event.to_sanitized_dict() for event in self.skipped],
        }


@dataclass(frozen=True)
class QueueSnapshot:
    name: str
    ready: int
    unacked: int
    consumers: int
    dlq_ready: int
    routing_keys: tuple[str, ...] = ()
    healthy: bool = True
    recent_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class QueueRemediationItem:
    topic: str
    queue: str
    ready: int | None
    unacked: int | None
    consumers: int | None
    dlq_ready: int | None
    remediation_only: bool = True
    approval_required: bool = True
    recommendation: str = (
        "Inspect/report first only. Capture a sanitized Rabbit export, verify the "
        "active queue is healthy, then seek explicit operator approval before any "
        "purge/delete/requeue/bind/unbind/publish/replay/deploy/build action."
    )

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "queue": self.queue,
            "ready": self.ready,
            "unacked": self.unacked,
            "consumers": self.consumers,
            "dlq_ready": self.dlq_ready,
            "remediation_only": self.remediation_only,
            "approval_required": self.approval_required,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class RabbitRemediationReport:
    legacy_queues: tuple[QueueRemediationItem, ...] = ()

    def to_sanitized_dict(self) -> dict[str, Any]:
        return {
            "legacy_queues": [item.to_sanitized_dict() for item in self.legacy_queues],
            "non_actions": (
                "No automated purge/delete/requeue/bind/unbind/publish/replay/"
                "deploy/build is performed by replay gate evaluation."
            ),
        }


RabbitGateProvider = Callable[[], Sequence[QueueSnapshot]]


def _routing_key_matches(binding_key: str, routing_key: str) -> bool:
    if binding_key == routing_key:
        return True
    binding_parts = binding_key.split(".")
    routing_parts = routing_key.split(".")
    for index, binding_part in enumerate(binding_parts):
        if binding_part == "#":
            return True
        if index >= len(routing_parts):
            return False
        if binding_part == "*":
            continue
        if binding_part != routing_parts[index]:
            return False
    return len(binding_parts) == len(routing_parts)


def build_rabbit_remediation_report(
    snapshots: Sequence[QueueSnapshot], topics: Sequence[str]
) -> RabbitRemediationReport:
    by_name = {snapshot.name: snapshot for snapshot in snapshots}
    items: list[QueueRemediationItem] = []
    for topic in topics:
        _validate_topic_allowed(topic)
        for queue_name in LEGACY_REMEDIATION_QUEUES.get(topic, ()):
            snapshot = by_name.get(queue_name)
            items.append(
                QueueRemediationItem(
                    topic=topic,
                    queue=queue_name,
                    ready=snapshot.ready if snapshot is not None else None,
                    unacked=snapshot.unacked if snapshot is not None else None,
                    consumers=snapshot.consumers if snapshot is not None else None,
                    dlq_ready=snapshot.dlq_ready if snapshot is not None else None,
                )
            )
    return RabbitRemediationReport(legacy_queues=tuple(items))


def _parse_topics(raw_topics: str) -> tuple[str, ...]:
    topics = tuple(topic.strip() for topic in raw_topics.split(",") if topic.strip())
    if not topics:
        raise ReplayConfigError("at least one topic is required")
    unsupported = sorted(set(topics) - set(ALLOWED_TOPICS))
    if unsupported:
        raise ReplayConfigError(f"unsupported topic(s): {', '.join(unsupported)}")
    return topics


def _parse_limits(raw_limits: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for raw_limit in raw_limits:
        if "=" not in raw_limit:
            raise ReplayConfigError("--limit must use topic=count")
        topic, raw_count = raw_limit.split("=", 1)
        topic = topic.strip()
        if topic not in ALLOWED_TOPICS:
            raise ReplayConfigError(f"unsupported topic in --limit: {topic}")
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise ReplayConfigError("--limit count must be an integer") from exc
        if count < 1:
            raise ReplayConfigError("--limit count must be positive")
        limits[topic] = count
    return limits


def parse_replay_args(argv: list[str] | None = None) -> CliOptions:
    parser = argparse.ArgumentParser(description="Safely plan or replay stored Meli webhook events")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--topics", default=",".join(ALLOWED_TOPICS))
    parser.add_argument("--limit", action="append", default=[])
    parser.add_argument("--rate-per-sec", type=float, default=1.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--dedupe-policy",
        choices=("latest-per-resource", "none", "replay-all"),
        default="latest-per-resource",
    )
    parser.add_argument("--allow-user-products-families", action="store_true")
    parser.add_argument("--plan-path", type=Path)
    parser.add_argument("--failure-ledger-path", type=Path)
    parser.add_argument("--rabbit-management-url")
    parser.add_argument("--rabbit-management-export", type=Path)
    parser.add_argument("--max-queue-ready", type=int, default=100)
    parser.add_argument("--max-dlq-delta", type=int, default=0)
    parser.add_argument("--no-require-consumer-health", action="store_true")
    parser.add_argument("--abort-file", type=Path)
    parser.add_argument("--output-format", choices=("json", "markdown"), default="json")
    parser.add_argument("--max-publish-attempts", type=int, default=2)
    args = parser.parse_args(argv)

    if args.execute and not args.run_id:
        raise ReplayConfigError("--run-id is required when --execute is set")
    if args.rate_per_sec <= 0 or args.rate_per_sec > 1:
        raise ReplayConfigError("--rate-per-sec must be greater than 0 and no faster than 1")
    if args.concurrency != 1:
        raise ReplayConfigError("concurrency must be 1 for safe replay")
    if args.max_queue_ready < 0:
        raise ReplayConfigError("--max-queue-ready must be non-negative")
    if args.max_dlq_delta < 0:
        raise ReplayConfigError("--max-dlq-delta must be non-negative")
    if args.max_publish_attempts < 1:
        raise ReplayConfigError("--max-publish-attempts must be positive")
    gate_source_count = sum(
        source is not None for source in (args.rabbit_management_export, args.rabbit_management_url)
    )
    if args.execute and gate_source_count == 0:
        raise ReplayConfigError("Rabbit management gate source is required when --execute is set")
    if args.execute and gate_source_count > 1:
        raise ReplayConfigError(
            "provide only one Rabbit management gate source: "
            "--rabbit-management-export or --rabbit-management-url"
        )

    run_id = args.run_id or f"dry-run-{uuid4()}"
    return CliOptions(
        execute=bool(args.execute),
        run_id=run_id,
        topics=_parse_topics(args.topics),
        limits=_parse_limits(args.limit),
        rate_per_sec=float(args.rate_per_sec),
        concurrency=int(args.concurrency),
        dedupe_policy=args.dedupe_policy,
        allow_user_products_families=bool(args.allow_user_products_families),
        plan_path=args.plan_path,
        failure_ledger_path=args.failure_ledger_path,
        rabbit_management_url=args.rabbit_management_url,
        rabbit_management_export=args.rabbit_management_export,
        max_queue_ready=int(args.max_queue_ready),
        max_dlq_delta=int(args.max_dlq_delta),
        require_consumer_health=not bool(args.no_require_consumer_health),
        abort_file=args.abort_file,
        output_format=args.output_format,
        max_publish_attempts=int(args.max_publish_attempts),
    )


def _validate_topic_allowed(topic: str) -> None:
    if topic not in ALLOWED_TOPICS:
        raise ReplayConfigError(f"unsupported topic: {topic}")


def _validate_required_fields(event: dict[str, Any]) -> None:
    required = ("_id", "topic", "user_id", "resource", "received_at", "schema_version")
    missing = [field_name for field_name in required if field_name not in event]
    if missing:
        raise ReplayConfigError(f"corrupt webhook event missing {', '.join(missing)}")
    if not str(event["resource"]):
        raise ReplayConfigError("corrupt webhook event has empty resource")
    if event["schema_version"] != 1:
        raise ReplayConfigError("corrupt webhook event has unsupported schema_version")
    if not isinstance(event["received_at"], datetime):
        raise ReplayConfigError("corrupt webhook event has non-date received_at")


def _planned_event(event: dict[str, Any], *, skip_reason: str | None = None) -> PlannedEvent:
    _validate_required_fields(event)
    classified = classify_webhook_event(event)
    return PlannedEvent(
        id=str(event["_id"]),
        topic=str(event["topic"]),
        user_id=int(event["user_id"]),
        resource=str(event["resource"]),
        received_at=event["received_at"],
        routing_key=classified.routing_key,
        idempotency_key=classified.idempotency_key,
        event=dict(event),
        skip_reason=skip_reason,
    )


def _coalesce_latest(events: list[PlannedEvent]) -> tuple[list[PlannedEvent], list[PlannedEvent]]:
    latest_by_key: dict[tuple[str, int, str], PlannedEvent] = {}
    skipped: list[PlannedEvent] = []
    for event in events:
        key = (event.topic, event.user_id, event.resource)
        existing = latest_by_key.get(key)
        if existing is None or event.received_at > existing.received_at:
            if existing is not None:
                skipped.append(
                    PlannedEvent(**{**existing.__dict__, "skip_reason": "coalesced_older"})
                )
            latest_by_key[key] = event
        else:
            skipped.append(PlannedEvent(**{**event.__dict__, "skip_reason": "coalesced_older"}))
    return list(latest_by_key.values()), skipped


async def _load_topic_events(
    collection: Any, topic: str, options: PlanOptions
) -> list[dict[str, Any]]:
    query = {"published_at": None, "topic": topic}
    if options.expected_counts is not None and topic in options.expected_counts:
        actual_count = await collection.count_documents(query)
        expected_count = options.expected_counts[topic]
        if actual_count != expected_count:
            raise ReplayConfigError(
                f"baseline drift for {topic}: expected {expected_count}, found {actual_count}"
            )
    cursor = collection.find(query, WEBHOOK_EVENTS_PROJECTION).sort("received_at", 1)
    if topic in options.limits:
        cursor = cursor.limit(options.limits[topic])
    cursor = cursor.max_time_ms(options.max_time_ms)
    return [event async for event in cursor]


async def build_replay_plan(db: Any, options: PlanOptions) -> ReplayPlan:
    if not options.run_id:
        raise ReplayConfigError("run_id is required")
    for topic in options.topics:
        _validate_topic_allowed(topic)
    collection = db["webhook_events"]
    selected: list[PlannedEvent] = []
    skipped: list[PlannedEvent] = []
    topic_counts: dict[str, TopicPlanCount] = {}

    for topic in options.topics:
        topic_events = [
            _planned_event(event) for event in await _load_topic_events(collection, topic, options)
        ]
        topic_selected: list[PlannedEvent]
        topic_skipped: list[PlannedEvent]
        if topic in TOPIC_NO_GO_REASONS:
            topic_selected = []
            topic_skipped = [
                PlannedEvent(**{**event.__dict__, "skip_reason": "topic_no_go"})
                for event in topic_events
            ]
        elif options.dedupe_policy == "latest-per-resource" and topic in COALESCED_TOPICS:
            topic_selected, topic_skipped = _coalesce_latest(topic_events)
        else:
            topic_selected = topic_events
            topic_skipped = []
        selected.extend(topic_selected)
        skipped.extend(topic_skipped)
        topic_counts[topic] = TopicPlanCount(
            total=len(topic_events), selected=len(topic_selected), skipped=len(topic_skipped)
        )

    return ReplayPlan(
        run_id=options.run_id,
        selected=tuple(
            sorted(selected, key=lambda event: (event.topic, event.received_at, event.id))
        ),
        skipped=tuple(
            sorted(skipped, key=lambda event: (event.topic, event.received_at, event.id))
        ),
        topic_counts=topic_counts,
        created_at=datetime.now(UTC),
    )


async def replay_events(
    db: Any,
    *,
    publisher: WebhookPublisher,
    topic: str | None = None,
    dry_run: bool = True,
    limit: int = 100,
) -> ReplayPlan:
    """Backward-compatible wrapper that now plans safely by default.

    The legacy CLI used this helper to publish directly. The hardened replay path never
    publishes from planning; execution goes through ``execute_replay_plan`` below.
    """
    del publisher, dry_run
    topics = (topic,) if topic is not None else tuple(ALLOWED_TOPICS)
    limits = {selected_topic: limit for selected_topic in topics}
    return await build_replay_plan(
        db,
        PlanOptions(run_id=f"dry-run-{uuid4()}", topics=topics, limits=limits),
    )


async def _run_from_options(options: CliOptions) -> ReplayPlan:
    settings = Settings()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(settings.mongo_uri)
    try:
        plan = await build_replay_plan(
            client[settings.mongo_db],
            PlanOptions(
                run_id=options.run_id,
                topics=options.topics,
                limits=options.limits,
                dedupe_policy=options.dedupe_policy,
                allow_user_products_families=options.allow_user_products_families,
                expected_counts=BASELINE_COUNTS,
            ),
        )
        if options.plan_path is not None:
            options.plan_path.write_text(
                json.dumps(plan.to_sanitized_dict(), indent=2), encoding="utf-8"
            )
        if options.execute:
            gate_provider = _rabbit_gate_provider_from_options(options)
            _enforce_rabbit_gate(gate_provider(), options.topics, options)
            publisher = AioPikaWebhookPublisher(rabbitmq_url=settings.rabbitmq_url)
            await execute_replay_plan(
                client[settings.mongo_db],
                plan,
                publisher=publisher,
                options=options,
                gate_provider=gate_provider,
            )
        return plan
    finally:
        client.close()


def format_replay_output(
    plan: ReplayPlan,
    output_format: Literal["json", "markdown"],
    *,
    remediation_report: RabbitRemediationReport | None = None,
) -> str:
    sanitized = plan.to_sanitized_dict()
    if remediation_report is not None:
        sanitized["rabbit_remediation"] = remediation_report.to_sanitized_dict()
    if output_format == "json":
        return json.dumps(sanitized, indent=2)
    lines = [
        f"# Webhook replay plan `{plan.run_id}`",
        "",
        "| Topic | Total | Selected | Skipped |",
        "|---|---:|---:|---:|",
    ]
    for topic, count in plan.topic_counts.items():
        lines.append(f"| `{topic}` | {count.total} | {count.selected} | {count.skipped} |")
    if remediation_report is not None and remediation_report.legacy_queues:
        lines.extend(
            [
                "",
                "## Rabbit remediation-only queues",
                "",
                "| Topic | Queue | Ready | Unacked | Consumers | DLQ | Recommendation |",
                "|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for item in remediation_report.legacy_queues:
            lines.append(
                "| "
                f"`{item.topic}` | `{item.queue}` | {item.ready} | {item.unacked} | "
                f"{item.consumers} | {item.dlq_ready} | remediation-only; "
                f"{item.recommendation} |"
            )
        lines.extend(["", remediation_report.to_sanitized_dict()["non_actions"]])
    return "\n".join(lines)


def _format_output(plan: ReplayPlan, output_format: Literal["json", "markdown"]) -> str:
    return format_replay_output(plan, output_format)


def main(argv: list[str] | None = None) -> None:
    options = parse_replay_args(argv)
    plan = asyncio.run(_run_from_options(options))
    remediation_report = None
    if options.rabbit_management_export is not None or options.rabbit_management_url is not None:
        remediation_report = build_rabbit_remediation_report(
            _rabbit_gate_provider_from_options(options)(), options.topics
        )
    print(format_replay_output(plan, options.output_format, remediation_report=remediation_report))


class FailureLedger(Protocol):
    def write(self, row: dict[str, Any]) -> None: ...


class JsonlFailureLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, sort_keys=True, default=str))
            file.write("\n")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sanitize_error(exc: BaseException | str) -> str:
    message = str(exc)
    message = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", "[redacted-url]", message)
    for token in ("access_token", "refresh_token", "secret", "password", "credential"):
        message = re.sub(token, "[redacted]", message, flags=re.IGNORECASE)
    return message


def _ledger_row(
    event: PlannedEvent,
    *,
    run_id: str,
    status: str,
    attempt: int,
    error_class: str | None = None,
    error: BaseException | str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "_id": event.id,
        "topic": event.topic,
        "resource": event.resource,
        "routing_key": event.routing_key,
        "idempotency_key": event.idempotency_key,
        "status": status,
        "attempt": attempt,
        "timestamp": _utc_now().isoformat(),
    }
    if error_class is not None:
        row["error_class"] = error_class
    if error is not None:
        row["error"] = _sanitize_error(error)
    return row


def _resolve_ledger(options: CliOptions, ledger: FailureLedger | None) -> FailureLedger | None:
    if ledger is not None:
        return ledger
    if options.failure_ledger_path is not None:
        return JsonlFailureLedger(options.failure_ledger_path)
    return None


def _write_ledger(ledger: FailureLedger | None, row: dict[str, Any]) -> None:
    if ledger is not None:
        ledger.write(row)


def _is_transient_publish_error(exc: BaseException) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _queue_snapshot_from_export(queue: dict[str, Any]) -> QueueSnapshot:
    return QueueSnapshot(
        name=str(queue["name"]),
        ready=int(queue.get("messages_ready", queue.get("ready", 0))),
        unacked=int(queue.get("messages_unacknowledged", queue.get("unacked", 0))),
        consumers=int(queue.get("consumers", 0)),
        dlq_ready=int(queue.get("dlq_ready", queue.get("dlq", 0))),
        routing_keys=tuple(str(key) for key in queue.get("routing_keys", ())),
        healthy=bool(queue.get("healthy", True)),
        recent_errors=tuple(str(error) for error in queue.get("recent_errors", ())),
    )


def load_rabbit_gate_state_from_export(path: Path) -> list[QueueSnapshot]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queues = payload if isinstance(payload, list) else payload.get("queues", [])
    return [_queue_snapshot_from_export(queue) for queue in queues]


def load_rabbit_gate_state_from_management_url(url: str) -> list[QueueSnapshot]:
    with urlopen(url, timeout=10) as response:  # noqa: S310 - operator-supplied local/management URL
        payload = json.loads(response.read().decode("utf-8"))
    queues = payload if isinstance(payload, list) else payload.get("queues", [])
    return [_queue_snapshot_from_export(queue) for queue in queues]


def _ensure_execute_gate_source(
    options: CliOptions, gate_provider: RabbitGateProvider | None = None
) -> None:
    if not options.execute:
        return
    gate_source_count = sum(
        source is not None
        for source in (options.rabbit_management_export, options.rabbit_management_url)
    )
    if gate_source_count == 0 and gate_provider is None:
        raise ReplayConfigError("Rabbit management gate source is required when --execute is set")
    if gate_source_count > 1:
        raise ReplayConfigError(
            "provide only one Rabbit management gate source: "
            "--rabbit-management-export or --rabbit-management-url"
        )


def _rabbit_gate_provider_from_options(options: CliOptions) -> RabbitGateProvider:
    _ensure_execute_gate_source(options)
    if options.rabbit_management_export is not None:
        export_path = options.rabbit_management_export
        return lambda: load_rabbit_gate_state_from_export(export_path)
    if options.rabbit_management_url is not None:
        management_url = options.rabbit_management_url
        return lambda: load_rabbit_gate_state_from_management_url(management_url)
    raise ReplayConfigError("Rabbit management gate source is required when --execute is set")


def evaluate_rabbit_gates(
    snapshots: Sequence[QueueSnapshot], topics: Sequence[str], options: CliOptions
) -> GateDecision:
    if options.abort_file is not None and options.abort_file.exists():
        return GateDecision(False, "operator_abort", str(options.abort_file))

    by_name = {snapshot.name: snapshot for snapshot in snapshots}
    for topic in topics:
        _validate_topic_allowed(topic)
        if topic in TOPIC_NO_GO_REASONS:
            return GateDecision(False, "topic_no_go", TOPIC_NO_GO_REASONS[topic])
        required_routing_key = TOPIC_ROUTING_KEYS[topic]
        for queue_name in TOPIC_REQUIRED_GATE_QUEUES.get(topic, ()):
            snapshot = by_name.get(queue_name)
            detail = f"active consumer path {queue_name}"
            if snapshot is None:
                return GateDecision(False, "missing_consumer", detail)
            if snapshot.ready > options.max_queue_ready:
                return GateDecision(False, "queue_cap_exceeded", detail)
            if snapshot.dlq_ready > options.max_dlq_delta:
                return GateDecision(False, "dlq_delta_exceeded", detail)
            if options.require_consumer_health and snapshot.consumers < 1:
                return GateDecision(False, "missing_consumer", detail)
            if options.require_consumer_health and (
                not snapshot.healthy
                or any(
                    marker in snapshot.recent_errors
                    for marker in ("worker.message.requeued", "worker.message.dlq")
                )
            ):
                return GateDecision(False, "consumer_health_failed", detail)
            if snapshot.routing_keys and not any(
                _routing_key_matches(binding_key, required_routing_key)
                for binding_key in snapshot.routing_keys
            ):
                return GateDecision(False, "wrong_routing", detail)
    return GateDecision(True, "ok")


def _enforce_rabbit_gate(
    snapshots: Sequence[QueueSnapshot], topics: Sequence[str], options: CliOptions
) -> None:
    gate_decision = evaluate_rabbit_gates(snapshots, topics, options)
    if not gate_decision.allowed:
        detail = f": {gate_decision.detail}" if gate_decision.detail else ""
        raise ReplayAbortError(f"Rabbit gate failed: {gate_decision.reason}{detail}")


async def execute_replay_plan(
    db: Any,
    plan: ReplayPlan,
    *,
    publisher: WebhookPublisher,
    options: CliOptions,
    ledger: FailureLedger | None = None,
    gate_provider: RabbitGateProvider | None = None,
) -> None:
    _ensure_execute_gate_source(options, gate_provider)
    resolved_gate_provider = gate_provider
    if resolved_gate_provider is None and (
        options.rabbit_management_export is not None or options.rabbit_management_url is not None
    ):
        resolved_gate_provider = _rabbit_gate_provider_from_options(options)
    resolved_ledger = _resolve_ledger(options, ledger)
    collection = db["webhook_events"]
    delay_seconds = 1 / options.rate_per_sec

    for index, event in enumerate(plan.selected):
        if resolved_gate_provider is not None:
            try:
                _enforce_rabbit_gate(resolved_gate_provider(), (event.topic,), options)
            except ReplayAbortError as exc:
                _write_ledger(
                    resolved_ledger,
                    _ledger_row(
                        event,
                        run_id=plan.run_id,
                        status="aborted",
                        attempt=0,
                        error_class="RabbitGateFailed",
                        error=exc,
                    ),
                )
                raise

        if options.abort_file is not None and options.abort_file.exists():
            _write_ledger(
                resolved_ledger,
                _ledger_row(
                    event,
                    run_id=plan.run_id,
                    status="aborted",
                    attempt=0,
                    error_class="operator_abort",
                    error="abort file present",
                ),
            )
            raise ReplayAbortError("operator abort requested")

        try:
            _validate_required_fields(event.event)
        except ReplayConfigError as exc:
            _write_ledger(
                resolved_ledger,
                _ledger_row(
                    event,
                    run_id=plan.run_id,
                    status="quarantined",
                    attempt=0,
                    error_class="schema",
                    error=exc,
                ),
            )
            continue

        last_error: BaseException | None = None
        published = False
        for attempt in range(1, options.max_publish_attempts + 1):
            try:
                await publish_webhook_event(event.event, publisher=publisher, trace_id=plan.run_id)
                published = True
                break
            except Exception as exc:  # noqa: BLE001 - ledger needs sanitized class for all failures
                last_error = exc
                if not _is_transient_publish_error(exc) or attempt >= options.max_publish_attempts:
                    break

        if not published:
            error = last_error or RuntimeError("publish failed without exception")
            _write_ledger(
                resolved_ledger,
                _ledger_row(
                    event,
                    run_id=plan.run_id,
                    status="failed",
                    attempt=options.max_publish_attempts,
                    error_class=error.__class__.__name__,
                    error=error,
                ),
            )
            continue

        published_at = _utc_now()
        update_result = await collection.update_one(
            {"_id": event.id, "published_at": None},
            {
                "$set": {
                    "published_at": published_at,
                    "classification": event.routing_key,
                    "replay_run_id": plan.run_id,
                }
            },
        )
        if (
            getattr(update_result, "matched_count", 0) != 1
            or getattr(update_result, "modified_count", 0) != 1
        ):
            _write_ledger(
                resolved_ledger,
                _ledger_row(
                    event,
                    run_id=plan.run_id,
                    status="mark_ambiguous",
                    attempt=1,
                    error_class="MongoMarkAmbiguous",
                    error="ambiguous Mongo mark",
                ),
            )
            raise ReplayAbortError("ambiguous Mongo mark")

        _write_ledger(
            resolved_ledger,
            _ledger_row(event, run_id=plan.run_id, status="published", attempt=1),
        )

        if index < len(plan.selected) - 1:
            await asyncio.sleep(delay_seconds)


if __name__ == "__main__":
    main()
