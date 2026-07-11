from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from infra.deploy.preflight import (
    CommandResult,
    build_deployment_preflight_report,
    render_preflight_markdown,
)
from infra.deploy.sheets_rollback import (
    PROHIBITED_OLD_API_DIGEST,
    RollbackSafetyError,
    canonical_sheets_registration_fingerprint,
    extract_cloud_build_id,
    verify_gcloud_provenance,
    verify_image_runtime_contract,
    verify_running_image_binding,
    verify_runtime_binding,
)

from zeler_platform_core.runtime.manifest import validate_manifest
from zeler_platform_core.runtime.registration import (
    module_registration_document,
    module_registration_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
DOCKER_DEPLOY_PREFLIGHT = ROOT / "infra" / "gce" / "docker-deploy-preflight.sh"
PLATFORM_STARTUP = ROOT / "infra" / "gce" / "platform-vm-startup.sh"
SHEETS_ROLLBACK_EXECUTOR = ROOT / "infra" / "gce" / "sheets-rollback-execute.sh"
LEGACY_SOURCE_COMMIT = "6ae0608226b6eee32797427506ad19bd03ef2af6"
CONNECTED_REPOSITORY = (
    "projects/zeler-platform-dev/locations/us-central1/connections/"
    "zeler-platform-github/repositories/zeler-platform"
)
CONNECTED_SOURCE_COMMIT = "7a455f76b33d7401a7b772499ccaf35dae6cff66"


def _startup_installed_preflight() -> str:
    startup = PLATFORM_STARTUP.read_text(encoding="utf-8")
    marker = "cat > /opt/zeler-platform/docker-deploy-preflight.sh << 'SCRIPT'\n"
    return startup.split(marker, 1)[1].split("\nSCRIPT", 1)[0] + "\n"


def _valid_bootstrap_binding_export() -> str:
    return json.dumps(
        {
            "jobs": {
                "zeler-bootstrap": {
                    "env": {
                        "ZELER_ENV": "prod",
                        "BOOTSTRAP_MONGO_DB": "zeler_platform_prod",
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


def test_sheets_reconciliation_docs_explain_connected_repository_provenance() -> None:
    guide = (ROOT / "docs" / "sheets" / "zelerdata-read-model-reconciliation.md").read_text(
        encoding="utf-8"
    )

    assert "SHEETS_ROLLBACK_CONNECTED_REPOSITORY" in guide
    assert "source.connectedRepository.repository" in guide
    assert "source.connectedRepository.revision" in guide


def _gcloud_provenance(
    image_ref: str,
    *,
    build_id: str = "build-123",
    builder: str = "https://cloudbuild.googleapis.com/GoogleHostedWorker",
) -> dict[str, Any]:
    repository, digest = image_ref.split("@sha256:", 1)
    return {
        "image_summary": {"fully_qualified_digest": image_ref},
        "provenance_summary": {
            "provenance": [
                {
                    "build": {
                        "inTotoSlsaProvenanceV1": {
                            "_type": "https://in-toto.io/Statement/v1",
                            "predicateType": "https://slsa.dev/provenance/v1",
                            "predicate": {
                                "runDetails": {
                                    "builder": {"id": builder},
                                    "metadata": {"invocationId": build_id},
                                }
                            },
                            "subject": [{"name": repository, "digest": {"sha256": digest}}],
                        }
                    }
                }
            ]
        },
    }


def _non_v1_intoto_row() -> dict[str, Any]:
    return {
        "build": {
            "intotoStatement": {
                "_type": "https://in-toto.io/Statement/v0.1",
                "predicateType": "https://slsa.dev/provenance/v0.2",
            }
        }
    }


def _provenance_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], artifact["provenance_summary"]["provenance"])


def _cloud_build(build_id: str = "build-123") -> dict[str, Any]:
    return {
        "id": build_id,
        "status": "SUCCESS",
        "sourceProvenance": {"resolvedRepoSource": {"commitSha": LEGACY_SOURCE_COMMIT}},
        "steps": [
            {
                "id": "zeler-sheets-rollback-contract",
                "args": [
                    "prior_api_base=passed",
                    "allowed_tree=core/src/zeler_platform_core/runtime/manifest.py,core/src/zeler_platform_core/runtime/registration.py,modules/sheets/manifest.yaml",
                    "entrypoint=zeler_sheets.app:make_app --factory",
                    f"registry_fingerprint={canonical_sheets_registration_fingerprint()}",
                    "clean_restart_health=passed",
                ],
            }
        ],
    }


def _connected_cloud_build(
    *,
    build_id: str = "build-123",
    repository: str = CONNECTED_REPOSITORY,
    revision: str | None = CONNECTED_SOURCE_COMMIT,
    legacy_commit_sha: str = "",
) -> dict[str, Any]:
    build = _cloud_build(build_id)
    connected_repository: dict[str, str] = {"repository": repository}
    if revision is not None:
        connected_repository["revision"] = revision
    build["source"] = {"connectedRepository": connected_repository}
    build["sourceProvenance"]["resolvedRepoSource"]["commitSha"] = legacy_commit_sha
    return build


def test_external_gcloud_provenance_binds_digest_build_source_and_contract() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)

    assert extract_cloud_build_id(artifact, image_ref=image_ref) == "build-123"
    verified = verify_gcloud_provenance(
        image_ref=image_ref,
        artifact_document=artifact,
        build_document=_cloud_build(),
        expected_source_commit=LEGACY_SOURCE_COMMIT,
    )

    assert verified.image_ref == image_ref
    assert verified.entrypoint == ("zeler_sheets.app:make_app", "--factory")
    assert verified.registry_fingerprint == canonical_sheets_registration_fingerprint()


def test_external_gcloud_provenance_accepts_connected_repository_source() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    build = _connected_cloud_build()

    verified = verify_gcloud_provenance(
        image_ref=image_ref,
        artifact_document=artifact,
        build_document=build,
        expected_source_commit=CONNECTED_SOURCE_COMMIT,
        expected_connected_repository=CONNECTED_REPOSITORY,
    )

    assert verified.image_ref == image_ref
    assert verified.source_commit == CONNECTED_SOURCE_COMMIT
    assert verified.entrypoint == ("zeler_sheets.app:make_app", "--factory")
    assert verified.registry_fingerprint == canonical_sheets_registration_fingerprint()


def test_external_gcloud_provenance_accepts_verified_slsa_v1_with_extra_intoto() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    _provenance_rows(artifact).append(_non_v1_intoto_row())
    build = _connected_cloud_build()

    assert extract_cloud_build_id(artifact, image_ref=image_ref) == "build-123"
    verified = verify_gcloud_provenance(
        image_ref=image_ref,
        artifact_document=artifact,
        build_document=build,
        expected_source_commit=CONNECTED_SOURCE_COMMIT,
        expected_connected_repository=CONNECTED_REPOSITORY,
    )

    assert verified.build_id == "build-123"
    assert verified.source_commit == CONNECTED_SOURCE_COMMIT


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_non_v1_intoto_row()],
        [_non_v1_intoto_row(), _non_v1_intoto_row()],
    ],
)
def test_external_gcloud_provenance_fails_closed_without_exactly_one_slsa_v1_row(
    rows: list[dict[str, Any]],
) -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    artifact["provenance_summary"]["provenance"] = rows

    with pytest.raises(RollbackSafetyError, match="provenance"):
        extract_cloud_build_id(artifact, image_ref=image_ref)


def test_external_gcloud_provenance_fails_closed_on_duplicate_slsa_v1_rows() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    duplicate = _gcloud_provenance(image_ref, build_id="build-456")["provenance_summary"][
        "provenance"
    ][0]
    _provenance_rows(artifact).append(duplicate)

    with pytest.raises(RollbackSafetyError, match="ambiguous"):
        extract_cloud_build_id(artifact, image_ref=image_ref)


def test_external_gcloud_provenance_fails_closed_on_invalid_slsa_v1_row_with_extra_intoto() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    _provenance_rows(artifact).append(_non_v1_intoto_row())
    artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
        "predicateType"
    ] = "https://slsa.dev/provenance/v0.2"

    with pytest.raises(RollbackSafetyError, match="invalid"):
        extract_cloud_build_id(artifact, image_ref=image_ref)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("digest", "digest"),
        ("build", "successful trusted build"),
        ("source", "source commit"),
    ],
)
def test_verified_slsa_v1_row_with_extra_intoto_still_fails_closed_on_wrong_authority(
    mutation: str, expected: str
) -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    _provenance_rows(artifact).append(_non_v1_intoto_row())
    build = _connected_cloud_build()
    if mutation == "digest":
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "subject"
        ][0]["digest"]["sha256"] = "f" * 64
    elif mutation == "build":
        build["id"] = "different-build"
    elif mutation == "source":
        build["source"]["connectedRepository"]["revision"] = "f" * 40

    with pytest.raises(RollbackSafetyError, match=expected):
        verify_gcloud_provenance(
            image_ref=image_ref,
            artifact_document=artifact,
            build_document=build,
            expected_source_commit=CONNECTED_SOURCE_COMMIT,
            expected_connected_repository=CONNECTED_REPOSITORY,
        )


def test_provenance_full_registration_fingerprint_tracks_canonical_manifest() -> None:
    manifest = validate_manifest(ROOT / "modules" / "sheets" / "manifest.yaml")
    assert canonical_sheets_registration_fingerprint() == module_registration_fingerprint(
        module_registration_document(manifest)
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("builder", "builder"),
        ("digest", "digest"),
        ("source", "source"),
    ],
)
def test_external_provenance_fails_closed_on_forged_or_incomplete_authority(
    mutation: str, expected: str
) -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    build = _cloud_build()
    if mutation == "builder":
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "predicate"
        ]["runDetails"]["builder"]["id"] = "self-asserted"
    elif mutation == "digest":
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "subject"
        ][0]["digest"]["sha256"] = "f" * 64
    elif mutation == "source":
        build["sourceProvenance"]["resolvedRepoSource"]["commitSha"] = "f" * 40

    with pytest.raises(RollbackSafetyError, match=expected):
        verify_gcloud_provenance(
            image_ref=image_ref,
            artifact_document=artifact,
            build_document=build,
            expected_source_commit=LEGACY_SOURCE_COMMIT,
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("repository", "repository"),
        ("revision", "source commit"),
        ("missing_revision", "revision"),
        ("status", "successful"),
        ("storage_only", "source"),
        ("spoofed_extra_source", "source"),
        ("legacy_mismatch", "source commit"),
        ("digest", "digest"),
    ],
)
def test_connected_repository_provenance_fails_closed_on_untrusted_authority(
    mutation: str, expected: str
) -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    build = _connected_cloud_build()
    if mutation == "repository":
        build["source"]["connectedRepository"]["repository"] = CONNECTED_REPOSITORY + "-fork"
    elif mutation == "revision":
        build["source"]["connectedRepository"]["revision"] = "f" * 40
    elif mutation == "missing_revision":
        del build["source"]["connectedRepository"]["revision"]
    elif mutation == "status":
        build["status"] = "FAILURE"
    elif mutation == "storage_only":
        build["source"] = {"storageSource": {"bucket": "source", "object": "archive.tgz"}}
    elif mutation == "spoofed_extra_source":
        build["source"]["storageSource"] = {"bucket": "source", "object": "archive.tgz"}
    elif mutation == "legacy_mismatch":
        build["sourceProvenance"]["resolvedRepoSource"]["commitSha"] = "e" * 40
    elif mutation == "digest":
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "subject"
        ][0]["digest"]["sha256"] = "f" * 64

    with pytest.raises(RollbackSafetyError, match=expected):
        verify_gcloud_provenance(
            image_ref=image_ref,
            artifact_document=artifact,
            build_document=build,
            expected_source_commit=CONNECTED_SOURCE_COMMIT,
            expected_connected_repository=CONNECTED_REPOSITORY,
        )


def _runtime_probe() -> dict[str, Any]:
    return {
        "entrypoint_import": True,
        "module_id": "sheets",
        "registry_fingerprint": canonical_sheets_registration_fingerprint(),
        "scope_count": 11,
        "routing_key_count": 5,
    }


def test_runtime_image_contract_rejects_noop_or_forged_build_step_authority() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    image_id = "sha256:" + "f" * 64
    valid_config = {
        "Entrypoint": None,
        "Cmd": [
            "sh",
            "-c",
            ".venv/bin/uvicorn zeler_sheets.app:make_app --factory --host 0.0.0.0",
        ],
    }

    proof = verify_image_runtime_contract(
        image_ref=image_ref,
        image_id=image_id,
        source_commit="6ae0608226b6eee32797427506ad19bd03ef2af6",
        image_config=valid_config,
        probe_document=_runtime_probe(),
    )
    assert proof["image_ref"] == image_ref
    assert proof["image_id"] == image_id

    for forged_config in (
        {"Entrypoint": None, "Cmd": ["true"]},
        {"Entrypoint": ["attacker/no-op"], "Cmd": []},
    ):
        with pytest.raises(RollbackSafetyError, match="entrypoint"):
            verify_image_runtime_contract(
                image_ref=image_ref,
                image_id=image_id,
                source_commit="6ae0608226b6eee32797427506ad19bd03ef2af6",
                image_config=forged_config,
                probe_document=_runtime_probe(),
            )
    forged_probe = _runtime_probe()
    forged_probe["registry_fingerprint"] = "0" * 64
    with pytest.raises(RollbackSafetyError, match="probe"):
        verify_image_runtime_contract(
            image_ref=image_ref,
            image_id=image_id,
            source_commit="6ae0608226b6eee32797427506ad19bd03ef2af6",
            image_config=valid_config,
            probe_document=forged_probe,
        )


def test_running_digest_binding_uses_container_image_object_then_image_repo_digests() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    image_id = "sha256:" + "f" * 64

    verify_running_image_binding(
        target_image_ref=image_ref,
        container_image_id=image_id,
        expected_image_id=image_id,
        image_repo_digests=[image_ref],
    )
    with pytest.raises(RollbackSafetyError, match="image object"):
        verify_running_image_binding(
            target_image_ref=image_ref,
            container_image_id="sha256:" + "e" * 64,
            expected_image_id=image_id,
            image_repo_digests=[image_ref],
        )
    with pytest.raises(RollbackSafetyError, match="RepoDigest"):
        verify_running_image_binding(
            target_image_ref=image_ref,
            container_image_id=image_id,
            expected_image_id=image_id,
            image_repo_digests=[image_ref.replace("a" * 64, "b" * 64)],
        )


def test_runtime_binding_requires_exact_running_repo_digest_and_registry_health() -> None:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    health: dict[str, Any] = {
        "ready": True,
        "checks": {
            "registry": {"ok": True, "detail": "registry_fingerprint_match"},
            "mongo": {"ok": True},
            "rabbitmq": {"ok": True},
        },
    }

    verify_runtime_binding(
        image_ref=image_ref,
        repo_digests=[image_ref],
        health_document=health,
    )
    with pytest.raises(RollbackSafetyError, match="RepoDigest"):
        verify_runtime_binding(
            image_ref=image_ref,
            repo_digests=[image_ref.replace("a" * 64, "b" * 64)],
            health_document=health,
        )
    health["checks"]["registry"] = {"ok": False, "detail": "mismatch"}
    with pytest.raises(RollbackSafetyError, match="health"):
        verify_runtime_binding(
            image_ref=image_ref,
            repo_digests=[image_ref],
            health_document=health,
        )


def test_concrete_rollback_executor_has_fail_closed_ordered_runtime_contract() -> None:
    executor = SHEETS_ROLLBACK_EXECUTOR.read_text(encoding="utf-8")

    ordered = (
        "disable --now zelerdata-devoluciones-reconcile.timer",
        "rollback --execute --failure-triggered",
        '"$PREFLIGHT_BIN"',
        "up -d gateway sheets-worker",
        "up -d sheets-api",
        "RepoDigests",
        "/health",
        "registry_fingerprint_match",
    )
    positions = [executor.index(value) for value in ordered]
    assert positions == sorted(positions)
    assert "PROHIBITED_OLD_SHEETS_API_DIGEST" in executor
    assert "stop sheets-api" in executor
    assert "trap rollback_error ERR" in executor
    assert "image inspect" in executor
    assert "{{.Image}}" in executor
    assert "restart sheets-api" in executor
    assert "set -x" not in executor


def test_concrete_rollback_executor_runs_idempotently_and_missing_safe_image_fails_closed(
    tmp_path: Path,
) -> None:
    command_log = tmp_path / "commands.log"
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    gateway_ref = image_ref.replace("sheets-api", "gateway").replace("a" * 64, "b" * 64)
    worker_ref = image_ref.replace("sheets-api", "sheets-worker").replace("a" * 64, "c" * 64)

    def executable(name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    systemctl = executable(
        "systemctl",
        'printf "systemctl %s\\n" "$*" >> "$COMMAND_LOG"\n[[ "${FAIL_SYSTEMCTL:-0}" != "1" ]]\n',
    )
    topology = executable(
        "topology",
        'printf "topology %s\\n" "$*" >> "$COMMAND_LOG"\n[[ "${FAIL_TOPOLOGY:-0}" != "1" ]]\n',
    )
    preflight = executable(
        "preflight",
        """printf 'preflight\\n' >> "$COMMAND_LOG"
if [[ "$PREFLIGHT_STATUS" != "0" ]]; then
  exit "$PREFLIGHT_STATUS"
fi
printf '%s\\n' "$RELEASE_PROOF_JSON" > "$SHEETS_ROLLBACK_PROOF_FILE"
""",
    )
    docker = executable(
        "docker",
        """printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
if [[ -n "${FAIL_DOCKER_MATCH:-}" && "$*" == *"$FAIL_DOCKER_MATCH"* ]]; then
  exit 42
fi
if [[ "$*" == *"ps -q sheets-api"* ]]; then
  printf '%s\n' 'sheets-api-container'
elif [[ "$1 $2" == "image inspect" && "$*" == *"{{.Id}}"* ]]; then
  printf '%s\n' "$EXPECTED_IMAGE_ID"
elif [[ "$1" == "inspect" && "$*" == *"{{.Image}}"* ]]; then
  printf '%s\n' "$CONTAINER_IMAGE_ID"
elif [[ "$1 $2" == "image inspect" && "$*" == *"{{json .RepoDigests}}"* ]]; then
  printf '["%s"]\n' "$EXPECTED_IMAGE_REF"
elif [[ "$*" == *"exec -T sheets-api"* ]]; then
  printf '%s\n' "$HEALTH_JSON"
fi
""",
    )
    health_json = json.dumps(
        {
            "ready": True,
            "checks": {
                "registry": {"ok": True, "detail": "registry_fingerprint_match"},
                "mongo": {"ok": True},
                "rabbitmq": {"ok": True},
            },
        },
        separators=(",", ":"),
    )
    image_id = "sha256:" + "f" * 64
    source_commit = "6ae0608226b6eee32797427506ad19bd03ef2af6"
    release_proof = {
        "schema_version": 1,
        "image_ref": image_ref,
        "image_id": image_id,
        "source_commit": source_commit,
        "registry_fingerprint": canonical_sheets_registration_fingerprint(),
        "scope_count": 11,
        "routing_key_count": 5,
    }
    env = {
        **os.environ,
        "COMMAND_LOG": str(command_log),
        "EXPECTED_IMAGE_REF": image_ref,
        "EXPECTED_IMAGE_ID": image_id,
        "CONTAINER_IMAGE_ID": image_id,
        "HEALTH_JSON": health_json,
        "RELEASE_PROOF_JSON": json.dumps(release_proof),
        "PREFLIGHT_STATUS": "0",
        "FAIL_SYSTEMCTL": "0",
        "FAIL_TOPOLOGY": "0",
        "FAIL_DOCKER_MATCH": "",
        "ZELER_PLATFORM_ROOT": str(ROOT),
        "ZELER_COMPOSE_FILE": str(compose_file),
        "ZELER_SYSTEMCTL_BIN": str(systemctl),
        "ZELER_TOPOLOGY_BIN": str(topology),
        "ZELER_PREFLIGHT_BIN": str(preflight),
        "ZELER_DOCKER_BIN": str(docker),
        "ZELER_PYTHON_BIN": "/usr/bin/python3",
        "SHEETS_ROLLBACK_API_IMAGE_REF": image_ref,
        "SHEETS_ROLLBACK_SOURCE_COMMIT": source_commit,
        "SHEETS_ROLLBACK_PROOF_FILE": str(tmp_path / "release-proof.json"),
        "SHEETS_PRIOR_GATEWAY_IMAGE_REF": gateway_ref,
        "SHEETS_PRIOR_WORKER_IMAGE_REF": worker_ref,
        "SHEETS_API_ROLLBACK_REQUESTED": "1",
    }

    for _ in range(2):
        completed = subprocess.run(  # noqa: S603 - repository-owned rollback executor.
            ["/bin/bash", str(SHEETS_ROLLBACK_EXECUTOR)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0

    log = command_log.read_text(encoding="utf-8")
    assert log.count("systemctl disable --now") == 2
    assert log.count("topology rollback --execute --failure-triggered") == 2
    assert log.count("up -d sheets-api") == 2
    assert log.count("restart sheets-api") == 2
    assert log.count("ps -q sheets-api") == 4
    assert log.count("docker inspect sheets-api-container") == 4
    assert log.count("image inspect sha256:") >= 4
    assert log.count("exec -T sheets-api") == 4

    env["PREFLIGHT_STATUS"] = "1"
    failed = subprocess.run(  # noqa: S603 - repository-owned rollback executor.
        ["/bin/bash", str(SHEETS_ROLLBACK_EXECUTOR)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "docker compose --file" in command_log.read_text(encoding="utf-8")
    assert "stop sheets-api" in command_log.read_text(encoding="utf-8")

    failure_cases = (
        {"FAIL_SYSTEMCTL": "1"},
        {"FAIL_TOPOLOGY": "1"},
        {"FAIL_DOCKER_MATCH": "up -d sheets-api"},
        {"CONTAINER_IMAGE_ID": "sha256:" + "0" * 64},
        {"FAIL_DOCKER_MATCH": "inspect sheets-api-container"},
        {"FAIL_DOCKER_MATCH": "image inspect sha256:"},
        {"EXPECTED_IMAGE_REF": image_ref.replace("a" * 64, "9" * 64)},
        {"FAIL_DOCKER_MATCH": "exec -T sheets-api"},
        {
            "HEALTH_JSON": json.dumps(
                {
                    "ready": True,
                    "checks": {
                        "registry": {"ok": False, "detail": "registry_fingerprint_mismatch"},
                        "mongo": {"ok": True},
                        "rabbitmq": {"ok": True},
                    },
                },
                separators=(",", ":"),
            )
        },
        {"FAIL_DOCKER_MATCH": "restart sheets-api"},
    )
    for mutation in failure_cases:
        command_log.write_text("", encoding="utf-8")
        failed_env = {
            **env,
            "PREFLIGHT_STATUS": "0",
            "FAIL_SYSTEMCTL": "0",
            "FAIL_TOPOLOGY": "0",
            "FAIL_DOCKER_MATCH": "",
            **mutation,
        }
        failed = subprocess.run(  # noqa: S603 - injected rollback command failure.
            ["/bin/bash", str(SHEETS_ROLLBACK_EXECUTOR)],
            cwd=ROOT,
            env=failed_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        failed_log = command_log.read_text(encoding="utf-8")
        assert "systemctl disable --now" in failed_log
        assert "topology rollback --execute --failure-triggered" in failed_log
        assert "stop sheets-api" in failed_log


def _fake_gcloud(tmp_path: Path) -> Path:
    path = tmp_path / "gcloud"
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2 $3 $4" == "artifacts docker images describe" ]]; then
  printf '%s\n' "$ARTIFACT_PROVENANCE_JSON"
elif [[ "$1 $2" == "builds describe" ]]; then
  printf '%s\n' "$CLOUD_BUILD_JSON"
else
  exit 64
fi
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _rollback_preflight_env(
    *, tmp_path: Path, artifact: dict[str, Any] | None = None, build: dict[str, Any] | None = None
) -> dict[str, str]:
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "pull" ]]; then
  exit 0
fi
if [[ "$1 $2" == "image inspect" && "$*" == *"{{.Id}}"* ]]; then
  printf '%s\n' "$IMAGE_ID"
  exit 0
fi
if [[ "$1 $2" == "image inspect" && "$*" == *"{{json .Config}}"* ]]; then
  printf '%s\n' "$IMAGE_CONFIG_JSON"
  exit 0
fi
if [[ "$1" == "run" ]]; then
  printf '%s\n' "$RUNTIME_PROBE_JSON"
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return {
        **os.environ,
        "MIN_FREE_GIB": "0",
        "ZELER_PLATFORM_ROOT": str(ROOT),
        "ZELER_GCLOUD_BIN": str(_fake_gcloud(tmp_path)),
        "ZELER_DOCKER_BIN": str(docker),
        "ZELER_PYTHON_BIN": "/usr/bin/python3",
        "ARTIFACT_PROVENANCE_JSON": json.dumps(artifact or _gcloud_provenance(image_ref)),
        "CLOUD_BUILD_JSON": json.dumps(build or _cloud_build()),
        "SHEETS_ROLLBACK_PREFLIGHT": "1",
        "SHEETS_CANDIDATE_API_DIGEST": "sha256:" + "b" * 64,
        "SHEETS_CANDIDATE_WORKER_DIGEST": "sha256:" + "c" * 64,
        "SHEETS_PRIOR_WORKER_DIGEST": "sha256:" + "d" * 64,
        "SHEETS_PRIOR_GATEWAY_DIGEST": "sha256:" + "e" * 64,
        "SHEETS_ROLLBACK_API_IMAGE_REF": image_ref,
        "SHEETS_ROLLBACK_SOURCE_COMMIT": "6ae0608226b6eee32797427506ad19bd03ef2af6",
        "SHEETS_ROLLBACK_PROOF_FILE": str(tmp_path / "release-proof.json"),
        "IMAGE_ID": "sha256:" + "f" * 64,
        "IMAGE_CONFIG_JSON": json.dumps(
            {
                "Entrypoint": None,
                "Cmd": [
                    "sh",
                    "-c",
                    ".venv/bin/uvicorn zeler_sheets.app:make_app --factory --host 0.0.0.0",
                ],
            }
        ),
        "RUNTIME_PROBE_JSON": json.dumps(_runtime_probe()),
    }


def test_deploy_wrapper_validates_sanitized_immutable_rollback_evidence(
    tmp_path: Path,
) -> None:
    env = _rollback_preflight_env(tmp_path=tmp_path)
    completed = subprocess.run(  # noqa: S603 - executes the repository-owned wrapper.
        ["/bin/bash", str(DOCKER_DEPLOY_PREFLIGHT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    proof = json.loads(Path(env["SHEETS_ROLLBACK_PROOF_FILE"]).read_text(encoding="utf-8"))
    assert proof["image_ref"].endswith("a" * 64)
    assert proof["image_id"] == "sha256:" + "f" * 64
    assert "Sheets rollback attestation passed: exact 11 scopes/5 routing keys." in completed.stdout
    assert "Artifact Registry and Cloud Build provenance: verified" in completed.stdout
    assert "MONGO_URI" not in completed.stdout
    assert "SHEETS_ROLLBACK_ENTRYPOINT" not in completed.stdout
    assert "zeler_sheets.app:app" not in completed.stdout
    wrapper = DOCKER_DEPLOY_PREFLIGHT.read_text(encoding="utf-8")
    for self_asserted_field in (
        "SHEETS_ROLLBACK_BASE_COMMIT",
        "SHEETS_ROLLBACK_ALLOWED_TREE",
        "SHEETS_ROLLBACK_ENTRYPOINT",
        "SHEETS_ROLLBACK_REGISTRY_FINGERPRINT",
        "SHEETS_ROLLBACK_HEALTH_READY",
        "SHEETS_ROLLBACK_CLEAN_RESTART_READY",
    ):
        assert self_asserted_field not in wrapper


def test_deploy_wrapper_accepts_connected_repository_source_provenance(
    tmp_path: Path,
) -> None:
    env = _rollback_preflight_env(tmp_path=tmp_path, build=_connected_cloud_build())
    env["SHEETS_ROLLBACK_SOURCE_COMMIT"] = CONNECTED_SOURCE_COMMIT
    env["SHEETS_ROLLBACK_CONNECTED_REPOSITORY"] = CONNECTED_REPOSITORY

    completed = subprocess.run(  # noqa: S603 - executes the repository-owned wrapper.
        ["/bin/bash", str(DOCKER_DEPLOY_PREFLIGHT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Artifact Registry and Cloud Build provenance: verified" in completed.stdout
    assert "MONGO_URI" not in completed.stdout


def test_deploy_preflight_rejects_noop_runtime_image_even_with_successful_cloud_build(
    tmp_path: Path,
) -> None:
    env = _rollback_preflight_env(tmp_path=tmp_path)
    env["IMAGE_CONFIG_JSON"] = json.dumps({"Entrypoint": None, "Cmd": ["true"]})

    completed = subprocess.run(  # noqa: S603 - repository-owned preflight.
        ["/bin/bash", str(DOCKER_DEPLOY_PREFLIGHT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert not Path(env["SHEETS_ROLLBACK_PROOF_FILE"]).exists()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"SHEETS_ROLLBACK_API_IMAGE_REF": ""}, "image reference is invalid"),
        (
            {
                "SHEETS_ROLLBACK_API_IMAGE_REF": (
                    "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@"
                    + PROHIBITED_OLD_API_DIGEST
                )
            },
            "prohibited old 8/4",
        ),
        ({"SHEETS_ROLLBACK_SOURCE_COMMIT": "invalid"}, "source commit is invalid"),
    ],
)
def test_deploy_wrapper_rejects_missing_unsafe_or_unhealthy_rollback_image(
    tmp_path: Path, mutation: dict[str, str], expected: str
) -> None:
    env = {**_rollback_preflight_env(tmp_path=tmp_path), **mutation}

    completed = subprocess.run(  # noqa: S603 - executes the repository-owned wrapper.
        ["/bin/bash", str(DOCKER_DEPLOY_PREFLIGHT)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert expected in completed.stderr


def test_startup_installed_preflight_is_exactly_canonical() -> None:
    assert _startup_installed_preflight() == DOCKER_DEPLOY_PREFLIGHT.read_text(encoding="utf-8")


@pytest.mark.parametrize("forged", [False, True])
def test_startup_installed_preflight_rejects_unknown_or_forged_digest(
    tmp_path: Path,
    forged: bool,
) -> None:
    installed = tmp_path / "docker-deploy-preflight.sh"
    installed.write_text(_startup_installed_preflight(), encoding="utf-8")
    installed.chmod(0o755)
    image_ref = (
        "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:" + "a" * 64
    )
    artifact = _gcloud_provenance(image_ref)
    if forged:
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "predicate"
        ]["runDetails"]["builder"]["id"] = "self-asserted"
    else:
        artifact["provenance_summary"]["provenance"][0]["build"]["inTotoSlsaProvenanceV1"][
            "subject"
        ][0]["digest"]["sha256"] = "f" * 64

    completed = subprocess.run(  # noqa: S603 - exact startup-installed repository script.
        ["/bin/bash", str(installed)],
        cwd=ROOT,
        env={
            **_rollback_preflight_env(tmp_path=tmp_path, artifact=artifact),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "builder" in completed.stderr or "digest binding" in completed.stderr
