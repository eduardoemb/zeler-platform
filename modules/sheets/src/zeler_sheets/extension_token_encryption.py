"""KMS envelope encryption for Sheets/ZelerData extension-token secrets.

Formula validation continues to use the persisted token hash. This module only
protects the optional recoverable secret used by token-management reveal flows.
Never log plaintext tokens, DEKs, or wrapped DEKs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from zeler_sheets.sheets_config import SheetsSettings


class KmsClient(Protocol):
    def encrypt(self, request: dict[str, bytes | str]) -> Any: ...

    def decrypt(self, request: dict[str, bytes | str]) -> Any: ...


TOKEN_SECRET_CIPHERTEXT_FIELD = "token_secret_ciphertext"  # noqa: S105 - field name.
TOKEN_SECRET_DEK_WRAPPED_FIELD = "token_secret_dek_wrapped"  # noqa: S105 - field name.
TOKEN_SECRET_NONCE_FIELD = "token_secret_nonce"  # noqa: S105 - field name.
TOKEN_SECRET_KMS_KEY_VERSION_FIELD = "token_secret_kms_key_version"  # noqa: S105 - field name.
TOKEN_SECRET_FIELDS = frozenset(
    {
        TOKEN_SECRET_CIPHERTEXT_FIELD,
        TOKEN_SECRET_DEK_WRAPPED_FIELD,
        TOKEN_SECRET_NONCE_FIELD,
        TOKEN_SECRET_KMS_KEY_VERSION_FIELD,
    }
)


class ExtensionTokenSecretCipher(Protocol):
    def encrypt(
        self,
        plaintext: str,
        *,
        owner_user_id: str,
        token_id: str,
    ) -> dict[str, bytes | str]: ...

    async def decrypt(
        self,
        doc: dict[str, Any],
        *,
        owner_user_id: str,
        token_id: str,
    ) -> str: ...


@dataclass(frozen=True)
class EncryptedExtensionTokenSecret:
    ciphertext: bytes
    nonce: bytes
    dek_wrapped: bytes
    kms_key_version: str

    def to_document(self) -> dict[str, bytes | str]:
        return {
            TOKEN_SECRET_CIPHERTEXT_FIELD: self.ciphertext,
            TOKEN_SECRET_DEK_WRAPPED_FIELD: self.dek_wrapped,
            TOKEN_SECRET_NONCE_FIELD: self.nonce,
            TOKEN_SECRET_KMS_KEY_VERSION_FIELD: self.kms_key_version,
        }


class KmsExtensionTokenSecretCipher:
    def __init__(self, *, kms_client: KmsClient, kms_key_name: str) -> None:
        self._kms_client = kms_client
        self._kms_key_name = kms_key_name

    def encrypt(
        self,
        plaintext: str,
        *,
        owner_user_id: str,
        token_id: str,
    ) -> dict[str, bytes | str]:
        dek = os.urandom(32)
        response = self._kms_client.encrypt(request={"name": self._kms_key_name, "plaintext": dek})
        dek_wrapped = cast(bytes, response.ciphertext)
        kms_key_version = cast(str, getattr(response, "name", self._kms_key_name))
        nonce = os.urandom(12)
        aad = _aad(owner_user_id=owner_user_id, token_id=token_id)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return EncryptedExtensionTokenSecret(
            ciphertext=ciphertext,
            nonce=nonce,
            dek_wrapped=dek_wrapped,
            kms_key_version=kms_key_version,
        ).to_document()

    async def decrypt(
        self,
        doc: dict[str, Any],
        *,
        owner_user_id: str,
        token_id: str,
    ) -> str:
        response = self._kms_client.decrypt(
            request={
                "name": self._kms_key_name,
                "ciphertext": cast(bytes, doc[TOKEN_SECRET_DEK_WRAPPED_FIELD]),
            }
        )
        dek = cast(bytes, response.plaintext)
        plaintext = AESGCM(dek).decrypt(
            cast(bytes, doc[TOKEN_SECRET_NONCE_FIELD]),
            cast(bytes, doc[TOKEN_SECRET_CIPHERTEXT_FIELD]),
            _aad(owner_user_id=owner_user_id, token_id=token_id),
        )
        return plaintext.decode("utf-8")


def build_extension_token_cipher(
    *,
    kms_client: KmsClient,
    settings: SheetsSettings,
) -> KmsExtensionTokenSecretCipher:
    key_name = _kms_key_name(settings)
    return KmsExtensionTokenSecretCipher(kms_client=kms_client, kms_key_name=key_name)


def _kms_key_name(settings: SheetsSettings) -> str:
    crypto_key = settings.kms_extension_tokens_key or settings.kms_google_tokens_key
    return (
        f"projects/{settings.kms_project_id}/locations/{settings.kms_location}/"
        f"keyRings/{settings.kms_keyring}/cryptoKeys/{crypto_key}"
    )


def _aad(*, owner_user_id: str, token_id: str) -> bytes:
    return f"sheets_extension_token:{owner_user_id}:{token_id}".encode()
