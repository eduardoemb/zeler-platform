from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zeler_sheets.pilot_history import (
    ChunkPriority,
    HistoryChunk,
    HistoryPlanner,
    ResourceHistoryPlan,
)

CUTOFF = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)


def test_twelve_month_plan_produces_monthly_chunks() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=12).plan_for("orders")
    assert len(plan.chunks) == 12
    assert plan.chunks[0].start == datetime(2025, 9, 14, tzinfo=UTC)
    assert plan.chunks[-1].end == CUTOFF
    # Chunks tile the window without overlap or gaps.
    for i in range(len(plan.chunks) - 1):
        assert plan.chunks[i].end == plan.chunks[i + 1].start
    assert all(chunk.duration_days <= 90 for chunk in plan.chunks)


def test_plan_preserves_cutoff_day_across_year_boundary() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=3).plan_for("questions")
    assert plan.chunks[0].start == datetime(2026, 6, 14, tzinfo=UTC)
    assert plan.chunks[1].start == datetime(2026, 7, 14, tzinfo=UTC)
    assert plan.chunks[2].start == datetime(2026, 8, 14, tzinfo=UTC)


def test_plan_rejects_non_utc_cutoff() -> None:
    with pytest.raises(ValueError, match="UTC"):
        HistoryPlanner(cutoff=datetime(2026, 9, 14), months=12)


def test_plan_rejects_zero_or_negative_months() -> None:
    with pytest.raises(ValueError, match="positive"):
        HistoryPlanner(cutoff=CUTOFF, months=0)


def test_chunk_ids_are_stable_across_regenerations() -> None:
    plan_a = HistoryPlanner(cutoff=CUTOFF, months=6).plan_for("orders")
    plan_b = HistoryPlanner(cutoff=CUTOFF, months=6).plan_for("orders")
    assert [c.id for c in plan_a.chunks] == [c.id for c in plan_b.chunks]
    assert len(set(c.id for c in plan_a.chunks)) == 6


def test_resource_ids_do_not_collide() -> None:
    orders = HistoryPlanner(cutoff=CUTOFF, months=3).plan_for("orders")
    items = HistoryPlanner(cutoff=CUTOFF, months=3).plan_for("items")
    order_ids = {c.id for c in orders.chunks}
    item_ids = {c.id for c in items.chunks}
    assert order_ids.isdisjoint(item_ids)


def test_priority_flags_oldest_edge_recent_and_middle() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=4).plan_for("orders")
    assert plan.chunks[0].priority == ChunkPriority.OLDEST_EDGE
    assert plan.chunks[-1].priority == ChunkPriority.RECENT
    assert all(c.priority == ChunkPriority.MIDDLE for c in plan.chunks[1:-1])


def test_single_chunk_gets_recent_priority() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=1).plan_for("orders")
    assert len(plan.chunks) == 1
    assert plan.chunks[0].priority == ChunkPriority.RECENT


def test_resume_returns_incomplete_chunks_ordered_by_priority() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=4).plan_for("orders")
    # chunks: [oldest, mid1, mid2, recent]
    completed = {plan.chunks[0].id, plan.chunks[2].id}
    remaining = plan.resume(completed_ids=completed)
    assert len(remaining) == 2
    # Recent first (immediate utility), then oldest edge (retention risk).
    assert remaining[0].id == plan.chunks[3].id
    assert remaining[0].priority == ChunkPriority.RECENT
    assert remaining[1].id == plan.chunks[1].id
    assert remaining[1].priority == ChunkPriority.MIDDLE


def test_resume_with_all_completed_returns_empty() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=3).plan_for("orders")
    remaining = plan.resume(completed_ids={c.id for c in plan.chunks})
    assert remaining == ()


def test_resume_with_none_completed_returns_recent_then_oldest() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=4).plan_for("orders")
    remaining = plan.resume(completed_ids=set())
    assert len(remaining) == 4
    assert remaining[0].priority == ChunkPriority.RECENT
    assert remaining[1].priority == ChunkPriority.OLDEST_EDGE
    assert remaining[2].priority == ChunkPriority.MIDDLE
    assert remaining[3].priority == ChunkPriority.MIDDLE


def test_unknown_completed_ids_are_ignored() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=2).plan_for("orders")
    remaining = plan.resume(completed_ids={"does-not-exist"})
    assert len(remaining) == 2


def test_two_chunks_get_oldest_edge_and_recent() -> None:
    plan = HistoryPlanner(cutoff=CUTOFF, months=2).plan_for("orders")
    assert len(plan.chunks) == 2
    assert plan.chunks[0].priority == ChunkPriority.OLDEST_EDGE
    assert plan.chunks[1].priority == ChunkPriority.RECENT


@pytest.mark.parametrize("field", ["start", "end"])
def test_history_chunk_is_frozen(field: str) -> None:
    chunk = HistoryChunk(
        resource="orders",
        start=CUTOFF - __import__("datetime").timedelta(days=30),
        end=CUTOFF,
        id="abc",
        priority=ChunkPriority.MIDDLE,
    )
    with pytest.raises(AttributeError):
        setattr(chunk, field, CUTOFF)


def test_resource_history_plan_rejects_non_utc_cutoff() -> None:
    with pytest.raises(ValueError, match="UTC"):
        ResourceHistoryPlan(
            resource="orders",
            cutoff=datetime(2026, 9, 14),
            chunks=(),
        )


def test_full_twelve_month_coverage_from_documented_cutoff() -> None:
    # The plan requires an explicit initial cutoff and twelve calendar months.
    plan = HistoryPlanner(cutoff=CUTOFF, months=12).plan_for("orders")
    total_days = sum(c.duration_days for c in plan.chunks)
    assert total_days == 365  # 2025-09-14 to 2026-09-14
