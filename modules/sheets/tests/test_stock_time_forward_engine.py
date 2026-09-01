from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import signature
from typing import Any

import pytest

import zeler_sheets
from zeler_sheets import _stock_time_forward_engine as engine
from zeler_sheets import source_gated_read_model_writers as planner

START, END = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)


def metric(target: str, value: int, **extra: Any) -> dict[str, Any]:
    return {
        "_id": target,
        "seller_id": "82453304",
        "date_from": START,
        "date_to": END,
        "value": value,
        **extra,
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
    return engine._seal_forward_plan(
        seller_id=seller,
        date_from=start,
        date_to=end,
        source_inventory=[{"_id": source}],
        action_plan=plan if plan is not None else action_plan(source=source),
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
    assert first.operation_id == "e0d8a44491f8e18db199c281bb38a2333f470dd19fb9fd3ef795be46466e7a15"
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
    assert "marker_document" not in signature(engine._seal_forward_plan).parameters
    assert not hasattr(first, "_marker_document")
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
        ("82453304", "2026-06-01", END, "INVALID_UTC_INTERVAL"),
        ("82453304", START, object(), "INVALID_UTC_INTERVAL"),
    ],
)
def test_seal_rejects_invalid_seller_and_half_open_utc_bounds(
    seller: str, start: Any, end: Any, code: str
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


def test_materializes_metric_actions_with_operation_owned_revisions() -> None:
    sealed = seal()
    mutations = sealed._mutations
    metric_mutations = mutations[:-1]

    assert [(item.sequence, item._target_id, item.action) for item in metric_mutations] == [
        (1, "delete", "delete"),
        (2, "insert", "insert"),
        (3, "replace", "replace"),
    ]
    assert [doc["_id"] for doc in sealed._expected_metric_documents] == [
        "insert",
        "replace",
        "same",
    ]
    final = {doc["_id"]: doc for doc in sealed._expected_metric_documents}
    assert final["same"] == metric("same", 1)
    assert "revision" not in final["same"]
    for target in ("insert", "replace"):
        mutation = next(item for item in metric_mutations if item._target_id == target)
        assert final[target]["revision"] == mutation.expected_forward_revision
        assert mutation._document == final[target]
    overwrite_plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("insert", 2, revision="caller-revision")],
        existing_target_rows=[],
    )
    overwritten = seal(plan=overwrite_plan)._expected_metric_documents[0]
    assert overwritten["revision"] != "caller-revision"
    deleted = metric_mutations[0]
    assert deleted._document is None
    assert (
        engine._operation_revision(
            sealed.operation_id, deleted.target_collection, "delete", "delete"
        )
        == deleted.expected_forward_revision
    )
    assert len({item.expected_forward_revision for item in mutations}) == len(mutations)
    assert seal()._mutations == mutations
    assert (
        len(
            {
                engine._operation_revision(sealed.operation_id, "collection", "id", action)
                for action in ("insert", "replace", "delete")
            }
        )
        == 3
    )


def test_noop_preserves_exact_existing_revision_and_nested_document() -> None:
    same = metric("same", 1, revision="existing", nested={"values": [1, 2]})
    plan = planner._plan_stock_time_actions(
        source_inventory=[{"_id": "source"}],
        planned_documents=[metric("same", 1, nested={"values": [1, 2]})],
        existing_target_rows=[same],
    )
    sealed = seal(plan=plan)

    assert len(sealed._mutations) == 1  # Marker only.
    assert planner._canonical_bson_bytes(sealed._expected_metric_documents[0]) == (
        planner._canonical_bson_bytes(same)
    )
    with pytest.raises(TypeError):
        sealed._expected_metric_documents[0]["nested"]["values"][0] = 9


@pytest.mark.parametrize("old_marker", [None, marker()])
def test_marker_is_canonical_final_mutation_with_exact_counts(
    old_marker: dict[str, Any] | None,
) -> None:
    sealed = seal(old_marker=old_marker)
    desired = sealed._desired_marker
    marker_mutation = sealed._mutations[-1]

    assert set(desired) == {
        "_id",
        "seller_id",
        "read_model",
        "state",
        "date_from",
        "fresh_until",
        "reconciled_until",
        "last_event_synced_at",
        "updated_at",
        "source",
        "coverage_basis",
        "revision",
        "proof_fingerprint",
        "schema_version",
    }
    assert desired == {
        "_id": "82453304:stock_time_metrics",
        "seller_id": "82453304",
        "read_model": "stock_time_metrics",
        "state": "reconciled",
        "date_from": START,
        "fresh_until": END,
        "reconciled_until": END,
        "last_event_synced_at": START,
        "updated_at": END,
        "source": "zelerdata_read_model_reconcile",
        "coverage_basis": "legacy_imported",
        "revision": marker_mutation.expected_forward_revision,
        "proof_fingerprint": sealed.expected_metric_fingerprint,
        "schema_version": 1,
    }
    assert desired["proof_fingerprint"] == engine._metric_proof_fingerprint(
        sealed._expected_metric_documents
    )
    assert desired["proof_fingerprint"] != engine._metric_proof_fingerprint(
        (*sealed._expected_metric_documents, desired)
    )
    assert marker_mutation.sequence == len(sealed._mutations)
    assert marker_mutation._document == desired
    assert marker_mutation.action == ("replace" if old_marker else "insert")
    assert marker_mutation._preimage == old_marker
    assert sealed.ledger_counts == engine._ForwardLedgerCounts(
        planned_insert_count=1 + (old_marker is None),
        planned_update_count=1 + (old_marker is not None),
        planned_delete_count=1,
        planned_preimage_count=4,
    )


def test_mutation_preimages_are_exact_coupled_and_deeply_frozen() -> None:
    sealed = seal(old_marker=marker(nested={"value": [1]}))

    for mutation in sealed._mutations:
        assert mutation.preimage_kind == (
            "absent" if mutation.action == "insert" else "exact_document"
        )
        if mutation.action == "insert":
            assert mutation._preimage is None
        else:
            assert mutation._preimage is not None
        assert mutation.preimage_fingerprint == engine._preimage_fingerprint(mutation._preimage)
    assert planner._canonical_bson_bytes(sealed._mutations[-1]._preimage) == (
        planner._canonical_bson_bytes(marker(nested={"value": [1]}))
    )
    with pytest.raises(TypeError):
        sealed._mutations[-1]._preimage["nested"]["value"][0] = 2
    with pytest.raises(FrozenInstanceError):
        sealed._mutations[0].sequence = 99


def test_forward_contract_remains_private_with_bounded_errors() -> None:
    assert not hasattr(zeler_sheets, "_seal_forward_plan")
    assert not hasattr(zeler_sheets, "_ForwardMutation")
    with pytest.raises(ValueError, match="unknown forward-engine error code"):
        engine._ForwardEngineError("NOT_A_SEALING_ERROR")
