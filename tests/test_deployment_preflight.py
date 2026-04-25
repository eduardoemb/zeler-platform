from __future__ import annotations

from pathlib import Path

from infra.deploy.preflight import (
    CommandResult,
    build_deployment_preflight_report,
    render_preflight_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_reports_missing_required_inputs_without_printing_secret_values() -> None:
    env = {
        "MONGO_URI": "mongodb://zeler-platform-target.invalid/zeler_platform",
        "RABBITMQ_URL": "amqps://zeler-platform-broker.invalid/vhost",
        "GOOGLE_CLOUD_PROJECT": "zeler-platform-dev",
        "CLOUD_RUN_REGION": "us-central1",
    }

    report = build_deployment_preflight_report(
        root=ROOT,
        env=env,
        command_runner=lambda _args: CommandResult(returncode=0, stdout="ok", stderr=""),
    )

    markdown = render_preflight_markdown(report)
    assert report.ok is False
    assert report.summary["missing_env_groups"] == 3
    assert "MONGO_URI: present" in markdown
    assert "RABBITMQ_URL/CLOUDAMQP_URL: present" in markdown
    assert "RabbitMQ_MANAGEMENT_EXPORT: missing" in markdown
    assert "MODULE_REGISTRY_EXPORT: missing" in markdown
    assert "CLOUD_RUN_SECRET_BINDINGS_EXPORT: missing" in markdown
    assert "zeler-platform-target.invalid" not in markdown
    assert "zeler-platform-broker.invalid" not in markdown
    assert "mongodb://" not in markdown
    assert "amqps://" not in markdown


def test_preflight_passes_when_gcloud_env_and_repo_contracts_are_available() -> None:
    env = {
        "MONGO_URI": "mongodb://zeler-platform-target.invalid/zeler_platform",
        "CLOUDAMQP_URL": "amqps://zeler-platform-broker.invalid/vhost",
        "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq-export.json",
        "MODULE_REGISTRY_EXPORT": "var/run/module-registry-export.json",
        "GOOGLE_CLOUD_PROJECT": "zeler-platform-dev",
        "CLOUD_RUN_REGION": "us-central1",
        "CLOUD_RUN_SECRET_BINDINGS_EXPORT": "var/run/cloud-run-bindings.json",
    }

    def runner(args: tuple[str, ...]) -> CommandResult:
        outputs = {
            ("gcloud", "config", "get-value", "project"): "zeler-platform-dev\n",
            ("gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"): (
                "operator@example.test\n"
            ),
            ("gcloud", "auth", "print-access-token", "--quiet"): "token-redacted-by-tool\n",
        }
        return CommandResult(returncode=0, stdout=outputs[args], stderr="")

    report = build_deployment_preflight_report(root=ROOT, env=env, command_runner=runner)

    assert report.ok is True
    assert report.summary == {
        "missing_env_groups": 0,
        "missing_repo_files": 0,
        "gcloud_failures": 0,
    }
    assert all(check.status == "pass" for check in report.checks)


def test_preflight_gcloud_check_is_non_interactive_and_exits_nonzero_on_auth_failure() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> CommandResult:
        calls.append(args)
        if args == ("gcloud", "auth", "print-access-token", "--quiet"):
            return CommandResult(
                returncode=1,
                stdout="",
                stderr="cannot prompt during non-interactive execution",
            )
        return CommandResult(returncode=0, stdout="present\n", stderr="")

    report = build_deployment_preflight_report(
        root=ROOT,
        env={
            "MONGO_URI": "mongodb://example.test/zeler_platform",
            "RABBITMQ_URL": "amqps://example.test/vhost",
            "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq.json",
            "MODULE_REGISTRY_EXPORT": "var/run/modules.json",
            "PROJECT_ID": "zeler-platform-dev",
            "REGION": "us-central1",
            "CLOUD_RUN_SECRET_BINDINGS_EXPORT": "var/run/bindings.json",
        },
        command_runner=runner,
    )

    markdown = render_preflight_markdown(report)
    assert report.ok is False
    assert report.summary["gcloud_failures"] == 1
    assert ("gcloud", "auth", "print-access-token", "--quiet") in calls
    assert all("login" not in arg for call in calls for arg in call)
    assert "gcloud auth login" in markdown
    assert "cannot prompt" in markdown


def test_preflight_reports_missing_repo_files_with_remediation(tmp_path: Path) -> None:
    env = {
        "MONGO_URI": "mongodb://example.test/zeler_platform",
        "RABBITMQ_URL": "amqps://example.test/vhost",
        "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq.json",
        "MODULE_REGISTRY_EXPORT": "var/run/modules.json",
        "PROJECT_ID": "zeler-platform-dev",
        "REGION": "us-central1",
        "CLOUD_RUN_SECRET_BINDINGS_EXPORT": "var/run/bindings.json",
    }

    report = build_deployment_preflight_report(
        root=tmp_path,
        env=env,
        command_runner=lambda _args: CommandResult(returncode=0, stdout="present", stderr=""),
    )

    markdown = render_preflight_markdown(report)
    assert report.ok is False
    assert report.summary["missing_repo_files"] >= 5
    assert "infra/cloudbuild/bootstrap-job.yaml: missing" in markdown
    assert "bootstrap/Dockerfile: missing" in markdown
    assert "Restore the missing repository files before deploy." in markdown


def test_live_readiness_report_documents_deployment_preflight_command() -> None:
    report = (ROOT / "docs" / "live-readiness-report.md").read_text(encoding="utf-8")

    assert "Deployment preflight" in report
    assert "uv run python -m infra.deploy.preflight" in report
    assert "prints only present/missing status" in report
