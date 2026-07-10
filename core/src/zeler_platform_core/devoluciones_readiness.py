from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

DEVOLUCIONES_LEASE_DURATION = timedelta(seconds=120)
DEVOLUCIONES_HEARTBEAT_INTERVAL = timedelta(seconds=30)
DEVOLUCIONES_READ_MODEL = "devoluciones"
DEVOLUCIONES_OPERATIONS_COLLECTION = "sheets_devoluciones_operations"
READ_MODEL_FRESHNESS_COLLECTION = "sheets_read_model_freshness"


class DevolucionesLeaseConflictError(RuntimeError):
    pass


class DevolucionesLeaseLostError(RuntimeError):
    pass


@dataclass(slots=True)
class DevolucionesOperationContext:
    seller_id: str
    scope: str
    operation_id: str
    attempt_token: str
    fence: int
    owns_lease: bool
    source_fingerprint: str | None = None
    required_coverage_start: datetime | None = None
    required_coverage_end: datetime | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    lease_lost: bool = False


def stable_devoluciones_operation_id(writer_kind: str, stable_source_id: str) -> str:
    basis = f"{writer_kind.strip()}:{stable_source_id.strip()}"
    if basis == ":":
        raise ValueError("operation identity basis must not be empty")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def new_devoluciones_attempt_token() -> str:
    return uuid4().hex


def operation_lease_guard(operation: DevolucionesOperationContext) -> dict[str, Any]:
    return {
        "seller_id": operation.seller_id,
        "scope": operation.scope,
        "operation_id": operation.operation_id,
        "attempt_token": operation.attempt_token,
        "fence": operation.fence,
        "state": "running",
        "$expr": {"$gt": ["$lease_until", "$$NOW"]},
    }


def takeover_checkpoint(
    existing: Mapping[str, Any] | None, *, source_fingerprint: str | None
) -> dict[str, Any] | None:
    if (
        source_fingerprint is None
        or existing is None
        or existing.get("source_fingerprint") != source_fingerprint
    ):
        return None
    checkpoint = existing.get("checkpoint")
    return dict(checkpoint) if isinstance(checkpoint, Mapping) else None


async def acquire_devoluciones_operation(
    *,
    db: Any,
    seller_id: str,
    scope: str,
    operation_id: str,
    attempt_token: str,
    source_fingerprint: str | None = None,
    invalidate_readiness: bool = True,
) -> DevolucionesOperationContext:
    seller_id = _required_identity(seller_id, "seller_id")
    scope = _required_identity(scope, "scope")
    operation_id = _required_identity(operation_id, "operation_id")
    attempt_token = _required_identity(attempt_token, "attempt_token")
    operations = db[DEVOLUCIONES_OPERATIONS_COLLECTION]
    freshness = db[READ_MODEL_FRESHNESS_COLLECTION]
    operation_key = {"seller_id": seller_id, "scope": scope}

    async with await _start_session(db) as session, session.start_transaction():
        valid_marker = await freshness.find_one(
            {
                "_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}",
                "seller_id": seller_id,
                "read_model": DEVOLUCIONES_READ_MODEL,
                "state": "reconciled",
                "$expr": {"$gt": ["$valid_until", "$$NOW"]},
            },
            session=session,
        )
        required_coverage_start, required_coverage_end = _marker_coverage(valid_marker)
        if invalidate_readiness:
            await freshness.update_one(
                {"_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}"},
                _stale_readiness_update(
                    seller_id=seller_id,
                    source="devoluciones_operation_acquire",
                ),
                upsert=True,
                session=session,
            )
        existing = await operations.find_one(operation_key, session=session)
        fence = int(existing.get("fence", 0)) + 1 if isinstance(existing, Mapping) else 1
        checkpoint = takeover_checkpoint(
            cast("Mapping[str, Any] | None", existing),
            source_fingerprint=source_fingerprint,
        )
        acquisition_filter: dict[str, Any] = dict(operation_key)
        if isinstance(existing, Mapping):
            acquisition_filter["fence"] = existing.get("fence")
            acquisition_filter["$or"] = [
                {"state": {"$ne": "running"}},
                {"$expr": {"$lte": ["$lease_until", "$$NOW"]}},
            ]
        lease_fields: dict[str, Any] = {
            "_id": f"{seller_id}:{scope}",
            **operation_key,
            "operation_id": operation_id,
            "attempt_token": attempt_token,
            "fence": fence,
            "state": "running",
            "lease_until": _server_time_plus(DEVOLUCIONES_LEASE_DURATION),
            "heartbeat_at": "$$NOW",
            "source_fingerprint": source_fingerprint,
            "checkpoint": checkpoint,
            "started_at": "$$NOW",
            "updated_at": "$$NOW",
            "finished_at": None,
            "error_code": None,
            "schema_version": 1,
        }
        try:
            result = await operations.update_one(
                acquisition_filter,
                [{"$set": lease_fields}],
                upsert=existing is None,
                session=session,
            )
        except Exception as exc:
            raise DevolucionesLeaseConflictError("operation lease is already owned") from exc
        if existing is not None and getattr(result, "matched_count", 0) != 1:
            raise DevolucionesLeaseConflictError("operation lease is already owned")

    return DevolucionesOperationContext(
        seller_id=seller_id,
        scope=scope,
        operation_id=operation_id,
        attempt_token=attempt_token,
        fence=fence,
        owns_lease=True,
        source_fingerprint=source_fingerprint,
        required_coverage_start=required_coverage_start,
        required_coverage_end=required_coverage_end,
        checkpoint=checkpoint or {},
    )


async def invalidate_devoluciones_readiness(
    *,
    db: Any,
    operation: DevolucionesOperationContext,
    source: str = "devoluciones_operation_invalidate",
) -> None:
    async def write(session: Any) -> None:
        await db[READ_MODEL_FRESHNESS_COLLECTION].update_one(
            {"_id": f"{operation.seller_id}:{DEVOLUCIONES_READ_MODEL}"},
            _stale_readiness_update(seller_id=operation.seller_id, source=source),
            upsert=True,
            session=session,
        )

    await guarded_devoluciones_write(
        db=db,
        operation=operation,
        seller_id=operation.seller_id,
        checkpoint={"phase": "readiness_invalidation", "source": source},
        writer=write,
    )


async def heartbeat_devoluciones_operation(
    *, db: Any, operation: DevolucionesOperationContext
) -> None:
    _ensure_live_owner(operation)
    result = await db[DEVOLUCIONES_OPERATIONS_COLLECTION].update_one(
        operation_lease_guard(operation),
        [
            {
                "$set": {
                    "heartbeat_at": "$$NOW",
                    "lease_until": _server_time_plus(DEVOLUCIONES_LEASE_DURATION),
                    "updated_at": "$$NOW",
                }
            }
        ],
    )
    if getattr(result, "matched_count", 0) != 1:
        operation.lease_lost = True
        raise DevolucionesLeaseLostError("devoluciones operation heartbeat lost its lease")


@asynccontextmanager
async def maintain_devoluciones_heartbeat(
    *,
    db: Any,
    operation: DevolucionesOperationContext,
    interval: timedelta = DEVOLUCIONES_HEARTBEAT_INTERVAL,
) -> AsyncIterator[None]:
    if interval.total_seconds() <= 0:
        raise ValueError("heartbeat interval must be positive")
    await heartbeat_devoluciones_operation(db=db, operation=operation)
    stopped = asyncio.Event()

    async def heartbeat_loop() -> None:
        while True:
            try:
                await asyncio.wait_for(stopped.wait(), timeout=interval.total_seconds())
            except TimeoutError:
                await heartbeat_devoluciones_operation(db=db, operation=operation)
                continue
            return

    task = asyncio.create_task(heartbeat_loop())
    try:
        yield
    finally:
        stopped.set()
        await task


async def finish_devoluciones_operation(
    *,
    db: Any,
    operation: DevolucionesOperationContext,
    succeeded: bool,
    error_code: str | None = None,
) -> None:
    _ensure_live_owner(operation)
    state = "succeeded" if succeeded else "failed"
    result = await db[DEVOLUCIONES_OPERATIONS_COLLECTION].update_one(
        operation_lease_guard(operation),
        [
            {
                "$set": {
                    "state": state,
                    "lease_until": "$$NOW",
                    "heartbeat_at": "$$NOW",
                    "updated_at": "$$NOW",
                    "finished_at": "$$NOW",
                    "error_code": None if succeeded else (error_code or "operation_failed"),
                }
            }
        ],
    )
    if getattr(result, "matched_count", 0) != 1:
        operation.lease_lost = True
        raise DevolucionesLeaseLostError("devoluciones operation release lost its lease")


async def guarded_devoluciones_write(
    *,
    db: Any,
    operation: DevolucionesOperationContext,
    seller_id: str,
    checkpoint: Mapping[str, Any],
    writer: Callable[[Any], Awaitable[Any] | Any],
) -> Any:
    _ensure_live_owner(operation)
    if _required_identity(seller_id, "seller_id") != operation.seller_id:
        raise DevolucionesLeaseLostError("mutation seller does not match operation seller")
    async with await _start_session(db) as session, session.start_transaction():
        result = await db[DEVOLUCIONES_OPERATIONS_COLLECTION].update_one(
            operation_lease_guard(operation),
            {
                "$set": {"checkpoint": dict(checkpoint)},
                "$currentDate": {"updated_at": True},
            },
            session=session,
        )
        if getattr(result, "matched_count", 0) != 1:
            operation.lease_lost = True
            raise DevolucionesLeaseLostError("devoluciones operation lease guard failed")
        write_result = writer(session)
        if inspect.isawaitable(write_result):
            return await write_result
        return write_result


def _ensure_live_owner(operation: DevolucionesOperationContext) -> None:
    if not operation.owns_lease:
        raise DevolucionesLeaseLostError("nested operation does not own the lease")
    if operation.lease_lost:
        raise DevolucionesLeaseLostError("devoluciones operation lease was lost")
    if operation.fence < 1:
        raise DevolucionesLeaseLostError("devoluciones operation fence is invalid")


def _required_identity(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _server_time_plus(duration: timedelta) -> dict[str, Any]:
    return {
        "$dateAdd": {
            "startDate": "$$NOW",
            "unit": "second",
            "amount": int(duration.total_seconds()),
        }
    }


def _stale_readiness_update(*, seller_id: str, source: str) -> list[dict[str, Any]]:
    return [
        {
            "$set": {
                "_id": f"{seller_id}:{DEVOLUCIONES_READ_MODEL}",
                "seller_id": seller_id,
                "read_model": DEVOLUCIONES_READ_MODEL,
                "state": "stale",
                "fresh_until": "$$NOW",
                "valid_until": "$$NOW",
                "updated_at": "$$NOW",
                "source": source,
                "schema_version": 1,
            }
        }
    ]


def _marker_coverage(marker: Any) -> tuple[datetime | None, datetime | None]:
    if not isinstance(marker, Mapping):
        return None, None
    start = _utc_datetime_or_none(marker.get("date_from"))
    end = _utc_datetime_or_none(marker.get("reconciled_until"))
    if start is None or end is None or start >= end:
        return None, None
    return start, end


def _utc_datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _start_session(db: Any) -> Any:
    client = getattr(db, "client", None)
    if client is None or not callable(getattr(client, "start_session", None)):
        raise RuntimeError("Mongo transaction-capable database client is required")
    session = client.start_session()
    if inspect.isawaitable(session):
        session = await session
    return session
