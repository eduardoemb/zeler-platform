from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
    FormulaExecutionResult,
)
from zeler_sheets.formulas.handlers_core import build_core_formula_handlers
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    build_item_shipping_catalog_formula_handlers,
)
from zeler_sheets.formulas.handlers_orders_questions import build_order_question_formula_handlers
from zeler_sheets.formulas.handlers_quality_calculator import (
    build_quality_calculator_formula_handlers,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import build_remaining_phase4_formula_handlers
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    build_returns_histories_withdrawals_formula_handlers,
)
from zeler_sheets.formulas.read_models import FormulaReadModelRepository
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.formulas.runtime_states import build_explicit_unsupported_formula_handlers
from zeler_sheets.scripts.goal_formula_smoke import build_cases


@pytest.mark.asyncio
async def test_52_real_handlers_concurrently_preserve_cold_source_results() -> None:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?directConnection=true", serverSelectionTimeoutMS=3000
    )
    database = client[f"formula_concurrent_{uuid4().hex}"]
    try:
        hello = await client.admin.command("hello")
        assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
        repository = FormulaReadModelRepository(db=database)
        now = datetime(2026, 9, 15, 12, tzinfo=UTC)
        dispatcher = FormulaDispatcher(
            build_core_formula_handlers(repository, now_fn=lambda: now)
            | build_item_shipping_catalog_formula_handlers(repository, now_fn=lambda: now)
            | build_order_question_formula_handlers(repository, now_fn=lambda: now)
            | build_quality_calculator_formula_handlers(repository, now_fn=lambda: now)
            | build_remaining_phase4_formula_handlers(repository, now_fn=lambda: now)
            | build_returns_histories_withdrawals_formula_handlers(repository, now_fn=lambda: now)
            | build_explicit_unsupported_formula_handlers()
        )
        cases = build_cases(
            {
                "skus": "LOCAL-SKU",
                "id_publicaciones": "MLA123",
                "codigo_ml": "LOCAL-CODE",
                "id_ordenes": "123",
                "fecha_inicial": "2026-08-08",
                "fecha_final": "2026-09-06",
            }
        )
        contexts = [
            FormulaExecutionContext(
                contract, "local", "local", "local", "local", cases[contract.name], None
            )
            for contract in FormulaRegistry.default().list_contracts()
        ]
        evidence = import_module("modules.sheets.tests.formula_execution_evidence")
        concurrent = await evidence.execute_concurrently(dispatcher, contexts)
        assert len(concurrent) == 52
        for context in contexts:
            observed = concurrent[context.contract.name]
            try:
                sequential = await dispatcher.execute(context)
            except FormulaDataUnavailableError as expected:
                assert isinstance(observed, FormulaDataUnavailableError)
                assert observed.formula == expected.formula
                assert observed.read_model == expected.read_model
            else:
                assert isinstance(observed, FormulaExecutionResult)
                assert observed.values == sequential.values
                assert observed.recovery == sequential.recovery
        assert await database.list_collection_names() == []
    finally:
        await client.drop_database(database.name)
        client.close()
