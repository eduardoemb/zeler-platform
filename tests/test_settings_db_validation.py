from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from zeler_bootstrap.runtime import BootstrapRuntimeSettings, RuntimeConfigError
from zeler_gateway.config import Settings as GatewaySettings


@dataclass(frozen=True)
class GatewaySettingsFactory:
    label: str = "gateway"
    exception_type: type[Exception] = ValidationError

    def build(self, mongo_uri: str, mongo_db: str | None) -> GatewaySettings:
        if mongo_db is None:
            return GatewaySettings(MONGO_URI=mongo_uri)
        return GatewaySettings(MONGO_URI=mongo_uri, MONGO_DB=mongo_db)


@dataclass(frozen=True)
class BootstrapSettingsFactory:
    label: str = "bootstrap"
    exception_type: type[Exception] = RuntimeConfigError

    def build(self, mongo_uri: str, mongo_db: str | None) -> BootstrapRuntimeSettings:
        return BootstrapRuntimeSettings(
            mongo_uri=mongo_uri,
            mongo_db=mongo_db or "",
            gateway_base_url="https://gateway.example",
            gateway_token="test-token",  # noqa: S106 - deterministic non-secret fixture value.
            rabbitmq_url="amqp://rabbitmq/",
        )


SettingsFactory = GatewaySettingsFactory | BootstrapSettingsFactory


SETTINGS_FACTORIES: tuple[SettingsFactory, ...] = (
    GatewaySettingsFactory(),
    BootstrapSettingsFactory(),
)


def test_mongo_uri_empty_path_with_mongo_db_is_allowed() -> None:
    for factory in SETTINGS_FACTORIES:
        settings = factory.build(
            "mongodb://user:secret@127.0.0.1:27019/?authSource=admin",
            "zeler_platform_prod",
        )

        assert settings is not None, factory.label


def test_mongo_uri_path_matching_mongo_db_is_allowed() -> None:
    for factory in SETTINGS_FACTORIES:
        settings = factory.build(
            "mongodb://user:secret@127.0.0.1:27019/zeler_platform_prod?authSource=admin",
            "zeler_platform_prod",
        )

        assert settings is not None, factory.label


def test_mongo_uri_path_mismatching_mongo_db_raises_with_both_values() -> None:
    for factory in SETTINGS_FACTORIES:
        with pytest.raises(factory.exception_type) as exc_info:
            factory.build(
                "mongodb://user:secret@127.0.0.1:27019/zeler_platform_dev?authSource=admin",
                "zeler_platform_prod",
            )

        message = str(exc_info.value)
        assert "zeler_platform_dev" in message, factory.label
        assert "zeler_platform_prod" in message, factory.label


def test_mongo_uri_path_is_not_validated_when_mongo_db_is_unset_or_empty() -> None:
    for factory in SETTINGS_FACTORIES:
        settings = factory.build(
            "mongodb://user:secret@127.0.0.1:27019/zeler_platform_prod?authSource=admin",
            None,
        )

        assert settings is not None, factory.label
