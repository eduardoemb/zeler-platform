from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from zeler_platform_core.clients.meli_gateway_client import MeliGatewayClient


@pytest.mark.parametrize(
    ("header_value", "expected_seconds"),
    [
        ("5", 5),
        (None, 5),
        ("0", 1),
        ("120", 30),
        ("abcdef", 5),
    ],
)
def test_parse_retry_after_numeric_missing_and_invalid_values(
    header_value: str | None,
    expected_seconds: int,
) -> None:
    assert MeliGatewayClient._parse_retry_after(header_value) == expected_seconds


def test_parse_retry_after_http_date_caps_delta_to_30_seconds() -> None:
    future = datetime.now(UTC) + timedelta(seconds=120)
    retry_after = format_datetime(future, usegmt=True)

    assert MeliGatewayClient._parse_retry_after(retry_after) == 30
