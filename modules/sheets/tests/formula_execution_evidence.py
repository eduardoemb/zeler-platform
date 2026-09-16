"""Opt-in local dispatcher evidence; never a Sheets or correctness certificate."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.registry import FormulaRegistry

CALLS: dict[str, list[tuple[str, str]]] = {}
OUTCOMES: dict[str, str] = {}


async def execute_concurrently(
    dispatcher: FormulaDispatcher,
    contexts: list[FormulaExecutionContext],
    *,
    timeout: float = 30,
) -> dict[str, FormulaExecutionResult | FormulaDataUnavailableError]:
    catalog = {contract.name for contract in FormulaRegistry.default().list_contracts()}
    if len(contexts) != 52 or {context.contract.name for context in contexts} != catalog:
        raise ValueError("52 distinct registered formulas required")

    async def execute(
        context: FormulaExecutionContext,
    ) -> FormulaExecutionResult | FormulaDataUnavailableError:
        try:
            return await dispatcher.execute(context)
        except FormulaDataUnavailableError as error:
            return error

    tasks = [asyncio.create_task(execute(context)) for context in contexts]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
        return dict(zip((context.contract.name for context in contexts), results, strict=True))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def summarize(
    catalog: set[str], calls: dict[str, list[tuple[str, str]]], outcomes: dict[str, str]
) -> dict[str, Any]:
    formulas: dict[str, list[dict[str, str]]] = {name: [] for name in sorted(catalog)}
    unknown: set[str] = set()
    for test, observations in calls.items():
        if outcomes.get(test) != "passed":
            continue
        for name, outcome in sorted(set(observations)):
            if name not in formulas:
                unknown.add(name)
                continue
            formulas[name].append({"test": test, "outcome": outcome})
    return {
        "scope": "local dispatcher calls in passing tests; fixtures may be doubles",
        "formulas": formulas,
        "missing": [name for name, cases in formulas.items() if not cases],
        "unknown": sorted(unknown),
        "sheets_verified": False,
        "correctness_verified": False,
        "variants": "Review named assertions; return does not imply positive data",
    }


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--formula-evidence", help="Write sanitized local execution matrix JSON")


@pytest.fixture(autouse=True)
def record_formula_execution(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    original = FormulaDispatcher.execute
    observations = CALLS.setdefault(request.node.nodeid, [])

    async def execute(
        dispatcher: FormulaDispatcher, context: FormulaExecutionContext
    ) -> FormulaExecutionResult:
        try:
            result = await original(dispatcher, context)
        except FormulaDataUnavailableError:
            observations.append((context.contract.name, "unavailable"))
            raise
        observations.append((context.contract.name, "returned"))
        return result

    monkeypatch.setattr(FormulaDispatcher, "execute", execute)
    yield


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or report.failed or report.skipped:
        OUTCOMES[report.nodeid] = report.outcome


def pytest_sessionfinish(session: pytest.Session) -> None:
    target = session.config.getoption("--formula-evidence")
    if target:
        catalog = {contract.name for contract in FormulaRegistry.default().list_contracts()}
        Path(target).write_text(
            json.dumps(summarize(catalog, CALLS, OUTCOMES), indent=2) + "\n", encoding="utf-8"
        )
