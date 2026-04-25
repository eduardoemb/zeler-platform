"""Idempotent replica-set bootstrap for the production MongoDB container.

Exit codes from ``main()``:
    0 — success (or idempotent no-op).
    1 — mongod did not become reachable within the timeout.
    2 — required env var missing (``MONGO_ADMIN_USER`` / ``MONGO_ADMIN_PASSWORD``).
    3 — unhandled ``OperationFailure`` from ``replSetInitiate`` or ``createUser``.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

LOGGER = logging.getLogger(__name__)
ALREADY_INITIALIZED = 23
USER_ALREADY_EXISTS = 51003
DEFAULT_INIT_URI = "mongodb://127.0.0.1:27019/?directConnection=true"
DEFAULT_MEMBER_HOST = "127.0.0.1:27019"
DEFAULT_TIMEOUT_S = 30.0
MISSING_CREDENTIALS_MESSAGE = "error: MONGO_ADMIN_USER and MONGO_ADMIN_PASSWORD required"


def ensure_admin_user(
    client: Any,
    username: str,
    password: str,
    roles: tuple[str, ...] = ("root",),
) -> None:
    """Create the admin user with the supplied credentials."""
    try:
        client.admin.command(
            {
                "createUser": username,
                "pwd": password,
                "roles": [{"role": role, "db": "admin"} for role in roles],
            }
        )
    except OperationFailure as exc:
        if exc.code == USER_ALREADY_EXISTS:
            LOGGER.info("admin user already exists")
            return
        raise


def initiate_replica_set(
    client: Any,
    rs_name: str = "rs0",
    host: str = DEFAULT_MEMBER_HOST,
) -> None:
    """Initialize a single-node replica set."""
    try:
        client.admin.command(
            {
                "replSetInitiate": {
                    "_id": rs_name,
                    "members": [{"_id": 0, "host": host}],
                }
            }
        )
    except OperationFailure as exc:
        if exc.code == ALREADY_INITIALIZED:
            LOGGER.info("replica set already initialized")
            return
        raise


def wait_for_mongod(
    client: Any,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Poll ``client`` until mongod responds to ping, or raise ``TimeoutError``."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            client.admin.command("ping")
            return
        except PyMongoError as exc:
            if time.monotonic() >= deadline:
                msg = "mongod did not become ready before timeout"
                raise TimeoutError(msg) from exc
            time.sleep(1)


def main() -> None:
    """Initialize the prod Mongo replica set and admin user from environment."""
    logging.basicConfig(level=logging.INFO)
    username = os.environ.get("MONGO_ADMIN_USER")
    password = os.environ.get("MONGO_ADMIN_PASSWORD")
    if not username or not password:
        print(MISSING_CREDENTIALS_MESSAGE, file=sys.stderr)
        sys.exit(2)

    init_uri = os.environ.get("MONGO_INIT_URI", DEFAULT_INIT_URI)
    member_host = os.environ.get("MONGO_RS_MEMBER_HOST", DEFAULT_MEMBER_HOST)
    timeout_s = float(os.environ.get("MONGO_INIT_TIMEOUT_S", DEFAULT_TIMEOUT_S))

    client: MongoClient[Any] = MongoClient(init_uri)
    try:
        wait_for_mongod(client, timeout_s=timeout_s)
    except TimeoutError as exc:
        print(
            f"error: mongod timeout — target {member_host} did not respond "
            f"within {timeout_s}s ({exc})",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        initiate_replica_set(client, host=member_host)
        ensure_admin_user(client, username, password)
    except OperationFailure as exc:
        print(f"error: unhandled mongod operation failure: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
