from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
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
    seller_timezone: str = "UTC"


@dataclass(frozen=True, slots=True)
class FormulaExecutionResult:
    values: list[list[Any]]
    meta: dict[str, Any]


class FormulaDataUnavailableError(Exception):
    def __init__(
        self,
        formula: str,
        reason: str | None = None,
        *,
        read_model: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        order_ids: tuple[str, ...] = (),
        shipment_ids: tuple[str, ...] = (),
    ) -> None:
        message = f"{formula} data is not available yet"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)
        self.formula = formula
        self.message = message
        self.read_model = read_model
        self.date_from = date_from
        self.date_to = date_to
        self.order_ids = order_ids
        self.shipment_ids = shipment_ids


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
