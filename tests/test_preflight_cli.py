from __future__ import annotations

import json
from typing import Any

from infra.operations import preflight


class FakeHttpResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class FakeHttpClient:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    async def get(self, path: str) -> FakeHttpResponse:
        assert path == "/health"
        return FakeHttpResponse(self.status_code)


class FakeMongo:
    def __init__(self, *, reachable: bool = True, has_account: bool = True) -> None:
        self.reachable = reachable
        self.has_account = has_account

    async def ping(self) -> bool:
        return self.reachable

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        assert collection == "meli_accounts"
        assert query == {"seller_id": "82453304"}
        if not self.has_account:
            return None
        return {"seller_id": "82453304", "status": "active"}


class FakeRabbit:
    def __init__(self, *, topology_valid: bool = True) -> None:
        self._topology_valid = topology_valid

    async def topology_valid(self, module: str) -> bool:
        assert module == "repricer"
        return self._topology_valid


def test_cli_exits_0_when_all_checks_pass(capsys: Any) -> None:
    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=lambda _url: FakeRabbit(),
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_exits_1_when_mongo_unreachable(capsys: Any) -> None:
    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(reachable=False),
        rabbitmq_factory=lambda _url: FakeRabbit(),
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["mongo"] == {"passed": False, "detail": "mongo ping failed"}


def test_cli_emits_json_to_stdout(capsys: Any) -> None:
    preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=lambda _url: FakeRabbit(),
        http_factory=lambda _url: FakeHttpClient(),
    )

    report = json.loads(capsys.readouterr().out)
    assert report["module"] == "repricer"
    assert report["seller_id"] == "82453304"
    assert report["checks"]["gateway"]["passed"] is True
    assert report["checks"]["module_health"]["passed"] is True
    assert report["checks"]["meli_account"]["passed"] is True
    assert isinstance(report["checked_at"], str)


def test_cli_emits_summary_to_stderr_on_failure(capsys: Any) -> None:
    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=lambda _url: FakeRabbit(topology_valid=False),
        http_factory=lambda _url: FakeHttpClient(),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "preflight failed for repricer seller 82453304: rabbitmq\n"
