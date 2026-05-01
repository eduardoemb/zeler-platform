from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.mongo import apply_validators as module


class FakeCollection:
    def __init__(self) -> None:
        self.index_calls: list[tuple[list[tuple[str, int]], dict[str, Any]]] = []

    def create_index(self, keys: list[tuple[str, int]], **options: Any) -> None:
        if not any(existing[1].get("name") == options.get("name") for existing in self.index_calls):
            self.index_calls.append((keys, options))


class FakeDatabase:
    def __init__(self) -> None:
        self.validators: dict[str, dict[str, Any]] = {}
        self.collections: dict[str, FakeCollection] = {}
        self.coll_mod_calls: list[dict[str, Any]] = []
        self.created: list[str] = []

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())

    def list_collection_names(self) -> list[str]:
        return list(self.validators)

    def create_collection(
        self, name: str, validator: dict[str, Any] | None = None, **_options: Any
    ) -> None:
        self.created.append(name)
        self.validators[name] = validator or {}

    def command(
        self, command: str, collection_name: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        if command == "listCollections":
            name = kwargs["filter"]["name"]
            if name not in self.validators:
                return {"cursor": {"firstBatch": []}}
            return {"cursor": {"firstBatch": [{"options": {"validator": self.validators[name]}}]}}
        if command == "collMod":
            assert collection_name is not None
            self.coll_mod_calls.append({"collection": collection_name, **kwargs})
            self.validators[collection_name] = kwargs.get("validator", {})
            return {"ok": 1}
        raise AssertionError(f"unexpected command {command}")


class FakeMongoClient:
    database = FakeDatabase()

    def __init__(self, _uri: str) -> None: ...

    def get_default_database(self) -> FakeDatabase:
        return self.database

    def close(self) -> None: ...


def test_dry_run_does_not_mutate(tmp_path: Path, monkeypatch: Any) -> None:
    schemas_dir = _schemas(tmp_path)
    FakeMongoClient.database = FakeDatabase()
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)

    result = module.apply_validators("mongodb://unit-test/db", schemas_dir, dry_run=True)

    assert result["widgets"] == "would_create"
    assert FakeMongoClient.database.created == []
    assert FakeMongoClient.database.coll_mod_calls == []


def test_second_apply_is_noop(tmp_path: Path, monkeypatch: Any) -> None:
    schemas_dir = _schemas(tmp_path)
    FakeMongoClient.database = FakeDatabase()
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)

    first = module.apply_validators("mongodb://unit-test/db", schemas_dir)
    second = module.apply_validators("mongodb://unit-test/db", schemas_dir)

    assert first["widgets"] == "created"
    assert second["widgets"] == "unchanged"
    assert FakeMongoClient.database.coll_mod_calls == []
    assert len(FakeMongoClient.database["widgets"].index_calls) == 1


def _schemas(tmp_path: Path) -> Path:
    schemas_dir = tmp_path / "schemas"
    indexes_dir = tmp_path / "indexes"
    schemas_dir.mkdir()
    indexes_dir.mkdir()
    (schemas_dir / "widgets.json").write_text(
        json.dumps(
            {"$jsonSchema": {"bsonType": "object", "properties": {"_id": {"bsonType": "string"}}}}
        ),
        encoding="utf-8",
    )
    (indexes_dir / "widgets.json").write_text(
        json.dumps([{"keys": {"_id": 1}, "options": {"name": "idx_widgets_id"}}]),
        encoding="utf-8",
    )
    return schemas_dir
