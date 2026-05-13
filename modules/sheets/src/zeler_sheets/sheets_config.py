from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SheetsSettings(BaseSettings):
    google_oauth_client_id: str
    google_oauth_client_secret: SecretStr
    google_oauth_redirect_uri: str
    kms_keyring: str = "zeler-platform"
    kms_google_tokens_key: str = "google-tokens"
    kms_project_id: str
    kms_location: str = "us-central1"
    google_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105
    google_sheets_scope: str = "https://www.googleapis.com/auth/spreadsheets"
    extension_token_pepper: SecretStr | None = None

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)


@lru_cache(maxsize=1)
def get_settings() -> SheetsSettings:
    return SheetsSettings()  # type: ignore[call-arg]
