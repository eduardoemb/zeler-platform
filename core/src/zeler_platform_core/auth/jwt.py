"""KMS-signed internal JWTs for module-to-gateway authentication."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from cachetools import TTLCache
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

PLATFORM_JWT_KEY_VERSION = (
    "projects/zeler-platform-dev/locations/us-central1/keyRings/zeler-platform/"
    "cryptoKeys/platform-jwt/cryptoKeyVersions/1"
)
JWT_HEADER = {"alg": "ES256", "kid": "platform-jwt:1", "typ": "JWT"}
JWT_AUDIENCE: Literal["gateway"] = "gateway"
ES256_COORDINATE_SIZE = 32


class InvalidJWTError(Exception):
    """Raised when an internal JWT is malformed or has an invalid signature."""


class ExpiredJWTError(InvalidJWTError):
    """Raised when an internal JWT has expired."""


class WrongAudienceError(InvalidJWTError):
    """Raised when an internal JWT is not intended for the gateway."""


@dataclass(frozen=True)
class ModuleClaims:
    module_id: str
    seller_id: int
    iss: str
    aud: Literal["gateway"]
    iat: int
    exp: int


class KmsSigningClient(Protocol):
    def asymmetric_sign(self, request: dict[str, Any]) -> Any: ...

    def get_public_key(self, request: dict[str, str]) -> Any: ...


_KMS_CLIENT: KmsSigningClient | None = None
_PUBLIC_KEY_CACHE: TTLCache[str, EllipticCurvePublicKey] = TTLCache(maxsize=1, ttl=300)


def set_kms_client(client: KmsSigningClient | None) -> None:
    global _KMS_CLIENT
    _KMS_CLIENT = client
    reset_jwt_cache()


def reset_jwt_cache() -> None:
    _PUBLIC_KEY_CACHE.clear()


def _kms_client() -> KmsSigningClient:
    global _KMS_CLIENT
    if _KMS_CLIENT is None:
        from google.cloud import kms

        _KMS_CLIENT = kms.KeyManagementServiceClient()
    return _KMS_CLIENT


def mint_module_jwt(module_id: str, seller_id: int, ttl_s: int = 60) -> str:
    now = int(time.time())
    payload = {
        "iss": f"module:{module_id}",
        "aud": JWT_AUDIENCE,
        "sub": str(seller_id),
        "iat": now,
        "exp": now + ttl_s,
    }
    signing_input = _signing_input(JWT_HEADER, payload)
    digest = hashlib.sha256(signing_input).digest()
    response = _kms_client().asymmetric_sign(
        request={"name": PLATFORM_JWT_KEY_VERSION, "digest": {"sha256": digest}}
    )
    jose_signature = der_to_jose_es256(cast(bytes, response.signature))
    return b".".join([signing_input, _b64url_encode(jose_signature)]).decode("ascii")


def verify_module_jwt(token: str) -> ModuleClaims:
    signing_input, payload, signature = _parse_token(token)
    _verify_signature(signing_input, signature)

    if payload.get("aud") != JWT_AUDIENCE:
        raise WrongAudienceError("JWT audience must be gateway")

    exp = _int_claim(payload, "exp")
    if exp <= int(time.time()):
        raise ExpiredJWTError("JWT has expired")

    iss = _str_claim(payload, "iss")
    if not iss.startswith("module:") or len(iss) == len("module:"):
        raise InvalidJWTError("JWT issuer must be module:<module_id>")

    seller_id = int(_str_claim(payload, "sub"))
    return ModuleClaims(
        module_id=iss.removeprefix("module:"),
        seller_id=seller_id,
        iss=iss,
        aud="gateway",
        iat=_int_claim(payload, "iat"),
        exp=exp,
    )


def der_to_jose_es256(der_signature: bytes) -> bytes:
    r, s = decode_dss_signature(der_signature)
    return r.to_bytes(ES256_COORDINATE_SIZE, "big") + s.to_bytes(ES256_COORDINATE_SIZE, "big")


def jose_to_der_es256(jose_signature: bytes) -> bytes:
    if len(jose_signature) != ES256_COORDINATE_SIZE * 2:
        raise InvalidJWTError("ES256 signature must be 64 bytes")
    r = int.from_bytes(jose_signature[:ES256_COORDINATE_SIZE], "big")
    s = int.from_bytes(jose_signature[ES256_COORDINATE_SIZE:], "big")
    return encode_dss_signature(r, s)


def _signing_input(header: dict[str, Any], payload: dict[str, Any]) -> bytes:
    return b".".join(
        [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )


def _parse_token(token: str) -> tuple[bytes, dict[str, Any], bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidJWTError("JWT must have three segments")

    header = json.loads(_b64url_decode(parts[0]))
    if header != JWT_HEADER:
        raise InvalidJWTError("JWT header is not supported")

    payload = json.loads(_b64url_decode(parts[1]))
    if not isinstance(payload, dict):
        raise InvalidJWTError("JWT payload must be an object")

    return f"{parts[0]}.{parts[1]}".encode("ascii"), payload, _b64url_decode(parts[2])


def _verify_signature(signing_input: bytes, jose_signature: bytes) -> None:
    digest = hashlib.sha256(signing_input).digest()
    try:
        _public_key().verify(
            jose_to_der_es256(jose_signature),
            digest,
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except InvalidSignature as exc:
        raise InvalidJWTError("JWT signature is invalid") from exc


def _public_key() -> EllipticCurvePublicKey:
    cached = _PUBLIC_KEY_CACHE.get(PLATFORM_JWT_KEY_VERSION)
    if cached is not None:
        return cached

    response = _kms_client().get_public_key(request={"name": PLATFORM_JWT_KEY_VERSION})
    pem = cast(str, response.pem).encode("ascii")
    loaded = serialization.load_pem_public_key(pem)
    if not isinstance(loaded, EllipticCurvePublicKey):
        raise InvalidJWTError("KMS public key is not an EC key")
    _PUBLIC_KEY_CACHE[PLATFORM_JWT_KEY_VERSION] = loaded
    return loaded


def _int_claim(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise InvalidJWTError(f"JWT claim {key} must be an integer")
    return value


def _str_claim(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise InvalidJWTError(f"JWT claim {key} must be a string")
    return value


def _b64url_encode(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}")
