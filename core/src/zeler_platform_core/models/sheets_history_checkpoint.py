"""Integrity envelope for original checkpoints; never runtime recovery authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from bson import BSON
from bson.codec_options import CodecOptions
from bson.errors import InvalidBSON
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zeler_platform_core.models.base import assert_aware_utc_datetime

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(ge=1, le=2**63 - 1)]
Revision = Annotated[int, Field(ge=0, le=2**63 - 1)]


def _integer(value: Any, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value < 2**63:
        raise ValueError("checkpoint integer is invalid")
    return int(value)


def deterministic_version_id(
    acquisition_id: str, generation: int, pass_number: int, checkpoint_revision: int
) -> str:
    """One version identity for one original checkpoint, independent of wall time."""
    if not isinstance(acquisition_id, str) or not acquisition_id.strip():
        raise ValueError("checkpoint acquisition identity is invalid")
    seed = {
        "acquisition_id": acquisition_id,
        "generation": _integer(generation, 1),
        "pass_number": _integer(pass_number, 1),
        "checkpoint_revision": _integer(checkpoint_revision),
    }
    return hashlib.sha256(BSON.encode(seed)).hexdigest()


def _decode(raw: bytes) -> dict[str, Any]:
    try:
        return dict(BSON(raw).decode(codec_options=CodecOptions(tz_aware=True, tzinfo=UTC)))
    except InvalidBSON as error:
        raise ValueError("checkpoint BSON is invalid") from error


class SheetsHistoryCheckpointVersion(BaseModel):
    """Exact snapshots and binding metadata, not TTL, ownership or permission proof."""

    model_config = ConfigDict(
        strict=True, extra="forbid", populate_by_name=True, hide_input_in_errors=True
    )

    id: Hash = Field(alias="_id")
    acquisition_id: Text
    job_id: Text
    seller_id: Annotated[str, Field(pattern=r"^[0-9]+$")]
    execution_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    generation: Positive
    pass_number: Positive
    checkpoint_revision: Revision
    reason: Literal["expired_question_cursor"]
    archived_at: datetime
    head_bson: bytes = Field(min_length=5, max_length=64 * 1024, repr=False)
    job_bson: bytes = Field(min_length=5, max_length=64 * 1024, repr=False)
    head_sha256: Hash
    job_sha256: Hash

    @field_validator("archived_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return assert_aware_utc_datetime(value)

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if self.id != deterministic_version_id(
            self.acquisition_id, self.generation, self.pass_number, self.checkpoint_revision
        ):
            raise ValueError("checkpoint version identity does not match scope")
        if (
            hashlib.sha256(self.head_bson).hexdigest() != self.head_sha256
            or hashlib.sha256(self.job_bson).hexdigest() != self.job_sha256
        ):
            raise ValueError("checkpoint snapshot hash does not match")
        head, job = _decode(self.head_bson), _decode(self.job_bson)
        if (
            self.acquisition_id != self.job_id
            or head.get("_id") != self.acquisition_id
            or head.get("job_id") != self.job_id
            or job.get("_id") != self.job_id
            or job.get("history_acquisition_id") != self.acquisition_id
            or head.get("seller_id") != self.seller_id
            or job.get("seller_id") != self.seller_id
            or head.get("read_model") != "questions"
            or job.get("read_model") != "questions"
            or head.get("scope_id") != "seller_scan"
        ):
            raise ValueError("checkpoint snapshot scope does not match")
        cursor = head.get("next_cursor")
        if (
            head.get("phase") not in {"discover", "verify"}
            or not isinstance(cursor, str)
            or not cursor.strip()
            or _integer(head.get("published_count")) != 0
        ):
            raise ValueError("checkpoint is not an unpublished question cursor")
        for head_field, job_field, expected in (
            ("generation", "history_generation", self.generation),
            ("pass_number", "history_pass_number", self.pass_number),
            ("checkpoint_revision", "history_checkpoint_revision", self.checkpoint_revision),
        ):
            if (
                _integer(head.get(head_field)) != expected
                or _integer(job.get(job_field)) != expected
            ):
                raise ValueError("checkpoint version binding does not match")
        if _integer(job.get("history_protocol_version")) != 1:
            raise ValueError("checkpoint protocol is invalid")
        if (
            job.get("state") != "failed"
            or job.get("failure_reason") not in {"source_rejected", "source_cursor_expired"}
            or _integer(job.get("attempts"), 1) < 1
        ):
            raise ValueError("checkpoint job is not the selected terminal failure")
        plan_id = head.get("plan_id")
        start, end = head.get("date_from"), head.get("date_to")
        if (
            not isinstance(plan_id, str)
            or not plan_id.strip()
            or job.get("history_plan_id") != plan_id
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start >= end
            or job.get("date_from") != start
            or job.get("date_to") != end
        ):
            raise ValueError("checkpoint original plan or bounds do not match")
        if job.get("lease_until") is not None and not isinstance(job["lease_until"], datetime):
            raise ValueError("checkpoint lease type is invalid")
        if any(
            "execution_id" in snapshot and snapshot["execution_id"] != self.execution_id
            for snapshot in (head, job)
        ):
            raise ValueError("checkpoint execution binding does not match")
        return self
