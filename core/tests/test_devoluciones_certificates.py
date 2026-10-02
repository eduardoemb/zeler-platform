from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from zeler_platform_core.devoluciones_certificates import (
    CoverageUnavailableError,
    certificate_identity,
    make_certificate,
    select_coverage,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def day(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


def certificate(start: datetime, end: datetime, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        seller_id="seller",
        kind="joint_snapshot",
        source_identity=start.isoformat(),
        source_fingerprint="source",
        acquisition_fingerprint="acquired",
        date_from=start,
        date_to=end,
        acquired_at=NOW,
        expected_count=2,
        current_membership_hash="members",
        current_read_model_fingerprint="facts",
        coverage_epoch=1,
        now=NOW,
    )
    values.update(changes)
    return make_certificate(**values)


def test_disjoint_periods_remain_independent_and_gap_is_not_coverage() -> None:
    june = certificate(day(6), day(6, 11))
    august = certificate(day(8, 8), day(9, 7))
    assert select_coverage([august, june], "seller", day(6), day(6, 11), NOW) == (june,)
    assert select_coverage([june, august], "seller", day(8, 8), day(9, 7), NOW) == (august,)
    with pytest.raises(CoverageUnavailableError):
        select_coverage([june, august], "seller", day(6), day(9, 7), NOW)


def test_adjacent_and_overlapping_proofs_are_selected_deterministically() -> None:
    first = certificate(day(6), day(6, 11))
    overlap = certificate(day(6, 5), day(6, 15))
    last = certificate(day(6, 15), day(6, 20))
    assert select_coverage([last, overlap, first], "seller", day(6), day(6, 20), NOW) == (
        first,
        overlap,
        last,
    )
    assert select_coverage([first, overlap], "seller", day(6, 5), day(6, 15), NOW) == (overlap,)


@pytest.mark.parametrize(
    "change",
    [
        {"seller_id": "foreign"},
        {"state": "stale"},
        {"valid_until": NOW},
        {"needs_reacquisition": True},
    ],
)
def test_ineligible_proofs_fail_closed(change: dict[str, Any]) -> None:
    proof = certificate(day(6), day(6, 11)) | change
    with pytest.raises(CoverageUnavailableError):
        select_coverage([proof], "seller", day(6), day(6, 11), NOW)


@pytest.mark.parametrize(
    "start,end",
    [(day(6), day(6)), (day(7), day(6)), (day(6), day(11)), (day(6).replace(tzinfo=None), day(7))],
)
def test_invalid_or_unacquired_bounds_fail_closed(start: datetime, end: datetime) -> None:
    with pytest.raises((CoverageUnavailableError, ValueError)):
        select_coverage([certificate(day(6), day(7))], "seller", start, end, NOW)


def test_identity_is_typed_seller_scoped_and_acquisition_fields_are_separate() -> None:
    proof = certificate(day(6), day(7))
    assert proof["_id"] == certificate_identity("seller", "joint_snapshot", day(6).isoformat())
    assert proof["_id"] != certificate_identity("seller", "quota_run", day(6).isoformat())
    assert proof["_id"] != certificate_identity("foreign", "joint_snapshot", day(6).isoformat())
    assert proof["acquisition_fingerprint"] == "acquired"
    assert proof["current_read_model_fingerprint"] == "facts"
    assert proof["valid_until"] == NOW + timedelta(minutes=30)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "completed"},
        {"source_identity": ""},
        {"source_fingerprint": None},
        {"date_to": day(6)},
        {"date_to": day(11)},
        {"expected_count": -1},
        {"acquisition_fingerprint": ""},
    ],
)
def test_publication_rejects_invalid_evidence(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        certificate(day(6), day(7), **changes)


def test_legacy_kind_does_not_invent_source_fingerprint() -> None:
    proof = certificate(day(6), day(7), kind="legacy_joint_snapshot", source_fingerprint=None)
    assert proof["source_fingerprint"] is None
    assert proof["kind"] == "legacy_joint_snapshot"


def test_certificate_export_requires_strict_typed_fields_and_compatible_fence() -> None:
    from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS

    schema = ENTITY_SCHEMAS["sheets_devoluciones_certificates"]
    assert schema["additionalProperties"] is False
    assert set(certificate(day(6), day(7))) == set(schema["required"])
    assert schema["properties"]["kind"]["enum"] == [
        "quota_run",
        "joint_snapshot",
        "legacy_joint_snapshot",
    ]
    operation = ENTITY_SCHEMAS["sheets_devoluciones_operations"]
    assert operation["properties"]["coverage_mode"]["enum"] == ["legacy", "active"]
    assert "coverage_mode" not in operation["required"]


def test_completed_run_alone_is_not_acquisition_evidence() -> None:
    from zeler_platform_core.devoluciones_certificates import quota_provenance

    with pytest.raises(CoverageUnavailableError):
        quota_provenance({"_id": "run", "seller_id": "seller", "state": "completed"}, [])


def test_quota_provenance_requires_bound_complete_contiguous_windows() -> None:
    from zeler_platform_core.devoluciones_certificates import quota_provenance
    from zeler_platform_core.devoluciones_runs import RunBinding, partition_windows

    binding = RunBinding(
        "auth", "cohort", "seller", "devoluciones", day(6), day(6, 12), "v1", {"worker": "release"}
    )
    run = dict(
        _id=binding.run_id,
        authorization_id="auth",
        cohort_id="cohort",
        seller_id="seller",
        scope="devoluciones",
        start=day(6),
        end=day(6, 12),
        partition_version="v1",
        release_fingerprints={"worker": "release"},
        state="completed",
        window_count=2,
    )
    windows = [
        dict(
            run_id=binding.run_id,
            index=w.index,
            start=w.start,
            end=w.end,
            state="completed",
            expected_count=1,
            persisted_count=1,
            complete_count=1,
            missing_count=0,
            source_fingerprint=f"source{w.index}",
            read_model_fingerprint=f"facts{w.index}",
        )
        for w in partition_windows(binding)
    ]
    proof = quota_provenance(run, windows)
    assert proof["expected_count"] == 2
    assert len(proof["acquisition_fingerprint"]) == 64
    for broken in [
        windows[:1],
        [windows[0], windows[1] | {"run_id": "foreign"}],
        [windows[0], windows[1] | {"state": "prepared"}],
    ]:
        with pytest.raises(CoverageUnavailableError):
            quota_provenance(run, broken)
    with pytest.raises(CoverageUnavailableError):
        quota_provenance(run | {"seller_id": "foreign"}, windows)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"revision": 0},
        {"coverage_epoch": -1},
        {"acquired_at": NOW + timedelta(days=1)},
        {"source_fingerprint": None},
        {"expected_count": -1},
        {"certified_count": -1},
    ],
)
def test_malformed_persisted_documents_cannot_certify(changes: dict[str, Any]) -> None:
    with pytest.raises(CoverageUnavailableError):
        select_coverage([certificate(day(6), day(7)) | changes], "seller", day(6), day(7), NOW)


def test_missing_field_and_nondate_input_fail_closed() -> None:
    proof = certificate(day(6), day(7))
    del proof["revision"]
    with pytest.raises(CoverageUnavailableError):
        select_coverage([proof], "seller", day(6), day(7), NOW)
    with pytest.raises(CoverageUnavailableError):
        select_coverage([], "seller", cast("Any", "bad"), day(7), NOW)


def test_schema_export_and_application_preserve_cross_field_bounds() -> None:
    from infra.mongo.apply_validators import _desired_validator

    from zeler_platform_core.cli.export_schemas import ENTITY_SCHEMAS, _validator_payload

    payload = _validator_payload(ENTITY_SCHEMAS["sheets_devoluciones_certificates"])
    assert payload["$expr"] == {
        "$and": [
            {"$lt": ["$date_from", "$date_to"]},
            {"$lte": ["$date_to", "$acquired_at"]},
            {"$lte": ["$acquired_at", "$validated_at"]},
        ]
    }
    assert _desired_validator(payload)["$expr"] == payload["$expr"]


def test_claim_dependency_index_is_seller_scoped() -> None:
    import json
    from pathlib import Path

    indexes = json.loads(Path("infra/mongo/indexes/claims.json").read_text())
    assert any(
        list(index["keys"]) == ["seller_id", "order_id", "type", "date_created"]
        for index in indexes
    )


def test_capacity_is_unknown_without_measurement_and_honest_on_overload() -> None:
    from zeler_platform_core.devoluciones_certificates import renewal_capacity

    assert renewal_capacity(2, None)["status"] == "unknown"
    measured = {"slowest_seconds": 1.0, "observed_interval_seconds": 900.0}
    assert renewal_capacity(20, measured) == {
        "status": "sufficient",
        "sustainable_batch": 20,
        "revisit_seconds": 990.0,
    }
    assert renewal_capacity(21, measured)["status"] == "degraded"
    assert (
        renewal_capacity(2, {"slowest_seconds": 1, "observed_interval_seconds": 5})["status"]
        == "unknown"
    )
