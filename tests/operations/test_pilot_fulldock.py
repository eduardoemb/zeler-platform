from __future__ import annotations

import pytest
from tests.operations.preflight import PreflightContext, run_preflight
from tests.operations.smoke_helpers import FakePilotStack


@pytest.mark.asyncio
async def test_pilot_fulldock_preflight_is_retired_not_active() -> None:
    stack = FakePilotStack(module="fulldock", history_collection="fulldock_inventory_rules")
    result = await run_preflight(PreflightContext.for_stack(stack))

    assert result.passed is False
    assert result.checks["rabbitmq"].detail == "unsupported module fulldock"
    assert stack.rabbitmq.published == []
    assert "fulldock_inventory_rules" not in stack.mongo.collections
