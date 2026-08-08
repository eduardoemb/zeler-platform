from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi.testclient import TestClient

from zeler_platform_core.auth.jwt import mint_module_jwt, reset_jwt_cache, set_kms_client
from zeler_publicador.app import build_app
from zeler_publicador.generator import GeneratedListing


class FakeKmsSignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class FakeKmsPublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeKmsSigningClient:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())

    def asymmetric_sign(self, request: dict[str, Any]) -> FakeKmsSignResponse:
        signature = self.private_key.sign(
            request["digest"]["sha256"],
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        return FakeKmsSignResponse(signature)

    def get_public_key(self, request: dict[str, str]) -> FakeKmsPublicKeyResponse:
        pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return FakeKmsPublicKeyResponse(pem.decode("ascii"))


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, *, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.documents[str(doc["_id"])] = doc

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(str(query["_id"]))

    async def replace_one(
        self, filter_doc: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        if upsert or str(filter_doc["_id"]) in self.documents:
            self.documents[str(filter_doc["_id"])] = replacement

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.documents.values() if _matches(doc, query)])


class FakeAdmin:
    async def command(self, command: str) -> dict[str, int]:
        assert command == "ping"
        return {"ok": 1}


class FakeDb:
    def __init__(self) -> None:
        self.admin = FakeAdmin()
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def generate(self, product: Any) -> GeneratedListing:
        self.calls.append(product)
        return GeneratedListing(
            title="Generated", description="Generated description", attributes={}
        )


@dataclass(frozen=True)
class FakePublishResult:
    item_id: str
    outcome: str
    payload: dict[str, Any]


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def publish(self, draft_id: str) -> FakePublishResult:
        self.calls.append(draft_id)
        return FakePublishResult(
            item_id="MLA123", outcome="published", payload={"draft_id": draft_id}
        )


@pytest.fixture(autouse=True)
def fake_kms() -> Generator[None]:
    set_kms_client(FakeKmsSigningClient())
    reset_jwt_cache()
    yield
    set_kms_client(None)
    reset_jwt_cache()


def test_create_draft_returns_201_with_valid_jwt() -> None:
    db = FakeDb()
    app = build_app(mongo_db=db, generator=FakeGenerator(), publisher=FakePublisher())

    response = TestClient(app).post(
        "/publicador/drafts",
        headers=_auth_headers(),
        json={"title": "Base", "category_id": "MLA1234", "attributes": {"sku": "SKU-1"}},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["draft_id"].startswith("publicador-draft-")
    assert body["status"] == "draft"
    assert db["publicador_drafts"].documents[body["draft_id"]]["source_product"]["name"] == "Base"


def test_generate_returns_503_with_stub_llm() -> None:
    db = FakeDb()
    app = build_app(mongo_db=db, publisher=FakePublisher())
    create_response = TestClient(app).post(
        "/publicador/drafts",
        headers=_auth_headers(),
        json={"title": "Base", "category_id": "MLA1234", "attributes": {}},
    )

    response = TestClient(app).post(
        f"/publicador/drafts/{create_response.json()['draft_id']}/generate",
        headers=_auth_headers(),
    )

    assert response.status_code == 503
    assert response.json() == {"code": "llm_not_configured"}


def test_publish_returns_200_with_fake_publisher() -> None:
    db = FakeDb()
    publisher = FakePublisher()
    app = build_app(mongo_db=db, generator=FakeGenerator(), publisher=publisher)
    create_response = TestClient(app).post(
        "/publicador/drafts",
        headers=_auth_headers(),
        json={"title": "Base", "category_id": "MLA1234", "attributes": {}},
    )
    draft_id = create_response.json()["draft_id"]

    response = TestClient(app).post(
        f"/publicador/drafts/{draft_id}/publish", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert response.json()["item_id"] == "MLA123"
    assert publisher.calls == [draft_id]


def test_app_populates_ai_state_from_stub_selector() -> None:
    db = FakeDb()
    app = build_app(mongo_db=db, publisher=FakePublisher())

    assert app.state.publicador_ai_providers == {}
    assert app.state.publicador_ai_default.provider == "stub"
    assert app.state.publicador_ai_default.model == "disabled"


def test_ai_generate_always_returns_503_never_422() -> None:
    db = FakeDb()
    app = build_app(mongo_db=db, publisher=FakePublisher())
    create_response = TestClient(app).post(
        "/publicador/drafts",
        headers=_auth_headers(),
        json={"title": "Base", "category_id": "MLA1234", "attributes": {}},
    )
    draft_id = create_response.json()["draft_id"]

    for payload in (
        {
            "seller_id": "123456789",
            "account_id": "123456789",
            "draft_id": draft_id,
            "operation": "title",
            "prompt_inputs": {},
            "actor_id": "operator-1",
        },
        {
            "seller_id": "123456789",
            "account_id": "123456789",
            "draft_id": "missing-draft",
            "operation": "description",
            "prompt_inputs": {},
            "actor_id": "operator-1",
        },
    ):
        response = TestClient(app).post(
            "/publicador/ai/generate", headers=_auth_headers(), json=payload
        )

        assert response.status_code == 503
        assert response.json() == {"code": "llm_not_configured"}


def _auth_headers() -> dict[str, str]:
    token = mint_module_jwt(
        "publicador",
        seller_id=123456789,
        token_type="module_admin",  # noqa: S106 - token type discriminator, not a secret
        scopes=["admin:publicador"],
        issued_by="zeler-app",
    )
    return {"Authorization": f"Bearer {token}"}


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
