"""Precalculated results for the heavy aggregate ZelerData formulas.

A Sheets custom function cannot exceed the caller's 30 second budget, and the
five formulas that walk the whole catalog legitimately reach 20-27 seconds on
the pilot. The agreed bridge is to compute those results during the refresh
cycle and serve them from the read model, so the formula call becomes a bounded
document read (Q3, Q8, Q16).

The cache is deliberately conservative:

* only the heavy aggregate formulas are cached, never the detail formulas;
* a result is keyed by seller, formula and the *canonical* argument map, so two
  spellings of the same call share one entry and a different argument can never
  read another caller's result;
* an entry is served only while ``valid_until`` is in the future, the same
  window the freshness markers use, so a stopped refresh loop degrades to the
  existing under-demand path instead of serving a stale table as current.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from zeler_platform_core.read_model_freshness import READ_MODEL_MARKER_VALIDITY
from zeler_sheets.formulas.registry import FormulaRegistry

logger = structlog.get_logger(__name__)

COLLECTION = "sheets_formula_precalculated"

# Q3/Q8: the formulas that aggregate many rows are precalculated; the detail
# formulas stay on demand because their cost is per-row and their arguments are
# unbounded.
PRECALCULATED_FORMULAS: frozenset[str] = frozenset(
    {
        "ZELERDATA_CATALOGO",
        "ZELERDATA_CATALOGOBUYBOX",
        "ZELERDATA_CATALOGO_COMPLETO",
        "ZELERDATA_CALIDAD",
        "ZELERDATA_DASHBOARD",
    }
)


@dataclass(frozen=True, slots=True)
class PrecalculatedResult:
    values: list[list[Any]]
    meta: dict[str, Any]


def canonical_arguments(formula: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Fold one call into the exact variant the contract defines.

    Missing optional arguments are filled with the contract default and
    ``cuenta`` is replaced by a constant, because the seller identity is already
    part of the key. Without this, ``{}`` and ``{"encabezados": ""}`` would be
    two entries for one identical result.
    """
    contract = FormulaRegistry.default().find(formula)
    if contract is None:
        raise ValueError(f"unknown formula {formula}")
    canonical: dict[str, Any] = {}
    for parameter in contract.parameters:
        if parameter.name == "cuenta":
            canonical[parameter.name] = "account"
            continue
        if parameter.name in args:
            canonical[parameter.name] = args[parameter.name]
        elif not parameter.required and parameter.default is not None:
            canonical[parameter.name] = parameter.default
    return canonical


def cache_identity(seller_id: str, formula: str, args: Mapping[str, Any]) -> str:
    """Return the deterministic cache key for one seller, formula and variant."""
    canonical = canonical_arguments(formula, args)
    payload = json.dumps(
        {"seller_id": str(seller_id), "formula": formula, "args": canonical},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class PrecalculatedFormulaStore:
    """Read and write precalculated formula results with a bounded validity."""

    def __init__(
        self,
        db: Any,
        *,
        now: Callable[[], datetime] | None = None,
        validity: Any = READ_MODEL_MARKER_VALIDITY,
    ) -> None:
        self._db = db
        self._now = now or (lambda: datetime.now(UTC))
        self._validity = validity

    async def read(
        self, *, seller_id: str, formula: str, args: Mapping[str, Any]
    ) -> PrecalculatedResult | None:
        if formula not in PRECALCULATED_FORMULAS:
            return None
        identity = cache_identity(seller_id, formula, args)
        document = await self._db[COLLECTION].find_one({"_id": identity})
        if not isinstance(document, Mapping):
            return None
        valid_until = _utc_or_none(document.get("valid_until"))
        if valid_until is None or valid_until <= self._now().astimezone(UTC):
            return None
        values = document.get("values")
        if not isinstance(values, list):
            return None
        meta = dict(document.get("meta") or {})
        meta["precalculated"] = True
        meta["precalculated_at"] = _iso(document.get("computed_at"))
        return PrecalculatedResult(values=[list(row) for row in values], meta=meta)

    async def write(
        self,
        *,
        seller_id: str,
        formula: str,
        args: Mapping[str, Any],
        values: list[list[Any]],
        meta: Mapping[str, Any],
    ) -> None:
        if formula not in PRECALCULATED_FORMULAS:
            return
        current = self._now().astimezone(UTC)
        identity = cache_identity(seller_id, formula, args)
        await self._db[COLLECTION].replace_one(
            {"_id": identity},
            {
                "_id": identity,
                "seller_id": str(seller_id),
                "formula": formula,
                "args": canonical_arguments(formula, args),
                "values": values,
                "meta": dict(meta),
                "computed_at": current,
                "valid_until": current + self._validity,
                "schema_version": 1,
            },
            upsert=True,
        )


# The variants are the ones the shipped Apps Script can actually produce: the
# header flag is the only optional argument the sheets toggle, and every other
# parameter keeps its contract default. Precalculating an open-ended argument
# space would be unbounded work for results nobody asks for.
_VARIANT_ARGUMENTS: Mapping[str, tuple[Mapping[str, Any], ...]] = {
    "ZELERDATA_CATALOGO": ({"tipo_precio": "base"},),
    "ZELERDATA_CATALOGOBUYBOX": ({},),
    "ZELERDATA_CATALOGO_COMPLETO": ({},),
    "ZELERDATA_CALIDAD": ({},),
    "ZELERDATA_DASHBOARD": (
        {"skus": "todos", "tipo_almacenamiento": "todos", "tipo_precio": "base"},
    ),
}
_HEADER_VARIANTS: tuple[str, ...] = ("si", "")

# Synthetic token label for the audit trail, not a credential.
_PRECALCULATED_TOKEN_LABEL = "zelerdata-precalculated"  # noqa: S105


def variant_argument_sets(formula: str) -> tuple[dict[str, Any], ...]:
    """Return every argument variant this platform precalculates for a formula."""
    base_variants = _VARIANT_ARGUMENTS.get(formula)
    if base_variants is None:
        return ()
    return tuple(
        {**variant, "encabezados": headers}
        for variant in base_variants
        for headers in _HEADER_VARIANTS
    )


class PrecalculatedFormulaWarmer:
    """Compute and store the precalculated results for one seller.

    The warmer runs inside the refresh cycle, where the same data is already
    being refreshed. It uses the real dispatcher, so a formula that cannot be
    produced from productive data raises and is simply not cached: an empty or
    partial table is never published as if it were the real answer.
    """

    def __init__(
        self,
        *,
        dispatcher: Any,
        store: PrecalculatedFormulaStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))

    async def warm(self, *, seller_id: str, cuenta: str) -> int:
        """Compute every variant and return how many were stored."""
        from zeler_sheets.formulas.dispatcher import (
            FormulaDataUnavailableError,
            FormulaExecutionContext,
        )

        registry = FormulaRegistry.default()
        written = 0
        for formula in sorted(PRECALCULATED_FORMULAS):
            contract = registry.find(formula)
            if contract is None:  # pragma: no cover - registry guard
                continue
            for variant in variant_argument_sets(formula):
                context = FormulaExecutionContext(
                    contract=contract,
                    cuenta=cuenta,
                    seller_id=str(seller_id),
                    seller_nickname=cuenta,
                    # Not a credential: a synthetic token label so the formula
                    # audit trail can tell a precalculated result from a caller.
                    token_id=_PRECALCULATED_TOKEN_LABEL,
                    args=variant,
                    request_id=None,
                )
                try:
                    result = await self._dispatcher.execute(context)
                except FormulaDataUnavailableError:
                    # No productive data for this variant: cache nothing rather
                    # than publish a partial table as the real result.
                    continue
                except Exception:  # noqa: BLE001 - one formula must not stop the rest
                    logger.warning("zelerdata.precalculated_formula_failed", formula=formula)
                    continue
                await self._store.write(
                    seller_id=str(seller_id),
                    formula=formula,
                    args=variant,
                    values=[list(row) for row in result.values],
                    meta=dict(result.meta),
                )
                written += 1
        return written


def _utc_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _iso(value: Any) -> str | None:
    parsed = _utc_or_none(value)
    return None if parsed is None else parsed.isoformat()
