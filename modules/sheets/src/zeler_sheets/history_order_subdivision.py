"""Pure subdivision plans; callers must persist nodes and acquire real child totals."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zeler_platform_core.models.base import assert_aware_utc_datetime
from zeler_sheets.history_acquisition import HistoryLimitError

MAX_SUBDIVISION_DEPTH = 12


class SaturatedOrderHourError(HistoryLimitError):
    """A provider-hour query exceeds our local budget; no finer filter is assumed."""


class OrderRangeNode(BaseModel):
    """Serializable plan metadata, not a persisted checkpoint or coverage proof."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    node_id: str = Field(min_length=1)
    root_id: str = Field(min_length=1)
    parent_id: str | None = Field(default=None, min_length=1)
    date_from: datetime
    date_to: datetime
    depth: int = Field(default=0, ge=0, le=MAX_SUBDIVISION_DEPTH)

    @field_validator("date_from", "date_to")
    @classmethod
    def normalize_dates(cls, value: datetime) -> datetime:
        return assert_aware_utc_datetime(value)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if not timedelta(0) < self.date_to - self.date_from <= timedelta(days=90):
            raise ValueError("order subdivision requires positive bounds of at most 90 days")
        if (self.depth == 0) != (self.parent_id is None):
            raise ValueError("subdivision depth must correspond to parent linkage")
        if self.depth == 0 and self.node_id != self.root_id:
            raise ValueError("root identity must identify the root node")
        return self

    def provider_hours(self) -> tuple[datetime, datetime]:
        """Inclusive hour filters; consumers still filter exact half-open local bounds."""
        lower = self.date_from.replace(minute=0, second=0, microsecond=0)
        upper = self.date_to.replace(minute=0, second=0, microsecond=0)
        if upper == self.date_to:
            upper -= timedelta(hours=1)
        return lower, upper


def subdivide_order_range(
    node: OrderRangeNode, *, observed_total: int, local_result_budget: int = 10000
) -> tuple[OrderRangeNode, ...]:
    """Return the unchanged leaf or two exact children, without assuming their totals."""
    node = OrderRangeNode.model_validate(node.model_dump())
    if type(observed_total) is not int or observed_total < 0:
        raise ValueError("observed total must be a nonnegative integer")
    if type(local_result_budget) is not int or local_result_budget < 1:
        raise ValueError("local result budget must be a positive integer")
    if observed_total <= local_result_budget:
        return (node,)
    lower, upper = node.provider_hours()
    hours = (upper - lower) // timedelta(hours=1) + 1
    if hours == 1:
        raise SaturatedOrderHourError("single provider hour exceeds local result budget")
    if node.depth == MAX_SUBDIVISION_DEPTH:
        raise HistoryLimitError("order subdivision reached local depth budget")
    midpoint = lower + timedelta(hours=hours // 2)
    children = []
    for start, end in ((node.date_from, midpoint), (midpoint, node.date_to)):
        identity = "\0".join(
            (
                node.node_id,
                start.isoformat(timespec="microseconds"),
                end.isoformat(timespec="microseconds"),
            )
        )
        children.append(
            OrderRangeNode(
                node_id=hashlib.sha256(identity.encode()).hexdigest(),
                root_id=node.root_id,
                parent_id=node.node_id,
                date_from=start,
                date_to=end,
                depth=node.depth + 1,
            )
        )
    return tuple(children)
