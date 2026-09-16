from __future__ import annotations

import asyncio
from importlib import import_module

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.registry import FormulaRegistry

summarize = import_module("modules.sheets.tests.formula_execution_evidence").summarize


def test_only_passing_executed_cases_count_as_local_evidence() -> None:
    report = summarize(
        {"A", "B", "C"},
        {"positive": [("A", "returned")], "absence": [("B", "unavailable")]},
        {"positive": "passed", "absence": "failed"},
    )
    assert report["formulas"]["A"] == [{"test": "positive", "outcome": "returned"}]
    assert report["formulas"]["B"] == []
    assert report["missing"] == ["B", "C"]
    assert report["sheets_verified"] is False
    assert report["correctness_verified"] is False


def test_unknown_formula_is_not_silently_added_to_catalog() -> None:
    report = summarize({"A"}, {"test": [("OTHER", "returned")]}, {"test": "passed"})
    assert report["unknown"] == ["OTHER"]
    assert report["missing"] == ["A"]


def contexts() -> list[FormulaExecutionContext]:
    return [
        FormulaExecutionContext(contract, "local", "local", "local", "local", {}, None)
        for contract in FormulaRegistry.default().list_contracts()
    ]


@pytest.mark.asyncio
async def test_concurrent_runner_enters_all_52_before_any_completes() -> None:
    evidence = import_module("modules.sheets.tests.formula_execution_evidence")
    entered: set[str] = set()
    released = asyncio.Event()

    async def handler(context: FormulaExecutionContext) -> FormulaExecutionResult:
        entered.add(context.contract.name)
        if len(entered) == 52:
            released.set()
        await released.wait()
        return FormulaExecutionResult([[context.contract.name]], {})

    dispatcher = FormulaDispatcher({context.contract.name: handler for context in contexts()})
    results = await evidence.execute_concurrently(dispatcher, contexts(), timeout=2)
    assert len(results) == len(entered) == 52
    assert all(result.values == [[name]] for name, result in results.items())


@pytest.mark.asyncio
async def test_concurrent_runner_rejects_missing_or_duplicate_formulas() -> None:
    evidence = import_module("modules.sheets.tests.formula_execution_evidence")
    for selected in (contexts()[:-1], [contexts()[0]] * 52):
        with pytest.raises(ValueError, match="52 distinct"):
            await evidence.execute_concurrently(FormulaDispatcher(), selected)


@pytest.mark.asyncio
async def test_missing_data_isolated_without_discarding_other_formula_results() -> None:
    evidence = import_module("modules.sheets.tests.formula_execution_evidence")
    missing_name = contexts()[0].contract.name

    async def handler(context: FormulaExecutionContext) -> FormulaExecutionResult:
        if context.contract.name == missing_name:
            raise FormulaDataUnavailableError(missing_name)
        return FormulaExecutionResult([[context.contract.name]], {})

    dispatcher = FormulaDispatcher({context.contract.name: handler for context in contexts()})
    results = await evidence.execute_concurrently(dispatcher, contexts())
    assert isinstance(results.pop(missing_name), FormulaDataUnavailableError)
    assert len(results) == 51
    assert all(result.values == [[name]] for name, result in results.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unexpected"])
async def test_failed_batch_drains_all_started_tasks(failure: str) -> None:
    evidence = import_module("modules.sheets.tests.formula_execution_evidence")
    active: set[str] = set()
    entered = asyncio.Event()
    blocked = asyncio.Event()

    async def handler(context: FormulaExecutionContext) -> FormulaExecutionResult:
        active.add(context.contract.name)
        if len(active) == 52:
            entered.set()
        try:
            await entered.wait()
            if failure == "unexpected" and context.contract.name == contexts()[0].contract.name:
                raise RuntimeError("test failure")
            await blocked.wait()
            return FormulaExecutionResult([], {})
        finally:
            active.remove(context.contract.name)

    dispatcher = FormulaDispatcher({context.contract.name: handler for context in contexts()})
    with pytest.raises(TimeoutError if failure == "timeout" else RuntimeError):
        await evidence.execute_concurrently(dispatcher, contexts(), timeout=0.1)
    assert entered.is_set()
    assert active == set()
