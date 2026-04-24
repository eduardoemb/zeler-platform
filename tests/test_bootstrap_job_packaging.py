from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bootstrap.tests.test_bootstrap_phase3 import NOW, FakeBootstrapJobs, FakeDatabase, FakeGateway

from zeler_bootstrap.__main__ import parse_args, run_bootstrap_job
from zeler_bootstrap.stages import InMemoryPublisher

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_cloud_run_job_packaging_files_exist() -> None:
    dockerfile = ROOT / "bootstrap" / "Dockerfile"
    cloudbuild = ROOT / "infra" / "cloudbuild" / "bootstrap-job.yaml"
    entrypoint = ROOT / "bootstrap" / "src" / "zeler_bootstrap" / "__main__.py"

    assert dockerfile.exists()
    assert cloudbuild.exists()
    assert entrypoint.exists()

    assert "zeler_bootstrap" in dockerfile.read_text(encoding="utf-8")
    assert "gcloud run jobs deploy zeler-bootstrap" in cloudbuild.read_text(encoding="utf-8")


def test_bootstrap_entrypoint_parses_runnable_job_arguments() -> None:
    args = parse_args(["--seller-id", "123", "--job-id", "job-1", "--dry-run"])

    assert args.seller_id == "123"
    assert args.job_id == "job-1"
    assert args.dry_run is True


@pytest.mark.asyncio
async def test_bootstrap_entrypoint_runs_dag_with_injected_clients() -> None:
    jobs = FakeBootstrapJobs()
    database = FakeDatabase()
    gateway = FakeGateway()
    publisher = InMemoryPublisher()

    completed: dict[str, Any] = await run_bootstrap_job(
        seller_id="123",
        job_id="job-1",
        jobs_collection=jobs,
        database=database,
        gateway=gateway,
        publisher=publisher,
        now_fn=lambda: NOW,
    )

    assert completed["state"] == "succeeded"
    assert publisher.events == [
        {"event_type": "BootstrapCompleted", "payload": {"job_id": "job-1", "seller_id": "123"}}
    ]
