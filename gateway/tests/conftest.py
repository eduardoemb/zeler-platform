from __future__ import annotations

import pytest

from zeler_gateway.observability.logging import configure_logging


@pytest.fixture(autouse=True)
def _default_gateway_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    configure_logging(environment="test")
