"""Tests for the immutable digest and Compose provenance contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from infra.deploy.provenance_check import (
    PROOF_SCHEMA_VERSION,
    ProvenanceCheckError,
    check_compose_digest_binding,
    compose_image_refs,
    digest_pinned_image_ref,
    image_to_commit_document,
    merge_image_to_commit,
    unpinned_image_refs,
    verify_image_to_commit,
    write_image_to_commit,
)

REPOSITORY = "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api"
DIGEST_HEX = "a" * 64
PINNED_IMAGE_REF = f"{REPOSITORY}@sha256:{DIGEST_HEX}"
MOVING_TAG_REF = f"{REPOSITORY}:rollout-v5"
SOURCE_COMMIT = "6ae0608226b6eee32797427506ad19bd03ef2af6"
CONNECTED_REPOSITORY = (
    "projects/zeler-platform-dev/locations/us-central1/connections/"
    "zeler-platform-github/repositories/zeler-platform"
)
CONNECTED_SOURCE_COMMIT = "7a455f76b33d7401a7b772499ccaf35dae6cff66"


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


def _cloud_build(
    *,
    build_id: str = "build-123",
    commit_sha: str = SOURCE_COMMIT,
    connected_repository: dict[str, str] | None = None,
) -> dict[str, Any]:
    build: dict[str, Any] = {
        "name": f"projects/zeler-platform-dev/locations/us-central1/builds/{build_id}",
        "id": build_id,
        "projectId": "zeler-platform-dev",
        "status": "SUCCESS",
        "sourceProvenance": {"resolvedRepoSource": {"commitSha": commit_sha}},
    }
    if connected_repository is not None:
        build["source"] = {"connectedRepository": connected_repository}
        build["sourceProvenance"]["resolvedRepoSource"]["commitSha"] = ""
    return build


def _compose(services: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"services": services}


# --- digest_pinned_image_ref -------------------------------------------------


def test_digest_pinned_image_ref_accepts_only_sha256_pinned_refs() -> None:
    assert digest_pinned_image_ref(PINNED_IMAGE_REF) is True
    assert digest_pinned_image_ref(MOVING_TAG_REF) is False
    assert digest_pinned_image_ref("mongo:7.0") is False
    assert digest_pinned_image_ref(f"{REPOSITORY}@sha256:{'a' * 63}") is False
    assert digest_pinned_image_ref("") is False


# --- compose_image_refs ------------------------------------------------------


def test_compose_image_refs_extracts_service_images_in_definition_order() -> None:
    compose = _compose(
        {
            "mongo": {"image": "mongo:7.0"},
            "sheets-api": {"image": PINNED_IMAGE_REF},
            "gateway": {"image": MOVING_TAG_REF},
            "builder": {"build": {"context": "."}},
        }
    )

    assert compose_image_refs(compose) == ["mongo:7.0", PINNED_IMAGE_REF, MOVING_TAG_REF]


def test_compose_image_refs_raises_on_non_string_image_value() -> None:
    compose = _compose({"sheets-api": {"image": ["not", "a", "string"]}})

    with pytest.raises(ProvenanceCheckError, match="sheets-api"):
        compose_image_refs(compose)


def test_compose_image_refs_raises_on_missing_services_mapping() -> None:
    with pytest.raises(ProvenanceCheckError, match="services"):
        compose_image_refs({"not_services": {}})


# --- check_compose_digest_binding --------------------------------------------


def test_check_compose_digest_binding_fails_closed_on_any_moving_tag() -> None:
    compose = _compose(
        {
            "sheets-api": {"image": PINNED_IMAGE_REF},
            "gateway": {"image": MOVING_TAG_REF},
        }
    )

    unpinned = unpinned_image_refs(compose)
    assert unpinned == [MOVING_TAG_REF]

    with pytest.raises(ProvenanceCheckError, match=MOVING_TAG_REF):
        check_compose_digest_binding(compose)


def test_check_compose_digest_binding_accepts_all_pinned_images() -> None:
    compose = _compose(
        {
            "sheets-api": {"image": PINNED_IMAGE_REF},
            "gateway": {
                "image": "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/"
                f"gateway@sha256:{'b' * 64}"
            },
        }
    )

    assert unpinned_image_refs(compose) == []
    check_compose_digest_binding(compose)  # must not raise


# --- verify_image_to_commit --------------------------------------------------


def test_verify_image_to_commit_emits_digest_build_and_source_commit() -> None:
    verified = verify_image_to_commit(
        image_ref=PINNED_IMAGE_REF,
        artifact_document=_gcloud_provenance(PINNED_IMAGE_REF),
        build_document=_cloud_build(),
    )

    assert verified == {
        "digest": f"sha256:{DIGEST_HEX}",
        "build_id": "build-123",
        "source_commit": SOURCE_COMMIT,
    }


def test_verify_image_to_commit_accepts_connected_repository_source() -> None:
    verified = verify_image_to_commit(
        image_ref=PINNED_IMAGE_REF,
        artifact_document=_gcloud_provenance(PINNED_IMAGE_REF),
        build_document=_cloud_build(
            connected_repository={
                "repository": CONNECTED_REPOSITORY,
                "revision": CONNECTED_SOURCE_COMMIT,
            }
        ),
    )

    assert verified["build_id"] == "build-123"
    assert verified["source_commit"] == CONNECTED_SOURCE_COMMIT


def test_verify_image_to_commit_refuses_moving_tag_before_evidence_check() -> None:
    with pytest.raises(ProvenanceCheckError, match="immutable"):
        verify_image_to_commit(
            image_ref=MOVING_TAG_REF,
            artifact_document=_gcloud_provenance(PINNED_IMAGE_REF),
            build_document=_cloud_build(),
        )


def test_verify_image_to_commit_fails_closed_on_missing_provenance() -> None:
    artifact = _gcloud_provenance(PINNED_IMAGE_REF)
    artifact["provenance_summary"]["provenance"] = []

    with pytest.raises(ProvenanceCheckError, match="provenance"):
        verify_image_to_commit(
            image_ref=PINNED_IMAGE_REF,
            artifact_document=artifact,
            build_document=_cloud_build(),
        )


def test_verify_image_to_commit_fails_closed_on_forged_builder() -> None:
    artifact = _gcloud_provenance(PINNED_IMAGE_REF, builder="self-asserted")

    with pytest.raises(ProvenanceCheckError, match="builder"):
        verify_image_to_commit(
            image_ref=PINNED_IMAGE_REF,
            artifact_document=artifact,
            build_document=_cloud_build(),
        )


def test_verify_image_to_commit_fails_closed_on_source_commit_mismatch() -> None:
    with pytest.raises(ProvenanceCheckError, match="source commit"):
        verify_image_to_commit(
            image_ref=PINNED_IMAGE_REF,
            artifact_document=_gcloud_provenance(PINNED_IMAGE_REF),
            build_document=_cloud_build(commit_sha="f" * 40),
            expected_source_commit=SOURCE_COMMIT,
        )


def test_verify_image_to_commit_fails_closed_when_build_has_no_source_commit() -> None:
    build = _cloud_build()
    build["sourceProvenance"] = {}

    with pytest.raises(ProvenanceCheckError, match="source commit"):
        verify_image_to_commit(
            image_ref=PINNED_IMAGE_REF,
            artifact_document=_gcloud_provenance(PINNED_IMAGE_REF),
            build_document=build,
        )


# --- image_to_commit document + atomic write ---------------------------------


def test_image_to_commit_document_uses_schema_version_and_images_mapping() -> None:
    entry = {
        "digest": f"sha256:{DIGEST_HEX}",
        "build_id": "build-123",
        "source_commit": SOURCE_COMMIT,
    }

    document = image_to_commit_document({PINNED_IMAGE_REF: entry})

    assert document["schema_version"] == PROOF_SCHEMA_VERSION
    assert document["images"] == {PINNED_IMAGE_REF: entry}


def test_image_to_commit_document_rejects_incomplete_entries() -> None:
    with pytest.raises(ProvenanceCheckError, match="build_id"):
        image_to_commit_document(
            {PINNED_IMAGE_REF: {"digest": f"sha256:{DIGEST_HEX}", "source_commit": SOURCE_COMMIT}}
        )


def test_merge_image_to_commit_accumulates_multiple_images() -> None:
    gateway_ref = PINNED_IMAGE_REF.replace("/sheets-api", "/gateway")
    first = image_to_commit_document(
        {
            PINNED_IMAGE_REF: {
                "digest": f"sha256:{DIGEST_HEX}",
                "build_id": "b1",
                "source_commit": SOURCE_COMMIT,
            }
        }
    )

    merged = merge_image_to_commit(
        first,
        gateway_ref,
        {
            "digest": f"sha256:{'b' * 64}",
            "build_id": "b2",
            "source_commit": CONNECTED_SOURCE_COMMIT,
        },
    )

    assert merged["schema_version"] == PROOF_SCHEMA_VERSION
    assert set(merged["images"]) == {PINNED_IMAGE_REF, gateway_ref}


def test_merge_image_to_commit_rejects_existing_wrong_schema() -> None:
    with pytest.raises(ProvenanceCheckError, match="schema_version"):
        merge_image_to_commit(
            {"schema_version": 99, "images": {}},
            PINNED_IMAGE_REF,
            {"digest": f"sha256:{DIGEST_HEX}", "build_id": "b1", "source_commit": SOURCE_COMMIT},
        )


def test_write_image_to_commit_writes_expected_json(tmp_path: Path) -> None:
    target = tmp_path / "image_to_commit.json"
    entry = {
        "digest": f"sha256:{DIGEST_HEX}",
        "build_id": "build-123",
        "source_commit": SOURCE_COMMIT,
    }
    document = image_to_commit_document({PINNED_IMAGE_REF: entry})

    write_image_to_commit(target, document)

    assert json.loads(target.read_text(encoding="utf-8")) == document
