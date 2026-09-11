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
