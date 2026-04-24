from __future__ import annotations

from dataclasses import replace

import pytest

from zeler_gateway.tokens.encryption import (
    decrypt_token,
    encrypt_token,
    reset_dek_cache,
    set_kms_client,
)


class FakeKmsResponse:
    def __init__(
        self,
        ciphertext: bytes | None = None,
        plaintext: bytes | None = None,
        name: str = "key-version-1",
    ) -> None:
        self.ciphertext = ciphertext
        self.plaintext = plaintext
        self.name = name


class FakeKmsClient:
    def __init__(self) -> None:
        self.encrypt_calls = 0
        self.decrypt_calls = 0
        self.wrapped_to_plaintext: dict[bytes, bytes] = {}

    def encrypt(self, request: dict[str, bytes | str]) -> FakeKmsResponse:
        self.encrypt_calls += 1
        plaintext = request["plaintext"]
        assert isinstance(plaintext, bytes)
        wrapped = b"wrapped:" + plaintext
        self.wrapped_to_plaintext[wrapped] = plaintext
        return FakeKmsResponse(ciphertext=wrapped, name="projects/test/cryptoKeyVersions/1")

    def decrypt(self, request: dict[str, bytes | str]) -> FakeKmsResponse:
        self.decrypt_calls += 1
        ciphertext = request["ciphertext"]
        assert isinstance(ciphertext, bytes)
        return FakeKmsResponse(plaintext=self.wrapped_to_plaintext[ciphertext])


@pytest.fixture
def fake_kms_client() -> FakeKmsClient:
    client = FakeKmsClient()
    reset_dek_cache()
    set_kms_client(client)
    return client


@pytest.mark.asyncio
async def test_encrypt_decrypt_roundtrip(fake_kms_client: FakeKmsClient) -> None:
    encrypted = encrypt_token("meli-access-token", account_id="account-1")

    decrypted = await decrypt_token(encrypted, account_id="account-1")

    assert decrypted == "meli-access-token"
    assert encrypted.ciphertext != b"meli-access-token"
    assert len(encrypted.nonce) == 12
    assert encrypted.dek_wrapped.startswith(b"wrapped:")
    assert encrypted.kms_key_version == "projects/test/cryptoKeyVersions/1"
    assert fake_kms_client.encrypt_calls == 1


@pytest.mark.asyncio
async def test_dek_cache_hit_no_kms_call(fake_kms_client: FakeKmsClient) -> None:
    first = encrypt_token("first-token", account_id="account-1")
    second = encrypt_token("second-token", account_id="account-1")

    assert fake_kms_client.encrypt_calls == 1
    assert first.dek_wrapped == second.dek_wrapped

    await decrypt_token(first, account_id="account-1")
    await decrypt_token(second, account_id="account-1")

    assert fake_kms_client.decrypt_calls == 0


@pytest.mark.asyncio
async def test_different_accounts_use_different_deks(fake_kms_client: FakeKmsClient) -> None:
    account_a = encrypt_token("same-token", account_id="account-a")
    account_b = encrypt_token("same-token", account_id="account-b")

    assert account_a.ciphertext != account_b.ciphertext
    assert account_a.dek_wrapped != account_b.dek_wrapped
    assert await decrypt_token(account_a, account_id="account-a") == "same-token"
    assert await decrypt_token(account_b, account_id="account-b") == "same-token"


@pytest.mark.asyncio
async def test_decrypt_cache_miss_unwraps_dek(fake_kms_client: FakeKmsClient) -> None:
    encrypted = encrypt_token("token", account_id="account-1")
    reset_dek_cache()
    set_kms_client(fake_kms_client)

    decrypted = await decrypt_token(replace(encrypted), account_id="account-1")

    assert decrypted == "token"
    assert fake_kms_client.decrypt_calls == 1
