from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from zeler_gateway.observability import configure_logging as gateway_package_configure_logging
from zeler_gateway.observability.logging import configure_logging as gateway_configure_logging
from zeler_platform_core.observability import configure_logging as core_configure_logging

_OBSERVABILITY_HANDLER_MARKER = "_zeler_platform_observability"


@pytest.fixture(autouse=True)
def reset_logging_configuration() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    for handler in logging.getLogger().handlers[:]:
        if getattr(handler, _OBSERVABILITY_HANDLER_MARKER, False):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_gateway_logging_module_reexports_core_configure_logging() -> None:
    assert gateway_configure_logging is core_configure_logging
    assert gateway_package_configure_logging is core_configure_logging


def test_gateway_logging_shim_preserves_public_behavior(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gateway_configure_logging(environment="production")

    structlog.get_logger("test").info("observability.ready", component="gateway")

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["event"] == "observability.ready"
    assert payload["component"] == "gateway"
    assert payload["level"] == "info"
