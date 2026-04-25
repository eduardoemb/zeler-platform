from __future__ import annotations

from typing import Any

import pytest
from infra.mongo.init_replica_set import (
    ensure_admin_user,
    initiate_replica_set,
    main,
    wait_for_mongod,
)
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError


class FakeAdmin:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.commands: list[tuple[object, tuple[Any, ...], dict[str, Any]]] = []

    def command(self, command: object, *args: Any, **kwargs: Any) -> dict[str, int]:
        self.commands.append((command, args, kwargs))
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
        return {"ok": 1}


class FakeMongoClient:
    def __init__(self, responses: list[object]) -> None:
        self.admin = FakeAdmin(responses)


def test_wait_for_mongod_times_out_when_client_never_responds() -> None:
    client = FakeMongoClient([ServerSelectionTimeoutError("offline")] * 3)

    with pytest.raises(TimeoutError, match="mongod did not become ready"):
        wait_for_mongod(client, timeout_s=0)

    assert client.admin.commands == [("ping", (), {})]


def test_wait_for_mongod_succeeds_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeMongoClient(
        [
            ServerSelectionTimeoutError("offline"),
            ServerSelectionTimeoutError("still offline"),
        ]
    )
    monkeypatch.setattr("infra.mongo.init_replica_set.time.sleep", lambda _seconds: None)

    wait_for_mongod(client, timeout_s=10)

    assert client.admin.commands == [("ping", (), {}), ("ping", (), {}), ("ping", (), {})]


def test_initiate_replica_set_fresh_node_uses_single_member_payload() -> None:
    client = FakeMongoClient([])

    initiate_replica_set(client)

    assert client.admin.commands == [
        (
            {
                "replSetInitiate": {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "localhost:27017"}],
                }
            },
            (),
            {},
        )
    ]


def test_initiate_replica_set_honors_custom_replica_set_name_and_host() -> None:
    client = FakeMongoClient([])

    initiate_replica_set(client, rs_name="prod-rs", host="127.0.0.1:27019")

    assert client.admin.commands == [
        (
            {
                "replSetInitiate": {
                    "_id": "prod-rs",
                    "members": [{"_id": 0, "host": "127.0.0.1:27019"}],
                }
            },
            (),
            {},
        )
    ]


def test_initiate_replica_set_is_idempotent_for_already_initialized() -> None:
    client = FakeMongoClient([OperationFailure("already initialized", code=23)])

    initiate_replica_set(client)

    assert len(client.admin.commands) == 1


def test_initiate_replica_set_reraises_unexpected_operation_failure() -> None:
    client = FakeMongoClient([OperationFailure("not yet initialized", code=11)])

    with pytest.raises(OperationFailure, match="not yet initialized"):
        initiate_replica_set(client)


def test_ensure_admin_user_creates_fresh_admin_user_from_credentials() -> None:
    client = FakeMongoClient([])

    ensure_admin_user(client, "admin", "s3cret")

    assert client.admin.commands == [
        (
            {
                "createUser": "admin",
                "pwd": "s3cret",
                "roles": [{"role": "root", "db": "admin"}],
            },
            (),
            {},
        )
    ]


def test_ensure_admin_user_is_idempotent_for_existing_user() -> None:
    client = FakeMongoClient([OperationFailure("user exists", code=51003)])

    ensure_admin_user(client, "admin", "s3cret")

    assert len(client.admin.commands) == 1


def test_ensure_admin_user_reraises_unexpected_operation_failure() -> None:
    client = FakeMongoClient([OperationFailure("not authorized", code=13)])

    with pytest.raises(OperationFailure, match="not authorized"):
        ensure_admin_user(client, "admin", "s3cret")


def test_main_exits_2_with_clear_stderr_when_admin_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MONGO_ADMIN_USER", raising=False)
    monkeypatch.delenv("MONGO_ADMIN_PASSWORD", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "MONGO_ADMIN_USER and MONGO_ADMIN_PASSWORD required" in capsys.readouterr().err


def test_main_uses_init_uri_and_runs_bootstrap_steps_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient([])
    observed_uris: list[str] = []

    def mongo_client(uri: str) -> FakeMongoClient:
        observed_uris.append(uri)
        return client

    monkeypatch.setattr("infra.mongo.init_replica_set.MongoClient", mongo_client)
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")

    main()

    assert observed_uris == ["mongodb://127.0.0.1:27019/?directConnection=true"]
    assert client.admin.commands == [
        ("ping", (), {}),
        (
            {
                "replSetInitiate": {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "localhost:27017"}],
                }
            },
            (),
            {},
        ),
        (
            {
                "createUser": "admin",
                "pwd": "s3cret",
                "roles": [{"role": "root", "db": "admin"}],
            },
            (),
            {},
        ),
    ]
