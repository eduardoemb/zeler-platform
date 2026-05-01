from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "infra" / "mongo" / "apply_validators.py"


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.collmod_calls: list[tuple[str, dict[str, Any]]] = []

    def list_collection_names(self) -> list[str]:
        return list(self.collections)

    def create_collection(self, name: str, validator: dict[str, Any] | None = None) -> None:
        self.collections[name] = validator or {}

    def command(self, command_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if command_name == "listCollections":
            filter_spec = kwargs["filter"]
            name = filter_spec["name"]
            validator = self.collections.get(name, {})
            return {"cursor": {"firstBatch": [{"options": {"validator": validator}}]}}

        if command_name == "collMod":
            name = args[0]
            validator = kwargs.get("validator", {})
            assert isinstance(name, str)
            assert isinstance(validator, dict)
            self.collections[name] = validator
            self.collmod_calls.append((name, validator))
            return {"ok": 1}

        msg = f"Unexpected command: {command_name}"
        raise AssertionError(msg)


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.closed = False

    def get_default_database(self) -> FakeDatabase:
        return self.database

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def apply_validators_module() -> ModuleType:
    assert MODULE_PATH.exists(), "infra/mongo/apply_validators.py must exist"
    return importlib.import_module("infra.mongo.apply_validators")


def test_apply_validators_contract_signature(apply_validators_module: ModuleType) -> None:
    apply_validators = getattr(apply_validators_module, "apply_validators", None)

    assert callable(apply_validators)

    signature = inspect.signature(apply_validators)
    assert list(signature.parameters) == ["mongo_uri", "schemas_dir"]
    assert str(signature.parameters["mongo_uri"].annotation) == "str"
    assert str(signature.parameters["schemas_dir"].annotation).endswith("Path")
    assert str(signature.return_annotation) in {"dict[str, str]", "Dict[str, str]"}


def test_apply_validators_reads_schema_files_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_validators_module: ModuleType,
) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()

    user_schema = {"bsonType": "object", "required": ["user_id"]}
    (schemas_dir / "users.json").write_text(json.dumps(user_schema), encoding="utf-8")
    (schemas_dir / "audit_log.json").write_text("{}", encoding="utf-8")

    database = FakeDatabase()
    fake_client = FakeClient(database)

    def mongo_client(uri: str) -> FakeClient:
        assert uri == "mongodb://example.test/zeler_platform"
        return fake_client

    monkeypatch.setattr(apply_validators_module, "MongoClient", mongo_client)

    result_first = apply_validators_module.apply_validators(
        "mongodb://example.test/zeler_platform",
        schemas_dir,
    )

    assert result_first == {"audit_log": "created", "users": "created"}

    result_second = apply_validators_module.apply_validators(
        "mongodb://example.test/zeler_platform",
        schemas_dir,
    )

    assert result_second == {"audit_log": "unchanged", "users": "unchanged"}
    assert database.collmod_calls == []


def test_apply_validators_updates_changed_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_validators_module: ModuleType,
) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()

    new_schema = {"bsonType": "object", "required": ["seller_id"]}
    (schemas_dir / "items.json").write_text(json.dumps(new_schema), encoding="utf-8")

    database = FakeDatabase()
    database.collections["items"] = {"$jsonSchema": {"bsonType": "object"}}
    fake_client = FakeClient(database)

    def mongo_client(uri: str) -> FakeClient:
        assert uri == "mongodb://example.test/zeler_platform"
        return fake_client

    monkeypatch.setattr(apply_validators_module, "MongoClient", mongo_client)

    result = apply_validators_module.apply_validators(
        "mongodb://example.test/zeler_platform",
        schemas_dir,
    )

    assert result == {"items": "applied"}
    assert database.collmod_calls == [("items", {"$jsonSchema": new_schema})]


def test_apply_validators_treats_placeholder_schema_as_inactive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_validators_module: ModuleType,
) -> None:
    """Regression: P3 placeholder schemas use $comment to mark TODOs.

    Mongo $jsonSchema rejects unknown keywords like $comment with
    'Unknown $jsonSchema keyword'. A schema that lacks ANY canonical
    JSON Schema keyword (bsonType, type, properties, required, items,
    enum, oneOf, anyOf, allOf, not, additionalProperties, patternProperties)
    must be treated as inactive: no validator applied.
    """
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()

    placeholder = {"$comment": "TODO: populated in Phase 3"}
    (schemas_dir / "users.json").write_text(json.dumps(placeholder), encoding="utf-8")

    database = FakeDatabase()
    fake_client = FakeClient(database)

    monkeypatch.setattr(apply_validators_module, "MongoClient", lambda _uri: fake_client)

    result = apply_validators_module.apply_validators(
        "mongodb://example.test/zeler_platform",
        schemas_dir,
    )

    assert result == {"users": "created"}
    # Critical: validator must be empty {}, NOT {"$jsonSchema": {"$comment": ...}}
    assert database.collections["users"] == {}, (
        "Placeholder schema (no canonical JSON Schema keywords) "
        "must produce empty validator, NOT a $jsonSchema with $comment"
    )

    # Idempotent: second call sees no validator + placeholder still inactive
    result_second = apply_validators_module.apply_validators(
        "mongodb://example.test/zeler_platform",
        schemas_dir,
    )
    assert result_second == {"users": "unchanged"}


def test_apply_validators_main_reads_env_vars_and_default_schema_dir(
    monkeypatch: pytest.MonkeyPatch,
    apply_validators_module: ModuleType,
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_validators(mongo_uri: str, schemas_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, schemas_dir))
        return {"users": "unchanged"}

    monkeypatch.setattr(apply_validators_module, "apply_validators", fake_apply_validators)
    monkeypatch.setenv("MONGO_URI", "mongodb://env.test/zeler_platform")
    monkeypatch.delenv("SCHEMAS_DIR", raising=False)

    main = getattr(apply_validators_module, "main", None)
    assert callable(main)

    main()

    assert calls == [
        (
            "mongodb://env.test/zeler_platform",
            ROOT / "infra" / "mongo" / "schemas",
        )
    ]
    assert 'if __name__ == "__main__":' in MODULE_PATH.read_text(encoding="utf-8")


def test_apply_validators_main_honors_explicit_schemas_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_validators_module: ModuleType,
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_validators(mongo_uri: str, schemas_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, schemas_dir))
        return {"users": "unchanged"}

    custom_dir = tmp_path / "custom-schemas"
    monkeypatch.setattr(apply_validators_module, "apply_validators", fake_apply_validators)
    monkeypatch.setenv("MONGO_URI", "mongodb://env.test/zeler_platform")
    monkeypatch.setenv("SCHEMAS_DIR", str(custom_dir))

    apply_validators_module.main()

    assert calls == [("mongodb://env.test/zeler_platform", custom_dir)]
