"""Production MongoDB smoke validation CLI.

Purpose: validate the day-1 production MongoDB replica set bring-up by checking
connectivity/auth, replica-set health, sentinel write/read/delete behavior,
transactions, change streams, and cleanup.

Entry point: run `uv run python infra/mongo/smoke_prod.py`, which calls
`main()` and returns a stable process exit code.

Exit-code taxonomy:
- 0 OK: all checks passed.
- 10 connectivity: mongod cannot be reached.
- 11 auth: admin credentials are rejected.
- 20 rs.status: `rs.status()` fails or reports unhealthy data.
- 21 not-primary: replica-set member is not PRIMARY.
- 30 roundtrip: sentinel insert/read/delete/count roundtrip fails.
- 40 transaction: multi-document transaction fails.
- 50 change-stream: change-stream event is not received within timeout.
- 60 cleanup: `_smoke` cleanup fails.
- 99 unexpected: unclassified smoke-script error.

Environment variables:
- MONGO_URI: MongoDB URI, defaulting to localhost prod port with rs0/directConnection.
- MONGO_ADMIN_USER: admin username.
- MONGO_ADMIN_PASSWORD: admin password.
- MONGO_SMOKE_TIMEOUT_S: change-stream timeout in seconds, default `5`.
- MONGO_SMOKE_DB: sentinel database name, default `_smoke`.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

import pymongo
from pymongo.errors import ConnectionFailure, OperationFailure

EXIT_OK = 0
EXIT_CONNECTIVITY = 10
EXIT_AUTH = 11
EXIT_RS_STATUS = 20
EXIT_NOT_PRIMARY = 21
EXIT_ROUNDTRIP = 30
EXIT_TRANSACTION = 40
EXIT_CHANGE_STREAM = 50
EXIT_CLEANUP = 60
EXIT_UNEXPECTED = 99

DEFAULT_SMOKE_DB = "_smoke"
ROUNDTRIP_COLLECTION = "_smoke_sentinel"
CHANGE_STREAM_COLLECTION = "cs_target"


class SmokeCheckError(Exception):
    def __init__(self, tag: str, detail: object, code: int) -> None:
        super().__init__(str(detail))
        self.tag = tag
        self.detail = detail
        self.code = code


def _die_with_tag(tag: str, detail: object, code: int) -> int:
    print(f"error: {tag}: {detail}", file=sys.stderr)
    return code


def check_connectivity(client: Any) -> None:
    client.admin.command("ping")


def _connect(uri: str, user: str, password: str) -> Any:
    client: Any = pymongo.MongoClient(uri, username=user, password=password, authSource="admin")
    check_connectivity(client)
    return client


def check_rs_status(client: Any) -> None:
    try:
        status = client.admin.command("replSetGetStatus")
    except Exception as exc:  # noqa: BLE001 - all rs.status failures share a smoke code
        raise SmokeCheckError("rs.status", exc, EXIT_RS_STATUS) from exc

    if status.get("ok") != 1:
        raise SmokeCheckError("rs.status", f"ok={status.get('ok')}", EXIT_RS_STATUS)
    if status.get("myState") != 1:
        raise SmokeCheckError("not-primary", f"myState={status.get('myState')}", EXIT_NOT_PRIMARY)
    members = status.get("members") or []
    first_member = members[0] if members else {}
    if first_member.get("health") != 1:
        raise SmokeCheckError(
            "rs.status",
            f"members[0].health={first_member.get('health')}",
            EXIT_RS_STATUS,
        )


def check_roundtrip(client: Any, db_name: str) -> None:
    collection = client[db_name][ROUNDTRIP_COLLECTION]
    document = {"_id": "roundtrip", "ok": True}
    try:
        collection.insert_one(document)
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("roundtrip", f"insert: {exc}", EXIT_ROUNDTRIP) from exc
    try:
        found = collection.find_one({"_id": document["_id"]})
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("roundtrip", f"find: {exc}", EXIT_ROUNDTRIP) from exc
    if found != document:
        raise SmokeCheckError("roundtrip", "find: sentinel not found", EXIT_ROUNDTRIP)
    try:
        collection.delete_many({"_id": document["_id"]})
        remaining = collection.count_documents({"_id": document["_id"]})
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("roundtrip", f"delete: {exc}", EXIT_ROUNDTRIP) from exc
    if remaining != 0:
        raise SmokeCheckError("roundtrip", f"delete: remaining={remaining}", EXIT_ROUNDTRIP)


def check_transaction(client: Any, db_name: str) -> None:
    db = client[db_name]
    try:
        with client.start_session() as session, session.start_transaction():
            db["tx_a"].insert_one({"_id": "tx-a", "ok": True}, session=session)
            db["tx_b"].insert_one({"_id": "tx-b", "ok": True}, session=session)
        if db["tx_a"].find_one({"_id": "tx-a"}) != {"_id": "tx-a", "ok": True}:
            raise RuntimeError("tx_a missing after commit")
        if db["tx_b"].find_one({"_id": "tx-b"}) != {"_id": "tx-b", "ok": True}:
            raise RuntimeError("tx_b missing after commit")
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("transaction", exc, EXIT_TRANSACTION) from exc


def check_change_stream(client: Any, db_name: str, timeout_s: float) -> None:
    collection = client[db_name][CHANGE_STREAM_COLLECTION]

    def insert_sentinel() -> None:
        time.sleep(0.2)
        session = client.start_session()
        try:
            collection.insert_one({"_id": "change-stream", "ok": True}, session=session)
        finally:
            close_session = getattr(session, "end_session", None) or getattr(session, "close", None)
            if close_session is not None:
                close_session()

    inserter = threading.Thread(target=insert_sentinel, daemon=True)
    try:
        with collection.watch() as stream:
            inserter.start()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() <= deadline:
                event = stream.try_next()
                if event is not None:
                    inserter.join(timeout=1)
                    return
                time.sleep(0.05)
            inserter.join(timeout=1)
            raise SmokeCheckError("change-stream", "timeout", EXIT_CHANGE_STREAM)
    except SmokeCheckError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("change-stream", exc, EXIT_CHANGE_STREAM) from exc


def cleanup(client: Any, db_name: str) -> None:
    try:
        client.drop_database(db_name)
    except Exception as exc:  # noqa: BLE001
        raise SmokeCheckError("cleanup", exc, EXIT_CLEANUP) from exc


def main() -> int:
    uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27019/?replicaSet=rs0&directConnection=true")
    user = os.getenv("MONGO_ADMIN_USER", "")
    password = os.getenv("MONGO_ADMIN_PASSWORD", "")
    db_name = os.getenv("MONGO_SMOKE_DB", DEFAULT_SMOKE_DB)
    timeout_s = float(os.getenv("MONGO_SMOKE_TIMEOUT_S", "5"))

    try:
        client: Any = _connect(uri, user, password)
    except ConnectionFailure as exc:
        return _die_with_tag("connectivity", exc, EXIT_CONNECTIVITY)
    except OperationFailure as exc:
        return _die_with_tag("auth", exc, EXIT_AUTH)
    except Exception as exc:  # noqa: BLE001 - smoke script must map unexpected failures
        return _die_with_tag("unexpected", exc, EXIT_UNEXPECTED)

    exit_code = EXIT_OK
    try:
        cleanup(client, db_name)
        check_rs_status(client)
        check_roundtrip(client, db_name)
        check_transaction(client, db_name)
        check_change_stream(client, db_name, timeout_s)
    except SmokeCheckError as exc:
        exit_code = _die_with_tag(exc.tag, exc.detail, exc.code)
    except Exception as exc:  # noqa: BLE001 - final safety net for stable taxonomy
        exit_code = _die_with_tag("unexpected", exc, EXIT_UNEXPECTED)
    finally:
        try:
            cleanup(client, db_name)
        except Exception as exc:  # noqa: BLE001 - cleanup failure has a dedicated code
            if exit_code == EXIT_OK:
                exit_code = _die_with_tag("cleanup", exc, EXIT_CLEANUP)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
