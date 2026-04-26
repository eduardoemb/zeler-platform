from __future__ import annotations

from typing import Any, ClassVar

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


class RecordingMongoClient:
    instances: ClassVar[list[RecordingMongoClient]] = []

    def __init__(
        self,
        uri: str,
        *,
        username: str | None = None,
        password: str | None = None,
        **_kwargs: Any,
    ) -> None:
        self.uri = uri
        self.username = username
        self.password = password
        self.auth_source = _kwargs.get("authSource")
        self.admin = FakeAdmin([])
        self.instances.append(self)


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


def test_initiate_replica_set_fresh_node_uses_prod_member_host_by_default() -> None:
    client = FakeMongoClient([])

    initiate_replica_set(client)

    assert client.admin.commands == [
        (
            {
                "replSetInitiate": {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "127.0.0.1:27019"}],
                }
            },
            (),
            {},
        )
    ]


def test_initiate_replica_set_honors_custom_replica_set_name_and_host() -> None:
    client = FakeMongoClient([])

    initiate_replica_set(client, rs_name="prod-rs", host="10.0.0.5:27019")

    assert client.admin.commands == [
        (
            {
                "replSetInitiate": {
                    "_id": "prod-rs",
                    "members": [{"_id": 0, "host": "10.0.0.5:27019"}],
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


def test_main_constructs_authenticated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "value-from-env"
    RecordingMongoClient.instances = []
    monkeypatch.setattr("infra.mongo.init_replica_set.MongoClient", RecordingMongoClient)
    monkeypatch.setenv("MONGO_ADMIN_USER", "alice")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", expected)
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")

    main()

    assert len(RecordingMongoClient.instances) == 1
    recorder = RecordingMongoClient.instances[0]
    assert recorder.uri == "mongodb://127.0.0.1:27019/?directConnection=true"
    assert recorder.username == "alice"
    assert recorder.password == expected
    assert recorder.auth_source == "admin"


def test_main_uses_init_uri_and_runs_bootstrap_steps_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient([])
    observed_uris: list[str] = []

    # widened to tolerate auth kwargs from GREEN step.
    def mongo_client(uri: str, **_kwargs: Any) -> FakeMongoClient:
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
                    "members": [{"_id": 0, "host": "127.0.0.1:27019"}],
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


def test_main_exits_1_when_mongod_never_responds_within_timeout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMongoClient([ServerSelectionTimeoutError("offline")] * 5)

    # widened to tolerate auth kwargs from GREEN step.
    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setattr("infra.mongo.init_replica_set.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")
    monkeypatch.setenv("MONGO_INIT_TIMEOUT_S", "0")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "timeout" in err.lower()
    assert "127.0.0.1:27019" in err


def test_main_exits_3_on_unexpected_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMongoClient([None, OperationFailure("not authorized", code=13)])

    # widened to tolerate auth kwargs from GREEN step.
    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    assert "not authorized" in capsys.readouterr().err


def test_replset_initiate_unauthorized_exits_3(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeMongoClient(
        [None, OperationFailure("Command replSetInitiate requires authentication", code=13)]
    )

    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    err = capsys.readouterr().err
    assert "error: unhandled mongod operation failure" in err
    assert "requires authentication" in err


def test_main_idempotent_rerun_succeeds_silently(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clients = [
        FakeMongoClient(
            [
                None,
                OperationFailure("already initialized", code=23),
                OperationFailure("user exists", code=51003),
            ]
        ),
        FakeMongoClient(
            [
                None,
                OperationFailure("already initialized", code=23),
                OperationFailure("user exists", code=51003),
            ]
        ),
    ]

    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: clients.pop(0),
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")

    main()
    first_run = capsys.readouterr()
    main()
    second_run = capsys.readouterr()

    assert first_run.err == ""
    assert second_run.err == ""


def test_main_uses_member_host_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient([])

    # widened to tolerate auth kwargs from GREEN step.
    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")
    monkeypatch.setenv("MONGO_RS_MEMBER_HOST", "10.0.0.5:27019")

    main()

    initiate_call = client.admin.commands[1]
    assert initiate_call[0] == {
        "replSetInitiate": {
            "_id": "rs0",
            "members": [{"_id": 0, "host": "10.0.0.5:27019"}],
        }
    }


def test_main_uses_rs_name_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient([])

    # widened to tolerate auth kwargs from GREEN step.
    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27017/?directConnection=true")
    monkeypatch.setenv("MONGO_RS_MEMBER_HOST", "127.0.0.1:27017")
    monkeypatch.setenv("MONGO_RS_NAME", "rs0-dev")

    main()

    initiate_call = client.admin.commands[1]
    assert initiate_call[0] == {
        "replSetInitiate": {
            "_id": "rs0-dev",
            "members": [{"_id": 0, "host": "127.0.0.1:27017"}],
        }
    }


def test_main_default_rs_name_is_rs0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient([])

    # widened to tolerate auth kwargs from GREEN step.
    monkeypatch.setattr(
        "infra.mongo.init_replica_set.MongoClient",
        lambda *_args, **_kwargs: client,
    )
    monkeypatch.setenv("MONGO_ADMIN_USER", "admin")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("MONGO_INIT_URI", "mongodb://127.0.0.1:27019/?directConnection=true")
    monkeypatch.delenv("MONGO_RS_NAME", raising=False)

    main()

    initiate_call = client.admin.commands[1]
    assert initiate_call[0] == {
        "replSetInitiate": {
            "_id": "rs0",
            "members": [{"_id": 0, "host": "127.0.0.1:27019"}],
        }
    }
