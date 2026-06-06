"""KMS envelope encryption for MercadoLibre tokens.

Local development uses Google Application Default Credentials. Run:
    gcloud auth application-default login

Production Cloud Run should execute as gateway-sa with Cloud KMS
Encrypter/Decrypter on the meli-tokens symmetric key. Never log plaintext
tokens, DEKs, or wrapped DEKs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, cast

from cachetools import TTLCache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zeler_gateway.config import get_settings


class KmsClient(Protocol):
    def encrypt(self, request: dict[str, bytes | str]) -> Any: ...

    def decrypt(self, request: dict[str, bytes | str]) -> Any: ...


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    nonce: bytes
    dek_wrapped: bytes
    kms_key_version: str


_DEK_CACHE: TTLCache[str, tuple[bytes, bytes]] = TTLCache(maxsize=1000, ttl=300)
_KMS_CLIENT: KmsClient | None = None


def reset_dek_cache() -> None:
    _DEK_CACHE.clear()


def set_kms_client(client: KmsClient | None) -> None:
    global _KMS_CLIENT
    _KMS_CLIENT = client


def _kms_client() -> KmsClient:
    global _KMS_CLIENT
    if _KMS_CLIENT is None:
        from google.cloud import kms_v1

        _KMS_CLIENT = kms_v1.KeyManagementServiceClient()
    return _KMS_CLIENT


def _kms_key_name() -> str:
    settings = get_settings()
    return (
        f"projects/{settings.kms_project_id}/locations/{settings.kms_location}/"
        f"keyRings/{settings.kms_keyring}/cryptoKeys/{settings.kms_meli_tokens_key}"
    )


def _cache_key(account_id: str) -> str:
    return f"meli-token-dek:{account_id}"


def _get_or_create_dek(account_id: str) -> tuple[bytes, bytes, str]:
    key = _cache_key(account_id)
    cached = _DEK_CACHE.get(key)
    if cached is not None:
        dek, dek_wrapped = cached
        return dek, dek_wrapped, _kms_key_name()

    dek = os.urandom(32)
    response = _kms_client().encrypt(request={"name": _kms_key_name(), "plaintext": dek})
    dek_wrapped = cast(bytes, response.ciphertext)
    kms_key_version = cast(str, getattr(response, "name", _kms_key_name()))
    _DEK_CACHE[key] = (dek, dek_wrapped)
    return dek, dek_wrapped, kms_key_version


def encrypt_token(plaintext: str, account_id: str) -> EncryptedToken:
    dek, dek_wrapped, kms_key_version = _get_or_create_dek(account_id)
    nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), account_id.encode("utf-8"))
    return EncryptedToken(
        ciphertext=ciphertext,
        nonce=nonce,
        dek_wrapped=dek_wrapped,
        kms_key_version=kms_key_version,
    )


async def decrypt_token(token: EncryptedToken, account_id: str) -> str:
    key = _cache_key(account_id)
    cached = _DEK_CACHE.get(key)
    if cached is None or cached[1] != token.dek_wrapped:
        response = _kms_client().decrypt(
            request={"name": _kms_key_name(), "ciphertext": token.dek_wrapped}
        )
        dek = cast(bytes, response.plaintext)
        _DEK_CACHE[key] = (dek, token.dek_wrapped)
    else:
        dek = cached[0]

    plaintext = AESGCM(dek).decrypt(token.nonce, token.ciphertext, account_id.encode("utf-8"))
    return plaintext.decode("utf-8")
