from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest
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


class FailingRabbit:
    async def topology_valid(self, module: str) -> bool:
        raise AssertionError(f"rabbit topology should not be checked for {module}")


def test_cli_exits_0_when_all_checks_pass(capsys: Any) -> None:
    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=lambda _url, _vhost: FakeRabbit(),
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_exits_1_when_mongo_unreachable(capsys: Any) -> None:
    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(reachable=False),
        rabbitmq_factory=lambda _url, _vhost: FakeRabbit(),
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["mongo"] == {"passed": False, "detail": "mongo ping failed"}


def test_cli_emits_json_to_stdout(capsys: Any) -> None:
    preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=lambda _url, _vhost: FakeRabbit(),
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
        rabbitmq_factory=lambda _url, _vhost: FakeRabbit(topology_valid=False),
        http_factory=lambda _url: FakeHttpClient(),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "preflight failed for repricer seller 82453304: rabbitmq\n"


def test_publicador_rabbitmq_check_is_not_required() -> None:
    result = asyncio.run(
        preflight._check_rabbitmq(FailingRabbit(), "publicador")  # noqa: SLF001
    )

    assert result == preflight.CheckResult(True, "rabbitmq topology not_required for publicador")


def test_retired_fulldock_rabbitmq_check_is_not_supported() -> None:
    result = asyncio.run(
        preflight._check_rabbitmq(FailingRabbit(), "fulldock")  # noqa: SLF001
    )

    assert "fulldock" not in preflight.RABBITMQ_WORKER_TOPOLOGY
    assert result == preflight.CheckResult(False, "unsupported module fulldock")


def test_cli_infers_rabbitmq_vhost_from_cloudamqp_url(monkeypatch: Any) -> None:
    monkeypatch.delenv("RABBITMQ_VHOST", raising=False)
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    monkeypatch.setenv("CLOUDAMQP_URL", "amqps://user:pass@woodpecker.rmq.cloudamqp.com/tenant-vhost")
    captured: dict[str, str] = {}

    def rabbit_factory(url: str, vhost: str) -> FakeRabbit:
        captured.update({"url": url, "vhost": vhost})
        return FakeRabbit()

    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=rabbit_factory,
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 0
    assert captured == {"url": "http://localhost:15672", "vhost": "tenant-vhost"}


def test_cli_rabbitmq_vhost_arg_overrides_parsed_amqp_url(monkeypatch: Any) -> None:
    monkeypatch.delenv("RABBITMQ_VHOST", raising=False)
    monkeypatch.setenv("RABBITMQ_URL", "amqps://user:pass@host/parsed-vhost")
    captured: dict[str, str] = {}

    def rabbit_factory(url: str, vhost: str) -> FakeRabbit:
        captured.update({"url": url, "vhost": vhost})
        return FakeRabbit()

    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304", "--rabbitmq-vhost", "explicit-vhost"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=rabbit_factory,
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 0
    assert captured["vhost"] == "explicit-vhost"


def test_cli_rabbitmq_vhost_env_overrides_cloudamqp_url(monkeypatch: Any) -> None:
    monkeypatch.setenv("RABBITMQ_VHOST", "env-vhost")
    monkeypatch.setenv("CLOUDAMQP_URL", "amqps://user:pass@host/cloudamqp-vhost")
    captured: dict[str, str] = {}

    def rabbit_factory(url: str, vhost: str) -> FakeRabbit:
        captured.update({"url": url, "vhost": vhost})
        return FakeRabbit()

    exit_code = preflight.main(
        ["--module", "repricer", "--seller-id", "82453304"],
        mongo_factory=lambda _uri: FakeMongo(),
        rabbitmq_factory=rabbit_factory,
        http_factory=lambda _url: FakeHttpClient(),
    )

    assert exit_code == 0
    assert captured["vhost"] == "env-vhost"


def test_rabbitmq_management_client_uses_url_encoded_non_root_vhost(monkeypatch: Any) -> None:
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            assert base_url == "https://woodpecker.rmq.cloudamqp.com"
            assert timeout == 5.0

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, path: str) -> Any:
            calls.append(path)
            if path.endswith("/bindings"):
                return SimpleNamespace(status_code=200, json=lambda: [{"source": "meli.events"}])
            return SimpleNamespace(
                status_code=200,
                json=lambda: [
                    {"name": "zeler.repricer.items"},
                    {"name": "zeler.repricer.items.dlq"},
                ],
            )

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))

    client = preflight._RabbitManagementPreflightClient(  # noqa: SLF001 - focused unit test.
        "https://woodpecker.rmq.cloudamqp.com",
        "tenant/prod",
    )

    assert asyncio.run(client.topology_valid("repricer")) is True
    assert calls == [
        "/api/queues/tenant%2Fprod",
        "/api/queues/tenant%2Fprod/zeler.repricer.items.dlq/bindings",
    ]


@pytest.mark.parametrize(
    ("module", "queue_name", "dlq_name"),
    [
        ("repricer", "zeler.repricer.items", "zeler.repricer.items.dlq"),
        ("sheets", "zeler.sheets.events", "zeler.sheets.events.dlq"),
        ("autoreply", "zeler.autoreply.events", "zeler.autoreply.events.dlq"),
    ],
)
def test_rabbitmq_management_client_uses_worker_queue_names(
    monkeypatch: Any,
    module: str,
    queue_name: str,
    dlq_name: str,
) -> None:
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            assert base_url == "http://localhost:15672"
            assert timeout == 5.0

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, path: str) -> Any:
            calls.append(path)
            if path.endswith("/bindings"):
                return SimpleNamespace(status_code=200, json=lambda: [{"source": "meli.events"}])
            return SimpleNamespace(
                status_code=200,
                json=lambda: [{"name": queue_name}, {"name": dlq_name}],
            )

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))

    client = preflight._RabbitManagementPreflightClient("http://localhost:15672", "/")  # noqa: SLF001

    assert asyncio.run(client.topology_valid(module)) is True
    assert calls == [
        "/api/queues/%2F",
        f"/api/queues/%2F/{dlq_name}/bindings",
    ]


def test_rabbitmq_management_client_preserves_root_vhost_encoding(monkeypatch: Any) -> None:
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            assert base_url == "http://localhost:15672"
            assert timeout == 5.0

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, path: str) -> Any:
            calls.append(path)
            if path.endswith("/bindings"):
                return SimpleNamespace(status_code=200, json=lambda: [{"source": "meli.events"}])
            return SimpleNamespace(
                status_code=200,
                json=lambda: [
                    {"name": "zeler.repricer.items"},
                    {"name": "zeler.repricer.items.dlq"},
                ],
            )

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))

    client = preflight._RabbitManagementPreflightClient("http://localhost:15672", "/")  # noqa: SLF001

    assert asyncio.run(client.topology_valid("repricer")) is True
    assert calls == [
        "/api/queues/%2F",
        "/api/queues/%2F/zeler.repricer.items.dlq/bindings",
    ]
