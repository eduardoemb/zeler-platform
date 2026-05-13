from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from zeler_platform_core.models import (
    RepricerAllies,
    RepricerBulkJob,
    RepricerBulkRow,
    RepricerCatalogRule,
    RepricerLimits,
    RepricerMonitoringSnapshot,
    RepricerReport,
)
from zeler_platform_core.repos.core import AsyncCursor, MongoClientLike


class AsyncWriteCollection(Protocol):
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...
    def find(self, filter_spec: dict[str, Any]) -> AsyncCursor: ...
    async def replace_one(
        self, filter_spec: dict[str, Any], document: dict[str, Any], *, upsert: bool
    ) -> Any: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


class SellerScopedRepo(Generic[ModelT]):
    collection_name: str
    model: type[ModelT]
    default_sort: list[tuple[str, int]] = [("updated_at", -1)]

    def __init__(self, mongo_client: MongoClientLike) -> None:
        self._collection: AsyncWriteCollection = mongo_client.get_default_database()[
            self.collection_name
        ]

    @staticmethod
    def _as_str(value: object) -> str:
        return str(value)

    async def list_by_seller(
        self,
        seller_id: object,
        *,
        limit: int = 100,
        offset: int = 0,
        **filters: object,
    ) -> list[ModelT]:
        query: dict[str, object] = {"seller_id": self._as_str(seller_id)}
        query.update({key: value for key, value in filters.items() if value is not None})
        cursor = self._collection.find(query).sort(self.default_sort).skip(offset).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self.model.model_validate(document) for document in documents]

    async def get_one_by_seller(self, seller_id: object, **filters: object) -> ModelT | None:
        query: dict[str, object] = {"seller_id": self._as_str(seller_id)}
        query.update({key: value for key, value in filters.items() if value is not None})
        document = await self._collection.find_one(query)
        if document is None:
            return None
        return self.model.model_validate(document)

    async def upsert(self, document: ModelT) -> None:
        payload = document.model_dump(mode="json", by_alias=True)
        await self._collection.replace_one(
            {"_id": payload["_id"], "seller_id": payload["seller_id"]}, payload, upsert=True
        )


class RepricerCatalogRuleRepo(SellerScopedRepo[RepricerCatalogRule]):
    collection_name = "repricer_catalog_rules"
    model = RepricerCatalogRule


class RepricerLimitsRepo(SellerScopedRepo[RepricerLimits]):
    collection_name = "repricer_limits"
    model = RepricerLimits


class RepricerAlliesRepo(SellerScopedRepo[RepricerAllies]):
    collection_name = "repricer_allies"
    model = RepricerAllies


class RepricerBulkJobRepo(SellerScopedRepo[RepricerBulkJob]):
    collection_name = "repricer_bulk_jobs"
    model = RepricerBulkJob
    default_sort = [("created_at", -1)]


class RepricerBulkRowRepo(SellerScopedRepo[RepricerBulkRow]):
    collection_name = "repricer_bulk_rows"
    model = RepricerBulkRow
    default_sort = [("row_number", 1)]

    async def list_by_job(
        self, seller_id: object, *, job_id: object, status: object | None = None
    ) -> list[RepricerBulkRow]:
        return await self.list_by_seller(seller_id, job_id=self._as_str(job_id), status=status)


class RepricerReportRepo(SellerScopedRepo[RepricerReport]):
    collection_name = "repricer_reports"
    model = RepricerReport
    default_sort = [("created_at", -1)]


class RepricerMonitoringSnapshotRepo(SellerScopedRepo[RepricerMonitoringSnapshot]):
    collection_name = "repricer_monitoring_snapshots"
    model = RepricerMonitoringSnapshot
    default_sort = [("generated_at", -1)]
