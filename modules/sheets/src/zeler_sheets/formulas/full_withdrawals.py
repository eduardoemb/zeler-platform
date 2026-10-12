"""Pair notified Full withdrawal operations into one row per reservation.

Mercado Libre exposes no withdrawal identifier, so each delivery, cancelation,
removal (abandoned withdrawal) or discard is matched to a reservation of the
same inventory that was created before it and still has open units:

* the oldest open reservation whose open units equal the closing quantity;
* otherwise the open reservations in creation order (FIFO), splitting units.

A closing that needs more units than the observed open reservations hold
belongs, at least in part, to a reservation the platform never saw (created
before its first notification); it is reported as unmatched instead of being
forced onto a later reservation. With two or more open reservations of one
inventory the match is a guess and the touched rows are flagged approximate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from zeler_sheets.full_operations import (
    WITHDRAWAL_CANCELATION,
    WITHDRAWAL_DELIVERY,
    WITHDRAWAL_DISCARDED,
    WITHDRAWAL_REMOVAL,
    WITHDRAWAL_RESERVATION,
    WITHDRAWAL_TYPES,
)

STATUS_RESERVED = "Reservado"
STATUS_DELIVERED = "Entregado"
CLOSED_STATUS = {
    WITHDRAWAL_CANCELATION: "Cancelado",
    WITHDRAWAL_DISCARDED: "Descartado",
    WITHDRAWAL_REMOVAL: "Abandonado",
}


@dataclass
class FullWithdrawal:
    operation_id: str
    inventory_id: str
    created_at: datetime
    requested: int | None
    delivered: int = 0
    canceled: int = 0
    removed: int = 0
    discarded: int = 0
    delivered_at: datetime | None = None
    closed_by: str | None = None
    approximate: bool = False

    @property
    def remaining(self) -> int:
        if self.requested is None:
            return 0
        return self.requested - self.delivered - self.canceled - self.removed - self.discarded

    @property
    def status(self) -> str:
        if self.requested is None or self.remaining > 0:
            return STATUS_RESERVED
        if self.delivered > 0:
            return STATUS_DELIVERED
        return CLOSED_STATUS.get(self.closed_by or "", STATUS_RESERVED)

    def close(self, kind: str, units: int, at: datetime) -> None:
        if kind == WITHDRAWAL_DELIVERY:
            self.delivered += units
            self.delivered_at = at if self.delivered_at is None else max(self.delivered_at, at)
        elif kind == WITHDRAWAL_CANCELATION:
            self.canceled += units
        elif kind == WITHDRAWAL_REMOVAL:
            self.removed += units
        else:
            self.discarded += units
        self.closed_by = kind


@dataclass(frozen=True)
class UnmatchedOperation:
    operation_id: str
    inventory_id: str
    kind: str
    created_at: datetime


def pair_full_withdrawals(
    operations: Iterable[Mapping[str, Any]],
) -> tuple[list[FullWithdrawal], list[UnmatchedOperation]]:
    """Return the reservations, in creation order, and the unmatched closings."""
    by_inventory: dict[str, list[tuple[datetime, int, str, str, int | None]]] = defaultdict(list)
    for operation in operations:
        kind = str(operation.get("type") or "").upper()
        inventory_id = str(operation.get("inventory_id") or "").strip()
        created = _datetime(operation.get("date_created"))
        operation_id = str(operation.get("operation_id") or "").strip()
        if kind not in WITHDRAWAL_TYPES or not inventory_id or not operation_id or not created:
            continue
        # At one instant a reservation precedes the closings that consume it.
        rank = 0 if kind == WITHDRAWAL_RESERVATION else 1
        by_inventory[inventory_id].append(
            (created, rank, operation_id, kind, withdrawal_units(operation))
        )
    withdrawals: list[FullWithdrawal] = []
    unmatched: list[UnmatchedOperation] = []
    for inventory_id, rows in by_inventory.items():
        open_rows: list[FullWithdrawal] = []
        for created, _, operation_id, kind, units in sorted(rows, key=_operation_order):
            if kind == WITHDRAWAL_RESERVATION:
                withdrawal = FullWithdrawal(operation_id, inventory_id, created, units)
                withdrawals.append(withdrawal)
                open_rows.append(withdrawal)
                continue
            candidates = [row for row in open_rows if row.remaining > 0]
            if units is None or units <= 0 or units > sum(row.remaining for row in candidates):
                unmatched.append(UnmatchedOperation(operation_id, inventory_id, kind, created))
                continue
            exact = next((row for row in candidates if row.remaining == units), None)
            left = units
            for row in [exact] if exact is not None else candidates:
                taken = min(left, row.remaining)
                row.close(kind, taken, created)
                row.approximate = row.approximate or len(candidates) > 1
                left -= taken
                if left == 0:
                    break
    withdrawals.sort(key=lambda row: (row.created_at, _numeric_order(row.operation_id)))
    return withdrawals, unmatched


def withdrawal_units(operation: Mapping[str, Any]) -> int | None:
    """Units that enter or leave the ``withdrawal`` state in one operation."""
    detail = operation.get("detail")
    if not isinstance(detail, Mapping):
        return None
    entries = detail.get("not_available_detail")
    quantities = [
        quantity
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, Mapping)
        and str(entry.get("status") or "").strip().casefold() == "withdrawal"
        and (quantity := _integer(entry.get("quantity"))) is not None
    ]
    if quantities:
        return abs(sum(quantities))
    fallback = _integer(detail.get("not_available_quantity"))
    return abs(fallback) if fallback else None


def _operation_order(row: tuple[datetime, int, str, str, int | None]) -> tuple[Any, ...]:
    created, rank, operation_id, _, _ = row
    return (created, rank, _numeric_order(operation_id))


def _numeric_order(operation_id: str) -> tuple[int, str]:
    return (int(operation_id), "") if operation_id.isdigit() else (0, operation_id)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
