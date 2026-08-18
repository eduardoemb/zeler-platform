from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class FakeMessage:
    queue_name: str
    body: bytes
    headers: dict[str, object]
    delivery_tag: int = 0


@dataclass
class QueueState:
    ready: int = 0
    unacked: int = 0
    consumers: int = 0


def queue_state(*, ready: int = 0, unacked: int = 0, consumers: int = 0) -> QueueState:
    return QueueState(ready=ready, unacked=unacked, consumers=consumers)


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
        self._delivery_tag_counter = 0

    async def inspect_queue(
        self,
        queue_name: str,
        *,
        timeout: float | None = None,
    ) -> QueueState | None:
        del timeout
        self.calls.append(f"inspect:{queue_name}")
        state = self.states.get(queue_name)
        if state is None:
            return None
        return replace(state, ready=len(self.messages.get(queue_name, [])))

    async def get_one(self, queue_name: str) -> FakeMessage | None:
        self._delivery_tag_counter += 1
        queue_messages = self.messages.get(queue_name)
        if not queue_messages:
            return None
        message = queue_messages.pop(0)
        state = self.states[queue_name]
        self.states[queue_name] = replace(state, unacked=state.unacked + 1)
        message.delivery_tag = self._delivery_tag_counter
        self.calls.append(f"get_one:{queue_name}:{message.delivery_tag}:{message.body.decode()}")
        return message

    async def nack_requeue(self, delivery: FakeMessage) -> None:
        self.calls.append(f"nack_requeue:{delivery.queue_name}:{delivery.delivery_tag}")
        state = self.states[delivery.queue_name]
        self.states[delivery.queue_name] = replace(state, unacked=state.unacked - 1)
        self.messages.setdefault(delivery.queue_name, []).append(delivery)

    async def close_channel(self) -> None:
        self.calls.append("channel_close")


class FakeRuntime:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy

    async def worker_is_healthy(self) -> bool:
        return self.healthy


# Hermetic aio_pika seam (PR 1: broker + worker runtime).


@dataclass
class FakeDecl:
    message_count: int = 0
    consumer_count: int = 0


@dataclass
class FakeQueue:
    declaration_result: FakeDecl = field(default_factory=FakeDecl)


class FakeMsg:
    """Fake aio_pika delivery recording nack requests."""

    def __init__(
        self, *, body: bytes = b"{}", delivery_tag: int = 0, nack_error: Exception | None = None
    ) -> None:
        self.body, self.delivery_tag, self.nack_error = body, delivery_tag, nack_error
        self.nacks: list[tuple[bool, bool]] = []

    async def nack(self, *, requeue: bool = True, multiple: bool = False) -> None:
        self.nacks.append((requeue, multiple))
        if self.nack_error is not None:
            raise self.nack_error


class FakeChannel:
    """Fake aio_pika channel exposing failure-injecting seams."""

    def __init__(
        self,
        *,
        queue: FakeQueue | None = None,
        messages: dict[str, FakeMsg | None] | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.queue, self.messages = queue or FakeQueue(), messages or {}
        self.calls = calls if calls is not None else []
        self.passives: list[bool] = []
        self.no_acks: list[bool] = []

    async def declare_queue(
        self, name: str, *, passive: bool = True, timeout: float | None = None
    ) -> FakeQueue:
        self.passives.append(passive)
        self.calls.append(f"declare:{name}")
        return self.queue

    async def get(
        self, queue: str, *, no_ack: bool = False, fail: bool = False, timeout: float | None = None
    ) -> FakeMsg | None:
        self.no_acks.append(no_ack)
        self.calls.append(f"get:{queue}")
        return self.messages.get(queue)

    async def close(self) -> None:
        self.calls.append("channel_close")


class FakeConnection:
    """Fake aio_pika connection yielding a dedicated fake channel."""

    def __init__(
        self,
        *,
        channel: FakeChannel | None = None,
        calls: list[str] | None = None,
        channel_error: Exception | None = None,
    ) -> None:
        self._channel, self.calls, self.channel_error = (
            channel or FakeChannel(),
            calls if calls is not None else [],
            channel_error,
        )

    async def channel(self) -> FakeChannel:
        if self.channel_error is not None:
            raise self.channel_error
        self.calls.append("new_channel")
        return self._channel

    async def close(self) -> None:
        self.calls.append("connection_close")


class FakeConnect:
    """Lazy aio_pika.connect seam; records attempts, pops injected connections."""

    def __init__(self, connections: list[FakeConnection] | None = None) -> None:
        self.connections = connections or [FakeConnection()]
        self.calls: list[str] = []

    async def __call__(self, url: str = "", **_kwargs: object) -> FakeConnection:
        self.calls.append(url)
        return self.connections.pop(0)
