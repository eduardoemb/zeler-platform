from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zeler_platform_core.auth.jwt import ModuleClaims, verify_module_jwt
from zeler_platform_core.auth.module_admin import authorize_module_admin
from zeler_platform_core.models import RepricerRule
from zeler_repricer.service import (
    BulkJobNotFoundError,
    BulkValidationResult,
    CatalogRuleNotFoundError,
    CatalogRuleValidationError,
    ReportNotFoundError,
    RepricerBulkJobService,
    RepricerCatalogRuleService,
    RepricerGuardService,
    RepricerHistoryService,
    RepricerMonitoringService,
    RepricerReportService,
)


class RulePayload(BaseModel):
    id: str = Field(alias="_id")
    seller_id: str
    item_id: str
    strategy: str
    min_price: Decimal
    max_price: Decimal
    active: bool = True
    updated_at: datetime | None = None


class CatalogRuleCreatePayload(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    seller_id: str
    account_id: str
    item_id: str
    title: str | None = None
    sku: str | None = None
    strategy: str
    min_price: Decimal
    max_price: Decimal
    active: bool = True


class CatalogRulePatchPayload(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    seller_id: str
    account_id: str | None = None
    title: str | None = None
    sku: str | None = None
    strategy: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    active: bool | None = None


class CatalogRuleRefreshPayload(BaseModel):
    seller_id: str
    account_id: str | None = None


class LimitsPayload(BaseModel):
    enabled: bool = True
    min_price_limit: Decimal
    max_price_limit: Decimal
    undercut_delta: Decimal = Decimal("0")
    pause_competition: bool = False
    escalate_to_manual_review: bool = False


class AlliesPayload(BaseModel):
    allies: list[dict[str, Any]] = Field(default_factory=list)


class BulkValidatePayload(BaseModel):
    seller_id: str
    account_id: str
    source_filename: str
    content: str
    format: str = "csv"


class BulkProcessPayload(BaseModel):
    seller_id: str
    job_id: str


class RulesExportPayload(BaseModel):
    seller_id: str
    account_id: str
    format: str = "csv"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/repricer", tags=["repricer"])

    @router.get("/catalog/rules")
    async def list_catalog_rules(
        request: Request,
        seller_id: str,
        account_id: str | None = None,
        status: str | None = None,
        query: str | None = None,
    ) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerCatalogRuleService(request.app.state.mongo_db)
        try:
            rules = await service.list_catalog_rules(
                seller_id=seller_id,
                account_id=account_id,
                status=status,
                query=query,
            )
        except CatalogRuleValidationError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return JSONResponse([rule.model_dump(mode="json", by_alias=True) for rule in rules])

    @router.post("/catalog/rules", status_code=201)
    async def create_catalog_rule(
        request: Request, payload: CatalogRuleCreatePayload
    ) -> JSONResponse:
        claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "detail": "missing claims"},
            )
        service = RepricerCatalogRuleService(request.app.state.mongo_db)
        command = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        try:
            rule = await service.create_catalog_rule(
                seller_id=payload.seller_id,
                payload=command,
                operator_id=_operator_id(claims),
            )
        except CatalogRuleValidationError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return JSONResponse(status_code=201, content=rule.model_dump(mode="json", by_alias=True))

    @router.post("/catalog/rules/refresh")
    async def refresh_catalog_rules(
        request: Request, payload: CatalogRuleRefreshPayload
    ) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        service = RepricerCatalogRuleService(request.app.state.mongo_db)
        result = await service.refresh_catalog_rules(
            seller_id=payload.seller_id,
            account_id=payload.account_id,
        )
        return JSONResponse(result)

    @router.patch("/catalog/rules")
    async def patch_catalog_rule_collection(
        request: Request, payload: CatalogRulePatchPayload
    ) -> JSONResponse:
        if payload.id is None:
            return JSONResponse(status_code=422, content={"error": "catalog_rule_id_required"})
        return await _patch_catalog_rule(request, payload.id, payload)

    @router.patch("/catalog/rules/{rule_id}")
    async def patch_catalog_rule(
        request: Request, rule_id: str, payload: CatalogRulePatchPayload
    ) -> JSONResponse:
        return await _patch_catalog_rule(request, rule_id, payload)

    @router.get("/limits")
    async def get_limits(request: Request, seller_id: str, account_id: str) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerGuardService(request.app.state.mongo_db)
        limits = await service.get_limits(seller_id=seller_id, account_id=account_id)
        if limits is None:
            return JSONResponse(status_code=404, content={"error": "repricer_limits_not_found"})
        return JSONResponse(limits.model_dump(mode="json", by_alias=True))

    @router.put("/limits")
    async def put_limits(
        request: Request,
        seller_id: str,
        account_id: str,
        payload: LimitsPayload,
    ) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerGuardService(request.app.state.mongo_db)
        try:
            limits = await service.put_limits(
                seller_id=seller_id,
                account_id=account_id,
                payload=payload.model_dump(mode="json"),
            )
        except CatalogRuleValidationError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return JSONResponse(limits.model_dump(mode="json", by_alias=True))

    @router.get("/allies")
    async def get_allies(request: Request, seller_id: str) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerGuardService(request.app.state.mongo_db)
        allies = await service.get_allies(seller_id=seller_id)
        if allies is None:
            return JSONResponse(status_code=404, content={"error": "repricer_allies_not_found"})
        return JSONResponse(allies.model_dump(mode="json", by_alias=True))

    @router.put("/allies")
    async def put_allies(
        request: Request,
        seller_id: str,
        payload: AlliesPayload,
    ) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerGuardService(request.app.state.mongo_db)
        allies = await service.put_allies(
            seller_id=seller_id,
            payload=payload.model_dump(mode="json"),
        )
        return JSONResponse(allies.model_dump(mode="json", by_alias=True))

    @router.post("/bulk-jobs/validate", status_code=201)
    async def validate_bulk_job(
        request: Request, payload: BulkValidatePayload
    ) -> JSONResponse:
        claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "detail": "missing claims", "retryable": False},
            )
        if payload.format != "csv":
            return JSONResponse(
                status_code=422,
                content={"error": "unsupported_bulk_format", "retryable": False},
            )
        service = RepricerBulkJobService(request.app.state.mongo_db)
        result = await service.validate_upload(
            seller_id=payload.seller_id,
            account_id=payload.account_id,
            source_filename=payload.source_filename,
            content=payload.content,
            operator_id=_operator_id(claims),
        )
        return JSONResponse(status_code=201, content=_bulk_result_payload(result))

    @router.post("/bulk-jobs")
    async def process_bulk_job(request: Request, payload: BulkProcessPayload) -> JSONResponse:
        claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "detail": "missing claims", "retryable": False},
            )
        service = RepricerBulkJobService(request.app.state.mongo_db)
        try:
            job = await service.process_job(
                seller_id=payload.seller_id,
                job_id=payload.job_id,
                operator_id=_operator_id(claims),
            )
        except BulkJobNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": "bulk_job_not_found", "retryable": True},
            )
        return JSONResponse(_job_payload(job))

    @router.get("/bulk-jobs/{job_id}")
    async def get_bulk_job(request: Request, job_id: str, seller_id: str) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerBulkJobService(request.app.state.mongo_db)
        try:
            job = await service.get_job(seller_id=seller_id, job_id=job_id)
        except BulkJobNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": "bulk_job_not_found", "retryable": True},
            )
        rows = await service.list_rows(seller_id=seller_id, job_id=job_id)
        return JSONResponse({"job": _job_payload(job), "rows": [_row_payload(row) for row in rows]})

    @router.get("/bulk-jobs/{job_id}/errors")
    async def get_bulk_job_errors(request: Request, job_id: str, seller_id: str) -> JSONResponse:
        _claims, auth = _claims_or_error(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerBulkJobService(request.app.state.mongo_db)
        try:
            await service.get_job(seller_id=seller_id, job_id=job_id)
        except BulkJobNotFoundError:
            return JSONResponse(
                status_code=404,
                content={"error": "bulk_job_not_found", "retryable": True},
            )
        rows = await service.list_rows(seller_id=seller_id, job_id=job_id, status="failed")
        return JSONResponse({"rows": [_row_payload(row) for row in rows]})

    async def _patch_catalog_rule(
        request: Request, rule_id: str, payload: CatalogRulePatchPayload
    ) -> JSONResponse:
        claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "detail": "missing claims"},
            )
        service = RepricerCatalogRuleService(request.app.state.mongo_db)
        try:
            rule = await service.patch_catalog_rule(
                seller_id=payload.seller_id,
                rule_id=rule_id,
                patch=payload.model_dump(mode="json", by_alias=True, exclude_none=True),
                operator_id=_operator_id(claims),
            )
        except CatalogRuleNotFoundError:
            return JSONResponse(status_code=404, content={"error": "catalog_rule_not_found"})
        except CatalogRuleValidationError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc)})
        return JSONResponse(rule.model_dump(mode="json", by_alias=True))

    @router.get("/rules")
    async def list_rules(request: Request, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        docs = await (
            request.app.state.mongo_db["repricer_rules"]
            .find({"seller_id": seller_id})
            .to_list(length=100)
        )
        return JSONResponse(docs)

    @router.get("/history")
    async def list_history(
        request: Request,
        seller_id: str,
        account_id: str | None = None,
        item_id: str | None = None,
        outcome: str | None = None,
        status: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        job_id: str | None = None,
        report_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerHistoryService(request.app.state.mongo_db)
        docs = await service.list_history(
            seller_id=seller_id,
            account_id=account_id,
            item_id=item_id,
            outcome=outcome,
            status=status,
            from_date=from_date,
            to_date=to_date,
            job_id=job_id,
            report_id=report_id,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(docs)

    @router.get("/reports")
    async def list_reports(
        request: Request,
        seller_id: str,
        account_id: str | None = None,
        status: str | None = None,
        report_type: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerReportService(request.app.state.mongo_db)
        reports = await service.list_reports(
            seller_id=seller_id,
            account_id=account_id,
            status=status,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        return JSONResponse([report.model_dump(mode="json", by_alias=True) for report in reports])

    @router.post("/reports/rules-export", status_code=201)
    async def create_rules_export(
        request: Request, payload: RulesExportPayload
    ) -> JSONResponse:
        claims, auth = _claims_or_error(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if claims is None:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "detail": "missing claims", "retryable": False},
            )
        service = RepricerReportService(request.app.state.mongo_db)
        try:
            report = await service.create_rules_export(
                seller_id=payload.seller_id,
                account_id=payload.account_id,
                requested_by=_operator_id(claims),
                format=payload.format,
            )
        except CatalogRuleValidationError as exc:
            return JSONResponse(status_code=422, content={"error": str(exc), "retryable": False})
        return JSONResponse(status_code=201, content=report.model_dump(mode="json", by_alias=True))

    @router.get("/reports/{report_id}/download")
    async def download_report(request: Request, report_id: str, seller_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerReportService(request.app.state.mongo_db)
        try:
            download = await service.get_download(seller_id=seller_id, report_id=report_id)
        except ReportNotFoundError:
            return JSONResponse(status_code=404, content={"error": "report_not_found"})
        return JSONResponse(download)

    @router.get("/monitoring")
    async def get_monitoring(request: Request, seller_id: str, account_id: str) -> JSONResponse:
        auth = _authorize(request, seller_id=seller_id)
        if auth is not None:
            return auth
        service = RepricerMonitoringService(request.app.state.mongo_db)
        status = await service.get_status(seller_id=seller_id, account_id=account_id)
        return JSONResponse(status)

    @router.post("/rules", status_code=201)
    async def create_rule(request: Request, payload: RulePayload) -> JSONResponse:
        auth = _authorize(request, seller_id=payload.seller_id)
        if auth is not None:
            return auth
        if payload.min_price > payload.max_price:
            return JSONResponse(status_code=422, content={"error": "min_price_above_max_price"})
        now = payload.updated_at or datetime.now(UTC)
        rule = RepricerRule(
            _id=payload.id,
            seller_id=payload.seller_id,
            item_id=payload.item_id,
            strategy=payload.strategy,  # type: ignore[arg-type]
            min_price=payload.min_price,
            max_price=payload.max_price,
            active=payload.active,
            updated_at=now,
        )
        doc = rule.model_dump(mode="json", by_alias=True)
        await request.app.state.mongo_db["repricer_rules"].insert_one(doc)
        return JSONResponse(status_code=201, content=doc)

    @router.patch("/rules/{rule_id}")
    async def update_rule(request: Request, rule_id: str, patch: dict[str, Any]) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        patch["updated_at"] = datetime.now(UTC)
        await request.app.state.mongo_db["repricer_rules"].update_one(
            {"_id": rule_id}, {"$set": patch}
        )
        return JSONResponse({"status": "updated"})

    @router.delete("/rules/{rule_id}")
    async def delete_rule(request: Request, rule_id: str) -> JSONResponse:
        auth = _authorize(request)
        if auth is not None:
            return auth
        await request.app.state.mongo_db["repricer_rules"].update_one(
            {"_id": rule_id}, {"$set": {"active": False, "updated_at": datetime.now(UTC)}}
        )
        return JSONResponse({"status": "deleted"})

    return router


def _authorize(request: Request, seller_id: str | int | None = None) -> JSONResponse | None:
    return authorize_module_admin(
        request,
        expected_module_id="repricer",
        seller_id=seller_id,
        verifier=verify_module_jwt,
    )


def _claims_or_error(
    request: Request, seller_id: str | int | None = None
) -> tuple[ModuleClaims | None, JSONResponse | None]:
    claims: ModuleClaims | None = None

    def verifier(token: str) -> ModuleClaims:
        nonlocal claims
        claims = verify_module_jwt(token)
        return claims

    auth = authorize_module_admin(
        request,
        expected_module_id="repricer",
        seller_id=seller_id,
        verifier=verifier,
    )
    if auth is not None:
        return None, auth
    return claims, None


def _operator_id(claims: ModuleClaims) -> str:
    return claims.issued_by or f"module:{claims.module_id}"


def _bulk_result_payload(result: BulkValidationResult) -> dict[str, Any]:
    return {"job": _job_payload(result.job), "rows": [_row_payload(row) for row in result.rows]}


def _job_payload(job: Any) -> dict[str, Any]:
    return cast(dict[str, Any], job.model_dump(mode="json", by_alias=True))


def _row_payload(row: Any) -> dict[str, Any]:
    payload = cast(dict[str, Any], row.model_dump(mode="json", by_alias=True))
    payload["error"] = None
    if row.error_code is not None:
        payload["error"] = {
            "code": row.error_code,
            "message": row.error_message,
            "retryable": False,
        }
    return payload
