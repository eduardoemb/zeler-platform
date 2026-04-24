from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = Field(
        default="mongodb://changeme_local_only:changeme_local_only@127.0.0.1:27017/zeler_platform_dev?authSource=admin",
        alias="MONGO_URI",
    )
    mongo_db: str = Field(default="zeler_platform_dev", alias="MONGO_DB")
    meli_client_id: str = Field(default="", alias="MELI_CLIENT_ID")
    meli_client_secret: SecretStr = Field(default=SecretStr(""), alias="MELI_CLIENT_SECRET")
    meli_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/callback", alias="MELI_REDIRECT_URI"
    )
    kms_project_id: str = Field(default="zeler-platform-dev", alias="KMS_PROJECT_ID")
    kms_location: str = Field(default="us-central1", alias="KMS_LOCATION")
    kms_keyring: str = Field(default="zeler-platform", alias="KMS_KEYRING")
    kms_meli_tokens_key: str = Field(default="meli-tokens", alias="KMS_MELI_TOKENS_KEY")
    kms_platform_jwt_key: str = Field(default="platform-jwt", alias="KMS_PLATFORM_JWT_KEY")
    use_secret_manager: bool = Field(default=False, alias="USE_SECRET_MANAGER")

    @field_validator("meli_client_id", "meli_redirect_uri")
    @classmethod
    def _load_secret_reference(cls, value: str) -> str:
        return value


def load_secret(secret_id: str, *, project_id: str) -> str:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
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
