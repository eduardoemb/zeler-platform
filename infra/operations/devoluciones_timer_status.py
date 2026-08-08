"""Read-only, sanitized status for the ZELERDATA DEVOLUCIONES reconcile timer.

Prints exactly one JSON object with the keys: ``timer_active``,
``accepted_through``, ``has_accepted_campaign``, ``accepted_campaign_id``,
``p95_seconds``, and ``sample_count``.

The script never touches Mongo and never starts, stops, or queries the systemd
timer unit. Campaign identity (campaign ID and both fingerprint hashes) is
sourced only from the service EnvironmentFile; missing or invalid identity
exits 64 as ``runtime_config_invalid``. Private campaign payloads (fingerprint
hashes, durations, and per-campaign details) are never printed.

``timer_active`` is the acceptance gate: true only while a campaign is durably
accepted for the service release. Enabling or disabling the systemd timer unit
is an operator action (Lane B) and is never performed here.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from infra.operations.zelerdata_campaign_state import (
    CampaignStateError,
    require_accepted_campaign,
    service_campaign_identity,
)

DEFAULT_ACCEPTED_THROUGH = "2026-07-09"
_ACCEPTED_THROUGH_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def accepted_through_from_environment(environment_text: str) -> str:
    try:
        assignments = shlex.split(environment_text)
    except ValueError as exc:
        raise CampaignStateError("systemd service environment is invalid") from exc
    accepted_through: str | None = None
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if separator and key == "ZELERDATA_DEVOLUCIONES_ACCEPTED_THROUGH":
            accepted_through = value
    if accepted_through is None:
        return DEFAULT_ACCEPTED_THROUGH
    return _validated_accepted_through(accepted_through)


def _validated_accepted_through(value: str) -> str:
    if _ACCEPTED_THROUGH_PATTERN.fullmatch(value) is None:
        raise CampaignStateError("systemd service accepted-through is invalid")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise CampaignStateError("systemd service accepted-through is invalid") from exc
    return value


def build_timer_status_document(
    *,
    state_file: Path,
    environment_text: str,
) -> dict[str, object]:
    campaign_id, source_hash, read_hash = service_campaign_identity(environment_text)
    accepted_through = accepted_through_from_environment(environment_text)
    try:
        accepted = require_accepted_campaign(
            state_file,
            expected_campaign_id=campaign_id,
            expected_source_fingerprint_hash=source_hash,
            expected_read_model_fingerprint_hash=read_hash,
        )
    except CampaignStateError:
        return _disabled_status(accepted_through)
    return {
        "timer_active": True,
        "accepted_through": accepted_through,
        "has_accepted_campaign": True,
        "accepted_campaign_id": accepted.campaign_id,
        "p95_seconds": accepted.p95_seconds,
        "sample_count": accepted.sample_count,
    }


def _disabled_status(accepted_through: str) -> dict[str, object]:
    return {
        "timer_active": False,
        "accepted_through": accepted_through,
        "has_accepted_campaign": False,
        "accepted_campaign_id": None,
        "p95_seconds": None,
        "sample_count": 0,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report sanitized ZELERDATA DEVOLUCIONES timer status."
    )
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--service-environment-file", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        environment_text = args.service_environment_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"runtime_config_invalid: {exc}", file=sys.stderr)
        raise SystemExit(64) from exc
    try:
        status = build_timer_status_document(
            state_file=args.state_file,
            environment_text=environment_text,
        )
    except (ValueError, CampaignStateError) as exc:
        print(f"runtime_config_invalid: {exc}", file=sys.stderr)
        raise SystemExit(64) from exc
    print(json.dumps(status, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
