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
    "ZELERDATA_PAUSADAS": "Historical paused-period read model is not available in zeler-platform yet.",
    "ZELERDATA_ENVIARAFULL": "Full replenishment recommendation read model is not available in zeler-platform yet.",
    "ZELERDATA_PUBLICACIONESDESCUIDADAS": "Neglected-publication history/read model is not available in zeler-platform yet.",
    "ZELERDATA_CATALOGO": "Catalog/buybox snapshot read model is not available in zeler-platform yet.",
    "ZELERDATA_TIEMPOSINSTOCK": "Stock history read model is not available in zeler-platform yet.",
    "ZELERDATA_TIEMPOACTIVA": "Active-time history read model is not available in zeler-platform yet.",
    "ZELERDATA_CATALOGOSINVINCULAR": "Recommended catalog-linking read model is not available in zeler-platform yet.",
    "ZELERDATA_CATALOGOBUYBOX": "Catalog/buybox competition read model is not available in zeler-platform yet.",
    "ZELERDATA_COMISION": "Commission and fee read model is not available in zeler-platform yet.",
    "ZELERDATA_DEVOLUCIONES": "Returns/claims read model is not available in zeler-platform yet.",
    "ZELERDATA_COMPETENCIA": "Competition snapshot read model is not available in zeler-platform yet.",
    "ZELERDATA_CATALOGOTIEMPO": "Catalog winning-time history read model is not available in zeler-platform yet.",
    "ZELERDATA_PRECIOHISTORICO": "Price history read model is not available in zeler-platform yet.",
    "ZELERDATA_TIEMPOSTOCKACTIVO": "Stock-available history read model is not available in zeler-platform yet.",
    "ZELERDATA_CALIDAD": "Listing quality/health read model is not available in zeler-platform yet.",
    "ZELERDATA_CALCULADORA": "Cost/category/catalog calculator read model is not available in zeler-platform yet.",
    "ZELERDATA_RETIROS": "Full withdrawals read model is not available in zeler-platform yet.",
    "ZELERDATA_SEMANASCONSTOCK": "Weekly stock-presence history read model is not available in zeler-platform yet.",
    "ZELERDATA_MEDIDASGENERAL": "Measurement read model is not available in zeler-platform yet.",
    "ZELERDATA_MEDIDAS": "Measurement read model is not available in zeler-platform yet.",
    "ZELERDATA_SUPERMERCADO": "Supermarket/regular listing flag read model is not available in zeler-platform yet.",
    "ZELERDATA_OBTENER_CATALOGO": "Catalog collection read model is not available in zeler-platform yet.",
    "ZELERDATA_COSTOENVIOVENDEDOR": "Seller-paid shipping cost read model is not available in zeler-platform yet.",
    "ZELERDATA_ENVIOSMERCADOENVIOS": "MercadoEnvios shipment/label read model is not available in zeler-platform yet.",
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
