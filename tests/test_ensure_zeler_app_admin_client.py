from __future__ import annotations

import importlib
from typing import Any

import pytest

PILOT_SELLER_ID = 82453304
REQUIRED_SCOPES = [
    "admin:repricer",
    "admin:sheets",
    "admin:publicador",
    "admin:autoreply",
    "admin:fulldock",
]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[Any, dict[str, Any]] = {}
        self.update_one_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def update_one(
        self,
        filter_: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> FakeUpdateResult:
        self.update_one_calls.append((filter_, update, upsert))
        doc_id = filter_["_id"]
        existing = self.documents.get(doc_id, {"_id": doc_id})
        set_doc = update.get("$set", {})
        self.documents[doc_id] = {**existing, **set_doc}
        return FakeUpdateResult(matched_count=1 if doc_id in self.documents else 0)


class FakeUpdateResult:
    def __init__(self, *, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {"module_registry": FakeCollection()}

    def __getitem__(self, name: str) -> FakeCollection:
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
    return importlib.import_module("infra.mongo.operations.ensure_zeler_app_admin_client")


def test_ensure_zeler_app_admin_client_inserts_missing_doc(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)

    result = operation_module.ensure_zeler_app_admin_client("mongodb://test/db")

    assert result == {"client_id": "zeler-app", "status": "updated"}
    zeler_app = database["module_registry"].documents["zeler-app"]
    assert zeler_app["_id"] == "zeler-app"
    assert zeler_app["status"] == "enabled"
    assert zeler_app["allowed_seller_ids"] == [PILOT_SELLER_ID]
    assert zeler_app["allowed_meli_scopes"] == REQUIRED_SCOPES
    assert fake_client.closed


def test_ensure_zeler_app_admin_client_repairs_stale_doc(
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase()
    database["module_registry"].documents["zeler-app"] = {
        "_id": "zeler-app",
        "status": "disabled",
        "allowed_seller_ids": [],
        "allowed_meli_scopes": ["admin:repricer"],
        "schema_version": 1,
    }
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)

    result = operation_module.ensure_zeler_app_admin_client("mongodb://test/db")

    assert result == {"client_id": "zeler-app", "status": "updated"}
    zeler_app = database["module_registry"].documents["zeler-app"]
    assert zeler_app["status"] == "enabled"
    assert zeler_app["allowed_seller_ids"] == [PILOT_SELLER_ID]
    assert zeler_app["allowed_meli_scopes"] == REQUIRED_SCOPES


def test_ensure_zeler_app_admin_client_main_does_not_log_secret_uri(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    operation_module: Any,
) -> None:
    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(operation_module, "MongoClient", lambda _uri: fake_client)
    monkeypatch.setenv("MONGO_URI", "mongodb://user:super-secret-password@mongo/db")

    operation_module.main()

    captured = capsys.readouterr()
    assert "super-secret-password" not in captured.out
    assert "super-secret-password" not in captured.err
    assert "zeler-app" in captured.out
