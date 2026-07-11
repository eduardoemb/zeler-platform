from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CANONICAL_SHEETS_SCOPES = (
    "GET /items",
    "GET /items/*",
    "GET /products/*",
    "GET /sites/*/listing_prices",
    "GET /users/*/shipping_options/free",
    "GET /orders/*",
    "GET /post-purchase/v1/claims/search",
    "GET /post-purchase/v1/claims/*",
    "GET /post-purchase/v2/claims/*/returns",
    "GET /shipments/*",
    "GET /questions/*",
)
CANONICAL_SHEETS_ROUTING_KEYS = (
    "items.*",
    "orders.*",
    "shipments.*",
    "questions.*",
    "claims.updated",
)
ROLLBACK_COMPATIBLE_ALLOWED_TREE = (
    "core/src/zeler_platform_core/runtime/manifest.py",
    "core/src/zeler_platform_core/runtime/registration.py",
    "modules/sheets/manifest.yaml",
)
ROLLBACK_HEALTH_CONTRACT = (
    "container_healthy",
    "mongo_ready",
    "rabbitmq_ready",
    "sheets_health_200",
    "startup_registration_exact_fingerprint",
    "clean_restart_exact_fingerprint",
)
PROHIBITED_OLD_API_DIGEST = (
    "sha256:8da8ab2b0b092825e6b3f362ea92e375a52e25a7a3cb78c2af0828844ddb00b6"
)
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_CLOUD_BUILD_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_IMAGE_REF_PATTERN = re.compile(
    r"(?P<repository>[a-z0-9.-]+/[a-z0-9._/-]+)@sha256:(?P<digest>[0-9a-f]{64})"
)
_CANONICAL_FULL_REGISTRATION_FINGERPRINT = (
    "3a80a26a340151c5a8a2fca1cbece0f0c4d3974e3695885bce488745c08cda38"
)


class RollbackSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedGcloudProvenance:
    image_ref: str
    build_id: str
    source_commit: str
    entrypoint: tuple[str, str]
    registry_fingerprint: str


def canonical_sheets_registration_fingerprint() -> str:
    return _CANONICAL_FULL_REGISTRATION_FINGERPRINT


def extract_cloud_build_id(artifact_document: Mapping[str, Any], *, image_ref: str) -> str:
    image_match = _required_image_ref(image_ref)
    summary = artifact_document.get("image_summary")
    if not isinstance(summary, Mapping) or summary.get("fully_qualified_digest") != image_ref:
        raise RollbackSafetyError("Artifact Registry digest binding is invalid")
    provenance_summary = artifact_document.get("provenance_summary")
    provenance_rows = (
        provenance_summary.get("provenance") if isinstance(provenance_summary, Mapping) else None
    )
    if not isinstance(provenance_rows, list):
        raise RollbackSafetyError("Artifact Registry provenance is missing or ambiguous")
    slsa_v1_rows = [
        row
        for row in provenance_rows
        if isinstance(row, Mapping)
        and isinstance(row.get("build"), Mapping)
        and "inTotoSlsaProvenanceV1" in row["build"]
    ]
    if len(slsa_v1_rows) != 1:
        raise RollbackSafetyError("Artifact Registry provenance is missing or ambiguous")
    row = slsa_v1_rows[0]
    build = row.get("build") if isinstance(row, Mapping) else None
    statement = build.get("inTotoSlsaProvenanceV1") if isinstance(build, Mapping) else None
    if (
        not isinstance(statement, Mapping)
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != "https://slsa.dev/provenance/v1"
    ):
        raise RollbackSafetyError("Artifact Registry provenance is invalid")
    predicate = statement.get("predicate")
    run_details = predicate.get("runDetails") if isinstance(predicate, Mapping) else None
    builder = run_details.get("builder") if isinstance(run_details, Mapping) else None
    builder_id = builder.get("id") if isinstance(builder, Mapping) else None
    if not isinstance(builder_id, str) or not builder_id.startswith(
        "https://cloudbuild.googleapis.com/"
    ):
        raise RollbackSafetyError("trusted Cloud Build builder is invalid")
    subjects = statement.get("subject")
    expected_digest = image_match.group("digest")
    expected_repository = image_match.group("repository")
    if not _single_subject_binds_image(
        subjects,
        expected_repository=expected_repository,
        expected_digest=expected_digest,
    ):
        raise RollbackSafetyError("Artifact Registry subject digest binding is invalid")
    metadata = run_details.get("metadata") if isinstance(run_details, Mapping) else None
    build_id = metadata.get("invocationId") if isinstance(metadata, Mapping) else None
    if not isinstance(build_id, str) or not build_id.strip():
        raise RollbackSafetyError("Cloud Build identity is missing")
    return build_id


def verify_gcloud_provenance(
    *,
    image_ref: str,
    artifact_document: Mapping[str, Any],
    build_document: Mapping[str, Any],
    expected_source_commit: str,
    expected_connected_repository: str | None = None,
    expected_cloud_build_project_id: str | None = None,
    expected_cloud_build_project_number: str | None = None,
) -> VerifiedGcloudProvenance:
    invocation_id = extract_cloud_build_id(artifact_document, image_ref=image_ref)
    build_id = _trusted_cloud_build_invocation_id(
        invocation_id,
        build_document,
        expected_project_id=expected_cloud_build_project_id,
        expected_project_number=expected_cloud_build_project_number,
    )
    if build_id is None or build_document.get("status") != "SUCCESS":
        raise RollbackSafetyError("Cloud Build result is not a successful trusted build")
    if _COMMIT_PATTERN.fullmatch(expected_source_commit) is None:
        raise RollbackSafetyError("Cloud Build source commit is invalid")
    connected_commit = _connected_repository_commit(
        build_document,
        expected_connected_repository=expected_connected_repository,
        expected_source_commit=expected_source_commit,
    )
    source_provenance = build_document.get("sourceProvenance")
    resolved_source = (
        source_provenance.get("resolvedRepoSource")
        if isinstance(source_provenance, Mapping)
        else None
    )
    source_commit = (
        resolved_source.get("commitSha") if isinstance(resolved_source, Mapping) else None
    )
    if isinstance(source_commit, str) and source_commit.strip():
        if source_commit != expected_source_commit:
            raise RollbackSafetyError("Cloud Build source commit is invalid")
    elif connected_commit is not None:
        source_commit = connected_commit
    else:
        raise RollbackSafetyError("Cloud Build source commit is invalid")
    return VerifiedGcloudProvenance(
        image_ref=image_ref,
        build_id=build_id,
        source_commit=expected_source_commit,
        entrypoint=("zeler_sheets.app:make_app", "--factory"),
        registry_fingerprint=canonical_sheets_registration_fingerprint(),
    )


def _trusted_cloud_build_invocation_id(
    invocation_id: str,
    build_document: Mapping[str, Any],
    *,
    expected_project_id: str | None = None,
    expected_project_number: str | None = None,
) -> str | None:
    build_id = build_document.get("id")
    if not isinstance(build_id, str) or not build_id.strip():
        return None
    if invocation_id == build_id:
        if _trusted_raw_cloud_build_invocation_id(
            build_id,
            build_document,
            expected_project_id=expected_project_id,
            expected_project_number=expected_project_number,
        ):
            return build_id
        return None
    parsed = urlparse(invocation_id)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "cloudbuild.googleapis.com"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    parts = parsed.path.strip("/").split("/")
    if (
        len(parts) != 7
        or parts[0] != "v1"
        or parts[1] != "projects"
        or parts[3] != "locations"
        or parts[5] != "builds"
    ):
        return None
    project, location, resource_build_id = parts[2], parts[4], parts[6]
    if (
        not project
        or not location
        or _CLOUD_BUILD_UUID_PATTERN.fullmatch(resource_build_id) is None
        or resource_build_id != build_id
    ):
        return None
    build_name = _cloud_build_name_parts(build_document.get("name"))
    if build_name is None:
        return None
    name_project, name_location, name_build_id = build_name
    if name_location != location or name_build_id != resource_build_id:
        return None
    build_project_id = build_document.get("projectId")
    if not isinstance(build_project_id, str) or not build_project_id.strip():
        return None
    if not _trusted_cloud_build_project_reference(
        invocation_project=project,
        build_project_id=build_project_id,
        build_name_project=name_project,
        expected_project_id=expected_project_id,
        expected_project_number=expected_project_number,
    ):
        return None
    return resource_build_id


def _trusted_raw_cloud_build_invocation_id(
    build_id: str,
    build_document: Mapping[str, Any],
    *,
    expected_project_id: str | None,
    expected_project_number: str | None,
) -> bool:
    build_name = _cloud_build_name_parts(build_document.get("name"))
    if build_name is None:
        return False
    name_project, _name_location, name_build_id = build_name
    if name_build_id != build_id:
        return False
    build_project_id = build_document.get("projectId")
    if not isinstance(build_project_id, str) or not build_project_id.strip():
        return False
    return _trusted_cloud_build_project_reference(
        invocation_project=build_project_id,
        build_project_id=build_project_id,
        build_name_project=name_project,
        expected_project_id=expected_project_id,
        expected_project_number=expected_project_number,
    )


def _cloud_build_name_parts(name: Any) -> tuple[str, str, str] | None:
    if not isinstance(name, str):
        return None
    parts = name.split("/")
    if (
        len(parts) != 6
        or parts[0] != "projects"
        or parts[2] != "locations"
        or parts[4] != "builds"
        or not parts[1]
        or not parts[3]
        or not parts[5]
    ):
        return None
    return parts[1], parts[3], parts[5]


def _trusted_cloud_build_project_reference(
    *,
    invocation_project: str,
    build_project_id: str,
    build_name_project: str,
    expected_project_id: str | None,
    expected_project_number: str | None,
) -> bool:
    if expected_project_id is None and expected_project_number is None:
        return build_project_id == invocation_project and build_name_project == invocation_project
    if (
        not isinstance(expected_project_id, str)
        or not expected_project_id.strip()
        or not isinstance(expected_project_number, str)
        or not expected_project_number.isdigit()
    ):
        return False
    expected_project_references = {expected_project_id, expected_project_number}
    return (
        invocation_project == expected_project_id
        and build_project_id == expected_project_id
        and build_name_project in expected_project_references
    )


def _connected_repository_commit(
    build_document: Mapping[str, Any],
    *,
    expected_connected_repository: str | None,
    expected_source_commit: str,
) -> str | None:
    source = build_document.get("source")
    if not isinstance(source, Mapping) or "connectedRepository" not in source:
        return None
    if set(source) != {"connectedRepository"}:
        raise RollbackSafetyError("Cloud Build connected repository source is ambiguous")
    connected_repository = source.get("connectedRepository")
    if not isinstance(connected_repository, Mapping):
        raise RollbackSafetyError("Cloud Build connected repository source is invalid")
    repository = connected_repository.get("repository")
    if (
        expected_connected_repository is None
        or not isinstance(repository, str)
        or repository != expected_connected_repository
    ):
        raise RollbackSafetyError("Cloud Build connected repository is invalid")
    revision = connected_repository.get("revision")
    if not isinstance(revision, str) or not revision.strip():
        raise RollbackSafetyError("Cloud Build connected repository revision is missing")
    if revision != expected_source_commit:
        raise RollbackSafetyError("Cloud Build source commit is invalid")
    return revision


def verify_image_runtime_contract(
    *,
    image_ref: str,
    image_id: str,
    source_commit: str,
    image_config: Mapping[str, Any],
    probe_document: Mapping[str, Any],
) -> dict[str, Any]:
    _required_image_ref(image_ref)
    _required_image_id(image_id)
    if _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise RollbackSafetyError("runtime image source commit is invalid")
    command_parts: list[str] = []
    for field in ("Entrypoint", "Cmd"):
        value = image_config.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
            raise RollbackSafetyError("runtime image entrypoint config is invalid")
        command_parts.extend(value)
    command = " ".join(command_parts)
    if (
        re.search(
            r"(?:^|\s)(?:/app/)?\.venv/bin/uvicorn\s+zeler_sheets\.app:make_app\s+--factory(?:\s|$)",
            command,
        )
        is None
    ):
        raise RollbackSafetyError("runtime image entrypoint contract is invalid")
    expected_probe = {
        "entrypoint_import": True,
        "module_id": "sheets",
        "registry_fingerprint": canonical_sheets_registration_fingerprint(),
        "scope_count": len(CANONICAL_SHEETS_SCOPES),
        "routing_key_count": len(CANONICAL_SHEETS_ROUTING_KEYS),
    }
    if dict(probe_document) != expected_probe:
        raise RollbackSafetyError("runtime image no-secret contract probe is invalid")
    return {
        "schema_version": 1,
        "image_ref": image_ref,
        "image_id": image_id,
        "source_commit": source_commit,
        "entrypoint": "zeler_sheets.app:make_app --factory",
        "registry_fingerprint": canonical_sheets_registration_fingerprint(),
        "scope_count": len(CANONICAL_SHEETS_SCOPES),
        "routing_key_count": len(CANONICAL_SHEETS_ROUTING_KEYS),
        "image_config_sha256": _sha256_json(image_config),
        "probe_sha256": _sha256_json(probe_document),
    }


def verify_running_image_binding(
    *,
    target_image_ref: str,
    container_image_id: str,
    expected_image_id: str,
    image_repo_digests: Sequence[str],
) -> None:
    _required_image_ref(target_image_ref)
    _required_image_id(container_image_id)
    _required_image_id(expected_image_id)
    if container_image_id != expected_image_id:
        raise RollbackSafetyError("running container does not use the verified image object")
    if target_image_ref not in image_repo_digests:
        raise RollbackSafetyError("verified image object RepoDigest does not match target")


def verify_runtime_binding(
    *,
    image_ref: str,
    repo_digests: Sequence[str],
    health_document: Mapping[str, Any],
) -> None:
    _required_image_ref(image_ref)
    if image_ref not in repo_digests:
        raise RollbackSafetyError("running Sheets API RepoDigest does not match verified image")
    checks = health_document.get("checks")
    registry = checks.get("registry") if isinstance(checks, Mapping) else None
    mongo = checks.get("mongo") if isinstance(checks, Mapping) else None
    rabbitmq = checks.get("rabbitmq") if isinstance(checks, Mapping) else None
    if (
        health_document.get("ready") is not True
        or not isinstance(registry, Mapping)
        or registry.get("ok") is not True
        or registry.get("detail") != "registry_fingerprint_match"
        or not isinstance(mongo, Mapping)
        or mongo.get("ok") is not True
        or not isinstance(rabbitmq, Mapping)
        or rabbitmq.get("ok") is not True
    ):
        raise RollbackSafetyError("Sheets API runtime health or registry fingerprint is invalid")


def _required_image_ref(image_ref: str) -> re.Match[str]:
    match = _IMAGE_REF_PATTERN.fullmatch(image_ref)
    if match is None:
        raise RollbackSafetyError("immutable Artifact Registry image reference is invalid")
    return match


def _single_subject_binds_image(
    subjects: Any,
    *,
    expected_repository: str,
    expected_digest: str,
) -> bool:
    if not isinstance(subjects, list) or len(subjects) != 1:
        return False
    subject = subjects[0]
    if not isinstance(subject, Mapping):
        return False
    digest = subject.get("digest")
    subject_name = subject.get("name")
    return (
        isinstance(digest, Mapping)
        and digest.get("sha256") == expected_digest
        and isinstance(subject_name, str)
        and _normalized_slsa_subject_repository(subject_name, expected_repository)
        == expected_repository
    )


def _normalized_slsa_subject_repository(subject_name: str, expected_repository: str) -> str | None:
    if subject_name == expected_repository:
        return subject_name
    parsed = urlparse(subject_name)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    expected_host, separator, _expected_path = expected_repository.partition("/")
    if (
        not separator
        or parsed.netloc != expected_host
        or not expected_host.endswith("-docker.pkg.dev")
    ):
        return None
    subject_path = parsed.path.lstrip("/")
    repository_path, tag_separator, tag = subject_path.rpartition(":")
    if not tag_separator or not repository_path or not tag:
        return None
    return f"{parsed.netloc}/{repository_path}"


def _required_image_id(image_id: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RollbackSafetyError("Docker image object identity is invalid")


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract-build-id")
    extract.add_argument("--artifact-provenance", type=Path, required=True)
    extract.add_argument("--image-ref", required=True)
    verify = subparsers.add_parser("verify-gcloud")
    verify.add_argument("--artifact-provenance", type=Path, required=True)
    verify.add_argument("--build", type=Path, required=True)
    verify.add_argument("--image-ref", required=True)
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--connected-repository")
    verify.add_argument("--expected-project-id")
    verify.add_argument("--expected-project-number")
    runtime = subparsers.add_parser("verify-runtime")
    runtime.add_argument("--repo-digests", type=Path, required=True)
    runtime.add_argument("--health", type=Path, required=True)
    runtime.add_argument("--image-ref", required=True)
    image_contract = subparsers.add_parser("verify-image-contract")
    image_contract.add_argument("--image-config", type=Path, required=True)
    image_contract.add_argument("--probe", type=Path, required=True)
    image_contract.add_argument("--image-ref", required=True)
    image_contract.add_argument("--image-id", required=True)
    image_contract.add_argument("--source-commit", required=True)
    image_contract.add_argument("--proof-out", type=Path, required=True)
    release = subparsers.add_parser("verify-release-proof")
    release.add_argument("--proof", type=Path, required=True)
    release.add_argument("--image-ref", required=True)
    release.add_argument("--image-id", required=True)
    release.add_argument("--source-commit", required=True)
    running = subparsers.add_parser("verify-running-binding")
    running.add_argument("--repo-digests", type=Path, required=True)
    running.add_argument("--image-ref", required=True)
    running.add_argument("--container-image-id", required=True)
    running.add_argument("--expected-image-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "verify-running-binding":
            repo_digests = json.loads(args.repo_digests.read_text(encoding="utf-8"))
            if not isinstance(repo_digests, list) or not all(
                isinstance(value, str) for value in repo_digests
            ):
                raise RollbackSafetyError("image RepoDigest evidence is invalid")
            verify_running_image_binding(
                target_image_ref=args.image_ref,
                container_image_id=args.container_image_id,
                expected_image_id=args.expected_image_id,
                image_repo_digests=repo_digests,
            )
            print("running container image object and RepoDigest: verified")
            return 0
        if args.command == "verify-image-contract":
            image_config = json.loads(args.image_config.read_text(encoding="utf-8"))
            probe = json.loads(args.probe.read_text(encoding="utf-8"))
            if not isinstance(image_config, Mapping) or not isinstance(probe, Mapping):
                raise RollbackSafetyError("runtime image contract evidence is invalid")
            proof = verify_image_runtime_contract(
                image_ref=args.image_ref,
                image_id=args.image_id,
                source_commit=args.source_commit,
                image_config=image_config,
                probe_document=probe,
            )
            _atomic_json_write(args.proof_out, proof)
            print("runtime image config and no-secret contract probe: verified")
            return 0
        if args.command == "verify-release-proof":
            proof = json.loads(args.proof.read_text(encoding="utf-8"))
            if (
                not isinstance(proof, Mapping)
                or proof.get("schema_version") != 1
                or proof.get("image_ref") != args.image_ref
                or proof.get("image_id") != args.image_id
                or proof.get("source_commit") != args.source_commit
                or proof.get("registry_fingerprint") != canonical_sheets_registration_fingerprint()
                or proof.get("scope_count") != len(CANONICAL_SHEETS_SCOPES)
                or proof.get("routing_key_count") != len(CANONICAL_SHEETS_ROUTING_KEYS)
            ):
                raise RollbackSafetyError("runtime release proof is invalid")
            _required_image_id(args.image_id)
            print("runtime release proof: verified")
            return 0
        if args.command == "verify-runtime":
            repo_digests = json.loads(args.repo_digests.read_text(encoding="utf-8"))
            health_document = json.loads(args.health.read_text(encoding="utf-8"))
            if (
                not isinstance(repo_digests, list)
                or not all(isinstance(value, str) for value in repo_digests)
                or not isinstance(health_document, Mapping)
            ):
                raise RollbackSafetyError("runtime binding evidence is invalid")
            verify_runtime_binding(
                image_ref=args.image_ref,
                repo_digests=repo_digests,
                health_document=health_document,
            )
            print("running Sheets API digest and health: verified")
            return 0
        artifact_document = json.loads(args.artifact_provenance.read_text(encoding="utf-8"))
        if not isinstance(artifact_document, Mapping):
            raise RollbackSafetyError("Artifact Registry provenance document is invalid")
        if args.command == "extract-build-id":
            print(extract_cloud_build_id(artifact_document, image_ref=args.image_ref))
            return 0
        build_document = json.loads(args.build.read_text(encoding="utf-8"))
        if not isinstance(build_document, Mapping):
            raise RollbackSafetyError("Cloud Build document is invalid")
        verify_gcloud_provenance(
            image_ref=args.image_ref,
            artifact_document=artifact_document,
            build_document=build_document,
            expected_source_commit=args.source_commit,
            expected_connected_repository=args.connected_repository,
            expected_cloud_build_project_id=args.expected_project_id,
            expected_cloud_build_project_number=args.expected_project_number,
        )
    except (OSError, ValueError, RollbackSafetyError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Artifact Registry and Cloud Build provenance: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
