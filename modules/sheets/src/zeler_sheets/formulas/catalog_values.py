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


def catalog_only_competitor(snapshot: Mapping[str, Any] | None) -> Any:
    if snapshot is None:
        return "DATA_UNAVAILABLE"
    only = snapshot.get("only_competitor")
    if isinstance(only, bool):
        return only
    # Mercado Libre declared the publication out of competition and its offer
    # listing has no row for it, so the flag does not apply; reacquiring it
    # returns the same answer until the status changes.
    return NA_VALUE if snapshot.get("buybox_status") == "not_listed" else "DATA_UNAVAILABLE"
