from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_MAX_ATTEMPTS = 3


class CloudRunJobsClientLike(Protocol):
    async def run_job(self, *, seller_id: str, job_id: str) -> str: ...


class BootstrapDispatcher:
    def __init__(
        self,
        mongo_db: Any,
        cloud_run_jobs_client: CloudRunJobsClientLike,
        *,
        concurrency_lock_collection_name: str = "bootstrap_dispatcher_locks",
        max_concurrent: int = 5,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._db = mongo_db
        self._cloud_run_jobs_client = cloud_run_jobs_client
        self._lock_collection_name = concurrency_lock_collection_name
        self._max_concurrent = max_concurrent
        self._max_attempts = max_attempts

    async def handle_accounts_linked(self, event: dict[str, Any]) -> str:
        seller_id = str(event["seller_id"])
        jobs = self._db["bootstrap_jobs"]

        active_job = await jobs.find_one(
            {"seller_id": seller_id, "state": {"$in": ["running", "dispatched"]}}
        )
        if active_job is not None:
            return "skipped"

        pending_job = await jobs.find_one({"seller_id": seller_id, "state": "pending"})
        if pending_job is None:
            return "skipped"

        attempts = int(pending_job.get("dispatch_attempts", 0))
        if attempts >= self._max_attempts:
            await self._mark_failed(pending_job, seller_id, attempts)
            return "failed"

        acquired = await self._acquire_lock()
        if not acquired:
            return "backpressure"

        job_id = str(pending_job["_id"])
        try:
            await jobs.update_one(
                {"_id": pending_job["_id"], "state": "pending"},
                {
                    "$set": {"state": "running", "updated_at": datetime.now(UTC)},
                    "$inc": {"dispatch_attempts": 1},
                },
            )
            await self._cloud_run_jobs_client.run_job(seller_id=seller_id, job_id=job_id)
        except Exception:
            await jobs.update_one(
                {"_id": pending_job["_id"]},
                {"$set": {"state": "pending", "updated_at": datetime.now(UTC)}},
            )
            await self._release_lock()
            raise
        return "running"

    async def _acquire_lock(self) -> bool:
        locks = self._db[self._lock_collection_name]
        now = datetime.now(UTC)
        current = await locks.find_one({"_id": "counter"})
        if current is None:
            await locks.find_one_and_update(
                {"_id": "counter"},
                {
                    "$set": {
                        "holder_id": "global",
                        "acquired_at": now,
                        "expires_at": now + timedelta(seconds=60),
                        "schema_version": 1,
                    },
                    "$inc": {"count": 1},
                },
                upsert=True,
            )
            return True
        if int(current.get("count", 0)) >= self._max_concurrent:
            return False
        await locks.find_one_and_update(
            {"_id": "counter"},
            {
                "$set": {"acquired_at": now, "expires_at": now + timedelta(seconds=60)},
                "$inc": {"count": 1},
            },
        )
        return True

    async def _release_lock(self) -> None:
        locks = self._db[self._lock_collection_name]
        current = await locks.find_one({"_id": "counter"})
        if current is None or int(current.get("count", 0)) <= 0:
            return
        await locks.find_one_and_update({"_id": "counter"}, {"$inc": {"count": -1}})

    async def _mark_failed(
        self,
        job: dict[str, Any],
        seller_id: str,
        attempts: int,
    ) -> None:
        error = "max dispatch attempts exceeded"
        await self._db["bootstrap_jobs"].update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "state": "failed",
                    "last_error": error,
                    "updated_at": datetime.now(UTC),
                    "failed_at": datetime.now(UTC),
                }
            },
        )
        logger.error(
            "bootstrap.dispatch.failed",
            seller_id=seller_id,
            attempts=attempts,
            error=error,
        )
