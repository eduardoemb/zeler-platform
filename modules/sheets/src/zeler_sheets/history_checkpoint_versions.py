"""Wire-BSON checkpoint versions and explicit, fenced question readmission only."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from bson import BSON
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from zeler_platform_core.history_onboarding import POLICY_VERSION, SOURCES
from zeler_platform_core.models import SheetsHistoryAcquisition
from zeler_platform_core.models.sheets_history_checkpoint import (
    SheetsHistoryCheckpointVersion,
    deterministic_version_id,
)
from zeler_sheets.history_acquisition import HistoryConflictError

VERSIONS = "sheets_history_checkpoint_versions"
RAW_CODEC = CodecOptions(document_class=RawBSONDocument, tz_aware=True, tzinfo=UTC)
UTC_CODEC: CodecOptions[dict[str, Any]] = CodecOptions(tz_aware=True, tzinfo=UTC)


def _integer(value: Any, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value < 2**63:
        raise HistoryConflictError("readmission integer unavailable")
    return int(value)


def _date(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HistoryConflictError("readmission UTC clock unavailable")
    return value.astimezone(UTC)


def _pin(raw: bytes, pin: Any) -> None:
    if (
        not isinstance(pin, str)
        or re.fullmatch("[a-f0-9]{64}", pin) is None
        or hashlib.sha256(raw).hexdigest() != pin
    ):
        raise HistoryConflictError("readmission wire BSON pin changed")


def _metadata(document: Any) -> dict[str, Any]:
    if not isinstance(document, RawBSONDocument):
        raise HistoryConflictError("readmission requires original wire BSON")
    return dict(BSON(document.raw).decode(codec_options=UTC_CODEC))


async def _raw(collection: Any, query: dict[str, Any], session: Any) -> RawBSONDocument:
    document = await collection.with_options(codec_options=RAW_CODEC).find_one(
        query, session=session
    )
    if not isinstance(document, RawBSONDocument):
        raise HistoryConflictError("readmission wire snapshot unavailable")
    return document


async def archive_question_checkpoint(
    db: Any,
    *,
    head: RawBSONDocument,
    job: RawBSONDocument,
    execution_id: str,
    expected_head_sha256: str,
    expected_job_sha256: str,
    now: datetime,
    session: Any,
) -> SheetsHistoryCheckpointVersion:
    """Insert only: same wire version is idempotent, conflicting bytes abort."""
    if session is None or not session.in_transaction:
        raise HistoryConflictError("checkpoint archive requires admission transaction")
    metadata, job_metadata = _metadata(head), _metadata(job)
    _pin(bytes(head.raw), expected_head_sha256)
    _pin(bytes(job.raw), expected_job_sha256)
    try:
        version = SheetsHistoryCheckpointVersion(
            _id=deterministic_version_id(
                metadata["_id"],
                metadata["generation"],
                metadata["pass_number"],
                metadata["checkpoint_revision"],
            ),
            acquisition_id=metadata["_id"],
            job_id=job_metadata["_id"],
            seller_id=metadata["seller_id"],
            execution_id=execution_id,
            generation=metadata["generation"],
            pass_number=metadata["pass_number"],
            checkpoint_revision=metadata["checkpoint_revision"],
            reason="expired_question_cursor",
            archived_at=_date(now),
            head_bson=bytes(head.raw),
            job_bson=bytes(job.raw),
            head_sha256=expected_head_sha256,
            job_sha256=expected_job_sha256,
        )
    except (ValueError, KeyError) as error:
        raise HistoryConflictError("checkpoint envelope invalid") from error
    collection = db[VERSIONS].with_options(codec_options=UTC_CODEC)
    existing = await collection.find_one({"_id": version.id}, session=session)
    if existing is not None:
        try:
            saved = SheetsHistoryCheckpointVersion.model_validate(existing)
        except ValueError as error:
            raise HistoryConflictError("checkpoint existing version invalid") from error
        # Timestamp belongs to the first insert and is never renewed on replay.
        if saved.model_dump(exclude={"archived_at"}) != version.model_dump(exclude={"archived_at"}):
            raise HistoryConflictError("checkpoint immutable version conflict")
        return saved
    try:
        await collection.insert_one(version.model_dump(by_alias=True), session=session)
    except DuplicateKeyError as error:
        raise HistoryConflictError("checkpoint concurrent version changed") from error
    return version


def _plan(plan: dict[str, Any], request: Any, execution_id: str, now: datetime) -> int:
    authority = plan.get("authority")
    if not isinstance(authority, dict):
        raise HistoryConflictError("readmission policy authority unavailable")
    if (
        plan.get("_id") != request.seller_id
        or plan.get("seller_id") != request.seller_id
        or plan.get("policy_version") != POLICY_VERSION
        or plan.get("state") != "paused"
        or plan.get("eligible") is not True
        or authority.get("kind") != "account_link_policy"
        or plan.get("sources") != list(SOURCES[:-1])
        or plan.get("execution_id") != execution_id
        or not isinstance(execution_id, str)
        or re.fullmatch("[a-f0-9]{32}", execution_id) is None
        or plan.get("execution_utc_day") != now.date().isoformat()
        or plan.get("incremental_day") != now.date().isoformat()
        or not now < _date(plan.get("execution_until"))
        or _date(plan["execution_until"]).date() != now.date()
        or plan.get("date_from") != request.date_from
        or plan.get("date_to") != request.date_to
        or plan.get("cutoff") != request.date_to
    ):
        raise HistoryConflictError("readmission plan authority unavailable")
    limit, consumed = (
        _integer(plan.get("execution_attempt_limit")),
        _integer(plan.get("execution_consumed")),
    )
    if limit > 2500 or not consumed < limit or _integer(plan.get("execution_sent")) > consumed:
        raise HistoryConflictError("readmission execution credit unavailable")
    total, used = _integer(plan.get("total_budget")), _integer(plan.get("total_consumed"))
    if total > 2000 or not used < total:
        raise HistoryConflictError("readmission initial credit unavailable")
    budgets = plan.get("budget")
    if not isinstance(budgets, dict) or set(budgets) != set(SOURCES):
        raise HistoryConflictError("readmission source credit unavailable")
    for source, ceiling in zip(SOURCES, (800, 150, 250, 300, 500, 0), strict=True):
        entry = budgets[source]
        if (
            not isinstance(entry, dict)
            or _integer(entry.get("physical_attempts")) > ceiling
            or _integer(entry.get("consumed")) > _integer(entry.get("physical_attempts"))
        ):
            raise HistoryConflictError("readmission source credit unavailable")
    if _integer(budgets["questions"]["consumed"]) >= _integer(
        budgets["questions"]["physical_attempts"]
    ):
        raise HistoryConflictError("readmission questions credit unavailable")
    policy = plan.get("incremental_policy")
    if (
        not isinstance(policy, dict)
        or _integer(policy.get("max_daily_total")) > 500
        or _integer(policy.get("max_daily_source")) > 300
    ):
        raise HistoryConflictError("readmission maintenance policy unavailable")
    revision = _integer(plan.get("history_readmission_revision", 0))
    if revision == 2**63 - 1:
        raise HistoryConflictError("readmission revision exhausted")
    return revision


async def readmit_question_cursor(
    queue: Any,
    request: Any,
    *,
    opt_in: bool = False,
    execution_id: str,
    expected_plan_bson_sha256: str,
    expected_head_sha256: str,
    expected_job_sha256: str,
) -> dict[str, Any]:
    """DB-only prospective pass; expired policy never creates pending work."""
    if (
        opt_in is not True
        or queue.enabled_models != frozenset({"questions"})
        or queue.allowed_sellers is None
        or request.seller_id not in queue.allowed_sellers
        or queue.policy_authority != POLICY_VERSION
    ):
        raise HistoryConflictError("question readmission not explicitly enabled")
    db = queue.collection.database

    async def transaction(session: Any) -> dict[str, Any]:
        now = _date(queue.now())  # Every driver retry must recheck actual authority time.
        plan_wire = await _raw(
            db["sheets_history_backfill_plans"], {"_id": request.seller_id}, session
        )
        _pin(bytes(plan_wire.raw), expected_plan_bson_sha256)
        plan = _metadata(plan_wire)
        revision = _plan(plan, request, execution_id, now)
        head_wire = await _raw(db["sheets_history_acquisitions"], {"_id": request.key}, session)
        job_wire = await _raw(queue.collection, {"_id": request.key}, session)
        _pin(bytes(head_wire.raw), expected_head_sha256)
        _pin(bytes(job_wire.raw), expected_job_sha256)
        head, job = _metadata(head_wire), _metadata(job_wire)
        request.validate_existing(job)
        if (
            job.get("policy_authority") != queue.policy_authority
            or _integer(job.get("attempts"), 1) >= 3
        ):
            raise HistoryConflictError("readmission job authority unavailable")
        if job.get("lease_until") is not None and _date(job["lease_until"]) > now:
            raise HistoryConflictError("readmission live lease")
        observed = _date(head.get("observed_until"))
        if observed > now or (now - observed).total_seconds() < 300:
            raise HistoryConflictError("readmission cursor not proven expired")
        if _integer(head.get("drift_restarts", 0)) >= 3:
            raise HistoryConflictError("readmission drift budget exhausted")
        # Serializes capacity with the existing canonical admission protocol.
        await queue.admission.update_one(
            {"_id": request.seller_id}, {"$inc": {"revision": 1}}, upsert=True, session=session
        )
        if (
            await queue.collection.count_documents(
                {"seller_id": request.seller_id, "state": {"$in": ["pending", "running"]}},
                limit=queue.max_active_jobs_per_seller,
                session=session,
            )
            >= queue.max_active_jobs_per_seller
        ):
            raise HistoryConflictError("readmission capacity exhausted")
        if (
            queue.reserved_inventory_slots
            and await queue.collection.count_documents(
                {
                    "seller_id": request.seller_id,
                    "state": {"$in": ["pending", "running"]},
                    "inventory_scope": {"$ne": True},
                },
                limit=queue.max_active_jobs_per_seller,
                session=session,
            )
            >= queue.max_active_jobs_per_seller - queue.reserved_inventory_slots
        ):
            raise HistoryConflictError("readmission reserved capacity exhausted")
        touched = await db["sheets_history_backfill_plans"].update_one(
            {
                "_id": request.seller_id,
                "state": "paused",
                "execution_id": execution_id,
                "history_readmission_revision": revision
                if "history_readmission_revision" in plan
                else {"$exists": False},
                "$expr": {"$eq": ["$$ROOT", {"$literal": plan}]},
            },
            {"$inc": {"history_readmission_revision": 1}},
            session=session,
        )
        if touched.matched_count != 1:
            raise HistoryConflictError("readmission whole plan changed")
        version = await archive_question_checkpoint(
            db,
            head=head_wire,
            job=job_wire,
            execution_id=execution_id,
            expected_head_sha256=expected_head_sha256,
            expected_job_sha256=expected_job_sha256,
            now=now,
            session=session,
        )
        patch = {
            "pass_number": _integer(head["pass_number"], 1) + 1,
            "checkpoint_revision": _integer(head["checkpoint_revision"]) + 1,
            "drift_restarts": _integer(head.get("drift_restarts", 0)) + 1,
            "phase": "discover",
            "next_cursor": None,
            "source_total": None,
            "discovered_count": 0,
            "fetched_count": 0,
            "published_count": 0,
            "publish_after": None,
            "active_range_id": None,
            "observed_from": None,
            "observed_until": None,
            "updated_at": now,
        }
        try:
            prospective = SheetsHistoryAcquisition.model_validate({**head, **patch})
        except ValueError as error:
            raise HistoryConflictError("readmission prospective head invalid") from error
        advanced = await db["sheets_history_acquisitions"].update_one(
            {"_id": request.key, "$expr": {"$eq": ["$$ROOT", {"$literal": head}]}},
            {"$set": patch},
            session=session,
        )
        binding = {
            "history_protocol_version": 1,
            "history_acquisition_id": prospective.id,
            "history_generation": prospective.generation,
            "history_pass_number": prospective.pass_number,
            "history_checkpoint_revision": prospective.checkpoint_revision,
        }
        pending = await queue.collection.update_one(
            {"_id": request.key, "$expr": {"$eq": ["$$ROOT", {"$literal": job}]}},
            {
                "$set": {
                    **binding,
                    "state": "pending",
                    "updated_at": now,
                    "available_at": max(now, _date(job.get("available_at"))),
                },
                "$unset": {"attempt_token": "", "lease_until": "", "failure_reason": ""},
            },
            session=session,
        )
        if advanced.matched_count != 1 or pending.matched_count != 1:
            raise HistoryConflictError("readmission whole checkpoint changed")
        return {
            "state": "pending",
            "version_id": version.id,
            "pass_number": prospective.pass_number,
            "plan_pin_format": "wire_bson_sha256",
        }

    async with await db.client.start_session() as session:
        return await asyncio.wait_for(
            session.with_transaction(
                transaction,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            ),
            timeout=30,
        )
