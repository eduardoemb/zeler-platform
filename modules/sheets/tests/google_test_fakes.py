from __future__ import annotations

import pytest


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
def fake_kms_client(monkeypatch: pytest.MonkeyPatch) -> FakeKmsClient:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://sheets.test/oauth/google/callback")
    monkeypatch.setenv("KMS_PROJECT_ID", "zeler-dev")
    from zeler_sheets.google_token_encryption import reset_dek_cache, set_kms_client

    client = FakeKmsClient()
    reset_dek_cache()
    set_kms_client(client)
    return client
