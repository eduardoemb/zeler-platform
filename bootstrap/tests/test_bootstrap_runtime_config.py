from __future__ import annotations

from typing import Any

import httpx
import pytest

from zeler_bootstrap import __main__
from zeler_bootstrap.runtime import (
    BootstrapRuntimeSettings,
    RuntimeConfigError,
    build_runtime_dependencies,
)
from zeler_platform_core.auth.jwt import verify_module_jwt


class FakeKmsSignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class FakeKmsPublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeJwtKmsClient:
    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import ec

        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.sign_calls = 0

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        self.sign_calls += 1
        digest = request["digest"]
        sha256_digest = digest["sha256"]
        signature = self.private_key.sign(
            sha256_digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return FakeKmsSignResponse(signature)

    def get_public_key(self, request: dict[str, str]) -> FakeKmsPublicKeyResponse:
        from cryptography.hazmat.primitives import serialization

        pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return FakeKmsPublicKeyResponse(pem.decode("ascii"))


class FailingJwtKmsClient:
    def asymmetric_sign(self, request: dict[str, Any]) -> Any:
        raise RuntimeError("kms signing unavailable SECRET=do-not-leak")

    def get_public_key(self, request: dict[str, str]) -> Any:
        raise AssertionError("public key should not be requested when signing fails")


def test_runtime_settings_loads_required_env_without_leaking_tokens() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://user:secret@mongo.example/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example/",
            "BOOTSTRAP_GATEWAY_TOKEN": "super-secret-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://guest:guest@rabbitmq/",
            "BOOTSTRAP_MAX_ATTEMPTS": "5",
            "ZELER_ENV": "development",
        }
    )

    assert settings.mongo_db == "zeler_platform"
    assert settings.gateway_base_url == "https://gateway.example"
    assert settings.rabbitmq_exchange == "meli.events"
    assert settings.max_attempts == 5
    assert "super-secret-token" not in repr(settings)
    assert "mongodb://user:secret" not in repr(settings)


def test_runtime_settings_prod_does_not_require_static_gateway_token() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_MODULE_ID": "bootstrap",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "ZELER_ENV": "prod",
        }
    )

    assert settings.gateway_token is None
    assert settings.module_id == "bootstrap"


def test_runtime_settings_prod_rejects_static_gateway_token_without_leaking_it() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        BootstrapRuntimeSettings.from_env(
            {
                "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
                "BOOTSTRAP_MONGO_DB": "zeler_platform",
                "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
                "BOOTSTRAP_GATEWAY_TOKEN": "do-not-leak-token",
                "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
                "ZELER_ENV": "prod",
            }
        )

    message = str(exc_info.value)
    assert "BOOTSTRAP_GATEWAY_TOKEN" in message
    assert "production" in message
    assert "do-not-leak-token" not in message


def test_amqp_publish_max_attempts_env_override() -> None:
    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_GATEWAY_TOKEN": "runtime-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "BOOTSTRAP_AMQP_PUBLISH_MAX_ATTEMPTS": "7",
            "ZELER_ENV": "development",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        seller_id="123",
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
            "ZELER_ENV": "development",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        seller_id="123",
        mongo_client_factory=lambda _uri: {"zeler_platform": {"bootstrap_jobs": object()}},
        http_client_factory=lambda **_kwargs: object(),
    )

    assert settings.amqp_publish_per_attempt_timeout_s == 2.5
    assert deps.publisher.amqp_publish_per_attempt_timeout_s == 2.5


def test_runtime_settings_reports_missing_required_env_names_only() -> None:
    with pytest.raises(RuntimeConfigError) as exc_info:
        BootstrapRuntimeSettings.from_env(
            {"BOOTSTRAP_GATEWAY_TOKEN": "do-not-leak", "ZELER_ENV": "development"}
        )

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
        def __init__(self, *, base_url: str, timeout: float) -> None:
            calls["http"] = {"base_url": base_url, "timeout": timeout}

    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example/api",
            "BOOTSTRAP_GATEWAY_TOKEN": "runtime-token",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "BOOTSTRAP_RABBITMQ_EXCHANGE": "bootstrap.events",
            "ZELER_ENV": "development",
        }
    )

    deps = build_runtime_dependencies(
        settings,
        seller_id="123",
        mongo_client_factory=FakeMongoClient,
        http_client_factory=FakeHttpClient,
    )

    assert calls == {
        "mongo_uri": "mongodb://mongo/zeler_platform",
        "mongo_db": "zeler_platform",
        "http": {
            "base_url": "https://gateway.example/api",
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

    def fake_build_runtime_dependencies(
        settings: BootstrapRuntimeSettings, *, seller_id: str
    ) -> FakeDependencies:
        observed["settings"] = settings
        observed["dependency_seller_id"] = seller_id
        return FakeDependencies()

    monkeypatch.setenv("BOOTSTRAP_MONGO_URI", "mongodb://mongo/zeler_platform")
    monkeypatch.setenv("BOOTSTRAP_MONGO_DB", "zeler_platform")
    monkeypatch.setenv("BOOTSTRAP_GATEWAY_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("BOOTSTRAP_GATEWAY_TOKEN", "runtime-token")
    monkeypatch.setenv("BOOTSTRAP_RABBITMQ_URL", "amqp://rabbitmq/")
    monkeypatch.setenv("BOOTSTRAP_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(__main__, "build_runtime_dependencies", fake_build_runtime_dependencies)
    monkeypatch.setattr(__main__, "run_bootstrap_job", fake_run_bootstrap_job)
    logging_calls: list[str] = []
    monkeypatch.setattr(__main__, "configure_logging", logging_calls.append)

    __main__.main(["--seller-id", "123", "--job-id", "job-123"])

    assert observed["settings"].mongo_db == "zeler_platform"
    assert observed["dependency_seller_id"] == "123"
    assert observed["run_kwargs"]["seller_id"] == "123"
    assert observed["run_kwargs"]["job_id"] == "job-123"
    assert observed["run_kwargs"]["jobs_collection"] is FakeDependencies.jobs_collection
    assert observed["run_kwargs"]["max_attempts"] == 4
    assert logging_calls == ["development"]


@pytest.mark.asyncio
async def test_runtime_gateway_client_mints_per_seller_jwt_authorization() -> None:
    requests: list[httpx.Request] = []
    kms_client = FakeJwtKmsClient()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    def http_client_factory(*, base_url: str, timeout: float) -> httpx.AsyncClient:
        assert base_url == "https://gateway.example"
        assert timeout == 30.0
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)

    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_MODULE_ID": "bootstrap",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "ZELER_ENV": "prod",
        }
    )
    deps = build_runtime_dependencies(
        settings,
        seller_id="123456",
        mongo_client_factory=lambda _uri: {"zeler_platform": {"bootstrap_jobs": object()}},
        http_client_factory=http_client_factory,
        kms_client_factory=lambda: kms_client,
    )

    payload = await deps.gateway.get("/users/123456")

    assert payload == {"ok": True}
    assert len(requests) == 1
    auth_header = requests[0].headers["Authorization"]
    token = auth_header.removeprefix("Bearer ")
    claims = verify_module_jwt(token)
    assert claims.module_id == "bootstrap"
    assert claims.seller_id == 123456
    assert kms_client.sign_calls == 1


@pytest.mark.asyncio
async def test_runtime_gateway_client_fails_before_http_when_jwt_signing_fails() -> None:
    http_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"should": "not happen"})

    settings = BootstrapRuntimeSettings.from_env(
        {
            "BOOTSTRAP_MONGO_URI": "mongodb://mongo/zeler_platform",
            "BOOTSTRAP_MONGO_DB": "zeler_platform",
            "BOOTSTRAP_GATEWAY_BASE_URL": "https://gateway.example",
            "BOOTSTRAP_MODULE_ID": "bootstrap",
            "BOOTSTRAP_RABBITMQ_URL": "amqp://rabbitmq/",
            "ZELER_ENV": "prod",
        }
    )
    deps = build_runtime_dependencies(
        settings,
        seller_id="123456",
        mongo_client_factory=lambda _uri: {"zeler_platform": {"bootstrap_jobs": object()}},
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), **kwargs
        ),
        kms_client_factory=FailingJwtKmsClient,
    )

    with pytest.raises(Exception) as exc_info:
        await deps.gateway.get("/users/123456")

    assert http_calls == 0
    assert "do-not-leak" not in str(exc_info.value)


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
    def fail_build_runtime_dependencies(
        settings: BootstrapRuntimeSettings, *, seller_id: str
    ) -> None:
        raise AssertionError(f"dry-run should not build runtime dependencies: {settings!r}")

    monkeypatch.delenv("BOOTSTRAP_MONGO_URI", raising=False)
    monkeypatch.delenv("BOOTSTRAP_MONGO_DB", raising=False)
    monkeypatch.delenv("BOOTSTRAP_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("BOOTSTRAP_RABBITMQ_URL", raising=False)
    monkeypatch.setattr(__main__, "build_runtime_dependencies", fail_build_runtime_dependencies)

    __main__.main(["--seller-id", "123", "--job-id", "job-123", "--dry-run"])
