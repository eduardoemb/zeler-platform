from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Generator
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from zeler_platform_core.auth.jwt import (
    ExpiredJWTError,
    WrongAudienceError,
    der_to_jose_es256,
    mint_module_jwt,
    mint_state_jwt,
    reset_jwt_cache,
    set_kms_client,
    verify_module_jwt,
    verify_state_jwt,
)


class FakeKmsSignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class FakeKmsPublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeKmsSigningClient:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        digest = request["digest"]
        sha256_digest = digest["sha256"]
        signature = self.private_key.sign(
            sha256_digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return FakeKmsSignResponse(signature)

    def get_public_key(self, request: dict[str, str]) -> FakeKmsPublicKeyResponse:
        pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return FakeKmsPublicKeyResponse(pem.decode("ascii"))


@pytest.fixture(autouse=True)
def fake_kms() -> Generator[FakeKmsSigningClient]:
    client = FakeKmsSigningClient()
    set_kms_client(client)
    reset_jwt_cache()
    yield client
    set_kms_client(None)
    reset_jwt_cache()


def test_mint_verify_roundtrip() -> None:
    token = mint_module_jwt("repricer", seller_id=123456789, ttl_s=60)

    claims = verify_module_jwt(token)

    assert claims.module_id == "repricer"
    assert claims.seller_id == 123456789
    assert claims.iss == "module:repricer"
    assert claims.aud == "gateway"
    assert claims.exp > claims.iat


def test_expired_jwt_raises() -> None:
    token = mint_module_jwt("repricer", seller_id=123456789, ttl_s=-1)

    with pytest.raises(ExpiredJWTError):
        verify_module_jwt(token)


def test_wrong_aud_raises() -> None:
    now = int(time.time())
    token = _mint_raw_token(
        {
            "iss": "module:repricer",
            "aud": "other",
            "sub": "123456789",
            "iat": now,
            "exp": now + 60,
        }
    )

    with pytest.raises(WrongAudienceError):
        verify_module_jwt(token)


def test_mint_verify_state_jwt_roundtrip() -> None:
    token = mint_state_jwt("platform-user-123", ttl_s=600)

    claims = verify_state_jwt(token)

    assert claims.platform_user_id == "platform-user-123"
    assert claims.exp - claims.iat == 600


def test_state_jwt_rejects_module_audience() -> None:
    token = mint_module_jwt("repricer", seller_id=123456789, ttl_s=60)

    with pytest.raises(WrongAudienceError):
        verify_state_jwt(token)


def _mint_raw_token(payload: dict[str, Any]) -> str:
    header = {"alg": "ES256", "kid": "platform-jwt:1", "typ": "JWT"}
    signing_input = b".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    response = mint_module_jwt.__globals__["_kms_client"]().asymmetric_sign(
        request={
            "name": mint_module_jwt.__globals__["PLATFORM_JWT_KEY_VERSION"],
            "digest": {"sha256": hashlib.sha256(signing_input).digest()},
        }
    )
    return b".".join([signing_input, _b64url(der_to_jose_es256(response.signature))]).decode(
        "ascii"
    )


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")
