from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterator
from types import ModuleType

import pytest
from fastapi import FastAPI

MODULES = ("repricer", "sheets", "publicador", "autoreply")


class FakeMongoClient:
    calls: list[str] = []

    def __init__(self, mongo_uri: str) -> None:
        self.calls.append(mongo_uri)

    def __getitem__(self, mongo_db_name: str) -> object:
        return {"mongo_db_name": mongo_db_name}


@pytest.fixture(autouse=True)
def reset_fake_mongo_client() -> Iterator[None]:
    FakeMongoClient.calls = []
    yield


def import_app_module(module_name: str) -> ModuleType:
    return importlib.import_module(f"zeler_{module_name}.app")


@pytest.mark.parametrize("module_name", MODULES)
def test_make_app_returns_fastapi(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://mongo:27017")
    monkeypatch.setenv("MONGO_DB", f"zeler_{module_name}")
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", FakeMongoClient)
    monkeypatch.setattr("google.cloud.kms.KeyManagementServiceClient", object)
    _set_module_env(monkeypatch, module_name)
    module = import_app_module(module_name)

    app = module.make_app()

    assert isinstance(app, FastAPI)


@pytest.mark.parametrize("module_name", MODULES)
def test_make_app_raises_on_missing_mongo_uri(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("MONGO_DB", f"zeler_{module_name}")
    module = import_app_module(module_name)

    with pytest.raises(RuntimeError, match="MONGO_URI"):
        module.make_app()


@pytest.mark.parametrize("module_name", MODULES)
def test_make_app_raises_on_missing_mongo_db(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://mongo:27017")
    monkeypatch.delenv("MONGO_DB", raising=False)
    module = import_app_module(module_name)

    with pytest.raises(RuntimeError, match="MONGO_DB"):
        module.make_app()


@pytest.mark.parametrize("module_name", MODULES)
def test_import_does_not_call_motor(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    monkeypatch.setattr("motor.motor_asyncio.AsyncIOMotorClient", FakeMongoClient)
    module = import_app_module(module_name)

    importlib.reload(module)

    assert FakeMongoClient.calls == []


@pytest.mark.parametrize("module_name", MODULES)
def test_make_app_is_no_arg(module_name: str) -> None:
    module = import_app_module(module_name)

    signature = inspect.signature(module.make_app)
    required_positionals = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]

    assert required_positionals == []


def _set_module_env(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    if module_name != "sheets":
        return

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.test/oauth")
    monkeypatch.setenv("KMS_PROJECT_ID", "test-project")
