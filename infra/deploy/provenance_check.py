"""Contract helpers for the opt-in immutable-digest provenance gate.

Moving tags are documentation metadata only; they are never treated as deploy
authority. The contract refuses any compose image that is not pinned to a
sha256 digest before a pull can occur.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_IMAGE_REF_PATTERN = re.compile(r"[a-z0-9.-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")


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
