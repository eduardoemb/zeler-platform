"""Shared question-scan admission identity; no provider cursor interpretation."""

from __future__ import annotations

from typing import Any

from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_sheets.formulas.recovery import QuestionScanRecoveryRequest
from zeler_sheets.history_acquisition import HistoryAcquisitionStore, HistoryConflictError


async def initialize_question_scan(
    store: HistoryAcquisitionStore,
    job: dict[str, Any],
    request: QuestionScanRecoveryRequest,
) -> SheetsHistoryAcquisition:
    request.validate_existing(job)
    if job.get("history_protocol_version") != 1 or job.get("history_acquisition_id") != request.key:
        raise HistoryConflictError("question scan requires its history-only admission")
    initial = SheetsHistoryAcquisition(
        _id=request.key,
        seller_id=request.seller_id,
        read_model="questions",
        plan_id=request.plan_id,
        scope_id="seller_scan",
        job_id=request.key,
        date_from=request.date_from,
        date_to=request.date_to,
        created_at=job["created_at"],
        updated_at=job["created_at"],
    )
    return await store.initialize(job, initial)
