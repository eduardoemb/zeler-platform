"""Read-only wire checkpoint preflight. Default NOOP; not recovery authority."""

from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, NoReturn

from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument

from zeler_platform_core.models.sheets_history_checkpoint import (
    SheetsHistoryCheckpointVersion,
    deterministic_version_id,
)

SELLER = "82453304"
CAPS = dict(
    zip(
        ("orders", "questions", "shipments", "messages", "claims_returns"),
        (800, 150, 250, 300, 500),
        strict=True,
    )
)
RAW_CODEC = CodecOptions(document_class=RawBSONDocument, tz_aware=True, tzinfo=UTC)


class CursorControlError(RuntimeError):
    """Closed codes only; never include BSON, private fields or driver errors."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CursorControlError("invalid_arguments")


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**63:
        raise CursorControlError("invalid_counter")
    return int(value)


def _date(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise CursorControlError("invalid_bson_date")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _find(db: Any, collection: str, identity: str) -> RawBSONDocument:
    value = (
        await db[collection]
        .with_options(codec_options=RAW_CODEC)
        .find_one({"_id": identity}, max_time_ms=4000)
    )
    if not isinstance(value, RawBSONDocument):
        raise CursorControlError("wire_document_required")
    return value


async def inspect_question_cursor(db: Any, *, execution_id: str, now: datetime) -> dict[str, Any]:
    """PRIMARY plus three exact documents; pins do not approve a mutation or send."""
    if not isinstance(execution_id, str) or re.fullmatch(r"[0-9a-f]{32}", execution_id) is None:
        raise CursorControlError("execution_identity_invalid")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CursorControlError("aware_clock_required")
    now = now.astimezone(UTC)
    hello = await db.client.admin.command("hello", maxTimeMS=4000)
    if hello.get("isWritablePrimary") is not True:
        raise CursorControlError("primary_required")
    plan = await _find(db, "sheets_history_backfill_plans", SELLER)
    if (
        len(plan.raw) > 2 * 1024 * 1024
        or plan.get("seller_id") != SELLER
        or plan.get("policy_version") != "history-on-link-v1"
        or plan.get("state") != "paused"
        or plan.get("eligible") is not True
        or plan.get("execution_id") != execution_id
        or not isinstance(plan.get("authority"), Mapping)
        or plan["authority"].get("kind") != "account_link_policy"
    ):
        raise CursorControlError("paused_plan_identity_required")
    start, end = _date(plan.get("date_from")), _date(plan.get("cutoff"))
    if (
        end.year <= 1
        or start
        != end.replace(
            year=end.year - 1, day=min(end.day, calendar.monthrange(end.year - 1, end.month)[1])
        )
        or _date(plan.get("date_to")) != end
    ):
        raise CursorControlError("original_calendar_bounds_required")
    budget = plan.get("budget")
    if not isinstance(budget, Mapping):
        raise CursorControlError("original_budget_required")
    if plan.get("sources") != list(CAPS):
        raise CursorControlError("original_source_scope_required")
    for source, cap in {**CAPS, "full_withdrawals": 0}.items():
        slot = budget.get(source)
        if not isinstance(slot, Mapping):
            raise CursorControlError("original_budget_required")
        limit, used = _integer(slot.get("physical_attempts")), _integer(slot.get("consumed"))
        if limit > cap or used > limit:
            raise CursorControlError("budget_or_full_exclusion_invalid")
    charged, sent = _integer(plan.get("execution_consumed")), _integer(plan.get("execution_sent"))
    execution_limit = _integer(plan.get("execution_attempt_limit"))
    initial_limit, initial_used = (
        _integer(plan.get("total_budget")),
        _integer(plan.get("total_consumed")),
    )
    maintenance = _integer(plan.get("incremental_consumed"))
    policy = plan.get("incremental_policy")
    if not isinstance(policy, Mapping):
        raise CursorControlError("maintenance_policy_required")
    daily_limit, source_limit = (
        _integer(policy.get("max_daily_total")),
        _integer(policy.get("max_daily_source")),
    )
    if (
        sent > charged
        or charged > execution_limit
        or execution_limit > 2500
        or initial_limit > 2000
        or initial_used > initial_limit
        or daily_limit > 500
        or source_limit > 300
        or maintenance > daily_limit
    ):
        raise CursorControlError("counter_or_policy_invalid")
    daily = plan.get("incremental_source_consumed")
    if not isinstance(daily, Mapping) or set(daily) != {*CAPS, "full_withdrawals"}:
        raise CursorControlError("maintenance_source_counters_required")
    source_consumed = {source: _integer(daily[source]) for source in daily}
    if (
        any(used > source_limit for used in source_consumed.values())
        or source_consumed["full_withdrawals"] != 0
        or sum(source_consumed.values()) != maintenance
        or sum(_integer(slot["consumed"]) for slot in budget.values()) != initial_used
        or initial_used + maintenance != charged
    ):
        raise CursorControlError("counter_or_policy_invalid")
    plan_id = "pilot-12m:" + end.isoformat(timespec="milliseconds")
    identity = hashlib.sha256(
        "\0".join((SELLER, "questions", "seller_scan", plan_id)).encode()
    ).hexdigest()
    head = await _find(db, "sheets_history_acquisitions", identity)
    job = await _find(db, "sheets_formula_recovery_jobs", identity)
    hashes = {
        "plan_bson_sha256": hashlib.sha256(plan.raw).hexdigest(),
        "head_bson_sha256": hashlib.sha256(head.raw).hexdigest(),
        "job_bson_sha256": hashlib.sha256(job.raw).hexdigest(),
    }
    try:
        version = SheetsHistoryCheckpointVersion(
            _id=deterministic_version_id(
                identity, head["generation"], head["pass_number"], head["checkpoint_revision"]
            ),
            acquisition_id=identity,
            job_id=identity,
            seller_id=SELLER,
            execution_id=execution_id,
            generation=head["generation"],
            pass_number=head["pass_number"],
            checkpoint_revision=head["checkpoint_revision"],
            reason="expired_question_cursor",
            archived_at=now,
            head_bson=bytes(head.raw),
            job_bson=bytes(job.raw),
            head_sha256=hashes["head_bson_sha256"],
            job_sha256=hashes["job_bson_sha256"],
        )
    except (ValueError, KeyError):
        raise CursorControlError("checkpoint_integrity_invalid") from None
    blockers = []
    if now >= _date(plan.get("execution_until")):
        blockers.append("execution_window_expired")
    if plan.get("execution_utc_day") != now.date().isoformat():
        blockers.append("execution_day_changed")
    if plan.get("incremental_day") != now.date().isoformat():
        blockers.append("maintenance_day_changed")
    remaining = _integer(budget["questions"]["physical_attempts"]) - _integer(
        budget["questions"]["consumed"]
    )
    if (
        min(
            remaining,
            execution_limit - charged,
            initial_limit - initial_used,
            daily_limit - maintenance,
        )
        <= 0
    ):
        blockers.append("quota_exhausted")
    observed = head.get("observed_until")
    age = None
    if not isinstance(observed, datetime) or _date(observed) > now:
        blockers.append("cursor_clock_invalid")
    else:
        age = int((now - _date(observed)).total_seconds())
        if age < 300:
            blockers.append("cursor_not_expired")
    lease = job.get("lease_until")
    if isinstance(lease, datetime) and _date(lease) > now:
        blockers.append("job_lease_live")
    return {
        "operation": "question_cursor_inspect",
        "action": "inspect",
        "read_only": True,
        "applied": False,
        "transport_authorized": False,
        "primary": True,
        "reads": 4,
        "hash_format": "wire_raw_bson_sha256",
        **hashes,
        "candidate_version_id": version.id,
        "charged": charged,
        "sent": sent,
        "maintenance": maintenance,
        "questions_remaining": remaining,
        "cursor_age_seconds": age,
        "readmission_preconditions_met": not blockers,
        "blockers": blockers,
        "observed_utc": now.isoformat(),
    }


def _runtime() -> Any:
    if not os.environ.get("MONGO_URI") or not os.environ.get("MONGO_DB"):
        raise CursorControlError("runtime_configuration_required")
    from infra.operations.zelerdata_read_model_reconcile import create_runtime_db

    return create_runtime_db()


def main(argv: Sequence[str] | None = None) -> int:
    runtime = None
    code = 0
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--inspect", action="store_true")
        parser.add_argument("--approved-runtime", action="store_true")
        parser.add_argument("--execution-id")
        args = parser.parse_args(argv)
        if not args.inspect:
            result = {
                "operation": "question_cursor_inspect",
                "action": "noop",
                "applied": False,
                "transport_authorized": False,
            }
        else:
            if not args.approved_runtime:
                raise CursorControlError("approved_runtime_required")
            if (
                not isinstance(args.execution_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", args.execution_id) is None
            ):
                raise CursorControlError("execution_identity_invalid")
            runtime = _runtime()
            result = asyncio.run(
                inspect_question_cursor(
                    runtime.db, execution_id=args.execution_id, now=datetime.now(UTC)
                )
            )
    except CursorControlError as error:
        result = {"ok": False, "code": str(error), "no_retry": True}
        code = 2
    except Exception:  # noqa: BLE001 - no driver messages or raw BSON at CLI boundary.
        result = {"ok": False, "code": "inspect_failed_no_repeat", "no_retry": True}
        code = 1
    finally:
        if runtime is not None:
            try:
                runtime.client.close()
            except Exception:  # noqa: BLE001 - cleanup must not expose driver values or a false PASS.
                result = {"ok": False, "code": "runtime_cleanup_failed", "no_retry": True}
                code = 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
