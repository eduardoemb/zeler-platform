from __future__ import annotations

import pytest
from tests.operations.preflight import PreflightContext, run_preflight
from tests.operations.smoke_helpers import FakePilotStack, run_module_smoke


@pytest.mark.asyncio
async def test_pilot_fulldock_preflight_and_smoke_are_idempotent() -> None:
    stack = FakePilotStack(module="fulldock", history_collection="fulldock_inventory_rules")
    assert (await run_preflight(PreflightContext.for_stack(stack))).passed is True

    first = await run_module_smoke(stack)
    second = await run_module_smoke(stack)

    assert first == {"module": "fulldock", "history_count": 1, "response": {"status": "ok"}}
    assert second == first
