from __future__ import annotations

from collections.abc import Sequence
from typing import Any

NA_VALUE = "NA"


def normalize_response_rows(
    rows: Sequence[Sequence[Any]], *, header_rows: int = 0, na_value: str = NA_VALUE
) -> list[list[Any]]:
    """Normalize tabular formula rows without padding non-response rows.

    Header rows are preserved as-is. Data rows whose first contract column has
    a response value get explicit `NA` for unavailable blank cells, while known
    zero values stay as `0`.
    """
    materialized = [list(row) for row in rows]
    if not materialized:
        return []

    last_response_index = _last_response_index(materialized, header_rows=header_rows)
    if last_response_index is None:
        return materialized[:header_rows]

    normalized: list[list[Any]] = []
    for index, row in enumerate(materialized[: last_response_index + 1]):
        if index < header_rows or not _has_response_value(row[0] if row else None):
            normalized.append(row)
            continue
        normalized.append([row[0], *[_normalize_cell(cell, na_value=na_value) for cell in row[1:]]])
    return normalized


def _last_response_index(rows: Sequence[Sequence[Any]], *, header_rows: int) -> int | None:
    for index in range(len(rows) - 1, max(header_rows - 1, -1), -1):
        row = rows[index]
        if row and _has_response_value(row[0]):
            return index
    return None


def _normalize_cell(value: Any, *, na_value: str) -> Any:
    if value is None:
        return na_value
    if isinstance(value, str) and value == "":
        return na_value
    return value


def _has_response_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True
