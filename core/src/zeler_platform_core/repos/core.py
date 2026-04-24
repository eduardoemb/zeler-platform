from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from zeler_platform_core.models import Claim, Item, MeliAccount, Message, Order, Question, Shipment


class AsyncCursor(Protocol):
    def sort(self, sort_spec: list[tuple[str, int]]) -> AsyncCursor: ...
    def skip(self, count: int) -> AsyncCursor: ...
    def limit(self, count: int) -> AsyncCursor: ...
    async def to_list(self, length: int) -> list[dict[str, Any]]: ...


class AsyncCollection(Protocol):
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...
    def find(self, filter_spec: dict[str, Any]) -> AsyncCursor: ...


class MongoDatabase(Protocol):
    def __getitem__(self, collection_name: str) -> AsyncCollection: ...


class MongoClientLike(Protocol):
    def get_default_database(self) -> MongoDatabase: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


class ReadOnlyRepo(Generic[ModelT]):
    collection_name: str
    model: type[ModelT]
    default_sort: list[tuple[str, int]] = [("last_updated", -1)]

    def __init__(self, mongo_client: MongoClientLike) -> None:
        self._collection = mongo_client.get_default_database()[self.collection_name]

    @staticmethod
    def _seller_id(value: object) -> str:
        return str(value)

    async def list_by_seller(
        self,
        seller_id: object,
        *,
        limit: int = 100,
        offset: int = 0,
        **filters: object,
    ) -> list[ModelT]:
        query: dict[str, object] = {"seller_id": self._seller_id(seller_id)}
        query.update({key: value for key, value in filters.items() if value is not None})
        cursor = self._collection.find(query).sort(self.default_sort).skip(offset).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self.model.model_validate(document) for document in documents]


class MeliAccountRepo:
    def __init__(self, mongo_client: MongoClientLike) -> None:
        self._collection = mongo_client.get_default_database()["meli_accounts"]

    async def get_by_user_id(self, platform_user_id: str) -> MeliAccount | None:
        document = await self._collection.find_one({"platform_user_id": platform_user_id})
        if document is None:
            return None
        return MeliAccount.model_validate(document)

    def save(self, _: Mapping[str, Any]) -> object:
        """Core repositories are intentionally read-only."""

        return NotImplemented


class ItemRepo(ReadOnlyRepo[Item]):
    collection_name = "items"
    model = Item


class OrderRepo(ReadOnlyRepo[Order]):
    collection_name = "orders"
    model = Order
    default_sort = [("date_created", -1)]


class QuestionRepo(ReadOnlyRepo[Question]):
    collection_name = "questions"
    model = Question
    default_sort = [("date_created", -1)]


class MessageRepo(ReadOnlyRepo[Message]):
    collection_name = "messages"
    model = Message
    default_sort = [("date_created", -1)]


class ShipmentRepo(ReadOnlyRepo[Shipment]):
    collection_name = "shipments"
    model = Shipment


class ClaimRepo(ReadOnlyRepo[Claim]):
    collection_name = "claims"
    model = Claim
    default_sort = [("date_created", -1)]
