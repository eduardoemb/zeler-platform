from __future__ import annotations

from typing import Any

import pytest

from zeler_bootstrap import __main__
from zeler_bootstrap.runtime import (
    BootstrapRuntimeSettings,
    RuntimeConfigError,
    build_runtime_dependencies,
)


def test_runtime_settings_loads_required_env_without_leaking_tokens() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://user:secret@mongo.example/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example/",
            "BOOTSTRAP_GATEWAY_TOKEN": "super-secret-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://guest:guest@rabbitmq/",
            "BOOTSTRAP_MAX_ATTEMPTS": "5",
        }
    )

    assert settings.mongo_db == "zeler_platform"
    assert settings.gateway_base_url == "https://gateway.example"
    assert settings.rabbitmq_exchange == "meli.events"
    assert settings.max_attempts == 5
    assert "super-secret-token" not in repr(settings)
    assert "mongodb://user:secret" not in repr(settings)


def test_amqp_publish_max_attempts_env_override() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_GATEWAY_TOKEN": "runtime-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "BOOTSTRAP_AMQP_PUBLISH_MAX_ATTEMPTS": "7",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        mongo_client_factory=lambda _uri: {"zeler_platform": {"bootstrap_jobs": object()}},
        http_client_factory=lambda **_kwargs: object(),
    )

    assert settings.amqp_publish_max_attempts == 7
    assert deps.publisher.amqp_publish_max_attempts == 7


def test_amqp_publish_timeout_env_override() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_GATEWAY_TOKEN": "runtime-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "BOOTSTRAP_AMQP_PUBLISH_TIMEOUT_S": "2.5",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        mongo_client_factory=lambda _uri: {"zeler_platform": {"bootstrap_jobs": object()}},
        http_client_factory=lambda **_kwargs: object(),
    )

    assert settings.amqp_publish_per_attempt_timeout_s == 2.5
    assert deps.publisher.amqp_publish_per_attempt_timeout_s == 2.5


def test_runtime_settings_reports_missing_required_env_names_only() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        BootstrapRuntimeSettings.from_env({"BOOTSTRAP_GATEWAY_TOKEN": "do-not-leak"})

    message = str(exc_info.value)

    assert "BOOTSTRAP_MONGO_URI" in message
    assert "BOOTSTRAP_MONGO_DB" in message
    assert "BOOTSTRAP_GATEWAY_BASE_URL" in message
    assert "BOOTSTRAP_RABBITMQ_URL" in message
    assert "do-not-leak" not in message


def test_runtime_dependency_factories_use_env_config_without_connecting() -> None:
    calls: dict[str, Any] = {}

    class FakeMongoClient:
        def __init__(self, uri: str) -> None:
            calls["mongo_uri"] = uri

        def __getitem__(self, db_name: str) -> dict[str, str]:
            calls["mongo_db"] = db_name
            return {"bootstrap_jobs": "jobs-collection"}

    class FakeHttpClient:
        def __init__(self, *, base_url: str, headers: dict[str, str], timeout: float) -> None:
            calls["http"] = {"base_url": base_url, "headers": headers, "timeout": timeout}

    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example/api",
            "BOOTSTRAP_GATEWAY_TOKEN": "runtime-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "BOOTSTRAP_RABBITMQ_EXCHANGE": "bootstrap.events",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        mongo_client_factory=FakeMongoClient,
        http_client_factory=FakeHttpClient,
    )

    assert calls == {
        "mongo_uri": "mongodb://mongo/zeler_platform",
        "mongo_db": "zeler_platform",
        "http": {
            "base_url": "https://gateway.example/api",
            "headers": {"Authorization": "Bearer runtime-token"},
            "timeout": 30.0,
        },
    }
    assert deps.jobs_collection == "jobs-collection"
    assert deps.database == {"bootstrap_jobs": "jobs-collection"}
    assert deps.gateway.path_prefix == "/proxy/meli"
    assert deps.publisher.rabbitmq_url == "amqp://rabbitmq/"
    assert deps.publisher.exchange_name == "bootstrap.events"


def test_cli_non_dry_run_builds_runtime_dependencies_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeDependencies:
        jobs_collection = object()
        database = object()
        gateway = object()
        publisher = object()

    async def fake_run_bootstrap_job(**kwargs: Any) -> dict[str, Any]:
        observed["run_kwargs"] = kwargs
        return {"_id": kwargs["job_id"], "seller_id": kwargs["seller_id"], "state": "succeeded"}

    def fake_build_runtime_dependencies(settings: BootstrapRuntimeSettings) -> FakeDependencies:
        observed["settings"] = settings
        return FakeDependencies()

    monkeypatch.setenv("BOOTSTRAP_MONGO_URI", "mongodb://mongo/zeler_platform")
    monkeypatch.setenv("BOOTSTRAP_MONGO_DB", "zeler_platform")
    monkeypatch.setenv("BOOTSTRAP_GATEWAY_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("BOOTSTRAP_GATEWAY_TOKEN", "runtime-token")
    monkeypatch.setenv("BOOTSTRAP_RABBITMQ_URL", "amqp://rabbitmq/")
    monkeypatch.setenv("BOOTSTRAP_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(__main__, "build_runtime_dependencies", fake_build_runtime_dependencies)
    monkeypatch.setattr(__main__, "run_bootstrap_job", fake_run_bootstrap_job)
    logging_calls: list[str] = []
    monkeypatch.setattr(__main__, "configure_logging", logging_calls.append)

    __main__.main(["--seller-id", "123", "--job-id", "job-123"])

    assert observed["settings"].mongo_db == "zeler_platform"
    assert observed["run_kwargs"]["seller_id"] == "123"
    assert observed["run_kwargs"]["job_id"] == "job-123"
    assert observed["run_kwargs"]["jobs_collection"] is FakeDependencies.jobs_collection
    assert observed["run_kwargs"]["max_attempts"] == 4
    assert logging_calls == ["test"]


def test_resolve_env_defaults_to_production_and_accepts_zeler_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ZELER_ENV", raising=False)
    assert __main__._resolve_env() == "production"

    monkeypatch.setenv("ZELER_ENV", "prod")
    assert __main__._resolve_env() == "production"

    monkeypatch.setenv("ENVIRONMENT", "development")
    assert __main__._resolve_env() == "development"


def test_cli_dry_run_does_not_read_runtime_env_or_build_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_build_runtime_dependencies(settings: BootstrapRuntimeSettings) -> None:
        raise AssertionError(f"dry-run should not build runtime dependencies: {settings!r}")

    monkeypatch.delenv("BOOTSTRAP_MONGO_URI", raising=False)
    monkeypatch.delenv("BOOTSTRAP_MONGO_DB", raising=False)
    monkeypatch.delenv("BOOTSTRAP_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("BOOTSTRAP_RABBITMQ_URL", raising=False)
    monkeypatch.setattr(__main__, "build_runtime_dependencies", fail_build_runtime_dependencies)

    __main__.main(["--seller-id", "123", "--job-id", "job-123", "--dry-run"])
