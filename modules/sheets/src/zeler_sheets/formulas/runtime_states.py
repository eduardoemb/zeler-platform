# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaExecutionContext,
    FormulaExecutionResult,
    FormulaHandler,
)
from zeler_sheets.formulas.handlers_core import CORE_FORMULA_NAMES
from zeler_sheets.formulas.handlers_orders_questions import BATCH_B_IMPLEMENTED_FORMULAS
from zeler_sheets.formulas.registry import FormulaRegistry

FormulaRuntimeStateName = Literal["implemented", "unsupported"]


@dataclass(frozen=True, slots=True)
class FormulaRuntimeState:
    state: FormulaRuntimeStateName
    reason: str


UNSUPPORTED_FORMULA_REASONS: Mapping[str, str] = {
    "SHEETSELLER_PAUSADAS": "Historical paused-period read model is not available in zeler-platform yet.",
    "sheetseller_enviarafull": "Full replenishment recommendation read model is not available in zeler-platform yet.",
    "SHEETSELLER_PUBLICACIONESDESCUIDADAS": "Neglected-publication history/read model is not available in zeler-platform yet.",
    "SHEETSELLER_CATALOGO": "Catalog/buybox snapshot read model is not available in zeler-platform yet.",
    "SHEETSELLER_TIEMPOSINSTOCK": "Stock history read model is not available in zeler-platform yet.",
    "SHEETSELLER_TIEMPOACTIVA": "Active-time history read model is not available in zeler-platform yet.",
    "SHEETSELLER_CATALOGOSINVINCULAR": "Recommended catalog-linking read model is not available in zeler-platform yet.",
    "SHEETSELLER_CATALOGOBUYBOX": "Catalog/buybox competition read model is not available in zeler-platform yet.",
    "SHEETSELLER_COMISION": "Commission and fee read model is not available in zeler-platform yet.",
    "SHEETSELLER_DEVOLUCIONES": "Returns/claims read model is not available in zeler-platform yet.",
    "SHEETSELLER_COMPETENCIA": "Competition snapshot read model is not available in zeler-platform yet.",
    "SHEETSELLER_CATALOGOTIEMPO": "Catalog winning-time history read model is not available in zeler-platform yet.",
    "SHEETSELLER_PRECIOHISTORICO": "Price history read model is not available in zeler-platform yet.",
    "SHEETSELLER_TIEMPOSTOCKACTIVO": "Stock-available history read model is not available in zeler-platform yet.",
    "SHEETSELLER_CALIDAD": "Listing quality/health read model is not available in zeler-platform yet.",
    "SHEETSELLER_CALCULADORA": "Cost/category/catalog calculator read model is not available in zeler-platform yet.",
    "SHEETSELLER_RETIROS": "Full withdrawals read model is not available in zeler-platform yet.",
    "SHEETSELLER_SEMANASCONSTOCK": "Weekly stock-presence history read model is not available in zeler-platform yet.",
    "SHEETSELLER_MEDIDASGENERAL": "Measurement read model is not available in zeler-platform yet.",
    "SHEETSELLER_MEDIDAS": "Measurement read model is not available in zeler-platform yet.",
    "SHEETSELLER_SUPERMERCADO": "Supermarket/regular listing flag read model is not available in zeler-platform yet.",
    "sheetseller_obtener_catalogo": "Catalog collection read model is not available in zeler-platform yet.",
    "SHEETSELLER_COSTOENVIOVENDEDOR": "Seller-paid shipping cost read model is not available in zeler-platform yet.",
    "SHEETSELLER_COMPRADORES": "Current canonical orders do not expose buyer/shipping address fields.",
    "SHEETSELLER_ENVIOSMERCADOENVIOS": "MercadoEnvios shipment/label read model is not available in zeler-platform yet.",
}


def get_formula_runtime_states() -> dict[str, FormulaRuntimeState]:
    implemented = CORE_FORMULA_NAMES | BATCH_B_IMPLEMENTED_FORMULAS
    registry = FormulaRegistry.default()
    states: dict[str, FormulaRuntimeState] = {}
    for contract in registry.list_contracts():
        if contract.name in implemented:
            states[contract.name] = FormulaRuntimeState(
                state="implemented",
                reason="Implemented with seller-scoped zeler-platform read models.",
            )
        else:
            states[contract.name] = FormulaRuntimeState(
                state="unsupported",
                reason=UNSUPPORTED_FORMULA_REASONS[contract.name],
            )
    return states


def build_explicit_unsupported_formula_handlers() -> dict[str, FormulaHandler]:
    return {
        formula: _unsupported_handler(formula, reason)
        for formula, reason in UNSUPPORTED_FORMULA_REASONS.items()
    }


def _unsupported_handler(formula: str, reason: str) -> FormulaHandler:
    async def handler(context: FormulaExecutionContext) -> FormulaExecutionResult:
        raise FormulaDataUnavailableError(context.contract.name or formula, reason)

    return handler
