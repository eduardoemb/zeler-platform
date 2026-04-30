from __future__ import annotations

import logging
from io import StringIO
from typing import Any

import pytest
from infra.mongo.init_replica_set import main
from pymongo.errors import OperationFailure

from zeler_platform_core.observability.logging import configure_logging

_OBSERVABILITY_HANDLER_MARKER = "_zeler_platform_observability"


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _FakeAdmin:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses

    def command(self, command: object, *args: Any, **kwargs: Any) -> dict[str, object]:
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if isinstance(response, dict):
                return response
        if command == "hello":
            return {"ok": 1, "isWritablePrimary": True}
        return {"ok": 1}


class _FakeMongoClient:
    def __init__(self, responses: list[object]) -> None:
        self.admin = _FakeAdmin(responses)


def test_configure_logging_preserves_existing_root_handlers_for_later_capsys_tests(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root_logger = logging.getLogger()
    pytest_like_handler = _RecordingHandler()
    root_logger.addHandler(pytest_like_handler)

    try:
        configure_logging(environment="test")

        clients = [
            _FakeMongoClient(
                [
                    None,
                    OperationFailure("already initialized", code=23),
                    {"ok": 1, "ismaster": True},
                    OperationFailure("user exists", code=51003),
                ]
            ),
            _FakeMongoClient(
                [
                    None,
                    OperationFailure("already initialized", code=23),
                    {"ok": 1, "ismaster": True},
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

        assert pytest_like_handler in root_logger.handlers
        assert first_run.err == ""
        assert second_run.err == ""
    finally:
        if pytest_like_handler in root_logger.handlers:
            root_logger.removeHandler(pytest_like_handler)
        pytest_like_handler.close()
        for handler in root_logger.handlers[:]:
            if getattr(handler, _OBSERVABILITY_HANDLER_MARKER, False):
                root_logger.removeHandler(handler)
                handler.close()


def test_init_replica_set_ignores_stale_closed_stream_handlers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root_logger = logging.getLogger()
    stale_stream = StringIO()
    stale_handler = logging.StreamHandler(stale_stream)
    original_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stale_handler)
    stale_stream.close()

    clients = [
        _FakeMongoClient(
            [
                None,
                OperationFailure("already initialized", code=23),
                {"ok": 1, "ismaster": True},
                OperationFailure("user exists", code=51003),
            ]
        ),
        _FakeMongoClient(
            [
                None,
                OperationFailure("already initialized", code=23),
                {"ok": 1, "ismaster": True},
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

    try:
        main()
        first_run = capsys.readouterr()
        main()
        second_run = capsys.readouterr()

        assert first_run.err == ""
        assert second_run.err == ""
    finally:
        if stale_handler in root_logger.handlers:
            root_logger.removeHandler(stale_handler)
        stale_handler.close()
        root_logger.setLevel(original_level)
