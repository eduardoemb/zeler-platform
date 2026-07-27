from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infra.operations.zelerdata_campaign_state import CampaignStateError, PrivateCampaignSample

_CAMPAIGN_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SOURCE_COUNTER_KEYS = ("P", "R", "O", "T")
_PROOF_COUNTER_KEYS = ("expected", "persisted", "complete", "missing")
MAX_SNAPSHOT_PHYSICAL_ATTEMPTS = 104
MAX_SOURCE_PHYSICAL_ATTEMPTS = 208


class ScheduledEvidenceError(ValueError):
    def __init__(self, message: str, *, status_class: str = "evidence_invalid") -> None:
        super().__init__(message)
        self.status_class = status_class


@dataclass(frozen=True)
class ScheduledEvidenceResult:
    public: Mapping[str, Any]
    private_campaign: PrivateCampaignSample
    exit_code: int


def build_scheduled_evidence(
    *,
    raw_output: str,
    campaign_id: str,
    process_status: int,
    wrapper_duration_seconds: float,
) -> tuple[dict[str, Any], int]:
    if _CAMPAIGN_PATTERN.fullmatch(campaign_id) is None:
        raise ScheduledEvidenceError("campaign identity is invalid")
    wrapper_duration = _duration(wrapper_duration_seconds)
    if process_status != 0:
        parsed = _parse_optional_scheduled_run(raw_output, campaign_id=campaign_id)
        return (
            _evidence(
                status_class="timeout" if process_status in {124, 137} else "process_failed",
                counters=parsed["counters"] if parsed else {},
            ),
            0,
        )
    try:
        parsed = _parse_required_scheduled_run(raw_output, campaign_id=campaign_id)
        if wrapper_duration >= 180.0:
            raise ScheduledEvidenceError("hard duration limit reached", status_class="timeout")
    except ScheduledEvidenceError as exc:
        return (
            _evidence(
                status_class=exc.status_class,
                counters={},
            ),
            65,
        )
    return (
        _evidence(
            status_class="success",
            counters=parsed["counters"],
        ),
        0,
    )


def build_scheduled_transport_result(
    *,
    raw_output: str,
    campaign_id: str,
    process_status: int,
    wrapper_duration_seconds: float,
) -> ScheduledEvidenceResult:
    if _CAMPAIGN_PATTERN.fullmatch(campaign_id) is None:
        raise ScheduledEvidenceError("campaign identity is invalid")
    wrapper_duration = _duration(wrapper_duration_seconds)
    if process_status != 0:
        return ScheduledEvidenceResult(
            public=_evidence(
                status_class="timeout" if process_status in {124, 137} else "process_failed",
                counters={},
            ),
            private_campaign=_failure_sample(campaign_id, wrapper_duration),
            exit_code=0,
        )
    try:
        public, private_campaign = _parse_private_transport(
            raw_output, expected_campaign_id=campaign_id
        )
        if wrapper_duration >= 180.0:
            raise ScheduledEvidenceError("hard duration limit reached", status_class="timeout")
    except ScheduledEvidenceError as exc:
        return ScheduledEvidenceResult(
            public=_evidence(status_class=exc.status_class, counters={}),
            private_campaign=_failure_sample(campaign_id, wrapper_duration),
            exit_code=65,
        )
    return ScheduledEvidenceResult(
        public=_evidence(status_class="success", counters=public["counters"]),
        private_campaign=private_campaign,
        exit_code=0,
    )


def _failure_sample(campaign_id: str, duration: float) -> PrivateCampaignSample:
    return PrivateCampaignSample(
        campaign_id=campaign_id,
        outcome="failure",
        campaign_disqualified=True,
        duration_seconds=duration,
    )


def _parse_private_transport(
    raw_output: str, *, expected_campaign_id: str
) -> tuple[dict[str, Any], PrivateCampaignSample]:
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines:
        raise ScheduledEvidenceError("scheduled transport is missing")
    try:
        payload = json.loads(lines[-1])
    except (TypeError, ValueError) as exc:
        raise ScheduledEvidenceError("scheduled transport is malformed") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "public",
        "private_campaign",
    }:
        raise ScheduledEvidenceError("scheduled transport fields are invalid")
    if payload.get("schema_version") != 1:
        raise ScheduledEvidenceError("scheduled transport version is invalid")
    public_payload = payload.get("public")
    if not isinstance(public_payload, Mapping):
        raise ScheduledEvidenceError("scheduled public evidence is invalid")
    public = _parse_required_scheduled_run(
        json.dumps(public_payload, sort_keys=True), campaign_id=expected_campaign_id
    )
    private_payload = payload.get("private_campaign")
    if not isinstance(private_payload, Mapping):
        raise ScheduledEvidenceError("scheduled private campaign is invalid")
    try:
        private_campaign = PrivateCampaignSample.from_mapping(private_payload)
    except (CampaignStateError, ValueError) as exc:
        raise ScheduledEvidenceError("scheduled private campaign is invalid") from exc
    if (
        private_campaign.campaign_id != expected_campaign_id
        or private_campaign.outcome != "success"
        or private_campaign.campaign_disqualified
    ):
        raise ScheduledEvidenceError("scheduled private campaign does not match wrapper")
    return public, private_campaign


def _parse_required_scheduled_run(raw_output: str, *, campaign_id: str) -> dict[str, Any]:
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines:
        raise ScheduledEvidenceError("scheduled output is missing")
    try:
        payload = json.loads(lines[-1])
    except (TypeError, ValueError) as exc:
        raise ScheduledEvidenceError("scheduled output is malformed") from exc
    if not isinstance(payload, Mapping):
        raise ScheduledEvidenceError("scheduled output must be an object")
    del campaign_id  # Campaign identity remains internal to the wrapper process.
    if set(payload) != {"stage", "status_class", "counters"}:
        raise ScheduledEvidenceError("scheduled evidence fields are invalid")
    if payload.get("stage") not in {"dry_run", "write_readback", "acceptance"}:
        raise ScheduledEvidenceError("scheduled evidence stage is invalid")
    status_class = payload.get("status_class")
    if status_class != "success":
        if status_class == "internal_drift":
            raise ScheduledEvidenceError("internal proof drift", status_class="internal_drift")
        raise ScheduledEvidenceError("scheduled run did not succeed")
    counters = _counters(payload.get("counters"))
    _validate_proof_counters(counters)
    return {"counters": counters}


def _parse_optional_scheduled_run(raw_output: str, *, campaign_id: str) -> dict[str, Any] | None:
    try:
        return _parse_required_scheduled_run(raw_output, campaign_id=campaign_id)
    except ScheduledEvidenceError:
        return None


def _evidence(
    *,
    status_class: str,
    counters: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "stage": "scheduled",
        "status_class": status_class,
        "counters": dict(sorted(counters.items())),
    }


def _duration(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScheduledEvidenceError("duration is invalid")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise ScheduledEvidenceError("duration is invalid")
    return round(duration, 3)


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScheduledEvidenceError(f"{field} is invalid")
    return int(value)


def _counters(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ScheduledEvidenceError("source counters are invalid")
    allowed = set(_SOURCE_COUNTER_KEYS) | set(_PROOF_COUNTER_KEYS)
    snapshot_keys = {
        key for key in value if isinstance(key, str) and re.fullmatch(r"snapshot_[12]_T", key)
    }
    if set(value) - allowed - snapshot_keys or not set(_SOURCE_COUNTER_KEYS).issubset(value):
        raise ScheduledEvidenceError("source counters are invalid")
    counters = {key: _nonnegative_int(raw, field=f"counter {key}") for key, raw in value.items()}
    if counters["P"] + counters["R"] + counters["O"] != counters["T"]:
        raise ScheduledEvidenceError(
            "source counters do not add up", status_class="counter_mismatch"
        )
    snapshot_totals = [counters[key] for key in sorted(snapshot_keys)]
    if not snapshot_totals:
        snapshot_totals = [counters["T"]]
    if any(total > MAX_SNAPSHOT_PHYSICAL_ATTEMPTS for total in snapshot_totals):
        raise ScheduledEvidenceError(
            "snapshot source budget exceeded", status_class="source_budget_exceeded"
        )
    if counters["T"] > MAX_SOURCE_PHYSICAL_ATTEMPTS:
        raise ScheduledEvidenceError(
            "run source budget exceeded", status_class="source_budget_exceeded"
        )
    return counters


def _validate_proof_counters(counters: Mapping[str, int]) -> None:
    if not set(_PROOF_COUNTER_KEYS).issubset(counters):
        raise ScheduledEvidenceError("readback counters are incomplete")
    expected = counters["expected"]
    if not (expected == counters["persisted"] == counters["complete"] and counters["missing"] == 0):
        raise ScheduledEvidenceError(
            "readback counters do not agree", status_class="counter_mismatch"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--process-status", type=int, required=True)
    parser.add_argument("--wrapper-duration-seconds", type=float, required=True)
    parser.add_argument("--private-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        raw_output = args.input.read_text(encoding="utf-8", errors="replace")
        if args.private_output is not None:
            result = build_scheduled_transport_result(
                raw_output=raw_output,
                campaign_id=args.campaign_id,
                process_status=args.process_status,
                wrapper_duration_seconds=args.wrapper_duration_seconds,
            )
            args.private_output.write_text(
                json.dumps(
                    result.private_campaign.to_mapping(),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            evidence = result.public
            exit_code = result.exit_code
        else:
            evidence, exit_code = build_scheduled_evidence(
                raw_output=raw_output,
                campaign_id=args.campaign_id,
                process_status=args.process_status,
                wrapper_duration_seconds=args.wrapper_duration_seconds,
            )
    except (OSError, ScheduledEvidenceError):
        evidence = _evidence(
            status_class="evidence_invalid",
            counters={},
        )
        exit_code = 65
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
