from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from infra.operations import devoluciones_classify_legacy_claims as classifier


class Cursor:
    batch: int | None
    timeout: int | None
    index: int

    def __init__(self, rows: list[dict[str, Any]], fail: bool = False) -> None:
        self.rows, self.fail, self.batch, self.timeout = rows, fail, None, None

    def batch_size(self, value: int) -> Cursor:
        self.batch = value
        return self

    def max_time_ms(self, value: int) -> Cursor:
        self.timeout = value
        return self

    def __aiter__(self) -> Cursor:
        self.index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError
        if self.index == len(self.rows):
            raise StopAsyncIteration
        self.index += 1
        return self.rows[self.index - 1]


class Client:
    def __init__(self, cursor: Cursor) -> None:
        self.claims, self.closed = Claims(cursor), False

    def __getitem__(self, _name: str) -> dict[str, Claims]:
        return {"claims": self.claims}

    def close(self) -> None:
        self.closed = True


class Claims:
    def __init__(self, cursor: Cursor) -> None:
        self.cursor = cursor
        self.query: dict[str, Any] | None = None
        self.projection: dict[str, int] | None = None

    def find(self, query: dict[str, Any], projection: dict[str, int]) -> Cursor:
        self.query, self.projection = query, projection
        return self.cursor

    def __getattr__(self, name: str) -> Any:
        if name in {"insert_one", "update_one", "delete_one", "replace_one", "bulk_write"}:
            raise AssertionError(f"mutation called: {name}")
        raise AttributeError(name)


def invoke(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], *args: str) -> Client:
    client = Client(Cursor(rows))
    monkeypatch.setattr(classifier, "AsyncIOMotorClient", lambda *_a, **_kw: client)
    monkeypatch.setenv("MONGO_URI", "mongodb://not-output")
    monkeypatch.setenv("MONGO_DB", "private")
    assert (
        classifier.main(["--seller-id", "seller-private", "--confirm-approved-runtime", *args]) == 0
    )
    return client


def test_cli_missing_seller_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    assert classifier.main([]) == 2
    assert capsys.readouterr() == ("", "MISSING_SELLER\n")


def test_cli_requires_approved_runtime_before_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(classifier, "AsyncIOMotorClient", lambda *_a, **_kw: pytest.fail("client"))
    assert classifier.main(["--seller-id", "seller-private"]) == 2
    assert capsys.readouterr() == ("", "APPROVED_RUNTIME_CONFIRMATION_REQUIRED\n")


@pytest.mark.parametrize(
    "args",
    [
        ("--date-from", "2026-01-01"),
        ("--date-from", "bad", "--date-to", "2026-01-01"),
        ("--date-from", "2026-02-01", "--date-to", "2026-01-01"),
    ],
)
def test_cli_rejects_invalid_date_ranges(
    args: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        classifier.main(["--seller-id", "seller-private", "--confirm-approved-runtime", *args]) == 2
    )
    assert capsys.readouterr() == ("", "INVALID_DATE_RANGE\n")


def test_cli_read_failure_has_no_partial_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = Client(Cursor([], fail=True))
    monkeypatch.setattr(classifier, "AsyncIOMotorClient", lambda *_a, **_kw: client)
    monkeypatch.setenv("MONGO_URI", "private")
    monkeypatch.setenv("MONGO_DB", "private")
    assert classifier.main(["--seller-id", "seller-private", "--confirm-approved-runtime"]) == 1
    assert capsys.readouterr() == ("", "READ_FAILED\n") and client.closed


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({}, ("missing", "missing", "missing")),
        (
            {"type": None, "productive": None, "return_quantity_basis": None},
            ("null", "null", "null"),
        ),
        (
            {"type": 123, "productive": "true", "return_quantity_basis": 42},
            ("unknown", "unknown", "unknown"),
        ),
    ],
)
def test_bounded_normalizers(row: dict[str, Any], expected: tuple[str, str, str]) -> None:
    assert classifier.normalize_row(row, None)[:3] == expected


def _groups(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: list[dict[str, Any]],
    *args: str,
) -> list[dict[str, Any]]:
    invoke(monkeypatch, rows, *args)
    return cast(list[dict[str, Any]], json.loads(capsys.readouterr().out)["groups"])


def test_zero_rows_emits_metadata_and_empty_groups(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = invoke(monkeypatch, [])
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "date_window": None,
        "groups": [],
        "mode": "read_only",
        "schema_version": "v1",
    }
    assert client.closed and (client.claims.cursor.batch, client.claims.cursor.timeout) == (
        200,
        30000,
    )


def test_mixed_claim_types_emit_only_bounded_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        {
            "type": "returns",
            "productive": True,
            "return_quantity_basis": "v2_return_order",
            "item_id": "private",
        },
        {"type": "mediations", "productive": False, "return_quantity_basis": None},
    ]
    client = invoke(monkeypatch, rows)
    first = capsys.readouterr().out
    invoke(monkeypatch, list(reversed(rows)))
    output = json.loads(first)
    assert (
        capsys.readouterr().out == first
        and "seller-private" not in first
        and "private" not in first
    )
    assert set(output) == {"schema_version", "mode", "date_window", "groups"}
    assert [set(group) for group in output["groups"]] == [
        {
            "type",
            "productive",
            "return_quantity_basis",
            "item_id_present",
            "in_requested_date_window",
            "count",
        }
    ] * 2
    assert client.claims.query == {"seller_id": "seller-private"} and client.claims.projection == {
        "_id": 0,
        "type": 1,
        "productive": 1,
        "return_quantity_basis": 1,
        "item_id": 1,
        "date_created": 1,
    }


def test_type_non_string_normalizes_to_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"type": True}, {"type": 123}])
    rendered = json.dumps(groups)
    assert [group["type"] for group in groups] == ["unknown"] and groups[0]["count"] == 2
    assert '"type": true' not in rendered and "123" not in rendered


def test_unknown_type_string_does_not_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"type": "foobar"}])
    assert groups[0]["type"] == "unknown" and "foobar" not in json.dumps(groups)


def test_productive_non_boolean_normalizes_to_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"productive": 1}])
    assert groups[0]["productive"] == "unknown" and '"productive":1' not in json.dumps(groups)


def test_invalid_basis_normalizes_without_leak(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"return_quantity_basis": "v2_return_order_typo"}])
    assert groups[0]["return_quantity_basis"] == "unknown" and "typo" not in json.dumps(groups)


def test_distinct_invalid_values_merge_into_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"type": 123}, {"type": "foobar"}])
    assert groups == [
        {
            "type": "unknown",
            "productive": "missing",
            "return_quantity_basis": "missing",
            "item_id_present": False,
            "in_requested_date_window": None,
            "count": 2,
        }
    ]


def test_all_group_values_belong_to_closed_domains(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(
        monkeypatch,
        capsys,
        [{"type": True, "productive": 1, "return_quantity_basis": "bad"}],
    )
    group = groups[0]
    assert group["type"] in {
        "returns",
        "mediations",
        "fulfillment",
        "cancel_purchase",
        "missing",
        "null",
        "unknown",
    }
    assert group["productive"] in {"true", "false", "missing", "null", "unknown"}
    assert group["return_quantity_basis"] in {
        "v2_return_order",
        "verified_low_cost_no_row",
        "missing",
        "null",
        "unknown",
    }
    assert set(group) == {
        "type",
        "productive",
        "return_quantity_basis",
        "item_id_present",
        "in_requested_date_window",
        "count",
    }
    assert isinstance(group["item_id_present"], bool)
    assert group["in_requested_date_window"] in {True, False, None, "unknown"}
    assert isinstance(group["count"], int) and group["count"] >= 0
    assert "bad" not in json.dumps(groups)


def test_no_window_labels_all_groups_null(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(monkeypatch, capsys, [{"type": "returns"}, {"type": "mediations"}])
    assert [group["in_requested_date_window"] for group in groups] == [None, None]
    assert sum(group["count"] for group in groups) == 2


def test_invalid_date_created_maps_to_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    groups = _groups(
        monkeypatch,
        capsys,
        [{"date_created": "bad"}, {}],
        "--date-from",
        "2026-01-01",
        "--date-to",
        "2026-01-02",
    )
    assert groups[0]["in_requested_date_window"] == "unknown" and groups[0]["count"] == 2


PHASE5_ALLOWLIST = frozenset(
    {
        "modules/sheets/tests/test_formula_handlers_returns_histories_withdrawals.py",
        "tests/operations/test_devoluciones_classify_legacy_claims.py",
        "tests/operations/test_zelerdata_read_model_reconcile.py",
        "tests/test_devoluciones_guarded_regressions.py",
    }
)
_FORBIDDEN_ROLLBACK_NAME = re.compile(r"rollback|restore|restoration|revert", re.I)


def _run_git(argv: list[str], cwd: Path) -> str:
    return subprocess.run(  # noqa: S603 -- fixed Git argv is structural test evidence.
        argv, cwd=cwd, shell=False, check=True, capture_output=True, text=True
    ).stdout.rstrip("\n")


def _prove_phase5_rollback(ref: str, run: Any) -> tuple[str, list[str]]:
    root = Path(__file__).resolve().parents[2]
    assert run(["git", "rev-parse", "--show-toplevel"], root) == str(root)
    sha = run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], root)
    assert len(run(["git", "rev-list", "--parents", "-n", "1", sha], root).split()) == 2
    paths = set(
        run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", f"{sha}^", sha], root
        ).split("\0")
    ) - {""}
    assert paths and "tests/operations/test_devoluciones_classify_legacy_claims.py" in paths
    assert paths <= PHASE5_ALLOWLIST
    for path in (
        "infra/operations/devoluciones_classify_legacy_claims.py",
        "infra/operations/zelerdata_read_model_reconcile.py",
    ):
        tree = ast.parse(run(["git", "cat-file", "blob", f"{sha}:{path}"], root))
        names = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
        names += [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
        names += [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not any(_FORBIDDEN_ROLLBACK_NAME.search(name) for name in names)
    return sha, ["git", "revert", sha]


def test_phase1_has_no_data_restoration_rollback_path() -> None:
    if ref := os.environ.get("PHASE5_WORK_UNIT_COMMIT"):
        sha, rollback = _prove_phase5_rollback(ref, _run_git)
        assert rollback == ["git", "revert", sha]
        return

    sha = "a" * 40
    calls: list[list[str]] = []

    def run(argv: list[str], cwd: Path) -> str:
        assert cwd == Path(__file__).resolve().parents[2]
        calls.append(argv)
        if argv[1:3] == ["rev-parse", "--show-toplevel"]:
            return str(cwd)
        if argv[1:3] == ["rev-parse", "--verify"]:
            return sha
        if argv[1:3] == ["rev-list", "--parents"]:
            return f"{sha} {'b' * 40}"
        if argv[1] == "diff-tree":
            return "tests/operations/test_devoluciones_classify_legacy_claims.py\0"
        return "def read_only(): pass\n"

    assert _prove_phase5_rollback("phase5", run) == (sha, ["git", "revert", sha])
    assert all(call[0] == "git" for call in calls)


def test_r9_s5_rejects_out_of_boundary_paths() -> None:
    with pytest.raises(AssertionError):
        _prove_phase5_rollback(
            "phase5",
            lambda argv, cwd: (
                "README.sh\0"
                if argv[1] == "diff-tree"
                else str(cwd)
                if argv[1:3] == ["rev-parse", "--show-toplevel"]
                else "a" * 40
                if argv[1] == "rev-parse"
                else f"{'a' * 40} {'b' * 40}"
            ),
        )


def test_r9_s5_pins_canonical_repository_root() -> None:
    with pytest.raises(AssertionError):
        _prove_phase5_rollback(
            "phase5",
            lambda argv, _: (
                "/wrong" if argv[1] == "rev-parse" and argv[2] == "--show-toplevel" else ""
            ),
        )


def test_window_is_inclusive_by_utc_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    invoke(
        monkeypatch,
        [{"date_created": "2026-01-02T23:59:59Z"}],
        "--date-from",
        "2026-01-02",
        "--date-to",
        "2026-01-02",
    )
    assert json.loads(capsys.readouterr().out)["groups"][0]["in_requested_date_window"] is True
