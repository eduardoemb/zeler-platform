from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Protocol

from zeler_platform_core.devoluciones_readiness import (
    DevolucionesOperationContext,
    operation_lease_guard,
)

WINDOW_DAYS = 10
INVOCATION_SECONDS = 175
CADENCE_SECONDS = 720
FINALIZATION_SECONDS = 895
RUN_STATES = frozenset({"authorized", "active", "finalizing", "completed", "failed", "expired"})
WINDOW_STATES = frozenset({"prepared", "completed"})


class RunBindingDriftError(ValueError):
    pass


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _digest(*values: object) -> str:
    return sha256("|".join(str(value) for value in values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RunBinding:
    authorization_id: str
    cohort_id: str
    seller_id: str
    scope: str
    start: datetime
    end: datetime
    partition_version: str
    release_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        for field in ("authorization_id", "cohort_id", "seller_id", "scope", "partition_version"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        start, end = _utc(self.start, "start"), _utc(self.end, "end")
        if start >= end:
            raise ValueError("start must be before end")
        fingerprints = {str(key): str(value) for key, value in self.release_fingerprints.items()}
        if not fingerprints or not all(fingerprints.values()):
            raise ValueError("release_fingerprints are required")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "release_fingerprints", MappingProxyType(fingerprints))

    @property
    def run_id(self) -> str:
        fingerprints = ",".join(
            f"{key}={value}" for key, value in sorted(self.release_fingerprints.items())
        )
        return _digest(
            "v1",
            self.authorization_id,
            self.cohort_id,
            self.seller_id,
            self.scope,
            self.start.isoformat(),
            self.end.isoformat(),
            self.partition_version,
            fingerprints,
        )

    def require_match(self, candidate: RunBinding) -> None:
        if self != candidate:
            raise RunBindingDriftError("run identity, coverage, or fingerprint drift")


@dataclass(frozen=True, slots=True)
class RunWindow:
    run_id: str
    index: int
    start: datetime
    end: datetime

    @property
    def window_id(self) -> str:
        return _digest(self.run_id, self.index, self.start.isoformat(), self.end.isoformat())


def partition_windows(binding: RunBinding) -> tuple[RunWindow, ...]:
    windows: list[RunWindow] = []
    start = binding.start
    while start < binding.end:
        end = min(start + timedelta(days=WINDOW_DAYS), binding.end)
        windows.append(RunWindow(binding.run_id, len(windows), start, end))
        start = end
    return tuple(windows)


def allowed_seconds(window_count: int) -> int:
    if window_count < 1:
        raise ValueError("window_count must be positive")
    return 895 * window_count + 175


def expires_at(binding: RunBinding, *, created_at: datetime) -> datetime:
    return _utc(created_at, "created_at") + timedelta(
        seconds=allowed_seconds(len(partition_windows(binding)))
    )


def is_expired(now: datetime, deadline: datetime) -> bool:
    return _utc(now, "now") >= _utc(deadline, "deadline")


class RunRepository(Protocol):
    async def create(self, binding: RunBinding, *, created_at: datetime) -> None: ...

    async def read(self, run_id: str) -> Mapping[str, object] | None: ...


class RunWindowRepository(Protocol):
    async def read_next(self, run_id: str, *, fence: int) -> RunWindow | None: ...

    async def prepare(self, window: RunWindow, *, fence: int, idempotency_key: str) -> bool: ...


RUNS_COLLECTION = "sheets_devoluciones_runs"
RUN_WINDOWS_COLLECTION = "sheets_devoluciones_run_windows"


class MongoRunWindowRepository:
    """Persist deterministic run windows only while the operation lease remains fenced."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def create(
        self,
        binding: RunBinding,
        *,
        operation: DevolucionesOperationContext,
        created_at: datetime | None = None,
    ) -> bool:
        created_at = _utc(created_at or datetime.now(UTC), "created_at")
        windows = partition_windows(binding)
        async with await _session(self._db) as session, session.start_transaction():
            if not await self._guard(operation, session):
                return False
            result = await self._db[RUNS_COLLECTION].update_one(
                {"_id": binding.run_id},
                {
                    "$setOnInsert": {
                        "_id": binding.run_id,
                        "authorization_id": binding.authorization_id,
                        "cohort_id": binding.cohort_id,
                        "seller_id": binding.seller_id,
                        "scope": binding.scope,
                        "start": binding.start,
                        "end": binding.end,
                        "partition_version": binding.partition_version,
                        "release_fingerprints": dict(binding.release_fingerprints),
                        "window_count": len(windows),
                        "state": "authorized",
                        "next_window_index": 0,
                        "created_at": created_at,
                        "expires_at": expires_at(binding, created_at=created_at),
                        "schema_version": 1,
                    }
                },
                upsert=True,
                session=session,
            )
            return getattr(result, "acknowledged", True) is not False

    async def prepare(
        self,
        window: RunWindow,
        *,
        operation: DevolucionesOperationContext,
        idempotency_key: str,
    ) -> bool:
        async with await _session(self._db) as session, session.start_transaction():
            if not await self._guard(operation, session):
                return False
            existing = await self._db[RUN_WINDOWS_COLLECTION].find_one(
                {"_id": window.window_id}, session=session
            )
            if existing is not None:
                return _prepared_window_matches(existing, window, idempotency_key)
            await self._db[RUN_WINDOWS_COLLECTION].update_one(
                {"_id": window.window_id},
                {
                    "$setOnInsert": {
                        "_id": window.window_id,
                        "run_id": window.run_id,
                        "index": window.index,
                        "start": window.start,
                        "end": window.end,
                        "state": "prepared",
                        "fence": operation.fence,
                        "idempotency_key": idempotency_key,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                        "schema_version": 1,
                    }
                },
                upsert=True,
                session=session,
            )
            return True

    async def read_next(
        self, run_id: str, *, operation: DevolucionesOperationContext
    ) -> RunWindow | None:
        async with await _session(self._db) as session, session.start_transaction():
            if not await self._guard(operation, session):
                return None
            run = await self._db[RUNS_COLLECTION].find_one({"_id": run_id}, session=session)
            if run is None:
                return None
            start, end = _mongo_utc(run["start"]), _mongo_utc(run["end"])
            for index in range(int(run["window_count"])):
                window = RunWindow(
                    run_id, index, start, min(start + timedelta(days=WINDOW_DAYS), end)
                )
                document = await self._db[RUN_WINDOWS_COLLECTION].find_one(
                    {"run_id": run_id, "index": index}, session=session
                )
                if document is None or document["state"] != "completed":
                    return window
                start = window.end
            return None

    async def _guard(self, operation: DevolucionesOperationContext, session: Any) -> bool:
        result = await self._db["sheets_devoluciones_operations"].update_one(
            operation_lease_guard(operation),
            {"$currentDate": {"updated_at": True}},
            session=session,
        )
        return getattr(result, "matched_count", 0) == 1


def _prepared_window_matches(
    document: Mapping[str, Any], window: RunWindow, idempotency_key: str
) -> bool:
    return (
        document.get("run_id") == window.run_id
        and document.get("index") == window.index
        and isinstance(document.get("start"), datetime)
        and _mongo_utc(document["start"]) == window.start
        and isinstance(document.get("end"), datetime)
        and _mongo_utc(document["end"]) == window.end
        and document.get("idempotency_key") == idempotency_key
    )


def _mongo_utc(value: datetime) -> datetime:
    """BSON dates decode as naive UTC unless the client enables tz_aware."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _session(db: Any) -> Any:
    client = getattr(db, "client", None)
    if client is None or not callable(getattr(client, "start_session", None)):
        raise RuntimeError("Mongo transaction-capable database client is required")
    session = client.start_session()
    return await session if hasattr(session, "__await__") else session
