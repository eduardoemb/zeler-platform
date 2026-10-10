from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from infra.operations.sheets_dlq_archive import (
    REASON_AGE_EXCEEDED,
    REASON_RESOURCE_REREAD,
    REASON_RETAINED,
    REASON_WINDOW_RECONCILED,
)
from infra.operations.sheets_dlq_archive_runtime import (
    ArchiveRunReport,
    load_reconciled_coverages,
    mongo_reread_lookup,
    run_archive,
    run_authorized_archive,
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

    async def store(record: Mapping[str, Any]) -> None:
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

    async def store(record: Mapping[str, Any]) -> None:
        stored.append(dict(record))

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

    async def store(record: Mapping[str, Any]) -> None:
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
    recent = _Delivery(
        _message(
            event_type="questions.new",
            resource="/questions/1",
            occurred_at=(NOW - timedelta(hours=2)).isoformat(),
        )
    )
    stored: list[dict[str, Any]] = []

    async def store(record: Mapping[str, Any]) -> None:
        stored.append(dict(record))

    report = await run_archive(
        broker=_Broker([recent]),
        store=store,
        reconciled_models_until={"82453304": {"questions": NOW}},
        now=lambda: NOW,
    )

    assert recent.acked is True
    assert report.by_reason[REASON_WINDOW_RECONCILED] == 1
    assert stored[0]["reason_code"] == REASON_WINDOW_RECONCILED


@pytest.mark.asyncio
async def test_the_run_is_bounded_by_its_limit() -> None:
    deliveries = [_Delivery(_message(event_id=f"evt-{i}")) for i in range(5)]

    async def store(record: Mapping[str, Any]) -> None:
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

    async def store(record: Mapping[str, Any]) -> None:
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
        event_type="questions.new",
        resource="/questions/1",
        occurred_at="2026-06-01T00:00:00Z",
    )
    broker = _HoldingBroker([retained_head, archivable])
    stored: list[dict[str, Any]] = []

    async def store(record: Mapping[str, Any]) -> None:
        stored.append(dict(record))

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={"82453304": {"questions": NOW}},
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

    async def store(record: Mapping[str, Any]) -> None:
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

    async def store(record: Mapping[str, Any]) -> None:
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

    async def store(record: Mapping[str, Any]) -> None:
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


def _lookup_returning(value: datetime | None, seen: list[Mapping[str, Any]] | None = None) -> Any:
    async def lookup(message: Mapping[str, Any]) -> datetime | None:
        if seen is not None:
            seen.append(message)
        return value

    return lookup


@pytest.mark.asyncio
async def test_a_resource_re_read_after_the_event_archives_a_recent_message() -> None:
    occurred = NOW - timedelta(days=1)
    recent = _Delivery(_message(occurred_at=occurred.isoformat()))
    stored: list[dict[str, Any]] = []
    seen: list[Mapping[str, Any]] = []

    async def store(record: Mapping[str, Any]) -> None:
        stored.append(dict(record))

    report = await run_archive(
        broker=_Broker([recent]),
        store=store,
        reconciled_models_until={},
        reread_lookup=_lookup_returning(occurred + timedelta(hours=1), seen),
        now=lambda: NOW,
    )

    assert recent.acked is True
    assert [message["event_id"] for message in seen] == ["evt-1"]
    assert report.by_reason == {REASON_RESOURCE_REREAD: 1}
    assert [record["reason_code"] for record in stored] == [REASON_RESOURCE_REREAD]


@pytest.mark.asyncio
async def test_no_re_read_evidence_keeps_a_recent_message() -> None:
    recent = _Delivery(_message(occurred_at=(NOW - timedelta(days=1)).isoformat()))

    async def store(record: Mapping[str, Any]) -> None:
        raise AssertionError("absence of evidence must not archive")

    report = await run_archive(
        broker=_Broker([recent]),
        store=store,
        reconciled_models_until={},
        reread_lookup=_lookup_returning(None),
        now=lambda: NOW,
    )

    assert recent.requeued is True
    assert recent.acked is False
    assert report.by_reason == {REASON_RETAINED: 1}


@pytest.mark.asyncio
async def test_a_failed_evidence_read_stops_the_run_and_releases_the_message() -> None:
    first = _queue_message(event_id="first", occurred_at="2026-06-01T00:00:00Z")
    behind = _queue_message(event_id="behind", occurred_at="2026-06-02T00:00:00Z")
    broker = _HoldingBroker([first, behind])

    async def lookup(message: Mapping[str, Any]) -> datetime | None:
        raise RuntimeError("mongo unavailable")

    async def store(record: Mapping[str, Any]) -> None:
        raise AssertionError("nothing may be archived without its evidence read")

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        reread_lookup=lookup,
        now=lambda: NOW,
    )

    assert report.stopped_reason == "evidence_read_failed"
    assert first.requeues == 1
    assert first.acked is False
    assert broker.drawn == [first], "the run stops before drawing another message"
    assert broker.closed is True


@pytest.mark.asyncio
async def test_a_dry_run_scans_like_the_real_run_but_writes_and_acks_nothing() -> None:
    occurred = NOW - timedelta(days=1)
    old = _queue_message(event_id="old", occurred_at="2026-06-01T00:00:00Z")
    reread = _queue_message(event_id="reread", occurred_at=occurred.isoformat())
    recent = _queue_message(
        event_id="recent",
        event_type="shipments.updated",
        resource="/shipments/9",
        occurred_at=occurred.isoformat(),
    )
    broker = _HoldingBroker([old, reread, recent])
    released: list[str] = []
    for delivery, name in ((old, "old"), (reread, "reread"), (recent, "recent")):
        original = delivery.nack_requeue

        async def requeue(original: Any = original, name: str = name) -> None:
            released.append(name)
            await original()

        delivery.nack_requeue = requeue  # type: ignore[method-assign]

    async def lookup(message: Mapping[str, Any]) -> datetime | None:
        return occurred + timedelta(hours=1) if message["event_id"] == "reread" else None

    async def store(record: Mapping[str, Any]) -> None:
        raise AssertionError("a dry run never writes an archive record")

    report = await run_archive(
        broker=broker,
        store=store,
        reconciled_models_until={},
        reread_lookup=lookup,
        now=lambda: NOW,
        dry_run=True,
    )

    assert broker.drawn == [old, reread, recent]
    assert not any(delivery.acked for delivery in (old, reread, recent))
    assert [delivery.requeues for delivery in (old, reread, recent)] == [1, 1, 1]
    assert released == ["recent", "reread", "old"], "LIFO release restores the queue order"
    assert broker.closed is True
    assert report.dry_run is True
    assert report.archived == 0
    assert report.would_archive == 2
    assert report.scanned == 3
    assert report.by_reason == {
        REASON_AGE_EXCEEDED: 1,
        REASON_RESOURCE_REREAD: 1,
        REASON_RETAINED: 1,
    }


@pytest.mark.asyncio
async def test_the_report_counts_by_type_month_and_type_by_reason_without_raw_values() -> None:
    deliveries = [
        _Delivery(_message(event_id="a", occurred_at="2026-06-01T00:00:00Z")),
        _Delivery(
            _message(
                event_id="b",
                event_type="shipments.updated",
                resource="/shipments/9",
                occurred_at=(NOW - timedelta(days=1)).isoformat(),
            )
        ),
        _Delivery(_message(event_id="c", occurred_at="not-a-time")),
        _Delivery(_message(event_id="d", event_type="MLM761153981 /items SECRET")),
    ]

    async def store(record: Mapping[str, Any]) -> None:
        raise AssertionError("a dry run never writes an archive record")

    report = await run_archive(
        broker=_Broker(deliveries),
        store=store,
        reconciled_models_until={},
        now=lambda: NOW,
        dry_run=True,
    )

    encoded = json.dumps(report.as_dict())
    assert report.by_event_type == {"items.updated": 2, "other": 1, "shipments.updated": 1}
    assert report.by_month == {"2026-06": 2, "2026-09": 1, "unknown": 1}
    assert report.by_event_type_reason == {
        "items.updated": {REASON_AGE_EXCEEDED: 1, REASON_RETAINED: 1},
        "other": {REASON_AGE_EXCEEDED: 1},
        "shipments.updated": {REASON_RETAINED: 1},
    }
    for raw in ("SECRET", "MLM", "evt-", "82453304", "/items", "/shipments"):
        assert raw not in encoded
    assert report.as_dict()["dry_run"] is True


class _FindOneCollection:
    def __init__(self, document: dict[str, Any] | None) -> None:
        self.document = document
        self.calls: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        self.calls.append((query, projection, kwargs))
        return self.document


class _LookupDb:
    def __init__(self, collections: dict[str, _FindOneCollection]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> _FindOneCollection:
        return self.collections[name]


@pytest.mark.asyncio
async def test_the_mongo_lookup_reads_one_document_by_identity_with_a_minimal_projection() -> None:
    synced = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    items = _FindOneCollection({"_id": "MLM1", "last_meli_sync_at": synced})
    lookup = mongo_reread_lookup(_LookupDb({"items": items}), ["82453304"])

    assert await lookup(_message()) == synced
    assert items.calls == [({"_id": "MLM1", "seller_id": "82453304"}, {"last_meli_sync_at": 1}, {})]


@pytest.mark.asyncio
async def test_the_mongo_lookup_reads_the_newest_competition_observation() -> None:
    observed = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    observations = _FindOneCollection({"observed_at": observed})
    lookup = mongo_reread_lookup(
        _LookupDb({"sheets_catalog_competition_observations": observations}), ["82453304"]
    )

    found = await lookup(
        _message(
            event_type="catalog_item_competition_status.updated",
            resource="/items/MLM1/price_to_win?version=v2",
        )
    )

    assert found == observed
    assert observations.calls == [
        (
            {"seller_id": "82453304", "item_id": "MLM1"},
            {"observed_at": 1},
            {"sort": [("observed_at", -1)]},
        )
    ]


@pytest.mark.asyncio
async def test_the_mongo_lookup_reads_nothing_for_an_unauthorized_seller_or_resource() -> None:
    items = _FindOneCollection({"last_meli_sync_at": NOW})
    lookup = mongo_reread_lookup(_LookupDb({"items": items}), ["82453304"])

    assert await lookup(_message(seller_id=99999999)) is None
    assert await lookup(_message(event_type="questions.new", resource="/questions/1")) is None
    assert items.calls == []


class _ReadyBroker(_HoldingBroker):
    def __init__(self, deliveries: list[Any], *, ready: int, calls: list[str]) -> None:
        super().__init__(deliveries)
        self._ready = ready
        self._calls = calls

    async def ready_count(self, queue_name: str) -> int:
        self._calls.append(f"ready:{queue_name}")
        return self._ready

    async def close_channel(self) -> None:
        self._calls.append("close")
        await super().close_channel()


class _RuntimeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.inserted: list[dict[str, Any]] = []
        self.counted: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any]) -> Any:
        rows = self.rows

        class Cursor:
            async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
                return rows

        return Cursor()

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        return None

    async def count_documents(self, query: dict[str, Any]) -> int:
        self.counted.append(query)
        return 1

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.inserted.append(document)


class _RuntimeDb:
    def __init__(self) -> None:
        self.collections: dict[str, _RuntimeCollection] = {}

    def __getitem__(self, name: str) -> _RuntimeCollection:
        return self.collections.setdefault(name, _RuntimeCollection())


@pytest.mark.asyncio
async def test_an_authorized_dry_run_reports_ready_before_and_after_and_writes_nothing() -> None:
    calls: list[str] = []
    scan = _ReadyBroker([_queue_message(event_id="old")], ready=1, calls=calls)
    after = _ReadyBroker([], ready=1, calls=calls)
    brokers = [scan, after]
    db = _RuntimeDb()

    report = await run_authorized_archive(
        db=db,
        amqp_url="amqp://test",
        seller_ids=["82453304"],
        now=lambda: NOW,
        dry_run=True,
        broker_factory=lambda url: brokers.pop(0),
    )

    assert report.ready_before == 1
    assert report.ready_after == 1
    assert report.would_archive == 1
    assert report.sellers_with_event_export == 1
    assert db["sheets_exports"].counted == [{"seller_id": {"$in": ["82453304"]}, "enabled": True}]
    assert db["sheets_dlq_archives"].inserted == []
    # The scan connection is closed before a fresh one measures the requeued queue.
    assert calls == [
        "ready:zeler.sheets.events.dlq",
        "close",
        "ready:zeler.sheets.events.dlq",
        "close",
    ]


@pytest.mark.asyncio
async def test_an_authorized_archive_writes_the_record_and_reports_ready_counts() -> None:
    calls: list[str] = []
    scan = _ReadyBroker([_queue_message(event_id="old")], ready=1, calls=calls)
    after = _ReadyBroker([], ready=0, calls=calls)
    brokers = [scan, after]
    db = _RuntimeDb()

    report = await run_authorized_archive(
        db=db,
        amqp_url="amqp://test",
        seller_ids=["82453304"],
        now=lambda: NOW,
        broker_factory=lambda url: brokers.pop(0),
    )

    assert report.dry_run is False
    assert report.archived == 1
    assert (report.ready_before, report.ready_after) == (1, 0)
    assert [record["reason_code"] for record in db["sheets_dlq_archives"].inserted] == [
        REASON_AGE_EXCEEDED
    ]


@pytest.mark.asyncio
async def test_a_failed_ready_inspection_still_closes_the_connection() -> None:
    calls: list[str] = []

    class _BrokenReady(_ReadyBroker):
        async def ready_count(self, queue_name: str) -> int:
            raise RuntimeError("queue missing")

    broken = _BrokenReady([], ready=0, calls=calls)

    with pytest.raises(RuntimeError, match="queue missing"):
        await run_authorized_archive(
            db=_RuntimeDb(),
            amqp_url="amqp://test",
            seller_ids=["82453304"],
            now=lambda: NOW,
            dry_run=True,
            broker_factory=lambda url: broken,
        )

    assert calls == ["close"]


@pytest.mark.asyncio
async def test_a_failed_ready_count_after_the_run_still_returns_the_report() -> None:
    """Archives already written must never lose their report to the last probe."""
    calls: list[str] = []

    class _BrokenAfter(_ReadyBroker):
        async def ready_count(self, queue_name: str) -> int:
            raise RuntimeError("connection refused")

    scan = _ReadyBroker([_queue_message(event_id="old")], ready=1, calls=calls)
    after = _BrokenAfter([], ready=0, calls=calls)
    brokers: list[_ReadyBroker] = [scan, after]
    db = _RuntimeDb()

    report = await run_authorized_archive(
        db=db,
        amqp_url="amqp://test",
        seller_ids=["82453304"],
        now=lambda: NOW,
        broker_factory=lambda url: brokers.pop(0),
    )

    assert report.archived == 1
    assert report.ready_before == 1
    assert report.ready_after is None
    assert calls == ["ready:zeler.sheets.events.dlq", "close", "close"]


@pytest.mark.asyncio
async def test_ready_count_uses_a_passive_declaration() -> None:
    from zeler_platform_test_support.sheets_dlq_snapshot import FakeDecl

    channel = FakeChannel(queue=FakeQueue(declaration_result=FakeDecl(message_count=316)))
    broker = _aio_pika_broker(FakeConnection(channel=channel))

    assert await broker.ready_count("zeler.sheets.events.dlq") == 316
    assert channel.passives == [True]


def test_the_runtime_cli_dry_run_needs_no_archive_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infra.operations.sheets_dlq_archive_runtime import main

    for name in ("RABBITMQ_URL", "MONGO_URI", "MONGO_DB"):
        monkeypatch.delenv(name, raising=False)

    # Past the confirmation gate, it still needs the runtime configuration.
    with pytest.raises(SystemExit, match="broker and Mongo"):
        main(["--seller-id", "82453304", "--dry-run"])


def test_the_runtime_cli_refuses_a_dry_run_combined_with_archive_confirmations() -> None:
    from infra.operations.sheets_dlq_archive_runtime import main

    with pytest.raises(SystemExit, match="dry-run"):
        main(["--seller-id", "82453304", "--dry-run", "--confirm-archive"])

    with pytest.raises(SystemExit, match="dry-run"):
        main(["--seller-id", "82453304", "--dry-run", "--confirm-approved-runtime"])


def test_the_runtime_cli_dry_run_prints_only_the_sanitized_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import infra.operations.sheets_dlq_archive_runtime as runtime

    monkeypatch.setenv("RABBITMQ_URL", "amqp://user:SECRET@broker/vhost")
    monkeypatch.setenv("MONGO_URI", "mongodb://user:SECRET@127.0.0.1:1/")
    monkeypatch.setenv("MONGO_DB", "zeler_test")
    received: dict[str, Any] = {}

    async def fake_run(**kwargs: Any) -> ArchiveRunReport:
        received.update(kwargs)
        return ArchiveRunReport(
            archived=0,
            retained=1,
            by_reason={REASON_AGE_EXCEEDED: 1},
            stopped_reason=None,
            dry_run=True,
            scanned=1,
            would_archive=1,
        )

    monkeypatch.setattr(runtime, "run_authorized_archive", fake_run)

    assert runtime.main(["--seller-id", "82453304", "--dry-run", "--limit", "400"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert received["dry_run"] is True
    assert received["limit"] == 400
    assert received["seller_ids"] == ["82453304"]
    assert output["dry_run"] is True
    assert output["by_reason"] == {REASON_AGE_EXCEEDED: 1}
    assert "SECRET" not in json.dumps(output)


@pytest.mark.asyncio
async def test_the_re_read_lookup_against_mongo_uses_identity_and_index_reads() -> None:
    """Real Mongo: the stored read timestamps come back, and reads stay bounded."""
    from pathlib import Path
    from uuid import uuid4

    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import ServerSelectionTimeoutError

    # Dedicated loopback test instance; never inherit a production connection.
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=1000
    )
    db = client[f"zeler_test_dlq_archive_{uuid4().hex}"]
    try:
        try:
            await client.admin.command("ping")
        except ServerSelectionTimeoutError:
            pytest.skip("dedicated local Mongo on port 27028 is unavailable")
        index_spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "infra/mongo/indexes/sheets_catalog_competition_observations.json"
            ).read_text()
        )
        observations = db["sheets_catalog_competition_observations"]
        for index in index_spec:
            await observations.create_index(list(index["keys"].items()), **index["options"])
        synced = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
        later = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
        await db["items"].insert_one(
            {"_id": "MLM1", "seller_id": "82453304", "last_meli_sync_at": synced, "title": "x"}
        )
        await db["shipments"].insert_one(
            {"_id": "9", "seller_id": "82453304", "formula_observed_at": synced}
        )
        await db["orders"].insert_one(
            {
                "_id": "55",
                "seller_id": "82453304",
                "items": [
                    {"item_id": "MLM1", "sale_fee_synced_at": synced},
                    {"item_id": "MLM2", "sale_fee_synced_at": later},
                ],
            }
        )
        await observations.insert_many(
            [
                {"seller_id": "82453304", "item_id": "MLM1", "observed_at": synced},
                {"seller_id": "82453304", "item_id": "MLM1", "observed_at": later},
                {"seller_id": "82453304", "item_id": "MLM2", "observed_at": later},
            ]
        )
        lookup = mongo_reread_lookup(db, ["82453304"])

        assert await lookup(_message()) == synced
        assert await lookup(_message(event_type="shipments.updated", resource="/shipments/9")) == (
            synced
        )
        assert await lookup(_message(event_type="orders.updated", resource="/orders/55")) == later
        assert (
            await lookup(
                _message(
                    event_type="catalog_item_competition_status.updated",
                    resource="/items/MLM1/price_to_win?version=v2",
                )
            )
            == later
        )
        assert await lookup(_message(resource="/items/MLM404")) is None

        plan = (
            await observations.find(
                {"seller_id": "82453304", "item_id": "MLM1"}, {"observed_at": 1}
            )
            .sort([("observed_at", -1)])
            .limit(1)
            .explain()
        )
        winning = json.dumps(plan["queryPlanner"]["winningPlan"])
        assert "idx_catalog_competition_seller_item_observed" in winning
        assert '"SORT"' not in winning
    finally:
        await client.drop_database(db.name)
        client.close()
