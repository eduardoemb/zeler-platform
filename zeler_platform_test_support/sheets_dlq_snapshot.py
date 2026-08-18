from __future__ import annotations

from dataclasses import dataclass, replace


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
