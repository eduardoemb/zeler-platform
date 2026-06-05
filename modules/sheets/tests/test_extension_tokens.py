# ruff: noqa: S105,S106

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from zeler_sheets.extension_tokens import (
    ExtensionTokenService,
    ExtensionTokenValidationError,
    SellerScope,
    hash_extension_token,
)


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
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.documents[str(doc["_id"])] = dict(doc)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )

    async def update_one(
        self, filter_spec: dict[str, Any], update_spec: dict[str, Any], *, upsert: bool = False
    ) -> FakeUpdateResult:
        assert upsert is False
        for doc_id, doc in self.documents.items():
            if _matches(doc, filter_spec):
                replacement = dict(doc)
                replacement.update(update_spec.get("$set", {}))
                self.documents[doc_id] = replacement
                return FakeUpdateResult()
        raise AssertionError(f"no matching document for {filter_spec}")


class FakeDb:
    def __init__(self) -> None:
        self.sheets_extension_tokens = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "sheets_extension_tokens"
        return self.sheets_extension_tokens


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _service(
    db: FakeDb,
    *,
    now: datetime,
    token_values: list[str] | None = None,
    audit_events: list[dict[str, Any]] | None = None,
    rate_limiter: Callable[[dict[str, Any]], bool] | None = None,
    secret_cipher: Any | None = None,
) -> ExtensionTokenService:
    values = token_values or ["secret-one"]

    def token_factory() -> str:
        return values.pop(0)

    return ExtensionTokenService(
        db=db,
        token_pepper="test-pepper",
        now_fn=lambda: now,
        token_factory=token_factory,
        audit_hook=audit_events.append if audit_events is not None else None,
        rate_limit_hook=rate_limiter,
        secret_cipher=secret_cipher,
    )


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


@pytest.mark.asyncio
async def test_create_token_returns_secret_once_and_stores_hash_only() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(db, now=now, token_values=["first-secret-material"])

    issued = await service.create_token(
        owner_user_id="user-1",
        label="Pilot sheet",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
        formula_scopes=["formulas:execute"],
        expires_at=now + timedelta(days=30),
    )

    assert issued.token_once.startswith("zs_ext_")
    assert issued.metadata.label == "Pilot sheet"
    stored = db.sheets_extension_tokens.documents[issued.metadata.id]
    assert stored["token_prefix"] == issued.token_once[:18]
    assert stored["token_hash"] == hash_extension_token(
        issued.token_once, token_pepper="test-pepper"
    )
    assert "token_once" not in stored
    assert "token" not in stored
    assert stored["seller_scopes"] == [{"seller_id": "123456789", "nickname": "HOPEMOB"}]

    listed = await service.list_tokens(owner_user_id="user-1")

    assert [token.model_dump(mode="json") for token in listed] == [
        {
            "id": issued.metadata.id,
            "label": "Pilot sheet",
            "token_prefix": issued.token_once[:18],
            "owner_user_id": "user-1",
            "seller_scopes": [{"seller_id": "123456789", "nickname": "HOPEMOB"}],
            "formula_scopes": ["formulas:execute"],
            "status": "active",
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "created_at": now.isoformat(),
            "rotated_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "schema_version": 1,
        }
    ]


@pytest.mark.asyncio
async def test_create_and_rotate_store_recoverable_secret_encrypted_only() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    cipher = FakeExtensionTokenCipher()
    service = _service(
        db,
        now=now,
        token_values=["recoverable-one", "recoverable-two"],
        secret_cipher=cipher,
    )

    issued = await service.create_token(
        owner_user_id="user-1",
        label="Recoverable sheet",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    rotated = await service.rotate_token(
        issued.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )

    original_doc = db.sheets_extension_tokens.documents[issued.metadata.id]
    rotated_doc = db.sheets_extension_tokens.documents[rotated.metadata.id]
    assert original_doc["status"] == "revoked"
    assert rotated_doc["token_hash"] == hash_extension_token(
        rotated.token_once, token_pepper="test-pepper"
    )
    assert rotated_doc["token_prefix"] == rotated.token_once[:18]
    assert rotated_doc["token_secret_ciphertext"] != rotated.token_once
    assert rotated_doc["token_secret_dek_wrapped"] != rotated.token_once
    assert "token_once" not in rotated_doc
    assert "token" not in rotated_doc

    revealed = await service.reveal_token(
        rotated.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )

    assert revealed.token_once == rotated.token_once
    assert revealed.metadata.id == rotated.metadata.id
    assert "token_secret_ciphertext" not in revealed.metadata.model_dump(mode="json")


@pytest.mark.asyncio
async def test_reveal_legacy_hash_only_token_fails_without_breaking_validation() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(db, now=now, secret_cipher=FakeExtensionTokenCipher())
    legacy_token = "zs_ext_legacy-material"
    legacy_id = "sheets-ext-token-legacy"
    await db.sheets_extension_tokens.insert_one(
        {
            "_id": legacy_id,
            "label": "Legacy token",
            "token_prefix": legacy_token[:18],
            "token_hash": hash_extension_token(legacy_token, token_pepper="test-pepper"),
            "owner_user_id": "user-1",
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

    validation = await service.validate_token(
        legacy_token,
        cuenta="HOPEMOB",
        formula="ZELERDATA_SKU",
    )
    with pytest.raises(ExtensionTokenValidationError) as exc_info:
        await service.reveal_token(
            legacy_id,
            owner_user_id="user-1",
            allowed_seller_ids={"123456789"},
        )

    assert validation.token_id == legacy_id
    assert exc_info.value.code == "TOKEN_SECRET_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered_field", ["token_hash", "token_prefix"])
async def test_reveal_verifies_decrypted_secret_hash_and_prefix(tampered_field: str) -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["recoverable-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    issued = await service.create_token(
        owner_user_id="user-1",
        label="Tamper check",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    if tampered_field == "token_hash":
        db.sheets_extension_tokens.documents[issued.metadata.id][tampered_field] = (
            hash_extension_token("zs_ext_other-secret", token_pepper="test-pepper")
        )
    else:
        db.sheets_extension_tokens.documents[issued.metadata.id][tampered_field] = (
            "zs_ext_wrongprefix"
        )

    with pytest.raises(ExtensionTokenValidationError) as exc_info:
        await service.reveal_token(
            issued.metadata.id,
            owner_user_id="user-1",
            allowed_seller_ids={"123456789"},
        )

    assert exc_info.value.code == "TOKEN_SECRET_UNAVAILABLE"


@pytest.mark.asyncio
async def test_seller_scope_is_required_for_reveal_and_delete_management() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["scoped-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    issued = await service.create_token(
        owner_user_id="user-1",
        label="Scoped token",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    with pytest.raises(ExtensionTokenValidationError) as reveal_exc:
        await service.reveal_token(
            issued.metadata.id,
            owner_user_id="user-1",
            allowed_seller_ids={"987654321"},
        )
    await service.revoke_token(
        issued.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    with pytest.raises(ExtensionTokenValidationError) as delete_exc:
        await service.delete_token(
            issued.metadata.id,
            owner_user_id="user-1",
            allowed_seller_ids={"987654321"},
        )

    stored = db.sheets_extension_tokens.documents[issued.metadata.id]
    assert reveal_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"
    assert delete_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"
    assert "deleted_at" not in stored


@pytest.mark.asyncio
async def test_management_requires_all_token_seller_scopes_authorized() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["multi-seller-secret", "unused-rotation-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    issued = await service.create_token(
        owner_user_id="platform-user-123",
        label="Multi seller token",
        seller_scopes=[
            SellerScope(seller_id="123456789", nickname="HOPEMOB"),
            SellerScope(seller_id="987654321", nickname="TESTUSER"),
        ],
    )

    fully_authorized = await service.list_tokens(
        owner_user_id="platform-user-123",
        allowed_seller_ids={"123456789", "987654321"},
    )
    partially_authorized = await service.list_tokens(
        owner_user_id="platform-user-123",
        allowed_seller_ids={"123456789"},
    )
    with pytest.raises(ExtensionTokenValidationError) as reveal_exc:
        await service.reveal_token(
            issued.metadata.id,
            owner_user_id="platform-user-123",
            allowed_seller_ids={"123456789"},
        )
    with pytest.raises(ExtensionTokenValidationError) as rotate_exc:
        await service.rotate_token(
            issued.metadata.id,
            owner_user_id="platform-user-123",
            allowed_seller_ids={"123456789"},
        )
    with pytest.raises(ExtensionTokenValidationError) as revoke_exc:
        await service.revoke_token(
            issued.metadata.id,
            owner_user_id="platform-user-123",
            allowed_seller_ids={"123456789"},
        )
    await service.revoke_token(
        issued.metadata.id,
        owner_user_id="platform-user-123",
        allowed_seller_ids={"123456789", "987654321"},
    )
    with pytest.raises(ExtensionTokenValidationError) as delete_exc:
        await service.delete_token(
            issued.metadata.id,
            owner_user_id="platform-user-123",
            allowed_seller_ids={"123456789"},
        )

    assert [token.id for token in fully_authorized] == [issued.metadata.id]
    assert partially_authorized == []
    assert reveal_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"
    assert rotate_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"
    assert revoke_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"
    assert delete_exc.value.code == "TOKEN_NOT_FOUND_OR_FORBIDDEN"


@pytest.mark.asyncio
async def test_delete_soft_deletes_revoked_tokens_only_and_blocks_repeats() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["delete-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    issued = await service.create_token(
        owner_user_id="user-1",
        label="Delete candidate",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    with pytest.raises(ExtensionTokenValidationError) as active_delete_exc:
        await service.delete_token(
            issued.metadata.id,
            owner_user_id="user-1",
            allowed_seller_ids={"123456789"},
        )
    await service.revoke_token(
        issued.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    deleted = await service.delete_token(
        issued.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    with pytest.raises(ExtensionTokenValidationError) as repeated_delete_exc:
        await service.delete_token(
            issued.metadata.id,
            owner_user_id="user-1",
            allowed_seller_ids={"123456789"},
        )

    stored = db.sheets_extension_tokens.documents[issued.metadata.id]
    assert active_delete_exc.value.code == "TOKEN_NOT_REVOKED"
    assert deleted.id == issued.metadata.id
    assert stored["status"] == "revoked"
    assert stored["deleted_at"] == now
    assert stored["updated_at"] == now
    assert repeated_delete_exc.value.code == "TOKEN_DELETED"


@pytest.mark.asyncio
async def test_reveal_rejects_revoked_deleted_and_expired_tokens_with_stable_codes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["revoked-secret", "deleted-secret", "expired-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    revoked = await service.create_token(
        owner_user_id="user-1",
        label="Revoked",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    deleted = await service.create_token(
        owner_user_id="user-1",
        label="Deleted",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    expired = await service.create_token(
        owner_user_id="user-1",
        label="Expired",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
        expires_at=now - timedelta(seconds=1),
    )
    await service.revoke_token(
        revoked.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    await service.revoke_token(
        deleted.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    await service.delete_token(
        deleted.metadata.id,
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )

    for token_id, expected_code in [
        (revoked.metadata.id, "TOKEN_NOT_ACTIVE"),
        (deleted.metadata.id, "TOKEN_DELETED"),
        (expired.metadata.id, "TOKEN_EXPIRED"),
    ]:
        with pytest.raises(ExtensionTokenValidationError) as exc_info:
            await service.reveal_token(
                token_id,
                owner_user_id="user-1",
                allowed_seller_ids={"123456789"},
            )
        assert exc_info.value.code == expected_code


@pytest.mark.asyncio
async def test_list_tokens_filters_deleted_seller_scope_and_secret_fields() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["active-secret", "foreign-secret", "deleted-secret"],
        secret_cipher=FakeExtensionTokenCipher(),
    )
    active = await service.create_token(
        owner_user_id="user-1",
        label="Active",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    await service.create_token(
        owner_user_id="user-1",
        label="Foreign seller",
        seller_scopes=[SellerScope(seller_id="987654321", nickname="OTHER")],
    )
    deleted = await service.create_token(
        owner_user_id="user-1",
        label="Deleted",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    db.sheets_extension_tokens.documents[deleted.metadata.id]["deleted_at"] = now

    listed = await service.list_tokens(
        owner_user_id="user-1",
        allowed_seller_ids={"123456789"},
    )
    payload = [token.model_dump(mode="json") for token in listed]

    assert [token["id"] for token in payload] == [active.metadata.id]
    assert "token_secret" not in json.dumps(payload)
    assert "token_hash" not in json.dumps(payload)
    assert "deleted_at" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_validate_token_enforces_seller_scope_and_records_audit_without_secret() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    audit_events: list[dict[str, Any]] = []
    service = _service(
        db,
        now=now,
        token_values=["valid-secret-material"],
        audit_events=audit_events,
    )
    issued = await service.create_token(
        owner_user_id="user-1",
        label="Formula access",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    validation = await service.validate_token(
        issued.token_once,
        cuenta="HOPEMOB",
        formula="SHEETSELLER_STOCK",
        request_id="req-1",
    )

    assert validation.token_id == issued.metadata.id
    assert validation.seller_id == "123456789"
    assert db.sheets_extension_tokens.documents[issued.metadata.id]["last_used_at"] == now
    assert audit_events[-1] == {
        "token_id": issued.metadata.id,
        "seller_id": "123456789",
        "seller_nickname": "HOPEMOB",
        "formula": "SHEETSELLER_STOCK",
        "request_id": "req-1",
        "outcome": "allowed",
        "error_code": None,
        "occurred_at": now,
    }

    with pytest.raises(ExtensionTokenValidationError) as exc_info:
        await service.validate_token(
            issued.token_once,
            cuenta="OTHERSELLER",
            formula="SHEETSELLER_STOCK",
            request_id="req-2",
        )

    assert exc_info.value.code == "SELLER_FORBIDDEN"
    assert audit_events[-1]["outcome"] == "denied"
    assert audit_events[-1]["error_code"] == "SELLER_FORBIDDEN"
    assert "valid-secret-material" not in repr(audit_events[-1])


@pytest.mark.asyncio
async def test_validate_token_resolves_multi_seller_scope_by_id_or_nickname() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(db, now=now, token_values=["multi-secret"])
    issued = await service.create_token(
        owner_user_id="platform-user-123",
        label="Multi seller",
        seller_scopes=[
            SellerScope(seller_id="123456789", nickname="HOPEMOB"),
            SellerScope(seller_id="987654321", nickname="TESTUSER"),
        ],
    )

    by_id = await service.validate_token(
        issued.token_once,
        cuenta="987654321",
        formula="ZELERDATA_STOCK",
    )
    by_nickname = await service.validate_token(
        issued.token_once,
        cuenta="hopemob",
        formula="ZELERDATA_STOCK",
    )

    assert by_id.seller_id == "987654321"
    assert by_id.seller_nickname == "TESTUSER"
    assert by_nickname.seller_id == "123456789"
    assert by_nickname.seller_nickname == "HOPEMOB"


@pytest.mark.asyncio
async def test_create_token_rejects_empty_and_duplicate_seller_scopes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    duplicate_id_service = _service(FakeDb(), now=now, token_values=["unused-1"])
    duplicate_nickname_service = _service(FakeDb(), now=now, token_values=["unused-2"])
    empty_service = _service(FakeDb(), now=now, token_values=["unused-3"])

    with pytest.raises(ExtensionTokenValidationError) as duplicate_id_exc:
        await duplicate_id_service.create_token(
            owner_user_id="platform-user-123",
            label="Duplicate ids",
            seller_scopes=[
                SellerScope(seller_id="123456789", nickname="HOPEMOB"),
                SellerScope(seller_id="123456789", nickname="OTHER"),
            ],
        )
    with pytest.raises(ExtensionTokenValidationError) as duplicate_nickname_exc:
        await duplicate_nickname_service.create_token(
            owner_user_id="platform-user-123",
            label="Duplicate nicknames",
            seller_scopes=[
                SellerScope(seller_id="123456789", nickname="HOPEMOB"),
                SellerScope(seller_id="987654321", nickname="hopemob"),
            ],
        )
    with pytest.raises(ExtensionTokenValidationError) as empty_exc:
        await empty_service.create_token(
            owner_user_id="platform-user-123",
            label="Empty",
            seller_scopes=[],
        )

    assert duplicate_id_exc.value.code == "SELLER_SCOPE_INVALID"
    assert duplicate_nickname_exc.value.code == "SELLER_SCOPE_INVALID"
    assert empty_exc.value.code == "SELLER_SCOPE_INVALID"


@pytest.mark.asyncio
async def test_validate_token_fails_safely_for_ambiguous_stored_nicknames() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(db, now=now, token_values=["ambiguous-secret"])
    issued = await service.create_token(
        owner_user_id="platform-user-123",
        label="Ambiguous",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )
    stored = db.sheets_extension_tokens.documents[issued.metadata.id]
    stored["seller_scopes"] = [
        {"seller_id": "123456789", "nickname": "HOPEMOB"},
        {"seller_id": "987654321", "nickname": "hopemob"},
    ]

    by_id = await service.validate_token(
        issued.token_once,
        cuenta="987654321",
        formula="ZELERDATA_STOCK",
    )
    with pytest.raises(ExtensionTokenValidationError) as nickname_exc:
        await service.validate_token(
            issued.token_once,
            cuenta="HOPEMOB",
            formula="ZELERDATA_STOCK",
        )

    assert by_id.seller_id == "987654321"
    assert nickname_exc.value.code == "SELLER_FORBIDDEN"


@pytest.mark.asyncio
async def test_rotate_and_revoke_invalidate_previous_or_current_secret() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    db = FakeDb()
    service = _service(
        db,
        now=now,
        token_values=["original-secret", "rotated-secret"],
    )
    issued = await service.create_token(
        owner_user_id="user-1",
        label="Rotatable",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    rotated = await service.rotate_token(issued.metadata.id, owner_user_id="user-1")

    assert rotated.token_once.startswith("zs_ext_")
    assert rotated.token_once != issued.token_once
    assert db.sheets_extension_tokens.documents[issued.metadata.id]["status"] == "revoked"
    assert db.sheets_extension_tokens.documents[issued.metadata.id]["rotated_at"] == now
    assert db.sheets_extension_tokens.documents[rotated.metadata.id]["status"] == "active"
    with pytest.raises(ExtensionTokenValidationError) as old_exc:
        await service.validate_token(issued.token_once, cuenta="HOPEMOB", formula="SHEETSELLER_SKU")
    assert old_exc.value.code == "TOKEN_REVOKED"

    await service.revoke_token(rotated.metadata.id, owner_user_id="user-1")

    with pytest.raises(ExtensionTokenValidationError) as revoked_exc:
        await service.validate_token(
            rotated.token_once, cuenta="HOPEMOB", formula="SHEETSELLER_SKU"
        )
    assert revoked_exc.value.code == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_expired_and_rate_limited_tokens_fail_with_stable_codes() -> None:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    expired_db = FakeDb()
    expired_service = _service(expired_db, now=now, token_values=["expired-secret"])
    expired = await expired_service.create_token(
        owner_user_id="user-1",
        label="Expired",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
        expires_at=now - timedelta(seconds=1),
    )

    with pytest.raises(ExtensionTokenValidationError) as expired_exc:
        await expired_service.validate_token(
            expired.token_once, cuenta="HOPEMOB", formula="SHEETSELLER_PRECIO"
        )
    assert expired_exc.value.code == "TOKEN_REVOKED"

    limited_db = FakeDb()
    limited_audit: list[dict[str, Any]] = []
    limited_service = _service(
        limited_db,
        now=now,
        token_values=["limited-secret"],
        audit_events=limited_audit,
        rate_limiter=lambda context: context["formula"] != "SHEETSELLER_PRECIO",
    )
    limited = await limited_service.create_token(
        owner_user_id="user-1",
        label="Limited",
        seller_scopes=[SellerScope(seller_id="123456789", nickname="HOPEMOB")],
    )

    with pytest.raises(ExtensionTokenValidationError) as limited_exc:
        await limited_service.validate_token(
            limited.token_once,
            cuenta="HOPEMOB",
            formula="SHEETSELLER_PRECIO",
            request_id="req-rate",
        )

    assert limited_exc.value.code == "RATE_LIMITED"
    assert limited_audit[-1]["error_code"] == "RATE_LIMITED"


def test_extension_token_schema_and_indexes_contract() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (repo_root / "infra/mongo/schemas/sheets_extension_tokens.json").read_text()
    )
    indexes = json.loads(
        (repo_root / "infra/mongo/indexes/sheets_extension_tokens.json").read_text()
    )

    required = set(schema["$jsonSchema"]["required"])
    assert {
        "_id",
        "token_hash",
        "token_prefix",
        "owner_user_id",
        "seller_scopes",
        "formula_scopes",
        "status",
        "created_at",
        "schema_version",
    }.issubset(required)
    assert schema["$jsonSchema"]["properties"]["status"]["enum"] == [
        "active",
        "revoked",
    ]
    for secret_field in [
        "token_secret_ciphertext",
        "token_secret_dek_wrapped",
        "token_secret_nonce",
    ]:
        assert secret_field not in required
        assert schema["$jsonSchema"]["properties"][secret_field]["bsonType"] == "binData"
    assert "token_secret_kms_key_version" not in required
    assert (
        schema["$jsonSchema"]["properties"]["token_secret_kms_key_version"]["bsonType"] == "string"
    )
    assert "deleted_at" not in required
    assert schema["$jsonSchema"]["properties"]["deleted_at"]["bsonType"] == ["date", "null"]
    assert all("token_once" not in json.dumps(section) for section in [schema, indexes])
    assert {index["options"]["name"]: index["keys"] for index in indexes} == {
        "uniq_sheets_extension_tokens_hash": {"token_hash": 1},
        "idx_sheets_extension_tokens_owner_deleted_status": {
            "owner_user_id": 1,
            "deleted_at": 1,
            "status": 1,
        },
        "idx_sheets_extension_tokens_seller_deleted_status": {
            "seller_scopes.seller_id": 1,
            "deleted_at": 1,
            "status": 1,
        },
        "idx_sheets_extension_tokens_expiry": {"expires_at": 1},
    }
