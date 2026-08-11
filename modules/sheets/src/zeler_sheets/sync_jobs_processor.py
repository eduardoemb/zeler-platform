from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


class SyncJobsProcessor:
    def __init__(
        self,
        *,
        db: Any,
        handler: Any,
        activation_cutoff: datetime,
        clock: Any = None,
        lease_duration: timedelta = timedelta(minutes=5),
        contention_backoff: timedelta = timedelta(seconds=5),
        retention_window: timedelta = timedelta(days=45),
    ) -> None:
        self._jobs = db["sheets_sync_jobs"]
        self._events = db["webhook_events"]
        self._handler = handler
        self._activation_cutoff = activation_cutoff
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lease_duration = lease_duration
        self._contention_backoff = contention_backoff
        self._retention_window = retention_window

    async def claim_next(self) -> dict[str, Any] | None:
        now = self._clock()
        query = {
            "created_at": {"$gte": self._activation_cutoff},
            "$or": [
                {
                    "state": "pending",
                    "$or": [
                        {"available_at": None},
                        {"available_at": {"$lte": now}},
                    ],
                },
                {
                    "state": "running",
                    "lease_until": {"$lte": now},
                    "append_started_at": None,
                },
            ],
        }
        candidate = await self._jobs.find_one(
            query, sort=[("created_at", 1), ("available_at", 1), ("_id", 1)]
        )
        if candidate is None:
            return None
        state = str(candidate["state"])
        fence = {
            "_id": candidate["_id"],
            "state": state,
            "created_at": {"$gte": self._activation_cutoff},
        }
        if state == "running":
            fence.update({"lease_until": {"$lte": now}, "append_started_at": None})
        else:
            fence["$or"] = [{"available_at": None}, {"available_at": {"$lte": now}}]
        try:
            claimed = await self._jobs.find_one_and_update(
                fence,
                {
                    "$set": {
                        "state": "running",
                        "attempt_token": uuid4().hex,
                        "lease_until": now + self._lease_duration,
                        "started_at": now,
                        "delta_through_at": now,
                        "updated_at": now,
                    },
                    "$inc": {"attempt_count": 1, "fence": 1},
                },
                return_document=ReturnDocument.AFTER,
            )
            return cast(dict[str, Any] | None, claimed)
        except DuplicateKeyError:
            await self._jobs.update_one(
                {"_id": candidate["_id"], "state": "pending"},
                {"$set": {"available_at": now + self._contention_backoff, "updated_at": now}},
            )
            return None

    async def recover_uncertain_appends(self) -> int:
        now = self._clock()
        result = await self._jobs.update_many(
            {
                "state": "running",
                "lease_until": {"$lte": now},
                "append_started_at": {"$ne": None},
            },
            {
                "$set": {
                    "state": "failed",
                    "completed_at": now,
                    "lease_until": None,
                    "error_code": "append_outcome_unknown",
                    "error_message": "Append outcome is unknown; automatic retry is disabled",
                    "updated_at": now,
                }
            },
        )
        return int(result.modified_count)

    async def process_once(self) -> str:
        await self.recover_uncertain_appends()
        job = await self.claim_next()
        if job is None:
            return "idle"
        if job["requested_at"] < job["delta_through_at"] - self._retention_window:
            await self._finish(job, False, "delta_unavailable")
            return "failed"
        try:
            await self._process_delta(job)
        except Exception as exc:  # noqa: BLE001 - handler errors must isolate one job
            await self._finish(job, False, "sync_job_processing_failed", type(exc).__name__)
            return "failed"
        await self._finish(job, True)
        return "succeeded"

    async def _process_delta(self, job: dict[str, Any]) -> None:
        from zeler_sheets.consumer import SheetsEvent

        seller_id = str(job["seller_id"])
        seller_values: list[Any] = (
            [seller_id, int(seller_id)] if seller_id.isdigit() else [seller_id]
        )
        cursor = self._events.find(
            {
                "user_id": {"$in": seller_values},
                "received_at": {
                    "$gte": job["requested_at"],
                    "$lte": job["delta_through_at"],
                },
            }
        ).sort([("received_at", 1), ("_id", 1)])
        events = await cursor.to_list(length=None)
        supported = [event for event in events if _supported(event)]
        if supported:
            await self._write(job, {"append_started_at": self._clock()})
        for event in supported:
            event_id = str(event["_id"])
            await self._handler.handle(
                SheetsEvent(
                    event_id=event_id,
                    event_type=str(event.get("classification") or event["topic"]),
                    seller_id=int(seller_id),
                    resource=str(event["resource"]),
                    idempotency_key=f"sync-job:{job['_id']}:{event_id}",
                )
            )
            await self._write(
                job,
                {"cursor_received_at": event["received_at"], "cursor_event_id": event["_id"]},
            )
        await self._write(job, {"unsupported_event_count": len(events) - len(supported)})

    async def _finish(
        self,
        job: dict[str, Any],
        succeeded: bool,
        code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        now = self._clock()
        await self._write(
            job,
            {
                "state": "succeeded" if succeeded else "failed",
                "completed_at": now,
                "lease_until": None,
                "error_code": code,
                "error_message": (
                    f"{error_type}: sync job processing failed"
                    if error_type
                    else ("Requested delta is outside retention" if code else None)
                ),
            },
        )

    async def _write(self, job: dict[str, Any], values: dict[str, Any]) -> None:
        result = await self._jobs.update_one(
            {
                "_id": job["_id"],
                "state": "running",
                "attempt_token": job["attempt_token"],
                "fence": job["fence"],
            },
            {"$set": {**values, "updated_at": self._clock()}},
        )
        if result.matched_count != 1:
            raise RuntimeError(f"lease lost for sync job {job['_id']}")


def _supported(event: dict[str, Any]) -> bool:
    classification = str(event.get("classification") or event.get("topic") or "")
    return classification.split(".", 1)[0] in {"items", "orders", "shipments", "questions"}
