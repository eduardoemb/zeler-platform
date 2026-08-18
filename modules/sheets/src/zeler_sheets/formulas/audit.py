from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = 1
AUDIT_COLLECTION = "sheets_formula_audit"
_REDACTED_EVENT_KEYS = {"Authorization", "authorization", "token", "token_once", "bearer_token"}


class FormulaAuditService:
    def __init__(self, *, db: Any, now_fn: Callable[[], datetime] | None = None) -> None:
        self._collection = db[AUDIT_COLLECTION]
        self._now = now_fn or (lambda: datetime.now(UTC))

    async def record(self, event: dict[str, Any]) -> None:
        occurred_at = event.get("occurred_at") or self._now()
        request_id = event.get("request_id")
        doc = {
            "_id": _audit_id(event, occurred_at=occurred_at),
            "token_id": str(event["token_id"]),
            "seller_id": str(event["seller_id"]),
            "seller_nickname": event.get("seller_nickname"),
            "formula": str(event["formula"]),
            "request_id": request_id,
            "outcome": str(event["outcome"]),
            "error_code": event.get("error_code"),
            "occurred_at": occurred_at,
            "schema_version": SCHEMA_VERSION,
        }
        for key in _REDACTED_EVENT_KEYS:
            doc.pop(key, None)
        try:
            await self._collection.insert_one(doc)
        except DuplicateKeyError:
            return
        except PyMongoError as exc:
            logger.warning(
                "formula.audit.write_failed",
                exception_type=type(exc).__name__,
                outcome=doc["outcome"],
                error_code=doc["error_code"],
            )


def _audit_id(event: dict[str, Any], *, occurred_at: datetime) -> str:
    request_id = event.get("request_id")
    if request_id:
        return f"formula-audit-{request_id}"
    token_id = str(event.get("token_id", "unknown-token"))
    formula = str(event.get("formula", "unknown-formula"))
    timestamp = int(occurred_at.timestamp() * 1_000_000)
    return f"formula-audit-{token_id}-{formula}-{timestamp}"
