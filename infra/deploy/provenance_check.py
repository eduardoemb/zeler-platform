"""Contract helpers for the opt-in immutable-digest provenance gate.

Moving tags are documentation metadata only; they are never treated as deploy
authority. The contract refuses any compose image that is not pinned to a
sha256 digest before a pull can occur.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from infra.deploy.sheets_rollback import (
    RollbackSafetyError,
    extract_cloud_build_id,
    verify_gcloud_provenance,
)

PROOF_SCHEMA_VERSION = 1
_IMAGE_REF_PATTERN = re.compile(r"[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class ProvenanceCheckError(RuntimeError):
    pass


def digest_pinned_image_ref(image_ref: str) -> bool:
    """True only for `repo@sha256:<64 hex>` references (immutable)."""
    return _IMAGE_REF_PATTERN.fullmatch(image_ref) is not None


def compose_image_refs(compose_document: Mapping[str, Any]) -> list[str]:
    """Return every service `image:` value in definition order."""
    services = compose_document.get("services")
    if not isinstance(services, Mapping):
        raise ProvenanceCheckError("compose services mapping is missing")
    image_refs: list[str] = []
    for service_name, service in services.items():
        if not isinstance(service, Mapping):
            continue
        image = service.get("image")
        if image is None:
            continue
        if not isinstance(image, str):
            raise ProvenanceCheckError(f"service {service_name!r} has an invalid image value")
        image_refs.append(image)
    return image_refs


def unpinned_image_refs(compose_document: Mapping[str, Any]) -> list[str]:
    """Return compose images that are not digest-pinned."""
    return [ref for ref in compose_image_refs(compose_document) if not digest_pinned_image_ref(ref)]


def check_compose_digest_binding(compose_document: Mapping[str, Any]) -> None:
    """Fail closed when any compose image is a moving tag or malformed ref."""
    unpinned = unpinned_image_refs(compose_document)
    if unpinned:
        listed = ", ".join(unpinned)
        raise ProvenanceCheckError(
            f"REQUIRE_DIGEST_BINDING refuses moving image tags before pull: {listed}"
        )


def _image_digest(image_ref: str) -> str:
    return f"sha256:{image_ref.split('@sha256:', 1)[1]}"


def _authoritative_source_commit(build_document: Mapping[str, Any]) -> str:
    """Extract the Cloud Build source commit from the trusted build document."""
    source_provenance = build_document.get("sourceProvenance")
    resolved = (
        source_provenance.get("resolvedRepoSource")
        if isinstance(source_provenance, Mapping)
        else None
    )
    commit_sha = resolved.get("commitSha") if isinstance(resolved, Mapping) else None
    if isinstance(commit_sha, str) and _COMMIT_PATTERN.fullmatch(commit_sha):
        return commit_sha
    source = build_document.get("source")
    connected = source.get("connectedRepository") if isinstance(source, Mapping) else None
    revision = connected.get("revision") if isinstance(connected, Mapping) else None
    if isinstance(revision, str) and _COMMIT_PATTERN.fullmatch(revision):
        return revision
    raise ProvenanceCheckError("Cloud Build source commit is missing or invalid")


def _build_connected_repository(build_document: Mapping[str, Any]) -> str | None:
    source = build_document.get("source")
    connected = source.get("connectedRepository") if isinstance(source, Mapping) else None
    if not isinstance(connected, Mapping):
        return None
    repository = connected.get("repository")
    revision = connected.get("revision")
    if (
        not isinstance(repository, str)
        or not repository.strip()
        or not isinstance(revision, str)
        or not revision.strip()
    ):
        return None
    return repository


def verify_image_to_commit(
    *,
    image_ref: str,
    artifact_document: Mapping[str, Any],
    build_document: Mapping[str, Any],
    expected_source_commit: str | None = None,
    expected_connected_repository: str | None = None,
    expected_cloud_build_project_id: str | None = None,
    expected_cloud_build_project_number: str | None = None,
) -> dict[str, str]:
    """Verify one digest-pinned image against its SLSA v1 subject/build/commit.

    Returns `{"digest", "build_id", "source_commit"}` for the image_to_commit
    evidence. When `expected_source_commit` is omitted the commit is derived
    from the trusted Cloud Build document itself; supplying it enforces the
    operator assertion exactly.
    """
    if not digest_pinned_image_ref(image_ref):
        raise ProvenanceCheckError(
            f"immutable image reference is required; got moving tag or malformed ref: {image_ref}"
        )
    source_commit = expected_source_commit or _authoritative_source_commit(build_document)
    connected_repository = expected_connected_repository
    if connected_repository is None:
        connected_repository = _build_connected_repository(build_document)
    try:
        verified = verify_gcloud_provenance(
            image_ref=image_ref,
            artifact_document=artifact_document,
            build_document=build_document,
            expected_source_commit=source_commit,
            expected_connected_repository=connected_repository,
            expected_cloud_build_project_id=expected_cloud_build_project_id,
            expected_cloud_build_project_number=expected_cloud_build_project_number,
        )
    except RollbackSafetyError as exc:
        raise ProvenanceCheckError(str(exc)) from exc
    return {
        "digest": _image_digest(image_ref),
        "build_id": verified.build_id,
        "source_commit": verified.source_commit,
    }


def image_to_commit_document(images: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """Build the bounded `image_to_commit.json` document, validating entries."""
    for image_ref, entry in images.items():
        if not digest_pinned_image_ref(image_ref):
            raise ProvenanceCheckError(f"immutable image reference is required; got {image_ref}")
        for field in ("digest", "build_id", "source_commit"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ProvenanceCheckError(f"image entry for {image_ref} is missing {field}")
    return {"schema_version": PROOF_SCHEMA_VERSION, "images": dict(images)}


def merge_image_to_commit(
    existing: Mapping[str, Any] | None,
    image_ref: str,
    entry: Mapping[str, str],
) -> dict[str, Any]:
    """Merge one verified image entry into an existing evidence document."""
    if existing is None:
        merged = image_to_commit_document({})
    elif (
        not isinstance(existing, Mapping) or existing.get("schema_version") != PROOF_SCHEMA_VERSION
    ):
        raise ProvenanceCheckError("existing image_to_commit.json schema_version is invalid")
    else:
        images = existing.get("images")
        if not isinstance(images, Mapping):
            raise ProvenanceCheckError("existing image_to_commit.json images mapping is invalid")
        merged = image_to_commit_document(images)
    images = dict(merged["images"])
    images[image_ref] = dict(entry)
    return image_to_commit_document(images)


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


def write_image_to_commit(path: Path, document: Mapping[str, Any]) -> None:
    if not isinstance(document, Mapping):
        raise ProvenanceCheckError("image_to_commit document is invalid")
    _atomic_json_write(path, document)


def _read_existing_map(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ProvenanceCheckError("existing image_to_commit.json is invalid")
    return document


def _read_compose(path: Path) -> Mapping[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ProvenanceCheckError("compose file does not contain a mapping")
    return document


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infra.deploy.provenance_check")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check-compose")
    check.add_argument("--compose-file", type=Path, required=True)
    list_images = subparsers.add_parser("list-images")
    list_images.add_argument("--compose-file", type=Path, required=True)
    extract = subparsers.add_parser("extract-build-id")
    extract.add_argument("--artifact-file", type=Path, required=True)
    extract.add_argument("--image-ref", required=True)
    verify = subparsers.add_parser("verify-image")
    verify.add_argument("--image-ref", required=True)
    verify.add_argument("--artifact-file", type=Path, required=True)
    verify.add_argument("--build-file", type=Path, required=True)
    verify.add_argument("--source-commit")
    verify.add_argument("--connected-repository")
    verify.add_argument("--expected-project-id")
    verify.add_argument("--expected-project-number")
    verify.add_argument("--map-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "check-compose":
            check_compose_digest_binding(_read_compose(args.compose_file))
            print("digest binding: every compose image is pinned by sha256 digest")
            return 0
        if args.command == "list-images":
            for image_ref in compose_image_refs(_read_compose(args.compose_file)):
                print(image_ref)
            return 0
        if args.command == "extract-build-id":
            artifact_document = json.loads(args.artifact_file.read_text(encoding="utf-8"))
            if not isinstance(artifact_document, Mapping):
                raise ProvenanceCheckError("Artifact Registry provenance document is invalid")
            print(extract_cloud_build_id(artifact_document, image_ref=args.image_ref))
            return 0
        if args.command == "verify-image":
            artifact_document = json.loads(args.artifact_file.read_text(encoding="utf-8"))
            build_document = json.loads(args.build_file.read_text(encoding="utf-8"))
            if not isinstance(artifact_document, Mapping) or not isinstance(
                build_document, Mapping
            ):
                raise ProvenanceCheckError("provenance evidence is invalid")
            entry = verify_image_to_commit(
                image_ref=args.image_ref,
                artifact_document=artifact_document,
                build_document=build_document,
                expected_source_commit=args.source_commit,
                expected_connected_repository=args.connected_repository,
                expected_cloud_build_project_id=args.expected_project_id,
                expected_cloud_build_project_number=args.expected_project_number,
            )
            merged = merge_image_to_commit(_read_existing_map(args.map_out), args.image_ref, entry)
            write_image_to_commit(args.map_out, merged)
            print(f"image_to_commit.json: {args.image_ref} digest/build/source verified")
            return 0
    except (OSError, ValueError, ProvenanceCheckError) as exc:
        raise SystemExit(str(exc)) from exc
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
