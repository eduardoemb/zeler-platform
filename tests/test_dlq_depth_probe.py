from __future__ import annotations

import json

import pytest
from infra.monitoring.dlq_depth import fetch_dlq_depth, main


class FakeHttpClient:
    def __init__(self, payload: dict[str, int]) -> None:
        self.payload = payload
        self.requests: list[tuple[str, str]] = []

    async def get(self, url: str) -> object:
        self.requests.append(("GET", url))
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload: dict[str, int]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, int]:
        return self._payload


@pytest.mark.asyncio
async def test_fetch_returns_depth_from_management_response() -> None:
    depth = await fetch_dlq_depth(
        "https://rabbit.example",
        "/",
        "zeler.repricer.items.dlq",
        http_client=FakeHttpClient({"messages": 7}),
    )

    assert depth == 7


@pytest.mark.asyncio
async def test_fetch_does_not_mutate_broker() -> None:
    client = FakeHttpClient({"messages": 3})

    await fetch_dlq_depth("https://rabbit.example", "prod/vhost", "queue.dlq", http_client=client)

    assert [method for method, _url in client.requests] == ["GET"]


def test_cli_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        ["--management-url", "fake://rabbit", "--vhost", "/", "--queue", "queue.dlq"],
        fetcher=lambda *_args: 11,
        now=lambda: "2026-05-01T00:00:00Z",
    )

    assert json.loads(capsys.readouterr().out) == {
        "queue": "queue.dlq",
        "depth": 11,
        "checked_at": "2026-05-01T00:00:00Z",
    }
