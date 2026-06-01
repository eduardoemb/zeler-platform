from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Any, cast
from uuid import uuid4

from zeler_publicador.schemas import SCHEMA_VERSION, PublicadorSettings

SECRET_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "cookies",
    "password",
    "refresh_token",
    "secret",
    "token",
}


class PublicadorReportingService:
    def __init__(
        self,
        mongo_db: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._mongo_db = mongo_db
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda prefix: f"{prefix}-{uuid4().hex}")

    async def list_logs(
        self,
        *,
        seller_id: str,
        account_id: str,
        status: str | None = None,
        sku: str | None = None,
        error: str | None = None,
        aggregate_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        events = await self._scoped_docs(
            "publicador_events", seller_id=seller_id, account_id=account_id
        )
        filtered = [
            self._public_event(event)
            for event in events
            if self._matches_event_filters(
                event,
                status=status,
                sku=sku,
                error=error,
                aggregate_type=aggregate_type,
                date_from=date_from,
                date_to=date_to,
            )
        ]
        filtered.sort(key=lambda event: self._created_at(event), reverse=True)
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "seller_id": seller_id,
            "account_id": account_id,
            "events": filtered[start:end],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_next": end < total,
            },
        }

    async def dashboard(self, *, seller_id: str, account_id: str) -> dict[str, Any]:
        drafts, batches, suggestions, batch_items, events = await self._read_scope(
            seller_id=seller_id, account_id=account_id
        )
        recent_activity = sorted(
            [self._public_event(event) for event in events],
            key=lambda event: self._created_at(event),
            reverse=True,
        )[:10]
        return {
            "seller_id": seller_id,
            "account_id": account_id,
            "counts": {
                "drafts": len(drafts),
                "pending_approval": sum(
                    1 for draft in drafts if draft.get("approval_status") == "pending"
                ),
                "batches": len(batches),
                "suggestions": len(suggestions),
                "failed_items": sum(
                    1 for item in batch_items if _is_failed_status(item.get("status"))
                ),
                "published_items": sum(
                    1 for item in batch_items if str(item.get("status")) == "published"
                ),
            },
            "recent_activity": recent_activity,
        }

    async def statistics(
        self,
        *,
        seller_id: str,
        account_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        drafts, batches, suggestions, batch_items, events = await self._read_scope(
            seller_id=seller_id, account_id=account_id
        )
        scoped_events = [
            event
            for event in events
            if _in_date_range(self._created_at(event), date_from=date_from, date_to=date_to)
        ]
        return {
            "seller_id": seller_id,
            "account_id": account_id,
            "status_breakdown": {
                "drafts": dict(Counter(str(draft.get("status")) for draft in drafts)),
                "batches": dict(Counter(str(batch.get("status")) for batch in batches)),
                "batch_items": dict(Counter(str(item.get("status")) for item in batch_items)),
                "suggestions": dict(
                    Counter(str(suggestion.get("status")) for suggestion in suggestions)
                ),
            },
            "trend": self._trend_by_day(scoped_events),
            "error_breakdown": self._error_breakdown(scoped_events),
        }

    async def get_settings(self, *, seller_id: str, account_id: str) -> dict[str, Any]:
        existing = await self._mongo_db["publicador_settings"].find_one(
            {"seller_id": seller_id, "account_id": account_id}
        )
        if existing is not None:
            return cast(dict[str, Any], existing)
        now = self._clock()
        return {
            "seller_id": seller_id,
            "account_id": account_id,
            "defaults": {},
            "ai_provider_ref": None,
            "catalog_behavior": "search_first",
            "created_at": now,
            "updated_at": now,
            "updated_by": None,
            "schema_version": SCHEMA_VERSION,
        }

    async def upsert_settings(self, settings: PublicadorSettings) -> dict[str, Any]:
        now = self._clock()
        existing = cast(
            dict[str, Any] | None,
            await self._mongo_db["publicador_settings"].find_one(
                {"seller_id": settings.seller_id, "account_id": settings.account_id}
            ),
        )
        document: dict[str, Any] = {
            **(existing or {}),
            **settings.model_dump(),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        document.setdefault("_id", self._id_factory("settings"))
        await self._mongo_db["publicador_settings"].replace_one(
            {"seller_id": settings.seller_id, "account_id": settings.account_id},
            document,
            upsert=True,
        )
        await self._append_event(
            seller_id=settings.seller_id,
            account_id=settings.account_id,
            operation="settings.updated",
            status="updated",
            actor_id=settings.updated_by or "module-admin",
        )
        return document

    async def _read_scope(
        self, *, seller_id: str, account_id: str
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        return (
            await self._scoped_docs(
                "publicador_drafts", seller_id=seller_id, account_id=account_id
            ),
            await self._scoped_docs(
                "publicador_batches", seller_id=seller_id, account_id=account_id
            ),
            await self._scoped_docs(
                "publicador_catalog_suggestions", seller_id=seller_id, account_id=account_id
            ),
            await self._scoped_docs(
                "publicador_batch_items", seller_id=seller_id, account_id=account_id
            ),
            await self._scoped_docs(
                "publicador_events", seller_id=seller_id, account_id=account_id
            ),
        )

    async def _scoped_docs(
        self, collection: str, *, seller_id: str, account_id: str
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._mongo_db[collection]
            .find({"seller_id": seller_id, "account_id": account_id})
            .to_list(length=5000),
        )

    def _matches_event_filters(
        self,
        event: dict[str, Any],
        *,
        status: str | None,
        sku: str | None,
        error: str | None,
        aggregate_type: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> bool:
        if status and str(event.get("status")) != status:
            return False
        if aggregate_type and str(event.get("aggregate_type")) != aggregate_type:
            return False
        event_sku = str(event.get("sku") or event.get("details", {}).get("sku") or "")
        if sku and sku.lower() not in event_sku.lower():
            return False
        event_error = " ".join(
            str(value)
            for value in [
                event.get("error_code"),
                event.get("error"),
                event.get("reason"),
                event.get("response_summary"),
            ]
            if value
        )
        if error and error.lower() not in event_error.lower():
            return False
        return _in_date_range(self._created_at(event), date_from=date_from, date_to=date_to)

    def _public_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _redact(event))

    def _created_at(self, doc: dict[str, Any]) -> datetime:
        value = doc.get("created_at") or doc.get("updated_at")
        return _coerce_datetime(value)

    def _trend_by_day(self, events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        trend: dict[str, Counter[str]] = {}
        for event in events:
            key = self._created_at(event).date().isoformat()
            trend.setdefault(key, Counter())[str(event.get("status"))] += 1
        return {day: dict(counts) for day, counts in sorted(trend.items())}

    @staticmethod
    def _error_breakdown(events: list[dict[str, Any]]) -> dict[str, int]:
        counter: Counter[str] = Counter(
            str(event.get("error_code")) for event in events if event.get("error_code")
        )
        return dict(counter)

    async def _append_event(
        self,
        *,
        seller_id: str,
        account_id: str,
        operation: str,
        status: str,
        actor_id: str,
    ) -> None:
        await self._mongo_db["publicador_events"].insert_one(
            {
                "_id": self._id_factory("event"),
                "seller_id": seller_id,
                "account_id": account_id,
                "aggregate_type": "settings",
                "aggregate_id": f"{seller_id}:{account_id}",
                "operation": operation,
                "status": status,
                "actor_id": actor_id,
                "created_at": self._clock(),
                "schema_version": SCHEMA_VERSION,
            }
        )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(child) for key, child in value.items() if key.lower() not in SECRET_KEYS
        }
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _in_date_range(
    value: datetime, *, date_from: datetime | None, date_to: datetime | None
) -> bool:
    if date_from and value < date_from:
        return False
    return not (date_to and value > date_to)


def _is_failed_status(value: Any) -> bool:
    status = str(value)
    return status in {"failed", "publish_failed", "validation_failed", "retryable"}
