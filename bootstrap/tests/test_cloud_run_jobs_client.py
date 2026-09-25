from __future__ import annotations

import json

import httpx
import pytest

from zeler_bootstrap.cloud_run_jobs_client import CloudRunJobsClient, FakeCloudRunJobsClient


@pytest.mark.asyncio
async def test_fake_client_records_calls_and_returns_execution_name() -> None:
    client = FakeCloudRunJobsClient(execution_prefix="fake-execution")

    execution_name = await client.run_job(seller_id="123", job_id="job-1")

    assert execution_name == "fake-execution/job-1"
    assert client.calls == [{"seller_id": "123", "job_id": "job-1"}]


@pytest.mark.asyncio
async def test_cloud_run_job_receives_required_cli_arguments() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"name": "operations/bootstrap-123"})

    class Credentials:
        valid = True
        token = "test-token"  # noqa: S105

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = CloudRunJobsClient(
            project="test-project",
            location="us-central1",
            job_name="zeler-bootstrap",
            credentials=Credentials(),
            http_client=http_client,
        )
        execution_name = await client.run_job(seller_id="123", job_id="bootstrap-123-oauth")

    assert execution_name == "operations/bootstrap-123"
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/jobs/zeler-bootstrap:run")
    assert json.loads(requests[0].content) == {
        "overrides": {
            "containerOverrides": [{"args": ["--seller-id=123", "--job-id=bootstrap-123-oauth"]}]
        }
    }
