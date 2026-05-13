from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

from zeler_sheets.formulas.schemas import FormulaContract


@dataclass(frozen=True, slots=True)
class FormulaExecutionContext:
    contract: FormulaContract
    cuenta: str
    seller_id: str
    seller_nickname: str
    token_id: str
    args: Mapping[str, Any]
    request_id: str | None


@dataclass(frozen=True, slots=True)
class FormulaExecutionResult:
    values: list[list[Any]]
    meta: dict[str, Any]


class FormulaDataUnavailableError(Exception):
    def __init__(self, formula: str) -> None:
        super().__init__(f"{formula} data is not available yet")
        self.formula = formula
        self.message = f"{formula} data is not available yet"


FormulaHandler: TypeAlias = Callable[
    [FormulaExecutionContext], FormulaExecutionResult | Awaitable[FormulaExecutionResult]
]


class FormulaDispatcher:
    def __init__(self, handlers: Mapping[str, FormulaHandler] | None = None) -> None:
        self._handlers = dict(handlers or {})

    async def execute(self, context: FormulaExecutionContext) -> FormulaExecutionResult:
        handler = self._handlers.get(context.contract.name)
        if handler is None:
            raise FormulaDataUnavailableError(context.contract.name)
        result = handler(context)
        if inspect.isawaitable(result):
            return await result
        return result
