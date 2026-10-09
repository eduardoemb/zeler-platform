"""Catalog winning time computed at read time from acquired competition observations.

Each row of ``sheets_catalog_competition_observations`` is the competition state
Mercado Libre reported at ``observed_at``. A state holds until the publication's
next observation, as the legacy ``catalog_history`` did between changes. The
legacy mapping applies: ``winning`` and ``sharing_first_place`` are winning,
``competing`` is losing, no stock or any other state is not competing. Time with
stock is winning plus losing time.

A range is covered only when an observation at or before its start establishes
the starting state. The uncovered prefix of a range is never inferred: such a
publication reports where its observed history begins instead of a partial sum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from zeler_sheets.formulas.output_normalization import NA_VALUE

CATALOG_COMPETITION_OBSERVATIONS_COLLECTION = "sheets_catalog_competition_observations"
CATALOG_WINNING_STATUSES = ("winning", "sharing_first_place")
CATALOG_LOSING_STATUSES = ("competing",)
NO_CATALOG_HISTORY_MESSAGE = "Sin histórico de catálogo"
_CENT = Decimal("0.01")
_MILLISECONDS_PER_HOUR = Decimal(3_600_000)


@dataclass(frozen=True, slots=True)
class CatalogWinningTime:
    winning: timedelta
    with_stock: timedelta
    covered: bool
    history_from: datetime

    @property
    def percent(self) -> Decimal | None:
        if self.with_stock <= timedelta(0):
            return None
        ratio = Decimal(_milliseconds(self.winning)) / Decimal(_milliseconds(self.with_stock))
        return (ratio * 100).quantize(_CENT, rounding=ROUND_HALF_UP)


async def find_catalog_winning_times(
    db: Any,
    *,
    seller_id: str,
    date_from: datetime,
    date_to: datetime,
    item_ids: Sequence[str] | None = None,
) -> dict[str, CatalogWinningTime]:
    """Return winning time per publication observed at or before ``date_to``.

    Two bounded reads on ``(seller_id, item_id, observed_at)``: the last state at
    or before the start (one index entry per publication) and the observations
    inside the range, summed by the server so only one row per publication is
    returned.
    """
    if date_to < date_from:
        date_to = date_from
    collection = db[CATALOG_COMPETITION_OBSERVATIONS_COLLECTION]
    scope: dict[str, Any] = {"seller_id": seller_id}
    if item_ids is not None:
        scope["item_id"] = {"$in": list(dict.fromkeys(item_ids))}
    starting = {
        row["_id"]: row
        for row in await collection.aggregate(
            _starting_state_pipeline(scope, date_from=date_from)
        ).to_list(None)
    }
    ranged = {
        row["_id"]: row
        for row in await collection.aggregate(
            _range_pipeline(scope, date_from=date_from, date_to=date_to)
        ).to_list(None)
    }
    times: dict[str, CatalogWinningTime] = {}
    for item_id in sorted(set(starting) | set(ranged)):
        start_row, range_row = starting.get(item_id), ranged.get(item_id)
        winning = timedelta(milliseconds=int(range_row["winning_ms"])) if range_row else timedelta()
        with_stock = (
            timedelta(milliseconds=int(range_row["with_stock_ms"])) if range_row else timedelta()
        )
        if start_row is not None:
            prefix = _as_utc(range_row["first_observed_at"]) if range_row else date_to
            held = prefix - date_from
            state = _state(start_row.get("status"), start_row.get("available_quantity"))
            if state == "winning":
                winning += held
            if state in {"winning", "losing"}:
                with_stock += held
        times[item_id] = CatalogWinningTime(
            winning=winning,
            with_stock=with_stock,
            covered=start_row is not None,
            history_from=_as_utc(
                (start_row or {}).get("observed_at") or (range_row or {})["first_observed_at"]
            ),
        )
    return times


def catalog_winning_time_cells(value: CatalogWinningTime | None, *, timezone: tzinfo) -> list[Any]:
    """Winning hours, hours with stock and winning percent, or why they are unknown."""
    gap = _history_gap_message(value, timezone=timezone)
    if gap is not None or value is None:
        return [gap or NO_CATALOG_HISTORY_MESSAGE] * 3
    return [
        _hours_cell(value.winning),
        _hours_cell(value.with_stock),
        catalog_winning_percent_cell(value, timezone=timezone),
    ]


def catalog_winning_percent_cell(value: CatalogWinningTime | None, *, timezone: tzinfo) -> Any:
    gap = _history_gap_message(value, timezone=timezone)
    if gap is not None or value is None:
        return gap or NO_CATALOG_HISTORY_MESSAGE
    percent = value.percent
    return NA_VALUE if percent is None else _number(percent)


def _history_gap_message(value: CatalogWinningTime | None, *, timezone: tzinfo) -> str | None:
    if value is None:
        return NO_CATALOG_HISTORY_MESSAGE
    if value.covered:
        return None
    return f"Sin histórico antes de {value.history_from.astimezone(timezone):%Y-%m-%d %H:%M}"


def _starting_state_pipeline(scope: dict[str, Any], *, date_from: datetime) -> list[Any]:
    # A full reverse walk of the index with $first lets Mongo read one entry per
    # publication (DISTINCT_SCAN) instead of every older observation.
    return [
        {"$match": {**scope, "observed_at": {"$lte": date_from}}},
        {"$sort": {"seller_id": -1, "item_id": -1, "observed_at": -1}},
        {
            "$group": {
                "_id": "$item_id",
                "observed_at": {"$first": "$observed_at"},
                "status": {"$first": "$status"},
                "available_quantity": {"$first": "$available_quantity"},
            }
        },
    ]


def _range_pipeline(scope: dict[str, Any], *, date_from: datetime, date_to: datetime) -> list[Any]:
    held = {"$subtract": ["$held_until", "$observed_at"]}
    in_stock = {"$gt": ["$available_quantity", 0]}
    return [
        {"$match": {**scope, "observed_at": {"$gt": date_from, "$lt": date_to}}},
        {"$sort": {"seller_id": 1, "item_id": 1, "observed_at": 1}},
        {
            "$setWindowFields": {
                "partitionBy": "$item_id",
                "sortBy": {"observed_at": 1},
                "output": {
                    "held_until": {
                        "$shift": {"output": "$observed_at", "by": 1, "default": date_to}
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$item_id",
                "first_observed_at": {"$min": "$observed_at"},
                "winning_ms": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    in_stock,
                                    {"$in": ["$status", list(CATALOG_WINNING_STATUSES)]},
                                ]
                            },
                            held,
                            0,
                        ]
                    }
                },
                "with_stock_ms": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    in_stock,
                                    {
                                        "$in": [
                                            "$status",
                                            [*CATALOG_WINNING_STATUSES, *CATALOG_LOSING_STATUSES],
                                        ]
                                    },
                                ]
                            },
                            held,
                            0,
                        ]
                    }
                },
            }
        },
    ]


def _state(status: Any, available_quantity: Any) -> str:
    if (
        not isinstance(available_quantity, int)
        or isinstance(available_quantity, bool)
        or available_quantity <= 0
    ):
        return "no_stock"
    if status in CATALOG_WINNING_STATUSES:
        return "winning"
    if status in CATALOG_LOSING_STATUSES:
        return "losing"
    return "not_competing"


def _hours_cell(value: timedelta) -> int | float:
    hours = Decimal(_milliseconds(value)) / _MILLISECONDS_PER_HOUR
    return _number(hours.quantize(_CENT, rounding=ROUND_HALF_UP))


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _milliseconds(value: timedelta) -> int:
    return value // timedelta(milliseconds=1)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
