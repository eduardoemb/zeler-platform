"""Tests for infra/mongo/apply_seeds.py.

All tests use a FakeDatabase/FakeClient pair (same pattern as test_apply_validators.py)
so no real MongoDB connection is required.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "infra" / "mongo" / "apply_seeds.py"


# ---------------------------------------------------------------------------
# Test doubles — mirror test_apply_validators.py exactly
# ---------------------------------------------------------------------------


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[Any, dict[str, Any]] = {}
        self.update_one_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def update_one(
        self,
        filter_: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> FakeUpdateResult:
        doc_id = filter_["_id"]
        self.update_one_calls.append((filter_, update))
        if doc_id in self.documents:
            # $setOnInsert: existing doc is NOT touched
            return FakeUpdateResult(matched_count=1, upserted_id=None)
        # New document — insert it
        doc = update.get("$setOnInsert", {})
        self.documents[doc_id] = dict(doc)
        return FakeUpdateResult(matched_count=0, upserted_id=doc_id)


class FakeUpdateResult:
    def __init__(self, matched_count: int, upserted_id: Any) -> None:
        self.matched_count = matched_count
        self.upserted_id = upserted_id


class FakeDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.closed = False

    def get_default_database(self) -> FakeDatabase:
        return self.database

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def apply_seeds_module() -> ModuleType:
    assert MODULE_PATH.exists(), "infra/mongo/apply_seeds.py must exist"
    return importlib.import_module("infra.mongo.apply_seeds")


@pytest.fixture
def fake_client_factory() -> tuple[FakeDatabase, FakeClient]:
    database = FakeDatabase()
    return database, FakeClient(database)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_apply_seeds_contract_signature(apply_seeds_module: ModuleType) -> None:
    apply_seeds = getattr(apply_seeds_module, "apply_seeds", None)
    assert callable(apply_seeds)

    sig = inspect.signature(apply_seeds)
    assert list(sig.parameters) == ["mongo_uri", "seeds_dir"]
    assert str(sig.parameters["mongo_uri"].annotation) == "str"
    assert str(sig.parameters["seeds_dir"].annotation).endswith("Path")
    assert str(sig.return_annotation) in {"dict[str, str]", "Dict[str, str]"}


# ---------------------------------------------------------------------------
# Test 1: upserts new document → "inserted"
# ---------------------------------------------------------------------------


def test_apply_seeds_upserts_new_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "users.json").write_text(
        json.dumps(
            {
                "collection": "users",
                "documents": [{"_id": "u1", "name": "Alice"}],
            }
        ),
        encoding="utf-8",
    )

    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: fake_client)

    result = apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)

    assert result == {"users/u1": "inserted"}
    assert database["users"].documents["u1"] == {"_id": "u1", "name": "Alice"}
    assert fake_client.closed


# ---------------------------------------------------------------------------
# Test 2: skips existing doc — $setOnInsert does NOT overwrite live data
# ---------------------------------------------------------------------------


def test_apply_seeds_skips_existing_document_does_not_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "users.json").write_text(
        json.dumps(
            {
                "collection": "users",
                "documents": [{"_id": "u1", "name": "SEED_VALUE"}],
            }
        ),
        encoding="utf-8",
    )

    database = FakeDatabase()
    # Pre-populate with different live data
    database["users"].documents["u1"] = {"_id": "u1", "name": "LIVE_VALUE"}
    fake_client = FakeClient(database)
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: fake_client)

    result = apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)

    assert result == {"users/u1": "unchanged"}
    # Critical: live data must be untouched
    assert database["users"].documents["u1"]["name"] == "LIVE_VALUE"


# ---------------------------------------------------------------------------
# Test 3: multiple documents in one file
# ---------------------------------------------------------------------------


def test_apply_seeds_handles_multiple_documents_in_one_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "items.json").write_text(
        json.dumps(
            {
                "collection": "items",
                "documents": [
                    {"_id": "i1", "label": "first"},
                    {"_id": "i2", "label": "second"},
                ],
            }
        ),
        encoding="utf-8",
    )

    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: fake_client)

    result = apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)

    assert result == {"items/i1": "inserted", "items/i2": "inserted"}
    assert database["items"].documents["i1"]["label"] == "first"
    assert database["items"].documents["i2"]["label"] == "second"


# ---------------------------------------------------------------------------
# Test 4: multiple seed files
# ---------------------------------------------------------------------------


def test_apply_seeds_processes_multiple_seed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "col_a.json").write_text(
        json.dumps({"collection": "col_a", "documents": [{"_id": "a1"}]}),
        encoding="utf-8",
    )
    (seeds_dir / "col_b.json").write_text(
        json.dumps({"collection": "col_b", "documents": [{"_id": "b1"}]}),
        encoding="utf-8",
    )

    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: fake_client)

    result = apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)

    assert result == {"col_a/a1": "inserted", "col_b/b1": "inserted"}


# ---------------------------------------------------------------------------
# Test 5: raises on missing "collection" field
# ---------------------------------------------------------------------------


def test_apply_seeds_raises_on_missing_collection_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "bad.json").write_text(
        json.dumps({"documents": [{"_id": "x1"}]}),
        encoding="utf-8",
    )

    database = FakeDatabase()
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: FakeClient(database))

    with pytest.raises(ValueError, match="collection"):
        apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)


# ---------------------------------------------------------------------------
# Test 6: raises on missing "documents" field
# ---------------------------------------------------------------------------


def test_apply_seeds_raises_on_missing_documents_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "bad.json").write_text(
        json.dumps({"collection": "things"}),
        encoding="utf-8",
    )

    database = FakeDatabase()
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: FakeClient(database))

    with pytest.raises(ValueError, match="documents"):
        apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)


# ---------------------------------------------------------------------------
# Test 7: raises on document without _id
# ---------------------------------------------------------------------------


def test_apply_seeds_raises_on_document_without_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "bad.json").write_text(
        json.dumps({"collection": "things", "documents": [{"name": "no_id_here"}]}),
        encoding="utf-8",
    )

    database = FakeDatabase()
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: FakeClient(database))

    with pytest.raises(ValueError, match="_id"):
        apply_seeds_module.apply_seeds("mongodb://test/db", seeds_dir)


# ---------------------------------------------------------------------------
# Test 8: returns {} when seeds_dir does not exist
# ---------------------------------------------------------------------------


def test_apply_seeds_returns_empty_when_seeds_dir_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    missing_dir = tmp_path / "nonexistent"

    database = FakeDatabase()
    fake_client = FakeClient(database)
    monkeypatch.setattr(apply_seeds_module, "MongoClient", lambda _uri: fake_client)

    result = apply_seeds_module.apply_seeds("mongodb://test/db", missing_dir)

    assert result == {}
    assert fake_client.closed


# ---------------------------------------------------------------------------
# Test: main() reads env vars with correct defaults
# ---------------------------------------------------------------------------


def test_apply_seeds_main_reads_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    apply_seeds_module: ModuleType,
) -> None:
    calls: list[tuple[str, Path]] = []

    def fake_apply_seeds(mongo_uri: str, seeds_dir: Path) -> dict[str, str]:
        calls.append((mongo_uri, seeds_dir))
        return {}

    monkeypatch.setattr(apply_seeds_module, "apply_seeds", fake_apply_seeds)
    monkeypatch.setenv("MONGO_URI", "mongodb://env.test/zeler_platform")
    monkeypatch.delenv("SEEDS_DIR", raising=False)

    main = getattr(apply_seeds_module, "main", None)
    assert callable(main)
    main()

    assert len(calls) == 1
    uri, seeds_dir = calls[0]
    assert uri == "mongodb://env.test/zeler_platform"
    assert seeds_dir == ROOT / "infra" / "mongo" / "seeds"
    assert 'if __name__ == "__main__":' in MODULE_PATH.read_text(encoding="utf-8")
