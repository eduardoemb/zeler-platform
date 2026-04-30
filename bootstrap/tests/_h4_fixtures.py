from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import structlog
from structlog.testing import LogCapture

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.current = start
        self.monotonic_value = 0.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.monotonic_value

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        self.monotonic_value += seconds


def recording_sleep() -> AsyncMock:
    return AsyncMock(name="recording_sleep")


class LogCaptureContext:
    def __enter__(self) -> LogCapture:
        self.capture = LogCapture()
        structlog.configure(processors=[self.capture])
        return self.capture

    def __exit__(self, *_: object) -> None:
        structlog.reset_defaults()


class FakeBootstrapJobs:
    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.document: dict[str, Any] = document or {
            "_id": "job-1",
            "seller_id": "123",
            "state": "pending",
            "dag": {},
            "checkpoints": {},
            "stage_progress": {},
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        }
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        if filter_spec.get("_id") == self.document["_id"]:
            return deepcopy(self.document)
        return None

    async def find_one_and_update(
        self, filter_spec: dict[str, Any], update: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        if not self._matches(filter_spec):
            return None
        self.updates.append((deepcopy(filter_spec), deepcopy(update)))
        for key, value in update.get("$set", {}).items():
            self._set_path(key, value)
        for key, value in update.get("$inc", {}).items():
            current = self._get_path(key, 0)
            self._set_path(key, current + value)
        return deepcopy(self.document)

    def _matches(self, filter_spec: dict[str, Any]) -> bool:
        for key, expected in filter_spec.items():
            if key == "$expr":
                if not self._eval_expr(expected):
                    return False
                continue
            actual = self._get_path(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif actual != expected:
                return False
        return True

    def _eval_expr(self, expr: dict[str, Any]) -> bool:
        if "$lt" in expr:
            left, right = expr["$lt"]
            return cast(bool, self._eval_value(left) < self._eval_value(right))
        raise AssertionError(f"unsupported expr: {expr}")

    def _eval_value(self, value: Any) -> Any:
        if isinstance(value, dict) and "$ifNull" in value:
            candidate, default = value["$ifNull"]
            resolved = self._eval_value(candidate)
            return default if resolved is None else resolved
        if isinstance(value, str) and value.startswith("$"):
            return self._get_path(value[1:])
        return value

    def _get_path(self, key: str, default: Any = None) -> Any:
        target: Any = self.document
        for part in key.split("."):
            if not isinstance(target, dict) or part not in target:
                return default
            target = target[part]
        return target

    def _set_path(self, key: str, value: Any) -> None:
        target = self.document
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value


def log_capture() -> Iterator[LogCapture]:
    with LogCaptureContext() as capture:
        yield capture
