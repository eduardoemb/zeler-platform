"""Opt-in durable order recovery worker; not wired into the runtime supervisor."""

from __future__ import annotations

from pymongo.errors import PyMongoError

from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.formulas.recovery import OrderHistoryRecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_acquisition import (
    HistoryAcquisitionStore,
    HistoryConflictError,
    HistoryLimitError,
)
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_orders import HistoryOrdersProducer
from zeler_sheets.history_publication import HistoryOrderPublisher


class HistoryOrdersWorker:
    def __init__(self, worker: FormulaRecoveryWorker) -> None:
        if worker.queue.enabled_models != frozenset({"orders"}):
            raise ValueError("history orders worker requires an explicitly orders-only queue")
        self.queue = worker.queue
        self.store = HistoryAcquisitionStore(worker.db, self.queue)
        continuation = HistoryContinuation(self.store)
        self.producer = HistoryOrdersProducer(worker, continuation)
        self.publisher = HistoryOrderPublisher(continuation)

    async def process_once(self) -> str:
        return "processed" if await self.process_one() else "idle"

    async def process_one(self) -> bool:
        job = await self.queue.claim(history=True)
        if job is None:
            return False
        try:
            stored = await self.store.heads.find_one({"_id": job.get("history_acquisition_id")})
            if stored is not None:
                head = SheetsHistoryAcquisition.model_validate(stored)
            else:
                request = OrderHistoryRecoveryRequest(
                    job["seller_id"],
                    job["history_plan_id"],
                    job["date_from"],
                    job["date_to"],
                )
                request.validate_existing(job)
                if job.get("history_acquisition_id") != request.key or job["_id"] != request.key:
                    raise HistoryConflictError("history admission references another acquisition")
                initial = SheetsHistoryAcquisition(
                    _id=request.key,
                    seller_id=request.seller_id,
                    read_model="orders",
                    plan_id=request.plan_id,
                    scope_id=request.scope_id,
                    job_id=request.key,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    created_at=job["created_at"],
                    updated_at=job["created_at"],
                )
                head = await self.store.initialize(job, initial)
            if head.phase == "publish":
                if head.published_count < head.fetched_count:
                    await self.publisher.batch(job, head)
                else:
                    await self.publisher.finalize(job, head)
            else:
                await self.producer.step(job, head)
        except HistoryLimitError:
            async with (
                await self.store.db.client.start_session() as session,
                session.start_transaction(),
            ):
                result = await self.queue.collection.update_one(
                    self.queue._owned(job, self.queue.now()),
                    {"$set": {"history_blocker": "local_acquisition_budget"}},
                    session=session,
                )
                if result.matched_count:
                    await self.queue.finish(job, succeeded=False, session=session)
        except PyMongoError:
            await self.queue.finish(
                job, succeeded=False, retryable=True, failure_reason="storage_unavailable"
            )
        except (ValueError, KeyError):
            await self.queue.finish(job, succeeded=False, failure_reason="source_incomplete")
        return True
