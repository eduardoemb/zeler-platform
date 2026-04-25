from __future__ import annotations

import threading
from typing import Any

import pytest
from infra.mongo import smoke_prod
from pymongo.errors import ConnectionFailure, OperationFailure


class FakeAdminCommand:
    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses = responses or []
        self.commands: list[tuple[object, tuple[Any, ...], dict[str, Any]]] = []

    def command(self, command: object, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.commands.append((command, args, kwargs))
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response  # type: ignore[return-value]
        if command == "replSetGetStatus":
            return {"ok": 1, "myState": 1, "members": [{"health": 1}]}
        return {"ok": 1}


class FakeMongoClient:
    def __init__(self, admin_responses: list[object] | None = None) -> None:
        self.admin = FakeAdminCommand(admin_responses)
        self.databases: dict[str, FakeDatabase] = {}
        self.dropped_databases: list[str] = []
        self.drop_failures: list[Exception | None] = []
        self.session = FakeSession()
        self.sessions: list[FakeSession] = []
        self.start_session_thread_ids: list[int] = []

    def __getitem__(self, name: str) -> FakeDatabase:
        if name not in self.databases:
            self.databases[name] = FakeDatabase(self)
        return self.databases[name]

    def start_session(self) -> FakeSession:
        self.start_session_thread_ids.append(threading.get_ident())
        session = self.session if not self.sessions else FakeSession()
        self.sessions.append(session)
        return session

    def drop_database(self, name: str) -> None:
        self.dropped_databases.append(name)
        if self.drop_failures:
            failure = self.drop_failures.pop(0)
            if failure is not None:
                raise failure
        if name in self.databases:
            for collection in self.databases[name].collections.values():
                collection.documents.clear()


class FakeDatabase:
    def __init__(self, client: FakeMongoClient) -> None:
        self.client = client
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.insert_calls: list[dict[str, Any]] = []
        self.fail_on: dict[str, Exception] = {}
        self.change_stream = FakeChangeStream()
        self.publish_change_events = True
        self.watch_calls: list[dict[str, Any]] = []
        self.count_override: int | None = None

    def insert_one(self, document: dict[str, Any], session: object | None = None) -> object:
        if "insert" in self.fail_on:
            raise self.fail_on["insert"]
        self.insert_calls.append({"document": document, "session": session})
        self.documents.append(document)
        if self.publish_change_events:
            self.change_stream.events.append({"operationType": "insert", "fullDocument": document})
        return object()

    def _matches(self, document: dict[str, Any], filter_: dict[str, Any]) -> bool:
        return all(document.get(key) == value for key, value in filter_.items())

    def find_one(
        self,
        filter_: dict[str, Any],
        session: object | None = None,
    ) -> dict[str, Any] | None:
        if "find" in self.fail_on:
            raise self.fail_on["find"]
        return next((doc for doc in self.documents if self._matches(doc, filter_)), None)

    def delete_many(self, filter_: dict[str, Any]) -> object:
        if "delete" in self.fail_on:
            raise self.fail_on["delete"]
        self.documents = [doc for doc in self.documents if not self._matches(doc, filter_)]
        return object()

    def count_documents(self, filter_: dict[str, Any]) -> int:
        if "count" in self.fail_on:
            raise self.fail_on["count"]
        if self.count_override is not None:
            return self.count_override
        return sum(1 for doc in self.documents if self._matches(doc, filter_))

    def watch(self) -> FakeChangeStream:
        self.watch_calls.append({})
        return self.change_stream


class FakeSession:
    def __init__(self) -> None:
        self.transaction = FakeTransactionContext()
        self.ended = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def start_transaction(self) -> FakeTransactionContext:
        return self.transaction

    def end_session(self) -> None:
        self.ended = True


class FakeTransactionContext:
    def __init__(self) -> None:
        self.commit_failure: Exception | None = None

    def __enter__(self) -> FakeTransactionContext:
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        if exc_type is None and self.commit_failure is not None:
            raise self.commit_failure


class FakeChangeStream:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.yielded_events: list[dict[str, Any]] = []
        self.closed = False

    def __enter__(self) -> FakeChangeStream:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.closed = True

    def try_next(self) -> dict[str, Any] | None:
        if not self.events:
            return None
        event = self.events.pop(0)
        self.yielded_events.append(event)
        return event


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27019/?replicaSet=rs0")
    monkeypatch.setenv("MONGO_ADMIN_USER", "root")
    monkeypatch.setenv("MONGO_ADMIN_PASSWORD", "secret")  # noqa: S105 - test credential fixture


def use_mongo_client(monkeypatch: pytest.MonkeyPatch, client: FakeMongoClient) -> None:
    monkeypatch.setattr(
        "infra.mongo.smoke_prod.pymongo.MongoClient",
        lambda *_args, **_kwargs: client,
    )


def test_main_returns_zero_when_connectivity_and_auth_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_env(monkeypatch)
    observed_uris: list[str] = []

    def mongo_client(uri: str, **kwargs: Any) -> FakeMongoClient:
        observed_uris.append(uri)
        assert kwargs["username"] == "root"
        assert kwargs["password"] == "secret"  # noqa: S105 - test credential fixture
        assert kwargs["authSource"] == "admin"
        return FakeMongoClient()

    monkeypatch.setattr("infra.mongo.smoke_prod.pymongo.MongoClient", mongo_client)

    assert smoke_prod.main() == 0
    assert observed_uris == ["mongodb://127.0.0.1:27019/?replicaSet=rs0"]


def test_main_returns_connectivity_exit_code_when_mongod_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)

    def mongo_client(_uri: str, **_kwargs: Any) -> FakeMongoClient:
        return FakeMongoClient([ConnectionFailure("offline")])

    monkeypatch.setattr("infra.mongo.smoke_prod.pymongo.MongoClient", mongo_client)

    assert smoke_prod.main() == 10
    assert capsys.readouterr().err == "error: connectivity: offline\n"


def test_main_returns_auth_exit_code_when_admin_credentials_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)

    def mongo_client(_uri: str, **_kwargs: Any) -> FakeMongoClient:
        return FakeMongoClient([OperationFailure("not authorized", code=18)])

    monkeypatch.setattr("infra.mongo.smoke_prod.pymongo.MongoClient", mongo_client)

    assert smoke_prod.main() == 11
    assert capsys.readouterr().err == "error: auth: not authorized\n"


def test_main_preserves_custom_connectivity_detail_in_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)

    def mongo_client(_uri: str, **_kwargs: Any) -> FakeMongoClient:
        return FakeMongoClient([ConnectionFailure("socket timeout on 27019")])

    monkeypatch.setattr("infra.mongo.smoke_prod.pymongo.MongoClient", mongo_client)

    assert smoke_prod.main() == 10
    assert capsys.readouterr().err == "error: connectivity: socket timeout on 27019\n"


def test_main_maps_operation_failure_code_18_to_auth_tag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)

    def mongo_client(_uri: str, **_kwargs: Any) -> FakeMongoClient:
        return FakeMongoClient([OperationFailure("Authentication failed", code=18)])

    monkeypatch.setattr("infra.mongo.smoke_prod.pymongo.MongoClient", mongo_client)

    assert smoke_prod.main() == 11
    assert capsys.readouterr().err == "error: auth: Authentication failed\n"


def test_main_returns_rs_status_exit_code_when_status_reports_not_ok(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient([{"ok": 1}, {"ok": 0, "myState": 1, "members": [{"health": 1}]}])
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 20
    assert capsys.readouterr().err == "error: rs.status: ok=0\n"


def test_main_returns_not_primary_exit_code_when_node_is_secondary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient([{"ok": 1}, {"ok": 1, "myState": 2, "members": [{"health": 1}]}])
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 21
    assert capsys.readouterr().err == "error: not-primary: myState=2\n"


def test_check_rs_status_accepts_healthy_primary() -> None:
    client = FakeMongoClient([{"ok": 1, "myState": 1, "members": [{"health": 1}]}])

    smoke_prod.check_rs_status(client)

    assert client.admin.commands == [("replSetGetStatus", (), {})]


def test_main_returns_rs_status_exit_code_when_status_command_raises(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient([{"ok": 1}, RuntimeError("rs command failed")])
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 20
    assert capsys.readouterr().err == "error: rs.status: rs command failed\n"


def test_main_returns_rs_status_exit_code_when_first_member_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient([{"ok": 1}, {"ok": 1, "myState": 1, "members": [{"health": 0}]}])
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 20
    assert capsys.readouterr().err == "error: rs.status: members[0].health=0\n"


def test_main_cleans_up_roundtrip_sentinel_documents_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 0
    assert client.dropped_databases == ["_smoke", "_smoke"]


def test_main_returns_roundtrip_exit_code_when_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["_smoke_sentinel"].fail_on["insert"] = RuntimeError("disk full")
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 30
    assert capsys.readouterr().err == "error: roundtrip: insert: disk full\n"


def test_main_returns_roundtrip_exit_code_when_find_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["_smoke_sentinel"].fail_on["find"] = RuntimeError("read failed")
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 30
    assert capsys.readouterr().err == "error: roundtrip: find: read failed\n"


def test_main_returns_roundtrip_exit_code_when_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["_smoke_sentinel"].fail_on["delete"] = RuntimeError("delete denied")
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 30
    assert capsys.readouterr().err == "error: roundtrip: delete: delete denied\n"


def test_main_returns_roundtrip_exit_code_when_sentinel_remains_after_delete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["_smoke_sentinel"].count_override = 1
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 30
    assert capsys.readouterr().err == "error: roundtrip: delete: remaining=1\n"


def test_check_transaction_commits_two_collections() -> None:
    client = FakeMongoClient()

    smoke_prod.check_transaction(client, "_smoke")

    assert client["_smoke"]["tx_a"].find_one({"_id": "tx-a"}) == {
        "_id": "tx-a",
        "ok": True,
    }
    assert client["_smoke"]["tx_b"].find_one({"_id": "tx-b"}) == {
        "_id": "tx-b",
        "ok": True,
    }


def test_main_returns_transaction_exit_code_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client.session.transaction.commit_failure = RuntimeError("commit rejected")
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 40
    assert capsys.readouterr().err == "error: transaction: commit rejected\n"


def test_check_change_stream_receives_insert_event(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeMongoClient()
    monkeypatch.setattr("infra.mongo.smoke_prod.time.sleep", lambda _seconds: None)

    smoke_prod.check_change_stream(client, "_smoke", timeout_s=1)

    collection = client["_smoke"]["cs_target"]
    assert collection.change_stream.closed is True
    assert len(collection.change_stream.yielded_events) == 1


def test_check_change_stream_inserts_with_separate_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient()
    main_thread_id = threading.get_ident()
    monkeypatch.setattr("infra.mongo.smoke_prod.time.sleep", lambda _seconds: None)

    smoke_prod.check_change_stream(client, "_smoke", timeout_s=1)

    collection = client["_smoke"]["cs_target"]
    assert len(client.sessions) == 1
    assert client.start_session_thread_ids[0] != main_thread_id
    assert collection.insert_calls == [
        {"document": {"_id": "change-stream", "ok": True}, "session": client.sessions[0]}
    ]
    assert collection.watch_calls == [{}]
    assert client.sessions[0].ended is True


def test_check_change_stream_consumes_one_event_then_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMongoClient()
    collection = client["_smoke"]["cs_target"]
    collection.publish_change_events = False
    collection.change_stream.events.extend(
        [
            {"operationType": "insert", "fullDocument": {"_id": "first"}},
            {"operationType": "insert", "fullDocument": {"_id": "second"}},
        ]
    )
    monkeypatch.setattr("infra.mongo.smoke_prod.time.sleep", lambda _seconds: None)

    smoke_prod.check_change_stream(client, "_smoke", timeout_s=1)

    assert collection.change_stream.yielded_events == [
        {"operationType": "insert", "fullDocument": {"_id": "first"}}
    ]
    assert collection.change_stream.events == [
        {"operationType": "insert", "fullDocument": {"_id": "second"}}
    ]
    assert collection.change_stream.closed is True


def test_smoke_prod_exposes_public_connectivity_check() -> None:
    assert callable(smoke_prod.check_connectivity)


def test_smoke_prod_module_docstring_documents_exit_code_taxonomy() -> None:
    assert smoke_prod.__doc__ is not None
    required_tags = [
        "0 OK",
        "10 connectivity",
        "11 auth",
        "20 rs.status",
        "21 not-primary",
        "30 roundtrip",
        "40 transaction",
        "50 change-stream",
        "60 cleanup",
        "99 unexpected",
    ]

    missing = [tag for tag in required_tags if tag not in smoke_prod.__doc__]
    assert missing == []


def test_main_returns_change_stream_exit_code_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["cs_target"].publish_change_events = False
    use_mongo_client(monkeypatch, client)
    monkeypatch.setattr("infra.mongo.smoke_prod.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("MONGO_SMOKE_TIMEOUT_S", "0")

    assert smoke_prod.main() == 50
    assert capsys.readouterr().err == "error: change-stream: timeout\n"


def test_main_returns_cleanup_exit_code_when_initial_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client.drop_failures.append(RuntimeError("drop denied"))
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 60
    assert capsys.readouterr().err == "error: cleanup: drop denied\n"


def test_main_preserves_original_exit_code_when_final_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    client = FakeMongoClient()
    client["_smoke"]["_smoke_sentinel"].fail_on["insert"] = RuntimeError("disk full")
    client.drop_failures.extend([None, RuntimeError("final drop denied")])
    use_mongo_client(monkeypatch, client)

    assert smoke_prod.main() == 30
    assert capsys.readouterr().err == "error: roundtrip: insert: disk full\n"


def test_main_returns_unexpected_exit_code_for_unknown_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_env(monkeypatch)
    monkeypatch.setattr(
        "infra.mongo.smoke_prod.pymongo.MongoClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad env")),
    )

    assert smoke_prod.main() == 99
    assert capsys.readouterr().err == "error: unexpected: bad env\n"
