from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

import zeler_sheets
from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner

START, END = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)


def metric(target: str, value: int) -> dict[str, Any]:
    return {
        "_id": target,
        "seller_id": "82453304",
        "date_from": START,
        "date_to": END,
        "value": value,
    }


def action_plan(*, source: str = "source", value: int = 2) -> Any:
    return planner._plan_stock_time_actions(
        source_inventory=[{"_id": source}],
        planned_documents=[metric("insert", value), metric("same", 1), metric("replace", value)],
        existing_target_rows=[metric("delete", 1), metric("same", 1), metric("replace", 1)],
    )


def marker(**extra: Any) -> dict[str, Any]:
    return {
        "_id": "82453304:stock_time_metrics",
        "seller_id": "82453304",
        "read_model": "stock_time_metrics",
        "state": "stale",
        "fresh_until": START,
        "updated_at": START,
        "schema_version": 1,
        **extra,
    }


def seal(
    *,
    plan: Any | None = None,
    source: str = "source",
    old_marker: dict[str, Any] | None = None,
    seller: str = "82453304",
    start: datetime = START,
    end: datetime = END,
) -> Any:
    desired = {
        "_id": f"{seller}:stock_time_metrics",
        "seller_id": seller,
        "read_model": "stock_time_metrics",
        "state": "reconciled",
        "fresh_until": end,
        "date_from": start,
        "reconciled_until": end,
        "updated_at": end,
        "schema_version": 1,
    }
    return engine._seal_forward_plan(
        seller_id=seller,
        date_from=start,
        date_to=end,
        source_inventory=[{"_id": source}],
        action_plan=plan if plan is not None else action_plan(source=source),
        marker_document=desired,
        marker_preimage=old_marker,
    )


EMPTY_PLAN = planner._plan_stock_time_actions(
    source_inventory=[{"_id": "source"}], planned_documents=[], existing_target_rows=[]
)


def test_seal_is_permutation_stable_and_binds_all_material() -> None:
    first = seal()
    base = action_plan()
    permuted = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[base.actions[i]._document for i in (3, 2, 1)],
        existing_target_rows=[base.actions[i]._preimage for i in (3, 2, 0)],
    )
    assert seal(plan=permuted).operation_id == first.operation_id
    assert first.operation_id == "77bbccdc25c327be7fa3f8b0e0f9f8193256efc90dd5a9976edf7a1ced675553"
    variants = [
        seal(seller="82453305", plan=EMPTY_PLAN),
        seal(start=START + timedelta(days=1), plan=EMPTY_PLAN),
        seal(source="drift", plan=action_plan(source="drift")),
        seal(plan=action_plan(value=3)),
        seal(old_marker=marker(source="drift")),
    ]
    assert all(item.operation_id != first.operation_id for item in variants)
    assert "82453304" not in repr(first)


def test_seal_canonicalizes_marker_action_and_is_frozen() -> None:
    first = seal()
    assert first._marker_action == "insert" and first._marker_preimage is None
    replaced = seal(old_marker=marker())
    assert replaced._marker_action == "replace" and replaced._marker_preimage == marker()
    with pytest.raises(FrozenInstanceError):
        first.__setattr__("operation_id", "changed")


@pytest.mark.parametrize(
    ("seller", "start", "end", "code"),
    [
        (" ", START, END, "INVALID_SELLER"),
        ("82453304", START.replace(tzinfo=None), END, "INVALID_UTC_INTERVAL"),
        (
            "82453304",
            START.replace(tzinfo=timezone(timedelta(hours=1))),
            END,
            "INVALID_UTC_INTERVAL",
        ),
        ("82453304", END, END, "INVALID_UTC_INTERVAL"),
    ],
)
def test_seal_rejects_invalid_seller_and_half_open_utc_bounds(
    seller: str, start: datetime, end: datetime, code: str
) -> None:
    with pytest.raises(engine._ForwardEngineError, match=code):
        seal(seller=seller, start=start, end=end, plan=EMPTY_PLAN)


@pytest.mark.parametrize(
    "field", ["source_fingerprint", "preimage_fingerprint", "plan_fingerprint"]
)
def test_seal_rejects_invalid_sha256(field: str) -> None:
    with pytest.raises(engine._ForwardEngineError, match="INVALID_SHA256"):
        seal(plan=replace(action_plan(), **{field: "not-a-sha"}))


def test_seal_rejects_action_order_identity_and_marker_drift() -> None:
    plan = action_plan()
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, actions=tuple(reversed(plan.actions))))
    bad_identity = replace(plan.actions[0], _target_id="other")
    with pytest.raises(engine._ForwardEngineError, match="ACTION_SCOPE_MISMATCH"):
        seal(plan=replace(plan, actions=(bad_identity, *plan.actions[1:])))
    with pytest.raises(engine._ForwardEngineError, match="ACTION_SCOPE_MISMATCH"):
        seal(old_marker=marker(_id="other"))


@pytest.mark.parametrize(
    ("index", "changes"),
    [
        (1, {"_document": metric("insert", 9)}),
        (2, {"action": "no-op"}),
        (2, {"_preimage": metric("replace", 2)}),
    ],
)
def test_seal_rejects_actions_tampered_without_updating_fingerprints(
    index: int, changes: dict[str, Any]
) -> None:
    plan = action_plan()
    actions = list(plan.actions)
    actions[index] = replace(actions[index], **changes)
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, actions=tuple(actions)))


@pytest.mark.parametrize(
    "field",
    [
        "source_fingerprint",
        "preimage_fingerprint",
        "plan_fingerprint",
        "action_count",
        "insert_count",
        "replace_count",
        "delete_count",
        "no_op_count",
        "preimage_count",
        "estimated_bson_bytes",
        "estimated_json_bytes",
        "estimated_transaction_payload_bytes",
    ],
)
def test_seal_rejects_tampered_planner_metadata(field: str) -> None:
    plan = action_plan()
    value = "0" * 64 if field.endswith("fingerprint") else getattr(plan, field) + 1
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(plan=replace(plan, **{field: value}))


def test_seal_rejects_source_that_does_not_match_the_plan() -> None:
    with pytest.raises(engine._ForwardEngineError, match="INVALID_ACTION"):
        seal(source="drift", plan=action_plan())


def test_forward_contract_remains_private_with_bounded_errors() -> None:
    assert not hasattr(zeler_sheets, "_seal_forward_plan")
    with pytest.raises(ValueError, match="unknown forward-engine error code"):
        engine._ForwardEngineError("NOT_A_SEALING_ERROR")
