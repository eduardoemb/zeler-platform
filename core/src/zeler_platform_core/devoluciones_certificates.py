"""Independent acquisition-backed DEVOLUCIONES read certificates.

Acquisition evidence is immutable; renewable current proof is a separate contract.
This module never acquires source data and never infers coverage from row counts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

CERTIFICATES = "sheets_devoluciones_certificates"
KINDS = frozenset({"quota_run", "joint_snapshot", "legacy_joint_snapshot"})
VALIDITY = timedelta(minutes=30)


class CoverageUnavailableError(ValueError):
    """Safe, payload-free failure to prove a complete readable interval."""


def utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise CoverageUnavailableError("invalid certificate time")
    # Mongo's default codec returns naive BSON UTC, unlike public API dates.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def certificate_identity(seller_id: str, kind: str, source_identity: str) -> str:
    if kind not in KINDS or not seller_id or not source_identity:
        raise CoverageUnavailableError("invalid certificate identity")
    return hashlib.sha256(json.dumps([seller_id, kind, source_identity]).encode()).hexdigest()


def make_certificate(
    *,
    seller_id: str,
    kind: str,
    source_identity: str,
    source_fingerprint: str | None,
    acquisition_fingerprint: str,
    date_from: datetime,
    date_to: datetime,
    acquired_at: datetime,
    expected_count: int,
    current_membership_hash: str,
    current_read_model_fingerprint: str,
    coverage_epoch: int,
    now: datetime,
) -> dict[str, Any]:
    now, date_from, date_to, acquired_at = map(utc, (now, date_from, date_to, acquired_at))
    if not date_from < date_to <= acquired_at <= now:
        raise CoverageUnavailableError("invalid acquired certificate bounds")
    if (
        not acquisition_fingerprint
        or not current_membership_hash
        or not current_read_model_fingerprint
        or expected_count < 0
        or coverage_epoch < 0
        or (kind != "legacy_joint_snapshot" and not source_fingerprint)
    ):
        raise CoverageUnavailableError("incomplete certificate evidence")
    return {
        "_id": certificate_identity(seller_id, kind, source_identity),
        "seller_id": seller_id,
        "kind": kind,
        "source_identity": source_identity,
        "source_fingerprint": source_fingerprint,
        "acquisition_fingerprint": acquisition_fingerprint,
        "date_from": date_from,
        "date_to": date_to,
        "acquired_at": acquired_at,
        "expected_count": expected_count,
        "state": "reconciled",
        "revision": 1,
        "current_membership_hash": current_membership_hash,
        "current_read_model_fingerprint": current_read_model_fingerprint,
        "certified_count": expected_count,
        "validated_at": now,
        "valid_until": now + VALIDITY,
        "next_check_at": now,
        "invalidation_reason": None,
        "needs_reacquisition": False,
        "coverage_epoch": coverage_epoch,
        "schema_version": 1,
    }


def select_coverage(
    certificates: Iterable[Mapping[str, Any]],
    seller_id: str,
    start: datetime,
    end: datetime,
    now: datetime,
) -> tuple[Mapping[str, Any], ...]:
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or end.tzinfo is None
        or not start < end
    ):
        raise CoverageUnavailableError("invalid requested bounds")
    candidates = []
    for certificate in certificates:
        try:
            validate_certificate(certificate, now=now)
            eligible = (
                certificate.get("seller_id") == seller_id
                and certificate.get("state") == "reconciled"
                and certificate.get("needs_reacquisition") is False
                and utc(certificate["valid_until"]) > utc(now)
                and utc(certificate["date_from"])
                < utc(certificate["date_to"])
                <= utc(certificate["acquired_at"])
                and certificate["_id"]
                == certificate_identity(
                    seller_id, str(certificate["kind"]), str(certificate["source_identity"])
                )
                and bool(certificate.get("current_membership_hash"))
                and bool(certificate.get("current_read_model_fingerprint"))
            )
        except (KeyError, ValueError, TypeError):
            eligible = False
        if eligible:
            candidates.append(certificate)
    cursor = start
    selected: list[Mapping[str, Any]] = []
    while cursor < end:
        covering = [c for c in candidates if utc(c["date_from"]) <= cursor < utc(c["date_to"])]
        if not covering:
            raise CoverageUnavailableError("requested interval is not certified")
        choice = min(covering, key=lambda c: (-utc(c["date_to"]).timestamp(), str(c["_id"])))
        selected.append(choice)
        cursor = utc(choice["date_to"])
    return tuple(selected)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def membership_hash(ids: Iterable[str]) -> str:
    return digest(sorted(set(ids)))


def quota_provenance(
    run: Mapping[str, Any], windows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Verify immutable binding and every completed window, never merely a count."""
    from zeler_platform_core.devoluciones_runs import RunBinding, partition_windows

    try:
        binding = RunBinding(
            run["authorization_id"],
            run["cohort_id"],
            run["seller_id"],
            run["scope"],
            utc(run["start"]),
            utc(run["end"]),
            run["partition_version"],
            run["release_fingerprints"],
        )
        rows = sorted(windows, key=lambda row: row["index"])
        expected = partition_windows(binding)
        if (
            run["_id"] != binding.run_id
            or run["state"] != "completed"
            or binding.scope != "devoluciones"
            or len(rows) != len(expected)
            or run["window_count"] != len(expected)
        ):
            raise CoverageUnavailableError("invalid quota acquisition binding")
        immutable = []
        for row, window in zip(rows, expected, strict=True):
            if (
                row["run_id"] != binding.run_id
                or row["index"] != window.index
                or utc(row["start"]) != window.start
                or utc(row["end"]) != window.end
                or row["state"] != "completed"
                or not row["source_fingerprint"]
                or not row["read_model_fingerprint"]
                or row["missing_count"] != 0
                or not row["expected_count"] == row["persisted_count"] == row["complete_count"]
                or not isinstance(row["expected_count"], int)
                or row["expected_count"] < 0
            ):
                raise CoverageUnavailableError("incomplete quota acquisition window")
            immutable.append(
                {
                    "index": window.index,
                    "start": window.start,
                    "end": window.end,
                    "expected_count": row["expected_count"],
                    "source_fingerprint": row["source_fingerprint"],
                    "read_model_fingerprint": row["read_model_fingerprint"],
                }
            )
        return {
            "expected_count": sum(row["expected_count"] for row in rows),
            "source_fingerprint": digest([row["source_fingerprint"] for row in rows]),
            "acquisition_fingerprint": digest({"run_id": binding.run_id, "windows": immutable}),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CoverageUnavailableError("invalid quota acquisition evidence") from exc


def validate_certificate(document: Mapping[str, Any], *, now: datetime) -> None:
    from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS

    schema = ENTITY_SCHEMAS[CERTIFICATES]
    if set(document) != set(schema["required"]):
        raise CoverageUnavailableError("invalid certificate fields")
    for field, definition in schema["properties"].items():
        value = document[field]
        if "enum" in definition and value not in definition["enum"]:
            raise CoverageUnavailableError("invalid certificate enum")
        types = definition.get("bsonType", [])
        types = [types] if isinstance(types, str) else types
        if types:
            matches = (
                ("string" in types and isinstance(value, str))
                or ("null" in types and value is None)
                or ("bool" in types and isinstance(value, bool))
                or ("date" in types and isinstance(value, datetime))
                or (("int" in types or "long" in types) and type(value) is int)
            )
            if not matches:
                raise CoverageUnavailableError("invalid certificate type")
        if "minimum" in definition and value < definition["minimum"]:
            raise CoverageUnavailableError("invalid certificate counter")
        if "minLength" in definition and len(value.strip()) < definition["minLength"]:
            raise CoverageUnavailableError("invalid certificate identity")
    if (
        document["_id"]
        != certificate_identity(
            document["seller_id"], document["kind"], document["source_identity"]
        )
        or not utc(document["date_from"])
        < utc(document["date_to"])
        <= utc(document["acquired_at"])
        <= utc(now)
        or not utc(document["acquired_at"]) <= utc(document["validated_at"]) <= utc(now)
        or utc(document["valid_until"]) > utc(document["validated_at"]) + VALIDITY
        or (
            document["kind"] == "legacy_joint_snapshot"
            and document["source_fingerprint"] is not None
        )
        or (document["kind"] != "legacy_joint_snapshot" and not document["source_fingerprint"])
    ):
        raise CoverageUnavailableError("inconsistent certificate evidence")


async def coverage_control(db: Any, seller_id: str, *, session: Any = None) -> Mapping[str, Any]:
    return (
        await db["sheets_devoluciones_operations"].find_one(
            {"seller_id": seller_id, "scope": "devoluciones"},
            **({"session": session} if session is not None else {}),
        )
        or {}
    )


def require_compatible(control: Mapping[str, Any]) -> None:
    if (
        control.get("coverage_mode") != "active"
        or control.get("coverage_ack_fence") != control.get("fence")
        or type(control.get("coverage_epoch")) is not int
    ):
        raise CoverageUnavailableError("certificate writer compatibility unavailable")


async def validate_provenance(db: Any, document: Mapping[str, Any], *, session: Any = None) -> None:
    if document["kind"] != "quota_run":
        return
    run = await db["sheets_devoluciones_runs"].find_one(
        {"_id": document["source_identity"], "seller_id": document["seller_id"]}, session=session
    )
    windows = [
        row
        async for row in db["sheets_devoluciones_run_windows"].find(
            {"run_id": document["source_identity"]}, session=session
        )
    ]
    evidence = quota_provenance(run or {}, windows)
    if (
        any(document[key] != evidence[key] for key in evidence)
        or utc(document["date_from"]) != utc(run["start"])
        or utc(document["date_to"]) != utc(run["end"])
    ):
        raise CoverageUnavailableError("certificate acquisition provenance changed")


async def publish_certificate(
    db: Any, operation: Any, document: Mapping[str, Any], *, session: Any
) -> None:
    """Called only after exact source/joint readback, in the owner's transaction."""
    from zeler_platform_core.devoluciones_readiness import (
        DevolucionesLeaseLostError,
        operation_lease_guard,
    )

    if session is None or not session.in_transaction:
        raise CoverageUnavailableError("certificate publication requires transaction")
    if operation.seller_id != document["seller_id"]:
        raise CoverageUnavailableError("certificate seller mismatch")
    control = await db["sheets_devoluciones_operations"].find_one(
        operation_lease_guard(operation), session=session
    )
    if not control or control.get("coverage_ack_fence") != operation.fence:
        raise DevolucionesLeaseLostError("certificate publication lost compatible owner")
    validate_certificate(document, now=datetime.now(UTC))
    if document["coverage_epoch"] != control.get("coverage_epoch", 0):
        raise CoverageUnavailableError("certificate epoch changed")
    await validate_provenance(db, document, session=session)
    existing = await db[CERTIFICATES].find_one({"_id": document["_id"]}, session=session)
    immutable = (
        "seller_id",
        "kind",
        "date_from",
        "date_to",
        "source_identity",
        "source_fingerprint",
        "acquisition_fingerprint",
        "expected_count",
    )
    if existing:
        for key in immutable:
            left, right = existing[key], document[key]
            if isinstance(left, datetime):
                left, right = utc(left), utc(right)
            if left != right:
                raise CoverageUnavailableError("conflicting certificate source identity")
        return
    await db[CERTIFICATES].insert_one(dict(document), session=session)


@dataclass(frozen=True)
class ProofVector:
    seller_id: str
    start: datetime
    end: datetime
    epoch: int
    fence: int
    proofs: tuple[Mapping[str, Any], ...]


async def select_covering_proofs(
    db: Any, seller_id: str, start: datetime, end: datetime, now: datetime, *, session: Any = None
) -> ProofVector:
    control = await coverage_control(db, seller_id, session=session)
    require_compatible(control)
    documents = [
        row
        async for row in db[CERTIFICATES]
        .find(
            {
                "seller_id": seller_id,
                "state": "reconciled",
                "date_from": {"$lt": end},
                "date_to": {"$gt": start},
                "coverage_epoch": control["coverage_epoch"],
                "valid_until": {"$gt": now},
            },
            session=session,
        )
        .max_time_ms(5000)
    ]
    selected = select_coverage(documents, seller_id, start, end, now)
    for document in selected:
        await validate_provenance(db, document, session=session)
    return ProofVector(seller_id, start, end, control["coverage_epoch"], control["fence"], selected)


async def validate_proof_vector(db: Any, vector: ProofVector, now: datetime) -> None:
    import asyncio

    from pymongo.read_concern import ReadConcern

    # One final linearization point: never mix independently read proof revisions.
    async with asyncio.timeout(5), await db.client.start_session() as session:  # noqa: SIM117
        async with session.start_transaction(read_concern=ReadConcern("snapshot")):
            await _validate_proof_vector(db, vector, now, session=session)


async def _validate_proof_vector(
    db: Any, vector: ProofVector, now: datetime, *, session: Any
) -> None:
    control = await coverage_control(db, vector.seller_id, session=session)
    require_compatible(control)
    if control["coverage_epoch"] != vector.epoch or control["fence"] != vector.fence:
        raise CoverageUnavailableError("certificate ownership changed during read")
    keys = (
        "_id",
        "seller_id",
        "date_from",
        "date_to",
        "revision",
        "coverage_epoch",
        "current_membership_hash",
        "current_read_model_fingerprint",
        "acquisition_fingerprint",
        "kind",
        "source_identity",
        "source_fingerprint",
        "expected_count",
        "certified_count",
        "acquired_at",
    )
    for proof in vector.proofs:
        current = await db[CERTIFICATES].find_one(
            {"_id": proof["_id"], "seller_id": vector.seller_id}, session=session
        )
        if not current:
            raise CoverageUnavailableError("certificate removed during read")
        select_coverage(
            [current], vector.seller_id, utc(proof["date_from"]), utc(proof["date_to"]), now
        )
        if any(current[key] != proof[key] for key in keys):
            raise CoverageUnavailableError("certificate changed during read")
        await validate_provenance(db, current, session=session)


async def invalidate_claim_impact(
    db: Any,
    seller_id: str,
    claims: Iterable[Mapping[str, Any] | None],
    *,
    session: Any,
    reason: str = "claim_mutation",
) -> None:
    dates = []
    unknown = False
    for claim in claims:
        if claim is None:
            continue
        if str(claim.get("seller_id")) != seller_id or "type" not in claim:
            unknown = True
        elif claim.get("type") == "returns":
            if not isinstance(claim.get("date_created"), datetime):
                unknown = True
            else:
                dates.append(utc(claim["date_created"]))
    query: dict[str, Any] = {"seller_id": seller_id}
    if not unknown:
        if not dates:
            return
        query["$or"] = [{"date_from": {"$lte": date}, "date_to": {"$gt": date}} for date in dates]
    marker_query: dict[str, Any] = {"_id": f"{seller_id}:devoluciones", "seller_id": seller_id}
    if not unknown:
        marker_query["$or"] = [
            {"date_from": {"$lte": date}, "reconciled_until": {"$gt": date}} for date in dates
        ]
    await db["sheets_read_model_freshness"].update_one(
        marker_query, {"$set": {"state": "stale"}}, session=session
    )
    await db[CERTIFICATES].update_many(
        query,
        {
            "$set": {
                "state": "stale",
                "needs_reacquisition": True,
                "invalidation_reason": "unknown_impact" if unknown else reason,
            },
            "$inc": {"revision": 1},
        },
        session=session,
    )


async def invalidate_all_certificates(
    db: Any, seller_id: str, *, session: Any, reason: str = "unknown_impact"
) -> None:
    await db[CERTIFICATES].update_many(
        {"seller_id": seller_id},
        {
            "$set": {"state": "stale", "needs_reacquisition": True, "invalidation_reason": reason},
            "$inc": {"revision": 1},
        },
        session=session,
    )


def renewal_capacity(eligible_count: int, measurement: Mapping[str, Any] | None) -> dict[str, Any]:
    import math

    unknown = {"status": "unknown", "sustainable_batch": None, "revisit_seconds": None}
    if not measurement:
        return unknown
    slowest = measurement.get("slowest_seconds")
    interval = measurement.get("observed_interval_seconds")
    if (
        not isinstance(slowest, (int, float))
        or not math.isfinite(slowest)
        or slowest <= 0
        or not isinstance(interval, (int, float))
        or not math.isfinite(interval)
        or interval < 900
    ):
        return unknown
    sustainable = min(20, max(1, int(30 / slowest)))
    revisit = math.ceil(eligible_count / sustainable) * interval + 30 + 60
    return {
        "status": "sufficient" if revisit < 1800 else "degraded",
        "sustainable_batch": sustainable,
        "revisit_seconds": float(revisit),
    }


async def certificate_status(db: Any, seller_id: str, now: datetime) -> dict[str, Any]:
    """Sanitized interval truth, never the min/max envelope of disjoint proofs."""
    control = await coverage_control(db, seller_id)
    compatible = control.get("coverage_mode") == "active" and control.get(
        "coverage_ack_fence"
    ) == control.get("fence")
    intervals = []
    due = expired = invalid = 0
    async for document in (
        db[CERTIFICATES]
        .find({"seller_id": seller_id})
        .sort([("date_from", 1), ("_id", 1)])
        .max_time_ms(5000)
    ):
        try:
            validate_certificate(document, now=now)
        except (ValueError, TypeError):
            invalid += 1
            continue
        due += int(utc(document["next_check_at"]) <= now)
        expired += int(utc(document["valid_until"]) <= now)
        readable = (
            compatible
            and document["coverage_epoch"] == control.get("coverage_epoch")
            and document["state"] == "reconciled"
            and not document["needs_reacquisition"]
            and utc(document["valid_until"]) > now
        )
        intervals.append(
            {
                "date_from": utc(document["date_from"]).isoformat(),
                "date_to": utc(document["date_to"]).isoformat(),
                "state": document["state"],
                "valid_until": utc(document["valid_until"]).isoformat(),
                "needs_reacquisition": document["needs_reacquisition"],
                "readable": readable,
                "kind": document["kind"],
            }
        )
    gaps = []
    end = None
    for interval in intervals:
        if end is not None and interval["date_from"] > end:
            gaps.append({"date_from": end, "date_to": interval["date_from"]})
        end = max(end or interval["date_to"], interval["date_to"])
    return {
        "mode": control.get("coverage_mode", "legacy"),
        "compatible": compatible,
        "intervals": intervals,
        "unacquired_gaps": gaps,
        "expired": expired,
        "invalid": invalid,
        "due": due,
        "capacity": renewal_capacity(len(intervals), control.get("coverage_renewal")),
    }
