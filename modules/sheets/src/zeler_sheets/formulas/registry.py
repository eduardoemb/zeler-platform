from __future__ import annotations

from collections.abc import Iterable, Sequence

from zeler_sheets.formulas.matrix_contracts import ACTIVE_FORMULA_RAW_CONTRACTS
from zeler_sheets.formulas.schemas import FormulaContract, FormulaParameterContract

STABLE_ERROR_CODES = (
    "TOKEN_MISSING",
    "TOKEN_REVOKED",
    "SELLER_FORBIDDEN",
    "FORMULA_UNKNOWN",
    "BAD_ARGUMENT",
    "DATA_UNAVAILABLE",
    "RATE_LIMITED",
    "INTERNAL",
)

_SCALAR_INPUT_CASES = ("scalar",)
_RANGE_INPUT_CASES = ("scalar", "row_range", "column_range", "rectangular_range")
_RANGE_INPUT_PARAMETER_NAMES = {
    "skus",
    "id_publicaciones",
    "codes",
    "codigo_ml",
    "compradores",
    "id_ordenes",
}

_RAW_CONTRACTS: Sequence[tuple[str, str, str, str, str]] = ACTIVE_FORMULA_RAW_CONTRACTS


class FormulaRegistry:
    def __init__(self, contracts: Iterable[FormulaContract]) -> None:
        self._contracts = tuple(contracts)
        self._contracts_by_name = {contract.name: contract for contract in self._contracts}
        if len(self._contracts_by_name) != len(self._contracts):
            raise ValueError("formula contracts must have unique names")

    @property
    def error_codes(self) -> tuple[str, ...]:
        return STABLE_ERROR_CODES

    @property
    def unknown_formula_error_code(self) -> str:
        return "FORMULA_UNKNOWN"

    @classmethod
    def default(cls) -> FormulaRegistry:
        return cls(_build_contracts(_RAW_CONTRACTS))

    def list_contracts(self) -> tuple[FormulaContract, ...]:
        return self._contracts

    def find(self, name: str) -> FormulaContract | None:
        return self._contracts_by_name.get(name)

    def get(self, name: str) -> FormulaContract:
        contract = self.find(name)
        if contract is None:
            raise KeyError(name)
        return contract

    def find_required(self, name: str) -> FormulaContract:
        return self.get(name)


def _build_contracts(
    raw_contracts: Sequence[tuple[str, str, str, str, str]],
) -> tuple[FormulaContract, ...]:
    return tuple(
        FormulaContract(
            name=name,
            signature=signature,
            batch=batch,
            output_shape=output_shape,
            output_contract=output_contract,
            parameters=_parameters_from_signature(signature),
        )
        for name, signature, batch, output_shape, output_contract in raw_contracts
    )


def _parameters_from_signature(signature: str) -> tuple[FormulaParameterContract, ...]:
    raw_parameters = signature.removeprefix("(").removesuffix(")").split(", ")
    return tuple(_parameter_from_token(raw_parameter) for raw_parameter in raw_parameters)


def _parameter_from_token(token: str) -> FormulaParameterContract:
    name, separator, default_value = token.partition("=")
    return FormulaParameterContract(
        name=name,
        required=separator == "",
        default=_decode_default(default_value) if separator else None,
        input_cases=_input_cases_for_parameter(name),
    )


def _decode_default(value: str) -> str:
    return value.removeprefix('"').removesuffix('"')


def _input_cases_for_parameter(name: str) -> tuple[str, ...]:
    if name in _RANGE_INPUT_PARAMETER_NAMES:
        return _RANGE_INPUT_CASES
    return _SCALAR_INPUT_CASES
