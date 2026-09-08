"""Source-faithful values shared by the two catalog competition formulas."""

from collections.abc import Mapping
from typing import Any

from zeler_sheets.formulas.output_normalization import NA_VALUE


def catalog_shared_users(snapshot: Mapping[str, Any] | None) -> Any:
    if snapshot is None or "competitors_sharing_first_place" not in snapshot:
        return "DATA_UNAVAILABLE"
    count = snapshot["competitors_sharing_first_place"]
    if count is None:
        return NA_VALUE
    return (
        int(count)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0
        else "DATA_UNAVAILABLE"
    )
