"""Phase1 immutable BSON envelope only; no admission, clock authority, sockets or DB."""

from __future__ import annotations

import copy
import hashlib
import importlib
import re
import socket
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from bson import BSON
from bson.codec_options import CodecOptions

ACQUISITION = "questions-scan:82453304:fixture-fixed-plan"
EXECUTION = "868b413e20184befb7e8358e0051924f"
ARCHIVED = datetime(2026, 10, 6, 8, 30, tzinfo=UTC)
UPDATED = datetime(2026, 10, 6, 4, 32, 12, 830586, tzinfo=UTC)
START = datetime(2025, 9, 24, 5, 36, 28, tzinfo=UTC)
END = START.replace(year=2026)
EXTRA = {"retained_unknown_field": {"value": "SYNTHETIC_EXTRA_MUST_REMAIN", "count": 7}}


def module() -> ModuleType:
    return importlib.import_module("zeler_platform_core.models.sheets_history_checkpoint")


def heads() -> tuple[dict[str, Any], dict[str, Any]]:
    head = {
        "_id": ACQUISITION,
        "seller_id": "82453304",
        "read_model": "questions",
        "scope_id": "seller_scan",
        "plan_id": "fixture-fixed-plan",
        "job_id": ACQUISITION,
        "date_from": START,
        "date_to": END,
        "generation": 1,
        "pass_number": 1,
        "checkpoint_revision": 3,
        "page_sequence": 3,
        "phase": "discover",
        "next_cursor": "synthetic-private-cursor",
        "discovered_count": 71,
        "fetched_count": 0,
        "published_count": 0,
        "source_total": 80,
        "created_at": UPDATED - timedelta(minutes=2),
        "updated_at": UPDATED,
        "observed_from": UPDATED - timedelta(minutes=2),
        "observed_until": UPDATED,
        **copy.deepcopy(EXTRA),
    }
    job = {
        "_id": ACQUISITION,
        "seller_id": "82453304",
        "read_model": "questions",
        "state": "failed",
        "failure_reason": "source_rejected",
        "attempts": 1,
        "policy_authority": "history-on-link-v1",
        "history_protocol_version": 1,
        "history_plan_id": "fixture-fixed-plan",
        "history_acquisition_id": ACQUISITION,
        "history_generation": 1,
        "history_pass_number": 1,
        "history_checkpoint_revision": 3,
        "date_from": START,
        "date_to": END,
        "created_at": UPDATED - timedelta(minutes=2),
        "updated_at": ARCHIVED - timedelta(minutes=40),
        **copy.deepcopy(EXTRA),
    }
    return head, job


def payload() -> dict[str, Any]:
    m = module()
    head, job = heads()
    raw_head, raw_job = BSON.encode(head), BSON.encode(job)
    return {
        "_id": m.deterministic_version_id(ACQUISITION, 1, 1, 3),
        "acquisition_id": ACQUISITION,
        "job_id": ACQUISITION,
        "seller_id": "82453304",
        "execution_id": EXECUTION,
        "generation": 1,
        "pass_number": 1,
        "checkpoint_revision": 3,
        "reason": "expired_question_cursor",
        "archived_at": ARCHIVED,
        "head_bson": raw_head,
        "job_bson": raw_job,
        "head_sha256": hashlib.sha256(raw_head).hexdigest(),
        "job_sha256": hashlib.sha256(raw_job).hexdigest(),
    }


def validate(value: dict[str, Any]) -> Any:
    return module().SheetsHistoryCheckpointVersion.model_validate(value)


def replace_blob(value: dict[str, Any], which: str, changes: dict[str, Any]) -> None:
    document = BSON(value[which + "_bson"]).decode(codec_options=CodecOptions(tz_aware=True))
    document.update(changes)
    value[which + "_bson"] = BSON.encode(document)
    value[which + "_sha256"] = hashlib.sha256(value[which + "_bson"]).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("checkpoint envelope tests forbid sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def test_raw_bytes_unknown_fields_and_bson_milliseconds_are_preserved() -> None:
    value = payload()
    before = copy.deepcopy(value)
    result = validate(value)
    assert "SYNTHETIC_EXTRA_MUST_REMAIN" not in str(result)
    assert "synthetic-private-cursor" not in str(result)
    out = result.model_dump(by_alias=True)
    assert out["head_bson"] == before["head_bson"] and out["job_bson"] == before["job_bson"]
    decoded = BSON(out["head_bson"]).decode(codec_options=CodecOptions(tz_aware=True))
    assert decoded["retained_unknown_field"] == EXTRA["retained_unknown_field"]
    assert decoded["updated_at"].microsecond == 830000
    assert value == before
    assert "execution_consumed" not in out and "execution_sent" not in out


def test_version_id_is_exact_deterministic_bson_scope_hash() -> None:
    m = module()
    seed = {
        "acquisition_id": ACQUISITION,
        "generation": 1,
        "pass_number": 1,
        "checkpoint_revision": 3,
    }
    expected = hashlib.sha256(BSON.encode(seed)).hexdigest()
    assert m.deterministic_version_id(ACQUISITION, 1, 1, 3) == expected
    assert re.fullmatch("[a-f0-9]{64}", expected)
    assert m.deterministic_version_id(ACQUISITION, 1, 2, 3) != expected
    for values in (
        ("", 1, 1, 3),
        (ACQUISITION, True, 1, 3),
        (ACQUISITION, 1, "1", 3),
        (ACQUISITION, 1, 1, -1),
        (ACQUISITION, 1, 1, 2**64),
    ):
        with pytest.raises(ValueError):
            m.deterministic_version_id(*values)


def test_outer_extra_and_required_fields_are_strict() -> None:
    value = payload()
    value["counter_grant"] = 2500
    with pytest.raises(ValueError):
        validate(value)
    value = payload()
    value.pop("reason")
    with pytest.raises(ValueError):
        validate(value)


def test_sha_mismatch_and_malformed_hashes_are_rejected() -> None:
    for field, bad in (
        ("head_sha256", "0" * 64),
        ("job_sha256", "0" * 64),
        ("head_sha256", "A" * 64),
        ("job_sha256", True),
    ):
        value = payload()
        value[field] = bad
        with pytest.raises(ValueError) as error:
            validate(value)
        assert "SYNTHETIC_EXTRA_MUST_REMAIN" not in str(error.value)
        assert "synthetic-private-cursor" not in str(error.value)


def test_version_id_and_metadata_bind_both_blob_identities() -> None:
    for field, bad in (
        ("_id", "0" * 64),
        ("acquisition_id", "other"),
        ("job_id", "other"),
        ("seller_id", "123"),
    ):
        value = payload()
        value[field] = bad
        with pytest.raises(ValueError):
            validate(value)
    for which in ("head", "job"):
        value = payload()
        replace_blob(value, which, {"_id": "other"})
        with pytest.raises(ValueError):
            validate(value)


def test_generation_pass_revision_and_job_binding_are_exact() -> None:
    for field, bad in (
        ("generation", 2),
        ("pass_number", 2),
        ("checkpoint_revision", 4),
        ("generation", True),
        ("pass_number", "1"),
        ("checkpoint_revision", -1),
    ):
        value = payload()
        value[field] = bad
        with pytest.raises(ValueError):
            validate(value)
    for field in ("history_generation", "history_pass_number", "history_checkpoint_revision"):
        value = payload()
        replace_blob(value, "job", {field: 99})
        with pytest.raises(ValueError):
            validate(value)


def test_execution_id_is_strict_32hex_not_fabricated_from_blobs() -> None:
    value = payload()
    assert "execution_id" not in BSON(value["head_bson"]).decode()
    assert validate(value).execution_id == EXECUTION
    for bad in ("B" * 32, "a" * 31, True, 82453304):
        value = payload()
        value["execution_id"] = bad
        with pytest.raises(ValueError):
            validate(value)
    value = payload()
    replace_blob(value, "job", {"execution_id": "b" * 32})
    with pytest.raises(ValueError):
        validate(value)


def test_archived_at_requires_aware_time_and_normalizes_utc() -> None:
    for bad in (ARCHIVED.replace(tzinfo=None), "2026-10-06T08:30:00Z", None):
        value = payload()
        value["archived_at"] = bad
        with pytest.raises(ValueError):
            validate(value)
    value = payload()
    value["archived_at"] = ARCHIVED.astimezone(timezone(timedelta(hours=2)))
    assert validate(value).archived_at == ARCHIVED
    assert validate(value).archived_at.utcoffset() == timedelta(0)


def test_bson_cap_is_exact_and_string_coercion_is_not_allowed() -> None:
    for which in ("head", "job"):
        value = payload()
        decoded = BSON(value[which + "_bson"]).decode()
        decoded["padding"] = ""
        decoded["padding"] = "x" * (65536 - len(BSON.encode(decoded)))
        value[which + "_bson"] = BSON.encode(decoded)
        value[which + "_sha256"] = hashlib.sha256(value[which + "_bson"]).hexdigest()
        assert len(value[which + "_bson"]) == 65536
        assert validate(value).model_dump()[which + "_bson"] == value[which + "_bson"]
        decoded["padding"] += "x"
        value[which + "_bson"] = BSON.encode(decoded)
        value[which + "_sha256"] = hashlib.sha256(value[which + "_bson"]).hexdigest()
        with pytest.raises(ValueError):
            validate(value)
    value = payload()
    value["head_bson"] = "not bytes"
    with pytest.raises(ValueError):
        validate(value)


def test_truncated_or_trailing_bson_is_rejected_even_when_hash_matches() -> None:
    for which in ("head", "job"):
        for suffix in (None, b"tail"):
            value = payload()
            raw = value[which + "_bson"][:-1] if suffix is None else value[which + "_bson"] + suffix
            value[which + "_bson"] = raw
            value[which + "_sha256"] = hashlib.sha256(raw).hexdigest()
            with pytest.raises(ValueError):
                validate(value)


def test_questions_cursor_phase_and_unpublished_scope_are_required() -> None:
    for bad in (
        {"read_model": "orders"},
        {"phase": "publish"},
        {"phase": "completed"},
        {"next_cursor": None},
        {"next_cursor": 0},
        {"next_cursor": ""},
        {"published_count": 1},
        {"published_count": False},
        {"scope_id": "different"},
    ):
        value = payload()
        replace_blob(value, "head", bad)
        with pytest.raises(ValueError):
            validate(value)
    value = payload()
    replace_blob(value, "head", {"phase": "verify"})
    assert validate(value).head_bson == value["head_bson"]


def test_terminal_question_job_attempts_and_failure_reason_are_required() -> None:
    for bad in (
        {"state": "running"},
        {"state": "completed"},
        {"failure_reason": "source_temporarily_unavailable"},
        {"attempts": 0},
        {"attempts": True},
        {"read_model": "orders"},
        {"history_protocol_version": False},
    ):
        value = payload()
        replace_blob(value, "job", bad)
        with pytest.raises(ValueError):
            validate(value)
    value = payload()
    replace_blob(value, "job", {"failure_reason": "source_cursor_expired"})
    assert validate(value).job_bson == value["job_bson"]


def test_plan_binding_bounds_and_job_seller_must_match_original_head() -> None:
    for bad in (
        {"history_plan_id": "other"},
        {"history_acquisition_id": "other"},
        {"seller_id": "123"},
        {"date_to": END + timedelta(milliseconds=1)},
        {"date_from": None},
    ):
        value = payload()
        replace_blob(value, "job", bad)
        with pytest.raises(ValueError):
            validate(value)


def test_lease_type_is_checked_but_live_lease_clock_is_operator_authority() -> None:
    value = payload()
    replace_blob(value, "job", {"lease_until": ARCHIVED + timedelta(days=10)})
    # Archive metadata validation cannot choose a runtime clock or authorize
    # readmission. The operator must reject this live lease before mutations.
    assert validate(value).job_bson == value["job_bson"]
    for bad in ("2026-10-06T09:00:00Z", True, 1):
        value = payload()
        replace_blob(value, "job", {"lease_until": bad})
        with pytest.raises(ValueError):
            validate(value)


def test_raw_type_or_date_bound_corruption_is_not_repaired() -> None:
    for which, bad in (
        ("head", {"date_from": "2025-09-24"}),
        ("head", {"date_to": START}),
        ("head", {"generation": True}),
        ("job", {"history_pass_number": "1"}),
    ):
        value = payload()
        replace_blob(value, which, bad)
        with pytest.raises(ValueError):
            validate(value)


def test_pydantic_schema_forbids_outer_extra_without_business_or_authority_fields() -> None:
    schema = module().SheetsHistoryCheckpointVersion.model_json_schema(by_alias=True)
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert {"_id", "head_bson", "job_bson", "head_sha256", "job_sha256"} <= set(properties)
    assert not {"execution_consumed", "execution_sent", "total_consumed", "allowed_until"} & set(
        properties
    )


def test_new_mongo_schema_and_unique_version_index_match_envelope_only() -> None:
    import json

    from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _payload_text

    name = "sheets_history_checkpoint_versions"
    schema = ENTITY_SCHEMAS[name]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(payload())
    assert schema["properties"]["head_bson"] == {"bsonType": "binData"}
    assert schema["properties"]["job_bson"] == {"bsonType": "binData"}
    assert schema["properties"]["reason"]["enum"] == ["expired_question_cursor"]
    root = Path(__file__).resolve().parents[2] / "infra/mongo"
    assert (root / "schemas" / (name + ".json")).read_text() == _payload_text(name)
    indexes = json.loads((root / "indexes" / (name + ".json")).read_text())
    assert indexes == [
        {
            "keys": {
                "acquisition_id": 1,
                "generation": 1,
                "pass_number": 1,
                "checkpoint_revision": 1,
            },
            "options": {"name": "uniq_sheets_history_checkpoint_version", "unique": True},
        }
    ]
