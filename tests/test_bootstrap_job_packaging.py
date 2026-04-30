from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from bootstrap.tests.test_bootstrap_phase3 import NOW, FakeBootstrapJobs, FakeDatabase, FakeGateway

from zeler_bootstrap.__main__ import parse_args, run_bootstrap_job
from zeler_bootstrap.stages import InMemoryPublisher

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_deploy_args() -> list[str]:
    lines = (
        (ROOT / "infra" / "cloudbuild" / "bootstrap-job.yaml")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    args_started = False
    deploy_seen = False
    args: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped == "args:":
            args_started = True
            args = []
            continue
        if args_started and stripped.startswith("- "):
            value = stripped.removeprefix("- ").strip()
            args.append(value)
            if value == "deploy":
                deploy_seen = True
            continue
        if args_started and stripped and not stripped.startswith("#"):
            if deploy_seen:
                return args
            args_started = False
    if deploy_seen:
        return args
    raise AssertionError("missing gcloud run jobs deploy args")


def _arg_value(args: list[str], flag: str) -> str:
    prefix = f"{flag}="
    for arg in args:
        if arg.startswith(prefix):
            return arg.removeprefix(prefix)
    available_flags = sorted(arg.split("=", 1)[0] for arg in args if arg.startswith("--"))
    raise AssertionError(f"missing {flag}; available deploy flags: {json.dumps(available_flags)}")


def test_bootstrap_cloud_run_job_packaging_files_exist() -> None:
    dockerfile = ROOT / "bootstrap" / "Dockerfile"
    cloudbuild = ROOT / "infra" / "cloudbuild" / "bootstrap-job.yaml"
    entrypoint = ROOT / "bootstrap" / "src" / "zeler_bootstrap" / "__main__.py"

    assert dockerfile.exists()
    assert cloudbuild.exists()
    assert entrypoint.exists()

    dockerfile_text = dockerfile.read_text(encoding="utf-8")
    assert "uv run" not in dockerfile_text
    assert 'ENTRYPOINT [".venv/bin/python", "-m", "zeler_bootstrap"]' in dockerfile_text
    assert "zeler_bootstrap" in dockerfile_text
    cloudbuild_text = cloudbuild.read_text(encoding="utf-8")
    assert "gcloud run jobs deploy zeler-bootstrap" in cloudbuild_text
    assert "--update-env-vars=ZELER_ENV=prod" in cloudbuild_text
    assert "--set-env-vars" not in cloudbuild_text


def test_bootstrap_cloud_run_job_uses_secret_bindings_and_non_secret_env_vars() -> None:
    args = _bootstrap_deploy_args()

    secret_bindings = _arg_value(args, "--set-secrets")
    env_vars = _arg_value(args, "--update-env-vars")
    manifest_text = (ROOT / "infra" / "cloudbuild" / "bootstrap-job.yaml").read_text(
        encoding="utf-8"
    )

    assert "BOOTSTRAP_MONGO_URI=${_BOOTSTRAP_MONGO_URI_SECRET}:latest" in secret_bindings
    assert "BOOTSTRAP_RABBITMQ_URL=${_BOOTSTRAP_RABBITMQ_URL_SECRET}:latest" in secret_bindings
    assert "BOOTSTRAP_MONGO_DB=zeler_platform" in env_vars
    assert "BOOTSTRAP_GATEWAY_BASE_URL=${_BOOTSTRAP_GATEWAY_BASE_URL}" in env_vars
    assert "BOOTSTRAP_GATEWAY_TOKEN" not in manifest_text


def test_bootstrap_cloud_run_job_declares_runtime_identity_and_vpc_contract() -> None:
    args = _bootstrap_deploy_args()

    assert _arg_value(args, "--service-account") == "${_BOOTSTRAP_RUNTIME_SERVICE_ACCOUNT}"
    assert _arg_value(args, "--vpc-connector") == "${_BOOTSTRAP_VPC_CONNECTOR}"
    assert _arg_value(args, "--vpc-egress") == "${_BOOTSTRAP_VPC_EGRESS}"


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
