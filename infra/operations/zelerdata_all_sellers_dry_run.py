"""Read-only dry run for ZelerData ``all`` mode: how many sellers would be served.

Run it inside ``sheets-worker`` before setting ``ZELERDATA_REFRESH_SELLERS=all``
or ``ZELERDATA_FORMULA_RECOVERY_SELLERS=all``::

    .venv/bin/python -m infra.operations.zelerdata_all_sellers_dry_run \
        [--seller-id <pilot>]

It only reads (``find``) the ``meli_accounts``, ``sheets_extension_tokens`` and
``sheets_formula_recovery_jobs`` collections and prints one JSON document with
counts. It never prints seller IDs, nicknames, token material or statuses it
does not recognize. ``--seller-id`` adds a yes/no and a reason for that one seller,
so the pilot can be confirmed without listing anyone.

The eligible set comes from ``eligible_sellers``, the runtime rule itself. The
exclusion reasons are an explanation of everyone else and are cross-checked
against it (``matches_runtime_rule``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.formulas.seller_scope import (
    ELIGIBLE_ACCOUNT_STATUSES,
    eligible_sellers,
    parse_seller_scope,
)

_KNOWN_ACCOUNT_STATUSES = frozenset(
    {"paused", "revoked", "invalid_grant", "error", "invalid", "pending"}
)
# Closest-to-usable first, so a seller with several tokens gets one honest reason.
_TOKEN_STATES = ("valid", "expired", "inactive", "deleted")
ACTIVE_JOB_STATES = ["pending", "running"]
_SCOPE_FLAGS = (
    "ZELERDATA_REFRESH_ENABLED",
    "ZELERDATA_FORMULA_RECOVERY_ENABLED",
    "ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED",
    "ZELERDATA_SCHEDULED_INVENTORY_REFRESH_ENABLED",
    "ZELERDATA_SCHEDULED_CATALOG_REFRESH_ENABLED",
    "ZELERDATA_PRECALCULATED_FORMULAS_ENABLED",
    "ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED",
    "ZELERDATA_ORDER_HISTORY_PROTOCOL_ENABLED",
    "ZELERDATA_QUESTION_HISTORY_PROTOCOL_ENABLED",
    "ZELERDATA_ORDER_MODIFICATION_SCAN_ENABLED",
    "ZELERDATA_HISTORY_ON_LINK_ENABLED",
)


def _seller_key(value: Any) -> str | None:
    seller_id = str(value if value is not None else "").strip()
    return seller_id if seller_id.isascii() and seller_id.isdecimal() else None


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _account_reasons(db: Any) -> tuple[dict[str, str | None], int]:
    """Per seller: ``None`` when an account is usable, else the account reason."""
    reasons: dict[str, str | None] = {}
    invalid_ids = 0
    async for account in db["meli_accounts"].find({}, {"seller_id": 1, "status": 1}):
        seller_id = _seller_key(account.get("seller_id"))
        if seller_id is None:
            invalid_ids += 1
            continue
        status = str(account.get("status") or "").strip()
        if status in ELIGIBLE_ACCOUNT_STATUSES:
            reasons[seller_id] = None
        elif reasons.get(seller_id, "") is not None:
            reasons[seller_id] = (
                f"account_{status}" if status in _KNOWN_ACCOUNT_STATUSES else "account_other_status"
            )
    return reasons, invalid_ids


async def _token_states(db: Any, now: datetime) -> dict[str, str]:
    """Per seller scoped by any extension token: the best state among its tokens."""
    best: dict[str, int] = {}
    projection = {"seller_scopes": 1, "expires_at": 1, "status": 1, "deleted_at": 1}
    async for token in db["sheets_extension_tokens"].find({}, projection):
        if token.get("deleted_at") is not None:
            state = "deleted"
        elif token.get("status") != "active":
            state = "inactive"
        else:
            expires_at = _aware(token.get("expires_at"))
            state = "expired" if expires_at is not None and expires_at <= now else "valid"
        rank = len(_TOKEN_STATES) - _TOKEN_STATES.index(state)
        for scope in token.get("seller_scopes") or ():
            seller_id = _seller_key(scope.get("seller_id")) if isinstance(scope, dict) else None
            if seller_id is not None:
                best[seller_id] = max(best.get(seller_id, 0), rank)
    return {seller: _TOKEN_STATES[len(_TOKEN_STATES) - rank] for seller, rank in best.items()}


def _reason(seller_id: str, accounts: dict[str, str | None], tokens: dict[str, str]) -> str:
    if seller_id not in accounts:
        return "token_scope_without_linked_account" if seller_id in tokens else "not_linked"
    if accounts[seller_id] is not None:
        return str(accounts[seller_id])
    state = tokens.get(seller_id)
    if state is None:
        return "no_extension_token"
    return "eligible" if state == "valid" else f"extension_token_{state}"


async def _active_jobs(db: Any, eligible: frozenset[str]) -> dict[str, int]:
    total = 0
    ineligible = 0
    async for job in db["sheets_formula_recovery_jobs"].find(
        {"state": {"$in": ACTIVE_JOB_STATES}}, {"seller_id": 1}
    ):
        total += 1
        if str(job.get("seller_id") or "").strip() not in eligible:
            ineligible += 1
    return {"total": total, "for_ineligible_sellers": ineligible}


def _configuration(environ: Any) -> dict[str, Any]:
    def scope(name: str) -> str:
        try:
            parsed = parse_seller_scope(environ.get(name), error="invalid")
        except ValueError:
            return "invalid"
        if parsed is None:
            return "all"
        return f"numeric:{len(parsed)}" if parsed else "closed"

    return {
        "refresh_sellers": scope("ZELERDATA_REFRESH_SELLERS"),
        "recovery_sellers": scope("ZELERDATA_FORMULA_RECOVERY_SELLERS"),
        "flags": {
            name: str(environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
            for name in _SCOPE_FLAGS
        },
    }


async def build_report(
    db: Any,
    *,
    now: datetime | None = None,
    seller_id: str | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    accounts, invalid_ids = await _account_reasons(db)
    tokens = await _token_states(db, current)
    eligible = frozenset(await eligible_sellers(db, now=current))
    sellers = set(accounts) | set(tokens)
    reasons = Counter(_reason(seller, accounts, tokens) for seller in sellers)
    explained = frozenset(
        seller for seller in sellers if _reason(seller, accounts, tokens) == "eligible"
    )
    excluded = {reason: count for reason, count in sorted(reasons.items()) if reason != "eligible"}
    report: dict[str, Any] = {
        "read_only": True,
        "generated_at": current.isoformat(),
        "linked_sellers": len(accounts),
        "accounts_with_invalid_seller_id": invalid_ids,
        "eligible_sellers": len(eligible),
        "excluded_sellers_by_reason": excluded,
        "matches_runtime_rule": explained == eligible,
        "active_recovery_jobs": await _active_jobs(db, eligible),
        "configuration": _configuration(os.environ if environ is None else environ),
    }
    if seller_id is not None:
        key = _seller_key(seller_id)
        report["requested_seller"] = {
            "eligible": key in eligible,
            "reason": "eligible" if key in eligible else _reason(key or "", accounts, tokens),
        }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--seller-id",
        help="report only whether this one seller would be eligible, and why",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    client: Any = AsyncIOMotorClient(
        os.environ["MONGO_URI"],
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
        maxPoolSize=2,
        tz_aware=True,
    )
    try:
        return await build_report(client[os.environ["MONGO_DB"]], seller_id=args.seller_id)
    finally:
        client.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not os.environ.get("MONGO_URI") or not os.environ.get("MONGO_DB"):
        print(json.dumps({"error": "MONGO_URI and MONGO_DB are required"}))
        return 2
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - fixed code only; never echo URIs or payloads
        print(json.dumps({"error": "dry_run_failed", "type": type(exc).__name__}))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
