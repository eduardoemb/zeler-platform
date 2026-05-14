from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from zeler_platform_core.models import (
    RepricerAllies,
    RepricerAllyAccount,
    RepricerBulkJob,
    RepricerBulkRow,
    RepricerCatalogRule,
    RepricerLimits,
    RepricerMonitoringSnapshot,
    RepricerReport,
    RepricerRuleExecutionState,
)
from zeler_platform_core.repos import RepricerBulkRowRepo, RepricerCatalogRuleRepo

NOW = datetime(2026, 5, 13, 18, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.sort_spec: list[tuple[str, int]] | None = None
        self.skip_count = 0
        self.limit_count = 0

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = sort_spec
        return self

    def skip(self, count: int) -> FakeCursor:
        self.skip_count = count
        return self

    def limit(self, count: int) -> FakeCursor:
        self.limit_count = count
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        end = self.skip_count + min(length, self.limit_count or length)
        return self.documents[self.skip_count : end]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.filters: list[dict[str, Any]] = []
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        self.cursor = FakeCursor(documents)

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.filters.append(filter_spec)
        return next(
            (doc for doc in self.documents if all(doc.get(k) == v for k, v in filter_spec.items())),
            None,
        )

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.filters.append(filter_spec)
        filtered = [
            doc for doc in self.documents if all(doc.get(k) == v for k, v in filter_spec.items())
        ]
        self.cursor = FakeCursor(filtered)
        return self.cursor

    async def replace_one(
        self, filter_spec: dict[str, Any], document: dict[str, Any], *, upsert: bool
    ) -> None:
        self.replace_calls.append((filter_spec, document, upsert))
        self.documents = [
            existing
            for existing in self.documents
            if not all(existing.get(key) == value for key, value in filter_spec.items())
        ]
        self.documents.append(document)


class FakeDatabase(dict[str, FakeCollection]):
    def __getitem__(self, collection_name: str) -> FakeCollection:
        return super().__getitem__(collection_name)


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database

    def get_default_database(self) -> FakeDatabase:
        return self.database


def _catalog_rule_doc(item_id: str = "MLA-1", *, seller_id: str = "82453304") -> dict[str, Any]:
    return {
        "_id": f"catalog-{item_id}",
        "seller_id": seller_id,
        "account_id": "acc-1",
        "item_id": item_id,
        "title": f"Item {item_id}",
        "sku": f"SKU-{item_id}",
        "strategy": "competitive",
        "min_price": Decimal("100.00"),
        "max_price": Decimal("120.00"),
        "active": True,
        "execution_state": {
            "last_outcome": "applied",
            "last_event_at": NOW,
            "last_applied_price": Decimal("109.90"),
            "last_competitor": {"seller_id": "998", "item_id": "MLA-COMP"},
            "predominant_variant_id": "VAR-1",
        },
        "created_at": NOW,
        "updated_at": NOW,
        "created_by": "operator-1",
        "updated_by": "operator-1",
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    "model_cls,payload_key",
    [
        (RepricerCatalogRule, "item_id"),
        (RepricerLimits, "account_id"),
        (RepricerAllies, "seller_id"),
        (RepricerBulkJob, "status"),
        (RepricerBulkRow, "job_id"),
        (RepricerReport, "report_type"),
        (RepricerMonitoringSnapshot, "generated_at"),
    ],
)
def test_repricer_foundation_models_validate_new_documents(
    model_cls: type[Any], payload_key: str
) -> None:
    payloads: dict[type[Any], dict[str, Any]] = {
        RepricerCatalogRule: _catalog_rule_doc(),
        RepricerLimits: {
            "_id": "limits-1",
            "seller_id": 82453304,
            "account_id": "acc-1",
            "enabled": True,
            "min_price_limit": "100.00",
            "max_price_limit": "150.00",
            "undercut_delta": "1.50",
            "pause_competition": False,
            "escalate_to_manual_review": True,
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        },
        RepricerAllies: {
            "_id": "allies-1",
            "seller_id": 82453304,
            "allies": [{"account_id": "ally-1", "nickname": "ALLY SHOP"}],
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        },
        RepricerBulkJob: {
            "_id": "bulk-job-1",
            "seller_id": 82453304,
            "account_id": "acc-1",
            "status": "processing",
            "source_filename": "catalog.xlsx",
            "total_rows": 10,
            "processed_rows": 4,
            "success_rows": 3,
            "failed_rows": 1,
            "created_at": NOW,
            "updated_at": NOW,
            "created_by": "operator-1",
            "schema_version": 1,
        },
        RepricerBulkRow: {
            "_id": "bulk-row-1",
            "seller_id": 82453304,
            "account_id": "acc-1",
            "job_id": "bulk-job-1",
            "row_number": 7,
            "status": "failed",
            "item_id": "MLA-1",
            "payload": {"sku": "SKU-1"},
            "error_code": "invalid_price",
            "error_message": "price below limit",
            "created_at": NOW,
            "updated_at": NOW,
            "schema_version": 1,
        },
        RepricerReport: {
            "_id": "report-1",
            "seller_id": 82453304,
            "account_id": "acc-1",
            "report_type": "rules_export",
            "format": "csv",
            "status": "ready",
            "storage_path": "gs://bucket/report.csv",
            "row_count": 25,
            "created_at": NOW,
            "updated_at": NOW,
            "requested_by": "operator-1",
            "schema_version": 1,
        },
        RepricerMonitoringSnapshot: {
            "_id": "snapshot-1",
            "seller_id": 82453304,
            "account_id": "acc-1",
            "generated_at": NOW,
            "worker_heartbeat_at": NOW,
            "queue_backlog": {"repricer.sweep.requested": 2},
            "error_buckets": {"rate_limit": 1},
            "active_bulk_job_ids": ["bulk-job-1"],
            "schema_version": 1,
        },
    }

    document = model_cls.model_validate(payloads[model_cls])

    assert getattr(document, payload_key) is not None
    assert document.seller_id == "82453304"
    assert document.schema_version == 1


def test_repricer_embedded_models_normalize_nested_values() -> None:
    execution_state = RepricerRuleExecutionState.model_validate(
        {
            "last_outcome": "guard_blocked",
            "last_event_at": NOW,
            "last_applied_price": "101.50",
            "last_competitor": {"seller_id": 321, "item_id": 654},
            "predominant_variant_id": 987,
        }
    )
    allies = RepricerAllies.model_validate(
        {
            "_id": "allies-1",
            "seller_id": 82453304,
            "allies": [{"account_id": 321, "nickname": "ALLY SHOP"}],
            "created_at": NOW,
            "updated_at": NOW,
        }
    )

    assert execution_state.last_applied_price == Decimal("101.50")
    assert execution_state.last_competitor == RepricerAllyAccount(
        account_id="321", nickname=None, item_id="654"
    )
    assert execution_state.predominant_variant_id == "987"
    assert allies.allies == [RepricerAllyAccount(account_id="321", nickname="ALLY SHOP")]


@pytest.mark.asyncio
async def test_repricer_catalog_rule_repo_lists_by_scope_and_upserts_json_documents() -> None:
    database = FakeDatabase(
        {
            "repricer_catalog_rules": FakeCollection(
                [
                    _catalog_rule_doc("MLA-1"),
                    _catalog_rule_doc("MLA-2"),
                    _catalog_rule_doc("MLA-9", seller_id="999"),
                ]
            )
        }
    )
    repo = RepricerCatalogRuleRepo(FakeClient(database))

    rules = await repo.list_by_seller(
        "82453304", account_id="acc-1", active=True, limit=1, offset=1
    )

    assert [rule.item_id for rule in rules] == ["MLA-2"]
    assert database["repricer_catalog_rules"].filters == [
        {"seller_id": "82453304", "account_id": "acc-1", "active": True}
    ]

    new_rule = RepricerCatalogRule.model_validate(
        {**_catalog_rule_doc("MLA-3"), "_id": "catalog-MLA-3"}
    )
    await repo.upsert(new_rule)

    assert database["repricer_catalog_rules"].replace_calls == [
        (
            {"_id": "catalog-MLA-3", "seller_id": "82453304"},
            new_rule.model_dump(mode="json", by_alias=True),
            True,
        )
    ]


@pytest.mark.asyncio
async def test_repricer_bulk_row_repo_lists_rows_by_job() -> None:
    database = FakeDatabase(
        {
            "repricer_bulk_rows": FakeCollection(
                [
                    {
                        "_id": "row-1",
                        "seller_id": "82453304",
                        "account_id": "acc-1",
                        "job_id": "job-1",
                        "row_number": 1,
                        "status": "processed",
                        "payload": {"sku": "SKU-1"},
                        "created_at": NOW,
                        "updated_at": NOW,
                        "schema_version": 1,
                    },
                    {
                        "_id": "row-2",
                        "seller_id": "82453304",
                        "account_id": "acc-1",
                        "job_id": "job-1",
                        "row_number": 2,
                        "status": "failed",
                        "payload": {"sku": "SKU-2"},
                        "created_at": NOW,
                        "updated_at": NOW,
                        "schema_version": 1,
                    },
                ]
            )
        }
    )
    repo = RepricerBulkRowRepo(FakeClient(database))

    rows = await repo.list_by_job("82453304", job_id="job-1", status="failed")

    assert [row.row_number for row in rows] == [2]
    assert database["repricer_bulk_rows"].filters == [
        {"seller_id": "82453304", "job_id": "job-1", "status": "failed"}
    ]
    assert database["repricer_bulk_rows"].cursor.sort_spec == [("row_number", 1)]
