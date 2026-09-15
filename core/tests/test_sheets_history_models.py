from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from bson import BSON
from bson.codec_options import CodecOptions
from pydantic import ValidationError

from zeler_platform_core.models import (
    SheetsHistoryAcquisition,
    SheetsHistoryOrderRange,
    SheetsHistoryReceipt,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def range_document(**changes: Any) -> dict[str, Any]:
    return {
        "_id": "range-storage-id",
        "acquisition_id": "head",
        "seller_id": "82453304",
        "generation": 1,
        "pass_number": 1,
        "node_id": "root",
        "root_id": "root",
        "date_from": NOW - timedelta(days=31),
        "date_to": NOW,
        **changes,
    }


@pytest.mark.parametrize("state", ["pending", "split", "enumerated"])
def test_order_range_accepts_structural_lifecycle(state: str) -> None:
    model = SheetsHistoryOrderRange.model_validate(
        range_document(state=state, source_total=10001 if state == "split" else 0)
    )
    assert model.date_to == NOW and model.next_offset == 0
    assert SheetsHistoryOrderRange.model_validate(model.model_dump(by_alias=True)) == model


@pytest.mark.parametrize(
    "changes",
    [
        {"next_offset": True},
        {"source_total": -1},
        {"generation": False},
        {"depth": 13},
        {"depth": 1},
        {"parent_id": "parent"},
        {"node_id": "not-root"},
        {"state": "complete"},
        {"extra": 1},
        {"date_from": NOW.replace(tzinfo=None)},
        {"date_from": NOW},
        {"date_from": NOW - timedelta(days=91)},
        {"next_offset": 1},
        {"state": "enumerated"},
        {"state": "split"},
        {"state": "enumerated", "source_total": 2, "next_offset": 1},
        {"state": "split", "source_total": 2, "next_offset": 1},
        {"source_total": 1, "next_offset": 2},
    ],
)
def test_order_range_rejects_invalid_contract(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SheetsHistoryOrderRange.model_validate(range_document(**changes))


def test_order_range_normalizes_child_dates_and_preserves_partial_offset() -> None:
    offset = timezone(timedelta(hours=-6))
    model = SheetsHistoryOrderRange.model_validate(
        range_document(
            node_id="child",
            parent_id="root",
            depth=1,
            source_total=5,
            next_offset=2,
            date_to=NOW.astimezone(offset),
        )
    )
    assert model.date_to.tzinfo is UTC
    assert model.next_offset == 2 and model.parent_id == "root"


def head(**changes: Any) -> dict[str, Any]:
    return {
        "_id": "head",
        "seller_id": "82453304",
        "read_model": "orders",
        "plan_id": "plan",
        "scope_id": "orders:20260815:20260915",
        "job_id": "job",
        "date_from": NOW - timedelta(days=31),
        "date_to": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        **changes,
    }


def test_initial_head_keeps_unknown_total_and_alias() -> None:
    model = SheetsHistoryAcquisition.model_validate(head())
    assert model.source_total is None
    assert model.phase == "discover"
    assert model.model_dump(by_alias=True)["_id"] == "head"
    assert model.generation == model.pass_number == 1
    assert model.discovered_count == model.fetched_count == model.published_count == 0


@pytest.mark.parametrize("count", [0, 3])
def test_completed_question_scan_preserves_valid_partition(count: int) -> None:
    model = SheetsHistoryAcquisition.model_validate(
        head(
            read_model="questions",
            scope_id="seller_scan",
            date_from=NOW - timedelta(days=365),
            phase="completed",
            source_total=10 if count else 0,
            discovered_count=10 if count else 0,
            fetched_count=count,
            published_count=count,
            publish_after="receipt" if count else None,
            observed_from=NOW,
            observed_until=NOW + timedelta(minutes=1),
        )
    )
    assert model.published_count == count
    assert model.discovered_count >= model.fetched_count


def test_bson_offsets_and_other_aware_offsets_normalize_to_utc() -> None:
    payload = head(observed_from=NOW, observed_until=NOW)
    decoded = BSON.encode(payload).decode(codec_options=CodecOptions(tz_aware=True))
    assert decoded["date_from"].tzinfo != UTC
    decoded["created_at"] = NOW.astimezone(timezone(timedelta(hours=-6)))
    model = SheetsHistoryAcquisition.model_validate(decoded)
    for field in (
        "date_from",
        "date_to",
        "created_at",
        "updated_at",
        "observed_from",
        "observed_until",
    ):
        value = getattr(model, field)
        assert value.tzinfo is UTC
    assert model.created_at == NOW


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "generation",
        "pass_number",
        "checkpoint_revision",
        "page_sequence",
        "source_total",
        "discovered_count",
        "fetched_count",
        "published_count",
        "drift_restarts",
    ],
)
@pytest.mark.parametrize("invalid", [True, -1, 1.5, "1"])
def test_counters_reject_non_integer_or_negative_values(field: str, invalid: Any) -> None:
    with pytest.raises(ValidationError):
        SheetsHistoryAcquisition.model_validate(head(**{field: invalid}))


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"generation": 0},
        {"pass_number": 0},
        {"drift_restarts": 4},
        {"seller_id": 82453304},
        {"seller_id": "seller"},
        {"seller_id": "٨٢٤٥٣٣٠٤"},
        {"_id": " "},
        {"plan_id": ""},
        {"job_id": False},
        {"scope_id": "seller_scan"},
        {"scope_id": "questions:20260815:20260915"},
        {"read_model": "questions"},
        {"read_model": "items"},
        {"phase": "failed"},
        {"next_cursor": "offset"},
        {"next_cursor": True},
        {"next_cursor": -1},
        {"read_model": "questions", "scope_id": "seller_scan", "next_cursor": 1},
        {"read_model": "questions", "scope_id": "seller_scan", "next_cursor": " "},
        {"date_from": NOW},
        {"date_from": NOW - timedelta(days=90, seconds=1)},
        {"updated_at": NOW - timedelta(seconds=1)},
        {"observed_from": NOW},
        {"observed_from": NOW, "observed_until": NOW - timedelta(seconds=1)},
        {"fetched_count": 1},
        {"discovered_count": 1, "published_count": 1, "publish_after": "receipt"},
        {"publish_after": "receipt"},
        {"discovered_count": 1, "fetched_count": 1, "published_count": 1},
        {"unexpected": "value"},
    ],
)
def test_invalid_head_contract_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SheetsHistoryAcquisition.model_validate(head(**changes))


@pytest.mark.parametrize(
    "field", ["date_from", "date_to", "created_at", "updated_at", "observed_from", "observed_until"]
)
def test_all_head_dates_reject_naive_values(field: str) -> None:
    payload = head(observed_from=NOW, observed_until=NOW)
    payload[field] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        SheetsHistoryAcquisition.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_from": None, "observed_until": None},
        {"source_total": None},
        {"next_cursor": 1},
        {"discovered_count": 1, "fetched_count": 1},
    ],
)
def test_completed_head_requires_final_local_bookkeeping(changes: dict[str, Any]) -> None:
    payload = head(phase="completed", source_total=0, observed_from=NOW, observed_until=NOW)
    with pytest.raises(ValidationError):
        SheetsHistoryAcquisition.model_validate({**payload, **changes})


@pytest.mark.parametrize("phase", ["discover", "hydrate", "verify", "publish"])
def test_nonterminal_phases_allow_valid_order_and_scan_cursors(phase: str) -> None:
    order = SheetsHistoryAcquisition.model_validate(
        head(phase=phase, date_from=NOW - timedelta(days=90), next_cursor=50)
    )
    question = SheetsHistoryAcquisition.model_validate(
        head(phase=phase, read_model="questions", scope_id="seller_scan", next_cursor="scan")
    )
    assert order.next_cursor == 50 and question.next_cursor == "scan"


def receipt(**changes: Any) -> dict[str, Any]:
    return {
        "_id": "receipt",
        "acquisition_id": "head",
        "seller_id": "82453304",
        "read_model": "orders",
        "generation": 1,
        "pass_number": 1,
        "page_sequence": 0,
        "kind": "membership",
        "resource_id": "200001",
        "observed_at": NOW,
        **changes,
    }


@pytest.mark.parametrize("read_model", ["orders", "questions"])
def test_membership_needs_no_detail_or_invented_version(read_model: str) -> None:
    model = SheetsHistoryReceipt.model_validate(receipt(read_model=read_model))
    assert model.payload is None and model.source_version is None
    assert model.source_hash is None and model.payload_hash is None
    assert model.resource_id == "200001" and model.acquisition_id == "head"
    assert model.model_dump(by_alias=True)["_id"] == "receipt"
    model.unavailable_fields.append("shipping")
    assert SheetsHistoryReceipt.model_validate(receipt()).unavailable_fields == []


def test_detail_keeps_enriched_payload_distinct_from_source_evidence() -> None:
    payload = {"id": 200001, "shipping": {"id": "300001"}, "tags": ["paid", None]}
    model = SheetsHistoryReceipt.model_validate(
        receipt(
            kind="detail",
            payload=payload,
            payload_hash="a" * 64,
            source_hash="b" * 64,
            source_version="provider-revision-7",
            unavailable_fields=["shipping_cost", "buyer_id"],
        )
    )
    assert model.payload == payload
    assert model.payload_hash != model.source_hash
    assert model.source_version == "provider-revision-7"
    assert model.unavailable_fields == ["shipping_cost", "buyer_id"]
    assert model.observed_at == NOW


@pytest.mark.parametrize("source_version", [None, "revision-2"])
def test_exclusion_preserves_available_provenance(source_version: str | None) -> None:
    model = SheetsHistoryReceipt.model_validate(
        receipt(
            kind="exclusion",
            exclusion_reason="outside_subscribed_intervals",
            source_version=source_version,
            source_hash="c" * 64,
        )
    )
    assert model.payload is None and model.payload_hash is None
    assert model.exclusion_reason == "outside_subscribed_intervals"
    assert model.source_version == source_version and model.source_hash == "c" * 64


def test_receipt_bson_observation_normalizes_without_renewing_it() -> None:
    decoded = BSON.encode(receipt()).decode(codec_options=CodecOptions(tz_aware=True))
    model = SheetsHistoryReceipt.model_validate(decoded)
    assert model.observed_at == NOW and model.observed_at.tzinfo is UTC


@pytest.mark.parametrize(
    "changes",
    [
        {"_id": " "},
        {"acquisition_id": ""},
        {"seller_id": 82453304},
        {"seller_id": "seller"},
        {"read_model": "shipments"},
        {"resource_id": ""},
        {"schema_version": True},
        {"schema_version": 2},
        {"generation": 0},
        {"generation": True},
        {"pass_number": -1},
        {"pass_number": "1"},
        {"page_sequence": -1},
        {"page_sequence": 1.5},
        {"observed_at": NOW.replace(tzinfo=None)},
        {"source_version": " "},
        {"source_version": 1},
        {"source_hash": "a" * 63},
        {"source_hash": "G" * 64},
        {"kind": "unknown"},
        {"payload": {"id": 200001}},
        {"payload_hash": "a" * 64},
        {"unavailable_fields": ["shipping"]},
        {"exclusion_reason": "absent"},
        {"kind": "detail"},
        {"kind": "detail", "payload": {}, "payload_hash": "a" * 64},
        {"kind": "detail", "payload": {"id": 200001}},
        {"kind": "exclusion"},
        {"kind": "exclusion", "exclusion_reason": " "},
        {"kind": "exclusion", "exclusion_reason": "absent", "payload_hash": "a" * 64},
        {"unexpected": "field"},
    ],
)
def test_receipt_rejects_invalid_identity_version_and_kind(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SheetsHistoryReceipt.model_validate(receipt(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"payload_hash": "Z" * 64},
        {"payload": {"invalid": object()}},
        {"payload": []},
        {"unavailable_fields": ["shipping", "shipping"]},
        {"unavailable_fields": [""]},
        {"exclusion_reason": "absent"},
    ],
)
def test_detail_rejects_invalid_payload_or_unavailable_fields(changes: dict[str, Any]) -> None:
    payload = receipt(kind="detail", payload={"id": 200001}, payload_hash="a" * 64)
    with pytest.raises(ValidationError):
        SheetsHistoryReceipt.model_validate({**payload, **changes})


def test_versionless_detail_and_versioned_membership_remain_distinct() -> None:
    detail = SheetsHistoryReceipt.model_validate(
        receipt(kind="detail", payload={"id": 200001}, payload_hash="d" * 64)
    )
    membership = SheetsHistoryReceipt.model_validate(
        receipt(source_version="revision-3", source_hash="e" * 64)
    )
    assert detail.source_version is None and detail.source_hash is None
    assert detail.payload == {"id": 200001}
    assert membership.payload is None and membership.payload_hash is None
    assert membership.source_version == "revision-3" and membership.source_hash == "e" * 64


@pytest.mark.parametrize("missing", ["generation", "pass_number", "page_sequence", "observed_at"])
def test_receipt_requires_acquisition_position_and_original_observation(missing: str) -> None:
    payload = receipt()
    del payload[missing]
    with pytest.raises(ValidationError):
        SheetsHistoryReceipt.model_validate(payload)


def test_optional_source_payload_preserves_legacy_and_source_bound_shapes() -> None:
    legacy = SheetsHistoryReceipt.model_validate(receipt(source_hash="a" * 64))
    assert legacy.source_payload is None
    source = {"id": 200001, "seller": {"id": 82453304}}
    model = SheetsHistoryReceipt.model_validate(
        receipt(source_payload=source, source_hash="b" * 64)
    )
    assert model.source_payload == source and model.payload is None


@pytest.mark.parametrize("source", [{}, [], {"id": 200001}])
def test_source_payload_requires_nonempty_object_and_hash(source: Any) -> None:
    with pytest.raises(ValidationError):
        SheetsHistoryReceipt.model_validate(receipt(source_payload=source))
