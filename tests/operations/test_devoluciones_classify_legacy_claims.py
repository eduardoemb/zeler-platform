from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from infra.operations import devoluciones_classify_legacy_claims as classifier


class Cursor:
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
        self.cursor, self.query, self.projection = cursor, None, None

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


def test_cli_requires_approved_runtime_before_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classifier, "AsyncIOMotorClient", lambda *_a, **_kw: pytest.fail("client"))
    assert classifier.main(["--seller-id", "seller-private"]) == 2


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


def test_invalid_date_created_maps_to_unknown() -> None:
    window = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    assert classifier.normalize_row({"date_created": "bad"}, window)[4] == "unknown"


def test_zero_rows_emits_metadata_and_cursor_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = invoke(monkeypatch, [])
    assert json.loads(capsys.readouterr().out)["groups"] == []
    assert client.closed and (client.claims.cursor.batch, client.claims.cursor.timeout) == (
        200,
        30000,
    )


def test_bounded_read_only_output_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        {
            "type": "returns",
            "productive": True,
            "return_quantity_basis": "v2_return_order",
            "item_id": "private",
        },
        {"type": "foobar", "productive": 1, "return_quantity_basis": object()},
    ]
    client = invoke(monkeypatch, rows)
    first = capsys.readouterr().out
    invoke(monkeypatch, list(reversed(rows)))
    output = json.loads(first)
    assert (
        capsys.readouterr().out == first and "seller-private" not in first and "foobar" not in first
    )
    assert set(output) == {"schema_version", "mode", "date_window", "groups"}
    assert client.claims.query == {"seller_id": "seller-private"} and client.claims.projection == {
        "_id": 0,
        "type": 1,
        "productive": 1,
        "return_quantity_basis": 1,
        "item_id": 1,
        "date_created": 1,
    }


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
