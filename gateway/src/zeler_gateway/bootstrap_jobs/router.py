from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["bootstrap-jobs"])

_BOOTSTRAP_JOB_PROJECTION = {"checkpoints": 0}


@router.get("/bootstrap-jobs/{job_id}")
async def get_bootstrap_job(request: Request, job_id: str) -> JSONResponse:
    document = await request.app.state.mongo_db["bootstrap_jobs"].find_one(
        {"_id": job_id}, _BOOTSTRAP_JOB_PROJECTION
    )
    if document is None:
        return JSONResponse(status_code=404, content={"error": "bootstrap_job_not_found"})

    return JSONResponse({"job": _serialize_bootstrap_job(document)})


def _serialize_bootstrap_job(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "seller_id": str(document.get("seller_id", "")),
        "state": str(document.get("state", "pending")),
        "current_stage": document.get("current_stage"),
        "stage_progress": document.get("stage_progress", {}),
        "errors": list(document.get("errors", [])),
        "created_at": _format_datetime(document.get("created_at")),
        "updated_at": _format_datetime(document.get("updated_at")),
    }


def _format_datetime(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)

    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
