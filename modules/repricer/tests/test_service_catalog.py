from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

NOW = datetime(2026, 5, 13, 19, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, _sort_spec: list[tuple[str, int]]) -> FakeCursor:
        return self

    def skip(self, count: int) -> FakeCursor:
        self._documents = self._documents[count:]
        return self

    def limit(self, count: int) -> FakeCursor:
        self._documents = self._documents[:count]
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._documents[:length]


class FakeUpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []
        self.filters: list[dict[str, Any]] = []
        self.inserted: list[dict[str, Any]] = []
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.replacements: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.filters.append(filter_spec)
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in filter_spec.items())
            ),
            None,
        )

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        self.filters.append(filter_spec)
        filtered = [
            document
            for document in self.documents
            if all(document.get(key) == value for key, value in filter_spec.items())
        ]
        return FakeCursor(filtered)

    async def insert_one(self, document: dict[str, Any]) -> None:
        self.inserted.append(document)
        self.documents.append(document)

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any]
    ) -> FakeUpdateResult:
        self.updates.append((filter_spec, update))
        for document in self.documents:
            if all(document.get(key) == value for key, value in filter_spec.items()):
                document.update(update["$set"])
                return FakeUpdateResult(1)
        return FakeUpdateResult(0)

    async def replace_one(
        self, filter_spec: dict[str, Any], document: dict[str, Any], *, upsert: bool
    ) -> None:
        self.replacements.append((filter_spec, document, upsert))
        self.documents = [
            existing
            for existing in self.documents
            if not all(existing.get(key) == value for key, value in filter_spec.items())
        ]
        self.documents.append(document)


class FakeDb:
    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.repricer_catalog_rules = FakeCollection(documents)
        self.repricer_limits = FakeCollection()
        self.repricer_allies = FakeCollection()
        self.repricer_bulk_jobs = FakeCollection()
        self.repricer_bulk_rows = FakeCollection()
        self.repricer_history = FakeCollection()
        self.repricer_reports = FakeCollection()
        self.repricer_monitoring_snapshots = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        if name == "repricer_catalog_rules":
            return self.repricer_catalog_rules
        if name == "repricer_limits":
            return self.repricer_limits
        if name == "repricer_allies":
            return self.repricer_allies
        if name == "repricer_bulk_jobs":
            return self.repricer_bulk_jobs
        if name == "repricer_bulk_rows":
            return self.repricer_bulk_rows
        if name == "repricer_history":
            return self.repricer_history
        if name == "repricer_reports":
            return self.repricer_reports
        if name == "repricer_monitoring_snapshots":
            return self.repricer_monitoring_snapshots
        raise AssertionError(name)


@pytest.mark.asyncio
async def test_catalog_service_lists_rules_by_seller_account_status_and_query() -> None:
    from zeler_repricer.service import RepricerCatalogRuleService

    db = FakeDb(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1", sku="SKU-ABC"),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-1", sku="OTHER"),
            _catalog_rule("catalog-3", seller_id="123456789", account_id="acc-2", sku="SKU-ABC"),
            _catalog_rule("catalog-4", seller_id="987654321", account_id="acc-1", sku="SKU-ABC"),
            _catalog_rule(
                "catalog-5",
                seller_id="123456789",
                account_id="acc-1",
                sku="SKU-ABC",
                active=False,
            ),
        ]
    )
    service = RepricerCatalogRuleService(db, clock=lambda: NOW)

    rules = await service.list_catalog_rules(
        seller_id="123456789", account_id="acc-1", status="active", query="sku-abc"
    )

    assert [rule.id for rule in rules] == ["catalog-1"]
    assert db.repricer_catalog_rules.filters == [
        {"seller_id": "123456789", "account_id": "acc-1", "active": True}
    ]


@pytest.mark.asyncio
async def test_catalog_service_creates_rule_with_operator_and_default_execution_state() -> None:
    from zeler_repricer.service import RepricerCatalogRuleService

    db = FakeDb()
    service = RepricerCatalogRuleService(db, clock=lambda: NOW)

    rule = await service.create_catalog_rule(
        seller_id="123456789",
        payload={
            "account_id": "acc-1",
            "item_id": "MLA123",
            "title": "Catalog Item",
            "sku": "SKU-123",
            "strategy": "competitive",
            "min_price": "100.00",
            "max_price": "120.00",
        },
        operator_id="operator-1",
    )

    assert rule.id == "catalog-123456789-acc-1-MLA123"
    assert rule.seller_id == "123456789"
    assert rule.execution_state.last_outcome is None
    assert rule.created_by == "operator-1"
    assert db.repricer_catalog_rules.inserted == [rule.model_dump(mode="json", by_alias=True)]


@pytest.mark.asyncio
async def test_catalog_service_rejects_invalid_price_bounds_before_insert() -> None:
    from zeler_repricer.service import CatalogRuleValidationError, RepricerCatalogRuleService

    db = FakeDb()
    service = RepricerCatalogRuleService(db, clock=lambda: NOW)

    with pytest.raises(CatalogRuleValidationError, match="min_price_above_max_price"):
        await service.create_catalog_rule(
            seller_id="123456789",
            payload={
                "account_id": "acc-1",
                "item_id": "MLA123",
                "strategy": "competitive",
                "min_price": "130.00",
                "max_price": "120.00",
            },
            operator_id="operator-1",
        )

    assert db.repricer_catalog_rules.inserted == []


@pytest.mark.asyncio
async def test_catalog_service_patches_only_rule_owned_by_seller_and_account() -> None:
    from zeler_repricer.service import CatalogRuleNotFoundError, RepricerCatalogRuleService

    db = FakeDb([_catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1")])
    service = RepricerCatalogRuleService(db, clock=lambda: NOW)

    patched = await service.patch_catalog_rule(
        seller_id="123456789",
        rule_id="catalog-1",
        patch={"account_id": "acc-1", "active": False, "min_price": "101.00"},
        operator_id="operator-2",
    )

    assert patched.active is False
    assert patched.min_price == Decimal("101.00")
    assert db.repricer_catalog_rules.updates == [
        (
            {"_id": "catalog-1", "seller_id": "123456789", "account_id": "acc-1"},
            {
                "$set": {
                    "active": False,
                    "min_price": "101.00",
                    "updated_at": NOW,
                    "updated_by": "operator-2",
                }
            },
        )
    ]

    with pytest.raises(CatalogRuleNotFoundError):
        await service.patch_catalog_rule(
            seller_id="987654321",
            rule_id="catalog-1",
            patch={"account_id": "acc-1", "active": True},
            operator_id="operator-3",
        )


@pytest.mark.asyncio
async def test_catalog_service_refresh_counts_only_seller_scoped_catalog_rules() -> None:
    from zeler_repricer.service import RepricerCatalogRuleService

    db = FakeDb(
        [
            _catalog_rule("catalog-1", seller_id="123456789", account_id="acc-1"),
            _catalog_rule("catalog-2", seller_id="123456789", account_id="acc-2"),
            _catalog_rule("catalog-3", seller_id="987654321", account_id="acc-1"),
        ]
    )
    service = RepricerCatalogRuleService(db, clock=lambda: NOW)

    result = await service.refresh_catalog_rules(seller_id="123456789", account_id="acc-1")

    assert result == {"status": "refreshed", "matched_rules": 1}
    assert db.repricer_catalog_rules.filters == [{"seller_id": "123456789", "account_id": "acc-1"}]


@pytest.mark.asyncio
async def test_guard_service_upserts_limits_by_seller_and_account() -> None:
    from zeler_repricer.service import RepricerGuardService

    db = FakeDb()
    service = RepricerGuardService(db, clock=lambda: NOW)

    limits = await service.put_limits(
        seller_id="123456789",
        account_id="acc-1",
        payload={
            "enabled": True,
            "min_price_limit": "100.00",
            "max_price_limit": "150.00",
            "undercut_delta": "2.00",
            "pause_competition": False,
            "escalate_to_manual_review": True,
        },
    )
    loaded = await service.get_limits(seller_id="123456789", account_id="acc-1")

    assert limits.id == "limits-123456789-acc-1"
    assert limits.min_price_limit == Decimal("100.00")
    assert limits.escalate_to_manual_review is True
    assert loaded == limits
    assert db.repricer_limits.replacements == [
        (
            {"seller_id": "123456789", "account_id": "acc-1"},
            limits.model_dump(mode="json", by_alias=True),
            True,
        )
    ]


@pytest.mark.asyncio
async def test_guard_service_rejects_invalid_limits_before_upsert() -> None:
    from zeler_repricer.service import CatalogRuleValidationError, RepricerGuardService

    db = FakeDb()
    service = RepricerGuardService(db, clock=lambda: NOW)

    with pytest.raises(CatalogRuleValidationError, match="min_limit_above_max_limit"):
        await service.put_limits(
            seller_id="123456789",
            account_id="acc-1",
            payload={
                "enabled": True,
                "min_price_limit": "160.00",
                "max_price_limit": "150.00",
                "undercut_delta": "2.00",
                "pause_competition": False,
                "escalate_to_manual_review": False,
            },
        )

    assert db.repricer_limits.replacements == []


@pytest.mark.asyncio
async def test_guard_service_upserts_allies_by_seller() -> None:
    from zeler_repricer.service import RepricerGuardService

    db = FakeDb()
    service = RepricerGuardService(db, clock=lambda: NOW)

    allies = await service.put_allies(
        seller_id="123456789",
        payload={
            "allies": [
                {"account_id": "ally-1", "nickname": "ALLY SHOP"},
                {"seller_id": 987, "nickname": "LEGACY ALIAS"},
            ]
        },
    )
    loaded = await service.get_allies(seller_id="123456789")

    assert [ally.account_id for ally in allies.allies] == ["ally-1", "987"]
    assert loaded == allies
    assert db.repricer_allies.replacements == [
        (
            {"seller_id": "123456789"},
            allies.model_dump(mode="json", by_alias=True),
            True,
        )
    ]


@pytest.mark.asyncio
async def test_bulk_service_validates_csv_rows_with_catalog_guards_and_allies() -> None:
    from zeler_repricer.service import RepricerBulkJobService

    db = FakeDb()
    db.repricer_limits.documents.append(
        _limits_doc(
            seller_id="123456789",
            account_id="acc-1",
            min_price="90.00",
            max_price="130.00",
        )
    )
    db.repricer_allies.documents.append(_allies_doc(seller_id="123456789", account_ids=["ally-1"]))
    service = RepricerBulkJobService(db, clock=lambda: NOW)

    result = await service.validate_upload(
        seller_id="123456789",
        account_id="acc-1",
        source_filename="catalog-upload.csv",
        content=(
            "item_id,title,sku,strategy,min_price,max_price,active,ally_account_id\n"
            "MLA1,Valid Item,SKU-1,competitive,100.00,120.00,true,ally-1\n"
            "MLA2,Bad Bounds,SKU-2,competitive,150.00,120.00,true,\n"
            "MLA3,Below Guard,SKU-3,competitive,80.00,100.00,true,\n"
            "MLA4,Unknown Ally,SKU-4,competitive,100.00,120.00,true,ghost-ally\n"
        ),
        operator_id="operator-1",
    )

    assert result.job.status == "validated"
    assert result.job.total_rows == 4
    assert result.job.success_rows == 1
    assert result.job.failed_rows == 3
    assert [row.status for row in result.rows] == ["validated", "failed", "failed", "failed"]
    assert [row.error_code for row in result.rows] == [
        None,
        "min_price_above_max_price",
        "min_price_below_limit",
        "unknown_ally_account",
    ]
    assert result.rows[0].payload == {
        "account_id": "acc-1",
        "item_id": "MLA1",
        "title": "Valid Item",
        "sku": "SKU-1",
        "strategy": "competitive",
        "min_price": "100.00",
        "max_price": "120.00",
        "active": True,
        "ally_account_id": "ally-1",
    }
    assert db.repricer_bulk_jobs.replacements[0][0] == {
        "_id": result.job.id,
        "seller_id": "123456789",
    }
    assert len(db.repricer_bulk_rows.replacements) == 4


@pytest.mark.asyncio
async def test_bulk_service_processes_valid_rows_and_is_retry_safe() -> None:
    from zeler_repricer.service import RepricerBulkJobService

    db = FakeDb()
    service = RepricerBulkJobService(db, clock=lambda: NOW)
    validation = await service.validate_upload(
        seller_id="123456789",
        account_id="acc-1",
        source_filename="catalog-upload.csv",
        content=(
            "item_id,title,sku,strategy,min_price,max_price,active\n"
            "MLA1,New Item,SKU-1,competitive,100.00,120.00,true\n"
            "MLA2,Bad Bounds,SKU-2,competitive,150.00,120.00,true\n"
        ),
        operator_id="operator-1",
    )

    processed = await service.process_job(
        seller_id="123456789", job_id=validation.job.id, operator_id="operator-1"
    )
    retried = await service.process_job(
        seller_id="123456789", job_id=validation.job.id, operator_id="operator-1"
    )

    assert processed.status == "completed_with_errors"
    assert processed.processed_rows == 2
    assert processed.success_rows == 1
    assert processed.failed_rows == 1
    assert retried == processed
    assert [row[1]["status"] for row in db.repricer_bulk_rows.replacements[-2:]] == [
        "processed",
        "failed",
    ]
    assert [doc["_id"] for doc in db.repricer_catalog_rules.documents] == [
        "catalog-123456789-acc-1-MLA1"
    ]
    assert db.repricer_catalog_rules.documents[0]["updated_by"] == "operator-1"


@pytest.mark.asyncio
async def test_history_service_filters_catalog_outcomes_and_paginates_by_seller() -> None:
    from zeler_repricer.service import RepricerHistoryService

    db = FakeDb()
    db.repricer_history.documents.extend(
        [
            _history_doc(
                "history-1",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
                job_id="job-1",
                report_id="report-1",
            ),
            _history_doc(
                "history-2",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA2",
                reason="below_floor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 5, tzinfo=UTC),
                job_id="job-1",
            ),
            _history_doc(
                "history-3",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA3",
                reason="competition_paused",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 10, tzinfo=UTC),
            ),
            _history_doc(
                "history-4",
                seller_id="123456789",
                account_id="acc-2",
                item_id="MLA4",
                reason="ally_competitor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 12, 15, tzinfo=UTC),
            ),
            _history_doc(
                "history-5",
                seller_id="987654321",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 12, 20, tzinfo=UTC),
            ),
        ]
    )
    service = RepricerHistoryService(db)

    page = await service.list_history(
        seller_id="123456789",
        account_id="acc-1",
        from_date=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        to_date=datetime(2026, 5, 13, 12, 10, tzinfo=UTC),
        limit=2,
        offset=1,
    )
    guard_blocked = await service.list_history(
        seller_id="123456789", outcome="guard_blocked", job_id="job-1"
    )
    report_scoped = await service.list_history(
        seller_id="123456789", item_id="MLA1", report_id="report-1"
    )
    no_action = await service.list_history(seller_id="123456789", status="no_action")

    assert [entry["_id"] for entry in page] == ["history-2", "history-1"]
    assert [entry["outcome"] for entry in page] == ["guard_blocked", "applied"]
    assert [entry["_id"] for entry in guard_blocked] == ["history-2"]
    assert [entry["_id"] for entry in report_scoped] == ["history-1"]
    assert [entry["_id"] for entry in no_action] == ["history-4"]
    assert db.repricer_history.filters == [
        {"seller_id": "123456789", "account_id": "acc-1"},
        {"seller_id": "123456789", "job_id": "job-1"},
        {"seller_id": "123456789", "item_id": "MLA1", "report_id": "report-1"},
        {"seller_id": "123456789"},
    ]


@pytest.mark.asyncio
async def test_report_service_creates_and_downloads_rules_export() -> None:
    from zeler_repricer.service import RepricerReportService

    db = FakeDb(
        [
            _catalog_rule(
                "catalog-1",
                seller_id="123456789",
                account_id="acc-1",
                sku="SKU-1",
            ),
            _catalog_rule(
                "catalog-2",
                seller_id="123456789",
                account_id="acc-2",
                sku="SKU-2",
            ),
            _catalog_rule(
                "catalog-3",
                seller_id="987654321",
                account_id="acc-1",
                sku="SKU-3",
            ),
        ]
    )
    service = RepricerReportService(db, clock=lambda: NOW)

    created = await service.create_rules_export(
        seller_id="123456789",
        account_id="acc-1",
        requested_by="operator-1",
    )
    listed = await service.list_reports(
        seller_id="123456789",
        account_id="acc-1",
        status="ready",
        report_type="rules_export",
    )
    download = await service.get_download(seller_id="123456789", report_id=created.id)

    assert created.id == "report-123456789-acc-1-rules_export-20260513T190000Z"
    assert created.status == "ready"
    assert created.storage_path == (
        "inline://repricer/reports/report-123456789-acc-1-rules_export-20260513T190000Z.csv"
    )
    assert created.row_count == 1
    assert listed == [created]
    assert download["filename"] == "repricer-rules-123456789-acc-1.csv"
    assert download["content_type"] == "text/csv"
    assert download["content"].splitlines() == [
        "item_id,title,sku,strategy,min_price,max_price,active,last_outcome",
        "MLA123,Catalog Item,SKU-1,competitive,100.00,120.00,true,",
    ]
    assert db.repricer_catalog_rules.filters == [{"seller_id": "123456789", "account_id": "acc-1"}]
    assert db.repricer_reports.replacements[0][0] == {
        "_id": created.id,
        "seller_id": "123456789",
    }
    assert db.repricer_reports.filters == [
        {
            "seller_id": "123456789",
            "account_id": "acc-1",
            "status": "ready",
            "report_type": "rules_export",
        },
        {"_id": created.id, "seller_id": "123456789"},
    ]


@pytest.mark.asyncio
async def test_monitoring_service_persists_snapshot_and_derives_scheduler_counts() -> None:
    from zeler_repricer.service import RepricerMonitoringService

    db = FakeDb(
        [
            _catalog_rule("catalog-active", seller_id="123456789", account_id="acc-1"),
            _catalog_rule(
                "catalog-paused",
                seller_id="123456789",
                account_id="acc-1",
                active=False,
            ),
            _catalog_rule("catalog-other-account", seller_id="123456789", account_id="acc-2"),
            _catalog_rule("catalog-other-seller", seller_id="987654321", account_id="acc-1"),
        ]
    )
    db.repricer_history.documents.extend(
        [
            _history_doc(
                "history-applied",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA1",
                reason="track_buybox",
                gateway_status=202,
                applied_at=datetime(2026, 5, 13, 18, 55, tzinfo=UTC),
            ),
            _history_doc(
                "history-guard",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA2",
                reason="below_floor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 18, 56, tzinfo=UTC),
            ),
            _history_doc(
                "history-no-action",
                seller_id="123456789",
                account_id="acc-1",
                item_id="MLA3",
                reason="ally_competitor",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 18, 57, tzinfo=UTC),
            ),
            _history_doc(
                "history-paused",
                seller_id="123456789",
                account_id="acc-2",
                item_id="MLA4",
                reason="competition_paused",
                gateway_status=None,
                applied_at=datetime(2026, 5, 13, 18, 58, tzinfo=UTC),
            ),
        ]
    )
    db.repricer_bulk_jobs.documents.extend(
        [
            _bulk_job_doc(
                "bulk-active", seller_id="123456789", account_id="acc-1", status="processing"
            ),
            _bulk_job_doc(
                "bulk-done", seller_id="123456789", account_id="acc-1", status="completed"
            ),
        ]
    )
    db.repricer_monitoring_snapshots.documents.append(
        _snapshot_doc(
            "snapshot-previous",
            seller_id="123456789",
            account_id="acc-1",
            generated_at=datetime(2026, 5, 13, 18, 50, tzinfo=UTC),
            worker_heartbeat_at=datetime(2026, 5, 13, 18, 59, tzinfo=UTC),
        )
    )
    service = RepricerMonitoringService(db, clock=lambda: NOW)

    status = await service.get_status(seller_id="123456789", account_id="acc-1")

    assert status["health"] == {
        "ready": True,
        "checks": {"catalog_rules": "ok", "worker_heartbeat": "ok"},
    }
    assert status["metrics"] == {
        "active_rules": 1,
        "paused_rules": 1,
        "active_bulk_jobs": 1,
    }
    assert status["scheduler"] == {
        "last_run_at": "2026-05-13T18:50:00Z",
        "next_run_at": "2026-05-13T18:55:00Z",
        "due": True,
        "interval_minutes": 5,
        "processed_count": 3,
        "applied_count": 1,
        "blocked_count": 1,
        "no_action_count": 1,
        "paused_count": 0,
        "error_summary": {},
    }
    assert status["snapshot"]["_id"] == "monitoring-123456789-acc-1-20260513T190000Z"
    assert status["snapshot"]["active_bulk_job_ids"] == ["bulk-active"]
    assert status["snapshot"]["generated_at"] == "2026-05-13T19:00:00Z"
    assert status["snapshot"]["worker_heartbeat_at"] == "2026-05-13T18:59:00Z"

    persisted_snapshot = db.repricer_monitoring_snapshots.inserted[0]
    assert persisted_snapshot["generated_at"] == NOW
    assert persisted_snapshot["worker_heartbeat_at"] == datetime(2026, 5, 13, 18, 59, tzinfo=UTC)


@pytest.mark.asyncio
async def test_monitoring_service_reports_due_unknown_worker_without_live_meli_probe() -> None:
    from zeler_repricer.service import RepricerMonitoringService

    db = FakeDb([_catalog_rule("catalog-active", seller_id="123456789", account_id="acc-1")])
    service = RepricerMonitoringService(db, clock=lambda: NOW)

    status = await service.get_status(seller_id="123456789", account_id="acc-1")

    assert status["health"] == {
        "ready": True,
        "checks": {"catalog_rules": "ok", "worker_heartbeat": "unknown"},
    }
    assert status["scheduler"]["last_run_at"] is None
    assert status["scheduler"]["next_run_at"] is None
    assert status["scheduler"]["due"] is True
    assert status["snapshot"]["generated_at"] == "2026-05-13T19:00:00Z"
    assert status["snapshot"]["worker_heartbeat_at"] is None
    persisted_snapshot = db.repricer_monitoring_snapshots.inserted[0]
    assert persisted_snapshot["generated_at"] == NOW
    assert persisted_snapshot["worker_heartbeat_at"] is None


def _catalog_rule(
    rule_id: str,
    *,
    seller_id: str,
    account_id: str,
    sku: str = "SKU-1",
    active: bool = True,
) -> dict[str, Any]:
    return {
        "_id": rule_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "item_id": "MLA123",
        "title": "Catalog Item",
        "sku": sku,
        "strategy": "competitive",
        "min_price": "100.00",
        "max_price": "120.00",
        "active": active,
        "execution_state": {},
        "created_at": NOW,
        "updated_at": NOW,
        "created_by": "operator-1",
        "updated_by": "operator-1",
        "schema_version": 1,
    }


def _history_doc(
    history_id: str,
    *,
    seller_id: str,
    account_id: str,
    item_id: str,
    reason: str,
    gateway_status: int | None,
    applied_at: datetime,
    job_id: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": history_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "rule_id": f"catalog-{item_id}",
        "item_id": item_id,
        "old_price": "150.00",
        "new_price": "149.00",
        "reason": reason,
        "applied_at": applied_at,
        "gateway_status": gateway_status,
        "gateway_latency_ms": 11 if gateway_status is not None else None,
        "event_id": f"event-{history_id}",
        "schema_version": 1,
    }
    if job_id is not None:
        document["job_id"] = job_id
    if report_id is not None:
        document["report_id"] = report_id
    return document


def _bulk_job_doc(job_id: str, *, seller_id: str, account_id: str, status: str) -> dict[str, Any]:
    return {
        "_id": job_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "status": status,
        "source_filename": "catalog-upload.csv",
        "total_rows": 2,
        "processed_rows": 1,
        "success_rows": 1,
        "failed_rows": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "created_by": "operator-1",
        "schema_version": 1,
    }


def _snapshot_doc(
    snapshot_id: str,
    *,
    seller_id: str,
    account_id: str,
    generated_at: datetime,
    worker_heartbeat_at: datetime | None,
) -> dict[str, Any]:
    return {
        "_id": snapshot_id,
        "seller_id": seller_id,
        "account_id": account_id,
        "generated_at": generated_at,
        "worker_heartbeat_at": worker_heartbeat_at,
        "queue_backlog": {"repricer.sweep.requested": 0},
        "error_buckets": {},
        "active_bulk_job_ids": [],
        "schema_version": 1,
    }


def _limits_doc(
    *, seller_id: str, account_id: str, min_price: str, max_price: str
) -> dict[str, Any]:
    return {
        "_id": f"limits-{seller_id}-{account_id}",
        "seller_id": seller_id,
        "account_id": account_id,
        "enabled": True,
        "min_price_limit": min_price,
        "max_price_limit": max_price,
        "undercut_delta": "1.00",
        "pause_competition": False,
        "escalate_to_manual_review": False,
        "created_at": NOW,
        "updated_at": NOW,
        "schema_version": 1,
    }


def _allies_doc(*, seller_id: str, account_ids: list[str]) -> dict[str, Any]:
    return {
        "_id": f"allies-{seller_id}",
        "seller_id": seller_id,
        "allies": [{"account_id": account_id} for account_id in account_ids],
        "created_at": NOW,
        "updated_at": NOW,
        "schema_version": 1,
    }
