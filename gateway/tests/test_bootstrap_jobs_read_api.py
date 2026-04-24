from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeBootstrapJobsCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            "job-1": {
                "_id": "job-1",
                "seller_id": "123456789",
                "state": "running",
                "current_stage": "items",
                "stage_progress": {
                    "items": {"done": 25, "total": 100},
                    "orders": {"done": 0, "total": 30},
                },
                "errors": ["orders retry scheduled"],
                "checkpoints": {"items": {"scroll_id": "secret-cursor"}},
                "created_at": datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
                "updated_at": datetime(2026, 4, 24, 12, 5, tzinfo=UTC),
            }
        }
        self.last_projection: dict[str, int] | None = None

    async def find_one(
        self, filter_doc: dict[str, Any], projection: dict[str, int]
    ) -> dict[str, Any] | None:
        self.last_projection = projection
        document = self.documents.get(str(filter_doc.get("_id")))
        if document is None:
            return None
        return {key: value for key, value in document.items() if projection.get(key) != 0}


class FakeDb:
    def __init__(self) -> None:
        self.bootstrap_jobs = FakeBootstrapJobsCollection()

    def __getitem__(self, name: str) -> FakeBootstrapJobsCollection:
        assert name == "bootstrap_jobs"
        return self.bootstrap_jobs


@pytest.mark.asyncio
async def test_get_bootstrap_job_returns_progress_without_checkpoints() -> None:
    from zeler_gateway.bootstrap_jobs.router import router

    app = FastAPI()
    app.state.mongo_db = FakeDb()
    app.include_router(router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.get("/api/bootstrap-jobs/job-1")

    assert response.status_code == 200
    assert response.json() == {
        "job": {
            "id": "job-1",
            "seller_id": "123456789",
            "state": "running",
            "current_stage": "items",
            "stage_progress": {
                "items": {"done": 25, "total": 100},
                "orders": {"done": 0, "total": 30},
            },
            "errors": ["orders retry scheduled"],
            "created_at": "2026-04-24T12:00:00Z",
            "updated_at": "2026-04-24T12:05:00Z",
        }
    }
    assert app.state.mongo_db.bootstrap_jobs.last_projection == {"checkpoints": 0}
    assert "secret-cursor" not in response.text


@pytest.mark.asyncio
async def test_get_bootstrap_job_404_for_unknown_job() -> None:
    from zeler_gateway.bootstrap_jobs.router import router

    app = FastAPI()
    app.state.mongo_db = FakeDb()
    app.include_router(router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.get("/api/bootstrap-jobs/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "bootstrap_job_not_found"}
