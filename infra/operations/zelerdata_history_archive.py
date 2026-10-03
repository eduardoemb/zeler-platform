"""Offline positive selection for the22 historical backup namespaces.

Stdlib-only, host Python3.10 compatible. No DB/cloud/provider access or writes.
Selection is NOT evidence of BSON integrity, restore success or consistency.
"""

from __future__ import annotations

import json
import re
import tarfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

WHITELIST = (
    "orders",
    "questions",
    "shipments",
    "claims",
    "messages",
    "items",
    "sheets_item_formula_rows",
    "sheets_item_sku_index",
    "sheets_history_backfill_plans",
    "sheets_history_acquisitions",
    "sheets_history_receipts",
    "sheets_history_order_ranges",
    "sheets_history_pending_records",
    "sheets_formula_recovery_jobs",
    "sheets_formula_recovery_admission",
    "sheets_devoluciones_operations",
    "sheets_devoluciones_runs",
    "sheets_devoluciones_run_windows",
    "sheets_devoluciones_certificates",
    "sheets_read_model_freshness",
    "sheets_full_operations",
    "sheets_full_withdrawals",
)
SOURCE_DB = "zeler_platform_prod"


class SelectionError(RuntimeError):
    """Fixed safe codes only; never expose file contents or provider data."""


def expected_member_names(present: Sequence[str]) -> frozenset[str]:
    """Exact positive member inventory from caller's independently proven presence."""
    if not present or len(set(present)) != len(present) or not set(present) <= set(WHITELIST):
        raise SelectionError("invalid_presence")
    return frozenset(
        {"cut-snapshot.json"}
        | {
            f"dump/{SOURCE_DB}/{name}.{suffix}"
            for name in present
            for suffix in ("bson", "metadata.json")
        }
    )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SelectionError("invalid_prelude")
        result[key] = value
    return result


def _validate_prelude(path: Path) -> None:
    # One bounded, tool-generated auxiliary file, never an uploaded member.
    with path.open("rb") as stream:
        content = stream.read(4097)
    if not content or len(content) > 4096:
        raise SelectionError("invalid_prelude")
    try:
        data = json.loads(content, object_pairs_hook=_unique_json_object)
    except (ValueError, UnicodeError):
        raise SelectionError("invalid_prelude") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"ServerVersion", "ToolVersion"}
        or data["ToolVersion"] != "100.16.0"
        or not isinstance(data["ServerVersion"], str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", data["ServerVersion"])
    ):
        raise SelectionError("invalid_prelude")


def _regular_unlinked_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file() and path.stat().st_nlink == 1


def select_backup_files(base_dir: Path, present: Sequence[str]) -> tuple[Path, ...]:
    """Read-only selection; reject extras/incompleteness, optionally exclude prelude.

    Caller must separately prove quiescence and validate/hash contents. Files can
    change after selection; this function does not certify an archive or restore.
    """
    expected = expected_member_names(present)
    dump = base_dir / "dump"
    source = dump / SOURCE_DB
    if any(path.is_symlink() or not path.is_dir() for path in (base_dir, dump, source)):
        raise SelectionError("invalid_dump_root")
    prelude_name = f"dump/{SOURCE_DB}/prelude.json"
    selected: dict[str, Path] = {}
    for path in sorted(dump.rglob("*")):
        name = path.relative_to(base_dir).as_posix()
        if not path.is_symlink() and path.is_dir() and path == source:
            continue
        if not _regular_unlinked_file(path):
            raise SelectionError("unexpected_dump_member")
        if name == prelude_name:
            _validate_prelude(path)
            continue
        if name not in expected:
            raise SelectionError("unexpected_dump_member")
        selected[name] = path
    snapshot = base_dir / "cut-snapshot.json"
    if not _regular_unlinked_file(snapshot):
        raise SelectionError("incomplete_selection")
    selected["cut-snapshot.json"] = snapshot
    if set(selected) != expected:
        raise SelectionError("incomplete_selection")
    return tuple(selected[name] for name in sorted(expected))


def validate_archive_members(archive: tarfile.TarFile, present: Sequence[str]) -> None:
    """Check exact member inventory/types only, NOT contents/hash/consistency."""
    expected = expected_member_names(present)
    members = archive.getmembers()
    names = [member.name for member in members]
    if (
        len(names) != len(set(names))
        or set(names) != expected
        or any(
            not member.isfile() or member.issym() or member.islnk() or member.size < 0
            for member in members
        )
    ):
        raise SelectionError("archive_members")
