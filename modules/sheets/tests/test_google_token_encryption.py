from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag
from google_test_fakes import FakeKmsClient, fake_kms_client

from zeler_sheets.google_token_encryption import decrypt_token, encrypt_token

__all__ = ["fake_kms_client"]


@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip(fake_kms_client: FakeKmsClient) -> None:
    encrypted = encrypt_token("google-access-token", account_id="seller-1")

    decrypted = await decrypt_token(encrypted, account_id="seller-1")

    assert decrypted == "google-access-token"
    assert encrypted.ciphertext != b"google-access-token"
    assert len(encrypted.nonce) == 12
    assert encrypted.dek_wrapped.startswith(b"wrapped:")
    assert encrypted.kms_key_version == "projects/test/cryptoKeyVersions/1"
    assert fake_kms_client.encrypt_calls == 1


@pytest.mark.asyncio
async def test_dek_cache_reused(fake_kms_client: FakeKmsClient) -> None:
    first = encrypt_token("first-google-token", account_id="seller-1")
    second = encrypt_token("second-google-token", account_id="seller-1")

    assert fake_kms_client.encrypt_calls == 1
    assert first.dek_wrapped == second.dek_wrapped

    await decrypt_token(first, account_id="seller-1")
    await decrypt_token(second, account_id="seller-1")

    assert fake_kms_client.decrypt_calls == 0


@pytest.mark.asyncio
async def test_aad_enforcement(fake_kms_client: FakeKmsClient) -> None:
    encrypted = encrypt_token("seller-bound-token", account_id="seller-1")

    try:
        await decrypt_token(encrypted, account_id="seller-2")
    except InvalidTag:
        pass
    else:  # pragma: no cover - assertion branch documents the expected failure
        raise AssertionError("decrypting with the wrong seller_id must fail")
