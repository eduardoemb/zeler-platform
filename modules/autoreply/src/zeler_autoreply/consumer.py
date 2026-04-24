from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class AutoreplyEvent:
    event_id: str
    event_type: str
    seller_id: int
    resource: str
    idempotency_key: str


class GatewayClient(Protocol):
    async def request(
        self, method: str, path: str, *, seller_id: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class IdempotencyStore(Protocol):
    async def is_duplicate(self, key: str) -> bool: ...

    async def mark_processed(self, key: str) -> None: ...


class AutoreplyEventHandler:
    def __init__(
        self,
        *,
        db: Any,
        gateway_client: GatewayClient,
        idempotency_store: IdempotencyStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateway_client = gateway_client
        self._idempotency_store = idempotency_store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, event: AutoreplyEvent) -> str:
        if await self._idempotency_store.is_duplicate(event.idempotency_key):
            return "duplicate"

        seller_id = str(event.seller_id)
        resource = await self._gateway_client.request(
            "GET", event.resource, seller_id=seller_id, json=None
        )
        templates = (
            await self._db["autoreply_templates"]
            .find({"seller_id": seller_id, "enabled": True})
            .to_list(length=100)
        )
        matched = select_matching_template(str(resource.get("text", "")), templates)
        resource_type = resource_type_from_event(event.event_type)
        resource_id = resource_id_from_resource(resource)

        if matched is None:
            await self._record_history(
                event=event,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome="no_match",
                template_id=None,
                answer_payload={},
            )
            await self._idempotency_store.mark_processed(event.idempotency_key)
            return "no_match"

        answer_payload = build_answer_payload(
            resource_type=resource_type,
            resource_id=resource_id,
            answer_text=str(matched["answer_text"]),
        )
        await self._gateway_client.request(
            "POST",
            "/answers",
            seller_id=seller_id,
            json=answer_payload,
        )
        await self._record_history(
            event=event,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome="answered",
            template_id=str(matched["_id"]),
            answer_payload=answer_payload,
        )
        await self._idempotency_store.mark_processed(event.idempotency_key)
        return "answered"

    async def _record_history(
        self,
        *,
        event: AutoreplyEvent,
        resource_type: str,
        resource_id: str,
        outcome: str,
        template_id: str | None,
        answer_payload: dict[str, Any],
    ) -> None:
        created_at = self._clock()
        await self._db["autoreply_history"].insert_one(
            {
                "_id": f"autoreply-history-{event.idempotency_key}",
                "seller_id": str(event.seller_id),
                "event_id": event.event_id,
                "idempotency_key": event.idempotency_key,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "template_id": template_id,
                "answer_payload": answer_payload,
                "created_at": created_at,
                "schema_version": 1,
            }
        )


def select_matching_template(text: str, templates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for template in templates:
        if template_matches(text, str(template["match_type"]), str(template["pattern"])):
            return template
    return None


def template_matches(text: str, match_type: str, pattern: str) -> bool:
    if match_type == "keyword":
        return pattern.casefold() in text.casefold()
    if match_type == "regex":
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return False


def resource_type_from_event(event_type: str) -> str:
    if event_type.startswith("messages."):
        return "message"
    return "question"


def resource_id_from_resource(resource: dict[str, Any]) -> str:
    value = resource.get("id", resource.get("_id"))
    return str(value)


def build_answer_payload(
    *, resource_type: str, resource_id: str, answer_text: str
) -> dict[str, Any]:
    key = "message_id" if resource_type == "message" else "question_id"
    return {key: resource_id, "text": answer_text}
