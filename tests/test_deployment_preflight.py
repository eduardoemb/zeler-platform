from __future__ import annotations

import json
from pathlib import Path

from infra.deploy.preflight import (
    CommandResult,
    build_deployment_preflight_report,
    render_preflight_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_bootstrap_binding_export() -> str:
    return json.dumps(
        {
            "jobs": {
                "zeler-bootstrap": {
                    "env": {
                        "ZELER_ENV": "prod",
                        "BOOTSTRAP_MONGO_DB": "zeler_platform",
                        "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.zeler.ai",
                        "BOOTSTRAP_GATEWAY_PATH_PREFIX": "/proxy/meli",
                        "BOOTSTRAP_MODULE_ID": "bootstrap",
                        "BOOTSTRAP_RABBITMQ_EXCHANGE": "meli.events",
                    },
                    "secrets": {
                        "BOOTSTRAP_MONGO_URI": "mongo-uri-prod:latest",
                        "BOOTSTRAP_RABBITMQ_URL": "cloudamqp-url:latest",
                    },
                    "vpc_connector": (
                        "projects/zeler-platform-dev/locations/us-central1/connectors/"
                        "zeler-platform-serverless"
                    ),
                    "vpc_egress": "private-ranges-only",
                    "service_account": (
                        "zeler-bootstrap-runtime@zeler-platform-dev.iam.gserviceaccount.com"
                    ),
                    "iam_prerequisites": [
                        "roles/secretmanager.secretAccessor",
                        "roles/vpcaccess.user",
                        "roles/cloudkms.signerVerifier",
                    ],
                }
            }
        }
    )


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
        "CLOUD_RUN_SECRET_BINDINGS_EXPORT": _valid_bootstrap_binding_export(),
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


def test_preflight_validates_structured_bootstrap_bindings_without_secret_payloads() -> None:
    report = build_deployment_preflight_report(
        root=ROOT,
        env={
            "MONGO_URI": "mongodb://user:password@mongo.example/zeler_platform",
            "CLOUDAMQP_URL": "amqps://user:password@rabbitmq.example/vhost",
            "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq-export.json",
            "MODULE_REGISTRY_EXPORT": "var/run/module-registry-export.json",
            "GOOGLE_CLOUD_PROJECT": "zeler-platform-dev",
            "CLOUD_RUN_REGION": "us-central1",
            "CLOUD_RUN_SECRET_BINDINGS_EXPORT": _valid_bootstrap_binding_export(),
        },
        command_runner=lambda _args: CommandResult(returncode=0, stdout="present", stderr=""),
    )

    markdown = render_preflight_markdown(report)

    assert report.ok is True
    assert "bootstrap bindings: valid" in markdown
    assert "mongo-uri-prod:latest" in markdown
    assert "cloudamqp-url:latest" in markdown
    assert "password" not in markdown
    assert "mongodb://" not in markdown
    assert "amqps://" not in markdown


def test_preflight_rejects_missing_bootstrap_binding_keys_with_actionable_errors() -> None:
    invalid_export = json.loads(_valid_bootstrap_binding_export())
    bootstrap = invalid_export["jobs"]["zeler-bootstrap"]
    bootstrap["secrets"].pop("BOOTSTRAP_RABBITMQ_URL")
    bootstrap.pop("vpc_egress")
    bootstrap["iam_prerequisites"].remove("roles/cloudkms.signerVerifier")

    report = build_deployment_preflight_report(
        root=ROOT,
        env={
            "MONGO_URI": "mongodb://user:password@mongo.example/zeler_platform",
            "CLOUDAMQP_URL": "amqps://user:password@rabbitmq.example/vhost",
            "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq-export.json",
            "MODULE_REGISTRY_EXPORT": "var/run/module-registry-export.json",
            "GOOGLE_CLOUD_PROJECT": "zeler-platform-dev",
            "CLOUD_RUN_REGION": "us-central1",
            "CLOUD_RUN_SECRET_BINDINGS_EXPORT": json.dumps(invalid_export),
        },
        command_runner=lambda _args: CommandResult(returncode=0, stdout="present", stderr=""),
    )

    markdown = render_preflight_markdown(report)

    assert report.ok is False
    assert "jobs.zeler-bootstrap.secrets.BOOTSTRAP_RABBITMQ_URL" in markdown
    assert "jobs.zeler-bootstrap.vpc_egress" in markdown
    assert "roles/cloudkms.signerVerifier" in markdown
    assert "password" not in markdown


def test_preflight_rejects_malformed_bootstrap_binding_export_without_echoing_input() -> None:
    report = build_deployment_preflight_report(
        root=ROOT,
        env={
            "MONGO_URI": "mongodb://mongo.example/zeler_platform",
            "CLOUDAMQP_URL": "amqps://rabbitmq.example/vhost",
            "RabbitMQ_MANAGEMENT_EXPORT": "var/run/rabbitmq-export.json",
            "MODULE_REGISTRY_EXPORT": "var/run/module-registry-export.json",
            "GOOGLE_CLOUD_PROJECT": "zeler-platform-dev",
            "CLOUD_RUN_REGION": "us-central1",
            "CLOUD_RUN_SECRET_BINDINGS_EXPORT": "{not-json with SECRET=super-secret}",
        },
        command_runner=lambda _args: CommandResult(returncode=0, stdout="present", stderr=""),
    )

    markdown = render_preflight_markdown(report)

    assert report.ok is False
    assert "bootstrap bindings: malformed JSON" in markdown
    assert "super-secret" not in markdown


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


def test_bootstrap_runtime_wiring_documents_prod_secret_vpc_and_jwt_contracts() -> None:
    runbook = (ROOT / "docs" / "bootstrap-runtime-wiring.md").read_text(encoding="utf-8")

    assert "BOOTSTRAP_MONGO_URI" in runbook
    assert "BOOTSTRAP_RABBITMQ_URL" in runbook
    assert "--set-secrets" in runbook
    assert "zeler-bootstrap-runtime" in runbook
    assert "roles/cloudkms.signerVerifier" in runbook
    assert "private-ranges-only" in runbook
    assert "MeliGatewayAuth" in runbook
    assert "BOOTSTRAP_GATEWAY_TOKEN" in runbook
    assert "not accepted in production" in runbook


def test_deploy_docs_describe_bootstrap_preflight_rollout_and_rollback() -> None:
    deploy = (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "live-readiness-report.md").read_text(encoding="utf-8")

    assert "CLOUD_RUN_SECRET_BINDINGS_EXPORT" in deploy
    assert "zeler-bootstrap" in deploy
    assert "zeler-bootstrap-runtime" in deploy
    assert "private-ranges-only" in deploy
    assert "redeploy the previous bootstrap job image" in deploy
    assert "jobs.zeler-bootstrap" in report
    assert "roles/cloudkms.signerVerifier" in report
