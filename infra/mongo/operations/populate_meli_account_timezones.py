from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pymongo import MongoClient

from zeler_platform_core.meli_timezones import resolve_meli_timezone


@dataclass(frozen=True)
class AccountTimezoneTarget:
    seller_id: str
    site_id: str
    timezone: str | None = None


class PopulationWarning(TypedDict):
    seller_id: str
    site_id: str | None
    timezone: str
    fallback: bool
    reason: str | None


class PopulationSummary(TypedDict):
    status: str
    dry_run: bool
    scanned_count: int
    planned_count: int
    updated_count: int
    warnings: list[PopulationWarning]
    canonical_collections_touched: list[str]


HOPEMOB_SELLER_ID = "82453304"
EXPLICIT_TARGETS: dict[str, AccountTimezoneTarget] = {
    HOPEMOB_SELLER_ID: AccountTimezoneTarget(
        seller_id=HOPEMOB_SELLER_ID,
        site_id="MLM",
        timezone="America/Tijuana",
    ),
}


def _seller_id_as_str(value: object) -> str:
    return str(value).strip()


def _seller_id_filter(seller_id: str) -> dict[str, object]:
    seller_values: list[str | int] = [seller_id]
    if seller_id.isdigit():
        seller_values.append(int(seller_id))
    return {"seller_id": {"$in": seller_values}}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_valid_timezone(value: object) -> bool:
    timezone = _optional_str(value)
    if timezone is None:
        return False
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return False
    return True


def _warning_for(seller_id: str, resolution_site_id: str | None) -> PopulationWarning | None:
    resolution = resolve_meli_timezone(resolution_site_id)
    if not resolution.fallback:
        return None
    return {
        "seller_id": seller_id,
        "site_id": resolution.site_id,
        "timezone": resolution.timezone,
        "fallback": resolution.fallback,
        "reason": resolution.reason,
    }


def _desired_metadata(
    document: Mapping[str, object],
) -> tuple[dict[str, str], PopulationWarning | None]:
    seller_id = _seller_id_as_str(document.get("seller_id"))
    target = EXPLICIT_TARGETS.get(seller_id)
    if target is not None:
        resolution = resolve_meli_timezone(target.site_id)
        return {
            "site_id": target.site_id,
            "timezone": target.timezone or resolution.timezone,
        }, _warning_for(seller_id, target.site_id)

    if _is_valid_timezone(document.get("timezone")):
        return {}, None

    existing_site_id = _optional_str(document.get("site_id"))
    resolution = resolve_meli_timezone(existing_site_id)
    desired = {"timezone": resolution.timezone}
    if resolution.site_id is not None:
        desired["site_id"] = resolution.site_id
    return desired, _warning_for(seller_id, existing_site_id)


def _changed_metadata(document: Mapping[str, object], desired: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value for key, value in desired.items() if _optional_str(document.get(key)) != value
    }


def populate_meli_account_timezones(
    mongo_uri: str,
    *,
    dry_run: bool = True,
    approved_runtime: bool = False,
) -> PopulationSummary:
    if not dry_run and not approved_runtime:
        raise ValueError("approved_runtime is required when dry_run is false")

    client: MongoClient[Mapping[str, object]] = MongoClient(mongo_uri)
    try:
        database = client.get_default_database()
        accounts = database["meli_accounts"]
        documents = list(accounts.find({}))
        planned_count = 0
        updated_count = 0
        warnings: list[PopulationWarning] = []

        for document in documents:
            desired, warning = _desired_metadata(document)
            changed = _changed_metadata(document, desired)
            if warning is not None:
                warnings.append(warning)
            if not changed:
                continue
            planned_count += 1
            if dry_run:
                continue
            result = accounts.update_one(
                _seller_id_filter(_seller_id_as_str(document.get("seller_id"))),
                {"$set": changed},
            )
            updated_count += int(result.modified_count)

        return {
            "status": "dry_run_complete" if dry_run else "write_complete",
            "dry_run": dry_run,
            "scanned_count": len(documents),
            "planned_count": planned_count,
            "updated_count": updated_count,
            "warnings": warnings,
            "canonical_collections_touched": [],
        }
    finally:
        client.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Populate meli_accounts site_id/timezone metadata without canonical re-backfill."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        default=True,
        help="Plan changes without writing them. This is the default.",
    )
    parser.add_argument(
        "--write",
        action="store_false",
        dest="dry_run",
        help=(
            "Write meli_accounts metadata updates. Never rewrites orders/items/shipments/questions."
        ),
    )
    parser.add_argument(
        "--confirm-approved-runtime",
        action="store_true",
        help="Required with --write to confirm execution from an approved runtime context.",
    )
    return parser


def _validate_cli_safety(args: argparse.Namespace) -> None:
    if not bool(args.dry_run) and not bool(args.confirm_approved_runtime):
        raise SystemExit("--confirm-approved-runtime is required with --write")


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    _validate_cli_safety(args)
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        print("error: MONGO_URI is required", file=sys.stderr)
        sys.exit(2)

    summary = populate_meli_account_timezones(
        mongo_uri,
        dry_run=bool(args.dry_run),
        approved_runtime=bool(args.confirm_approved_runtime),
    )
    print(
        "meli account timezone population "
        f"{summary['status']}: scanned={summary['scanned_count']} "
        f"planned={summary['planned_count']} updated={summary['updated_count']} "
        f"warnings={len(summary['warnings'])} canonical_collections_touched=0"
    )


if __name__ == "__main__":
    main()
