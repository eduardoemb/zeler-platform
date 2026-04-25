from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["production", "test", "development"] = Field(
        default="production", alias="ENVIRONMENT"
    )
    otel_enabled: bool = Field(default=True, alias="OTEL_ENABLED")
    otel_metrics_enabled: bool = Field(default=False, alias="OTEL_METRICS_ENABLED")
    gcp_project_id: str = Field(default="zeler-platform-dev", alias="GCP_PROJECT_ID")
    mongo_uri: str = Field(
        default="mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/zeler_platform_dev?replicaSet=rs0-dev&directConnection=true&authSource=admin",
        alias="MONGO_URI",
    )
    mongo_db: str = Field(default="zeler_platform_dev", alias="MONGO_DB")
    meli_client_id: str = Field(default="", alias="MELI_CLIENT_ID")
    meli_client_secret: SecretStr = Field(default=SecretStr(""), alias="MELI_CLIENT_SECRET")
    meli_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/callback", alias="MELI_REDIRECT_URI"
    )
    oauth_success_url: str = Field(
        default="https://app.zeler.local/accounts/linked", alias="OAUTH_SUCCESS_URL"
    )
    # Deprecated/unused: OAuth state JWTs are now KMS-signed ES256 via core.auth.jwt.
    # Kept temporarily so existing environments with STATE_SIGNING_SECRET keep validating.
    state_signing_secret: SecretStr = Field(
        default=SecretStr("dev-only-insecure-secret-change-me"), alias="STATE_SIGNING_SECRET"
    )
    state_ttl_seconds: int = Field(default=600, alias="STATE_TTL_SECONDS")
    kms_project_id: str = Field(default="zeler-platform-dev", alias="KMS_PROJECT_ID")
    kms_location: str = Field(default="us-central1", alias="KMS_LOCATION")
    kms_keyring: str = Field(default="zeler-platform", alias="KMS_KEYRING")
    kms_meli_tokens_key: str = Field(default="meli-tokens", alias="KMS_MELI_TOKENS_KEY")
    kms_platform_jwt_key: str = Field(default="platform-jwt", alias="KMS_PLATFORM_JWT_KEY")
    use_secret_manager: bool = Field(default=False, alias="USE_SECRET_MANAGER")
    meli_allowed_ips: str = Field(default="", alias="MELI_ALLOWED_IPS")
    meli_webhook_hmac_secret: SecretStr = Field(
        default=SecretStr(""), alias="MELI_WEBHOOK_HMAC_SECRET"
    )
    rabbitmq_url: str = Field(default="", alias="RABBITMQ_URL")
    rabbitmq_events_exchange: str = Field(default="meli.events", alias="RABBITMQ_EVENTS_EXCHANGE")

    @field_validator("meli_client_id", "meli_redirect_uri")
    @classmethod
    def _load_secret_reference(cls, value: str) -> str:
        return value

    @model_validator(mode="after")
    def _validate_mongo_uri_path_matches_mongo_db(self) -> Self:
        if not self.mongo_db or "mongo_db" not in self.model_fields_set:
            return self

        uri_path = urlsplit(self.mongo_uri).path.lstrip("/")
        if uri_path and uri_path != self.mongo_db:
            msg = f"MONGO_URI path '{uri_path}' does not match MONGO_DB '{self.mongo_db}'"
            raise ValueError(msg)

        return self


def load_secret(secret_id: str, *, project_id: str) -> str:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton for long-running paths (lifespan, background jobs).

    NOTE: Request handlers that may observe freshly-monkeypatched env vars
    (typically OAuth endpoints exercised under `pytest` + `monkeypatch.setenv`)
    MUST instantiate `Settings()` directly instead of calling this function.
    The cache is intentionally bypassed in those hot paths so per-request env
    reads remain honest. Do NOT reintroduce `get_settings()` into endpoint
    code without also moving the lru_cache behind a test-aware flag.
    """
    settings = Settings()
    if not settings.use_secret_manager:
        return settings

    return settings.model_copy(
        update={
            "meli_client_id": load_secret("meli-client-id", project_id=settings.kms_project_id),
            "meli_client_secret": SecretStr(
                load_secret("meli-client-secret", project_id=settings.kms_project_id)
            ),
        }
    )
