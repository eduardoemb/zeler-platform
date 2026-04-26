# ruff: noqa: S105

from __future__ import annotations

import pytest
from pydantic import SecretStr

from zeler_sheets.sheets_config import SheetsSettings


def test_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://sheets.test/oauth/google/callback")
    monkeypatch.setenv("KMS_PROJECT_ID", "zeler-dev")
    monkeypatch.setenv("KMS_KEYRING", "custom-keyring")
    monkeypatch.setenv("KMS_GOOGLE_TOKENS_KEY", "custom-google-key")
    monkeypatch.setenv("KMS_LOCATION", "europe-west1")
    monkeypatch.setenv("GOOGLE_OAUTH_AUTHORIZE_URL", "https://accounts.example/auth")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_URL", "https://oauth.example/token")
    monkeypatch.setenv("GOOGLE_SHEETS_SCOPE", "https://scope.example/sheets")

    settings = SheetsSettings()  # type: ignore[call-arg]

    assert settings.google_oauth_client_id == "google-client-id"
    assert isinstance(settings.google_oauth_client_secret, SecretStr)
    assert settings.google_oauth_client_secret.get_secret_value() == "google-client-secret"
    assert settings.google_oauth_redirect_uri == "https://sheets.test/oauth/google/callback"
    assert settings.kms_project_id == "zeler-dev"
    assert settings.kms_keyring == "custom-keyring"
    assert settings.kms_google_tokens_key == "custom-google-key"
    assert settings.kms_location == "europe-west1"
    assert settings.google_oauth_authorize_url == "https://accounts.example/auth"
    assert settings.google_oauth_token_url == "https://oauth.example/token"
    assert settings.google_sheets_scope == "https://scope.example/sheets"


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://sheets.test/oauth/google/callback")
    monkeypatch.setenv("KMS_PROJECT_ID", "zeler-dev")
    monkeypatch.delenv("KMS_KEYRING", raising=False)
    monkeypatch.delenv("KMS_GOOGLE_TOKENS_KEY", raising=False)
    monkeypatch.delenv("KMS_LOCATION", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_AUTHORIZE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_URL", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_SCOPE", raising=False)

    settings = SheetsSettings()  # type: ignore[call-arg]

    assert settings.kms_keyring == "zeler-platform"
    assert settings.kms_google_tokens_key == "google-tokens"
    assert settings.kms_location == "us-central1"
    assert settings.google_oauth_authorize_url == "https://accounts.google.com/o/oauth2/v2/auth"
    assert settings.google_oauth_token_url == "https://oauth2.googleapis.com/token"
    assert settings.google_sheets_scope == "https://www.googleapis.com/auth/spreadsheets"
