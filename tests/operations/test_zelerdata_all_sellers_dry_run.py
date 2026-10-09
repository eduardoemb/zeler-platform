from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from infra.operations import zelerdata_all_sellers_dry_run as dry_run

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for row in self._rows:
                yield row

        return gen()


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


class _ReadOnlyCollection:
    """Only ``find`` exists: any write or aggregation raises AttributeError."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def find(self, query: dict[str, Any], projection: Any = None) -> _Cursor:
        return _Cursor([doc for doc in self._docs if _matches(doc, query)])


class _Db:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self._collections = {name: _ReadOnlyCollection(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> _ReadOnlyCollection:
        return self._collections.get(name, _ReadOnlyCollection([]))


def _token(sellers: list[str], **fields: Any) -> dict[str, Any]:
    return {
        "status": "active",
        "seller_scopes": [
            {"seller_id": seller, "nickname": f"secret-{seller}"} for seller in sellers
        ],
        "expires_at": None,
        **fields,
    }


def _db() -> _Db:
    return _Db(
        meli_accounts=[
            {"seller_id": "1", "status": "active"},
            {"seller_id": 2, "status": "refresh_pending"},
            {"seller_id": "3", "status": "paused"},
            {"seller_id": "4", "status": "revoked"},
            {"seller_id": "5", "status": "invalid_grant"},
            {"seller_id": "6", "status": "something-new"},
            {"seller_id": "7", "status": "active"},
            {"seller_id": "8", "status": "active"},
            {"seller_id": "9", "status": "active"},
            {"seller_id": "10", "status": "active"},
            {"seller_id": "not-a-number", "status": "active"},
        ],
        sheets_extension_tokens=[
            _token(["1", "2", "3", "4", "5", "6"]),
            _token(["8"], status="revoked"),
            _token(["9"], expires_at=NOW - timedelta(seconds=1)),
            _token(["10"], deleted_at=NOW),
            _token(["99"]),
        ],
        sheets_formula_recovery_jobs=[
            {"seller_id": "1", "state": "pending"},
            {"seller_id": "3", "state": "running"},
            {"seller_id": "3", "state": "pending"},
            {"seller_id": "3", "state": "completed"},
        ],
    )


@pytest.mark.asyncio
async def test_report_counts_eligible_sellers_and_reasons_without_identities() -> None:
    report = await dry_run.build_report(_db(), now=NOW, environ={})

    assert report["read_only"] is True
    assert report["eligible_sellers"] == 2
    assert report["matches_runtime_rule"] is True
    assert report["linked_sellers"] == 10
    assert report["accounts_with_invalid_seller_id"] == 1
    assert report["excluded_sellers_by_reason"] == {
        "account_invalid_grant": 1,
        "account_other_status": 1,
        "account_paused": 1,
        "account_revoked": 1,
        "extension_token_deleted": 1,
        "extension_token_expired": 1,
        "extension_token_inactive": 1,
        "no_extension_token": 1,
        "token_scope_without_linked_account": 1,
    }
    assert report["active_recovery_jobs"] == {"total": 3, "for_ineligible_sellers": 2}
    text = json.dumps(report)
    assert "secret-" not in text and "something-new" not in text


@pytest.mark.asyncio
async def test_requested_seller_reports_only_a_verdict_and_a_reason() -> None:
    db = _db()

    eligible = await dry_run.build_report(db, now=NOW, seller_id="1", environ={})
    paused = await dry_run.build_report(db, now=NOW, seller_id="3", environ={})
    unknown = await dry_run.build_report(db, now=NOW, seller_id="12345", environ={})

    assert eligible["requested_seller"] == {"eligible": True, "reason": "eligible"}
    assert paused["requested_seller"] == {"eligible": False, "reason": "account_paused"}
    assert unknown["requested_seller"] == {"eligible": False, "reason": "not_linked"}


@pytest.mark.asyncio
async def test_configuration_reports_scope_kind_and_flags_not_values() -> None:
    environ = {
        "ZELERDATA_REFRESH_SELLERS": "82453304",
        "ZELERDATA_FORMULA_RECOVERY_SELLERS": "ALL",
        "ZELERDATA_REFRESH_ENABLED": "true",
        "ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED": "false",
    }

    report = await dry_run.build_report(_db(), now=NOW, environ=environ)

    configuration = report["configuration"]
    assert configuration["refresh_sellers"] == "numeric:1"
    assert configuration["recovery_sellers"] == "all"
    assert configuration["flags"]["ZELERDATA_REFRESH_ENABLED"] is True
    assert configuration["flags"]["ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED"] is False
    assert "82453304" not in json.dumps(report)


def test_main_requires_the_database_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_DB", raising=False)

    assert dry_run.main([]) == 2
    assert "required" in capsys.readouterr().out


def test_main_never_echoes_failure_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://user:secret@127.0.0.1:1/x")
    monkeypatch.setenv("MONGO_DB", "x")

    async def boom(_args: Any) -> Any:
        raise RuntimeError("mongodb://user:secret@host")

    monkeypatch.setattr(dry_run, "_run", boom)

    assert dry_run.main([]) == 1
    out = capsys.readouterr().out
    assert "secret" not in out and "RuntimeError" in out
