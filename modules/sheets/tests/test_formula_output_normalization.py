from __future__ import annotations

from typing import Any

from zeler_sheets.formulas.output_normalization import normalize_response_rows


def test_normalize_response_rows_skips_headers_and_fills_response_blanks() -> None:
    rows: list[list[Any]] = [
        ["ID Publicación", "Logística", "Ventas"],
        ["MLA1", "", 0],
        ["MLA2", None, ""],
    ]

    normalized = normalize_response_rows(rows, header_rows=1)

    assert normalized == [
        ["ID Publicación", "Logística", "Ventas"],
        ["MLA1", "NA", 0],
        ["MLA2", "NA", "NA"],
    ]


def test_normalize_response_rows_does_not_fill_trailing_non_response_rows() -> None:
    rows: list[list[Any]] = [
        ["MLA1", "", "active"],
        ["", "", ""],
        [None, "", None],
    ]

    normalized = normalize_response_rows(rows)

    assert normalized == [["MLA1", "NA", "active"]]
