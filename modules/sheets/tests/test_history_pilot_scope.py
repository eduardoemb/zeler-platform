"""Optional rollout scope fences the real coordinator before any renewal/source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_history_onboarding import Gateway
from test_history_onboarding import db as db

from zeler_platform_core.history_onboarding import admit_history_onboarding
from zeler_sheets.consumer import build_history_onboarding_poller
from zeler_sheets.history_onboarding import HistoryOnboardingWorker


@pytest.mark.asyncio
async def test_optional_pilot_scope_leaves_other_account_completely_untouched(db: Any) -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    await admit_history_onboarding(db, "456", now=now - timedelta(days=1))
    await admit_history_onboarding(db, "123", now=now)
    await db.meli_accounts.insert_many(
        [
            {"_id": "a", "seller_id": 123, "status": "active"},
            {"_id": "b", "seller_id": 456, "status": "active"},
        ]
    )
    await db.sheets_history_backfill_plans.update_many({}, {"$set": {"source_cursor": 3}})
    other = await db.sheets_history_backfill_plans.find_one({"_id": "456"})
    worker = HistoryOnboardingWorker(
        db, Gateway(), Gateway(), now=lambda: now, allowed_sellers=frozenset({"123"})
    )
    assert await worker.process_once() == "processed"
    assert await db.sheets_history_backfill_plans.find_one({"_id": "456"}) == other
    selected = await db.sheets_history_backfill_plans.find_one({"_id": "123"})
    assert selected["source_cursor"] == 4
    assert "certificate_renewal" in selected
    # Absent scope remains the ordinary account-independent product behavior.
    unrestricted = HistoryOnboardingWorker(db, Gateway(), Gateway(), now=lambda: now)
    assert await unrestricted.process_once() == "processed"
    arbitrary = await db.sheets_history_backfill_plans.find_one({"_id": "456"})
    assert arbitrary["source_cursor"] == 4
    assert "certificate_renewal" in arbitrary


@pytest.mark.parametrize(
    "scope",
    [frozenset(), frozenset({"*"}), frozenset({"00123"}), frozenset({"１２３"}), frozenset({"-1"})],
)
def test_explicit_invalid_scope_fails_closed(scope: frozenset[str]) -> None:
    with pytest.raises(ValueError, match="seller"):
        HistoryOnboardingWorker({}, Gateway(), Gateway(), allowed_sellers=scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["", " ", "*", "123,", "00123", "１２３", "123,-1"])
async def test_factory_invalid_explicit_scope_fails_startup(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_SELLERS", raw)
    with pytest.raises(ValueError, match="seller"):
        await build_history_onboarding_poller(db={}, kms_client=None, detail_gateway=Gateway())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"), [(None, None), ("123,456", frozenset({"123", "456"}))]
)
async def test_factory_passes_optional_scope_to_real_worker(
    raw: str | None, expected: frozenset[str] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if raw is None:
        monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_SELLERS", raising=False)
    else:
        monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_SELLERS", raw)
    supervisor = await build_history_onboarding_poller(
        db={}, kms_client=None, detail_gateway=Gateway()
    )
    assert supervisor.lanes[0]._processor.allowed_sellers == expected
