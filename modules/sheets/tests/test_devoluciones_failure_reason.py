"""A DEVOLUCIONES window failure names the check that refused it.

Production, 2026-10-13: the pilot's year window 2026-05-12 to 05-22 failed
twice with ``DevolucionesReadModelVerificationError`` and nothing else. That
error is raised by about 35 checks (keyset, scope, identity, orders, order
lines, fingerprints...), and neither the log nor the run said which one.
Every raise now carries a stable ``reason`` code: no identities, amounts or
source text.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from zeler_sheets import devoluciones_reconciliation as reconciliation
from zeler_sheets.claim_projection import build_claim_projection
from zeler_sheets.devoluciones_reconciliation import (
    DevolucionesReadModelVerificationError,
    devoluciones_failure_reason,
    devoluciones_read_model_fingerprint,
)

SELLER = "82453304"
REASON = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
MODULE = Path(reconciliation.__file__)


def _claim() -> dict[str, Any]:
    return {
        "id": "5500001",
        "claim_version": 1,
        "date_created": "2026-05-14T10:00:00.000Z",
        "last_updated": "2026-05-14T10:00:00.000Z",
        "order_id": "2000001",
        "item_id": "MLM1",
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "players": [
            {"user_id": int(SELLER), "role": "respondent", "type": "seller"},
            {"user_id": 90001, "role": "complainant", "type": "buyer"},
        ],
        "related_entities": [{"type": "return", "id": "RETURN-5500001"}],
    }


def _returns() -> dict[str, Any]:
    return {
        "id": "RETURN-5500001",
        "status": "delivered",
        "subtype": "return_total",
        "last_updated": "2026-05-14T10:00:00.000Z",
        "orders": [
            {
                "order_id": "2000001",
                "item_id": "MLM1",
                "context_type": "total",
                "return_quantity": "1.0",
                "total_quantity": 1,
            }
        ],
    }


def _order(*lines: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": 2000001,
        "seller": {"id": int(SELLER)},
        "buyer": {"id": 90001},
        "status": "paid",
        "date_created": "2026-05-10T10:00:00.000Z",
        "last_updated": "2026-05-10T10:00:00.000Z",
        "items": list(lines)
        or [{"item": {"id": "MLM1", "seller_sku": "SKU-1", "title": "T"}, "quantity": 1}],
    }


def _projection() -> dict[str, Any]:
    return build_claim_projection(
        seller_id=SELLER, claim=_claim(), returns=_returns(), order=_order()
    )


def _reason(claims: list[dict[str, Any]], orders: list[dict[str, Any]]) -> str:
    with pytest.raises(DevolucionesReadModelVerificationError) as raised:
        devoluciones_read_model_fingerprint(seller_id=SELLER, claims=claims, orders=orders)
    assert REASON.match(raised.value.reason)
    return raised.value.reason


def test_every_verification_raise_names_a_reason() -> None:
    tree = ast.parse(MODULE.read_text())
    raises = [
        node.exc
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "DevolucionesReadModelVerificationError"
    ]

    assert len(raises) >= 30
    unnamed = [call.lineno for call in raises if "reason" not in {kw.arg for kw in call.keywords}]
    assert unnamed == []


def test_a_verification_error_cannot_be_raised_without_a_reason() -> None:
    with pytest.raises(TypeError):
        DevolucionesReadModelVerificationError("no reason")  # type: ignore[call-arg]
    error = DevolucionesReadModelVerificationError("message", reason="some_check")
    assert error.reason == "some_check"
    assert devoluciones_failure_reason(error) == "some_check"


def test_the_source_proof_names_which_order_check_refused_it() -> None:
    line = {"item": {"id": "MLM1", "seller_sku": "SKU-1", "title": "T"}, "quantity": 1}
    other = {"item": {"id": "MLM2", "seller_sku": "SKU-2", "title": "T"}, "quantity": 1}
    claims = [_projection()]

    assert _reason(claims, []) == "source_order_missing"
    assert _reason(claims, [_order(line, line)]) == "source_order_line_ambiguous"
    assert _reason(claims, [_order(other)]) == "source_order_line_missing"
    assert _reason(claims, [{**_order(), "items": None}]) == "source_order_items_missing"
    assert _reason(claims, [{**_order(), "seller": {"id": 1}}]) == "source_order_seller_mismatch"
    assert _reason(claims, [_order(), _order()]) == "source_orders_duplicated"
    assert (
        _reason(claims, [_order({**line, "quantity": 0})]) == "source_order_line_quantity_invalid"
    )


def test_the_source_proof_names_which_claim_check_refused_it() -> None:
    order = [_order()]

    assert _reason([{**_projection(), "seller_id": "1"}], order) == "source_claim_seller_mismatch"
    assert _reason([{**_projection(), "claim_version": None}], order) == (
        "source_claim_version_missing"
    )
    assert _reason([{**_projection(), "productive": None}], order) == (
        "source_claim_productive_missing"
    )
    assert _reason([{**_projection(), "returned_quantity": 0}], order) == (
        "source_claim_quantity_invalid"
    )
    assert _reason([{**_projection(), "productive": False}], order) == (
        "source_claim_quantity_unexpected"
    )


def test_a_missing_field_names_the_field_not_its_value() -> None:
    order = [_order()]

    assert _reason([{**_projection(), "return_subtype": None}], order) == "return_subtype_required"
    assert _reason([{**_projection(), "stage": " "}], order) == "claim_stage_required"
    assert _reason([{**_projection(), "last_updated": "2026-05-14"}], order) == (
        "claim_last_updated_not_datetime"
    )


def _revalidated(**changes: Any) -> SimpleNamespace:
    snapshot = SimpleNamespace(
        source_fingerprint="source",
        read_model_fingerprint="read-model",
        inventory=SimpleNamespace(fingerprint="inventory"),
        exclusion_fingerprint="exclusions",
        expected_claim_ids=frozenset({"1"}),
        counters={"excluded_outside_requested_range": 0},
    )
    current = SimpleNamespace(**{**vars(snapshot), **changes})
    return SimpleNamespace(snapshot=snapshot, current=current)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"inventory": SimpleNamespace(fingerprint="other")}, "revalidation_inventory_changed"),
        ({"exclusion_fingerprint": "other"}, "revalidation_exclusions_changed"),
        ({"expected_claim_ids": frozenset({"2"})}, "revalidation_claims_changed"),
        ({"read_model_fingerprint": "other"}, "revalidation_read_model_changed"),
        ({"counters": {"excluded_outside_requested_range": 1}}, "revalidation_counters_changed"),
        ({"source_fingerprint": "other"}, "revalidation_source_changed"),
        ({}, None),
    ],
)
def test_a_revalidation_names_what_the_source_changed(
    changes: dict[str, Any], reason: str | None
) -> None:
    pair = _revalidated(**changes)

    assert reconciliation._revalidation_change(current=pair.current, snapshot=pair.snapshot) == (
        reason
    )


def test_a_publication_age_names_its_direction() -> None:
    snapshot = SimpleNamespace(captured_at=datetime(2026, 5, 22, 3, 0, tzinfo=UTC))

    with pytest.raises(DevolucionesReadModelVerificationError) as late:
        reconciliation.require_snapshot_publication_age(
            snapshot=snapshot,  # type: ignore[arg-type]
            current_time=datetime(2026, 5, 22, 3, 2, 31, tzinfo=UTC),
        )
    with pytest.raises(DevolucionesReadModelVerificationError) as early:
        reconciliation.require_snapshot_publication_age(
            snapshot=snapshot,  # type: ignore[arg-type]
            current_time=datetime(2026, 5, 22, 2, 59, tzinfo=UTC),
        )

    assert late.value.reason == "snapshot_publication_too_old"
    assert early.value.reason == "snapshot_publication_before_capture"


def test_a_source_failure_reason_is_its_bounded_stage_and_family() -> None:
    request = httpx.Request("GET", "https://gateway.invalid/claims/5500001")
    response = httpx.Response(403, request=request)
    refused = reconciliation._tag_private_focused_devoluciones_failure(
        httpx.HTTPStatusError("refused 5500001", request=request, response=response),
        reconciliation._FocusedDevolucionesFailure.SOURCE,
        source_stage=reconciliation._FocusedSourceStage.CLAIM_DETAIL,
    )

    assert devoluciones_failure_reason(refused) == "claim_detail_client_other"
    assert devoluciones_failure_reason(RuntimeError("payload 5500001")) == "source_failure"
