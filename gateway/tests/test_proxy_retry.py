from __future__ import annotations

import httpx
import pytest
import respx

from zeler_gateway.proxy.retry import send_single_attempt, send_with_retry


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay_s: float) -> None:
        self.calls.append(delay_s)


@pytest.mark.asyncio
async def test_single_attempt_contract_never_consumes_hidden_gateway_retry() -> None:
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/MLA123")
        with respx.mock(assert_all_called=False) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
                side_effect=[httpx.Response(502), httpx.Response(200, json={"id": "unexpected"})]
            )
            response = await send_single_attempt(client, request)

    assert response.status_code == 502
    assert response.headers["X-Zeler-Upstream-Attempts"] == "1"
    assert upstream.call_count == 1


@pytest.mark.asyncio
async def test_502_then_200_surfaces_200() -> None:
    sleep = SleepRecorder()
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/MLA123")
        with respx.mock(assert_all_called=True) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
                side_effect=[
                    httpx.Response(502),
                    httpx.Response(200, json={"id": "MLA123"}),
                ]
            )

            response = await send_with_retry(client, request, sleep_fn=sleep)

    assert response.status_code == 200
    assert response.json() == {"id": "MLA123"}
    assert upstream.call_count == 2


@pytest.mark.asyncio
async def test_404_not_retried() -> None:
    sleep = SleepRecorder()
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/NOPE")
        with respx.mock(assert_all_called=True) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/NOPE").mock(
                return_value=httpx.Response(404)
            )

            response = await send_with_retry(client, request, sleep_fn=sleep)

    assert response.status_code == 404
    assert upstream.call_count == 1
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_429_respects_retry_after() -> None:
    sleep = SleepRecorder()
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/MLA123")
        with respx.mock(assert_all_called=True) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
                side_effect=[
                    httpx.Response(429, headers={"Retry-After": "1"}),
                    httpx.Response(200, json={"id": "MLA123"}),
                ]
            )

            response = await send_with_retry(client, request, sleep_fn=sleep)

    assert response.status_code == 200
    assert upstream.call_count == 2
    assert sleep.calls == pytest.approx([1.0])


@pytest.mark.asyncio
async def test_timeout_retried_then_succeeds() -> None:
    sleep = SleepRecorder()
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/MLA123")
        with respx.mock(assert_all_called=True) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
                side_effect=[
                    httpx.ConnectError("connection failed"),
                    httpx.Response(200, json={"id": "MLA123"}),
                ]
            )

            response = await send_with_retry(client, request, sleep_fn=sleep)

    assert response.status_code == 200
    assert upstream.call_count == 2


@pytest.mark.asyncio
async def test_exhausts_attempts_surfaces_last_5xx() -> None:
    sleep = SleepRecorder()
    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", "https://api.mercadolibre.com/items/MLA123")
        with respx.mock(assert_all_called=True) as respx_mock:
            upstream = respx_mock.get("https://api.mercadolibre.com/items/MLA123").mock(
                return_value=httpx.Response(503)
            )

            response = await send_with_retry(client, request, sleep_fn=sleep)

    assert response.status_code == 503
    assert upstream.call_count == 3
