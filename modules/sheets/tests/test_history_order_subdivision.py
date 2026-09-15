from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from zeler_sheets.history_order_subdivision import (
    OrderRangeNode,
    SaturatedOrderHourError,
    subdivide_order_range,
)


def node() -> OrderRangeNode:
    return OrderRangeNode(
        node_id="monthly-chunk",
        root_id="monthly-chunk",
        date_from=datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
        date_to=datetime(2026, 9, 15, 12, 30, tzinfo=UTC),
    )


def test_split_keeps_exact_cutoff_and_parent_link_without_guessing_child_totals() -> None:
    parent = node()
    children = subdivide_order_range(parent, observed_total=10001)
    assert len(children) == 2
    first, second = children
    assert first.date_from == parent.date_from
    assert first.date_to == second.date_from
    assert second.date_to == parent.date_to
    assert first.date_to.minute == first.date_to.second == first.date_to.microsecond == 0
    assert all(
        child.parent_id == parent.node_id and child.root_id == parent.root_id for child in children
    )
    assert all(child.depth == 1 for child in children)
    assert first.node_id != second.node_id
    assert children == subdivide_order_range(parent, observed_total=20000)
    assert "source_total" not in first.model_dump()
    assert OrderRangeNode.model_validate(first.model_dump()) == first


@pytest.mark.parametrize("total", [0, 10000])
def test_within_local_budget_does_not_split_or_certify(total: int) -> None:
    parent = node()
    assert subdivide_order_range(parent, observed_total=total) == (parent,)


def test_saturated_single_provider_hour_is_explicit_not_an_infinite_split() -> None:
    parent = node().model_copy(
        update={
            "date_from": datetime(2026, 9, 15, 12, 30, tzinfo=UTC),
            "date_to": datetime(2026, 9, 15, 12, 45, tzinfo=UTC),
        }
    )
    with pytest.raises(SaturatedOrderHourError, match="local result budget"):
        subdivide_order_range(parent, observed_total=10001)


@pytest.mark.parametrize("minute, expected_hour", [(0, 12), (30, 13)])
def test_provider_query_superset_respects_exclusive_upper_hour(
    minute: int, expected_hour: int
) -> None:
    parent = node().model_copy(
        update={
            "date_from": datetime(2026, 9, 15, 12, 30, tzinfo=UTC),
            "date_to": datetime(2026, 9, 15, 13, minute, tzinfo=UTC),
        }
    )
    lower, upper = parent.provider_hours()
    assert lower == datetime(2026, 9, 15, 12, tzinfo=UTC)
    assert upper == datetime(2026, 9, 15, expected_hour, tzinfo=UTC)


def test_all_saturated_ninety_day_ranges_terminate_with_exact_partition() -> None:
    original = node().model_copy(update={"date_to": node().date_from + timedelta(days=90)})
    pending = [original]
    leaves = []
    while pending:
        current = pending.pop()
        try:
            pending.extend(subdivide_order_range(current, observed_total=10001))
        except SaturatedOrderHourError:
            leaves.append(current)
    ordered = sorted(leaves, key=lambda leaf: leaf.date_from)
    assert len(ordered) == 2161
    assert ordered[0].date_from == original.date_from
    assert ordered[-1].date_to == original.date_to
    assert all(
        first.date_to == second.date_from
        for first, second in zip(ordered, ordered[1:], strict=False)
    )
    assert max(leaf.depth for leaf in leaves) <= 12


def test_equivalent_offset_dates_produce_identical_child_ids() -> None:
    original = node()
    offset = timezone(timedelta(hours=-6))
    normalized = OrderRangeNode.model_validate(
        {
            **original.model_dump(),
            "date_from": original.date_from.astimezone(offset),
            "date_to": original.date_to.astimezone(offset),
        }
    )
    assert subdivide_order_range(original, observed_total=10001) == subdivide_order_range(
        normalized, observed_total=10001
    )


@pytest.mark.parametrize("value", [True, -1, "10"])
def test_invalid_observed_total_is_not_an_empty_source(value: Any) -> None:
    with pytest.raises(ValueError):
        subdivide_order_range(node(), observed_total=value)


@pytest.mark.parametrize("budget", [True, 0, -1, "10000"])
def test_invalid_local_budget_is_rejected(budget: Any) -> None:
    with pytest.raises(ValueError):
        subdivide_order_range(node(), observed_total=10001, local_result_budget=budget)


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": datetime(2026, 9, 1)},
        {"date_to": datetime(2026, 8, 1, tzinfo=UTC)},
        {"date_to": datetime(2027, 1, 1, tzinfo=UTC)},
        {"depth": True},
        {"depth": 13, "parent_id": "parent"},
        {"depth": 1},
        {"node_id": "wrong-root"},
    ],
)
def test_invalid_plan_metadata_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        OrderRangeNode.model_validate({**node().model_dump(), **changes})


def test_external_depth_exhaustion_is_bounded_without_provider_claim() -> None:
    exhausted = node().model_copy(update={"depth": 12, "parent_id": "prior"})
    with pytest.raises(ValueError, match="local depth budget"):
        subdivide_order_range(exhausted, observed_total=10001)
