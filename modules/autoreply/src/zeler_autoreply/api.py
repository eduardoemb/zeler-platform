from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from zeler_autoreply.consumer import template_matches
from zeler_platform_core.auth.jwt import verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin


class TemplatePayload(BaseModel):
    seller_id: str
    template_name: str
    match_type: str
    pattern: str
    answer_text: str
    enabled: bool = True


class TemplatePatch(BaseModel):
    template_name: str | None = None
    match_type: str | None = None
    pattern: str | None = None
    answer_text: str | None = None
    enabled: bool | None = None


class PreviewPayload(BaseModel):
    match_type: str
    pattern: str
    answer_text: str
    sample_text: str


class PreferencesPayload(BaseModel):
    seller_id: str
    enabled: bool = True
    auto_answer_questions: bool = True
    auto_answer_messages: bool = False
    auto_answer_claims: bool = False
    ai: dict[str, Any] = {}


class SchedulePayload(BaseModel):
    seller_id: str
    name: str
    days: list[str]
    start_time: str
    end_time: str
    timezone: str
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = None
    days: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class TagPayload(BaseModel):
    seller_id: str
    name: str
    color: str
    enabled: bool = True


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    enabled: bool | None = None


class PredefinedAnswerPayload(BaseModel):
    seller_id: str
    short_answer: str
    text: str
    description: str | None = None
    tags: list[str] = []


class PredefinedAnswerPatch(BaseModel):
    short_answer: str | None = None
    text: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class SellerPayload(BaseModel):
    seller_id: str


def build_router(*, clock: Callable[[], datetime] | None = None) -> APIRouter:
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(prefix="/autoreply", tags=["autoreply"])

    @router.get("/dashboard")
    async def dashboard(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        questions = await _find_many(request, "questions", seller_id=seller_id)
        messages = await _find_many(request, "messages", seller_id=seller_id)
        claims = await _find_many(request, "claims", seller_id=seller_id)
        notifications = await _find_many(request, "autoreply_notifications", seller_id=seller_id)
        history = await _find_many(request, "autoreply_history", seller_id=seller_id)
        ai_suggestions = await _find_many(request, "autoreply_ai_suggestions", seller_id=seller_id)
        return JSONResponse(
            jsonable_encoder(
                {
                    "seller_id": seller_id,
                    "counters": {
                        "pending_questions": len(
                            [doc for doc in questions if str(doc.get("status")) == "UNANSWERED"]
                        ),
                        "open_conversations": len(_group_conversations(messages)),
                        "open_claims": len(
                            [
                                doc
                                for doc in claims
                                if str(doc.get("status", "")).lower()
                                not in {"closed", "resolved", "cancelled"}
                            ]
                        ),
                        "unread_notifications": len(
                            [doc for doc in notifications if doc.get("read_at") is None]
                        ),
                    },
                    "recent_activity": sorted(
                        history + notifications,
                        key=lambda doc: str(doc.get("created_at", "")),
                        reverse=True,
                    )[:10],
                    "auto_response_health": {
                        "last_outcome": history[0].get("outcome") if history else None,
                        "recent_failures": len(
                            [doc for doc in history if doc.get("outcome") == "failed"]
                        ),
                        "recent_total": len(history),
                    },
                    "ai_usage_summary": {
                        "suggested": len(ai_suggestions),
                        "auto_sent": len(
                            [doc for doc in ai_suggestions if doc.get("status") == "auto_sent"]
                        ),
                        "total": len(ai_suggestions),
                    },
                    "hydration_status": None,
                }
            )
        )

    @router.get("/questions")
    async def list_pending_questions(request: Request, seller_id: str) -> JSONResponse:
        return await _questions_response(request, seller_id=seller_id, answered=False)

    @router.get("/questions/answered")
    async def list_answered_questions(request: Request, seller_id: str) -> JSONResponse:
        return await _questions_response(request, seller_id=seller_id, answered=True)

    @router.get("/conversations")
    async def list_conversations(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        messages = await _find_many(request, "messages", seller_id=seller_id)
        conversations = _group_conversations(messages)
        return JSONResponse(
            jsonable_encoder(
                {
                    "seller_id": seller_id,
                    "conversations": conversations,
                    "pagination": _pagination(len(conversations)),
                }
            )
        )

    @router.get("/conversations/{conversation_id}")
    async def conversation_detail(
        request: Request, conversation_id: str, seller_id: str
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        messages = [
            _serialize_message(message)
            for message in await _find_many(request, "messages", seller_id=seller_id)
            if _conversation_id(message) == conversation_id
        ]
        return JSONResponse(
            jsonable_encoder(
                {
                    "seller_id": seller_id,
                    "conversation_id": conversation_id,
                    "messages": messages,
                    "ai_suggestion": None,
                    "state": None,
                }
            )
        )

    @router.get("/claims")
    async def list_claims(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        claims = [
            _serialize_claim(doc)
            for doc in await _find_many(request, "claims", seller_id=seller_id)
        ]
        return JSONResponse(
            jsonable_encoder(
                {"seller_id": seller_id, "claims": claims, "pagination": _pagination(len(claims))}
            )
        )

    @router.get("/claims/{claim_id}")
    async def claim_detail(request: Request, claim_id: str, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        claim = await _find_one_by_id(request, "claims", seller_id=seller_id, resource_id=claim_id)
        if claim is None:
            return JSONResponse(status_code=404, content={"error": "claim_not_found"})
        return JSONResponse(jsonable_encoder(_serialize_claim(claim)))

    @router.get("/claims/{claim_id}/messages")
    async def claim_messages(request: Request, claim_id: str, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return JSONResponse({"seller_id": seller_id, "claim_id": claim_id, "messages": []})

    @router.get("/claims/{claim_id}/partial-refund-options")
    async def partial_refund_options(
        request: Request, claim_id: str, seller_id: str
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        return JSONResponse({"seller_id": seller_id, "claim_id": claim_id, "available_offers": []})

    @router.get("/notifications")
    async def list_notifications(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        notifications = await _find_many(request, "autoreply_notifications", seller_id=seller_id)
        return JSONResponse(
            jsonable_encoder(
                {
                    "seller_id": seller_id,
                    "notifications": notifications,
                    "unread_count": len(
                        [
                            notification
                            for notification in notifications
                            if notification.get("read_at") is None
                        ]
                    ),
                }
            )
        )

    @router.post("/notifications/read-all")
    async def read_all_notifications(request: Request, payload: SellerPayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        return JSONResponse({"seller_id": payload.seller_id, "read": True})

    @router.post("/notifications/{notification_id}/read")
    async def read_notification(
        request: Request, notification_id: str, payload: SellerPayload
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        return JSONResponse(
            {"seller_id": payload.seller_id, "notification_id": notification_id, "read": True}
        )

    @router.get("/config/preferences")
    async def get_preferences(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["autoreply_preferences"].find_one(
            _seller_filter(seller_id)
        )
        return JSONResponse(jsonable_encoder(current or _default_preferences(seller_id)))

    @router.patch("/config/preferences")
    async def update_preferences(request: Request, payload: PreferencesPayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        doc = {
            **payload.model_dump(),
            "_id": f"autoreply-preferences-{payload.seller_id}",
            "updated_at": now(),
            "schema_version": 1,
        }
        await request.app.state.mongo_db["autoreply_preferences"].replace_one(
            {"_id": doc["_id"]}, doc, upsert=True
        )
        return JSONResponse(jsonable_encoder(doc))

    @router.get("/config/schedules")
    async def list_schedules(request: Request, seller_id: str) -> JSONResponse:
        return await _list_config_items(
            request,
            seller_id=seller_id,
            collection_name="autoreply_schedules",
            list_key="schedules",
        )

    @router.post("/config/schedules", status_code=201)
    async def create_schedule(request: Request, payload: SchedulePayload) -> JSONResponse:
        return await _create_config_item(
            request,
            now=now,
            payload=payload,
            collection_name="autoreply_schedules",
        )

    @router.patch("/config/schedules/{item_id}")
    async def update_schedule(
        request: Request, item_id: str, payload: SchedulePatch
    ) -> JSONResponse:
        return await _update_config_item(
            request,
            now=now,
            item_id=item_id,
            payload=payload,
            collection_name="autoreply_schedules",
            error_name="schedules_not_found",
        )

    @router.delete("/config/schedules/{item_id}", status_code=204)
    async def delete_schedule(request: Request, item_id: str) -> JSONResponse:
        return await _delete_config_item(
            request, item_id=item_id, collection_name="autoreply_schedules"
        )

    @router.get("/config/tags")
    async def list_tags(request: Request, seller_id: str) -> JSONResponse:
        return await _list_config_items(
            request, seller_id=seller_id, collection_name="autoreply_tags", list_key="tags"
        )

    @router.post("/config/tags", status_code=201)
    async def create_tag(request: Request, payload: TagPayload) -> JSONResponse:
        return await _create_config_item(
            request,
            now=now,
            payload=payload,
            collection_name="autoreply_tags",
        )

    @router.patch("/config/tags/{item_id}")
    async def update_tag(request: Request, item_id: str, payload: TagPatch) -> JSONResponse:
        return await _update_config_item(
            request,
            now=now,
            item_id=item_id,
            payload=payload,
            collection_name="autoreply_tags",
            error_name="tags_not_found",
        )

    @router.delete("/config/tags/{item_id}", status_code=204)
    async def delete_tag(request: Request, item_id: str) -> JSONResponse:
        return await _delete_config_item(request, item_id=item_id, collection_name="autoreply_tags")

    @router.get("/config/predefined-answers")
    async def list_predefined_answers(request: Request, seller_id: str) -> JSONResponse:
        return await _list_config_items(
            request,
            seller_id=seller_id,
            collection_name="autoreply_predefined_answers",
            list_key="predefined_answers",
        )

    @router.post("/config/predefined-answers", status_code=201)
    async def create_predefined_answer(
        request: Request, payload: PredefinedAnswerPayload
    ) -> JSONResponse:
        return await _create_config_item(
            request,
            now=now,
            payload=payload,
            collection_name="autoreply_predefined_answers",
        )

    @router.patch("/config/predefined-answers/{item_id}")
    async def update_predefined_answer(
        request: Request, item_id: str, payload: PredefinedAnswerPatch
    ) -> JSONResponse:
        return await _update_config_item(
            request,
            now=now,
            item_id=item_id,
            payload=payload,
            collection_name="autoreply_predefined_answers",
            error_name="predefined_answers_not_found",
        )

    @router.delete("/config/predefined-answers/{item_id}", status_code=204)
    async def delete_predefined_answer(request: Request, item_id: str) -> JSONResponse:
        return await _delete_config_item(
            request, item_id=item_id, collection_name="autoreply_predefined_answers"
        )

    @router.get("/templates")
    async def list_templates(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        templates = (
            await request.app.state.mongo_db["autoreply_templates"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        history = (
            await request.app.state.mongo_db["autoreply_history"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(
            jsonable_encoder([_with_recent_history(template, history) for template in templates])
        )

    @router.post("/templates", status_code=201)
    async def create_template(request: Request, payload: TemplatePayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        created_at = now()
        doc = {
            "_id": f"autoreply-template-{payload.seller_id}-{int(created_at.timestamp())}",
            "seller_id": payload.seller_id,
            "template_name": payload.template_name,
            "match_type": payload.match_type,
            "pattern": payload.pattern,
            "answer_text": payload.answer_text,
            "enabled": payload.enabled,
            "created_at": created_at,
            "updated_at": created_at,
            "schema_version": 1,
        }
        await request.app.state.mongo_db["autoreply_templates"].insert_one(doc)
        return JSONResponse(status_code=201, content=jsonable_encoder(doc))

    @router.patch("/templates/{template_id}")
    async def update_template(
        request: Request, template_id: str, payload: TemplatePatch
    ) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["autoreply_templates"].find_one(
            {"_id": template_id}
        )
        if current is None:
            return JSONResponse(status_code=404, content={"error": "autoreply_template_not_found"})
        updates = payload.model_dump(exclude_unset=True)
        updated = {**current, **updates, "updated_at": now()}
        await request.app.state.mongo_db["autoreply_templates"].replace_one(
            {"_id": template_id}, updated, upsert=True
        )
        return JSONResponse(jsonable_encoder(updated))

    @router.delete("/templates/{template_id}", status_code=204)
    async def delete_template(request: Request, template_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        current = await request.app.state.mongo_db["autoreply_templates"].find_one(
            {"_id": template_id}
        )
        if current is None:
            return JSONResponse(status_code=404, content={"error": "autoreply_template_not_found"})
        await request.app.state.mongo_db["autoreply_templates"].delete_one({"_id": template_id})
        return JSONResponse(status_code=204, content=None)

    @router.post("/templates/preview")
    async def preview_template(request: Request, payload: PreviewPayload) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        return JSONResponse(
            {
                "matched": template_matches(
                    payload.sample_text,
                    payload.match_type,
                    payload.pattern,
                ),
                "answer_text": payload.answer_text,
            }
        )

    return router


def _authorize(request: Request, seller_id: str | int | None = None) -> JSONResponse | None:
    return authorize_module_admin(
        request,
        expected_module_id="autoreply",
        seller_id=seller_id,
        verifier=verify_module_jwt,
    )


async def _questions_response(request: Request, *, seller_id: str, answered: bool) -> JSONResponse:
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    expected_status = "ANSWERED" if answered else "UNANSWERED"
    questions = [
        _serialize_question(question)
        for question in await _find_many(request, "questions", seller_id=seller_id)
        if str(question.get("status")) == expected_status
    ]
    return JSONResponse(
        jsonable_encoder(
            {
                "seller_id": seller_id,
                "questions": questions,
                "pagination": _pagination(len(questions)),
            }
        )
    )


async def _list_config_items(
    request: Request, *, seller_id: str, collection_name: str, list_key: str
) -> JSONResponse:
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    docs = await _find_many(request, collection_name, seller_id=seller_id)
    return JSONResponse(jsonable_encoder({"seller_id": seller_id, list_key: docs}))


async def _create_config_item(
    request: Request,
    *,
    now: Callable[[], datetime],
    payload: BaseModel,
    collection_name: str,
) -> JSONResponse:
    seller_id = str(payload.model_dump()["seller_id"])
    auth = _authorize(request, seller_id=seller_id)
    if auth is not None:
        return auth
    created_at = now()
    doc = {
        **payload.model_dump(),
        "_id": f"{collection_name}-{seller_id}-{int(created_at.timestamp())}",
        "created_at": created_at,
        "updated_at": created_at,
        "schema_version": 1,
    }
    await request.app.state.mongo_db[collection_name].insert_one(doc)
    return JSONResponse(status_code=201, content=jsonable_encoder(doc))


async def _update_config_item(
    request: Request,
    *,
    now: Callable[[], datetime],
    item_id: str,
    payload: BaseModel,
    collection_name: str,
    error_name: str,
) -> JSONResponse:
    auth = _authorize(request)
    if auth is not None:
        return auth
    current = await request.app.state.mongo_db[collection_name].find_one({"_id": item_id})
    if current is None:
        return JSONResponse(status_code=404, content={"error": error_name})
    updates = payload.model_dump(exclude_unset=True)
    updated = {**current, **updates, "updated_at": now()}
    await request.app.state.mongo_db[collection_name].replace_one(
        {"_id": item_id}, updated, upsert=True
    )
    return JSONResponse(jsonable_encoder(updated))


async def _delete_config_item(
    request: Request, *, item_id: str, collection_name: str
) -> JSONResponse:
    auth = _authorize(request)
    if auth is not None:
        return auth
    await request.app.state.mongo_db[collection_name].delete_one({"_id": item_id})
    return JSONResponse(status_code=204, content=None)


async def _find_many(
    request: Request, collection_name: str, *, seller_id: str
) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        await request.app.state.mongo_db[collection_name]
        .find(_seller_filter(seller_id))
        .to_list(length=100),
    )


async def _find_one_by_id(
    request: Request, collection_name: str, *, seller_id: str, resource_id: str
) -> dict[str, Any] | None:
    for doc in await _find_many(request, collection_name, seller_id=seller_id):
        if str(doc.get("_id")) == resource_id or str(doc.get("id")) == resource_id:
            return doc
    return None


def _seller_filter(seller_id: str) -> dict[str, Any]:
    values: list[str | int] = [seller_id]
    with contextlib.suppress(ValueError):
        values.append(int(seller_id))
    return {"seller_id": {"$in": values}}


def _pagination(total: int) -> dict[str, int]:
    return {"page": 1, "limit": 100, "total": total, "pages": 1 if total else 0}


def _serialize_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": str(question.get("_id", question.get("id", ""))),
        "seller_id": str(question.get("seller_id", "")),
        "item_id": _nullable_str(question.get("item_id")),
        "text": question.get("text"),
        "status": str(question.get("status", "")),
        "from_user_id": _nullable_str(question.get("from_user_id")),
        "date_created": question.get("date_created"),
        "answer": question.get("answer"),
        "read_state": "unread",
        "tags": [],
        "ai_suggestion": None,
    }


def _serialize_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(message.get("_id", message.get("id", ""))),
        "seller_id": str(message.get("seller_id", "")),
        "conversation_id": _conversation_id(message),
        "order_id": _nullable_str(message.get("order_id")),
        "from_user_id": str(message.get("from_user_id", "")),
        "to_user_id": str(message.get("to_user_id", "")),
        "text": message.get("text"),
        "status": str(message.get("status", "")),
        "date_created": message.get("date_created"),
        "read_at": message.get("read_at"),
    }


def _serialize_claim(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": str(claim.get("_id", claim.get("id", ""))),
        "seller_id": str(claim.get("seller_id", "")),
        "buyer_id": _nullable_str(claim.get("buyer_id")),
        "order_id": _nullable_str(claim.get("order_id")),
        "status": str(claim.get("status", "")),
        "stage": str(claim.get("stage", "")),
        "type": str(claim.get("type", "")),
        "date_created": claim.get("date_created"),
        "resolution": claim.get("resolution"),
        "read_state": "unread",
        "tags": [],
        "available_actions": list(claim.get("available_actions", [])),
        "ai_suggestion": None,
    }


def _group_conversations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        grouped.setdefault(_conversation_id(message), []).append(message)

    conversations: list[dict[str, Any]] = []
    for conversation_id, group in grouped.items():
        sorted_group = sorted(group, key=lambda doc: str(doc.get("date_created", "")), reverse=True)
        latest = sorted_group[0]
        conversations.append(
            {
                "conversation_id": conversation_id,
                "seller_id": str(latest.get("seller_id", "")),
                "order_id": _nullable_str(latest.get("order_id")),
                "last_message_text": latest.get("text"),
                "last_message_at": latest.get("date_created"),
                "message_count": len(group),
                "unread_count": len([doc for doc in group if doc.get("read_at") is None]),
                "read_state": "unread",
                "tags": [],
                "ai_suggestion": None,
            }
        )
    return conversations


def _conversation_id(message: dict[str, Any]) -> str:
    return str(
        message.get("pack_id")
        or message.get("order_id")
        or message.get("conversation_id")
        or message.get("_id")
        or ""
    )


def _default_preferences(seller_id: str) -> dict[str, Any]:
    return {
        "seller_id": seller_id,
        "enabled": True,
        "auto_answer_questions": True,
        "auto_answer_messages": False,
        "auto_answer_claims": False,
        "ai": {
            "enabled": False,
            "auto_send_enabled": False,
            "provider": "central",
            "model": None,
            "secret_name": None,
        },
    }


def _nullable_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _with_recent_history(template: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    template_history = [doc for doc in history if doc.get("template_id") == template.get("_id")]
    if not template_history:
        template_history = history[:5]
    return {**template, "recent_history": template_history[:5]}
