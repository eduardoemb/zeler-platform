from __future__ import annotations

import json
from typing import Any


class FakeMessage:
    def __init__(
        self,
        body: dict[str, Any] | bytes,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
        self.headers = headers or {}
        self.acked = False
        self.nacks: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = False) -> None:
        self.nacks.append(requeue)


class FakeExchange:
    def __init__(self) -> None:
        self.bindings: list[tuple[FakeQueue, str]] = []


class FakeQueue:
    def __init__(self) -> None:
        self.bindings: list[tuple[FakeExchange, str]] = []
        self.consumer: Any = None

    async def bind(self, exchange: FakeExchange, routing_key: str) -> None:
        self.bindings.append((exchange, routing_key))

    async def consume(self, callback: Any) -> None:
        self.consumer = callback


class FakeChannel:
    def __init__(self) -> None:
        self.qos: list[int] = []
        self.exchange = FakeExchange()
        self.queue = FakeQueue()
        self.declared_exchanges: list[tuple[str, Any, bool]] = []
        self.declared_queues: list[tuple[str, bool, dict[str, object]]] = []

    async def set_qos(self, *, prefetch_count: int) -> None:
        self.qos.append(prefetch_count)

    async def declare_exchange(
        self, name: str, exchange_type: Any, *, durable: bool
    ) -> FakeExchange:
        self.declared_exchanges.append((name, exchange_type, durable))
        return self.exchange

    async def declare_queue(
        self, name: str, *, durable: bool, arguments: dict[str, object]
    ) -> FakeQueue:
        self.declared_queues.append((name, durable, arguments))
        return self.queue


class FakeConnection:
    def __init__(self) -> None:
        self.channel_obj = FakeChannel()
        self.closed = False

    async def channel(self) -> FakeChannel:
        return self.channel_obj

    async def close(self) -> None:
        self.closed = True
