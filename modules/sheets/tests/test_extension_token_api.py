# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope, hash_extension_token


class FakeUpdateResult:
    modified_count = 1


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_args: Any) -> FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(dict(doc))

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        return FakeCursor([dict(doc) for doc in self.docs if _matches(doc, filter_spec)])

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        assert upsert is False
        for index, doc in enumerate(self.docs):
            if _matches(doc, filter_spec):
                replacement = dict(doc)
                replacement.update(update_spec.get("$set", {}))
                self.docs[index] = replacement
                return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")


class FakeDb:
    def __init__(self) -> None:
        self.sheets_exports = FakeCollection()
        self.sheets_sync_jobs = FakeCollection()
        self.sheets_extension_tokens = FakeCollection()
        self.meli_accounts = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "sheets_exports":
            return self.sheets_exports
        if name == "sheets_sync_jobs":
            return self.sheets_sync_jobs
        if name == "sheets_extension_tokens":
            return self.sheets_extension_tokens
        if name == "meli_accounts":
            return self.meli_accounts
        raise AssertionError(name)


class FakeExtensionTokenCipher:
    def __init__(self) -> None:
        self.plaintexts_by_token_id: dict[str, str] = {}

    def encrypt(
        self,
        plaintext: str,
        *,
        owner_user_id: str,
        token_id: str,
    ) -> dict[str, bytes | str]:
        assert owner_user_id
        self.plaintexts_by_token_id[token_id] = plaintext
        return {
            "token_secret_ciphertext": f"ciphertext:{token_id}".encode(),
            "token_secret_dek_wrapped": f"dek:{token_id}".encode(),
            "token_secret_nonce": f"nonce:{token_id}".encode(),
            "token_secret_kms_key_version": "kms-test-version",
        }

    async def decrypt(
        self,
        doc: dict[str, Any],
        *,
        owner_user_id: str,
        token_id: str,
    ) -> str:
        assert doc["token_secret_ciphertext"] == f"ciphertext:{token_id}".encode()
        assert owner_user_id == doc["owner_user_id"]
        return self.plaintexts_by_token_id[token_id]


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_create_and_list_extension_token_show_secret_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch, token_values=["api-secret"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
                "formula_scopes": ["formulas:execute"],
            },
        )
        list_response = await client.get(
            "/sheets/extension-tokens?owner_user_id=user-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["token_once"].startswith("zs_ext_")
    assert body["status"] == "active"
    assert body["seller_scopes"] == [{"seller_id": "123456789", "nickname": "HOPEMOB"}]
    stored = db.sheets_extension_tokens.docs[0]
    assert stored["token_prefix"] == body["token_prefix"]
    assert stored["token_hash"] != body["token_once"]
    assert "token_once" not in stored

    assert list_response.status_code == 200
    assert list_response.json() == [
        {key: value for key, value in body.items() if key != "token_once"}
    ]


@pytest.mark.asyncio
async def test_rotate_and_revoke_extension_token_api(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch, token_values=["api-secret", "rotated-secret"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )
        token_id = created.json()["id"]
        rotated = await client.post(
            f"/sheets/extension-tokens/{token_id}:rotate",
            headers={"Authorization": "Bearer valid"},
        )
        revoked = await client.post(
            f"/sheets/extension-tokens/{rotated.json()['id']}:revoke",
            headers={"Authorization": "Bearer valid"},
        )

    assert rotated.status_code == 200
    assert rotated.json()["token_once"].startswith("zs_ext_")
    assert rotated.json()["token_once"] != created.json()["token_once"]
    assert db.sheets_extension_tokens.docs[0]["status"] == "revoked"
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert db.sheets_extension_tokens.docs[-1]["status"] == "revoked"


@pytest.mark.asyncio
async def test_reveal_extension_token_api_returns_secret_without_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _db = _app(
        monkeypatch,
        token_values=["api-reveal-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Revealable sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )
        revealed = await client.post(
            f"/sheets/extension-tokens/{created.json()['id']}:reveal",
            headers={"Authorization": "Bearer valid"},
        )

    assert revealed.status_code == 200
    body = revealed.json()
    assert body["token_once"] == created.json()["token_once"]
    assert body["id"] == created.json()["id"]
    assert "token_secret" not in str(body)
    assert "token_hash" not in body


@pytest.mark.asyncio
async def test_delete_extension_token_api_soft_deletes_revoked_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(
        monkeypatch,
        token_values=["api-delete-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Delete from UI",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )
        active_delete = await client.delete(
            f"/sheets/extension-tokens/{created.json()['id']}",
            headers={"Authorization": "Bearer valid"},
        )
        await client.post(
            f"/sheets/extension-tokens/{created.json()['id']}:revoke",
            headers={"Authorization": "Bearer valid"},
        )
        deleted = await client.delete(
            f"/sheets/extension-tokens/{created.json()['id']}",
            headers={"Authorization": "Bearer valid"},
        )
        listed = await client.get(
            "/sheets/extension-tokens?owner_user_id=user-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert active_delete.status_code == 409
    assert active_delete.json()["error"] == "TOKEN_NOT_REVOKED"
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert db.sheets_extension_tokens.docs[0]["deleted_at"] == datetime(
        2026, 5, 13, 12, 0, tzinfo=UTC
    )
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_delete_extension_token_api_rejects_nonexistent_and_already_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _db = _app(
        monkeypatch,
        token_values=["api-redelete-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Delete twice",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )
        await client.post(
            f"/sheets/extension-tokens/{created.json()['id']}:revoke",
            headers={"Authorization": "Bearer valid"},
        )
        first_delete = await client.delete(
            f"/sheets/extension-tokens/{created.json()['id']}",
            headers={"Authorization": "Bearer valid"},
        )
        repeated_delete = await client.delete(
            f"/sheets/extension-tokens/{created.json()['id']}",
            headers={"Authorization": "Bearer valid"},
        )
        missing_delete = await client.delete(
            "/sheets/extension-tokens/sheets-ext-token-missing",
            headers={"Authorization": "Bearer valid"},
        )

    assert first_delete.status_code == 204
    assert repeated_delete.status_code == 409
    assert repeated_delete.json() == {
        "error": "TOKEN_DELETED",
        "detail": "El token ya fue eliminado.",
    }
    assert missing_delete.status_code == 404
    assert missing_delete.json() == {
        "error": "TOKEN_NOT_FOUND_OR_FORBIDDEN",
        "detail": "Token no encontrado o sin permisos.",
    }


@pytest.mark.asyncio
async def test_management_api_requires_all_multi_seller_scopes_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = FakeExtensionTokenCipher()
    claims = _claims(platform_user_id="platform-user-123", issued_by="zeler-app")
    app, db = _app(
        monkeypatch,
        token_values=["unused-route-secret"],
        claims=claims,
        secret_cipher=cipher,
    )
    db.meli_accounts.docs.append(
        {
            "seller_id": 123456789,
            "nickname": "HOPEMOB",
            "platform_user_id": "platform-user-123",
            "app_id": "zeler-platform",
            "status": "active",
        }
    )
    issued = await ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        token_factory=lambda: "multi-seller-route-secret",
        secret_cipher=cipher,
    ).create_token(
        owner_user_id="platform-user-123",
        label="Partially authorized",
        seller_scopes=[
            SellerScope(seller_id="123456789", nickname="HOPEMOB"),
            SellerScope(seller_id="987654321", nickname="TESTUSER"),
        ],
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(
            "/sheets/extension-tokens?owner_user_id=platform-user-123",
            headers={"Authorization": "Bearer valid"},
        )
        revealed = await client.post(
            f"/sheets/extension-tokens/{issued.metadata.id}:reveal",
            headers={"Authorization": "Bearer valid"},
        )

    assert listed.status_code == 200
    assert listed.json() == []
    assert revealed.status_code == 404
    assert revealed.json() == {
        "error": "TOKEN_NOT_FOUND_OR_FORBIDDEN",
        "detail": "Token no encontrado o sin permisos.",
    }


@pytest.mark.asyncio
async def test_reveal_api_maps_legacy_and_foreign_scope_to_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = _claims(platform_user_id="platform-user-123", issued_by="zeler-app")
    app, db = _app(
        monkeypatch,
        token_values=["unused-api-secret"],
        claims=claims,
        secret_cipher=FakeExtensionTokenCipher(),
    )
    db.meli_accounts.docs.append(
        {
            "seller_id": 123456789,
            "nickname": "HOPEMOB",
            "platform_user_id": "platform-user-123",
            "app_id": "zeler-platform",
            "status": "active",
        }
    )
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    legacy_token = "zs_ext_legacy-api-material"
    db.sheets_extension_tokens.docs.append(
        {
            "_id": "sheets-ext-token-legacy-api",
            "label": "Legacy API",
            "token_prefix": legacy_token[:18],
            "token_hash": hash_extension_token(legacy_token, token_pepper="test-pepper"),
            "owner_user_id": "platform-user-123",
            "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            "formula_scopes": ["formulas:execute"],
            "status": "active",
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
            "rotated_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "schema_version": 1,
        }
    )
    foreign = await ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: now,
        token_factory=lambda: "foreign-api-secret",
        secret_cipher=FakeExtensionTokenCipher(),
    ).create_token(
        owner_user_id="platform-user-123",
        label="Foreign scope",
        seller_scopes=[SellerScope(seller_id="987654321", nickname="OTHER")],
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        legacy_reveal = await client.post(
            "/sheets/extension-tokens/sheets-ext-token-legacy-api:reveal",
            headers={"Authorization": "Bearer valid"},
        )
        foreign_reveal = await client.post(
            f"/sheets/extension-tokens/{foreign.metadata.id}:reveal",
            headers={"Authorization": "Bearer valid"},
        )

    assert legacy_reveal.status_code == 409
    assert legacy_reveal.json() == {
        "error": "TOKEN_SECRET_UNAVAILABLE",
        "detail": (
            "Este token no se puede revelar. Generá o rotá el token para obtener "
            "un valor recuperable."
        ),
    }
    assert foreign_reveal.status_code == 404
    assert foreign_reveal.json() == {
        "error": "TOKEN_NOT_FOUND_OR_FORBIDDEN",
        "detail": "Token no encontrado o sin permisos.",
    }
    assert legacy_token not in str(legacy_reveal.json())


@pytest.mark.asyncio
async def test_extension_token_api_requires_module_admin_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/extension-tokens?owner_user_id=user-1",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
async def test_extension_token_api_can_read_pepper_from_app_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr

    from zeler_sheets.sheets_config import SheetsSettings

    app, _db = _app(monkeypatch, token_values=["settings-secret"], configure_pepper=False)
    app.state.settings = SheetsSettings(
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret=SecretStr("google-client-secret"),
        google_oauth_redirect_uri="https://sheets.test/oauth/google/callback",
        kms_project_id="zeler-dev",
        extension_token_pepper=SecretStr("settings-pepper"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Operator sheet",
                "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            },
        )

    assert response.status_code == 201
    assert response.json()["token_once"].startswith("zs_ext_")


@pytest.mark.asyncio
async def test_platform_user_token_creation_canonicalizes_active_same_user_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(
        monkeypatch,
        token_values=["multi-seller-secret"],
        claims=_claims(platform_user_id="platform-user-123", issued_by="zeler-app"),
    )
    db.meli_accounts.docs.extend(
        [
            {
                "seller_id": 123456789,
                "nickname": "HOPEMOB",
                "platform_user_id": "platform-user-123",
                "app_id": "zeler-platform",
                "status": "active",
            },
            {
                "seller_id": "987654321",
                "nickname": "TESTUSER",
                "platform_user_id": "platform-user-123",
                "app_id": "zeler-platform",
                "status": "active",
            },
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "All accounts",
                "seller_scopes": [
                    {"seller_id": "123456789", "nickname": "spoofed"},
                    {"seller_id": "987654321", "nickname": "stale"},
                ],
            },
        )

    assert response.status_code == 201
    assert response.json()["owner_user_id"] == "platform-user-123"
    assert response.json()["seller_scopes"] == [
        {"seller_id": "123456789", "nickname": "HOPEMOB"},
        {"seller_id": "987654321", "nickname": "TESTUSER"},
    ]
    assert db.sheets_extension_tokens.docs[0]["seller_scopes"] == [
        {"seller_id": "123456789", "nickname": "HOPEMOB"},
        {"seller_id": "987654321", "nickname": "TESTUSER"},
    ]


@pytest.mark.asyncio
async def test_platform_user_token_creation_rejects_foreign_inactive_empty_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(
        monkeypatch,
        token_values=["unused-secret"],
        claims=_claims(platform_user_id="platform-user-123", issued_by="zeler-app"),
    )
    db.meli_accounts.docs.extend(
        [
            {
                "seller_id": 123456789,
                "nickname": "HOPEMOB",
                "platform_user_id": "platform-user-123",
                "app_id": "zeler-platform",
                "status": "active",
            },
            {
                "seller_id": 222222222,
                "nickname": "INACTIVE",
                "platform_user_id": "platform-user-123",
                "app_id": "zeler-platform",
                "status": "inactive",
            },
            {
                "seller_id": 333333333,
                "nickname": "FOREIGN",
                "platform_user_id": "other-user",
                "app_id": "zeler-platform",
                "status": "active",
            },
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        inactive = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Inactive",
                "seller_scopes": [{"seller_id": "222222222", "nickname": "INACTIVE"}],
            },
        )
        foreign = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Foreign",
                "seller_scopes": [{"seller_id": "333333333", "nickname": "FOREIGN"}],
            },
        )
        empty = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={"label": "Empty", "seller_scopes": []},
        )
        duplicate = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Duplicate",
                "seller_scopes": [
                    {"seller_id": "123456789", "nickname": "HOPEMOB"},
                    {"seller_id": "123456789", "nickname": "HOPEMOB"},
                ],
            },
        )

    assert inactive.status_code == 403
    assert inactive.json()["error"] == "forbidden"
    assert foreign.status_code == 403
    assert foreign.json()["error"] == "forbidden"
    assert empty.status_code == 403
    assert empty.json()["error"] == "forbidden"
    assert duplicate.status_code == 400
    assert duplicate.json()["error"] == "invalid_seller_scopes"
    assert db.sheets_extension_tokens.docs == []


@pytest.mark.asyncio
async def test_legacy_token_creation_ignores_client_only_extra_seller_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch, token_values=["legacy-secret"], claims=_claims())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/extension-tokens",
            headers={"Authorization": "Bearer valid"},
            json={
                "label": "Legacy",
                "seller_scopes": [
                    {"seller_id": "123456789", "nickname": "HOPEMOB"},
                    {"seller_id": "999999999", "nickname": "OTHER"},
                ],
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": "forbidden",
        "detail": "seller scopes must match JWT seller_id",
    }
    assert db.sheets_extension_tokens.docs == []


def _app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_values: list[str] | None = None,
    jwt_error: Exception | None = None,
    configure_pepper: bool = True,
    claims: object | None = None,
    secret_cipher: FakeExtensionTokenCipher | None = None,
) -> tuple[FastAPI, FakeDb]:
    import zeler_sheets.api as api
    from zeler_sheets.api import build_router

    values = token_values or ["api-secret"]
    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    pepper = "test-pepper" if configure_pepper else None
    app.include_router(
        build_router(
            clock=lambda: datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            extension_token_pepper=pepper,
            extension_token_factory=lambda: values.pop(0),
            extension_token_secret_cipher=secret_cipher,
        )
    )

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return claims or _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims(*, platform_user_id: str | None = None, issued_by: str | None = "user-1") -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    claim_values = {
        "module_id": "sheets",
        "seller_id": 123456789,
        "iss": "module:sheets",
        "aud": "gateway",
        "iat": 1,
        "exp": 2,
        "token_type": "module_admin",
        "scopes": ["admin:sheets"],
        "issued_by": issued_by,
    }
    if platform_user_id is not None:
        return SimpleNamespace(**claim_values, platform_user_id=platform_user_id)
    return ModuleClaims(
        module_id="sheets",
        seller_id=123456789,
        iss="module:sheets",
        aud="gateway",
        iat=1,
        exp=2,
        token_type="module_admin",
        scopes=["admin:sheets"],
        issued_by="user-1",
    )
