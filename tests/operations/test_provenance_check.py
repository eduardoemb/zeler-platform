"""Tests for the immutable digest and Compose provenance contract."""

from __future__ import annotations

from typing import Any

import pytest
from infra.deploy.provenance_check import (
    ProvenanceCheckError,
    check_compose_digest_binding,
    compose_image_refs,
    digest_pinned_image_ref,
    unpinned_image_refs,
)

REPOSITORY = "us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api"
DIGEST_HEX = "a" * 64
PINNED_IMAGE_REF = f"{REPOSITORY}@sha256:{DIGEST_HEX}"
MOVING_TAG_REF = f"{REPOSITORY}:rollout-v5"


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
