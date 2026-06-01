from __future__ import annotations

# ruff: noqa: S106 -- model fixtures use inert token-shaped strings, not credentials.
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from zeler_platform_core.cli.export_schemas import export_schemas, validate_export_drift
from zeler_platform_core.models import MeliAccount, current_schema_version

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


def _account_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "507f1f77bcf86cd799439011",
        "seller_id": 82453304,
        "nickname": "HOPEMOB",
        "app_id": "zeler-platform",
        "platform_user_id": "platform-user-1",
        "access_token_ciphertext": "access-ciphertext",
        "access_token_dek_wrapped": "access-dek",
        "refresh_token_ciphertext": "refresh-ciphertext",
        "refresh_token_dek_wrapped": "refresh-dek",
        "token_nonce": "nonce",
        "refresh_token_nonce": "refresh-nonce",
        "scopes": ["read", "write"],
        "status": "active",
        "expires_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        "kms_key_version": "kms-v1",
    }
    payload.update(overrides)
    return payload


def test_meli_account_accepts_missing_optional_site_timezone_metadata() -> None:
    account = MeliAccount.model_validate(_account_payload())

    assert account.seller_id == "82453304"
    assert account.site_id is None
    assert account.timezone is None
    assert account.schema_version == 1


def test_meli_account_accepts_site_id_and_valid_iana_timezone() -> None:
    account = MeliAccount.model_validate(
        _account_payload(site_id="MLM", timezone="America/Mexico_City")
    )

    assert account.site_id == "MLM"
    assert account.timezone == "America/Mexico_City"


def test_meli_account_rejects_invalid_timezone_metadata() -> None:
    with pytest.raises(ValidationError, match="timezone must be a valid IANA timezone"):
        MeliAccount.model_validate(_account_payload(site_id="MLM", timezone="Not/A_Zone"))


def test_meli_account_schema_exports_additive_non_required_timezone_fields(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    payload = json.loads((tmp_path / "meli_accounts.json").read_text(encoding="utf-8"))
    schema = payload["$jsonSchema"]

    assert current_schema_version("meli_accounts") == 1
    assert "site_id" not in schema["required"]
    assert "timezone" not in schema["required"]
    assert schema["properties"]["site_id"] == {"bsonType": ["string", "null"]}
    assert schema["properties"]["timezone"] == {"bsonType": ["string", "null"]}


def test_meli_account_committed_schema_has_no_export_drift() -> None:
    drift = validate_export_drift(Path("infra/mongo/schemas"))

    assert "meli_accounts.json" not in drift
