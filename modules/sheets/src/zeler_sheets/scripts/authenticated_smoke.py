"""Env-only authenticated ZelerData smoke CLI (SDD Lane A5).

Reads the base URL, token, and seller exclusively from the environment
(``ZELERDATA_SMOKE_BASE_URL``, ``ZELERDATA_SMOKE_TOKEN``,
``ZELERDATA_SMOKE_SELLER``). It never accepts a token on the command line,
never mints, rotates, or reveals tokens, and redacts the token and seller
values from every output line.

The real short-lived smoke credential is a Lane B (B1) operator input and stays
out of scope for this code; the CLI only consumes whatever the environment
provides. No production call, no Mongo access, no Docker build, and no
token-lifecycle endpoint is ever touched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

STAGE = "zelerdata_smoke"
SMOKE_FORMULA = "ZELERDATA_DEVOLUCIONES"
EXPECTED_FORMULA_COUNT = 52
# Fixed closed smoke range inside the documented pilot accepted coverage.
SMOKE_DATE_FROM = "2026-06-01"
SMOKE_DATE_TO = "2026-06-04"

ENV_BASE_URL = "ZELERDATA_SMOKE_BASE_URL"
ENV_TOKEN = "ZELERDATA_SMOKE_TOKEN"  # noqa: S105 - environment variable name.
ENV_SELLER = "ZELERDATA_SMOKE_SELLER"
REQUIRED_ENV_NAMES = (ENV_BASE_URL, ENV_TOKEN, ENV_SELLER)

TOKEN_REDACTED = "[REDACTED_TOKEN]"  # noqa: S105 - placeholder label.
SELLER_REDACTED = "[REDACTED_SELLER]"

EXIT_CODES: Mapping[str, int] = {
    "success": 0,
    "config_missing": 2,
    "inventory_mismatch": 3,
    "auth_failed": 4,
    "data_unavailable": 5,
    "formula_failed": 6,
    "transport_failed": 7,
    "redaction_failed": 8,
}


class SmokeConfigError(ValueError):
    """Raised when required environment values are missing."""


class SmokeRedactionError(RuntimeError):
    """Raised when a token or seller value would leak into output."""


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    token: str
    seller: str


@dataclass(frozen=True)
class SmokeResult:
    status_class: str
    counters: Mapping[str, int]
    exit_code: int


def exit_code_for(status_class: str) -> int:
    return EXIT_CODES[status_class]


def config_from_env(environment: Mapping[str, str], *, dry_run: bool = False) -> SmokeConfig:
    """Read env-only smoke values and fail closed when required values are absent."""
    values = {name: environment.get(name, "").strip() for name in REQUIRED_ENV_NAMES}
    required = (ENV_TOKEN,) if dry_run else REQUIRED_ENV_NAMES
    missing = [name for name in required if not values[name]]
    if missing:
        raise SmokeConfigError("missing environment: " + ", ".join(missing))
    return SmokeConfig(
        base_url=values[ENV_BASE_URL],
        token=values[ENV_TOKEN],
        seller=values[ENV_SELLER],
    )


def redact_text(text: str, config: SmokeConfig) -> str:
    redacted = text
    if config.token:
        redacted = redacted.replace(config.token, TOKEN_REDACTED)
    if config.seller:
        redacted = redacted.replace(config.seller, SELLER_REDACTED)
    return redacted


def assert_redacted(text: str, config: SmokeConfig) -> None:
    leaked = [
        label
        for label, value in (("token", config.token), ("seller", config.seller))
        if value and value in text
    ]
    if leaked:
        raise SmokeRedactionError("redaction failed for " + ", ".join(leaked))


def build_evidence(status_class: str, counters: Mapping[str, int]) -> dict[str, Any]:
    return {
        "stage": STAGE,
        "status_class": status_class,
        "counters": dict(sorted(counters.items())),
    }


def _serialize(result: SmokeResult) -> str:
    return json.dumps(
        build_evidence(result.status_class, result.counters),
        sort_keys=True,
        separators=(",", ":"),
    )
