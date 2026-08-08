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

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

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
INVENTORY_PATH = "/sheets/formulas/inventory"
EXECUTE_PATH = "/sheets/formulas:execute"

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


class SmokeHttpError(RuntimeError):
    """Raised when an HTTP transport or payload failure cannot be classified."""

    def __init__(self, message: str, *, status_class: str) -> None:
        super().__init__(message)
        self.status_class = status_class


class InventoryInvalidError(ValueError):
    """Raised when the inventory payload is not the expected bounded shape."""


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


@dataclass(frozen=True)
class InventoryObservation:
    formulas_total: int
    formulas_implemented: int
    devoluciones_implemented: bool


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


def parse_inventory(payload: Any) -> InventoryObservation:
    if not isinstance(payload, Mapping):
        raise InventoryInvalidError("inventory payload must be an object")
    formulas = payload.get("formulas")
    if not isinstance(formulas, list):
        raise InventoryInvalidError("inventory payload must list formulas")
    implemented = 0
    devoluciones_implemented = False
    for contract in formulas:
        if not isinstance(contract, Mapping):
            raise InventoryInvalidError("inventory formula contract must be an object")
        if contract.get("status") == "implemented":
            implemented += 1
        if contract.get("name") == SMOKE_FORMULA and contract.get("status") == "implemented":
            devoluciones_implemented = True
    return InventoryObservation(
        formulas_total=len(formulas),
        formulas_implemented=implemented,
        devoluciones_implemented=devoluciones_implemented,
    )


def inventory_passes(observation: InventoryObservation) -> bool:
    return (
        observation.formulas_total == EXPECTED_FORMULA_COUNT
        and observation.formulas_implemented == EXPECTED_FORMULA_COUNT
        and observation.devoluciones_implemented
    )


async def fetch_inventory(client: httpx.AsyncClient, base_url: str) -> InventoryObservation:
    url = f"{base_url.rstrip('/')}{INVENTORY_PATH}"
    try:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SmokeHttpError("inventory request failed", status_class="transport_failed") from exc
    try:
        return parse_inventory(payload)
    except InventoryInvalidError as exc:
        raise SmokeHttpError(str(exc), status_class="inventory_mismatch") from exc


async def run_devoluciones(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    seller: str,
) -> str:
    """Execute one DEVOLUCIONES smoke and return its bounded status class."""
    url = f"{base_url.rstrip('/')}{EXECUTE_PATH}"
    payload: dict[str, Any] = {
        "formula": SMOKE_FORMULA,
        "cuenta": seller,
        "args": {
            "fecha_inicio": SMOKE_DATE_FROM,
            "fecha_final": SMOKE_DATE_TO,
            "id_publicaciones": "todos",
            "encabezados": "",
        },
    }
    try:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise SmokeHttpError(
            "devoluciones request failed", status_class="transport_failed"
        ) from exc
    if response.status_code in {401, 403}:
        return "auth_failed"
    if response.status_code != 200:
        return "formula_failed"
    try:
        body = response.json()
    except ValueError as exc:
        raise SmokeHttpError(
            "devoluciones response malformed", status_class="transport_failed"
        ) from exc
    if isinstance(body, Mapping) and body.get("ok") is True:
        return "success"
    code = _error_code(body)
    if code == "DATA_UNAVAILABLE":
        return "data_unavailable"
    if code in {"TOKEN_MISSING", "TOKEN_REVOKED", "SELLER_FORBIDDEN"}:
        return "auth_failed"
    return "formula_failed"


async def run_smoke(
    config: SmokeConfig,
    *,
    client_factory: Callable[[], httpx.AsyncClient],
    inventory_only: bool,
    dry_run: bool,
) -> SmokeResult:
    if dry_run:
        return SmokeResult("success", {"dry_run": 1}, exit_code_for("success"))
    async with client_factory() as client:
        try:
            inventory = await fetch_inventory(client, config.base_url)
        except SmokeHttpError as exc:
            return SmokeResult(exc.status_class, {}, exit_code_for(exc.status_class))
        counters: dict[str, int] = {
            "formulas_total": inventory.formulas_total,
            "formulas_implemented": inventory.formulas_implemented,
        }
        if not inventory_passes(inventory):
            return SmokeResult("inventory_mismatch", counters, exit_code_for("inventory_mismatch"))
        if inventory_only:
            counters["inventory_only"] = 1
            return SmokeResult("success", counters, exit_code_for("success"))
        try:
            devoluciones_class = await run_devoluciones(
                client,
                config.base_url,
                config.token,
                config.seller,
            )
        except SmokeHttpError as exc:
            return SmokeResult(exc.status_class, counters, exit_code_for(exc.status_class))
        counters["devoluciones"] = 1
        if devoluciones_class != "success":
            return SmokeResult(devoluciones_class, counters, exit_code_for(devoluciones_class))
        return SmokeResult("success", counters, exit_code_for("success"))


def _error_code(body: Any) -> str | None:
    if not isinstance(body, Mapping):
        return None
    error = body.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Env-only authenticated ZelerData smoke: validates the formula inventory "
            "and executes one DEVOLUCIONES smoke. Reads ZELERDATA_SMOKE_BASE_URL, "
            "ZELERDATA_SMOKE_TOKEN, and ZELERDATA_SMOKE_SELLER from the environment "
            "only; never mints, rotates, or reveals tokens; redacts both values from "
            "every output line."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and redact only; no network call is made.",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Validate the formula inventory and skip the DEVOLUCIONES execute smoke.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    env = os.environ if environment is None else environment
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0))
    try:
        config = config_from_env(env, dry_run=args.dry_run)
    except SmokeConfigError:
        result = SmokeResult("config_missing", {}, exit_code_for("config_missing"))
        print(_serialize(result))
        return result.exit_code
    result = asyncio.run(
        run_smoke(
            config,
            client_factory=factory,
            inventory_only=args.inventory_only,
            dry_run=args.dry_run,
        )
    )
    redacted = redact_text(_serialize(result), config)
    try:
        assert_redacted(redacted, config)
    except SmokeRedactionError:
        fallback = SmokeResult("redaction_failed", {}, exit_code_for("redaction_failed"))
        print(_serialize(fallback))
        return fallback.exit_code
    print(redacted)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
