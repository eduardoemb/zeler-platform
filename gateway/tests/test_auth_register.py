from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from infra.mongo.apply_validators import apply_validators
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from zeler_gateway.app import app

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "infra" / "mongo" / "schemas"


@pytest.fixture
def auth_db(default_mongo_uri: str) -> Iterator[Any]:
    mongo_uri = default_mongo_uri
    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:  # pragma: no cover - only for machines without local Docker Mongo
        pytest.skip(f"local Mongo is not available: {exc}")

    database = client.get_default_database()
    database.drop_collection("users")
    apply_validators(mongo_uri, SCHEMAS_DIR)
    async_client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        mongo_uri, serverSelectionTimeoutMS=1000, tz_aware=True
    )
    yield async_client.get_default_database(), database
    database.drop_collection("users")
    async_client.close()
    client.close()


@pytest_asyncio.fixture
async def auth_client(auth_db: Any) -> AsyncIterator[httpx.AsyncClient]:
    async_db, _ = auth_db
    app.state.mongo_db = async_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_register_valid_user_returns_201(
    auth_client: httpx.AsyncClient, auth_db: Any
) -> None:
    _, database = auth_db

    response = await auth_client.post(
        "/auth/register",
        json={
            "email": "operator@example.com",
            "name": "Operator One",
            "auth_provider": "local",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "operator@example.com"
    user_doc = database.users.find_one({"email": "operator@example.com"})
    assert user_doc is not None
    assert user_doc["name"] == "Operator One"
    assert user_doc["auth_provider"] == "local"
    assert user_doc["status"] == "active"
    assert user_doc["roles"] == ["user"]
    assert user_doc["meli_account_ids"] == []


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(auth_client: httpx.AsyncClient) -> None:
    payload = {
        "email": "operator@example.com",
        "name": "Operator One",
        "auth_provider": "google",
    }

    first_response = await auth_client.post("/auth/register", json=payload)
    second_response = await auth_client.post("/auth/register", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": "email already registered"}


@pytest.mark.asyncio
async def test_register_rejects_invalid_email_format(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "name": "Operator One",
            "auth_provider": "local",
        },
    )

    assert response.status_code == 422
    assert "email" in response.json()["detail"][0]["loc"]


@pytest.mark.asyncio
async def test_register_invalid_auth_provider_returns_422(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(
        "/auth/register",
        json={
            "email": "operator@example.com",
            "name": "Operator One",
            "auth_provider": "password",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_email_returns_422(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.post(
        "/auth/register",
        json={"name": "Operator One", "auth_provider": "local"},
    )

    assert response.status_code == 422
