"""Synthetic local files only; no production data, Mongo, cloud or restore."""

import io
import json
import tarfile
from pathlib import Path

import pytest
from infra.operations import zelerdata_history_archive as mod

PRESENT = tuple(
    c
    for c in mod.WHITELIST
    if c
    not in {
        "sheets_history_pending_records",
        "sheets_full_operations",
    }
)


@pytest.fixture
def dump(tmp_path: Path) -> Path:
    target = tmp_path / "dump" / mod.SOURCE_DB
    target.mkdir(parents=True)
    for name in PRESENT:
        (target / f"{name}.bson").write_bytes(b"")
        (target / f"{name}.metadata.json").write_text('{"options":{},"indexes":[]}')
    (tmp_path / "cut-snapshot.json").write_text('{"synthetic":true}')
    return tmp_path


def test_baseline_without_prelude_selects_exact41_members(dump: Path) -> None:
    selected = mod.select_backup_files(dump, PRESENT)
    assert len(selected) == 41
    assert len(set(selected)) == 41


def test_authentic_shaped_valid_tool_prelude_is_excluded_not_rejected(dump: Path) -> None:
    prelude = dump / "dump" / mod.SOURCE_DB / "prelude.json"
    prelude.write_text(json.dumps({"ServerVersion": "7.0.12", "ToolVersion": "100.16.0"}))
    selected = mod.select_backup_files(dump, PRESENT)
    assert len(selected) == 41
    assert prelude not in selected


@pytest.mark.parametrize(
    "filename",
    [
        "dump/zeler_platform_prod/orders.bson",
        "dump/zeler_platform_prod/orders.metadata.json",
        "cut-snapshot.json",
    ],
)
def test_missing_required_file_is_never_skipped(dump: Path, filename: str) -> None:
    (dump / filename).unlink()
    with pytest.raises(mod.SelectionError, match="incomplete_selection"):
        mod.select_backup_files(dump, PRESENT)


@pytest.mark.parametrize("present", [(), ("orders", "orders"), ("unknown",)])
def test_invalid_presence_is_rejected(dump: Path, present: tuple[str, ...]) -> None:
    with pytest.raises(mod.SelectionError, match="invalid_presence"):
        mod.select_backup_files(dump, present)


@pytest.mark.parametrize(
    "filename",
    [
        "dump/zeler_platform_prod/extra.json",
        "dump/zeler_platform_prod/sheets_full_operations.bson",
        "dump/prelude.json",
        "dump/zeler_platform_prod/nested/prelude.json",
    ],
)
def test_extra_or_mislocated_prelude_is_rejected(dump: Path, filename: str) -> None:
    path = dump / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    with pytest.raises(mod.SelectionError, match="unexpected_dump_member"):
        mod.select_backup_files(dump, PRESENT)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not-json",
        b"[]",
        b"{}",
        b"x" * 4097,
        b'{"ServerVersion":"7.0.12","ToolVersion":"100.15.0"}',
        b'{"ServerVersion":"7.0.12-suffix","ToolVersion":"100.16.0"}',
        b'{"ServerVersion":7,"ToolVersion":"100.16.0"}',
        b'{"ServerVersion":"7.0.12","ToolVersion":"100.16.0","extra":true}',
        b'{"ServerVersion":"7.0.12","ToolVersion":"100.16.0","ToolVersion":"100.16.0"}',
    ],
)
def test_tampered_or_unsupported_prelude_is_rejected(dump: Path, payload: bytes) -> None:
    (dump / "dump" / mod.SOURCE_DB / "prelude.json").write_bytes(payload)
    with pytest.raises(mod.SelectionError, match="invalid_prelude"):
        mod.select_backup_files(dump, PRESENT)


@pytest.mark.parametrize(
    "filename",
    [
        "dump/zeler_platform_prod/orders.bson",
        "dump/zeler_platform_prod/prelude.json",
        "cut-snapshot.json",
    ],
)
def test_filesystem_symlink_is_rejected(dump: Path, tmp_path: Path, filename: str) -> None:
    target = tmp_path / "synthetic-target"
    target.write_text("{}")
    path = dump / filename
    path.unlink(missing_ok=True)
    path.symlink_to(target)
    with pytest.raises(mod.SelectionError):
        mod.select_backup_files(dump, PRESENT)


def test_filesystem_hardlink_is_rejected(dump: Path) -> None:
    import os

    source = dump / "dump" / mod.SOURCE_DB / "orders.bson"
    os.link(source, dump / "synthetic-hardlink")
    with pytest.raises(mod.SelectionError, match="unexpected_dump_member"):
        mod.select_backup_files(dump, PRESENT)


def test_symlink_dump_root_is_rejected(dump: Path) -> None:
    actual = dump / "dump"
    moved = dump / "moved"
    actual.rename(moved)
    actual.symlink_to(moved, target_is_directory=True)
    with pytest.raises(mod.SelectionError, match="invalid_dump_root"):
        mod.select_backup_files(dump, PRESENT)


def archive_infos(names: list[str]) -> tarfile.TarFile:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name in names:
            archive.addfile(tarfile.TarInfo(name))
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode="r")


def test_archive_contains_exact41_members_not_prelude(dump: Path) -> None:
    selected = mod.select_backup_files(dump, PRESENT)
    with archive_infos([path.relative_to(dump).as_posix() for path in selected]) as archive:
        mod.validate_archive_members(archive, PRESENT)


@pytest.mark.parametrize(
    "extra",
    [
        "dump/zeler_platform_prod/prelude.json",
        "../orders.bson",
        "/orders.bson",
        "dump/zeler_platform_prod/../../orders.bson",
        "dump//zeler_platform_prod/orders.bson",
        "cut-snapshot.json",
    ],
)
def test_archive_extras_traversal_duplicates_are_rejected(extra: str) -> None:
    names = sorted(mod.expected_member_names(PRESENT)) + [extra]
    with (
        archive_infos(names) as archive,
        pytest.raises(mod.SelectionError, match="archive_members"),
    ):
        mod.validate_archive_members(archive, PRESENT)


def test_archive_missing_member_is_rejected() -> None:
    with (
        archive_infos(sorted(mod.expected_member_names(PRESENT))[1:]) as archive,
        pytest.raises(mod.SelectionError, match="archive_members"),
    ):
        mod.validate_archive_members(archive, PRESENT)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory"])
def test_archive_nonregular_member_is_rejected(kind: str) -> None:
    import tarfile

    with archive_infos(sorted(mod.expected_member_names(PRESENT))) as archive:
        member = archive.getmembers()[0]
        member.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "directory": tarfile.DIRTYPE,
        }[kind]
        with pytest.raises(mod.SelectionError, match="archive_members"):
            mod.validate_archive_members(archive, PRESENT)
