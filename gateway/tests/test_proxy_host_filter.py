from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from starlette.datastructures import Headers

from zeler_gateway.proxy.router import _upstream_headers


def test_upstream_headers_strips_inbound_host_header() -> None:
    request = SimpleNamespace(
        headers=Headers(
            {
                "Host": "gateway:8080",
                "User-Agent": "zeler-worker/1.0",
                "Content-Type": "application/json",
            }
        )
    )

    upstream_access_token = "meli-" + "token"
    headers = _upstream_headers(cast(Any, request), access_token=upstream_access_token)

    assert "host" not in {key.lower() for key in headers}
    assert headers["user-agent"] == "zeler-worker/1.0"
    assert headers["content-type"] == "application/json"
    assert headers["Authorization"] == f"Bearer {upstream_access_token}"
