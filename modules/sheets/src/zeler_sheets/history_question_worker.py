"""Opt-in worker for a single shared twelve-month question scan."""

from __future__ import annotations

import asyncio

import httpx
from pymongo.errors import PyMongoError

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_sheets.formulas.pacing import LocalQuotaTimeoutError, recovery_quota_deadline
from zeler_sheets.formulas.recovery import QuestionScanRecoveryRequest
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryLimitError
from zeler_sheets.history_continuation import HistoryContinuation
from zeler_sheets.history_question_publication import HistoryQuestionPublisher
from zeler_sheets.history_questions import (
    QuestionManifestDriftError,
    QuestionScanStaging,
    initialize_question_scan,
)


class HistoryQuestionsWorker:
    def __init__(self, worker: FormulaRecoveryWorker) -> None:
        if worker.queue.enabled_models != frozenset({"questions"}):
            raise ValueError("history questions worker requires a questions-only queue")
        self.worker = worker
        self.queue = worker.queue
        self.store = HistoryAcquisitionStore(worker.db, self.queue)
        continuation = HistoryContinuation(self.store)
        self.staging = QuestionScanStaging(continuation)
        self.publisher = HistoryQuestionPublisher(continuation)

    async def process_once(self) -> str:
        return "processed" if await self.process_one() else "idle"

    async def process_one(self) -> bool:
        job = await self.queue.claim(history=True)
        if job is None:
            return False
        try:
            with recovery_quota_deadline(asyncio.get_running_loop().time() + 239) as quota:
                async with asyncio.timeout(240):
                    request = QuestionScanRecoveryRequest(
                        job["seller_id"],
                        job["history_plan_id"],
                        job["date_from"],
                        job["date_to"],
                    )
                    head = await initialize_question_scan(self.store, job, request)
                    if head.phase == "discover" or (
                        head.phase == "verify"
                        and (head.page_sequence == 0 or head.next_cursor is not None)
                    ):
                        await self.staging.fetch_and_stage(job, head, self.worker.gateway)
                    elif head.phase == "hydrate":
                        await self.staging.begin_verification(job, head)
                    elif head.phase == "verify":
                        if head.fetched_count < head.discovered_count:
                            try:
                                await self.staging.fetch_and_hydrate(
                                    job, head, self.worker.detail_gateway
                                )
                            except QuestionManifestDriftError:
                                await self.staging.continuation.release(
                                    job, head, reason="source_drift"
                                )
                        else:
                            await self.staging.begin_publication(job, head)
                    elif head.phase == "publish":
                        if head.published_count < head.fetched_count:
                            await self.publisher.batch(job, head)
                        else:
                            await self.publisher.finalize(job, head)
                    else:
                        raise ValueError("completed question acquisition cannot be reclaimed")
        except LocalQuotaTimeoutError:
            await self.queue.defer_quota(job)
        except httpx.HTTPStatusError as error:
            transient = error.response.status_code == 429 or error.response.status_code >= 500
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=transient,
                failure_reason="source_temporarily_unavailable" if transient else "source_rejected",
            )
        except (httpx.TransportError, TimeoutError, GatewayRateLimitError) as error:
            if isinstance(error, TimeoutError) and quota.expired:
                await self.queue.defer_quota(job)
            else:
                await self.queue.finish(
                    job,
                    succeeded=False,
                    retryable=True,
                    failure_reason="source_temporarily_unavailable",
                )
        except PyMongoError:
            await self.queue.finish(
                job, succeeded=False, retryable=True, failure_reason="storage_unavailable"
            )
        except HistoryLimitError:
            await self.queue.collection.update_one(
                self.queue._owned(job, self.queue.now()),
                {"$set": {"history_blocker": "local_acquisition_budget"}},
            )
            await self.queue.finish(job, succeeded=False, failure_reason="source_incomplete")
        except (ValueError, KeyError):
            await self.queue.finish(job, succeeded=False, failure_reason="source_incomplete")
        return True
