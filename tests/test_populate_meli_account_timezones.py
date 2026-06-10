from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any

import pytest


class FakeUpdateResult:
    def __init__(self, *, modified_count: int) -> None:
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self, documents: Iterable[dict[str, Any]] = ()) -> None:
        self.documents = [dict(document) for document in documents]
        self.update_one_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def find(self, _filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [dict(document) for document in self.documents]

    def update_one(self, filter_: dict[str, Any], update: dict[str, Any]) -> FakeUpdateResult:
        self.update_one_calls.append((filter_, update))
        seller_ids = filter_["seller_id"]["$in"]
        set_doc = update["$set"]
        for document in self.documents:
            if document.get("seller_id") in seller_ids:
                before = dict(document)
                document.update(set_doc)
                return FakeUpdateResult(modified_count=1 if before != document else 0)
        return FakeUpdateResult(modified_count=0)


class FakeDatabase:
    def __init__(self, accounts: Iterable[dict[str, Any]]) -> None:
        self.collections = {"meli_accounts": FakeCollection(accounts)}
        self.accessed_collections: list[str] = []

    def __getitem__(self, name: str) -> FakeCollection:
        self.accessed_collections.append(name)
        if name in {"orders", "items", "shipments", "questions"}:
            raise AssertionError(f"canonical collection {name} must not be touched")
        return self.collections[name]


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.closed = False

    def get_default_database(self) -> FakeDatabase:
        return self.database

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def operation_module() -> Any:
    return importlib.import_module("infra.mongo.operations.populate_meli_account_timezones")


def test_cli_write_requires_approved_runtime_confirmation_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    def forbidden_client(_uri: str) -> FakeClient:
        raise AssertionError("MongoClient must not be created without write confirmation")

    monkeypatch.setattr(operation_module, "MongoClient", forbidden_client)
    monkeypatch.setenv("MONGO_URI", "mongodb://example.invalid/zeler")

    with pytest.raises(SystemExit, match="--confirm-approved-runtime is required with --write"):
        operation_module.main(["--write"])


def test_population_write_requires_approved_runtime_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    def forbidden_client(_uri: str) -> FakeClient:
        raise AssertionError("MongoClient must not be created without approved runtime")

    monkeypatch.setattr(operation_module, "MongoClient", forbidden_client)

    with pytest.raises(ValueError, match="approved_runtime is required when dry_run is false"):
        operation_module.populate_meli_account_timezones("mongodb://test/db", dry_run=False)


def test_population_updates_hopemob_without_touching_canonical_collections(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase([{"seller_id": "82453304", "nickname": "Hopemob"}])
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)

    result = operation_module.populate_meli_account_timezones(
        "mongodb://example.invalid/zeler", dry_run=False, approved_runtime=True
    )

    hopemob = database["meli_accounts"].documents[0]
    assert hopemob["site_id"] == "MLM"
    assert hopemob["timezone"] == "America/Tijuana"
    assert result["updated_count"] == 1
    assert result["dry_run"] is False
    assert result["canonical_collections_touched"] == []
    assert "orders" not in database.accessed_collections
    assert "items" not in database.accessed_collections
    assert "shipments" not in database.accessed_collections
    assert "example.invalid" not in repr(result)
    assert fake_client.closed


def test_cli_confirmed_write_updates_hopemob_and_omits_secret_uri(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase([{"seller_id": "82453304", "nickname": "Hopemob"}])
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)
    monkeypatch.setenv("MONGO_URI", "mongodb://example.invalid/zeler")

    operation_module.main(["--write", "--confirm-approved-runtime"])

    hopemob = database["meli_accounts"].documents[0]
    assert hopemob["site_id"] == "MLM"
    assert hopemob["timezone"] == "America/Tijuana"
    captured = capsys.readouterr()
    assert "write_complete" in captured.out
    assert "example.invalid" not in captured.out
    assert "example.invalid" not in captured.err


def test_population_is_idempotent_and_preserves_valid_existing_timezones(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase(
        [
            {
                "seller_id": "82453304",
                "site_id": "MLM",
                "timezone": "America/Tijuana",
            },
            {
                "seller_id": "11111111",
                "site_id": "MLB",
                "timezone": "America/Sao_Paulo",
            },
        ]
    )
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)

    first = operation_module.populate_meli_account_timezones(
        "mongodb://test/db", dry_run=False, approved_runtime=True
    )
    second = operation_module.populate_meli_account_timezones(
        "mongodb://test/db", dry_run=False, approved_runtime=True
    )

    assert first["updated_count"] == 0
    assert second["updated_count"] == 0
    assert database["meli_accounts"].documents[1]["timezone"] == "America/Sao_Paulo"
    assert database["meli_accounts"].update_one_calls == []


def test_population_uses_utc_fallback_warning_for_unmapped_missing_timezones(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase([{"seller_id": 99999999, "site_id": "MLZ"}])
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)

    result = operation_module.populate_meli_account_timezones(
        "mongodb://test/db", dry_run=False, approved_runtime=True
    )

    account = database["meli_accounts"].documents[0]
    assert account["site_id"] == "MLZ"
    assert account["timezone"] == "UTC"
    assert result["updated_count"] == 1
    assert result["warnings"] == [
        {
            "seller_id": "99999999",
            "site_id": "MLZ",
            "timezone": "UTC",
            "fallback": True,
            "reason": "unmapped_site_id",
        }
    ]


def test_dry_run_reports_plan_without_writes_and_cli_omits_secret_uri(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase([{"seller_id": "82453304"}])
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)
    monkeypatch.setenv("MONGO_URI", "mongodb://example.invalid/zeler")

    result = operation_module.populate_meli_account_timezones("mongodb://test/db", dry_run=True)
    operation_module.main(["--dry-run"])

    assert result["planned_count"] == 1
    assert result["updated_count"] == 0
    assert "site_id" not in database["meli_accounts"].documents[0]
    captured = capsys.readouterr()
    assert "dry_run_complete" in captured.out
    assert "example.invalid" not in captured.out
    assert "example.invalid" not in captured.err
