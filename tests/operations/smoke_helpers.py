from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FakeHttpResponse:
    status_code: int
    json_body: dict[str, Any]


class FakeHttpSource:
    async def get(self, path: str) -> FakeHttpResponse:
        assert path == "/health"
        return FakeHttpResponse(status_code=200, json_body={"ready": True})


class FakeMongo:
    def __init__(self, *, seller_id: str = "82453304") -> None:
        self.collections: dict[str, list[dict[str, Any]]] = {
            "meli_accounts": [{"seller_id": seller_id, "status": "active"}]
        }

    async def ping(self) -> bool:
        return True

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(
            (doc for doc in self.collections.get(collection, []) if _matches(doc, query)),
            None,
        )

    async def upsert_one(self, collection: str, key: str, doc: dict[str, Any]) -> None:
        docs = self.collections.setdefault(collection, [])
        existing = next((candidate for candidate in docs if candidate.get("_id") == key), None)
        if existing is None:
            docs.append({"_id": key, **doc})


class FakeRabbit:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def topology_valid(self, module: str) -> bool:
        return module in {"repricer", "sheets", "publicador", "autoreply", "fulldock"}

    async def publish(self, *, module: str, payload: dict[str, Any]) -> None:
        self.published.append({"module": module, "payload": payload})


@dataclass
class FakePilotStack:
    module: str
    history_collection: str
    mongo: FakeMongo = None  # type: ignore[assignment]
    rabbitmq: FakeRabbit = None  # type: ignore[assignment]
    gateway_http: FakeHttpSource = None  # type: ignore[assignment]
    module_http: FakeHttpSource = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.mongo = self.mongo or FakeMongo()
        self.rabbitmq = self.rabbitmq or FakeRabbit()
        self.gateway_http = self.gateway_http or FakeHttpSource()
        self.module_http = self.module_http or FakeHttpSource()


async def run_module_smoke(stack: FakePilotStack) -> dict[str, Any]:
    payload = {"event_id": f"pilot-{stack.module}-82453304", "seller_id": "82453304"}
    await stack.rabbitmq.publish(module=stack.module, payload=payload)
    await stack.mongo.upsert_one(
        stack.history_collection,
        payload["event_id"],
        {"seller_id": "82453304", "status": "ok", "module": stack.module},
    )
    return {
        "module": stack.module,
        "history_count": len(stack.mongo.collections[stack.history_collection]),
        "response": {"status": "ok"},
    }


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
