from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
import structlog

from zeler_gateway.observability.logging import configure_logging

_OBSERVABILITY_HANDLER_MARKER = "_zeler_platform_observability"


@pytest.fixture(autouse=True)
def _default_gateway_test_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    configure_logging(environment="test")
    yield
    structlog.reset_defaults()
    for handler in logging.getLogger().handlers[:]:
        if getattr(handler, _OBSERVABILITY_HANDLER_MARKER, False):
            logging.getLogger().removeHandler(handler)
            handler.close()
