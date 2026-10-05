"""Durable work authority for bounded maintenance; headers only locate receipts.

No lease renewal, provider I/O or new budget. Ownership touches are meaningful
only inside the gateway's transaction with the final prepaid-send reservation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from zeler_platform_core.events.idempotency import scoped_processed_event_id
from zeler_platform_core.history_onboarding import (
    PLAN_COLLECTION,
    POLICY_VERSION,
    history_execution_query,
)

CONSUMER = "zeler.sheets.events"
TOPICS = {
    "orders_v2": ("orders.updated", "orders"),
    "orders.updated": ("orders.updated", "orders"),
    "questions": ("questions.new", "questions"),
    "questions.new": ("questions.new", "questions"),
    "shipments": ("shipments.updated", "shipments"),
    "shipments.updated": ("shipments.updated", "shipments"),
    "messages": ("messages.new", "messages"),
    "messages.new": ("messages.new", "messages"),
}
PATHS = {
    "orders": r"/orders/[0-9]+",
    "questions": r"/questions/[0-9]+",
    "shipments": r"/shipments/[0-9]+(?:/costs|/payments)?",
    "messages": r"/messages/packs/[0-9]+/sellers/[0-9]+",
    "claims_returns": (
        r"/(?:orders/[0-9]+|post-purchase/v1/claims/[0-9]+|"
        r"post-purchase/v2/claims/[0-9]+/returns)"
    ),
}


class HistoryWorkWaitError(ValueError):
    """Work has no currently owned, trustworthy acquisition authority."""


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise HistoryWorkWaitError("history work unavailable")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_history_event(document: Mapping[str, Any]) -> tuple[str, str, str] | None:
    topic = document.get("topic") or document.get("classification")
    resource = document.get("resource")
    if not isinstance(resource, str):
        return None
    if topic == "post_purchase":
        raw = document.get("raw_body")
        actions = document.get("actions")
        if actions is None and isinstance(raw, dict):
            actions = raw.get("actions")
        root = re.fullmatch(r"/post-purchase/v1/claims/([0-9]+)", resource)
        history = re.fullmatch(r"/post-purchase/v1/claims/([0-9]+)/actions-history", resource)
        if root is not None and actions == ["claims"]:
            value = ("claims.updated", resource, "claims_returns")
        elif history is not None and actions == ["claims_actions"]:
            value = ("claims.updated", "/post-purchase/v1/claims/" + history[1], "claims_returns")
        else:
            return None
    elif isinstance(topic, str) and topic in TOPICS:
        event_type, source = TOPICS[topic]
        if re.fullmatch(PATHS[source], resource) is None:
            return None
        value = (event_type, resource, source)
    else:
        return None
    classification = document.get("classification")
    return (
        value
        if classification is None or classification == topic or classification == value[0]
        else None
    )


@dataclass(frozen=True)
class HistoryWorkIntent:
    event_id: str
    seller_id: str
    event_type: str
    resource: str
    source: str
    claim_identity: dict[str, str]
    job_identity: dict[str, Any] | None = None

    def receipt(self, path: str) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "seller_id": self.seller_id,
            "event_type": self.event_type,
            "resource": self.resource,
            "source": self.source,
            "phase": "maintenance",
            "path": path,
            "claim_identity": dict(self.claim_identity),
            "job_identity": dict(self.job_identity) if self.job_identity else None,
        }

    async def assert_live(self, db: Any, now: datetime) -> None:
        await validate_history_work_receipt(db, self.receipt(self.resource), now=now)


async def resolve_history_work_intent(
    db: Any,
    *,
    event_id: str,
    seller_id: str,
    event_type: str,
    resource: str,
    claim_identity: Mapping[str, Any] | None,
    job_identity: Mapping[str, Any] | None = None,
    now: datetime,
) -> HistoryWorkIntent:
    if claim_identity is None:
        raise HistoryWorkWaitError("history work unavailable")
    row = await db["webhook_events"].find_one({"_id": event_id})
    normalized = normalize_history_event(row) if isinstance(row, dict) else None
    if normalized is None:
        raise HistoryWorkWaitError("history work unavailable")
    receipt = {
        "event_id": event_id,
        "seller_id": seller_id,
        "event_type": event_type,
        "resource": resource,
        "source": normalized[2],
        "phase": "maintenance",
        "path": resource,
        "claim_identity": dict(claim_identity),
        "job_identity": dict(job_identity) if job_identity else None,
    }
    return await validate_history_work_receipt(db, receipt, now=now)


async def validate_history_work_receipt(
    db: Any,
    receipt: Mapping[str, Any],
    *,
    now: datetime,
    session: Any = None,
    touch: bool = False,
) -> HistoryWorkIntent:
    fail = HistoryWorkWaitError("history work unavailable")
    fields = ("event_id", "seller_id", "event_type", "resource", "source", "path")
    if any(not isinstance(receipt.get(k), str) or not receipt[k] for k in fields):
        raise fail
    seller = receipt["seller_id"]
    if re.fullmatch(r"[0-9]{1,20}", seller) is None or str(int(seller)) != seller:
        raise fail
    if receipt.get("phase") != "maintenance" or receipt["source"] not in PATHS:
        raise fail
    path = receipt["path"]
    if re.fullmatch(PATHS[receipt["source"]], path) is None:
        raise fail
    if receipt["source"] == "messages" and not path.endswith("/sellers/" + seller):
        raise fail
    identity = receipt.get("claim_identity")
    if (
        not isinstance(identity, dict)
        or identity.get("module_id") != "sheets"
        or identity.get("consumer_id") != CONSUMER
    ):
        raise fail
    owner = identity.get("owner_token")
    if not isinstance(owner, str) or re.fullmatch(r"[a-f0-9]{32}", owner) is None:
        raise fail
    job = receipt.get("job_identity")
    if job is not None and (
        not isinstance(job, dict)
        or not isinstance(job.get("_id"), str)
        or not job["_id"]
        or not isinstance(job.get("attempt_token"), str)
        or re.fullmatch(r"[a-f0-9]{32}", job["attempt_token"]) is None
        or type(job.get("fence")) is not int
        or job["fence"] < 1
    ):
        raise fail
    options = {"session": session} if session is not None else {}
    event = await db["webhook_events"].find_one({"_id": receipt["event_id"]}, **options)
    if (
        not isinstance(event, dict)
        or event.get("_id") != receipt["event_id"]
        or str(event.get("user_id")) != seller
        or normalize_history_event(event)
        != (receipt["event_type"], receipt["resource"], receipt["source"])
    ):
        raise fail
    topic = event.get("topic")
    if not isinstance(topic, str) or not topic:
        raise fail
    key = (
        f"sync-job:{job['_id']}:{receipt['event_id']}"
        if job
        else f"{topic}:{receipt['resource']}:{receipt['event_id']}"
    )
    if identity.get("processing_key") != key or (touch and session is None):
        raise fail
    current = _utc(now)
    claim_query = {
        "_id": scoped_processed_event_id(key, CONSUMER),
        "owner_token": owner,
        "module_id": "sheets",
        "consumer_id": CONSUMER,
        "idempotency_key": key,
        "expires_at": {"$gt": current},
    }
    claim = await db["processed_event_claims"].find_one(claim_query, **options)
    if (
        not isinstance(claim, dict)
        or any(claim.get(k) != v for k, v in claim_query.items() if k != "expires_at")
        or _utc(claim.get("expires_at")) <= current
    ):
        raise fail
    job_query = None
    if job is not None:
        job_query = {
            **job,
            "state": "running",
            "seller_id": {"$in": [seller, int(seller)]},
            "lease_until": {"$gt": current},
        }
        stored_job = await db["sheets_sync_jobs"].find_one(job_query, **options)
        if (
            not isinstance(stored_job, dict)
            or any(stored_job.get(k) != v for k, v in job.items())
            or stored_job.get("state") != "running"
            or str(stored_job.get("seller_id")) != seller
            or _utc(stored_job.get("lease_until")) <= current
            or not _utc(stored_job.get("requested_at"))
            <= _utc(event.get("received_at"))
            <= _utc(stored_job.get("delta_through_at"))
        ):
            raise fail
    if touch:
        for collection, query in [
            ("processed_event_claims", claim_query),
            ("sheets_sync_jobs", job_query),
        ]:
            if (
                query is not None
                and await db[collection].find_one_and_update(
                    query,
                    {"$inc": {"history_dispatch_fence": 1}},
                    return_document=ReturnDocument.AFTER,
                    **options,
                )
                is None
            ):
                raise fail
    return HistoryWorkIntent(
        receipt["event_id"],
        seller,
        receipt["event_type"],
        receipt["resource"],
        receipt["source"],
        dict(identity),
        dict(job) if job else None,
    )


async def reserve_history_work_send(
    db: Any,
    *,
    seller_id: str,
    execution: str,
    source: str,
    phase: str,
    work_id: str,
    path: str,
    now: datetime,
) -> dict[str, Any]:
    """One transaction; no retry. Prepaid work credits cannot fund legacy h1.

    Writing the existing ownership documents makes a concurrent takeover conflict
    with this reservation; mere reads would not fence a snapshot write skew.
    """
    fail = HistoryWorkWaitError("history work unavailable")
    if phase != "maintenance" or re.fullmatch(r"[a-f0-9]{32}", work_id) is None:
        raise fail
    try:
        async with (
            await db.client.start_session() as session,
            session.start_transaction(
                read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
            ),
        ):
            plan = await db[PLAN_COLLECTION].find_one({"_id": seller_id}, session=session)
            if not isinstance(plan, dict) or not isinstance(plan.get("execution_work"), dict):
                raise fail
            receipt = plan["execution_work"].get(work_id)
            if (
                not isinstance(receipt, dict)
                or receipt.get("source") != source
                or receipt.get("phase") != phase
                or receipt.get("path") != path
                or receipt.get("seller_id") != seller_id
            ):
                raise fail
            await validate_history_work_receipt(db, receipt, now=now, session=session, touch=True)
            field = f"execution_work.{work_id}"
            sent = f"execution_work_sent_by_source.{execution}.{source}.{phase}"
            query = {
                "_id": seller_id,
                "seller_id": seller_id,
                "policy_version": POLICY_VERSION,
                "authority.kind": "account_link_policy",
                "execution_id": execution,
                "state": "active",
                "eligible": True,
                "sources": source,
                "execution_consumed": {"$type": ["int", "long"], "$gt": 0},
                "execution_until": {"$gt": now},
                "execution_utc_day": now.astimezone(UTC).date().isoformat(),
                "execution_attempt_limit": {"$type": ["int", "long"], "$gte": 0},
                field + ".credit": {"$type": ["int", "long"], "$eq": 1},
                field + ".sent": {"$type": ["int", "long"], "$eq": 0},
                **history_execution_query(now, charged=True),
            }
            for counter in ("execution_sent", sent):
                query["$and"].append(
                    {
                        "$or": [
                            {counter: {"$exists": False}},
                            {counter: {"$type": ["int", "long"], "$gte": 0}},
                        ]
                    }
                )
            query["$and"].append(
                {"$expr": {"$lt": [{"$ifNull": ["$execution_sent", 0]}, "$execution_consumed"]}}
            )
            result = await db[PLAN_COLLECTION].find_one_and_update(
                query,
                {"$inc": {"execution_sent": 1, sent: 1, field + ".sent": 1}},
                return_document=ReturnDocument.AFTER,
                session=session,
            )
            if result is None:
                raise fail
            return dict(result)
    except PyMongoError:
        raise fail from None
