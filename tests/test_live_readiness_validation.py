from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo.readiness import build_mongo_readiness_report, render_mongo_markdown
from infra.rabbitmq.readiness import (
    build_rabbitmq_amqp_passive_readiness_report,
    build_rabbitmq_readiness_report,
    render_rabbitmq_markdown,
)

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
    missing_binding = next(
        binding
        for binding in definitions["bindings"]
        if binding["destination"] == "zeler.publicador.messages"
        and binding["routing_key"] == "messages.*"
    )
    export = {
        "exchanges": definitions["exchanges"],
        "queues": definitions["queues"],
        "bindings": [binding for binding in definitions["bindings"] if binding != missing_binding],
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


def test_rabbitmq_readiness_accepts_management_default_classic_queue_type(
    tmp_path: Path,
) -> None:
    definitions = json.loads((ROOT / "infra" / "rabbitmq" / "definitions.json").read_text())
    export = {
        "exchanges": definitions["exchanges"],
        "queues": [
            {
                **queue,
                "arguments": {
                    **queue.get("arguments", {}),
                    "x-queue-type": "classic",
                },
            }
            for queue in definitions["queues"]
        ],
        "bindings": definitions["bindings"],
    }
    export_path = tmp_path / "management-export.json"
    export_path.write_text(json.dumps(export), encoding="utf-8")

    report = build_rabbitmq_readiness_report(
        definitions_path=ROOT / "infra" / "rabbitmq" / "definitions.json",
        management_export_path=export_path,
    )

    assert report.summary["missing_queues"] == 0


def test_rabbitmq_passive_readiness_checks_resources_without_mutation(monkeypatch: Any) -> None:
    calls: list[tuple[str, str, str]] = []

    class FakeConnection:
        async def channel(self) -> FakeChannel:
            return FakeChannel()

        async def close(self) -> None:
            calls.append(("connection", "close", ""))

    class FakeChannel:
        async def declare_exchange(
            self,
            name: str,
            type: str,
            *,
            durable: bool,
            passive: bool,
        ) -> None:
            calls.append(("exchange", name, f"{type}:{durable}:{passive}"))

        async def declare_queue(
            self,
            name: str,
            *,
            durable: bool,
            passive: bool,
            arguments: dict[str, Any],
        ) -> None:
            calls.append(("queue", name, f"{durable}:{passive}:{bool(arguments)}"))

        async def close(self) -> None:
            calls.append(("channel", "close", ""))

    async def fake_connect_robust(_url: str, **_kwargs: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("infra.rabbitmq.readiness.aio_pika.connect_robust", fake_connect_robust)

    report = build_rabbitmq_amqp_passive_readiness_report(
        definitions_path=ROOT / "infra" / "rabbitmq" / "definitions.json",
        amqp_url="amqps://example.test/vhost",
        timeout_seconds=1,
    )

    assert report.mode == "amqp-passive"
    assert report.safe_to_execute is True
    assert report.read_only is True
    assert report.mutations_attempted == 0
    assert report.summary["missing_exchanges"] == 0
    assert report.summary["missing_queues"] == 0
    assert report.summary["unchecked_bindings"] == report.summary["expected_bindings"]
    assert any(call[0] == "exchange" for call in calls)
    assert any(call[0] == "queue" for call in calls)


def test_rabbitmq_passive_readiness_reports_missing_queue(monkeypatch: Any) -> None:
    class FakeConnection:
        async def channel(self) -> FakeChannel:
            return FakeChannel()

        async def close(self) -> None:
            return None

    class FakeChannel:
        async def declare_exchange(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        async def declare_queue(self, name: str, **_kwargs: Any) -> None:
            if name == "zeler.repricer.sweep":
                raise RuntimeError("not found")

        async def close(self) -> None:
            return None

    async def fake_connect_robust(_url: str, **_kwargs: Any) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("infra.rabbitmq.readiness.aio_pika.connect_robust", fake_connect_robust)

    report = build_rabbitmq_amqp_passive_readiness_report(
        definitions_path=ROOT / "infra" / "rabbitmq" / "definitions.json",
        amqp_url="amqps://example.test/vhost",
        timeout_seconds=1,
    )

    assert report.summary["missing_queues"] == 1
    assert any(
        finding.severity == "fail"
        and finding.resource_type == "queue"
        and finding.resource_name == "zeler.repricer.sweep"
        for finding in report.findings
    )


def test_mongo_readiness_offline_default_validates_schema_and_index_files() -> None:
    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        seeds_dir=ROOT / "infra" / "mongo" / "seeds",
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
    assert report.summary["seed_files"] >= 1
    assert report.summary["seed_file_errors"] == 0
    assert report.summary["module_registry_admin_clients"] >= 1

    markdown = render_mongo_markdown(report)
    assert "safe_to_execute: true" in markdown
    assert "read_only: true" in markdown
    assert "No collMod, createIndex, drop, or import operations are attempted" in markdown
    assert (
        "Seed files are local JSON contracts only; readiness does not "
        "insert or upsert seed documents." in markdown
    )


def test_mongo_readiness_validates_zeler_app_admin_seed_scope() -> None:
    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        seeds_dir=ROOT / "infra" / "mongo" / "seeds",
        mongo_uri=None,
    )

    assert report.summary["module_registry_admin_clients"] >= 1
    assert report.summary["module_registry_scope_mismatches"] == 0
    assert not [
        finding
        for finding in report.findings
        if finding.resource_type == "seed" and finding.resource_name == "zeler-app"
    ]


def test_mongo_readiness_reports_wrong_zeler_app_admin_seed_scope(tmp_path: Path) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    wrong_seed = {
        "collection": "module_registry",
        "documents": [
            {
                "_id": "zeler-app",
                "version": "0.1.0",
                "allowed_meli_scopes": ["admin:orders"],
                "routing_keys": [],
                "owned_collections": [],
                "health_endpoint": "/health",
                "status": "enabled",
                "schema_version": 1,
            }
        ],
    }
    (seeds_dir / "module_registry.admin_clients.json").write_text(
        json.dumps(wrong_seed), encoding="utf-8"
    )

    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        seeds_dir=seeds_dir,
        mongo_uri=None,
    )

    assert report.summary["module_registry_scope_mismatches"] == 1
    assert report.findings[0].severity == "fail"
    assert report.findings[0].resource_type == "seed"
    assert report.findings[0].resource_name == "zeler-app"
    assert "admin:repricer" in report.findings[0].detail


def test_mongo_readiness_reports_missing_zeler_app_admin_seed_from_export(tmp_path: Path) -> None:
    export_path = tmp_path / "module-registry-export.json"
    export_path.write_text(json.dumps({"documents": []}), encoding="utf-8")

    report = build_mongo_readiness_report(
        schemas_dir=ROOT / "infra" / "mongo" / "schemas",
        indexes_dir=ROOT / "infra" / "mongo" / "indexes",
        seeds_dir=ROOT / "infra" / "mongo" / "seeds",
        module_registry_export_path=export_path,
        mongo_uri=None,
    )

    assert report.summary["module_registry_missing_admin_clients"] == 1
    assert report.summary["module_registry_export_docs_checked"] == 0
    assert report.findings[0].severity == "fail"
    assert report.findings[0].resource_type == "module_registry_doc"
    assert report.findings[0].resource_name == "zeler-app"


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
        seeds_dir=ROOT / "infra" / "mongo" / "seeds",
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
    assert "RABBITMQ_READINESS_MODE=amqp-passive" in runbook
    assert "infra.rabbitmq.apply_topology" in runbook
    assert "MONGO_URI" in runbook
    assert "MODULE_REGISTRY_EXPORT" in runbook
    assert "python -m infra.rabbitmq.readiness" in runbook
    assert "python -m infra.mongo.readiness" in runbook
    assert "--module-registry-export" in runbook
    assert "module_registry.admin_clients.json" in runbook
    assert "readiness command is read-only" in runbook
    assert "Do not run `infra/mongo/apply_validators.py`" in runbook
    assert "Do not apply module_registry seeds" in runbook
    assert "Do not import RabbitMQ definitions" in runbook
