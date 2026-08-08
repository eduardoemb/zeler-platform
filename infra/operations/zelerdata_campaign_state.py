from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CAMPAIGN_WINDOW_SIZE = 20
_CAMPAIGN_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


class CampaignStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class AcceptedCampaign:
    campaign_id: str
    sample_count: int
    p95_seconds: float
    source_fingerprint_hash: str
    read_model_fingerprint_hash: str


@dataclass(frozen=True)
class PrivateCampaignSample:
    campaign_id: str
    outcome: str
    campaign_disqualified: bool
    duration_seconds: float
    source_fingerprint_hash: str | None = None
    read_model_fingerprint_hash: str | None = None

    def __post_init__(self) -> None:
        validated = _validated_evidence(self.to_mapping())
        object.__setattr__(self, "duration_seconds", validated["duration_seconds"])

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PrivateCampaignSample:
        validated = _validated_evidence(value)
        return cls(**validated)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "outcome": self.outcome,
            "campaign_disqualified": self.campaign_disqualified,
            "duration_seconds": self.duration_seconds,
            "source_fingerprint_hash": self.source_fingerprint_hash,
            "read_model_fingerprint_hash": self.read_model_fingerprint_hash,
        }


@dataclass(frozen=True)
class CampaignState:
    disqualified_campaign_ids: frozenset[str]
    accepted_campaign_id: str | None
    campaigns: Mapping[str, Mapping[str, Any]]


def nearest_rank_p95(durations: Sequence[float]) -> float:
    if not durations:
        raise CampaignStateError("eligible campaign window is empty")
    normalized = sorted(_duration(value) for value in durations)
    rank = math.ceil(0.95 * len(normalized))
    return normalized[rank - 1]


class CampaignStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CampaignState:
        document = self._load_document()
        return CampaignState(
            disqualified_campaign_ids=frozenset(document["disqualified_campaign_ids"]),
            accepted_campaign_id=document["accepted_campaign_id"],
            campaigns=document["campaigns"],
        )

    def record(self, evidence: Mapping[str, Any] | PrivateCampaignSample) -> CampaignState:
        sample = (
            evidence
            if isinstance(evidence, PrivateCampaignSample)
            else PrivateCampaignSample.from_mapping(evidence)
        ).to_mapping()
        document = self._load_document()
        campaign_id = sample["campaign_id"]
        disqualified = set(document["disqualified_campaign_ids"])
        failure_reason: str | None = None
        if campaign_id in disqualified and not (
            sample["campaign_disqualified"] or sample["outcome"] != "success"
        ):
            raise CampaignStateError("campaign ID is permanently disqualified")
        campaigns = document["campaigns"]
        if sample["campaign_disqualified"] or sample["outcome"] != "success":
            disqualified.add(campaign_id)
            campaigns.pop(campaign_id, None)
            if document["accepted_campaign_id"] == campaign_id:
                document["accepted_campaign_id"] = None
        else:
            campaign = campaigns.setdefault(
                campaign_id,
                {
                    "source_fingerprint_hash": sample["source_fingerprint_hash"],
                    "read_model_fingerprint_hash": sample["read_model_fingerprint_hash"],
                    "durations": [],
                },
            )
            if (
                campaign["source_fingerprint_hash"] != sample["source_fingerprint_hash"]
                or campaign["read_model_fingerprint_hash"] != sample["read_model_fingerprint_hash"]
            ):
                if document["accepted_campaign_id"] == campaign_id:
                    raise CampaignStateError(
                        "campaign fingerprint drift refused without state update"
                    )
                disqualified.add(campaign_id)
                campaigns.pop(campaign_id, None)
                failure_reason = "campaign fingerprint drift disqualified the campaign ID"
            else:
                durations = [*campaign["durations"], sample["duration_seconds"]]
                campaign["durations"] = durations[-CAMPAIGN_WINDOW_SIZE:]
                if len(campaign["durations"]) == CAMPAIGN_WINDOW_SIZE:
                    p95 = nearest_rank_p95(campaign["durations"])
                    if p95 >= 150.0:
                        disqualified.add(campaign_id)
                        campaigns.pop(campaign_id, None)
                        document["accepted_campaign_id"] = None
                    else:
                        document["accepted_campaign_id"] = campaign_id
        document["disqualified_campaign_ids"] = sorted(disqualified)
        self._atomic_write(document)
        if failure_reason is not None:
            raise CampaignStateError(failure_reason)
        return self.load()

    def _load_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "disqualified_campaign_ids": [],
                "accepted_campaign_id": None,
                "campaigns": {},
            }
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CampaignStateError("campaign state is unreadable") from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or not isinstance(document.get("disqualified_campaign_ids"), list)
            or not isinstance(document.get("campaigns"), dict)
            or (
                document.get("accepted_campaign_id") is not None
                and not isinstance(document.get("accepted_campaign_id"), str)
            )
        ):
            raise CampaignStateError("campaign state schema is invalid")
        return document

    def _atomic_write(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary_path.unlink(missing_ok=True)


def require_accepted_campaign(
    path: Path,
    *,
    expected_campaign_id: str,
    expected_source_fingerprint_hash: str,
    expected_read_model_fingerprint_hash: str,
) -> AcceptedCampaign:
    state = CampaignStateStore(path).load()
    campaign_id = state.accepted_campaign_id
    if campaign_id is None or campaign_id in state.disqualified_campaign_ids:
        raise CampaignStateError("campaign is not accepted")
    if campaign_id != expected_campaign_id:
        raise CampaignStateError("accepted campaign does not match the service release")
    campaign = state.campaigns.get(campaign_id)
    if not isinstance(campaign, Mapping):
        raise CampaignStateError("accepted campaign state is missing")
    durations = campaign.get("durations")
    if not isinstance(durations, list) or len(durations) != CAMPAIGN_WINDOW_SIZE:
        raise CampaignStateError("campaign is not accepted")
    if (
        campaign.get("source_fingerprint_hash") != expected_source_fingerprint_hash
        or campaign.get("read_model_fingerprint_hash") != expected_read_model_fingerprint_hash
    ):
        raise CampaignStateError("accepted campaign fingerprints do not match the service release")
    p95 = nearest_rank_p95(durations)
    if p95 >= 150.0 or any(_duration(value) >= 180.0 for value in durations):
        raise CampaignStateError("campaign is not accepted")
    return AcceptedCampaign(
        campaign_id,
        len(durations),
        p95,
        expected_source_fingerprint_hash,
        expected_read_model_fingerprint_hash,
    )


def service_campaign_identity(environment_text: str) -> tuple[str, str, str]:
    try:
        assignments = shlex.split(environment_text)
    except ValueError as exc:
        raise CampaignStateError("systemd service environment is invalid") from exc
    environment: dict[str, str] = {}
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if separator:
            environment[key] = value
    campaign_id = environment.get("ZELERDATA_DEVOLUCIONES_CAMPAIGN_ID", "")
    source_hash = environment.get("ZELERDATA_DEVOLUCIONES_SOURCE_FINGERPRINT_HASH", "")
    read_hash = environment.get("ZELERDATA_DEVOLUCIONES_READ_MODEL_FINGERPRINT_HASH", "")
    if _CAMPAIGN_PATTERN.fullmatch(campaign_id) is None:
        raise CampaignStateError("systemd service campaign identity is missing or invalid")
    if _HASH_PATTERN.fullmatch(source_hash) is None or _HASH_PATTERN.fullmatch(read_hash) is None:
        raise CampaignStateError("systemd service release fingerprints are missing or invalid")
    return campaign_id, source_hash, read_hash


def _validated_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    campaign_id = value.get("campaign_id")
    if not isinstance(campaign_id, str) or _CAMPAIGN_PATTERN.fullmatch(campaign_id) is None:
        raise CampaignStateError("campaign evidence identity is invalid")
    outcome = value.get("outcome")
    if outcome not in {"success", "failure"}:
        raise CampaignStateError("campaign evidence outcome is invalid")
    disqualified = value.get("campaign_disqualified")
    if not isinstance(disqualified, bool):
        raise CampaignStateError("campaign evidence disqualification is invalid")
    if outcome == "success":
        source_hash = value.get("source_fingerprint_hash")
        read_hash = value.get("read_model_fingerprint_hash")
        if (
            not isinstance(source_hash, str)
            or _HASH_PATTERN.fullmatch(source_hash) is None
            or not isinstance(read_hash, str)
            or _HASH_PATTERN.fullmatch(read_hash) is None
        ):
            raise CampaignStateError("campaign evidence fingerprint is invalid")
    elif (
        value.get("source_fingerprint_hash") is not None
        or value.get("read_model_fingerprint_hash") is not None
    ):
        raise CampaignStateError("campaign evidence fingerprints are success-only")
    return {
        "campaign_id": campaign_id,
        "outcome": outcome,
        "campaign_disqualified": disqualified,
        "duration_seconds": _duration(value.get("duration_seconds")),
        "source_fingerprint_hash": value.get("source_fingerprint_hash"),
        "read_model_fingerprint_hash": value.get("read_model_fingerprint_hash"),
    }


def _duration(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignStateError("campaign duration is invalid")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise CampaignStateError("campaign duration is invalid")
    return duration


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--state-file", type=Path, required=True)
    record.add_argument("--evidence-file", type=Path, required=True)
    record_stdin = subparsers.add_parser("record-stdin")
    record_stdin.add_argument("--state-file", type=Path, required=True)
    accepted = subparsers.add_parser("require-accepted")
    accepted.add_argument("--state-file", type=Path, required=True)
    accepted.add_argument("--service-environment-file", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command in {"record", "record-stdin"}:
            raw_evidence = (
                args.evidence_file.read_text(encoding="utf-8")
                if args.command == "record"
                else sys.stdin.read()
            )
            evidence = json.loads(raw_evidence)
            if not isinstance(evidence, Mapping):
                raise CampaignStateError("campaign evidence must be an object")
            state = CampaignStateStore(args.state_file).record(evidence)
            campaign_id = evidence.get("campaign_id")
            if (
                evidence.get("outcome") == "success"
                and campaign_id in state.disqualified_campaign_ids
            ):
                updated_evidence = dict(evidence)
                updated_evidence.update(
                    {
                        "outcome": "failure",
                        "reason": "campaign_budget_disqualified",
                        "campaign_disqualified": True,
                        "reset_required": True,
                    }
                )
                CampaignStateStore(args.evidence_file)._atomic_write(updated_evidence)
                raise CampaignStateError("campaign ID is permanently disqualified")
            return 0
        environment_text = args.service_environment_file.read_text(encoding="utf-8")
        campaign_id, source_hash, read_hash = service_campaign_identity(environment_text)
        accepted = require_accepted_campaign(
            args.state_file,
            expected_campaign_id=campaign_id,
            expected_source_fingerprint_hash=source_hash,
            expected_read_model_fingerprint_hash=read_hash,
        )
    except (OSError, ValueError, CampaignStateError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "campaign_id": accepted.campaign_id,
                "sample_count": accepted.sample_count,
                "p95_seconds": accepted.p95_seconds,
                "source_fingerprint_hash": accepted.source_fingerprint_hash,
                "read_model_fingerprint_hash": accepted.read_model_fingerprint_hash,
                "status": "accepted",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
