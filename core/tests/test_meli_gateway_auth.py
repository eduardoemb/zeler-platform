from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, cast

import pytest
from core.tests.test_jwt import FakeKmsSigningClient, FakeKmsSignResponse

from zeler_platform_core.auth.jwt import reset_jwt_cache, set_kms_client
from zeler_platform_core.auth.meli_gateway_auth import KMSSignError, MeliGatewayAuth


class CountingKmsSigningClient(FakeKmsSigningClient):
    def __init__(self) -> None:
        super().__init__()
        self.sign_calls = 0

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        self.sign_calls += 1
        return super().asymmetric_sign(request)


class FailingKmsSigningClient(FakeKmsSigningClient):
    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        raise PermissionError("cloudkms.cryptoKeyVersions.useToSign denied")


@pytest.fixture(autouse=True)
def reset_kms_client() -> None:
    set_kms_client(None)
    reset_jwt_cache()


@pytest.mark.asyncio
async def test_get_token_for_seller_reuses_cached_token_until_cache_ttl_expires() -> None:
    kms_client = CountingKmsSigningClient()
    now = 1_000.0
    auth = MeliGatewayAuth(
        "sheets",
        kms_client,
        jwt_ttl_s=60,
        cache_ttl_s=50,
        clock=lambda: now,
    )

    first_token = await auth.get_token_for_seller(82453304)
    second_token = await auth.get_token_for_seller(82453304)

    assert second_token == first_token
    assert kms_client.sign_calls == 1

    other_seller_token = await auth.get_token_for_seller(99999999)

    assert other_seller_token != first_token
    assert kms_client.sign_calls == 2

    now = 1_051.0
    refreshed_token = await auth.get_token_for_seller(82453304)

    assert refreshed_token != first_token
    assert kms_client.sign_calls == 3


@pytest.mark.asyncio
async def test_get_token_for_seller_serializes_concurrent_mints_per_seller() -> None:
    kms_client = CountingKmsSigningClient()
    auth = MeliGatewayAuth(
        "sheets",
        kms_client,
        jwt_ttl_s=60,
        cache_ttl_s=50,
    )

    tokens = await asyncio.gather(*(auth.get_token_for_seller(82453304) for _ in range(10)))

    assert tokens == [tokens[0]] * 10
    assert kms_client.sign_calls == 1
    assert 82453304 in auth._locks


@pytest.mark.asyncio
async def test_get_token_for_seller_propagates_kms_sign_failure_without_caching() -> None:
    auth = MeliGatewayAuth("sheets", FailingKmsSigningClient())

    with pytest.raises(KMSSignError):
        await auth.get_token_for_seller(82453304)

    assert 82453304 not in auth._cache


@pytest.mark.asyncio
async def test_get_token_for_seller_returns_es256_jwt_with_module_and_seller_claims() -> None:
    auth = MeliGatewayAuth("sheets", CountingKmsSigningClient(), jwt_ttl_s=60)

    token = await auth.get_token_for_seller(82453304)
    header, payload = _decode_unverified_jwt(token)

    assert header == {"alg": "ES256", "kid": "platform-jwt:1", "typ": "JWT"}
    assert payload["module_id"] == "sheets"
    assert payload["iss"] == "module:sheets"
    assert payload["aud"] == "gateway"
    assert payload["sub"] == "82453304"
    assert payload["exp"] - payload["iat"] == 60


def _decode_unverified_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header, payload, _signature = token.split(".")
    return _b64url_json(header), _b64url_json(payload)


def _b64url_json(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    return cast(dict[str, Any], json.loads(base64.urlsafe_b64decode(f"{value}{padding}")))
