from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo.readiness import build_mongo_readiness_report, render_mongo_markdown
from infra.rabbitmq.readiness import build_rabbitmq_readiness_report, render_rabbitmq_markdown

ROOT = Path(__file__).resolve().parents[1]


def test_rabbitmq_readiness_offline_default_is_non_mutating_and_safe_language() -> None:
    report = build_rabbitmq_readiness_report(
        definitions_path=ROOT / "infra" / "rabbitmq" / "definitions.json",
        management_export_path=None,
    )

    assert report.mode == "offline"
    assert report.safe_to_execute is True
    assert report.read_only is True
    assert report.management_export_checked is False
    assert report.mutations_attempted == 0
    assert report.summary["missing_exchanges"] == 0
    assert report.summary["missing_queues"] == 0
    assert report.summary["missing_bindings"] == 0

    markdown = render_rabbitmq_markdown(report)
    assert "safe_to_execute: true" in markdown
    assert "read_only: true" in markdown
    assert "No RabbitMQ mutations are attempted" in markdown


def test_rabbitmq_readiness_detects_missing_binding_from_management_export(tmp_path: Path) -> None:
    definitions = json.loads((ROOT / "infra" / "rabbitmq" / "definitions.json").read_text())
    export = {
        "exchanges": definitions["exchanges"],
        "queues": definitions["queues"],
        "bindings": definitions["bindings"][:-1],
    }
    export_path = tmp_path / "management-export.json"
    export_path.write_text(json.dumps(export), encoding="utf-8")

    report = build_rabbitmq_readiness_report(
        definitions_path=ROOT / "infra" / "rabbitmq" / "definitions.json",
        management_export_path=export_path,
    )

    assert report.mode == "offline-with-export"
    assert report.management_export_checked is True
    assert report.safe_to_execute is True
    assert report.read_only is True
    assert report.summary["missing_bindings"] == 1
    assert report.findings[0].severity == "fail"
    assert report.findings[0].resource_type == "binding"
    assert "messages.*" in report.findings[0].resource_name


def test_mongo_readiness_offline_default_validates_schema_and_index_files() -> None:
    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        mongo_uri=None,
    )

    assert report.mode == "offline"
    assert report.safe_to_execute is True
    assert report.read_only is True
    assert report.live_target_checked is False
    assert report.mutations_attempted == 0
    assert report.summary["schema_files"] >= 17
    assert report.summary["index_files"] >= 17
    assert report.summary["schema_file_errors"] == 0
    assert report.summary["index_file_errors"] == 0

    markdown = render_mongo_markdown(report)
    assert "safe_to_execute: true" in markdown
    assert "read_only: true" in markdown
    assert "No collMod, createIndex, drop, or import operations are attempted" in markdown


class FakeIndexCursor:
    def __init__(self, indexes: list[dict[str, Any]]) -> None:
        self._indexes = indexes

    def __iter__(self) -> Any:
        return iter(self._indexes)


class FakeCollection:
    def __init__(self, indexes: list[dict[str, Any]]) -> None:
        self._indexes = indexes
        self.create_index_calls = 0

    def list_indexes(self) -> FakeIndexCursor:
        return FakeIndexCursor(self._indexes)

    def create_index(self, *_args: Any, **_kwargs: Any) -> None:
        self.create_index_calls += 1
        raise AssertionError("readiness checks must not create indexes")


class FakeMongoDatabase:
    def __init__(self) -> None:
        self.command_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.collections = {
            "users": FakeCollection([{"key": {"email": 1}, "unique": True, "name": "email_1"}])
        }

    def list_collection_names(self) -> list[str]:
        return ["users"]

    def command(self, command_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.command_calls.append((command_name, args, kwargs))
        if command_name == "listCollections":
            return {
                "cursor": {
                    "firstBatch": [
                        {
                            "name": "users",
                            "options": {"validator": {"$jsonSchema": {"bsonType": "object"}}},
                        }
                    ]
                }
            }
        raise AssertionError(f"unexpected command: {command_name}")

    def __getitem__(self, collection_name: str) -> FakeCollection:
        return self.collections[collection_name]


class FakeMongoClient:
    def __init__(self, database: FakeMongoDatabase) -> None:
        self.database = database
        self.closed = False

    def get_default_database(self) -> FakeMongoDatabase:
        return self.database

    def close(self) -> None:
        self.closed = True


def test_mongo_readiness_live_check_is_read_only_and_reports_missing_collections(
    monkeypatch: Any,
) -> None:
    database = FakeMongoDatabase()
    client = FakeMongoClient(database)

    monkeypatch.setattr("infra.mongo.readiness.MongoClient", lambda _uri: client)

    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        mongo_uri="mongodb://example.test/zeler_platform",
    )

    assert report.mode == "read-only-live-check"
    assert report.safe_to_execute is True
    assert report.read_only is True
    assert report.live_target_checked is True
    assert report.mutations_attempted == 0
    assert report.summary["missing_collections"] >= 1
    assert {call[0] for call in database.command_calls} == {"listCollections"}
    assert database.collections["users"].create_index_calls == 0
    assert client.closed is True


def test_live_readiness_runbook_documents_sandbox_sequence_and_env_vars() -> None:
    runbook = (ROOT / "docs" / "live-readiness-validation.md").read_text(encoding="utf-8")

    assert "Non-destructive readiness validation" in runbook
    assert "safe_to_execute" in runbook
    assert "read_only" in runbook
    assert "RabbitMQ_MANAGEMENT_EXPORT" in runbook
    assert "MONGO_URI" in runbook
    assert "python -m infra.rabbitmq.readiness" in runbook
    assert "python -m infra.mongo.readiness" in runbook
    assert "Do not run `infra/mongo/apply_validators.py`" in runbook
    assert "Do not import RabbitMQ definitions" in runbook
