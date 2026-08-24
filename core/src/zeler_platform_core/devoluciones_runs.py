from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Protocol

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
