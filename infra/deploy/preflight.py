from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CheckStatus = Literal["pass", "fail"]
CheckCategory = Literal["gcloud", "env", "repo"]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PreflightCheck:
    category: CheckCategory
    name: str
    status: CheckStatus
    detail: str
    remediation: str


@dataclass(frozen=True)
class DeploymentPreflightReport:
    ok: bool
    safe_to_execute: bool
    read_only: bool
    mutations_attempted: int
    summary: dict[str, int]
    checks: tuple[PreflightCheck, ...]


CommandRunner = Callable[[tuple[str, ...]], CommandResult]

ENV_GROUPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("MONGO_URI", ("MONGO_URI",), "Export the target MongoDB URI for zeler-platform."),
    (
        "RABBITMQ_URL/CLOUDAMQP_URL",
        ("RABBITMQ_URL", "CLOUDAMQP_URL"),
        "Export RABBITMQ_URL or CLOUDAMQP_URL for the target RabbitMQ vhost.",
    ),
    (
        "RabbitMQ_MANAGEMENT_EXPORT",
        ("RabbitMQ_MANAGEMENT_EXPORT",),
        "Create a RabbitMQ management export JSON and set RabbitMQ_MANAGEMENT_EXPORT to its path.",
    ),
    (
        "MODULE_REGISTRY_EXPORT",
        ("MODULE_REGISTRY_EXPORT",),
        "Export target module_registry documents to JSON and set MODULE_REGISTRY_EXPORT.",
    ),
    (
        "GCP project env",
        ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT", "GCLOUD_PROJECT", "PROJECT_ID"),
        "Set GOOGLE_CLOUD_PROJECT, GCP_PROJECT, GCLOUD_PROJECT, or PROJECT_ID.",
    ),
    (
        "Cloud Run region env",
        ("CLOUD_RUN_REGION", "REGION"),
        "Set CLOUD_RUN_REGION or REGION for Cloud Run checks/deploys.",
    ),
    (
        "CLOUD_RUN_SECRET_BINDINGS_EXPORT",
        ("CLOUD_RUN_SECRET_BINDINGS_EXPORT",),
        "Export Cloud Run service/job env + Secret Manager bindings to JSON and set this path.",
    ),
)

REQUIRED_REPO_PATHS: tuple[tuple[str, str], ...] = (
    (
        "infra/cloudbuild/bootstrap-job.yaml",
        "Restore bootstrap Cloud Build job packaging before deploy.",
    ),
    ("bootstrap/Dockerfile", "Restore bootstrap Dockerfile before deploy."),
    ("infra/mongo/readiness.py", "Restore Mongo readiness tooling."),
    ("infra/rabbitmq/readiness.py", "Restore RabbitMQ readiness tooling."),
    ("infra/rabbitmq/definitions.json", "Regenerate RabbitMQ definitions before deploy."),
    ("infra/mongo/schemas", "Restore Mongo schema directory before deploy."),
    ("infra/mongo/indexes", "Restore Mongo index directory before deploy."),
    (
        "infra/mongo/seeds/module_registry.admin_clients.json",
        "Restore module_registry admin-client seed contract before deploy.",
    ),
)


def _default_command_runner(args: tuple[str, ...]) -> CommandResult:
    completed = subprocess.run(  # noqa: S603 - args are static gcloud probes, no shell.
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _has_any_env(env: Mapping[str, str], names: tuple[str, ...]) -> bool:
    return any(bool(env.get(name)) for name in names)


def _env_checks(env: Mapping[str, str]) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    for label, names, remediation in ENV_GROUPS:
        present = _has_any_env(env, names)
        checks.append(
            PreflightCheck(
                category="env",
                name=label,
                status="pass" if present else "fail",
                detail=f"{label}: {'present' if present else 'missing'}",
                remediation="" if present else remediation,
            )
        )
    return checks


def _repo_checks(root: Path) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    for relative_path, remediation in REQUIRED_REPO_PATHS:
        exists = (root / relative_path).exists()
        checks.append(
            PreflightCheck(
                category="repo",
                name=relative_path,
                status="pass" if exists else "fail",
                detail=f"{relative_path}: {'present' if exists else 'missing'}",
                remediation="" if exists else remediation,
            )
        )
    return checks


def _gcloud_check(
    *,
    name: str,
    args: tuple[str, ...],
    runner: CommandRunner,
    remediation: str,
) -> PreflightCheck:
    try:
        result = runner(args)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PreflightCheck(
            category="gcloud",
            name=name,
            status="fail",
            detail=f"{name}: unavailable ({exc})",
            remediation=remediation,
        )

    if result.returncode == 0 and result.stdout.strip():
        return PreflightCheck(
            category="gcloud",
            name=name,
            status="pass",
            detail=f"{name}: available",
            remediation="",
        )
    failure = _sanitize_gcloud_failure(result)
    return PreflightCheck(
        category="gcloud",
        name=name,
        status="fail",
        detail=f"{name}: unavailable ({failure})",
        remediation=remediation,
    )


def _sanitize_gcloud_failure(result: CommandResult) -> str:
    stderr = result.stderr.strip()
    if "cannot prompt" in stderr:
        return "cannot prompt during non-interactive execution"
    if "Reauthentication failed" in stderr:
        return "reauthentication failed"
    if "command not found" in stderr:
        return "gcloud command not found"
    if stderr:
        return f"command failed with exit code {result.returncode}"
    return "command returned no output"


def _gcloud_checks(runner: CommandRunner) -> list[PreflightCheck]:
    return [
        _gcloud_check(
            name="gcloud project",
            args=("gcloud", "config", "get-value", "project"),
            runner=runner,
            remediation=(
                "Run `gcloud config set project <zeler-platform-project>` after auth is valid."
            ),
        ),
        _gcloud_check(
            name="gcloud active account",
            args=("gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"),
            runner=runner,
            remediation="Run `gcloud auth login` outside this non-interactive tool.",
        ),
        _gcloud_check(
            name="gcloud access token",
            args=("gcloud", "auth", "print-access-token", "--quiet"),
            runner=runner,
            remediation=(
                "Run `gcloud auth login` or `gcloud auth application-default login` interactively."
            ),
        ),
    ]


def build_deployment_preflight_report(
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
) -> DeploymentPreflightReport:
    selected_env = os.environ if env is None else env
    runner = _default_command_runner if command_runner is None else command_runner

    checks = [*_gcloud_checks(runner), *_env_checks(selected_env), *_repo_checks(root)]
    missing_env_groups = sum(
        1 for check in checks if check.category == "env" and check.status == "fail"
    )
    missing_repo_files = sum(
        1 for check in checks if check.category == "repo" and check.status == "fail"
    )
    gcloud_failures = sum(
        1 for check in checks if check.category == "gcloud" and check.status == "fail"
    )
    summary = {
        "missing_env_groups": missing_env_groups,
        "missing_repo_files": missing_repo_files,
        "gcloud_failures": gcloud_failures,
    }

    return DeploymentPreflightReport(
        ok=all(check.status == "pass" for check in checks),
        safe_to_execute=True,
        read_only=True,
        mutations_attempted=0,
        summary=summary,
        checks=tuple(checks),
    )


def render_preflight_markdown(report: DeploymentPreflightReport) -> str:
    lines = [
        "# Deployment Preflight",
        "",
        f"- ok: {str(report.ok).lower()}",
        f"- safe_to_execute: {str(report.safe_to_execute).lower()}",
        f"- read_only: {str(report.read_only).lower()}",
        f"- mutations_attempted: {report.mutations_attempted}",
        "- secrecy: prints only present/missing status and sanitized command status; "
        "secret values are never rendered.",
        "",
        "## Summary",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(report.summary.items()))
    lines.extend(["", "## Checks", ""])
    for check in report.checks:
        lines.append(f"- [{check.status}] {check.category} `{check.name}` — {check.detail}")
        if check.remediation:
            lines.append(f"  - remediation: {check.remediation}")

    if not report.ok:
        lines.extend(
            [
                "",
                "## Remediation",
                "",
                "- Run `gcloud auth login` outside this non-interactive tool "
                "if gcloud auth failed.",
                "- Export the missing env vars in the operator shell or CI secret context.",
                "- Restore the missing repository files before deploy.",
                "- Re-run this preflight command before any Cloud Run deploy or live apply.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check deployment prerequisites without printing secret values."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    report = build_deployment_preflight_report(root=args.root)
    if args.format == "json":
        print(json.dumps(report, default=lambda obj: obj.__dict__, indent=2), end="\n")
    else:
        print(render_preflight_markdown(report), end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
