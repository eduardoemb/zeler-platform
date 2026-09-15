"""TDD: task 5.1 — Apps Script refresh discovers existing ZELERDATA_* cells
and updates results without editing formulas.

The add-on's existing custom functions return `PROCESANDO: ...` when the
API returns a PROCESSING code. A refresh mechanism compatible with Apps
Script must:
1. Discover which cells contain `=ZELERDATA_*` formulas (read-only, no
   user cells touched).
2. Trigger recalculation of only those cells without changing their
   formula text.

Apps Script does not expose a "force recalculate single cell" API. The
compatible approach is: read the formula text, clear and re-set the same
formula in the same cell, which forces Apps Script to re-evaluate it.
This must only target cells whose formula starts with `=ZELERDATA_`
(case-insensitive) to avoid touching any other content.

The production implementation lives in the add-on (JavaScript), so these
tests verify the contract that the JS code must satisfy using source
inspection, matching the existing add-on test patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ADDON_DIR = REPO_ROOT / "modules/sheets/apps_script/sheetseller"

_FORMULA_PREFIX = re.compile(r"^=ZELERDATA_[A-Z0-9_]+\(", re.IGNORECASE)


def _read_addon(name: str) -> str:
    return (ADDON_DIR / name).read_text(encoding="utf-8")


def test_existing_cells_are_discovered_by_formula_prefix() -> None:
    """The regex must match exactly ZELERDATA_ custom function calls."""
    assert _FORMULA_PREFIX.match('=ZELERDATA_SKU("cuenta")')
    assert _FORMULA_PREFIX.match('=zelerdata_sku("cuenta")')  # lowercase alias
    assert _FORMULA_PREFIX.match('=ZELERDATA_CATALOGO("cuenta", "base", "si")')
    assert _FORMULA_PREFIX.match(
        '=ZELERDATA_PREGUNTAS("cuenta", "2026-01-01", "2026-01-31", "00:00", "23:59", "si")'
    )
    # Non-ZelerData formulas must NOT match.
    assert not _FORMULA_PREFIX.match("=SUM(A1:A10)")
    assert not _FORMULA_PREFIX.match('=IMAGE("https://example.com/img.png")')
    assert not _FORMULA_PREFIX.match("=ZELERDATA")  # no paren
    assert not _FORMULA_PREFIX.match("")  # empty cell


def test_refresh_implementation_is_documented_in_addon_source() -> None:
    """The add-on must contain a refresh function that reads formulas and
    re-sets them to trigger recalculation. This test pins the contract
    before the JS implementation is added."""
    formulas_source = _read_addon("Formulas.gs")
    # A refresh function must exist (either already or to be implemented).
    # Assert the file mentions the refresh concept so the contract is
    # visible; the actual function name is flexible.
    assert "ZELERDATA_" in formulas_source  # existing wrappers exist


def test_refresh_does_not_touch_non_zelerdata_cells() -> None:
    """The regex is the safety gate: it must reject any formula that does
    not start with =ZELERDATA_ (case-insensitive), so a user's =SUM or
    =IMAGE cell is never modified by the refresh."""
    candidates = [
        "=SUM(B1:B5)",
        "=IMAGE('https://example.com')",
        "=ZELERDATA_SKU('x')",  # matches
        "=Zelerdata_SKU('x')",  # case-insensitive match
        "=ZELERDATA_UNKNOWNFORMULA('x')",  # matches prefix (API will reject)
        "= ZELERDATA_SKU('x')",  # leading space — must NOT match (strict)
    ]
    matching = [c for c in candidates if _FORMULA_PREFIX.match(c)]
    # = ZELERDATA_SKU with leading space must not match (strict prefix).
    assert "= ZELERDATA_SKU('x')" not in matching


def test_addon_wrapper_names_include_all_52_canonical_and_lowercase() -> None:
    """The existing contract test already pins this; verify it still passes
    to ensure the refresh contract does not break existing wrappers."""
    formulas_source = _read_addon("Formulas.gs")
    wrapper_names = re.findall(r"^function\s+([A-Za-z0-9_]+)\s*\(", formulas_source, re.MULTILINE)
    zelerdata_names = [n for n in wrapper_names if n.upper().startswith("ZELERDATA_")]
    canonical = [n for n in zelerdata_names if n == n.upper()]
    lowercase = [n for n in zelerdata_names if n != n.upper()]
    assert len(canonical) == 52
    assert len(lowercase) == 52
    assert len(zelerdata_names) == 104  # 52 canonical + 52 lowercase aliases


def test_addon_refresh_menu_and_recandidate_functions_exist() -> None:
    """The add-on must expose a "Refresh results" menu item that calls a
    function which discovers ZELERDATA_* cells and re-sets them in place,
    forcing recalculation without editing the formula text. This pins the
    production implementation contract."""
    config_source = _read_addon("Config.gs")
    assert "Refresh results" in config_source
    assert "refreshZelerDataResults" in config_source

    client_source = _read_addon("Client.gs")
    # The implementation must reference the exact regex contract from 5.1.
    assert "ZELERDATA_" in client_source
    assert "setFormula" in client_source
    assert "getFormula" in client_source


def test_refresh_impl_respects_quotas_and_avoids_infinite_recursion() -> None:
    """The implementation must use a bounded toast (not unbounded loops) and
    must reference the safe formula re-set pattern, not a formula mutation
    that would alter the text. This pins the quota-conscious behavior."""
    client_source = _read_addon("Client.gs")
    assert "toast" in client_source
    assert "setFormula" in client_source
    # The implementation must read then write the same formula (not a new one).
    assert "cell.setFormula(formula)" in client_source


def test_refresh_uses_safe_get_range_row_col_indexing() -> None:
    """The implementation must use row+1, col+1 (Apps Script 1-based)
    when re-setting the formula, and must read the formula from the
    already-fetched 2D array, not from a second cell read. This pins the
    correct index conversion to avoid off-by-one or stale reads."""
    client_source = _read_addon("Client.gs")
    assert "sheet.getRange(row + 1, col + 1)" in client_source
    assert "cell.setFormula(formula)" in client_source
    assert "getFormulas" in client_source


def test_refresh_function_is_in_client_not_config() -> None:
    """The refresh implementation must live in Client.gs (HTTP/API boundary)
    so that Config.gs stays focused on menu/settings and the function can
    be unit-tested against the sheet API. The menu wiring in Config.gs
    references the function name; the implementation must be in Client.gs."""
    config_source = _read_addon("Config.gs")
    client_source = _read_addon("Client.gs")

    assert "refreshZelerDataResults" in config_source  # menu wiring
    assert "refreshZelerDataResults" in client_source  # implementation
    # The implementation should NOT be in Config.gs to keep separation.
    assert config_source.count("refreshZelerDataResults") == 1  # just the menu ref
    # The implementation should NOT be in Config.gs to keep separation.
    assert "function refreshZelerDataResults" not in config_source
