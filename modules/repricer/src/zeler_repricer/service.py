from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Protocol, cast

from zeler_platform_core.models import (
    RepricerAllies,
    RepricerBulkJob,
    RepricerBulkRow,
    RepricerCatalogRule,
    RepricerLimits,
    RepricerMonitoringSnapshot,
    RepricerReport,
)


class CatalogRuleValidationError(ValueError):
    """Raised when a catalog rule command violates business invariants."""


class CatalogRuleNotFoundError(LookupError):
    """Raised when a seller-scoped catalog rule mutation matches no rule."""


class BulkJobNotFoundError(LookupError):
    """Raised when a seller-scoped bulk job lookup matches no job."""


class ReportNotFoundError(LookupError):
    """Raised when a seller-scoped report lookup matches no report."""


@dataclass(frozen=True)
class BulkValidationResult:
    job: RepricerBulkJob
    rows: list[RepricerBulkRow]


class AsyncCatalogCursor(Protocol):
    def sort(self, sort_spec: list[tuple[str, int]]) -> AsyncCatalogCursor: ...
    def skip(self, count: int) -> AsyncCatalogCursor: ...
    def limit(self, count: int) -> AsyncCatalogCursor: ...
    async def to_list(self, length: int) -> list[dict[str, Any]]: ...


class AsyncCatalogCollection(Protocol):
    def find(self, filter_spec: dict[str, Any]) -> AsyncCatalogCursor: ...
    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None: ...
    async def insert_one(self, document: dict[str, Any]) -> Any: ...
    async def update_one(self, filter_spec: dict[str, Any], update: dict[str, Any]) -> Any: ...
    async def replace_one(
        self, filter_spec: dict[str, Any], document: dict[str, Any], *, upsert: bool
    ) -> Any: ...


class CatalogDatabase(Protocol):
    def __getitem__(self, name: str) -> AsyncCatalogCollection: ...


_ACTIVE_BULK_JOB_STATUSES = {"draft", "validated", "processing"}


class RepricerCatalogRuleService:
    def __init__(
        self,
        db: CatalogDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._collection = db["repricer_catalog_rules"]
        self._clock = clock

    async def list_catalog_rules(
        self,
        *,
        seller_id: object,
        account_id: object | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RepricerCatalogRule]:
        filter_spec: dict[str, Any] = {"seller_id": str(seller_id)}
        if account_id is not None:
            filter_spec["account_id"] = str(account_id)
        active_filter = _status_to_active(status)
        if active_filter is not None:
            filter_spec["active"] = active_filter

        cursor = (
            self._collection.find(filter_spec).sort([("updated_at", -1)]).skip(offset).limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        rules = [RepricerCatalogRule.model_validate(document) for document in documents]
        return _filter_rules_by_query(rules, query)

    async def create_catalog_rule(
        self,
        *,
        seller_id: object,
        payload: dict[str, Any],
        operator_id: str,
    ) -> RepricerCatalogRule:
        min_price = Decimal(str(payload["min_price"]))
        max_price = Decimal(str(payload["max_price"]))
        if min_price > max_price:
            raise CatalogRuleValidationError("min_price_above_max_price")

        now = self._clock()
        account_id = str(payload["account_id"])
        item_id = str(payload["item_id"])
        rule_id = str(payload.get("_id") or f"catalog-{seller_id}-{account_id}-{item_id}")
        rule = RepricerCatalogRule.model_validate(
            {
                "_id": rule_id,
                "seller_id": str(seller_id),
                "account_id": account_id,
                "item_id": item_id,
                "title": payload.get("title"),
                "sku": payload.get("sku"),
                "strategy": payload["strategy"],
                "min_price": min_price,
                "max_price": max_price,
                "active": bool(payload.get("active", True)),
                "execution_state": payload.get("execution_state") or {},
                "created_at": now,
                "updated_at": now,
                "created_by": operator_id,
                "updated_by": operator_id,
            }
        )
        await self._collection.insert_one(rule.model_dump(mode="json", by_alias=True))
        return rule

    async def patch_catalog_rule(
        self,
        *,
        seller_id: object,
        rule_id: str,
        patch: dict[str, Any],
        operator_id: str,
    ) -> RepricerCatalogRule:
        filter_spec: dict[str, Any] = {"_id": rule_id, "seller_id": str(seller_id)}
        if patch.get("account_id") is not None:
            filter_spec["account_id"] = str(patch["account_id"])

        update_fields = {
            key: value
            for key, value in patch.items()
            if key not in {"_id", "seller_id", "account_id"} and value is not None
        }
        update_fields["updated_at"] = self._clock()
        update_fields["updated_by"] = operator_id
        result = await self._collection.update_one(filter_spec, {"$set": update_fields})
        if getattr(result, "matched_count", 0) == 0:
            raise CatalogRuleNotFoundError(rule_id)

        cursor = self._collection.find(filter_spec).limit(1)
        documents = await cursor.to_list(length=1)
        if not documents:
            raise CatalogRuleNotFoundError(rule_id)
        return RepricerCatalogRule.model_validate(documents[0])

    async def refresh_catalog_rules(
        self, *, seller_id: object, account_id: object | None = None
    ) -> dict[str, int | str]:
        rules = await self.list_catalog_rules(seller_id=seller_id, account_id=account_id)
        return {"status": "refreshed", "matched_rules": len(rules)}


class RepricerGuardService:
    def __init__(
        self,
        db: CatalogDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._limits = db["repricer_limits"]
        self._allies = db["repricer_allies"]
        self._clock = clock

    async def get_limits(self, *, seller_id: object, account_id: object) -> RepricerLimits | None:
        document = await self._limits.find_one(
            {"seller_id": str(seller_id), "account_id": str(account_id)}
        )
        if document is None:
            return None
        return RepricerLimits.model_validate(document)

    async def put_limits(
        self,
        *,
        seller_id: object,
        account_id: object,
        payload: dict[str, Any],
    ) -> RepricerLimits:
        min_price_limit = Decimal(str(payload["min_price_limit"]))
        max_price_limit = Decimal(str(payload["max_price_limit"]))
        if min_price_limit > max_price_limit:
            raise CatalogRuleValidationError("min_limit_above_max_limit")

        now = self._clock()
        existing = await self.get_limits(seller_id=seller_id, account_id=account_id)
        limits = RepricerLimits.model_validate(
            {
                "_id": f"limits-{seller_id}-{account_id}",
                "seller_id": str(seller_id),
                "account_id": str(account_id),
                "enabled": bool(payload.get("enabled", True)),
                "min_price_limit": min_price_limit,
                "max_price_limit": max_price_limit,
                "undercut_delta": Decimal(str(payload.get("undercut_delta", "0"))),
                "pause_competition": bool(payload.get("pause_competition", False)),
                "escalate_to_manual_review": bool(payload.get("escalate_to_manual_review", False)),
                "created_at": existing.created_at if existing is not None else now,
                "updated_at": now,
            }
        )
        await self._limits.replace_one(
            {"seller_id": str(seller_id), "account_id": str(account_id)},
            limits.model_dump(mode="json", by_alias=True),
            upsert=True,
        )
        return limits

    async def get_allies(self, *, seller_id: object) -> RepricerAllies | None:
        document = await self._allies.find_one({"seller_id": str(seller_id)})
        if document is None:
            return None
        return RepricerAllies.model_validate(document)

    async def put_allies(self, *, seller_id: object, payload: dict[str, Any]) -> RepricerAllies:
        now = self._clock()
        existing = await self.get_allies(seller_id=seller_id)
        allies = RepricerAllies.model_validate(
            {
                "_id": f"allies-{seller_id}",
                "seller_id": str(seller_id),
                "allies": payload.get("allies", []),
                "created_at": existing.created_at if existing is not None else now,
                "updated_at": now,
            }
        )
        await self._allies.replace_one(
            {"seller_id": str(seller_id)},
            allies.model_dump(mode="json", by_alias=True),
            upsert=True,
        )
        return allies


class RepricerBulkJobService:
    def __init__(
        self,
        db: CatalogDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._rules = db["repricer_catalog_rules"]
        self._limits = db["repricer_limits"]
        self._allies = db["repricer_allies"]
        self._jobs = db["repricer_bulk_jobs"]
        self._rows = db["repricer_bulk_rows"]
        self._clock = clock

    async def validate_upload(
        self,
        *,
        seller_id: object,
        account_id: object,
        source_filename: str,
        content: str,
        operator_id: str,
    ) -> BulkValidationResult:
        seller = str(seller_id)
        account = str(account_id)
        now = self._clock()
        parsed_rows = _parse_catalog_csv(content)
        limits = await self._load_limits(seller_id=seller, account_id=account)
        allies = await self._load_allies(seller_id=seller)
        job_id = _bulk_job_id(seller, account, content)
        row_models = [
            self._validate_row(
                seller_id=seller,
                account_id=account,
                job_id=job_id,
                row_number=row_number,
                raw_row=raw_row,
                limits=limits,
                allies=allies,
                now=now,
            )
            for row_number, raw_row in parsed_rows
        ]
        success_rows = sum(1 for row in row_models if row.status == "validated")
        failed_rows = len(row_models) - success_rows
        job = RepricerBulkJob.model_validate(
            {
                "_id": job_id,
                "seller_id": seller,
                "account_id": account,
                "status": "validated",
                "source_filename": source_filename,
                "total_rows": len(row_models),
                "processed_rows": 0,
                "success_rows": success_rows,
                "failed_rows": failed_rows,
                "created_at": now,
                "updated_at": now,
                "created_by": operator_id,
            }
        )
        await self._jobs.replace_one(
            {"_id": job.id, "seller_id": seller},
            job.model_dump(mode="json", by_alias=True),
            upsert=True,
        )
        for row in row_models:
            await self._rows.replace_one(
                {"_id": row.id, "seller_id": seller},
                row.model_dump(mode="json", by_alias=True),
                upsert=True,
            )
        return BulkValidationResult(job=job, rows=row_models)

    async def process_job(
        self, *, seller_id: object, job_id: str, operator_id: str
    ) -> RepricerBulkJob:
        seller = str(seller_id)
        job = await self.get_job(seller_id=seller, job_id=job_id)
        if job.status in {"completed", "completed_with_errors", "failed"}:
            return job

        rows = await self.list_rows(seller_id=seller, job_id=job.id)
        now = self._clock()
        processed_rows: list[RepricerBulkRow] = []
        for row in rows:
            if row.status == "validated":
                await self._upsert_catalog_rule_from_row(row, operator_id=operator_id, now=now)
                row = row.model_copy(update={"status": "processed", "updated_at": now})
            processed_rows.append(row)
            await self._rows.replace_one(
                {"_id": row.id, "seller_id": seller},
                row.model_dump(mode="json", by_alias=True),
                upsert=True,
            )

        success_rows = sum(1 for row in processed_rows if row.status == "processed")
        failed_rows = sum(1 for row in processed_rows if row.status == "failed")
        status = "completed_with_errors" if failed_rows else "completed"
        updated_job = job.model_copy(
            update={
                "status": status,
                "processed_rows": len(processed_rows),
                "success_rows": success_rows,
                "failed_rows": failed_rows,
                "updated_at": now,
            }
        )
        await self._jobs.replace_one(
            {"_id": updated_job.id, "seller_id": seller},
            updated_job.model_dump(mode="json", by_alias=True),
            upsert=True,
        )
        return updated_job

    async def get_job(self, *, seller_id: object, job_id: str) -> RepricerBulkJob:
        document = await self._jobs.find_one({"_id": job_id, "seller_id": str(seller_id)})
        if document is None:
            raise BulkJobNotFoundError(job_id)
        return RepricerBulkJob.model_validate(document)

    async def list_rows(
        self, *, seller_id: object, job_id: str, status: str | None = None
    ) -> list[RepricerBulkRow]:
        filter_spec: dict[str, Any] = {"seller_id": str(seller_id), "job_id": job_id}
        if status is not None:
            filter_spec["status"] = status
        cursor = self._rows.find(filter_spec).sort([("row_number", 1)]).limit(1000)
        documents = await cursor.to_list(length=1000)
        return [RepricerBulkRow.model_validate(document) for document in documents]

    async def _load_limits(self, *, seller_id: str, account_id: str) -> RepricerLimits | None:
        document = await self._limits.find_one({"seller_id": seller_id, "account_id": account_id})
        if document is None:
            return None
        return RepricerLimits.model_validate(document)

    async def _load_allies(self, *, seller_id: str) -> RepricerAllies | None:
        document = await self._allies.find_one({"seller_id": seller_id})
        if document is None:
            return None
        return RepricerAllies.model_validate(document)

    def _validate_row(
        self,
        *,
        seller_id: str,
        account_id: str,
        job_id: str,
        row_number: int,
        raw_row: dict[str, str],
        limits: RepricerLimits | None,
        allies: RepricerAllies | None,
        now: datetime,
    ) -> RepricerBulkRow:
        payload, error_code, error_message = _normalize_bulk_row(
            raw_row=raw_row,
            row_number=row_number,
            account_id=account_id,
            limits=limits,
            allies=allies,
        )
        status = "failed" if error_code else "validated"
        return RepricerBulkRow.model_validate(
            {
                "_id": f"{job_id}-row-{row_number}",
                "seller_id": seller_id,
                "account_id": account_id,
                "job_id": job_id,
                "row_number": row_number,
                "status": status,
                "item_id": payload.get("item_id"),
                "payload": payload,
                "error_code": error_code,
                "error_message": error_message,
                "created_at": now,
                "updated_at": now,
            }
        )

    async def _upsert_catalog_rule_from_row(
        self, row: RepricerBulkRow, *, operator_id: str, now: datetime
    ) -> None:
        rule_id = f"catalog-{row.seller_id}-{row.account_id}-{row.item_id}"
        existing = await self._rules.find_one({"_id": rule_id, "seller_id": row.seller_id})
        payload = row.payload
        if existing is None:
            rule = RepricerCatalogRule.model_validate(
                {
                    "_id": rule_id,
                    "seller_id": row.seller_id,
                    "account_id": row.account_id,
                    "item_id": payload["item_id"],
                    "title": payload.get("title"),
                    "sku": payload.get("sku"),
                    "strategy": payload["strategy"],
                    "min_price": payload["min_price"],
                    "max_price": payload["max_price"],
                    "active": payload["active"],
                    "execution_state": {},
                    "created_at": now,
                    "updated_at": now,
                    "created_by": operator_id,
                    "updated_by": operator_id,
                }
            )
            await self._rules.insert_one(rule.model_dump(mode="json", by_alias=True))
            return

        update_fields = {
            "title": payload.get("title"),
            "sku": payload.get("sku"),
            "strategy": payload["strategy"],
            "min_price": payload["min_price"],
            "max_price": payload["max_price"],
            "active": payload["active"],
            "updated_at": now,
            "updated_by": operator_id,
        }
        await self._rules.update_one(
            {"_id": rule_id, "seller_id": row.seller_id}, {"$set": update_fields}
        )


class RepricerHistoryService:
    def __init__(self, db: CatalogDatabase) -> None:
        self._history = db["repricer_history"]

    async def list_history(
        self,
        *,
        seller_id: object,
        account_id: object | None = None,
        item_id: object | None = None,
        outcome: str | None = None,
        status: str | None = None,
        from_date: datetime | str | None = None,
        to_date: datetime | str | None = None,
        job_id: object | None = None,
        report_id: object | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filter_spec: dict[str, Any] = {"seller_id": str(seller_id)}
        if account_id is not None:
            filter_spec["account_id"] = str(account_id)
        if item_id is not None:
            filter_spec["item_id"] = str(item_id)
        if job_id is not None:
            filter_spec["job_id"] = str(job_id)
        if report_id is not None:
            filter_spec["report_id"] = str(report_id)

        fetch_limit = max(limit + offset, 100)
        cursor = _sort_and_limit_cursor(
            self._history.find(filter_spec), [("applied_at", -1)], fetch_limit
        )
        documents = await cursor.to_list(length=fetch_limit)
        normalized = [_history_payload(document) for document in documents]
        normalized.sort(key=lambda entry: _datetime_sort_key(entry.get("applied_at")), reverse=True)

        expected_outcome = outcome or status
        filtered = [
            entry
            for entry in normalized
            if _matches_history_filters(
                entry,
                outcome=expected_outcome,
                from_date=from_date,
                to_date=to_date,
            )
        ]
        return filtered[offset : offset + limit]


class RepricerReportService:
    def __init__(
        self,
        db: CatalogDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._rules = db["repricer_catalog_rules"]
        self._reports = db["repricer_reports"]
        self._clock = clock

    async def create_rules_export(
        self,
        *,
        seller_id: object,
        account_id: object,
        requested_by: str,
        format: str = "csv",
    ) -> RepricerReport:
        if format != "csv":
            raise CatalogRuleValidationError("unsupported_report_format")

        seller = str(seller_id)
        account = str(account_id)
        now = self._clock()
        rules = await self._list_rules(seller_id=seller, account_id=account)
        content = _rules_export_csv(rules)
        report_id = f"report-{seller}-{account}-rules_export-{_report_timestamp(now)}"
        report = RepricerReport.model_validate(
            {
                "_id": report_id,
                "seller_id": seller,
                "account_id": account,
                "report_type": "rules_export",
                "format": format,
                "status": "ready",
                "storage_path": f"inline://repricer/reports/{report_id}.csv",
                "row_count": len(rules),
                "created_at": now,
                "updated_at": now,
                "requested_by": requested_by,
            }
        )
        document = report.model_dump(mode="json", by_alias=True)
        document.update(
            {
                "filename": f"repricer-rules-{seller}-{account}.csv",
                "content_type": "text/csv",
                "inline_content": content,
            }
        )
        await self._reports.replace_one(
            {"_id": report.id, "seller_id": seller}, document, upsert=True
        )
        return report

    async def list_reports(
        self,
        *,
        seller_id: object,
        account_id: object | None = None,
        status: str | None = None,
        report_type: str | None = None,
        from_date: datetime | str | None = None,
        to_date: datetime | str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[RepricerReport]:
        filter_spec: dict[str, Any] = {"seller_id": str(seller_id)}
        if account_id is not None:
            filter_spec["account_id"] = str(account_id)
        if status is not None:
            filter_spec["status"] = status
        if report_type is not None:
            filter_spec["report_type"] = report_type

        fetch_limit = max(limit + offset, 100)
        cursor = _sort_and_limit_cursor(
            self._reports.find(filter_spec), [("created_at", -1)], fetch_limit
        )
        documents = await cursor.to_list(length=fetch_limit)
        filtered = [
            RepricerReport.model_validate(document)
            for document in sorted(
                documents,
                key=lambda document: _datetime_sort_key(document.get("created_at")),
                reverse=True,
            )
            if _matches_date_range(document.get("created_at"), from_date=from_date, to_date=to_date)
        ]
        return filtered[offset : offset + limit]

    async def get_download(self, *, seller_id: object, report_id: str) -> dict[str, Any]:
        document = await self._reports.find_one({"_id": report_id, "seller_id": str(seller_id)})
        if document is None:
            raise ReportNotFoundError(report_id)
        report = RepricerReport.model_validate(document)
        return {
            "report": report.model_dump(mode="json", by_alias=True),
            "filename": document.get("filename") or f"{report.id}.{report.format}",
            "content_type": document.get("content_type") or "text/csv",
            "content": document.get("inline_content") or "",
        }

    async def _list_rules(self, *, seller_id: str, account_id: str) -> list[RepricerCatalogRule]:
        cursor = _sort_and_limit_cursor(
            self._rules.find({"seller_id": seller_id, "account_id": account_id}),
            [("updated_at", -1)],
            1000,
        )
        documents = await cursor.to_list(length=1000)
        return [RepricerCatalogRule.model_validate(document) for document in documents]


class RepricerMonitoringService:
    def __init__(
        self,
        db: CatalogDatabase,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sweep_interval_minutes: int = 5,
    ) -> None:
        self._rules = db["repricer_catalog_rules"]
        self._jobs = db["repricer_bulk_jobs"]
        self._history = db["repricer_history"]
        self._snapshots = db["repricer_monitoring_snapshots"]
        self._clock = clock
        self._sweep_interval_minutes = sweep_interval_minutes

    async def get_status(self, *, seller_id: object, account_id: object) -> dict[str, Any]:
        seller = str(seller_id)
        account = str(account_id)
        now = self._clock()
        rules = await self._list_documents(
            self._rules, {"seller_id": seller, "account_id": account}, sort=[("updated_at", -1)]
        )
        jobs = await self._list_documents(
            self._jobs, {"seller_id": seller, "account_id": account}, sort=[("updated_at", -1)]
        )
        history = await self._list_documents(
            self._history, {"seller_id": seller, "account_id": account}, sort=[("applied_at", -1)]
        )
        previous_snapshots = await self._list_documents(
            self._snapshots,
            {"seller_id": seller, "account_id": account},
            sort=[("generated_at", -1)],
        )
        previous_snapshot = _latest_snapshot(previous_snapshots)
        active_jobs = [job for job in jobs if job.get("status") in _ACTIVE_BULK_JOB_STATUSES]
        worker_heartbeat_at = (
            _parse_datetime(previous_snapshot.get("worker_heartbeat_at"))
            if previous_snapshot is not None
            else None
        )
        snapshot = RepricerMonitoringSnapshot.model_validate(
            {
                "_id": f"monitoring-{seller}-{account}-{_report_timestamp(now)}",
                "seller_id": seller,
                "account_id": account,
                "generated_at": now,
                "worker_heartbeat_at": worker_heartbeat_at,
                "queue_backlog": {"repricer.sweep.requested": 0},
                "error_buckets": _error_buckets(history),
                "active_bulk_job_ids": [str(job["_id"]) for job in active_jobs],
            }
        )
        snapshot_document = snapshot.model_dump(mode="python", by_alias=True)
        await self._snapshots.insert_one(snapshot_document)
        snapshot_payload = snapshot.model_dump(mode="json", by_alias=True)

        return {
            "snapshot": snapshot_payload,
            "metrics": {
                "active_rules": sum(1 for rule in rules if rule.get("active") is True),
                "paused_rules": sum(1 for rule in rules if rule.get("active") is False),
                "active_bulk_jobs": len(active_jobs),
            },
            "scheduler": _scheduler_status(
                history=history,
                previous_snapshot=previous_snapshot,
                now=now,
                interval_minutes=self._sweep_interval_minutes,
            ),
            "health": _monitoring_health(
                rules=rules, worker_heartbeat_at=worker_heartbeat_at, now=now
            ),
        }

    async def _list_documents(
        self,
        collection: AsyncCatalogCollection,
        filter_spec: dict[str, Any],
        *,
        sort: list[tuple[str, int]],
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        cursor = _sort_and_limit_cursor(collection.find(filter_spec), sort, limit)
        return cast(list[dict[str, Any]], await cursor.to_list(length=limit))


def _status_to_active(status: str | None) -> bool | None:
    if status in (None, "all"):
        return None
    if status == "active":
        return True
    if status in {"inactive", "paused"}:
        return False
    raise CatalogRuleValidationError("invalid_status")


def _filter_rules_by_query(
    rules: list[RepricerCatalogRule], query: str | None
) -> list[RepricerCatalogRule]:
    if not query:
        return rules
    normalized = query.casefold()
    return [
        rule
        for rule in rules
        if any(
            normalized in value.casefold()
            for value in (rule.item_id, rule.sku or "", rule.title or "")
        )
    ]


def _parse_catalog_csv(content: str) -> list[tuple[int, dict[str, str]]]:
    reader = csv.DictReader(StringIO(content))
    if reader.fieldnames is None:
        return []
    return [
        (index, {str(key): (value or "").strip() for key, value in row.items() if key is not None})
        for index, row in enumerate(reader, start=2)
    ]


def _bulk_job_id(seller_id: str, account_id: str, content: str) -> str:
    digest = hashlib.sha256(f"{seller_id}:{account_id}:{content}".encode()).hexdigest()[:12]
    return f"bulk-{seller_id}-{account_id}-{digest}"


def _normalize_bulk_row(
    *,
    raw_row: dict[str, str],
    row_number: int,
    account_id: str,
    limits: RepricerLimits | None,
    allies: RepricerAllies | None,
) -> tuple[dict[str, Any], str | None, str | None]:
    row_account_id = raw_row.get("account_id") or account_id
    payload: dict[str, Any] = {
        "account_id": row_account_id,
        "item_id": raw_row.get("item_id", ""),
        "title": raw_row.get("title") or None,
        "sku": raw_row.get("sku") or None,
        "strategy": raw_row.get("strategy", ""),
        "min_price": raw_row.get("min_price", ""),
        "max_price": raw_row.get("max_price", ""),
        "active": _parse_bool(raw_row.get("active", "true")),
    }
    ally_account_id = raw_row.get("ally_account_id") or None
    if ally_account_id is not None:
        payload["ally_account_id"] = ally_account_id

    required_fields = ("item_id", "strategy", "min_price", "max_price")
    missing = [field for field in required_fields if not payload[field]]
    if missing:
        return payload, "missing_required_field", f"Row {row_number} missing {missing[0]}"
    if row_account_id != account_id:
        return payload, "account_mismatch", f"Row {row_number} account_id does not match the job"
    if payload["strategy"] not in {"min_price", "competitive", "maximize"}:
        return payload, "invalid_strategy", f"Row {row_number} strategy is not supported"

    try:
        min_price = Decimal(str(payload["min_price"]))
        max_price = Decimal(str(payload["max_price"]))
    except InvalidOperation:
        return payload, "invalid_price", f"Row {row_number} has an invalid decimal price"

    if min_price > max_price:
        return (
            payload,
            "min_price_above_max_price",
            f"Row {row_number} min_price is above max_price",
        )
    if limits is not None and limits.enabled:
        if min_price < limits.min_price_limit:
            return (
                payload,
                "min_price_below_limit",
                f"Row {row_number} min_price is below the configured limit",
            )
        if max_price > limits.max_price_limit:
            return (
                payload,
                "max_price_above_limit",
                f"Row {row_number} max_price is above the configured limit",
            )
    if ally_account_id is not None and allies is not None:
        known_allies = {ally.account_id for ally in allies.allies}
        if ally_account_id not in known_allies:
            return payload, "unknown_ally_account", f"Row {row_number} references an unknown ally"
    return payload, None, None


def _parse_bool(value: str) -> bool:
    return value.strip().casefold() not in {"false", "0", "no", "inactive"}


def _history_payload(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document)
    if _is_catalog_history(payload):
        payload["outcome"] = str(payload.get("outcome") or _history_outcome(payload))
    return payload


def _sort_and_limit_cursor(cursor: Any, sort_spec: list[tuple[str, int]], limit: int) -> Any:
    if hasattr(cursor, "sort"):
        cursor = cursor.sort(sort_spec)
    if hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)
    return cursor


def _is_catalog_history(document: dict[str, Any]) -> bool:
    return any(document.get(key) is not None for key in ("account_id", "rule_id", "outcome"))


def _history_outcome(document: dict[str, Any]) -> str:
    if document.get("gateway_status") is not None:
        return "applied"
    reason = str(document.get("reason") or "")
    if reason in {"paused", "competition_paused"}:
        return "paused"
    if reason in {"below_floor", "manual_review_required"}:
        return "guard_blocked"
    return "no_action"


def _latest_snapshot(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not documents:
        return None
    return max(documents, key=lambda document: _datetime_sort_key(document.get("generated_at")))


def _scheduler_status(
    *,
    history: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
    now: datetime,
    interval_minutes: int,
) -> dict[str, Any]:
    last_run_at = (
        _parse_datetime(previous_snapshot.get("generated_at"))
        if previous_snapshot is not None
        else None
    )
    next_run_at = (
        last_run_at + _minutes_delta(interval_minutes) if last_run_at is not None else None
    )
    counts = _history_counts(history)
    return {
        "last_run_at": _isoformat_z(last_run_at),
        "next_run_at": _isoformat_z(next_run_at),
        "due": next_run_at is None or now >= next_run_at,
        "interval_minutes": interval_minutes,
        "processed_count": counts["processed"],
        "applied_count": counts["applied"],
        "blocked_count": counts["blocked"],
        "no_action_count": counts["no_action"],
        "paused_count": counts["paused"],
        "error_summary": _error_buckets(history),
    }


def _minutes_delta(minutes: int) -> Any:
    from datetime import timedelta

    return timedelta(minutes=minutes)


def _history_counts(history: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"processed": 0, "applied": 0, "blocked": 0, "no_action": 0, "paused": 0}
    for document in history:
        outcome = _history_payload(document).get("outcome")
        if outcome not in {"applied", "guard_blocked", "no_action", "paused"}:
            continue
        counts["processed"] += 1
        if outcome == "guard_blocked":
            counts["blocked"] += 1
        else:
            counts[str(outcome)] += 1
    return counts


def _error_buckets(history: list[dict[str, Any]]) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for document in history:
        if _history_payload(document).get("outcome") != "error":
            continue
        key = str(document.get("reason") or document.get("error_code") or "unknown")
        buckets[key] = buckets.get(key, 0) + 1
    return buckets


def _monitoring_health(
    *, rules: list[dict[str, Any]], worker_heartbeat_at: datetime | None, now: datetime
) -> dict[str, Any]:
    worker_check = "unknown"
    if worker_heartbeat_at is not None:
        worker_check = "ok" if (now - worker_heartbeat_at).total_seconds() <= 600 else "stale"
    return {
        "ready": bool(rules),
        "checks": {
            "catalog_rules": "ok" if rules else "empty",
            "worker_heartbeat": worker_check,
        },
    }


def _isoformat_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _matches_history_filters(
    entry: dict[str, Any],
    *,
    outcome: str | None,
    from_date: datetime | str | None,
    to_date: datetime | str | None,
) -> bool:
    if outcome is not None and entry.get("outcome") != outcome:
        return False
    return _matches_date_range(entry.get("applied_at"), from_date=from_date, to_date=to_date)


def _matches_date_range(
    value: object,
    *,
    from_date: datetime | str | None,
    to_date: datetime | str | None,
) -> bool:
    parsed_value = _parse_datetime(value)
    parsed_from = _parse_datetime(from_date)
    parsed_to = _parse_datetime(to_date)
    if parsed_value is None:
        return True
    if parsed_from is not None and parsed_value < parsed_from:
        return False
    return not (parsed_to is not None and parsed_value > parsed_to)


def _datetime_sort_key(value: object) -> datetime:
    return _parse_datetime(value) or datetime.min.replace(tzinfo=UTC)


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    return None


def _rules_export_csv(rules: list[RepricerCatalogRule]) -> str:
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "item_id",
            "title",
            "sku",
            "strategy",
            "min_price",
            "max_price",
            "active",
            "last_outcome",
        ]
    )
    for rule in rules:
        writer.writerow(
            [
                rule.item_id,
                rule.title or "",
                rule.sku or "",
                rule.strategy,
                str(rule.min_price),
                str(rule.max_price),
                str(rule.active).lower(),
                rule.execution_state.last_outcome or "",
            ]
        )
    return output.getvalue()


def _report_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
