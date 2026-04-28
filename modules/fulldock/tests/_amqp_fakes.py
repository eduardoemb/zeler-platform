from __future__ import annotations

import json
from typing import Any


class FakeMessage:
    def __init__(
        self,
        body: dict[str, Any] | bytes,
        *,
        headers: dict[str, object] | None = None,
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
        self.exchanges_by_name: dict[str, FakeExchange] = {}
        self.queues_by_name: dict[str, FakeQueue] = {}
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
        exchange = self.exchanges_by_name.setdefault(name, FakeExchange())
        if name == "meli.events":
            self.exchange = exchange
        return exchange

    async def declare_queue(
        self, name: str, *, durable: bool, arguments: dict[str, object]
    ) -> FakeQueue:
        self.declared_queues.append((name, durable, arguments))
        queue = self.queues_by_name.setdefault(name, FakeQueue())
        if name == "zeler.fulldock.events":
            self.queue = queue
        return queue


class FakeConnection:
    def __init__(self) -> None:
        self.channel_obj = FakeChannel()
        self.closed = False

    async def channel(self) -> FakeChannel:
        return self.channel_obj

    async def close(self) -> None:
        self.closed = True
