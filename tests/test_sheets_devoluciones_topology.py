from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

import pytest
from infra.rabbitmq import sheets_devoluciones_topology as topology_module
from infra.rabbitmq.sheets_devoluciones_topology import (
    CLAIMS_DLQ,
    CLAIMS_DLX,
    CLAIMS_QUEUE,
    CLAIMS_ROUTING_KEY,
    LEGACY_ORDERS_DLX,
    LEGACY_ORDERS_QUEUE,
    LIVE_EXCHANGE,
    QUARANTINE_QUEUE,
    REPLAY_EXCHANGE,
    RETRY_DELAYS_MS,
    QueueState,
    TopologySafetyError,
    _build_parser,
    _main_async,
    resolve_management_url,
    run_topology_command,
)

SHARED_EVENTS_QUEUE = "zeler.sheets.events"
SHARED_EVENTS_DLQ = f"{SHARED_EVENTS_QUEUE}.dlq"


@dataclass
class FakeMessage:
    queue_name: str
    body: bytes
    headers: dict[str, object]


class FakeBroker:
    def __init__(
        self,
        *,
        states: dict[str, QueueState] | None = None,
        messages: dict[str, list[bytes]] | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.states = dict(states or {})
        self.messages = {
            queue_name: [FakeMessage(queue_name, body, {}) for body in bodies]
            for queue_name, bodies in (messages or {}).items()
        }
        self.calls = calls if calls is not None else []
        self.queue_arguments: dict[str, dict[str, object]] = {}
        self.exchanges: set[str] = set()
        self.bindings: set[tuple[str, str, str]] = set()
        self.deleted_queues: list[str] = []
        self.deleted_exchanges: list[str] = []

    async def inspect_queue(self, queue_name: str) -> QueueState | None:
        self.calls.append(f"inspect:{queue_name}")
        state = self.states.get(queue_name)
        if state is None:
            return None
        return replace(state, ready=len(self.messages.get(queue_name, [])))

    async def declare_exchange(self, name: str, exchange_type: str) -> None:
        self.calls.append(f"declare_exchange:{name}:{exchange_type}")
        self.exchanges.add(name)

    async def declare_queue(self, name: str, arguments: dict[str, object]) -> None:
        self.calls.append(f"declare_queue:{name}")
        self.queue_arguments[name] = arguments
        self.states.setdefault(name, QueueState(ready=0, unacked=0, consumers=0))
        self.messages.setdefault(name, [])

    async def bind(self, exchange: str, queue_name: str, routing_key: str) -> None:
        self.calls.append(f"bind:{exchange}:{queue_name}:{routing_key}")
        self.bindings.add((exchange, queue_name, routing_key))

    async def unbind(self, exchange: str, queue_name: str, routing_key: str) -> None:
        self.calls.append(f"unbind:{exchange}:{queue_name}:{routing_key}")
        self.bindings.discard((exchange, queue_name, routing_key))

    async def get_message(self, queue_name: str) -> FakeMessage | None:
        queue_messages = self.messages.get(queue_name)
        if not queue_messages:
            return None
        message = queue_messages.pop(0)
        state = self.states[queue_name]
        self.states[queue_name] = replace(state, unacked=state.unacked + 1)
        self.calls.append(f"get:{queue_name}:{message.body.decode()}")
        return message

    async def publish_confirmed(self, queue_name: str, message: FakeMessage) -> None:
        self.calls.append(f"confirm:{queue_name}:{message.body.decode()}")
        self.messages.setdefault(queue_name, []).append(
            FakeMessage(queue_name, message.body, dict(message.headers))
        )

    async def ack(self, message: FakeMessage) -> None:
        self.calls.append(f"ack:{message.queue_name}:{message.body.decode()}")
        state = self.states[message.queue_name]
        self.states[message.queue_name] = replace(state, unacked=state.unacked - 1)

    async def delete_queue(self, queue_name: str) -> None:
        if queue_name not in self.states:
            return
        self.calls.append(f"delete_queue:{queue_name}")
        self.deleted_queues.append(queue_name)
        self.states.pop(queue_name, None)
        self.messages.pop(queue_name, None)

    async def delete_exchange(self, exchange: str) -> None:
        if exchange not in self.exchanges and exchange != LEGACY_ORDERS_DLX:
            return
        self.calls.append(f"delete_exchange:{exchange}")
        self.deleted_exchanges.append(exchange)
        self.exchanges.discard(exchange)

    async def close(self) -> None:
        self.calls.append("broker_close")


class FakeRuntime:
    def __init__(
        self,
        *,
        stopped: bool = True,
        healthy: bool = True,
        calls: list[str] | None = None,
    ) -> None:
        self.stopped = stopped
        self.healthy = healthy
        self.calls = calls if calls is not None else []

    async def worker_is_stopped(self) -> bool:
        self.calls.append("worker_is_stopped")
        return self.stopped

    async def worker_is_healthy(self) -> bool:
        self.calls.append("worker_is_healthy")
        return self.healthy

    async def stop_worker(self) -> None:
        self.calls.append("stop_worker")
        self.stopped = True
        self.healthy = False


def _state(*, ready: int = 0, unacked: int = 0, consumers: int = 0) -> QueueState:
    return QueueState(ready=ready, unacked=unacked, consumers=consumers)


def _legacy_names() -> tuple[str, ...]:
    return (
        LEGACY_ORDERS_QUEUE,
        f"{LEGACY_ORDERS_QUEUE}.dlq",
        *(f"{LEGACY_ORDERS_QUEUE}.retry.{delay}" for delay in RETRY_DELAYS_MS),
    )


def _dedicated_names() -> tuple[str, ...]:
    return (
        CLAIMS_QUEUE,
        CLAIMS_DLQ,
        *(f"{CLAIMS_QUEUE}.retry.{delay}" for delay in RETRY_DELAYS_MS),
    )


async def _fence_none() -> int:
    return 0


def test_management_url_is_derived_without_credentials_or_accepts_explicit_override() -> None:
    amqp_url = "amqps://operator:super-secret@rabbit.example.test/tenant"

    assert resolve_management_url(amqp_url, explicit_url=None) == "https://rabbit.example.test"
    assert (
        resolve_management_url(amqp_url, explicit_url="https://management.example.test/base")
        == "https://management.example.test/base"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "collection_name"),
    [
        (topology_module.stale_devoluciones_readiness, "sheets_read_model_freshness"),
        (
            topology_module.fence_active_devoluciones_operations,
            "sheets_devoluciones_operations",
        ),
    ],
)
async def test_rollback_database_mutations_work_when_worker_runtime_has_no_mongo_db(
    operation: Callable[[], Awaitable[int]],
    collection_name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[object] = []

    class FakeCollection:
        async def update_many(self, filter_spec: object, update: object) -> object:
            calls.append(("update_many", filter_spec, update))
            return type("UpdateResult", (), {"modified_count": 2})()

    class FakeDatabase:
        def __getitem__(self, collection_name: str) -> FakeCollection:
            calls.append(("collection", collection_name))
            return FakeCollection()

    class FakeMongoClient:
        def __init__(self, mongo_uri: str, **kwargs: object) -> None:
            calls.append(("client", kwargs))

        def __getitem__(self, database_name: str) -> FakeDatabase:
            calls.append(("database", database_name))
            return FakeDatabase()

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setenv(
        "MONGO_URI",
        "mongodb://runtime-user:runtime-secret@mongo:27017/zeler_platform_prod"
        "?replicaSet=rs0&authSource=admin",
    )
    monkeypatch.delenv("MONGO_DB", raising=False)
    monkeypatch.setattr(topology_module, "AsyncIOMotorClient", FakeMongoClient)

    modified = await operation()
    output = capsys.readouterr().out

    assert modified == 2
    assert ("database", "zeler_platform_prod") in calls
    assert ("collection", collection_name) in calls
    assert calls[-1] == "close"
    assert "runtime-secret" not in output


def test_rollback_database_resolution_preserves_existing_explicit_contract() -> None:
    database_name = topology_module._resolve_runtime_mongo_database_name(
        mongo_uri="mongodb://mongo:27017/?replicaSet=rs0",
        explicit_database="zeler_platform_explicit",
    )

    assert database_name == "zeler_platform_explicit"


@pytest.mark.asyncio
async def test_rollback_cli_sanitizes_uri_without_a_database_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def connect(**_kwargs: object) -> FakeBroker:
        return FakeBroker()

    monkeypatch.setenv("RABBITMQ_URL", "amqps://operator:broker-secret@rabbit.invalid/tenant")
    monkeypatch.setenv(
        "MONGO_URI",
        "mongodb://runtime-user:mongo-secret@mongo:27017/?replicaSet=rs0&authSource=admin",
    )
    monkeypatch.delenv("MONGO_DB", raising=False)
    monkeypatch.setattr(topology_module.RabbitMqBroker, "connect", connect)
    args = _build_parser().parse_args(["rollback", "--execute", "--format", "json"])

    exit_code = await _main_async(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert json.loads(output) == {"ok": False, "error_code": "topology_safety_gate_failed"}
    assert "mongo-secret" not in output
    assert "broker-secret" not in output


@pytest.mark.asyncio
async def test_cli_boundary_sanitizes_unexpected_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail_connect(**_kwargs: object) -> object:
        raise RuntimeError("amqps://operator:super-secret@rabbit.example.test/tenant")

    monkeypatch.setenv("RABBITMQ_URL", "amqps://operator:super-secret@rabbit.example.test/tenant")
    monkeypatch.setattr(
        "infra.rabbitmq.sheets_devoluciones_topology.RabbitMqBroker.connect",
        fail_connect,
    )
    args = _build_parser().parse_args(["plan", "--format", "json"])

    exit_code = await _main_async(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert json.loads(output) == {"ok": False, "error_code": "topology_safety_gate_failed"}
    assert "super-secret" not in output


@pytest.mark.asyncio
async def test_cli_boundary_sanitizes_broker_close_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class CloseFailBroker(FakeBroker):
        async def close(self) -> None:
            raise RuntimeError("raw-close-sentinel amqps://operator:secret@rabbit.invalid")

    broker = CloseFailBroker()

    async def connect(**_kwargs: object) -> CloseFailBroker:
        return broker

    monkeypatch.setenv("RABBITMQ_URL", "amqps://operator:secret@rabbit.invalid/tenant")
    monkeypatch.setattr(
        "infra.rabbitmq.sheets_devoluciones_topology.RabbitMqBroker.connect",
        connect,
    )
    args = _build_parser().parse_args(["plan", "--format", "json"])

    exit_code = await _main_async(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert json.loads(output) == {"ok": False, "error_code": "topology_safety_gate_failed"}
    assert "raw-close-sentinel" not in output
    assert "secret" not in output


@pytest.mark.asyncio
async def test_cli_boundary_sanitizes_operation_and_cleanup_errors_together(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class OperationAndCloseFailBroker(FakeBroker):
        async def inspect_queue(self, queue_name: str) -> QueueState | None:
            raise RuntimeError(f"raw-operation-sentinel:{queue_name}")

        async def close(self) -> None:
            raise RuntimeError("raw-cleanup-sentinel amqps://operator:secret@rabbit.invalid")

    async def connect(**_kwargs: object) -> OperationAndCloseFailBroker:
        return OperationAndCloseFailBroker()

    monkeypatch.setenv("RABBITMQ_URL", "amqps://operator:secret@rabbit.invalid/tenant")
    monkeypatch.setattr(
        "infra.rabbitmq.sheets_devoluciones_topology.RabbitMqBroker.connect",
        connect,
    )
    args = _build_parser().parse_args(["plan", "--format", "json"])

    exit_code = await _main_async(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert json.loads(output) == {"ok": False, "error_code": "topology_safety_gate_failed"}
    assert "raw-operation-sentinel" not in output
    assert "raw-cleanup-sentinel" not in output
    assert "secret" not in output


@pytest.mark.asyncio
async def test_plan_is_read_only_and_sanitized() -> None:
    broker = FakeBroker(
        states={
            CLAIMS_QUEUE: _state(ready=7, consumers=1),
            SHARED_EVENTS_QUEUE: _state(ready=219, consumers=1),
        }
    )

    report = await run_topology_command(
        "plan",
        execute=False,
        broker=broker,
        runtime=FakeRuntime(),
    )

    assert report.ok is True
    assert report.read_only is True
    assert report.mutations_attempted == 0
    assert report.summary["managed_queues_present"] == 1
    assert all(call.startswith("inspect:") for call in broker.calls)
    assert SHARED_EVENTS_QUEUE not in "\n".join(broker.calls)
    assert "amqp" not in report.render_markdown().lower()


@pytest.mark.asyncio
async def test_prestart_creates_unbound_claims_resources_and_confirm_drains_legacy() -> None:
    legacy_messages = {
        queue_name: [f"message-{index}".encode()]
        for index, queue_name in enumerate(_legacy_names())
    }
    broker = FakeBroker(
        states={
            **{name: _state(ready=1) for name in _legacy_names()},
            SHARED_EVENTS_QUEUE: _state(ready=219, consumers=1),
            SHARED_EVENTS_DLQ: _state(ready=3),
        },
        messages={
            **legacy_messages,
            SHARED_EVENTS_QUEUE: [f"shared-{index}".encode() for index in range(219)],
            SHARED_EVENTS_DLQ: [b"shared-dlq-1", b"shared-dlq-2", b"shared-dlq-3"],
        },
    )
    broker.bindings.update(
        {
            (LIVE_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY),
            (REPLAY_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY),
        }
    )

    report = await run_topology_command(
        "prestart",
        execute=True,
        broker=broker,
        runtime=FakeRuntime(stopped=True),
    )

    assert report.ok is True
    assert set(_dedicated_names()) | {QUARANTINE_QUEUE} <= set(broker.queue_arguments)
    assert broker.queue_arguments[CLAIMS_QUEUE] == {
        "x-dead-letter-exchange": CLAIMS_DLX,
        "x-dead-letter-routing-key": CLAIMS_DLQ,
    }
    for delay_name, ttl_ms in RETRY_DELAYS_MS.items():
        assert broker.queue_arguments[f"{CLAIMS_QUEUE}.retry.{delay_name}"] == {
            "x-message-ttl": ttl_ms,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": CLAIMS_QUEUE,
        }
    assert broker.bindings == {(CLAIMS_DLX, CLAIMS_DLQ, CLAIMS_DLQ)}
    for queue_name, messages in legacy_messages.items():
        body = messages[0].decode()
        assert broker.calls.index(f"confirm:{QUARANTINE_QUEUE}:{body}") < broker.calls.index(
            f"ack:{queue_name}:{body}"
        )
    assert set(broker.deleted_queues) == set(_legacy_names())
    assert broker.deleted_exchanges == [LEGACY_ORDERS_DLX]
    assert len(broker.messages[SHARED_EVENTS_QUEUE]) == 219
    assert len(broker.messages[SHARED_EVENTS_DLQ]) == 3
    assert not any(
        call.startswith((f"get:{SHARED_EVENTS_QUEUE}", f"delete_queue:{SHARED_EVENTS_QUEUE}"))
        for call in broker.calls
    )
    assert (LIVE_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY) not in broker.bindings
    assert (REPLAY_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY) not in broker.bindings


@pytest.mark.asyncio
async def test_prestart_requires_stopped_worker_before_any_mutation() -> None:
    broker = FakeBroker()

    with pytest.raises(TopologySafetyError, match="stopped"):
        await run_topology_command(
            "prestart",
            execute=True,
            broker=broker,
            runtime=FakeRuntime(stopped=False),
        )

    assert broker.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (_state(unacked=1), "unacknowledged"),
        (_state(consumers=1), "consumers"),
    ],
)
async def test_prestart_never_deletes_legacy_queue_while_unsafe(
    state: QueueState,
    reason: str,
) -> None:
    broker = FakeBroker(states={LEGACY_ORDERS_QUEUE: state})

    with pytest.raises(TopologySafetyError, match=reason):
        await run_topology_command(
            "prestart",
            execute=True,
            broker=broker,
            runtime=FakeRuntime(stopped=True),
        )

    assert LEGACY_ORDERS_QUEUE not in broker.deleted_queues


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unsafe_queue", "unsafe_state"),
    [
        (f"{LEGACY_ORDERS_QUEUE}.dlq", _state(unacked=1)),
        (f"{LEGACY_ORDERS_QUEUE}.retry.10m", _state(consumers=1)),
    ],
)
async def test_prestart_preflights_every_legacy_queue_before_any_mutation(
    unsafe_queue: str,
    unsafe_state: QueueState,
) -> None:
    legacy_names = _legacy_names()
    states = {name: _state() for name in legacy_names}
    states[LEGACY_ORDERS_QUEUE] = _state(ready=1)
    states[unsafe_queue] = unsafe_state
    broker = FakeBroker(
        states=states,
        messages={LEGACY_ORDERS_QUEUE: [b"must-remain-in-place"]},
    )

    with pytest.raises(TopologySafetyError):
        await run_topology_command(
            "prestart",
            execute=True,
            broker=broker,
            runtime=FakeRuntime(stopped=True),
        )

    inspected = {
        call.removeprefix("inspect:") for call in broker.calls if call.startswith("inspect:")
    }
    assert inspected == set(legacy_names)
    assert broker.messages[LEGACY_ORDERS_QUEUE][0].body == b"must-remain-in-place"
    assert broker.deleted_queues == []
    assert broker.deleted_exchanges == []
    assert not any(
        call.startswith(("declare_", "bind:", "unbind:", "get:", "confirm:", "ack:"))
        for call in broker.calls
    )


@pytest.mark.asyncio
async def test_prestart_is_idempotent_when_legacy_resources_are_absent() -> None:
    broker = FakeBroker()

    first = await run_topology_command(
        "prestart", execute=True, broker=broker, runtime=FakeRuntime(stopped=True)
    )
    second = await run_topology_command(
        "prestart", execute=True, broker=broker, runtime=FakeRuntime(stopped=True)
    )

    assert first.ok is True
    assert second.ok is True
    assert not broker.deleted_queues
    assert broker.deleted_exchanges == [LEGACY_ORDERS_DLX, LEGACY_ORDERS_DLX]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("healthy", "consumers", "reason"),
    [
        (False, 1, "health"),
        (True, 0, "consumer"),
    ],
)
async def test_bind_claims_fails_closed_until_health_and_passive_consumer_are_ready(
    healthy: bool,
    consumers: int,
    reason: str,
) -> None:
    broker = FakeBroker(states={CLAIMS_QUEUE: _state(consumers=consumers)})

    with pytest.raises(TopologySafetyError, match=reason):
        await run_topology_command(
            "bind-claims",
            execute=True,
            broker=broker,
            runtime=FakeRuntime(stopped=False, healthy=healthy),
        )

    assert broker.bindings == set()


@pytest.mark.asyncio
async def test_bind_claims_binds_live_and_replay_only_after_both_readiness_gates() -> None:
    broker = FakeBroker(states={CLAIMS_QUEUE: _state(consumers=1)})

    report = await run_topology_command(
        "bind-claims",
        execute=True,
        broker=broker,
        runtime=FakeRuntime(stopped=False, healthy=True),
    )

    assert report.ok is True
    assert broker.bindings == {
        (LIVE_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY),
        (REPLAY_EXCHANGE, CLAIMS_QUEUE, CLAIMS_ROUTING_KEY),
    }


@pytest.mark.asyncio
async def test_rollback_stales_first_then_stops_unbinds_and_confirm_quarantines() -> None:
    calls: list[str] = []
    messages = {
        queue_name: [f"rollback-{index}".encode()]
        for index, queue_name in enumerate(_dedicated_names())
    }
    broker = FakeBroker(
        states={
            **{name: _state(ready=1) for name in _dedicated_names()},
            QUARANTINE_QUEUE: _state(),
            SHARED_EVENTS_QUEUE: _state(ready=219, consumers=1),
        },
        messages={
            **messages,
            SHARED_EVENTS_QUEUE: [f"shared-{index}".encode() for index in range(219)],
        },
        calls=calls,
    )
    readiness = {"state": "reconciled"}

    class RepublishDuringStopRuntime(FakeRuntime):
        async def stop_worker(self) -> None:
            await super().stop_worker()
            calls.append("active_reconcile_republished")
            readiness["state"] = "reconciled"

    runtime = RepublishDuringStopRuntime(stopped=False, healthy=True, calls=calls)

    async def stale_readiness() -> int:
        calls.append("stale_readiness")
        readiness["state"] = "stale"
        return 4

    async def fence_operations() -> int:
        calls.append("fence_operations")
        return 1

    report = await run_topology_command(
        "rollback",
        execute=True,
        broker=broker,
        runtime=runtime,
        stale_readiness=stale_readiness,
        fence_operations=fence_operations,
    )

    assert report.ok is True
    assert calls[0:2] == ["stale_readiness", "stop_worker"]
    assert calls.index("active_reconcile_republished") < calls.index("fence_operations")
    assert calls[-1] == "stale_readiness"
    assert readiness["state"] == "stale"
    first_unbind = min(index for index, call in enumerate(calls) if call.startswith("unbind:"))
    first_get = min(index for index, call in enumerate(calls) if call.startswith("get:"))
    assert first_unbind < first_get
    claims_get = next(
        index for index, call in enumerate(calls) if call.startswith(f"get:{CLAIMS_QUEUE}:")
    )
    retry_get = next(
        index
        for index, call in enumerate(calls)
        if call.startswith(f"get:{CLAIMS_QUEUE}.retry.1s:")
    )
    assert retry_get < claims_get
    for queue_name, queue_messages in messages.items():
        body = queue_messages[0].decode()
        assert calls.index(f"confirm:{QUARANTINE_QUEUE}:{body}") < calls.index(
            f"ack:{queue_name}:{body}"
        )
    assert len(broker.messages[SHARED_EVENTS_QUEUE]) == 219
    assert broker.deleted_queues == []
    assert report.summary["readiness_markers_staled"] == 8
    assert report.summary["operations_fenced"] == 1


@pytest.mark.asyncio
async def test_rollback_refuses_drain_or_delete_with_unacked_claims() -> None:
    calls: list[str] = []
    broker = FakeBroker(
        states={
            CLAIMS_QUEUE: _state(unacked=1),
            QUARANTINE_QUEUE: _state(),
        },
        calls=calls,
    )

    async def stale_readiness() -> int:
        calls.append("stale_readiness")
        return 1

    with pytest.raises(TopologySafetyError, match="unacknowledged"):
        await run_topology_command(
            "rollback",
            execute=True,
            delete_dedicated=True,
            broker=broker,
            runtime=FakeRuntime(stopped=False, calls=calls),
            stale_readiness=stale_readiness,
            fence_operations=_fence_none,
        )

    assert CLAIMS_QUEUE not in broker.deleted_queues
    assert not any(call.startswith(f"get:{CLAIMS_QUEUE}") for call in calls)


@pytest.mark.asyncio
async def test_rollback_stale_failure_prevents_worker_stop_and_topology_mutation() -> None:
    calls: list[str] = []

    async def stale_readiness() -> int:
        calls.append("stale_readiness")
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_topology_command(
            "rollback",
            execute=True,
            broker=FakeBroker(calls=calls),
            runtime=FakeRuntime(stopped=False, calls=calls),
            stale_readiness=stale_readiness,
            fence_operations=_fence_none,
        )

    assert calls == ["stale_readiness"]


@pytest.mark.asyncio
async def test_confirm_failure_never_acks_or_deletes_source_queue() -> None:
    class FailingConfirmBroker(FakeBroker):
        async def publish_confirmed(self, queue_name: str, message: FakeMessage) -> None:
            self.calls.append(f"confirm_failed:{queue_name}:{message.body.decode()}")
            raise RuntimeError("publisher confirm failed")

    broker = FailingConfirmBroker(
        states={LEGACY_ORDERS_QUEUE: _state(ready=1)},
        messages={LEGACY_ORDERS_QUEUE: [b"legacy-order"]},
    )

    with pytest.raises(RuntimeError, match="publisher confirm failed"):
        await run_topology_command(
            "prestart",
            execute=True,
            broker=broker,
            runtime=FakeRuntime(stopped=True),
        )

    assert f"ack:{LEGACY_ORDERS_QUEUE}:legacy-order" not in broker.calls
    assert LEGACY_ORDERS_QUEUE not in broker.deleted_queues


@pytest.mark.asyncio
async def test_failure_rollback_optionally_deletes_only_drained_dedicated_resources() -> None:
    calls: list[str] = []
    broker = FakeBroker(
        states={
            **{name: _state() for name in _dedicated_names()},
            QUARANTINE_QUEUE: _state(),
        },
        calls=calls,
    )
    broker.exchanges.add(CLAIMS_DLX)

    async def stale_readiness() -> int:
        calls.append("stale_readiness")
        return 0

    report = await run_topology_command(
        "rollback",
        execute=True,
        delete_dedicated=True,
        failure_triggered=True,
        broker=broker,
        runtime=FakeRuntime(stopped=False, calls=calls),
        stale_readiness=stale_readiness,
        fence_operations=_fence_none,
    )

    assert report.ok is True
    assert set(broker.deleted_queues) == set(_dedicated_names())
    assert QUARANTINE_QUEUE not in broker.deleted_queues
    assert broker.deleted_exchanges == [CLAIMS_DLX]
    assert report.summary["failure_triggered"] == 1


@pytest.mark.asyncio
async def test_rollback_is_idempotent_when_dedicated_resources_are_absent() -> None:
    calls: list[str] = []

    async def stale_readiness() -> int:
        calls.append("stale_readiness")
        return 0

    report = await run_topology_command(
        "rollback",
        execute=True,
        delete_dedicated=True,
        broker=FakeBroker(calls=calls),
        runtime=FakeRuntime(stopped=True, healthy=False, calls=calls),
        stale_readiness=stale_readiness,
        fence_operations=_fence_none,
    )

    assert report.ok is True
    assert calls[0:2] == ["stale_readiness", "stop_worker"]
