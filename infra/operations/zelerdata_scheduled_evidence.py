from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_CAMPAIGN_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_COUNTER_KEYS = ("P", "R", "O", "T")


class ScheduledEvidenceError(ValueError):
    pass


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
        reason = "timeout" if process_status in {124, 137} else "process_failed"
        if parsed is None:
            reason = f"{reason}_evidence_missing"
        return (
            _evidence(
                campaign_id=campaign_id,
                outcome="failure",
                reason=reason,
                duration_seconds=wrapper_duration,
                parsed=parsed,
                disqualified=True,
            ),
            0,
        )
    try:
        parsed = _parse_required_scheduled_run(raw_output, campaign_id=campaign_id)
        duration = _duration(parsed["duration_seconds"])
        if duration >= 180.0:
            raise ScheduledEvidenceError("hard duration limit reached")
        if parsed["physical_attempts"] > 64:
            raise ScheduledEvidenceError("physical attempt limit exceeded")
        if parsed["succeeded"] is not True:
            raise ScheduledEvidenceError("scheduled run did not succeed")
    except ScheduledEvidenceError:
        return (
            _evidence(
                campaign_id=campaign_id,
                outcome="failure",
                reason="evidence_invalid",
                duration_seconds=wrapper_duration,
                parsed=None,
                disqualified=True,
            ),
            65,
        )
    return (
        _evidence(
            campaign_id=campaign_id,
            outcome="success",
            reason="candidate_sample_recorded",
            duration_seconds=duration,
            parsed=parsed,
            disqualified=False,
        ),
        0,
    )


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
    scheduled = payload.get("scheduled_run")
    runtime = payload.get("runtime_evidence")
    if not isinstance(scheduled, Mapping) or not isinstance(runtime, Mapping):
        raise ScheduledEvidenceError("scheduled evidence is incomplete")
    if scheduled.get("campaign_id") != campaign_id:
        raise ScheduledEvidenceError("campaign identity changed")
    succeeded = scheduled.get("succeeded")
    if not isinstance(succeeded, bool):
        raise ScheduledEvidenceError("scheduled outcome is invalid")
    attempts = _nonnegative_int(scheduled.get("physical_attempts"), field="physical attempts")
    counters = _counters(runtime.get("source_calls"))
    if attempts != counters["T"]:
        raise ScheduledEvidenceError("physical attempts do not match counters")
    source_fingerprint = _fingerprint(scheduled.get("source_fingerprint"), field="source")
    read_model_fingerprint = _fingerprint(
        scheduled.get("read_model_fingerprint"), field="read model"
    )
    return {
        "duration_seconds": _duration(scheduled.get("duration_seconds")),
        "succeeded": succeeded,
        "physical_attempts": attempts,
        "counters": counters,
        "source_fingerprint_hash": _hash_text(source_fingerprint),
        "read_model_fingerprint_hash": _hash_text(read_model_fingerprint),
    }


def _parse_optional_scheduled_run(raw_output: str, *, campaign_id: str) -> dict[str, Any] | None:
    try:
        return _parse_required_scheduled_run(raw_output, campaign_id=campaign_id)
    except ScheduledEvidenceError:
        return None


def _evidence(
    *,
    campaign_id: str,
    outcome: str,
    reason: str,
    duration_seconds: float,
    parsed: Mapping[str, Any] | None,
    disqualified: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event": "zelerdata_devoluciones_scheduled_run",
        "campaign_id": campaign_id,
        "outcome": outcome,
        "reason": reason,
        "duration_seconds": duration_seconds,
        "physical_attempts": parsed.get("physical_attempts") if parsed else None,
        "source_fingerprint_hash": parsed.get("source_fingerprint_hash") if parsed else None,
        "read_model_fingerprint_hash": (
            parsed.get("read_model_fingerprint_hash") if parsed else None
        ),
        "counters": parsed.get("counters") if parsed else dict.fromkeys(_COUNTER_KEYS),
        "campaign_disqualified": disqualified,
        "reset_required": disqualified,
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
    if not isinstance(value, Mapping) or set(value) != set(_COUNTER_KEYS):
        raise ScheduledEvidenceError("source counters are invalid")
    counters = {
        key: _nonnegative_int(value.get(key), field=f"counter {key}") for key in _COUNTER_KEYS
    }
    if counters["P"] + counters["R"] + counters["O"] != counters["T"]:
        raise ScheduledEvidenceError("source counters do not add up")
    return counters


def _fingerprint(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ScheduledEvidenceError(f"{field} fingerprint is invalid")
    return value


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--process-status", type=int, required=True)
    parser.add_argument("--wrapper-duration-seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        raw_output = args.input.read_text(encoding="utf-8", errors="replace")
        evidence, exit_code = build_scheduled_evidence(
            raw_output=raw_output,
            campaign_id=args.campaign_id,
            process_status=args.process_status,
            wrapper_duration_seconds=args.wrapper_duration_seconds,
        )
    except (OSError, ScheduledEvidenceError):
        evidence = _evidence(
            campaign_id=(
                args.campaign_id
                if _CAMPAIGN_PATTERN.fullmatch(args.campaign_id)
                else "invalid-campaign"
            ),
            outcome="failure",
            reason="evidence_invalid",
            duration_seconds=0.0,
            parsed=None,
            disqualified=True,
        )
        exit_code = 65
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
