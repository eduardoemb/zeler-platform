from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import structlog
from pymongo.errors import PyMongoError
from test_formula_api import _app_with_token, _execute
from test_formula_handlers_quality_calculator import NOW, _context, _item_row

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError, FormulaExecutionResult
from zeler_sheets.formulas.handlers_quality_calculator import QualityCalculatorFormulaHandlers
from zeler_sheets.formulas.recovery import ItemInventoryRecoveryRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("formula", ["ZELERDATA_CALIDAD", "ZELERDATA_CALCULADORA"])
@pytest.mark.parametrize("missing_base", [False, True])
async def test_missing_enrichment_recovers_independently_of_inventory(
    formula: str, missing_base: bool
) -> None:
    row = _item_row(item_id="MLA1", sku="sku", title="Owned", status="active")
    row["source_snapshot"] = {}

    class Repository:
        async def require_read_model_productive(self, **kwargs: Any) -> None:
            raise FormulaDataUnavailableError(formula, read_model="item_formula_rows")

        async def find_recent_item_inventory(self, **kwargs: Any) -> Any:
            return [row], ["MLA1", "MLA2"], (("MLA2",) if missing_base else ()), True

    handlers = QualityCalculatorFormulaHandlers(Repository(), now_fn=lambda: NOW)  # type: ignore[arg-type]
    handler = (
        handlers.sheetseller_calidad
        if formula.endswith("CALIDAD")
        else handlers.sheetseller_calculadora
    )
    result = await handler(_context(formula, {}))
    intents = (*((result.recovery,) if result.recovery else ()), *result.additional_recoveries)
    assert any(intent.item_ids == ("MLA1",) for intent in intents)
    assert any(not intent.item_ids for intent in intents) is missing_base
    assert result.values[0][0] == "MLA1"
    assert "DATA_UNAVAILABLE" in result.values[0]


@pytest.mark.asyncio
async def test_explicit_enrichment_does_not_suppress_current_inventory_refresh() -> None:
    async def handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[["MLA1", "DATA_UNAVAILABLE"]],
            meta={"inventory_enumeration_current": True},
            recovery=FormulaDataUnavailableError(
                context.contract.name, read_model="item_formula_rows", item_ids=("MLA1",)
            ),
        )

    app, _, token = await _app_with_token(now=NOW, formula_dispatcher=handler)
    queued: list[Any] = []

    class Queue:
        async def enqueue(self, request: Any) -> str:
            queued.append(request)
            return str(request.key)

    app.state.formula_recovery_queue = Queue()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _execute(client, token, formula="ZELERDATA_CALIDAD", args={})
    assert response.json()["values"] == [["MLA1", "DATA_UNAVAILABLE"]]
    assert response.json()["meta"]["inventory_refresh_requested"] is True
    assert len(queued) == 2
    assert sum(isinstance(intent, ItemInventoryRecoveryRequest) for intent in queued) == 1


@pytest.mark.asyncio
async def test_admission_accepts_work_after_old_one_second_limit() -> None:
    async def handler(context: Any) -> FormulaExecutionResult:
        raise FormulaDataUnavailableError(context.contract.name, read_model="item_formula_rows")

    app, _, token = await _app_with_token(now=NOW, formula_dispatcher=handler)

    class Queue:
        async def enqueue(self, request: Any) -> str:
            await asyncio.sleep(1.05)
            return str(request.key)

    app.state.formula_recovery_queue = Queue()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _execute(client, token, formula="ZELERDATA_CALIDAD", args={})
    assert response.json().get("meta", {}).get("recovery_requested") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ValueError("recovery seller capacity reached"), "capacity"),
        (ValueError("private-invalid-arguments"), "invalid_request"),
        (PyMongoError("private-connection-string"), "storage_unavailable"),
    ],
)
async def test_admission_outcomes_are_sanitized(error: Exception, outcome: str) -> None:
    async def handler(context: Any) -> FormulaExecutionResult:
        raise FormulaDataUnavailableError(context.contract.name, read_model="item_formula_rows")

    app, _, token = await _app_with_token(now=NOW, formula_dispatcher=handler)

    class Queue:
        async def enqueue(self, request: Any) -> str:
            raise error

    app.state.formula_recovery_queue = Queue()
    with structlog.testing.capture_logs() as logs:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await _execute(client, token, formula="ZELERDATA_CALIDAD", args={})
    events = [entry for entry in logs if entry["event"] == "formula_recovery_admission"]
    assert len(events) == 1
    assert events[0]["outcome"] == outcome
    assert "private-" not in str(logs)
    assert token not in str(logs)
    assert response.json()["error"]["code"] == "DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_batch_intents_share_one_admission_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_sheets import api

    monkeypatch.setattr(api, "RECOVERY_ADMISSION_SECONDS", 0.06)

    async def handler(context: Any) -> FormulaExecutionResult:
        return FormulaExecutionResult(
            values=[["kept"]],
            meta={},
            recovery=FormulaDataUnavailableError(
                context.contract.name, read_model="item_formula_rows"
            ),
        )

    app, _, token = await _app_with_token(now=NOW, formula_dispatcher=handler)
    accepted: list[str] = []
    cancelled = False
    attempts = 0

    class Queue:
        async def enqueue(self, request: Any) -> str:
            nonlocal cancelled, attempts
            attempts += 1
            if attempts >= 3:
                accepted.append(request.key)
                return str(request.key)
            try:
                await asyncio.sleep(0.04)
            except asyncio.CancelledError:
                cancelled = True
                raise
            accepted.append(request.key)
            return str(request.key)

    app.state.formula_recovery_queue = Queue()
    with structlog.testing.capture_logs() as logs:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/sheets/formulas:batch",
                json={
                    "requests": [
                        {"formula": "ZELERDATA_CALIDAD", "cuenta": "HOPEMOB", "args": {}}
                        for _ in range(3)
                    ]
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    results = response.json()["results"]
    assert len(accepted) == 1 and cancelled
    assert [entry["body"]["meta"]["recovery_requested"] for entry in results] == [
        True,
        False,
        False,
    ]
    assert [entry["body"]["values"] for entry in results] == [[["kept"]]] * 3
    assert [
        entry["outcome"] for entry in logs if entry["event"] == "formula_recovery_admission"
    ] == ["admitted", "deadline", "deadline"]


@pytest.mark.parametrize("status", ["trusted", "basis_mismatch", "transient", None])
def test_quality_with_invalidated_basis_stays_unavailable(status: str | None) -> None:
    from zeler_sheets.formulas.handlers_quality_calculator import _quality_row

    row = _item_row(
        item_id="MLA1",
        sku="SKU",
        title="Owned",
        status="active",
        quality_projection={
            "entity_type": "ITEM",
            "entity_id": "MLA1",
            "item_id": "MLA1",
            "source": "/item/{id}/performance",
            "observed_at": NOW,
            "calculated_at": NOW,
            "score": 88.0,
            "level": "good",
            "components": {},
            "pending_actions": [],
        },
    )
    if status is not None:
        row["current"]["enrichment_state"] = {"quality_projection": {"status": status}}
    values = _quality_row(row, now=NOW)
    assert values[7] == ("DATA_UNAVAILABLE" if status == "basis_mismatch" else 88)
    assert row["current"]["quality_projection"]["observed_at"] == NOW
