from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_formula_api import _app_with_token, _execute
from test_formula_handlers_quality_calculator import NOW
from test_formula_recovery import recovery_db  # noqa: F401 - shared isolated Mongo fixture

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError, FormulaExecutionResult
from zeler_sheets.formulas.recovery import IMPLEMENTED_MODELS, FormulaRecoveryQueue


@pytest.mark.asyncio
async def test_authenticated_formula_admits_base_and_enrichment_once(recovery_db: Any) -> None:  # noqa: F811
    async def handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[["MLA1", "DATA_UNAVAILABLE"]],
            meta={"inventory_enumeration_current": True},
            recovery=FormulaDataUnavailableError(
                context.contract.name, read_model="item_formula_rows", item_ids=("MLA1",)
            ),
        )

    app, _, token = await _app_with_token(now=NOW, formula_dispatcher=handler)
    queue = FormulaRecoveryQueue(
        recovery_db, enabled_models=IMPLEMENTED_MODELS, allowed_sellers=frozenset({"123456789"})
    )
    await queue.ensure_indexes()
    app.state.formula_recovery_queue = queue
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(2):
            response = await _execute(client, token, formula="ZELERDATA_CALIDAD", args={})
            assert response.json()["meta"]["inventory_refresh_requested"] is True
            assert response.json()["meta"]["recovery_requested"] is True
    jobs = await queue.collection.find({}).to_list(length=3)
    assert len(jobs) == 2
    assert {job["seller_id"] for job in jobs} == {"123456789"}
    assert {job["state"] for job in jobs} == {"pending"}
    assert sum(job.get("inventory_scope") is True for job in jobs) == 1
    assert [job["item_ids"] for job in jobs if "item_ids" in job] == [["MLA1"]]
