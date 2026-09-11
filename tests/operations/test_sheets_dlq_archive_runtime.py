from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from infra.operations.sheets_dlq_archive import (
    REASON_AGE_EXCEEDED,
    REASON_WINDOW_RECONCILED,
)
from infra.operations.sheets_dlq_archive_runtime import (
    ArchiveRunReport,
    load_reconciled_coverages,
    run_archive,
)
from zeler_platform_test_support.sheets_dlq_snapshot import (
    FakeChannel,
    FakeConnect,
    FakeConnection,
    FakeMsg,
    FakeQueue,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class _Delivery:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()
        self.acked = False
        self.requeued = False

    async def ack(self) -> None:
        self.acked = True

    async def nack_requeue(self) -> None:
        self.requeued = True


class _Broker:
    def __init__(self, deliveries: list[_Delivery]) -> None:
        self._deliveries = list(deliveries)
        self.closed = False

    async def get_one(self, queue_name: str) -> _Delivery | None:
        return self._deliveries.pop(0) if self._deliveries else None

    async def close_channel(self) -> None:
        self.closed = True


def _message(**overrides: Any) -> dict[str, Any]:
    base = {
        "event_id": "evt-1",
        "event_type": "items.updated",
        "resource": "/items/MLM1",
        "seller_id": 82453304,
        "occurred_at": "2026-06-01T00:00:00Z",
        "idempotency_key": "SECRET",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_archive_writes_the_record_before_removing_the_message() -> None:
    delivery = _Delivery(_message())
    order: list[str] = []

    async def store(record: dict[str, Any]) -> None:
        order.append("store")

    class _OrderedBroker(_Broker):
        async def get_one(self, queue_name: str) -> Any:
            order.append("get")
            return await super().get_one(queue_name)

    broker = _OrderedBroker([delivery])

    original_ack = delivery.ack

    async def ack() -> None:
        order.append("ack")
        await original_ack()

    delivery.ack = ack  # type: ignore[method-assign]

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    # The extra ``get`` is the loop's confirming empty read after the batch.
    assert order == ["get", "store", "ack", "get"]
    assert report.archived == 1
    assert report.retained == 0
    assert broker.closed is True


@pytest.mark.asyncio
async def test_a_retained_message_is_requeued_and_never_stored() -> None:
    recent = _Delivery(_message(occurred_at=(NOW - timedelta(days=1)).isoformat()))
    stored: list[dict[str, Any]] = []

    async def store(record: dict[str, Any]) -> None:
        stored.append(record)

    report = await run_archive(
        broker=_Broker([recent]),
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert recent.requeued is True
    assert recent.acked is False
    assert stored == []
    assert report.archived == 0
    assert report.retained == 1
    assert report.by_reason["retained"] == 1


@pytest.mark.asyncio
async def test_a_failed_archive_write_requeues_and_stops_the_run() -> None:
    """An unexplained removal is the failure this design must never allow."""
    first = _Delivery(_message(event_id="evt-1"))
    second = _Delivery(_message(event_id="evt-2"))

    async def store(record: dict[str, Any]) -> None:
        raise RuntimeError("mongo unavailable")

    report = await run_archive(
        broker=_Broker([first, second]),
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert first.requeued is True
    assert first.acked is False
    assert second.acked is False
    assert second.requeued is False
    assert report.archived == 0
    assert report.stopped_reason == "archive_write_failed"


@pytest.mark.asyncio
async def test_a_reconciled_window_archives_a_recent_message() -> None:
    recent = _Delivery(_message(occurred_at=(NOW - timedelta(hours=2)).isoformat()))
    stored: list[dict[str, Any]] = []

    async def store(record: dict[str, Any]) -> None:
        stored.append(record)

    report = await run_archive(
        broker=_Broker([recent]),
        store=store,
        reconciled_models_until={"82453304": {"items": NOW}},
        now=lambda: NOW,
    )

    assert recent.acked is True
    assert report.by_reason[REASON_WINDOW_RECONCILED] == 1
    assert stored[0]["reason_code"] == REASON_WINDOW_RECONCILED


@pytest.mark.asyncio
async def test_the_run_is_bounded_by_its_limit() -> None:
    deliveries = [_Delivery(_message(event_id=f"evt-{i}")) for i in range(5)]

    async def store(record: dict[str, Any]) -> None:
        return None

    broker = _Broker(deliveries)

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        limit=2,
        now=lambda: NOW,
    )

    assert report.archived == 2
    assert len(broker._deliveries) == 3
    assert all(delivery.acked for delivery in deliveries[:2])


@pytest.mark.asyncio
async def test_an_unreadable_body_is_retained_not_archived() -> None:
    class _RawDelivery:
        body = b"not-json"
        acked = False
        requeued = False

        async def ack(self) -> None:
            self.acked = True

        async def nack_requeue(self) -> None:
            self.requeued = True

    delivery = _RawDelivery()

    async def store(record: dict[str, Any]) -> None:
        raise AssertionError("nothing may be stored for an unreadable body")

    report = await run_archive(
        broker=_Broker([delivery]),  # type: ignore[list-item]
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert delivery.requeued is True
    assert report.archived == 0


def test_report_dict_is_bounded_and_carries_no_payload() -> None:
    report = ArchiveRunReport(
        archived=1,
        retained=0,
        by_reason={REASON_AGE_EXCEEDED: 1},
        stopped_reason=None,
    )

    encoded = json.dumps(report.as_dict())

    assert "zeler.sheets.events.dlq" in encoded
    assert "SECRET" not in encoded
    assert report.as_dict()["by_reason"] == {REASON_AGE_EXCEEDED: 1}


class _MarkerCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def find(self, query: dict[str, Any]) -> Any:
        sellers = set((query.get("seller_id") or {}).get("$in", []))
        rows = [row for row in self._rows if row.get("seller_id") in sellers]

        class Cursor:
            async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
                return rows

        return Cursor()


class _MarkerDb:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __getitem__(self, name: str) -> _MarkerCollection:
        assert name == "sheets_read_model_freshness"
        return _MarkerCollection(self._rows)


@pytest.mark.asyncio
async def test_coverage_uses_the_furthest_proof_per_model_and_ignores_stale() -> None:
    """A stale marker withdraws its claim; a newer proof still authorizes."""
    older = datetime(2026, 8, 1, tzinfo=UTC)
    newer = datetime(2026, 9, 10, tzinfo=UTC)
    db = _MarkerDb(
        [
            {
                "seller_id": "82453304",
                "read_model": "items",
                "state": "reconciled",
                "reconciled_until": older,
            },
            {
                "seller_id": "82453304",
                "read_model": "items",
                "state": "reconciled",
                "reconciled_until": newer,
            },
            {
                "seller_id": "82453304",
                "read_model": "orders",
                "state": "stale",
                "reconciled_until": newer,
            },
            {
                # An observed-only heartbeat proves the loop audited what it
                # saw; it says nothing about an event that never observed
                # anything, so it must never authorize an archive.
                "seller_id": "82453304",
                "read_model": "shipments",
                "state": "fresh",
                "coverage_basis": "observed_only",
                "reconciled_until": newer,
                "fresh_until": newer,
            },
            {
                # A fresh-but-reconciled marker without an interval edge is not
                # coverage of anything.
                "seller_id": "82453304",
                "read_model": "questions",
                "state": "reconciled",
                "fresh_until": newer,
            },
        ]
    )

    coverage = await load_reconciled_coverages(db, ["82453304"])

    assert coverage["82453304"]["items"] == newer
    assert "orders" not in coverage["82453304"]
    assert "shipments" not in coverage["82453304"]
    assert "questions" not in coverage["82453304"]


def test_the_runtime_cli_requires_both_confirmations() -> None:
    from infra.operations.sheets_dlq_archive_runtime import main

    with pytest.raises(SystemExit, match="confirmations"):
        main(["--seller-id", "82453304"])

    with pytest.raises(SystemExit, match="confirmations"):
        main(["--seller-id", "82453304", "--confirm-archive"])


def test_the_runtime_cli_requires_broker_and_mongo_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations.sheets_dlq_archive_runtime import main

    for name in ("RABBITMQ_URL", "MONGO_URI", "MONGO_DB"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit, match="broker and Mongo"):
        main(
            [
                "--seller-id",
                "82453304",
                "--confirm-approved-runtime",
                "--confirm-archive",
            ]
        )


def _aio_pika_broker(conn: Any, url: str = "amqp://test") -> Any:
    from infra.operations.sheets_dlq_archive_runtime import AioPikaArchiveBroker

    return AioPikaArchiveBroker(url, connect=FakeConnect(connections=[conn]))


@pytest.mark.asyncio
async def test_get_one_falls_back_to_the_queue_when_the_channel_exposes_no_get() -> None:
    message = FakeMsg(body=b'{"event_type":"items.updated"}', delivery_tag=4)
    channel = FakeChannel(queue=FakeQueue(message=message), get_available=False)

    delivery = await _aio_pika_broker(FakeConnection(channel=channel)).get_one(
        "zeler.sheets.events.dlq"
    )

    assert delivery is not None
    assert delivery.body == message.body
    assert channel.calls == ["get_queue:zeler.sheets.events.dlq:None"]
    assert channel.queue.no_acks == [False]


@pytest.mark.asyncio
async def test_the_broker_connects_without_robust_reconnect_so_delivery_tags_stay_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aio_pika
    from infra.operations.sheets_dlq_archive_runtime import AioPikaArchiveBroker

    message = FakeMsg(body=b'{"event_type":"items.updated"}', delivery_tag=1)
    connection = FakeConnection(channel=FakeChannel(messages={"q": message}))
    calls: list[dict[str, Any]] = []

    def _robust(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a reconnect would invalidate the delivery tags of an open message")

    async def _plain(url: str = "", **kwargs: Any) -> Any:
        calls.append({"url": url, **kwargs})
        return connection

    monkeypatch.setattr(aio_pika, "connect_robust", _robust)
    monkeypatch.setattr(aio_pika, "connect", _plain)

    broker = AioPikaArchiveBroker("amqp://test")

    assert await broker.get_one("q") is not None
    assert calls and calls[0]["url"] == "amqp://test"


@pytest.mark.asyncio
async def test_the_aio_pika_broker_requeues_without_multiple_ack() -> None:
    message = FakeMsg(body=b"{}", delivery_tag=9)
    broker = _aio_pika_broker(FakeConnection(channel=FakeChannel(messages={"q": message})))

    delivery = await broker.get_one("q")
    assert delivery is not None
    await delivery.nack_requeue()

    assert message.nacks == [(True, False)]


class _QueueDelivery:
    """Delivery that a real front-requeue queue would hand back first."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()
        self.acked = False
        self.requeues = 0
        self.released = False

    async def ack(self) -> None:
        self.acked = True

    async def nack_requeue(self) -> None:
        self.requeues += 1
        self.released = True


class _HoldingBroker:
    """Broker that keeps unacked messages out of the ready set, like AMQP does."""

    def __init__(self, deliveries: list[Any]) -> None:
        self.ready = list(deliveries)
        self.drawn: list[Any] = []
        self.closed = False

    async def get_one(self, queue_name: str) -> Any:
        if not self.ready:
            return None
        message = self.ready.pop(0)
        self.drawn.append(message)
        return message

    async def close_channel(self) -> None:
        self.closed = True


def _queue_message(**overrides: Any) -> _QueueDelivery:
    return _QueueDelivery(_message(**overrides))


@pytest.mark.asyncio
async def test_retained_messages_do_not_starve_archivable_ones_in_a_bounded_run() -> None:
    """Inspection advances past retained messages instead of cycling on them.

    Production showed the failure directly: messages requeued during the scan
    came back at the head, so a single retained message was redrawn on every
    draw of an otherwise bounded run and the 30 archivable orders behind it were
    never reached. Holding them unacked and releasing them after the scan keeps
    the messages in the queue while still letting the head advance.
    """
    retained_head = _queue_message(
        event_id="retained-head",
        event_type="items.updated",
        occurred_at=(NOW - timedelta(days=1)).isoformat(),
    )
    archivable = _queue_message(
        event_id="archivable-behind",
        event_type="orders.updated",
        occurred_at="2026-06-01T00:00:00Z",
    )
    broker = _HoldingBroker([retained_head, archivable])
    stored: list[dict[str, Any]] = []

    async def store(record: dict[str, Any]) -> None:
        stored.append(record)

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={"82453304": {"orders": NOW}},
        limit=4,
        now=lambda: NOW,
    )

    assert broker.drawn == [retained_head, archivable]
    assert archivable.acked is True
    assert retained_head.acked is False
    assert retained_head.requeues == 1, "a retained message must go back to the queue exactly once"
    assert report.archived == 1
    assert report.retained == 1
    assert [record["reason_code"] for record in stored] == ["window_reconciled"]


@pytest.mark.asyncio
async def test_retained_messages_are_released_after_the_scan_in_their_original_order() -> None:
    first = _queue_message(event_id="retained-1", occurred_at=(NOW - timedelta(days=1)).isoformat())
    second = _queue_message(
        event_id="retained-2", occurred_at=(NOW - timedelta(days=2)).isoformat()
    )
    broker = _HoldingBroker([first, second])
    released: list[str] = []

    async def store(record: dict[str, Any]) -> None:
        raise AssertionError("nothing is archivable in this run")

    original_first, original_second = first.nack_requeue, second.nack_requeue

    async def requeue_first() -> None:
        released.append("first")
        await original_first()

    async def requeue_second() -> None:
        released.append("second")
        await original_second()

    first.nack_requeue = requeue_first  # type: ignore[method-assign]
    second.nack_requeue = requeue_second  # type: ignore[method-assign]

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert report.retained == 2
    assert released == ["second", "first"], (
        "LIFO release restores the draw order on the ready queue"
    )
    assert broker.closed is True


@pytest.mark.asyncio
async def test_a_failed_archive_write_still_releases_the_held_messages() -> None:
    retained = _queue_message(
        event_id="retained", occurred_at=(NOW - timedelta(days=1)).isoformat()
    )
    failing = _queue_message(event_id="failing", occurred_at="2026-06-01T00:00:00Z")
    behind = _queue_message(event_id="behind", occurred_at="2026-06-02T00:00:00Z")
    broker = _HoldingBroker([retained, failing, behind])

    async def store(record: dict[str, Any]) -> None:
        raise RuntimeError("mongo unavailable")

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert report.stopped_reason == "archive_write_failed"
    assert retained.requeues == 1
    assert failing.requeues == 1
    assert behind.requeues == 0
    assert behind.acked is False
    assert broker.closed is True


@pytest.mark.asyncio
async def test_a_release_failure_still_closes_the_broker_and_is_reported() -> None:
    class _FailingRequeue(_QueueDelivery):
        async def nack_requeue(self) -> None:
            self.requeues += 1
            raise RuntimeError("channel closed")

    retained = _FailingRequeue(_message(occurred_at=(NOW - timedelta(days=1)).isoformat()))
    broker = _HoldingBroker([retained])

    async def store(record: dict[str, Any]) -> None:
        raise AssertionError("nothing is archivable in this run")

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
    )

    assert broker.closed is True, "a release failure must not leave the connection open"
    assert report.stopped_reason == "release_failed"
    assert report.retained == 1
