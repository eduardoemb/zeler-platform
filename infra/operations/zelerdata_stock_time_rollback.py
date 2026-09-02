from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Never

from zeler_sheets._stock_time_forward_engine import (
    _ForwardEngineError,
    _preflight_stock_time_runtime,
    _rollback_forward_operation,
)

_OPERATION_ID = re.compile(r"[0-9a-f]{64}")
_DIGEST_DOMAIN = b"zeler.stock_time_rollback.operation_id.v1\0"


@dataclass(frozen=True)
class _RuntimeDatabase:
    db: Any
    client: Any = field(repr=False)

    def close(self) -> None:
        self.client.close()


def create_runtime_db() -> _RuntimeDatabase:
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_db_name = os.environ.get("MONGO_DB")
    if not mongo_uri or not mongo_db_name:
        raise RuntimeError("runtime Mongo configuration is required")

    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri)
    return _RuntimeDatabase(db=client[mongo_db_name], client=client)


class _InvalidRequestError(Exception):
    def __init__(self, operation_id: str | None = None) -> None:
        self.operation_id = operation_id


class _BoundedParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise _InvalidRequestError


@dataclass(frozen=True)
class _Request:
    operation_id: str


def _parse(argv: Sequence[str] | None) -> _Request:
    parser = _BoundedParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--confirm-approved-runtime", action="store_true", required=True)
    parser.add_argument("--confirm-stock-time-rollback-operation-id", required=True)
    parsed = parser.parse_args(argv)
    operation_id = parsed.operation_id
    confirmation = parsed.confirm_stock_time_rollback_operation_id
    if (
        not isinstance(operation_id, str)
        or _OPERATION_ID.fullmatch(operation_id) is None
        or not parsed.confirm_approved_runtime
        or confirmation != operation_id
    ):
        raise _InvalidRequestError(
            operation_id
            if isinstance(operation_id, str) and _OPERATION_ID.fullmatch(operation_id)
            else None
        )
    return _Request(operation_id)


def _receipt(operation_id: str | None, preflight: str, outcome: str) -> dict[str, int | str | None]:
    digest = None
    if operation_id is not None:
        digest = hashlib.sha256(_DIGEST_DOMAIN + operation_id.encode("ascii")).hexdigest()
    return {
        "schema_version": 1,
        "operation": "stock_time_rollback",
        "operation_id_digest": digest,
        "preflight": preflight,
        "outcome": outcome,
    }


def _encode_receipt(receipt: dict[str, int | str | None]) -> str:
    return json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


async def _run(operation_id: str) -> tuple[str, str]:
    preflight = "not_run"
    outcome = "rollback_failed"
    handle: Any | None = None
    try:
        handle = create_runtime_db()
    except (Exception, SystemExit):  # noqa: BLE001 - terminal output is deliberately bounded
        return preflight, outcome
    try:
        try:
            readiness = await _preflight_stock_time_runtime(handle.db)
            ready = readiness.ready
        except (Exception, SystemExit):  # noqa: BLE001 - preflight detail must not escape
            preflight, outcome = "blocked", "preflight_blocked"
        else:
            if not ready:
                preflight, outcome = "blocked", "preflight_blocked"
            else:
                preflight = "passed"
                try:
                    await _rollback_forward_operation(handle.db, operation_id)
                except _ForwardEngineError:
                    outcome = "rollback_blocked"
                except (Exception, SystemExit):  # noqa: BLE001 - rollback detail must not escape
                    outcome = "rollback_failed"
                else:
                    outcome = "rolled_back"
    finally:
        try:
            handle.close()
        except (Exception, SystemExit):  # noqa: BLE001 - cleanup detail must not escape
            outcome = "rollback_failed"
    return preflight, outcome


def main(argv: Sequence[str] | None = None) -> int:
    try:
        request = _parse(argv)
    except _InvalidRequestError as exc:
        print(_encode_receipt(_receipt(exc.operation_id, "not_run", "invalid_request")))
        return 2
    preflight, outcome = asyncio.run(_run(request.operation_id))
    print(_encode_receipt(_receipt(request.operation_id, preflight, outcome)))
    return {"rolled_back": 0, "preflight_blocked": 3, "rollback_blocked": 4}.get(outcome, 1)


if __name__ == "__main__":
    raise SystemExit(main())
