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
    )


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
    assert all("token_once" not in json.dumps(section) for section in [schema, indexes])
    assert {index["options"]["name"]: index["keys"] for index in indexes} == {
        "uniq_sheets_extension_tokens_hash": {"token_hash": 1},
        "idx_sheets_extension_tokens_owner_status": {"owner_user_id": 1, "status": 1},
        "idx_sheets_extension_tokens_seller_status": {
            "seller_scopes.seller_id": 1,
            "status": 1,
        },
        "idx_sheets_extension_tokens_expiry": {"expires_at": 1},
    }
