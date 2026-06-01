from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                doc
                for doc in self.docs
                if all(_matches(doc.get(key), value) for key, value in query.items())
            ]
        )

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(_matches(doc.get(key), value) for key, value in query.items()):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        assert upsert is True
        for index, doc in enumerate(self.docs):
            if all(_matches(doc.get(key), value) for key, value in query.items()):
                self.docs[index] = replacement
                return
        self.docs.append(replacement)

    async def delete_one(self, query: dict[str, Any]) -> None:
        self.docs = [
            doc for doc in self.docs if not all(_matches(doc.get(k), v) for k, v in query.items())
        ]


class FakeDb:
    def __init__(self) -> None:
        self.autoreply_templates = FakeCollection(
            [
                {
                    "_id": "template-1",
                    "seller_id": "123456789",
                    "template_name": "shipping",
                    "match_type": "keyword",
                    "pattern": "envio",
                    "answer_text": "Hola, hacemos envíos a todo el país.",
                    "enabled": True,
                    "created_at": "2026-04-24T12:00:00+00:00",
                    "updated_at": "2026-04-24T12:00:00+00:00",
                    "schema_version": 1,
                }
            ]
        )
        self.autoreply_history = FakeCollection(
            [
                {
                    "_id": "history-1",
                    "seller_id": "123456789",
                    "event_id": "event-1",
                    "idempotency_key": "idem-1",
                    "resource_type": "question",
                    "resource_id": "987",
                    "outcome": "answered",
                    "created_at": "2026-04-24T12:30:00+00:00",
                    "schema_version": 1,
                }
            ]
        )
        self.questions = FakeCollection(
            [
                {
                    "_id": "question-1",
                    "seller_id": "123456789",
                    "item_id": "MLA1",
                    "text": "Tienen envio?",
                    "status": "UNANSWERED",
                    "from_user_id": "buyer-1",
                    "date_created": "2026-04-24T12:00:00+00:00",
                    "answer": None,
                    "schema_version": 1,
                }
            ]
        )
        self.messages = FakeCollection(
            [
                {
                    "_id": "message-1",
                    "seller_id": "123456789",
                    "pack_id": "pack-1",
                    "order_id": "order-1",
                    "from_user_id": "buyer-1",
                    "to_user_id": "123456789",
                    "text": "Hola",
                    "status": "available",
                    "date_created": "2026-04-24T12:00:00+00:00",
                    "read_at": None,
                    "schema_version": 1,
                }
            ]
        )
        self.claims = FakeCollection(
            [
                {
                    "_id": "claim-1",
                    "seller_id": "123456789",
                    "buyer_id": "buyer-1",
                    "order_id": "order-1",
                    "status": "opened",
                    "stage": "claim",
                    "type": "mediations",
                    "date_created": "2026-04-24T12:00:00+00:00",
                    "resolution": None,
                    "schema_version": 1,
                }
            ]
        )
        self.autoreply_preferences = FakeCollection()
        self.autoreply_schedules = FakeCollection()
        self.autoreply_tags = FakeCollection()
        self.autoreply_predefined_answers = FakeCollection()
        self.autoreply_notifications = FakeCollection(
            [
                {
                    "_id": "notification-1",
                    "seller_id": "123456789",
                    "resource_type": "question",
                    "resource_id": "question-1",
                    "title": "Nueva pregunta",
                    "read_at": None,
                    "created_at": "2026-04-24T12:00:00+00:00",
                }
            ]
        )
        self.autoreply_ai_suggestions = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "autoreply_templates":
            return self.autoreply_templates
        if name == "autoreply_history":
            return self.autoreply_history
        if name == "questions":
            return self.questions
        if name == "messages":
            return self.messages
        if name == "claims":
            return self.claims
        if name == "autoreply_preferences":
            return self.autoreply_preferences
        if name == "autoreply_schedules":
            return self.autoreply_schedules
        if name == "autoreply_tags":
            return self.autoreply_tags
        if name == "autoreply_predefined_answers":
            return self.autoreply_predefined_answers
        if name == "autoreply_notifications":
            return self.autoreply_notifications
        if name == "autoreply_ai_suggestions":
            return self.autoreply_ai_suggestions
        raise AssertionError(name)


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and "$in" in expected:
        return actual in cast(list[Any], expected["$in"])
    return bool(actual == expected)


@pytest.mark.asyncio
async def test_list_templates_includes_history(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/autoreply/templates?seller_id=123456789",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 200
    assert response.json()[0]["template_name"] == "shipping"
    assert response.json()[0]["recent_history"][0]["outcome"] == "answered"


@pytest.mark.asyncio
async def test_create_template_persists_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/autoreply/templates",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "template_name": "returns",
                "match_type": "regex",
                "pattern": "devoluci[oó]n",
                "answer_text": "Podés iniciar la devolución desde tu compra.",
                "enabled": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["template_name"] == "returns"
    assert db.autoreply_templates.docs[-1]["pattern"] == "devoluci[oó]n"


@pytest.mark.asyncio
async def test_update_template_replaces_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/autoreply/templates/template-1",
            headers={"Authorization": "Bearer valid"},
            json={"answer_text": "Respuesta actualizada", "enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["answer_text"] == "Respuesta actualizada"
    assert db.autoreply_templates.docs[0]["enabled"] is False


@pytest.mark.asyncio
async def test_delete_template_removes_existing_template(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(
            "/autoreply/templates/template-1",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 204
    assert db.autoreply_templates.docs == []


@pytest.mark.asyncio
async def test_delete_template_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(
            "/autoreply/templates/missing-template",
            headers={"Authorization": "Bearer valid"},
        )

    assert response.status_code == 404
    assert response.json() == {"error": "autoreply_template_not_found"}
    assert len(db.autoreply_templates.docs) == 1


@pytest.mark.asyncio
async def test_delete_template_requires_module_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(
            "/autoreply/templates/template-1",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}
    assert len(db.autoreply_templates.docs) == 1


@pytest.mark.asyncio
async def test_preview_template_returns_match_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/autoreply/templates/preview",
            headers={"Authorization": "Bearer valid"},
            json={
                "match_type": "keyword",
                "pattern": "envio",
                "answer_text": "Hola, hacemos envíos a todo el país.",
                "sample_text": "Tienen envio a Córdoba?",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "matched": True,
        "answer_text": "Hola, hacemos envíos a todo el país.",
    }


@pytest.mark.asyncio
async def test_only_module_jwt_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from zeler_platform_core.auth.jwt import InvalidJWTError

    app, _db = _app(monkeypatch, jwt_error=InvalidJWTError("bad token"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/autoreply/templates?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "detail": "bad token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims_kwargs",
    [
        {"token_type": "module"},
        {"module_id": "publicador", "scopes": ["admin:publicador"]},
        {"seller_id": 987654321},
        {"scopes": []},
    ],
    ids=["wrong-token-type", "wrong-module", "wrong-seller", "missing-scope"],
)
async def test_module_admin_claims_enforced(
    monkeypatch: pytest.MonkeyPatch, claims_kwargs: dict[str, Any]
) -> None:
    app, _db = _app(monkeypatch, claims=_claims(**claims_kwargs))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/autoreply/templates?seller_id=123456789",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


@pytest.mark.asyncio
async def test_parity_read_routes_return_seller_scoped_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = {
            path: await client.get(path, headers={"Authorization": "Bearer valid"})
            for path in (
                "/autoreply/dashboard?seller_id=123456789",
                "/autoreply/questions?seller_id=123456789",
                "/autoreply/questions/answered?seller_id=123456789",
                "/autoreply/conversations?seller_id=123456789",
                "/autoreply/conversations/pack-1?seller_id=123456789",
                "/autoreply/claims?seller_id=123456789",
                "/autoreply/claims/claim-1?seller_id=123456789",
                "/autoreply/claims/claim-1/messages?seller_id=123456789",
                "/autoreply/claims/claim-1/partial-refund-options?seller_id=123456789",
                "/autoreply/config/preferences?seller_id=123456789",
                "/autoreply/config/schedules?seller_id=123456789",
                "/autoreply/config/tags?seller_id=123456789",
                "/autoreply/config/predefined-answers?seller_id=123456789",
                "/autoreply/notifications?seller_id=123456789",
            )
        }

    assert all(response.status_code == 200 for response in responses.values())
    assert (
        responses["/autoreply/questions?seller_id=123456789"].json()["questions"][0]["question_id"]
        == "question-1"
    )
    assert (
        responses["/autoreply/conversations?seller_id=123456789"].json()["conversations"][0][
            "conversation_id"
        ]
        == "pack-1"
    )
    assert (
        responses["/autoreply/claims?seller_id=123456789"].json()["claims"][0]["claim_id"]
        == "claim-1"
    )
    assert (
        responses["/autoreply/config/preferences?seller_id=123456789"].json()["ai"]["secret_name"]
        is None
    )


@pytest.mark.asyncio
async def test_config_mutation_routes_persist_seller_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, db = _app(monkeypatch)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        preferences = await client.patch(
            "/autoreply/config/preferences",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "enabled": True,
                "auto_answer_questions": True,
                "auto_answer_messages": False,
                "auto_answer_claims": False,
                "ai": {
                    "enabled": True,
                    "auto_send_enabled": False,
                    "provider": "openai",
                    "model": "gpt-5.2",
                    "secret_name": "seller-ai-key",  # noqa: S105 - secret reference, not a value
                },
            },
        )
        schedule = await client.post(
            "/autoreply/config/schedules",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "123456789",
                "name": "business",
                "days": ["mon"],
                "start_time": "09:00",
                "end_time": "18:00",
                "timezone": "America/Monterrey",
                "enabled": True,
            },
        )

    assert preferences.status_code == 200
    assert preferences.json()["ai"]["secret_name"] == "seller-ai-key"  # noqa: S105
    assert schedule.status_code == 201
    assert db.autoreply_schedules.docs[0]["name"] == "business"


def _app(
    monkeypatch: pytest.MonkeyPatch,
    jwt_error: Exception | None = None,
    claims: object | None = None,
) -> tuple[FastAPI, FakeDb]:
    import zeler_autoreply.api as api
    from zeler_autoreply.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.include_router(build_router(clock=lambda: datetime(2026, 4, 24, 12, 30, tzinfo=UTC)))

    def fake_verify(_token: str) -> object:
        if jwt_error is not None:
            raise jwt_error
        return claims or _claims()

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    return app, db


def _claims(**overrides: Any) -> object:
    from zeler_platform_core.auth.jwt import ModuleClaims

    module_id = str(overrides.pop("module_id", "autoreply"))
    seller_id = int(overrides.pop("seller_id", 123456789))
    return ModuleClaims(
        module_id=module_id,
        seller_id=seller_id,
        iss=f"module:{module_id}",
        aud="gateway",
        iat=1,
        exp=2,
        token_type=str(overrides.pop("token_type", "module_admin")),
        scopes=list(overrides.pop("scopes", ["admin:autoreply"])),
        issued_by="zeler-app",
    )
