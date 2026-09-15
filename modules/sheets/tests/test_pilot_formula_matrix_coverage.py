"""TDD: task 4.1 — every one of the 52 active formulas has contract tests.

The pilot requires that all 52 formulas are executed, not just a subset.
This test derives the active formula list from the registry and asserts
that each formula name appears in at least one of the handler test files,
so a formula without any test cannot silently pass the acceptance gate.
It is a coverage assertion, not a behavioral test.
"""

from __future__ import annotations

from pathlib import Path

from zeler_sheets.formulas.registry import FormulaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
HANDLER_TEST_FILES = [
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_core.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_orders_questions.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_remaining_phase4.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_handlers_quality_calculator.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_read_models.py",
    REPO_ROOT / "modules/sheets/tests/test_formula_recovery.py",
]


def _formula_name(function_name: str) -> str:
    """Handler test functions reference formulas via dispatcher context; the
    mapping from test name to formula name is not 1:1. Instead we search the
    test file contents for the formula name string."""
    return function_name


def test_registry_exposes_exactly_52_active_formulas() -> None:
    contracts = FormulaRegistry.default().list_contracts()
    assert len(contracts) == 52


def test_every_active_formula_is_referenced_in_handler_tests() -> None:
    """Each formula name must appear as a string in at least one handler test
    file. This proves the formula has at least one direct or indirect test
    reference; behavioral correctness is proven by the tests themselves."""
    contracts = FormulaRegistry.default().list_contracts()
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in HANDLER_TEST_FILES if path.exists()
    )
    missing = [
        contract.name
        for contract in contracts
        if f'"{contract.name}"' not in combined and f"'{contract.name}'" not in combined
    ]
    assert missing == [], "Formulas without any handler-test reference: " + ", ".join(missing)
