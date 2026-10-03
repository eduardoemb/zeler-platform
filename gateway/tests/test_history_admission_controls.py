"""History admission hold is independent from OAuth and bootstrap behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from gateway.tests.test_oauth_emit_accounts_linked import FakeDb, FakePublisher

from zeler_gateway.oauth import events


@pytest.mark.asyncio
@pytest.mark.parametrize("relink", [False, True])
async def test_hold_skips_new_history_intent_but_preserves_account_link_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    relink: bool,
) -> None:
    monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", "true")
    db, publisher = FakeDb(), FakePublisher()
    called: list[str] = []

    async def admission(_: Any, seller: str, **kwargs: Any) -> None:
        called.append(seller)

    monkeypatch.setattr(events, "admit_history_onboarding", admission)
    if relink:
        db.bootstrap_jobs.docs["bootstrap-82453304-oauth"] = {
            "_id": "bootstrap-82453304-oauth",
            "seller_id": "82453304",
            "state": "succeeded",
            "checkpoints": {"orders": 1},
        }
    await events.emit_accounts_linked(
        "82453304",
        "user",
        mongo_db=db,
        amqp_publisher=publisher,
        clock=lambda: datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert called == []
    assert db.bootstrap_jobs.docs["bootstrap-82453304-oauth"]["state"] == (
        "succeeded" if relink else "pending"
    )
    assert len(publisher.messages) == (0 if relink else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "seller", "admitted"),
    [
        ("82453304", "82453304", True),
        ("82453304", "456", False),
        ("", "82453304", False),
        ("*", "82453304", False),
        ("082453304", "82453304", False),
        (None, "456", True),
    ],
)
async def test_admission_scope_fences_nonpilot_without_disabling_oauth(
    monkeypatch: pytest.MonkeyPatch,
    scope: str | None,
    seller: str,
    admitted: bool,
) -> None:
    monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD", raising=False)
    if scope is None:
        monkeypatch.delenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", raising=False)
    else:
        monkeypatch.setenv("ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS", scope)
    called: list[str] = []

    async def admission(_: Any, value: str, **kwargs: Any) -> None:
        called.append(value)

    monkeypatch.setattr(events, "admit_history_onboarding", admission)
    db, publisher = FakeDb(), FakePublisher()
    await events.emit_accounts_linked(seller, "user", mongo_db=db, amqp_publisher=publisher)
    assert called == ([seller] if admitted else [])
    assert len(publisher.messages) == 1
