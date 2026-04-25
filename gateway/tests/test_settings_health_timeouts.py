from __future__ import annotations

import pytest

from zeler_gateway.config import Settings


def test_readiness_timeout_settings_default_to_two_seconds() -> None:
    settings = Settings()

    assert settings.ready_mongo_timeout_s == 2.0
    assert settings.ready_rabbitmq_timeout_s == 2.0


def test_readiness_timeout_settings_are_configurable_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("READY_MONGO_TIMEOUT_S", "0.75")
    monkeypatch.setenv("READY_RABBITMQ_TIMEOUT_S", "1.25")

    settings = Settings()

    assert settings.ready_mongo_timeout_s == 0.75
    assert settings.ready_rabbitmq_timeout_s == 1.25
