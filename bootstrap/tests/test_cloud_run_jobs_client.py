from __future__ import annotations

import pytest

from zeler_bootstrap.cloud_run_jobs_client import FakeCloudRunJobsClient


@pytest.mark.asyncio
async def test_fake_client_records_calls_and_returns_execution_name() -> None:
    client = FakeCloudRunJobsClient(execution_prefix="fake-execution")

    execution_name = await client.run_job(seller_id="123", job_id="job-1")

    assert execution_name == "fake-execution/job-1"
    assert client.calls == [{"seller_id": "123", "job_id": "job-1"}]
