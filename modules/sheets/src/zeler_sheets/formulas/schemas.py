from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormulaParameterContract:
    name: str
    required: bool
    default: str | None
    input_cases: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "required": self.required,
            "default": self.default,
            "input_cases": list(self.input_cases),
        }


@dataclass(frozen=True, slots=True)
class FormulaContract:
    name: str
    signature: str
    batch: str
    output_shape: str
    output_contract: str
    parameters: tuple[FormulaParameterContract, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "signature": self.signature,
            "batch": self.batch,
            "output_shape": self.output_shape,
            "output_contract": self.output_contract,
            "parameters": [parameter.to_json_dict() for parameter in self.parameters],
        }
