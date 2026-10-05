"""Trusted work intent is durable identity, not a freely supplied source label."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_platform_core.events.idempotency import scoped_processed_event_id
from zeler_platform_core.history_work_intent import (
    HistoryWorkWaitError,
    normalize_history_event,
    resolve_history_work_intent,
    validate_history_work_receipt,
)

NOW = datetime(2026, 10, 5, 20, tzinfo=UTC)
OWNER = "a" * 32


class Collection:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.calls: list[tuple[Any, Any]] = []

    async def find_one(self, query: Any, **kwargs: Any) -> Any:
        self.calls.append((query, None))
        return self.row

    async def find_one_and_update(self, query: Any, update: Any, **kwargs: Any) -> Any:
        self.calls.append((query, update))
        return self.row


def database(topic: str = "orders_v2", resource: str = "/orders/42") -> Any:
    key = "orders_v2:/orders/42:event-1"
    return {
        "webhook_events": Collection(
            {
                "_id": "event-1",
                "user_id": 82,
                "topic": topic,
                "classification": topic,
                "resource": resource,
                "received_at": NOW,
            }
        ),
        "processed_event_claims": Collection(
            {
                "_id": scoped_processed_event_id(key, "zeler.sheets.events"),
                "idempotency_key": key,
                "owner_token": OWNER,
                "module_id": "sheets",
                "consumer_id": "zeler.sheets.events",
                "expires_at": NOW + timedelta(minutes=2),
            }
        ),
        "sheets_sync_jobs": Collection(None),
    }


def identity(key: str = "orders_v2:/orders/42:event-1") -> dict[str, str]:
    return {
        "processing_key": key,
        "owner_token": OWNER,
        "module_id": "sheets",
        "consumer_id": "zeler.sheets.events",
    }


async def resolve(db: Any, **changes: Any) -> Any:
    args = {
        "event_id": "event-1",
        "seller_id": "82",
        "event_type": "orders.updated",
        "resource": "/orders/42",
        "claim_identity": identity(),
        "now": NOW,
    }
    return await resolve_history_work_intent(db, **{**args, **changes})


@pytest.mark.parametrize(
    ("topic", "resource", "expected"),
    [
        ("orders_v2", "/orders/42", ("orders.updated", "/orders/42", "orders")),
        ("questions", "/questions/42", ("questions.new", "/questions/42", "questions")),
        ("shipments", "/shipments/42", ("shipments.updated", "/shipments/42", "shipments")),
        (
            "messages",
            "/messages/packs/42/sellers/82",
            ("messages.new", "/messages/packs/42/sellers/82", "messages"),
        ),
        ("items", "/items/42", None),
        ("catalog_item_competition_status", "/items/42", None),
        ("full_withdrawals", "/stock/fulfillment/operations/42", None),
    ],
)
def test_exact_durable_topics_not_path_guesses(topic: str, resource: str, expected: Any) -> None:
    assert normalize_history_event({"topic": topic, "resource": resource}) == expected


def test_claim_actions_are_normalized_without_gateway_dependency() -> None:
    document = {
        "topic": "post_purchase",
        "resource": "/post-purchase/v1/claims/42/actions-history",
        "raw_body": {"actions": ["claims_actions"]},
    }
    assert normalize_history_event(document) == (
        "claims.updated",
        "/post-purchase/v1/claims/42",
        "claims_returns",
    )
    document["raw_body"] = {"actions": ["untrusted"]}
    assert normalize_history_event(document) is None


@pytest.mark.asyncio
async def test_resolved_maintenance_receipt_is_bound_to_claim_and_resource() -> None:
    db = database()
    intent = await resolve(db)
    assert intent.source == "orders"
    receipt = intent.receipt("/orders/42")
    assert receipt["phase"] == "maintenance" and receipt["seller_id"] == "82"
    await validate_history_work_receipt(db, receipt, now=NOW, session=object(), touch=True)
    query, update = db["processed_event_claims"].calls[-1]
    assert query["owner_token"] == OWNER and query["expires_at"] == {"$gt": NOW}
    assert update == {"$inc": {"history_dispatch_fence": 1}}
    assert "expires_at" not in update.get("$set", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["owner", "expired", "seller", "resource", "classification", "legacy"]
)
async def test_mismatched_intent_waits_before_any_ownership_write(change: str) -> None:
    db = database()
    args: dict[str, Any] = {}
    if change == "owner":
        db["processed_event_claims"].row["owner_token"] = "b" * 32
    if change == "expired":
        db["processed_event_claims"].row["expires_at"] = NOW
    if change == "seller":
        db["webhook_events"].row["user_id"] = 83
    if change == "resource":
        db["webhook_events"].row["resource"] = "/orders/43"
    if change == "classification":
        db["webhook_events"].row["classification"] = "questions.new"
    if change == "legacy":
        args["claim_identity"] = None
    with pytest.raises(HistoryWorkWaitError):
        await resolve(db, **args)
    assert all(update is None for _, update in db["processed_event_claims"].calls)


@pytest.mark.asyncio
async def test_receipt_source_and_path_cannot_be_forged() -> None:
    db = database()
    intent = await resolve(db)
    for changes in ({"source": "claims_returns"}, {"phase": "initial"}, {"path": "/questions/42"}):
        with pytest.raises(HistoryWorkWaitError):
            await validate_history_work_receipt(
                db, {**intent.receipt("/orders/42"), **changes}, now=NOW
            )


@pytest.mark.asyncio
async def test_replay_requires_exact_live_job_fence_and_delta_bounds() -> None:
    db = database()
    key = "sync-job:job-1:event-1"
    db["processed_event_claims"].row.update(
        _id=scoped_processed_event_id(key, "zeler.sheets.events"), idempotency_key=key
    )
    db["sheets_sync_jobs"].row = {
        "_id": "job-1",
        "seller_id": "82",
        "state": "running",
        "attempt_token": "b" * 32,
        "fence": 3,
        "lease_until": NOW + timedelta(minutes=2),
        "requested_at": NOW - timedelta(minutes=1),
        "delta_through_at": NOW,
    }
    job = {"_id": "job-1", "attempt_token": "b" * 32, "fence": 3}
    intent = await resolve(db, claim_identity=identity(key), job_identity=job)
    await validate_history_work_receipt(
        db, intent.receipt("/orders/42"), now=NOW, session=object(), touch=True
    )
    assert db["sheets_sync_jobs"].calls[-1][0]["fence"] == 3
    for changes in (
        {"fence": 4},
        {"lease_until": NOW},
        {"requested_at": NOW + timedelta(seconds=1)},
    ):
        saved = dict(db["sheets_sync_jobs"].row)
        db["sheets_sync_jobs"].row.update(changes)
        with pytest.raises(HistoryWorkWaitError):
            await intent.assert_live(db, NOW)
        db["sheets_sync_jobs"].row = saved


def test_malformed_classification_fails_closed_without_exception() -> None:
    assert (
        normalize_history_event(
            {"topic": "orders_v2", "resource": "/orders/42", "classification": []}
        )
        is None
    )


class Transaction:
    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class Session(Transaction):
    def start_transaction(self, **kwargs: Any) -> Any:
        assert kwargs["read_concern"].document == {"level": "snapshot"}
        assert kwargs["write_concern"].document == {"w": "majority"}
        return Transaction()


class Client:
    async def start_session(self) -> Any:
        return Session()


class Database(dict[str, Any]):
    client = Client()


@pytest.mark.asyncio
async def test_work_send_reservation_is_atomic_and_cannot_spend_legacy_credit() -> None:
    from zeler_platform_core.history_work_intent import reserve_history_work_send

    db = Database(database())
    intent = await resolve(db)
    nonce = "c" * 32
    receipt = {**intent.receipt("/orders/42"), "credit": 1, "sent": 0}
    db["sheets_history_backfill_plans"] = Collection({"execution_work": {nonce: receipt}})
    result = await reserve_history_work_send(
        db,
        seller_id="82",
        execution="d" * 32,
        source="orders",
        phase="maintenance",
        work_id=nonce,
        path="/orders/42",
        now=NOW,
    )
    assert result is not None
    query, update = db["sheets_history_backfill_plans"].calls[-1]
    assert query[f"execution_work.{nonce}.sent"]["$eq"] == 0
    assert query["authority.kind"] == "account_link_policy"
    assert update["$inc"] == {
        "execution_sent": 1,
        f"execution_work_sent_by_source.{'d' * 32}.orders.maintenance": 1,
        f"execution_work.{nonce}.sent": 1,
    }
    assert "execution_charged" not in str(query) and "execution_sent_by_source" not in str(update)
    assert db["processed_event_claims"].calls[-1][1] == {"$inc": {"history_dispatch_fence": 1}}


@pytest.mark.asyncio
async def test_forged_work_receipt_cannot_touch_owner_or_reserve_send() -> None:
    from zeler_platform_core.history_work_intent import reserve_history_work_send

    db = Database(database())
    intent = await resolve(db)
    receipt = {**intent.receipt("/orders/42"), "credit": 1, "sent": 0, "source": "claims_returns"}
    db["sheets_history_backfill_plans"] = Collection({"execution_work": {"c" * 32: receipt}})
    with pytest.raises(HistoryWorkWaitError):
        await reserve_history_work_send(
            db,
            seller_id="82",
            execution="d" * 32,
            source="claims_returns",
            phase="maintenance",
            work_id="c" * 32,
            path="/orders/42",
            now=NOW,
        )
    assert all(update is None for _, update in db["processed_event_claims"].calls)
    assert all(update is None for _, update in db["sheets_history_backfill_plans"].calls)


@pytest.mark.asyncio
async def test_real_publisher_processing_key_is_preserved_not_replaced() -> None:
    db = database()
    key = "orders_v2:/orders/42:event-1"
    db["processed_event_claims"].row.update(
        _id=scoped_processed_event_id(key, "zeler.sheets.events"), idempotency_key=key
    )
    intent = await resolve(db, claim_identity=identity(key))
    assert intent.claim_identity["processing_key"] == key


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", [None, [], True, "invalid"])
async def test_corrupt_execution_work_shape_waits_without_owner_touch(shape: Any) -> None:
    from zeler_platform_core.history_work_intent import reserve_history_work_send

    db = Database(database())
    db["sheets_history_backfill_plans"] = Collection({"execution_work": shape})
    with pytest.raises(HistoryWorkWaitError):
        await reserve_history_work_send(
            db,
            seller_id="82",
            execution="d" * 32,
            source="orders",
            phase="maintenance",
            work_id="c" * 32,
            path="/orders/42",
            now=NOW,
        )
    assert not db["processed_event_claims"].calls
