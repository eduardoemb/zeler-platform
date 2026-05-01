from __future__ import annotations

import pytest
from tests.operations.preflight import PreflightContext, run_preflight
from tests.operations.smoke_helpers import FakePilotStack, run_module_smoke


@pytest.mark.asyncio
async def test_pilot_sheets_preflight_and_smoke_are_idempotent() -> None:
    stack = FakePilotStack(module="sheets", history_collection="sheets_exports")
    assert (await run_preflight(PreflightContext.for_stack(stack))).passed is True

    first = await run_module_smoke(stack)
    second = await run_module_smoke(stack)

    assert first == {"module": "sheets", "history_count": 1, "response": {"status": "ok"}}
    assert second == first
