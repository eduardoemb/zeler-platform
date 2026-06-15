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
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    ITEM_SHIPPING_CATALOG_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.handlers_orders_questions import BATCH_B_IMPLEMENTED_FORMULAS
from zeler_sheets.formulas.handlers_quality_calculator import (
    QUALITY_CALCULATOR_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    REMAINING_PHASE4_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    RETURNS_HISTORIES_WITHDRAWALS_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.registry import FormulaRegistry

FormulaRuntimeStateName = Literal["implemented", "unsupported"]


@dataclass(frozen=True, slots=True)
class FormulaRuntimeState:
    state: FormulaRuntimeStateName
    reason: str


UNSUPPORTED_FORMULA_REASONS: Mapping[str, str] = {}


def get_formula_runtime_states() -> dict[str, FormulaRuntimeState]:
    implemented = (
        CORE_FORMULA_NAMES
        | BATCH_B_IMPLEMENTED_FORMULAS
        | ITEM_SHIPPING_CATALOG_IMPLEMENTED_FORMULAS
        | RETURNS_HISTORIES_WITHDRAWALS_IMPLEMENTED_FORMULAS
        | QUALITY_CALCULATOR_IMPLEMENTED_FORMULAS
        | REMAINING_PHASE4_IMPLEMENTED_FORMULAS
    )
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
