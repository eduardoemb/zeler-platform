from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

import zeler_sheets.claim_projection as claim_projection_module
import zeler_sheets.devoluciones_reconciliation as reconciliation_module
from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
from zeler_sheets.claim_projection import (
    ClaimProjectionError,
    ClaimProjectionReason,
    build_claim_projection,
    persist_claim_projection,
    project_claim,
)
from zeler_sheets.devoluciones_reconciliation import (
    ClaimInventoryError,
    DevolucionesReadModelVerificationError,
    InventoryRelevance,
    SourceCallBudgetError,
    SourceCallRecorder,
    claim_inventory_search_params,
    classify_inventory_relevance,
    collect_devoluciones_projections,
    read_devoluciones_claims_keyset,
    read_devoluciones_orders_by_id_keyset,
    revalidate_devoluciones_snapshot,
    verify_claim_inventory,
    verify_devoluciones_read_model,
)

FIXTURES = Path(__file__).parent / "fixtures" / "devoluciones"
START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 10, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _mutable_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_copy(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_mutable_copy(item) for item in value]
    return deepcopy(value)


class ScriptedInventorySource:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = [deepcopy(response) for response in responses]
        self.calls: list[tuple[str, dict[str, str | int]]] = []

    async def search_claims(
        self, *, seller_id: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        self.calls.append((seller_id, dict(params)))
        if not self.responses:
            raise AssertionError("unexpected inventory request")
        return self.responses.pop(0)


def _claim(*, claim_type: str = "returns", item_id: str = "MLA1") -> dict[str, Any]:
    related_entities = [{"type": "return", "id": "RETURN-519988001"}]
    return {
        "id": "519988001",
        "claim_version": 3,
        "last_updated": "2026-06-15T12:05:00.000Z",
        "date_created": "2026-06-15T12:00:00.000Z",
        "order_id": "2001",
        "item_id": item_id,
        "status": "closed",
        "stage": "claim",
        "type": claim_type,
        "players": [
            {"user_id": 82453304, "role": "respondent", "type": "seller"},
            {"user_id": 90001, "role": "complainant", "type": "buyer"},
        ],
        "related_entities": related_entities,
        "claimed_quantity": 99,
    }


def _order(
    *,
    item_id: str = "MLA1",
    seller_id: int = 82453304,
    sku: str = "SKU-1",
    title: str = "Formula-visible title",
) -> dict[str, Any]:
    return {
        "id": 2001,
        "seller": {"id": seller_id},
        "items": [
            {
                "item": {"id": item_id, "seller_sku": sku, "title": title},
                "quantity": 5,
            }
        ],
    }


def _operation() -> DevolucionesOperationContext:
    return DevolucionesOperationContext(
        seller_id="82453304",
        scope="devoluciones",
        operation_id="operation-1",
        attempt_token=uuid4().hex,
        fence=1,
        owns_lease=True,
        source_fingerprint="inventory-v1",
    )


def test_claim_inventory_params_use_paired_utc_date_and_range_contract() -> None:
    params = claim_inventory_search_params(
        seller_id="82453304", start=START, end=END, offset=0, limit=100
    )

    assert params == {
        "players.user_id": "82453304",
        "players.role": "respondent",
        "date_created": "2026-06-01T00:00:00.000+0000",
        "range": (
            "date_created:after:2026-05-31T23:59:59.999+0000,before:2026-07-10T00:00:00.000+0000"
        ),
        "sort": "date_created:asc",
        "offset": 0,
        "limit": 100,
    }


@pytest.mark.asyncio
async def test_stable_two_pass_inventory_is_authoritative_for_old_order_claims() -> None:
    page = _fixture("inventory.json")
    source = ScriptedInventorySource([page, page])

    inventory = await verify_claim_inventory(
        source=source, seller_id="82453304", start=START, end=END
    )

    assert [entry.claim_id for entry in inventory.entries] == ["519988001", "519988002"]
    assert inventory.fingerprint
    assert len(source.calls) == 2
    assert all(call[1]["players.role"] == "respondent" for call in source.calls)
    assert all("order_id" not in call[1] for call in source.calls)


@pytest.mark.parametrize(
    ("page", "expected_private_failure"),
    [
        (
            {"data": [], "paging": {"offset": "0", "limit": 100, "total": 0}},
            reconciliation_module._FocusedDevolucionesFailure.PARSER,
        ),
        (
            {"data": [], "paging": {"offset": 1, "limit": 100, "total": 0}},
            reconciliation_module._FocusedDevolucionesFailure.PARSER,
        ),
        (
            {"data": [], "paging": {"offset": 0, "limit": 101, "total": 0}},
            reconciliation_module._FocusedDevolucionesFailure.PARSER,
        ),
        (
            {"data": [], "paging": {"offset": 0, "limit": 100, "total": 1}},
            reconciliation_module._FocusedDevolucionesFailure.PARSER,
        ),
        (
            {
                "data": [{"id": "1", "last_updated": "a"}],
                "paging": {"offset": 0, "limit": 1, "total": 2},
            },
            reconciliation_module._FocusedDevolucionesFailure.SOURCE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_inventory_rejects_unproven_paging_contract(
    page: dict[str, Any],
    expected_private_failure: reconciliation_module._FocusedDevolucionesFailure,
) -> None:
    source = ScriptedInventorySource([page])

    with pytest.raises(ClaimInventoryError) as exc_info:
        await verify_claim_inventory(source=source, seller_id="82453304", start=START, end=END)

    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is expected_private_failure
    )


@pytest.mark.asyncio
async def test_inventory_rejects_duplicates_total_drift_and_second_pass_drift() -> None:
    duplicate_page = {
        "data": [
            {"id": "1", "last_updated": "a"},
            {"id": "1", "last_updated": "a"},
        ],
        "paging": {"offset": 0, "limit": 100, "total": 2},
    }
    with pytest.raises(ClaimInventoryError, match="duplicate"):
        await verify_claim_inventory(
            source=ScriptedInventorySource([duplicate_page]),
            seller_id="82453304",
            start=START,
            end=END,
        )


@pytest.mark.asyncio
async def test_inventory_rejects_relevance_drift_with_same_identity_and_timestamp() -> None:
    first = _fixture("inventory.json")
    opposite = deepcopy(first)
    first["data"][0].update({"type": "cancel_purchase", "status": "closed"})
    opposite["data"][0].update({"type": "returns", "status": "opened"})

    with pytest.raises(ClaimInventoryError, match="fingerprint"):
        await verify_claim_inventory(
            source=ScriptedInventorySource([first, opposite]),
            seller_id="82453304",
            start=START,
            end=END,
        )

    first = _fixture("inventory.json")
    drifted = deepcopy(first)
    drifted["data"][1]["last_updated"] = "2026-06-16T09:06:00.000Z"
    with pytest.raises(ClaimInventoryError, match="fingerprint"):
        await verify_claim_inventory(
            source=ScriptedInventorySource([first, drifted]),
            seller_id="82453304",
            start=START,
            end=END,
        )


class SplittingInventorySource:
    def __init__(self, original_start: datetime, original_end: datetime) -> None:
        self.original_start = original_start
        self.original_end = original_end
        self.calls: list[dict[str, str | int]] = []

    async def search_claims(
        self, *, seller_id: str, params: dict[str, str | int]
    ) -> dict[str, Any]:
        del seller_id
        self.calls.append(dict(params))
        range_value = str(params["range"])
        is_parent = (
            params["date_created"] == "2026-07-01T00:00:00.000+0000"
            and "before:2026-07-02T00:00:00.000+0000" in range_value
        )
        if is_parent:
            return {"data": [], "paging": {"offset": 0, "limit": 100, "total": 10000}}
        claim_id = "1" if "before:2026-07-01T12:00:00.000+0000" in range_value else "2"
        return {
            "data": [{"id": claim_id, "last_updated": "stable"}],
            "paging": {"offset": 0, "limit": 100, "total": 1},
        }


@pytest.mark.asyncio
async def test_over_cap_inventory_recursively_splits_closed_window() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 2, tzinfo=UTC)
    source = SplittingInventorySource(start, end)

    inventory = await verify_claim_inventory(
        source=source, seller_id="82453304", start=start, end=end
    )

    assert [entry.claim_id for entry in inventory.entries] == ["1", "2"]
    assert len(source.calls) == 6


@pytest.mark.asyncio
async def test_over_cap_unsplittable_window_fails_closed() -> None:
    page = {"data": [], "paging": {"offset": 0, "limit": 100, "total": 10000}}

    with pytest.raises(ClaimInventoryError, match="unsplittable"):
        await verify_claim_inventory(
            source=ScriptedInventorySource([page]),
            seller_id="82453304",
            start=START,
            end=START + timedelta(milliseconds=1),
        )


@pytest.mark.parametrize("claim_type", ["returns", "return", "mediations"])
def test_productive_return_uses_unique_positive_integral_v2_quantity(claim_type: str) -> None:
    projection = build_claim_projection(
        seller_id="82453304",
        claim=_claim(claim_type=claim_type),
        returns=_fixture("return_v2.json"),
        order=_order(),
    )

    assert projection["type"] == "returns"
    assert projection["item_id"] == "MLA1"
    assert projection["order_id"] == "2001"
    assert projection["returned_quantity"] == 2
    assert projection["return_quantity_basis"] == "v2_return_order"
    assert projection["productive"] is True
    assert projection["claim_version"] == 3


@pytest.mark.parametrize("missing_related_entities", [False, True])
def test_productive_mediation_without_related_return_uses_authoritative_v2_order_row(
    missing_related_entities: bool,
) -> None:
    claim = _claim(claim_type="mediations")
    claim["claimed_quantity"] = 99
    claim["returned_quantity"] = 88
    if missing_related_entities:
        claim.pop("related_entities")
    else:
        claim["related_entities"] = []

    projection = build_claim_projection(
        seller_id="82453304",
        claim=claim,
        returns=_fixture("return_v2.json"),
        order=_order(),
    )

    assert projection["type"] == "returns"
    assert projection["order_id"] == "2001"
    assert projection["item_id"] == "MLA1"
    assert projection["returned_quantity"] == 2
    assert projection["return_quantity_basis"] == "v2_return_order"
    assert projection["productive"] is True


def test_verified_low_cost_without_order_row_is_unresolved() -> None:
    with pytest.raises(ClaimProjectionError, match="positive integral v2 return proof"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=_fixture("low_cost.json"),
            order=_order(),
        )


def test_only_positive_integral_v2_proof_can_produce_a_projection_row() -> None:
    with pytest.raises(ClaimProjectionError, match="positive integral v2 return proof"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=_fixture("low_cost.json"),
            order=_order(),
        )


def test_verified_low_cost_null_orders_is_unresolved() -> None:
    with pytest.raises(ClaimProjectionError, match="orders must be a list"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=_fixture("low_cost_orders_null.json"),
            order=_order(),
        )


@pytest.mark.parametrize(
    "returns",
    [
        {**_fixture("return_v2.json"), "orders": None},
        {**_fixture("low_cost.json"), "orders": {"unexpected": "shape"}},
        {key: value for key, value in _fixture("low_cost.json").items() if key != "orders"},
    ],
    ids=("productive-null", "low-cost-non-list", "low-cost-missing"),
)
def test_projection_rejects_unverified_null_or_non_list_orders(
    returns: dict[str, Any],
) -> None:
    with pytest.raises(ClaimProjectionError, match="orders must be a list"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=returns,
            order=_order(),
        )


@pytest.mark.parametrize("return_quantity", [None, 0, -1, "1.5", True])
def test_projection_never_falls_back_from_invalid_return_quantity(return_quantity: Any) -> None:
    returns = _fixture("return_v2.json")
    returns["orders"][0]["return_quantity"] = return_quantity

    with pytest.raises(ClaimProjectionError, match="return_quantity"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=returns,
            order=_order(),
        )


def test_projection_rejects_ambiguous_rows_and_seller_or_order_ownership_mismatch() -> None:
    returns = _fixture("return_v2.json")
    returns["orders"].append(deepcopy(returns["orders"][0]))
    with pytest.raises(ClaimProjectionError, match="unique"):
        build_claim_projection(
            seller_id="82453304", claim=_claim(), returns=returns, order=_order()
        )
    with pytest.raises(ClaimProjectionError, match="respondent"):
        build_claim_projection(
            seller_id="999",
            claim=_claim(),
            returns=_fixture("return_v2.json"),
            order=_order(),
        )
    with pytest.raises(ClaimProjectionError, match="order seller"):
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns=_fixture("return_v2.json"),
            order=_order(seller_id=999),
        )


@pytest.mark.asyncio
async def test_project_claim_borrows_operation_for_guarded_claim_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def guarded_write(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(claim_projection_module, "guarded_devoluciones_write", guarded_write)
    operation = _operation()

    projection = await project_claim(
        db=object(),
        seller_id="82453304",
        claim=_claim(),
        returns=_fixture("return_v2.json"),
        order=_order(),
        operation=operation,
    )

    assert projection["_id"] == "519988001"
    assert captured["operation"] is operation
    assert captured["checkpoint"] == {
        "claim_id": "519988001",
        "claim_version": 3,
        "last_updated": datetime(2026, 6, 15, 12, 5, tzinfo=UTC),
    }


class _WriteResult:
    def __init__(self, *, matched_count: int = 0, upserted_id: str | None = None) -> None:
        self.matched_count = matched_count
        self.upserted_id = upserted_id


class _MonotonicClaimCollection:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = dict(document)
        self.replace_filters: list[dict[str, Any]] = []

    async def update_one(
        self, filter_spec: dict[str, Any], update: dict[str, Any], *, upsert: bool, **_: Any
    ) -> _WriteResult:
        if self.document:
            return _WriteResult()
        self.document = dict(update["$setOnInsert"])
        return _WriteResult(upserted_id=str(filter_spec["_id"]))

    async def replace_one(
        self,
        filter_spec: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool,
        **_: Any,
    ) -> _WriteResult:
        assert upsert is False
        self.replace_filters.append(deepcopy(filter_spec))
        if _matches_projection_filter(self.document, filter_spec):
            self.document = dict(replacement)
            return _WriteResult(matched_count=1)
        return _WriteResult()


class _ProjectionDb:
    def __init__(self, document: dict[str, Any]) -> None:
        self.claims = _MonotonicClaimCollection(document)

    def __getitem__(self, name: str) -> _MonotonicClaimCollection:
        assert name == "claims"
        return self.claims


def _matches_projection_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$and":
            if not all(_matches_projection_filter(document, clause) for clause in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches_projection_filter(document, clause) for clause in expected):
                return False
            continue
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected and (key in document) is not bool(expected["$exists"]):
                return False
            if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                return False
            if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                return False
            continue
        if actual != expected:
            return False
    return True


@pytest.mark.asyncio
async def test_claim_projection_replacement_is_monotonic_for_claim_and_return_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def guarded_write(**kwargs: Any) -> None:
        await kwargs["writer"](None)

    monkeypatch.setattr(claim_projection_module, "guarded_devoluciones_write", guarded_write)
    fresh_claim = {**_claim(), "claim_version": 9, "last_updated": "2026-06-20T12:00:00Z"}
    fresh_returns = {
        **_fixture("return_v2.json"),
        "last_updated": "2026-06-20T12:01:00Z",
    }
    fresh = build_claim_projection(
        seller_id="82453304",
        claim=fresh_claim,
        returns=fresh_returns,
        order=_order(),
    )
    db = _ProjectionDb(fresh)
    stale = build_claim_projection(
        seller_id="82453304",
        claim=_claim(),
        returns=_fixture("return_v2.json"),
        order=_order(),
    )

    await persist_claim_projection(db=db, document=stale, operation=_operation())

    assert db.claims.document["claim_version"] == 9
    assert db.claims.document["last_updated"] == datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    assert db.claims.replace_filters[0]["$and"]

    newer_claim = {
        **_claim(),
        "claim_version": 10,
        "last_updated": "2026-06-21T12:00:00Z",
    }
    newer_returns = {
        **_fixture("return_v2.json"),
        "last_updated": "2026-06-21T12:01:00Z",
    }
    newer = build_claim_projection(
        seller_id="82453304",
        claim=newer_claim,
        returns=newer_returns,
        order=_order(),
    )

    await persist_claim_projection(db=db, document=newer, operation=_operation())

    assert db.claims.document["claim_version"] == 10
    assert db.claims.document["return_last_updated"] == datetime(2026, 6, 21, 12, 1, tzinfo=UTC)


class HydratingSource(ScriptedInventorySource):
    def __init__(self) -> None:
        page = _fixture("inventory.json")
        super().__init__([page, page])
        mediation = _claim(claim_type="mediations")
        mediation["id"] = "519988002"
        mediation["order_id"] = "1999"
        mediation["item_id"] = "MLA2"
        mediation["last_updated"] = "2026-06-16T09:05:00.000Z"
        second_return = _fixture("return_v2.json")
        second_return["id"] = "RETURN-519988002"
        second_return["orders"][0].update({"order_id": "1999", "item_id": "MLA2"})
        self.claims = {"519988001": _claim(), "519988002": mediation}
        self.returns = {
            "519988001": _fixture("return_v2.json"),
            "519988002": second_return,
        }
        self.orders = {"2001": _order(), "1999": _order(item_id="MLA2") | {"id": 1999}}
        self.hydration_calls: list[tuple[str, str]] = []

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.hydration_calls.append(("claim", claim_id))
        return deepcopy(self.claims[claim_id])

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.hydration_calls.append(("returns", claim_id))
        return deepcopy(self.returns[claim_id])

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        self.hydration_calls.append(("order", order_id))
        return deepcopy(self.orders[order_id])


class FakeMonotonicClock:
    def __init__(self, *, current: float = 100.0, sleep_overshoot: float = 0.0) -> None:
        self.current = current
        self.sleep_overshoot = sleep_overshoot
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.current += delay + self.sleep_overshoot


class TimedHydratingSource(HydratingSource):
    def __init__(self, clock: FakeMonotonicClock) -> None:
        super().__init__()
        self.clock = clock
        self.return_starts: list[float] = []

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.return_starts.append(self.clock.monotonic())
        return await super().get_returns(seller_id=seller_id, claim_id=claim_id)


def _use_mediation_without_related_v2_return_order(
    source: HydratingSource, *, missing_related_entities: bool = False
) -> None:
    mediation = source.claims["519988002"]
    mediation.update(
        {
            "type": "mediations",
            "status": "closed",
            "order_id": "1999",
            "item_id": "MLA2",
            "claimed_quantity": 99,
            "returned_quantity": 88,
        }
    )
    if missing_related_entities:
        mediation.pop("related_entities", None)
    else:
        mediation["related_entities"] = []
    returns = _fixture("return_v2.json")
    returns["id"] = "RETURN-519988002"
    returns["orders"][0].update({"order_id": "1999", "item_id": "MLA2", "return_quantity": "1.0"})
    source.returns["519988002"] = returns


@pytest.mark.parametrize(
    ("inventory_type", "inventory_status", "expected"),
    [
        (
            "cancel_purchase",
            "closed",
            InventoryRelevance.EXCLUDED_TERMINAL_CANCELLATION,
        ),
        ("cancel_purchase", "opened", InventoryRelevance.HYDRATE_CANDIDATE),
        ("returns", "closed", InventoryRelevance.HYDRATE_CANDIDATE),
        ("mediations", "closed", InventoryRelevance.HYDRATE_CANDIDATE),
        (None, "closed", InventoryRelevance.HYDRATE_CANDIDATE),
        ("unknown", None, InventoryRelevance.HYDRATE_CANDIDATE),
    ],
)
def test_inventory_relevance_is_closed_and_only_terminal_cancellation_excludes(
    inventory_type: str | None,
    inventory_status: str | None,
    expected: InventoryRelevance,
) -> None:
    entry = reconciliation_module.ClaimInventoryEntry(
        claim_id="519988002",
        last_updated="2026-06-16T09:05:00.000Z",
        date_created="2026-06-16T09:00:00.000Z",
        source={"id": "519988002", "type": inventory_type, "status": inventory_status},
    )

    assert classify_inventory_relevance(entry) is expected


@pytest.mark.asyncio
async def test_terminal_cancellation_excludes_before_detail_with_stable_evidence() -> None:
    source = HydratingSource()
    for page in source.responses:
        page["data"][1].update({"type": "cancel_purchase", "status": "closed"})
    source.claims.pop("519988002")

    first = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )
    second_source = HydratingSource()
    for page in second_source.responses:
        page["data"][1].update({"type": "cancel_purchase", "status": "closed"})
    second_source.claims.pop("519988002")
    second = await reconciliation_module.collect_devoluciones_snapshot(
        source=second_source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert [projection["_id"] for projection in first.projections] == ["519988001"]
    assert ("claim", "519988002") not in source.hydration_calls
    assert first.exclusions == (
        reconciliation_module.InventoryExclusionEvidence(
            claim_id="519988002",
            last_updated="2026-06-16T09:05:00.000Z",
            reason="terminal_cancellation",
        ),
    )
    assert first.counters == {
        "inventory_candidates": 2,
        "hydrated_candidates": 1,
        "excluded_terminal_cancellations": 1,
        "productive_claims": 1,
        "non_productive_claims": 0,
    }
    assert first.inventory.fingerprint == second.inventory.fingerprint
    assert first.exclusion_fingerprint == second.exclusion_fingerprint


@pytest.mark.asyncio
async def test_returns_pacing_has_exact_spacing_without_first_or_post_final_wait() -> None:
    clock = FakeMonotonicClock()
    source = TimedHydratingSource(clock)

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert source.return_starts == [100.0, 101.25]
    assert clock.sleeps == [1.25]
    assert clock.current == 101.25
    assert [call[0] for call in source.hydration_calls] == [
        "claim",
        "returns",
        "order",
        "claim",
        "returns",
        "order",
    ]
    assert snapshot.expected_claim_ids == frozenset({"519988001", "519988002"})


@pytest.mark.asyncio
async def test_returns_pacing_does_not_wait_for_pre_detail_cancellation() -> None:
    clock = FakeMonotonicClock()
    source = TimedHydratingSource(clock)
    for page in source.responses:
        page["data"][1].update({"type": "cancel_purchase", "status": "closed"})

    await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert source.return_starts == [100.0]
    assert clock.sleeps == []


@pytest.mark.parametrize("missing_related_entities", [False, True])
@pytest.mark.asyncio
async def test_mediation_without_related_return_hydrates_from_authoritative_v2_order_row(
    missing_related_entities: bool,
) -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(
        source, missing_related_entities=missing_related_entities
    )

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    mediation = next(
        projection for projection in snapshot.projections if projection["_id"] == "519988002"
    )
    assert mediation["productive"] is True
    assert mediation["returned_quantity"] == 1
    assert mediation["return_quantity_basis"] == "v2_return_order"
    assert mediation["order_id"] == "1999"
    assert mediation["item_id"] == "MLA2"
    assert ("returns", "519988002") in source.hydration_calls
    assert ("order", "1999") in source.hydration_calls


@pytest.mark.asyncio
async def test_uncertain_inventory_candidate_hydrates_and_fails_closed_on_detail_error() -> None:
    source = HydratingSource()
    for page in source.responses:
        page["data"][1].update({"type": "cancel_purchase", "status": "opened"})
    source.claims.pop("519988002")

    with pytest.raises(KeyError):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("claim", "519988002") in source.hydration_calls


@pytest.mark.parametrize(
    ("claim_type", "status"),
    [
        ("unknown", "closed"),
        (None, "closed"),
        ("cancel_purchase", "opened"),
        ("warranty", "closed"),
    ],
)
@pytest.mark.asyncio
async def test_hydrated_uncertain_candidate_never_disappears_fail_open(
    claim_type: str | None,
    status: str,
) -> None:
    source = HydratingSource()
    source.claims["519988002"].update(
        {"type": claim_type, "status": status, "related_entities": []}
    )

    with pytest.raises(ClaimInventoryError, match="unresolved"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("claim", "519988002") in source.hydration_calls
    assert ("returns", "519988002") not in source.hydration_calls
    assert ("order", "1999") not in source.hydration_calls


@pytest.mark.asyncio
async def test_mediation_without_related_and_no_v2_return_rows_fails_closed_after_probe() -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(source)
    source.returns["519988002"]["orders"] = []

    with pytest.raises(ClaimProjectionError, match="unique order/item"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("returns", "519988002") in source.hydration_calls


class RawReturnsAccessError(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = type("Response", (), {"status_code": status_code})()
        super().__init__(
            "HTTP "
            f"{status_code} GET https://runtime.internal/post-purchase/v2/claims/"
            "519988002/returns?access_token=RAW_TOKEN&seller_id=82453304 "
            'payload={"claim_id":"519988002","order_id":"1999"}'
        )


class ReturnsAccessFailureSource(HydratingSource):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        if claim_id != "519988002":
            return await super().get_returns(seller_id=seller_id, claim_id=claim_id)
        self.hydration_calls.append(("returns", claim_id))
        raise self.failure


class _SingleAttemptOnlyGatewayClient:
    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        del seller_id, path
        raise AssertionError("single-attempt test client does not support retrying fetch")


class AuthoritativeReturns404Client(_SingleAttemptOnlyGatewayClient):
    async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
        del seller_id, path
        response = type(
            "Response",
            (),
            {
                "status_code": 404,
                "headers": {"X-Zeler-Upstream-Attempts": "1"},
            },
        )()
        error = RuntimeError("unsafe raw v2 returns URL and identifiers")
        error.response = response  # type: ignore[attr-defined]
        raise error


@pytest.mark.asyncio
async def test_single_attempt_only_gateway_client_rejects_retrying_fetch() -> None:
    client = AuthoritativeReturns404Client()

    with pytest.raises(AssertionError, match="single-attempt test client"):
        await client.fetch_resource(seller_id="82453304", path="/unsupported")


class GatewayReturns404Source(HydratingSource):
    def __init__(self) -> None:
        super().__init__()
        self.gateway = reconciliation_module.GatewayDevolucionesSource(
            AuthoritativeReturns404Client(),
            single_attempt=True,
        )

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        if claim_id != "519988002":
            return await super().get_returns(seller_id=seller_id, claim_id=claim_id)
        self.hydration_calls.append(("returns", claim_id))
        return await self.gateway.get_returns(seller_id=seller_id, claim_id=claim_id)


@pytest.mark.parametrize("related_entities", [None, []], ids=("missing-related", "empty-related"))
@pytest.mark.asyncio
async def test_authoritative_returns_404_excludes_only_closed_unlinked_mediation(
    related_entities: list[dict[str, Any]] | None,
) -> None:
    source = GatewayReturns404Source()
    mediation = source.claims["519988002"]
    mediation.update(
        {
            "type": "mediations",
            "status": "closed",
            "order_id": "1999",
            "item_id": None,
        }
    )
    if related_entities is None:
        mediation.pop("related_entities", None)
    else:
        mediation["related_entities"] = related_entities

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert snapshot.expected_claim_ids == frozenset({"519988001"})
    assert [projection["_id"] for projection in snapshot.projections] == ["519988001"]
    assert snapshot.exclusions[-1] == reconciliation_module.InventoryExclusionEvidence(
        claim_id="519988002",
        last_updated="2026-06-16T09:05:00.000Z",
        reason="authoritative_no_return_mediation",
    )
    assert snapshot.counters["excluded_authoritative_no_return_mediations"] == 1
    assert ("returns", "519988002") in source.hydration_calls
    assert ("order", "1999") not in source.hydration_calls


@pytest.mark.parametrize(
    "claim_mutation",
    [
        {"item_id": "MLA2"},
        {"status": "opened"},
        {"related_entities": [{"type": "return", "id": "RETURN-1"}]},
        {"players": []},
    ],
    ids=("item-present", "not-closed", "return-linked", "seller-unproven"),
)
@pytest.mark.asyncio
async def test_authoritative_returns_404_fails_closed_when_mediation_invariants_are_unsafe(
    claim_mutation: dict[str, Any],
) -> None:
    source = GatewayReturns404Source()
    mediation = source.claims["519988002"]
    mediation.update(
        {
            "type": "mediations",
            "status": "closed",
            "order_id": "1999",
            "item_id": None,
            "related_entities": [],
            **claim_mutation,
        }
    )

    with pytest.raises(ClaimInventoryError, match="source_issue") as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is reconciliation_module._FocusedDevolucionesFailure.SAFE_404_PRECONDITION
    )
    assert ("order", "1999") not in source.hydration_calls


@pytest.mark.parametrize(
    "claim_mutation",
    [
        {"resource_id": "2999"},
        {"returned_quantity": 1},
        {
            "players": [
                {"user_id": "82453304", "role": "respondent", "type": "seller"},
                {"user_id": "999", "role": "respondent", "type": "seller"},
            ]
        },
    ],
    ids=("conflicting-order", "return-proof-present", "second-seller-respondent"),
)
@pytest.mark.asyncio
async def test_authoritative_returns_404_fails_closed_on_contradictory_evidence(
    claim_mutation: dict[str, Any],
) -> None:
    source = GatewayReturns404Source()
    source.claims["519988002"].update(
        {
            "type": "mediations",
            "status": "closed",
            "order_id": "1999",
            "item_id": None,
            "related_entities": [],
            **claim_mutation,
        }
    )

    with pytest.raises(ClaimInventoryError, match="source_issue"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("order", "1999") not in source.hydration_calls


@pytest.mark.asyncio
async def test_authoritative_404_rejects_inventory_status_contradiction() -> None:
    source = GatewayReturns404Source()
    for response in source.responses:
        response["data"][1]["status"] = "opened"
    source.claims["519988002"].update(
        {
            "type": "mediations",
            "status": "closed",
            "order_id": "1999",
            "item_id": None,
            "related_entities": [],
        }
    )

    with pytest.raises(ClaimInventoryError, match="source_issue"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )


@pytest.mark.asyncio
async def test_gateway_returns_404_requires_attempt_metadata_exactly_one() -> None:
    class TwoAttemptClient(_SingleAttemptOnlyGatewayClient):
        async def fetch_resource_once(self, *, seller_id: str, path: str) -> dict[str, Any]:
            del seller_id, path
            response = type(
                "Response",
                (),
                {"status_code": 404, "headers": {"X-Zeler-Upstream-Attempts": "2"}},
            )()
            error = RuntimeError("unsafe raw upstream detail")
            error.response = response  # type: ignore[attr-defined]
            raise error

    gateway = reconciliation_module.GatewayDevolucionesSource(
        TwoAttemptClient(),
        single_attempt=True,
    )

    with pytest.raises(RuntimeError, match="unsafe raw upstream detail") as exc_info:
        await gateway.get_returns(seller_id="82453304", claim_id="519988002")

    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is reconciliation_module._FocusedDevolucionesFailure.ATTEMPT_METADATA
    )


@pytest.mark.parametrize(
    "failure",
    [
        RawReturnsAccessError(401),
        RawReturnsAccessError(403),
        RawReturnsAccessError(404),
        RawReturnsAccessError(429),
        RawReturnsAccessError(500),
        ConnectionError(
            "network GET https://runtime.internal/post-purchase/v2/claims/"
            "519988002/returns?access_token=RAW_TOKEN payload order_id=1999"
        ),
    ],
    ids=("401", "403", "404", "429", "500", "network"),
)
@pytest.mark.asyncio
async def test_mediation_without_related_sanitizes_v2_returns_access_failure(
    failure: Exception,
) -> None:
    source = ReturnsAccessFailureSource(failure)
    _use_mediation_without_related_v2_return_order(source)

    with pytest.raises(ClaimInventoryError) as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert str(exc_info.value) == "v2 returns source_issue"
    expected_private_failure = (
        reconciliation_module._FocusedDevolucionesFailure.UNSAFE_404
        if getattr(getattr(failure, "response", None), "status_code", None) == 404
        else reconciliation_module._FocusedDevolucionesFailure.SOURCE
    )
    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is expected_private_failure
    )
    sanitized = str(exc_info.value)
    for forbidden in (
        "https://runtime.internal",
        "/post-purchase/v2/claims",
        "access_token",
        "RAW_TOKEN",
        "82453304",
        "519988002",
        "1999",
        "payload",
    ):
        assert forbidden not in sanitized
    assert ("returns", "519988002") in source.hydration_calls
    assert ("order", "1999") not in source.hydration_calls


class MissingReferencedOrderSource(HydratingSource):
    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        if order_id != "1999":
            return await super().get_order(seller_id=seller_id, order_id=order_id)
        self.hydration_calls.append(("order", order_id))
        raise ClaimInventoryError("referenced order missing")


@pytest.mark.asyncio
async def test_mediation_without_related_fails_closed_when_referenced_order_is_missing() -> None:
    source = MissingReferencedOrderSource()
    _use_mediation_without_related_v2_return_order(source)

    with pytest.raises(ClaimInventoryError, match="referenced order missing") as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is reconciliation_module._FocusedDevolucionesFailure.ORDER
    )
    assert ("order", "1999") in source.hydration_calls


@pytest.mark.asyncio
async def test_missing_order_identity_retains_only_bounded_private_failure() -> None:
    source = HydratingSource()
    source.claims["519988002"]["order_id"] = ""
    source.claims["519988002"]["resource_id"] = ""

    with pytest.raises(ClaimInventoryError, match="missing order identity") as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is reconciliation_module._FocusedDevolucionesFailure.IDENTITY
    )


@pytest.mark.asyncio
async def test_mediation_without_related_fails_closed_on_seller_mismatch() -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(source)
    source.orders["1999"] = _order(item_id="MLA2", seller_id=999) | {"id": 1999}

    with pytest.raises(ClaimProjectionError, match="order seller"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("order", "1999") in source.hydration_calls


@pytest.mark.asyncio
async def test_mediation_without_related_fails_closed_on_order_item_mismatch() -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(source)
    source.orders["1999"] = _order(item_id="MLA-OTHER") | {"id": 1999}

    with pytest.raises(ClaimProjectionError, match="unique matching item"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("order", "1999") in source.hydration_calls


@pytest.mark.asyncio
async def test_mediation_without_related_never_uses_claim_or_order_quantity_substitutes() -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(source)
    source.returns["519988002"]["orders"][0].pop("return_quantity")

    with pytest.raises(ClaimProjectionError, match="return_quantity"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("order", "1999") in source.hydration_calls


@pytest.mark.parametrize("claim_type", ["cancel_purchase", "cancel_sale", "warranty"])
@pytest.mark.asyncio
async def test_cancel_and_non_return_hydrated_claims_do_not_become_productive_from_v2_returns(
    claim_type: str,
) -> None:
    source = HydratingSource()
    _use_mediation_without_related_v2_return_order(source)
    source.claims["519988002"].update({"type": claim_type, "status": "closed"})

    with pytest.raises(ClaimInventoryError, match="unresolved"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("returns", "519988002") not in source.hydration_calls
    assert ("order", "1999") not in source.hydration_calls


class FocusedSourceSpy(HydratingSource):
    async def search_orders(self, **_: Any) -> Any:
        raise AssertionError("broad order-date search is forbidden")

    async def search_questions(self, **_: Any) -> Any:
        raise AssertionError("question hydration is forbidden")

    async def get_item(self, **_: Any) -> Any:
        raise AssertionError("item hydration is forbidden")

    async def get_shipment(self, **_: Any) -> Any:
        raise AssertionError("shipment hydration is forbidden")

    async def get_catalog_product(self, **_: Any) -> Any:
        raise AssertionError("catalog hydration is forbidden")


@pytest.mark.asyncio
async def test_focused_snapshot_is_immutable_claims_first_and_referenced_orders_only() -> None:
    source = FocusedSourceSpy()
    source.claims["519988002"]["order_id"] = "2001"
    source.claims["519988002"]["item_id"] = "MLA1"
    source.returns["519988002"] = {
        **source.returns["519988002"],
        "orders": [{"order_id": "2001", "item_id": "MLA1", "return_quantity": 1}],
    }
    captured_at = datetime(2026, 7, 10, 12, tzinfo=UTC)

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        captured_at=captured_at,
    )

    assert snapshot.seller_id == "82453304"
    assert snapshot.start == START
    assert snapshot.end == END
    assert snapshot.captured_at == captured_at
    assert snapshot.expected_claim_ids == frozenset({"519988001", "519988002"})
    assert [call[0] for call in source.hydration_calls] == [
        "claim",
        "returns",
        "order",
        "claim",
        "returns",
    ]
    assert len(snapshot.orders) == 1
    with pytest.raises(TypeError):
        snapshot.projections[0]["status"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.orders[0]["items"][0]["quantity"] = 999
    source_fingerprint = snapshot.source_fingerprint
    read_model_fingerprint = snapshot.read_model_fingerprint
    projection = cast(Any, snapshot.projections[0])
    inventory_source = cast(Any, snapshot.inventory.entries[0].source)
    with pytest.raises(TypeError, match="immutable"):
        projection |= {"status": "mutated"}
    with pytest.raises(TypeError, match="immutable"):
        inventory_source |= {"type": "cancel_purchase"}
    assert snapshot.source_fingerprint == source_fingerprint
    assert snapshot.read_model_fingerprint == read_model_fingerprint


def test_source_call_recorder_charges_physical_attempts_before_send_and_caps_total() -> None:
    recorder = SourceCallRecorder(max_total=3)

    recorder.charge("claim_search")
    recorder.charge("claim_detail")
    recorder.charge("order_detail")

    assert recorder.counts == {"P": 1, "R": 1, "O": 1, "T": 3}
    with pytest.raises(SourceCallBudgetError, match="64|budget") as exc_info:
        recorder.charge("return_detail")
    assert (
        reconciliation_module._private_focused_devoluciones_failure(exc_info.value)
        is reconciliation_module._FocusedDevolucionesFailure.BUDGET
    )
    assert recorder.counts == {"P": 1, "R": 1, "O": 1, "T": 3}


@pytest.mark.asyncio
async def test_source_attempt_deadline_cancels_gateway_call_and_keeps_failure_charged() -> None:
    class SlowSource:
        async def search_claims(self, **_: Any) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"data": [], "paging": {"offset": 0, "limit": 100, "total": 0}}

    recorder = SourceCallRecorder(max_total=64)
    deadline = time.monotonic() + 0.005

    with pytest.raises(ClaimInventoryError, match="source request failed") as exc_info:
        await verify_claim_inventory(
            source=SlowSource(),
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
            absolute_deadline=deadline,
        )

    assert isinstance(exc_info.value.__cause__, SourceCallBudgetError)
    assert recorder.counts == {"P": 1, "R": 0, "O": 0, "T": 1}


@pytest.mark.asyncio
async def test_failed_physical_attempt_and_deadline_are_recorded_fail_closed() -> None:
    source = HydratingSource()
    source.claims.pop("519988001")
    recorder = SourceCallRecorder()
    heartbeat_calls: list[int] = []

    async def heartbeat() -> None:
        heartbeat_calls.append(recorder.total)

    with pytest.raises(KeyError):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
            absolute_deadline=11.0,
            monotonic=lambda: 10.0,
            heartbeat=heartbeat,
        )

    assert recorder.counts == {"P": 2, "R": 1, "O": 0, "T": 3}
    assert heartbeat_calls

    untouched = HydratingSource()
    with pytest.raises(SourceCallBudgetError, match="deadline"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=untouched,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=SourceCallRecorder(),
            absolute_deadline=10.0,
            monotonic=lambda: 10.0,
        )
    assert untouched.calls == []


@pytest.mark.parametrize(
    ("deadline", "sleep_overshoot", "expected_sleeps"),
    [
        (101.25, 0.0, []),
        (101.30, 0.05, [1.25]),
    ],
    ids=("insufficient-margin-before-wait", "deadline-reached-after-wake"),
)
@pytest.mark.asyncio
async def test_returns_pacing_deadline_fails_before_charge_and_second_send(
    deadline: float,
    sleep_overshoot: float,
    expected_sleeps: list[float],
) -> None:
    clock = FakeMonotonicClock(sleep_overshoot=sleep_overshoot)
    source = TimedHydratingSource(clock)
    recorder = SourceCallRecorder()

    with pytest.raises(SourceCallBudgetError, match="deadline"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
            absolute_deadline=deadline,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert source.return_starts == [100.0]
    assert clock.sleeps == expected_sleeps
    assert recorder.counts == {"P": 2, "R": 3, "O": 1, "T": 6}


def _projection_matrix_source(case: str) -> HydratingSource:
    source = HydratingSource()
    claim = source.claims["519988001"]
    returns = source.returns["519988001"]
    order = source.orders["2001"]
    row = returns["orders"][0]
    if case == "claim_respondent":
        claim["players"] = []
    elif case == "order_seller":
        order["seller"] = {"id": 999}
    elif case == "returns_orders_shape":
        returns["orders"] = None
    elif case == "return_row_cardinality":
        returns["orders"] = []
    elif case == "item_identity":
        claim.pop("item_id")
        row.pop("item_id")
    elif case == "order_items_shape":
        order["items"] = None
    elif case == "order_item_cardinality":
        order["items"] = [{"item": {"id": "MLA-OTHER"}}]
    elif case == "return_quantity":
        row["return_quantity"] = 0
    elif case == "claim_identity":
        claim.pop("id")
    elif case == "claim_version":
        claim["claim_version"] = "not-an-integer"
    elif case == "last_updated_format":
        claim["last_updated"] = "not-a-timestamp"
    elif case == "last_updated_timezone":
        claim["last_updated"] = "2026-06-15T12:05:00"
    elif case == "return_last_updated_format":
        returns["last_updated"] = "not-a-timestamp"
    elif case == "return_last_updated_timezone":
        returns["last_updated"] = "2026-06-15T12:05:00"
    else:
        raise AssertionError(f"unknown projection matrix case: {case}")
    return source


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("claim_respondent", "projection_claim_respondent"),
        ("order_seller", "projection_order_seller"),
        ("returns_orders_shape", "projection_returns_orders_shape_null"),
        ("return_row_cardinality", "projection_return_row_cardinality"),
        ("item_identity", "projection_item_identity"),
        ("order_items_shape", "projection_order_items_shape"),
        ("order_item_cardinality", "projection_order_item_cardinality"),
        ("return_quantity", "projection_return_quantity"),
        ("claim_identity", "projection_claim_identity"),
        ("claim_version", "projection_claim_version"),
        ("last_updated_format", "projection_last_updated_format"),
        ("last_updated_timezone", "projection_last_updated_timezone"),
        ("return_last_updated_format", "projection_return_last_updated_format"),
        ("return_last_updated_timezone", "projection_return_last_updated_timezone"),
    ],
)
@pytest.mark.asyncio
async def test_focused_projection_diagnostics_classify_reachable_hydration_failures(
    case: str, expected_reason: str
) -> None:
    source = _projection_matrix_source(case)

    with pytest.raises(ClaimProjectionError) as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source, seller_id="82453304", start=START, end=END
        )

    assert source.hydration_calls == [
        ("claim", "519988001"),
        ("returns", "519988001"),
        ("order", "2001"),
    ]
    assert reconciliation_module._private_focused_devoluciones_diagnostic(exc_info.value) == {
        "failure_class": "parser_failure",
        "projection_reason": expected_reason,
    }


@pytest.mark.parametrize(
    ("case", "value", "expected_reason"),
    [
        ("return_quantity", "not-a-decimal", "projection_return_quantity"),
        ("return_quantity", "1.5", "projection_return_quantity"),
        ("last_updated_format", "not-a-timestamp", "projection_last_updated_format"),
        ("last_updated_format", object(), "projection_last_updated_format"),
        ("last_updated_timezone", datetime(2026, 6, 15, 12, 5), "projection_last_updated_timezone"),
        ("return_last_updated_format", "not-a-timestamp", "projection_return_last_updated_format"),
        ("return_last_updated_format", object(), "projection_return_last_updated_format"),
        (
            "return_last_updated_timezone",
            datetime(2026, 6, 15, 12, 5),
            "projection_return_last_updated_timezone",
        ),
    ],
)
@pytest.mark.asyncio
async def test_focused_projection_diagnostics_keep_coercion_and_validation_reasons_stable(
    case: str, value: Any, expected_reason: str
) -> None:
    source = _projection_matrix_source(case)
    if case == "return_quantity":
        source.returns["519988001"]["orders"][0]["return_quantity"] = value
    elif case == "last_updated_format" or case == "last_updated_timezone":
        source.claims["519988001"]["last_updated"] = value
    else:
        source.returns["519988001"]["last_updated"] = value

    with pytest.raises(ClaimProjectionError) as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source, seller_id="82453304", start=START, end=END
        )

    assert reconciliation_module._private_focused_devoluciones_diagnostic(exc_info.value) == {
        "failure_class": "parser_failure",
        "projection_reason": expected_reason,
    }


@pytest.mark.parametrize("reason", [None, "projection_return_quantity SECRET=token-123"])
def test_focused_projection_diagnostic_uses_unknown_for_untyped_or_invalid_reason(
    reason: str | None,
) -> None:
    error = ClaimProjectionError("https://sensitive.example/claim/519988001?token=secret")
    if reason is not None:
        error.projection_reason = cast(ClaimProjectionReason, reason)

    assert reconciliation_module._private_focused_devoluciones_diagnostic(error) == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_unknown",
    }


@pytest.mark.parametrize(
    ("key_present", "value", "expected_reason"),
    [
        (False, None, "projection_returns_orders_shape_absent"),
        (True, None, "projection_returns_orders_shape_null"),
        (True, {"order_id": "SECRET-ORDER"}, "projection_returns_orders_shape_object"),
        (True, True, "projection_returns_orders_shape_scalar"),
        (True, ("unserializable",), "projection_returns_orders_shape_other"),
    ],
    ids=("absent", "null", "mapping", "bool-scalar", "other"),
)
def test_returns_orders_shape_classifier_uses_closed_private_tokens(
    key_present: bool, value: object, expected_reason: str
) -> None:
    assert claim_projection_module._classify_returns_orders_shape(  # type: ignore[attr-defined]
        key_present=key_present, value=value
    ) is ClaimProjectionReason(expected_reason)


@pytest.mark.parametrize(
    ("orders", "expected_reason"),
    [
        (None, "projection_returns_orders_shape_null"),
        ({"order_id": "SECRET-ORDER"}, "projection_returns_orders_shape_object"),
        (True, "projection_returns_orders_shape_scalar"),
        (("not-json",), "projection_returns_orders_shape_other"),
    ],
    ids=("null", "mapping", "bool-scalar", "other"),
)
def test_non_list_orders_emit_exact_private_tokens_without_content_leakage(
    orders: object, expected_reason: str
) -> None:
    returns = _fixture("return_v2.json")
    returns["orders"] = orders

    with pytest.raises(ClaimProjectionError) as exc_info:
        build_claim_projection(
            seller_id="82453304", claim=_claim(), returns=returns, order=_order()
        )

    assert exc_info.value.projection_reason is ClaimProjectionReason(expected_reason)
    assert exc_info.value.projection_reason.value == expected_reason
    assert "SECRET-ORDER" not in exc_info.value.projection_reason.value
    assert "not-json" not in exc_info.value.projection_reason.value


def test_missing_orders_emit_absent_private_token() -> None:
    returns = _fixture("return_v2.json")
    returns.pop("orders")

    with pytest.raises(ClaimProjectionError) as exc_info:
        build_claim_projection(
            seller_id="82453304", claim=_claim(), returns=returns, order=_order()
        )

    assert exc_info.value.projection_reason is ClaimProjectionReason.RETURNS_ORDERS_SHAPE_ABSENT


def test_returns_orders_shape_classifier_failure_falls_back_to_broad_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_classifier(*, key_present: bool, value: object) -> ClaimProjectionReason:
        del key_present, value
        raise RuntimeError("unexpected classifier failure")

    monkeypatch.setattr(
        claim_projection_module,
        "_classify_returns_orders_shape",
        fail_classifier,
    )

    with pytest.raises(ClaimProjectionError) as exc_info:
        build_claim_projection(
            seller_id="82453304",
            claim=_claim(),
            returns={**_fixture("return_v2.json"), "orders": None},
            order=_order(),
        )

    assert exc_info.value.projection_reason is ClaimProjectionReason.RETURNS_ORDERS_SHAPE


def test_list_orders_bypass_shape_classifier_for_populated_and_empty_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_classifier(*, key_present: bool, value: object) -> ClaimProjectionReason:
        del key_present, value
        raise AssertionError("list values must bypass shape classification")

    monkeypatch.setattr(
        claim_projection_module,
        "_classify_returns_orders_shape",
        fail_classifier,
    )

    projection = build_claim_projection(
        seller_id="82453304",
        claim=_claim(),
        returns=_fixture("return_v2.json"),
        order=_order(),
    )
    assert projection["returned_quantity"] == 2

    returns = _fixture("return_v2.json")
    returns["orders"] = []
    with pytest.raises(ClaimProjectionError) as exc_info:
        build_claim_projection(
            seller_id="82453304", claim=_claim(), returns=returns, order=_order()
        )
    assert exc_info.value.projection_reason is ClaimProjectionReason.RETURN_ROW_CARDINALITY


@pytest.mark.asyncio
async def test_first_non_list_orders_failure_aborts_before_second_candidate() -> None:
    source = HydratingSource()
    source.returns["519988001"]["orders"] = None
    source.returns["519988002"]["orders"] = {"order_id": "SECOND-SECRET"}
    recorder = SourceCallRecorder()

    with pytest.raises(ClaimProjectionError) as exc_info:
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
        )

    assert reconciliation_module._private_focused_devoluciones_diagnostic(exc_info.value) == {
        "failure_class": "parser_failure",
        "projection_reason": "projection_returns_orders_shape_null",
    }
    assert source.hydration_calls == [
        ("claim", "519988001"),
        ("returns", "519988001"),
        ("order", "2001"),
    ]
    assert ("claim", "519988002") not in source.hydration_calls
    assert ("returns", "519988002") not in source.hydration_calls
    assert ("order", "1999") not in source.hydration_calls
    assert recorder.counts == {"P": 2, "R": 2, "O": 1, "T": 5}


@pytest.mark.asyncio
async def test_targeted_revalidation_uses_root_context_and_rejects_fingerprint_drift() -> None:
    run_ledger = reconciliation_module.SourceRunLedger()
    recorder = SourceCallRecorder(run_ledger=run_ledger)
    source = HydratingSource()
    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        recorder=recorder,
        captured_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
        absolute_deadline=100.0,
        monotonic=lambda: 1.0,
    )
    operation = _operation()
    operation.source_fingerprint = snapshot.source_fingerprint
    heartbeat_calls: list[str] = []

    async def heartbeat() -> None:
        heartbeat_calls.append(operation.operation_id)

    revalidation_recorder = SourceCallRecorder(run_ledger=run_ledger)
    proof = await revalidate_devoluciones_snapshot(
        source=HydratingSource(),
        snapshot=snapshot,
        operation=operation,
        absolute_deadline=100.0,
        recorder=revalidation_recorder,
        heartbeat=heartbeat,
        monotonic=lambda: 2.0,
        now=lambda: datetime(2026, 7, 10, 12, 1, tzinfo=UTC),
    )

    assert proof.source_fingerprint == snapshot.source_fingerprint
    assert proof.read_model_fingerprint == snapshot.read_model_fingerprint
    assert recorder.counts == {"P": 2, "R": 4, "O": 2, "T": 8}
    assert revalidation_recorder.counts == {"P": 2, "R": 4, "O": 2, "T": 8}
    assert run_ledger.counts == {"P": 4, "R": 8, "O": 4, "T": 16}
    assert heartbeat_calls == [operation.operation_id] * len(heartbeat_calls)
    assert len(heartbeat_calls) >= 2

    drifted = HydratingSource()
    drifted.returns["519988001"]["orders"][0]["return_quantity"] = 3
    with pytest.raises(DevolucionesReadModelVerificationError, match="changed"):
        await revalidate_devoluciones_snapshot(
            source=drifted,
            snapshot=snapshot,
            operation=operation,
            absolute_deadline=200.0,
            recorder=SourceCallRecorder(),
            heartbeat=heartbeat,
            monotonic=lambda: 3.0,
            now=lambda: datetime(2026, 7, 10, 12, 2, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_targeted_revalidation_rejects_reused_snapshot_ledger() -> None:
    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=HydratingSource(),
        seller_id="82453304",
        start=START,
        end=END,
        captured_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
    )
    operation = _operation()
    operation.source_fingerprint = snapshot.source_fingerprint
    reused = SourceCallRecorder()
    reused.charge("claim_search")

    async def heartbeat() -> None:
        return None

    with pytest.raises(SourceCallBudgetError, match="snapshot ledger"):
        await revalidate_devoluciones_snapshot(
            source=HydratingSource(),
            snapshot=snapshot,
            operation=operation,
            absolute_deadline=100.0,
            recorder=reused,
            heartbeat=heartbeat,
            monotonic=lambda: 2.0,
            now=lambda: datetime(2026, 7, 10, 12, 1, tzinfo=UTC),
        )

    assert reused.total == 1


@pytest.mark.asyncio
async def test_targeted_revalidation_rechecks_publication_age_after_hydration() -> None:
    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=HydratingSource(),
        seller_id="82453304",
        start=START,
        end=END,
        captured_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
    )
    operation = _operation()
    operation.source_fingerprint = snapshot.source_fingerprint
    clock = iter(
        (
            datetime(2026, 7, 10, 12, 2, 29, tzinfo=UTC),
            datetime(2026, 7, 10, 12, 2, 31, tzinfo=UTC),
            datetime(2026, 7, 10, 12, 2, 31, tzinfo=UTC),
        )
    )

    async def heartbeat(**_: Any) -> None:
        return None

    with pytest.raises(DevolucionesReadModelVerificationError, match="publication age"):
        await revalidate_devoluciones_snapshot(
            source=HydratingSource(),
            snapshot=snapshot,
            operation=operation,
            absolute_deadline=200.0,
            recorder=SourceCallRecorder(),
            heartbeat=heartbeat,
            monotonic=lambda: 3.0,
            now=lambda: next(clock),
        )


@pytest.mark.asyncio
async def test_collection_hydrates_return_mediation_and_old_order_from_claim_inventory() -> None:
    source = HydratingSource()

    projections, inventory = await collect_devoluciones_projections(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert inventory.fingerprint
    assert [projection["_id"] for projection in projections] == ["519988001", "519988002"]
    assert projections[0]["returned_quantity"] == 2
    assert projections[1]["productive"] is True
    assert ("order", "1999") in source.hydration_calls
    assert all("order_id" not in params for _, params in source.calls)


@pytest.mark.asyncio
async def test_hydrated_source_proof_changes_when_formula_visible_facts_drift() -> None:
    baseline_source = HydratingSource()
    quantity_source = HydratingSource()
    quantity_source.returns["519988001"]["orders"][0]["return_quantity"] = 3
    variation_source = HydratingSource()
    variation_source.orders["2001"]["items"][0]["item"]["variation_id"] = 991
    sku_source = HydratingSource()
    sku_source.orders["2001"]["items"][0]["item"]["seller_sku"] = "SKU-CHANGED"
    title_source = HydratingSource()
    title_source.orders["2001"]["items"][0]["item"]["title"] = "Changed title"

    baseline = await reconciliation_module.collect_devoluciones_snapshot(
        source=baseline_source,
        seller_id="82453304",
        start=START,
        end=END,
    )
    quantity_drift = await reconciliation_module.collect_devoluciones_snapshot(
        source=quantity_source,
        seller_id="82453304",
        start=START,
        end=END,
    )
    variation_drift = await reconciliation_module.collect_devoluciones_snapshot(
        source=variation_source,
        seller_id="82453304",
        start=START,
        end=END,
    )
    sku_drift = await reconciliation_module.collect_devoluciones_snapshot(
        source=sku_source,
        seller_id="82453304",
        start=START,
        end=END,
    )
    title_drift = await reconciliation_module.collect_devoluciones_snapshot(
        source=title_source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert quantity_drift.inventory.fingerprint == baseline.inventory.fingerprint
    assert variation_drift.inventory.fingerprint == baseline.inventory.fingerprint
    assert sku_drift.inventory.fingerprint == baseline.inventory.fingerprint
    assert title_drift.inventory.fingerprint == baseline.inventory.fingerprint
    assert quantity_drift.source_fingerprint != baseline.source_fingerprint
    assert variation_drift.source_fingerprint != baseline.source_fingerprint
    assert sku_drift.source_fingerprint != baseline.source_fingerprint
    assert title_drift.source_fingerprint != baseline.source_fingerprint
    assert quantity_drift.read_model_fingerprint != baseline.read_model_fingerprint
    assert variation_drift.read_model_fingerprint != baseline.read_model_fingerprint
    assert sku_drift.read_model_fingerprint != baseline.read_model_fingerprint
    assert title_drift.read_model_fingerprint != baseline.read_model_fingerprint


@pytest.mark.asyncio
async def test_low_cost_null_orders_suppresses_snapshot_proof() -> None:
    source = HydratingSource()
    source.returns["519988002"] = _fixture("low_cost_orders_null.json")

    with pytest.raises(ClaimProjectionError, match="orders must be a list"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )


def _persisted_readiness_order(source_order: dict[str, Any]) -> dict[str, Any]:
    seller = source_order["seller"]
    return {
        "_id": str(source_order["id"]),
        "seller_id": str(seller["id"]),
        "date_created": datetime(2025, 1, 1, tzinfo=UTC),
        "items": [
            {
                "item_id": str(row["item"]["id"]),
                "variation_id": (
                    str(row["item"]["variation_id"])
                    if row["item"].get("variation_id") is not None
                    else None
                ),
                "seller_sku": row["item"].get("seller_sku"),
                "title": row["item"].get("title"),
                "qty": int(row["quantity"]),
                "unit_price": "10.00",
            }
            for row in source_order["items"]
        ],
        "schema_version": 1,
    }


@pytest.mark.parametrize(
    "drift",
    ["return-quantity", "order-variation", "order-sku", "order-title"],
)
@pytest.mark.asyncio
async def test_joint_verifier_rejects_local_facts_that_differ_from_hydrated_proof(
    drift: str,
) -> None:
    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=HydratingSource(),
        seller_id="82453304",
        start=START,
        end=END,
    )
    claims = [_mutable_copy(projection) for projection in snapshot.projections]
    orders = [_persisted_readiness_order(_mutable_copy(order)) for order in snapshot.orders]
    if drift == "return-quantity":
        claims[0]["returned_quantity"] += 1
    elif drift == "order-variation":
        orders[0]["items"][0]["variation_id"] = "changed"
    elif drift == "order-sku":
        orders[0]["items"][0]["seller_sku"] = "SKU-CHANGED"
    else:
        orders[0]["items"][0]["title"] = "Changed title"

    with pytest.raises(DevolucionesReadModelVerificationError, match="hydrated source facts"):
        await verify_devoluciones_read_model(
            db=_KeysetDb(claims=claims, orders=orders),
            seller_id="82453304",
            date_from=START,
            date_to=END,
            expected_claim_ids=frozenset(projection["_id"] for projection in snapshot.projections),
            expected_read_model_fingerprint=snapshot.read_model_fingerprint,
        )


@pytest.mark.asyncio
async def test_hydrated_unrelated_claim_type_fails_closed_without_fabricating_return() -> None:
    source = HydratingSource()
    source.claims["519988002"] = {
        **source.claims["519988002"],
        "type": "cancel_purchase",
        "related_entities": [],
    }

    with pytest.raises(ClaimInventoryError, match="unresolved"):
        await collect_devoluciones_projections(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
        )

    assert ("returns", "519988002") not in source.hydration_calls


class NineOldOrderClaimsSource(ScriptedInventorySource):
    def __init__(self) -> None:
        rows = [
            {
                "id": str(519988000 + index),
                "last_updated": f"2026-06-{index + 1:02d}T12:05:00.000Z",
                "date_created": f"2026-06-{index + 1:02d}T12:00:00.000Z",
            }
            for index in range(1, 10)
        ]
        page = {"data": rows, "paging": {"offset": 0, "limit": 100, "total": 9}}
        super().__init__([page, page])

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        index = int(claim_id) - 519988000
        return {
            **_claim(),
            "id": claim_id,
            "order_id": str(1000 + index),
            "claim_version": index,
            "last_updated": f"2026-06-{index + 1:02d}T12:05:00.000Z",
            "date_created": f"2026-06-{index + 1:02d}T12:00:00.000Z",
        }

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        del seller_id
        index = int(claim_id) - 519988000
        payload = _fixture("return_v2.json")
        payload["id"] = f"RETURN-{claim_id}"
        payload["last_updated"] = f"2026-06-{index + 1:02d}T12:06:00.000Z"
        payload["orders"][0]["order_id"] = str(1000 + index)
        return payload

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        return {**_order(), "id": int(order_id), "seller": {"id": seller_id}}


@pytest.mark.asyncio
async def test_authoritative_inventory_expands_previous_three_to_nine_with_old_orders() -> None:
    previously_known_claim_ids = {"519988001", "519988002", "519988003"}

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=NineOldOrderClaimsSource(),
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert len(previously_known_claim_ids) == 3
    assert len(snapshot.projections) == 9
    assert len(snapshot.orders) == 9
    assert {str(order["id"]) for order in snapshot.orders} == {
        str(1000 + index) for index in range(1, 10)
    }
    assert snapshot.inventory.fingerprint


class CompleteRangeSource(ScriptedInventorySource):
    hydration_candidates = 34

    def __init__(self) -> None:
        terminal_rows = [
            {
                "id": str(700000000 + index),
                "last_updated": f"2026-06-{index + 1:02d}T12:01:00.000Z",
                "date_created": f"2026-06-{index + 1:02d}T12:00:00.000Z",
                "type": "cancel_purchase",
                "status": "closed",
            }
            for index in range(12)
        ]
        candidate_rows = [
            {
                "id": str(800000000 + index),
                "last_updated": "2026-06-20T12:01:00.000Z",
                "date_created": "2026-06-20T12:00:00.000Z",
                "type": "returns" if index < 9 else "mediations",
                "status": "closed",
            }
            for index in range(self.hydration_candidates)
        ]
        page = {
            "data": [*terminal_rows, *candidate_rows],
            "paging": {"offset": 0, "limit": 100, "total": 46},
        }
        super().__init__([page, page])
        self.hydration_calls: list[tuple[str, str]] = []

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        del seller_id
        self.hydration_calls.append(("claim", claim_id))
        index = int(claim_id) - 800000000
        claim = {
            **_claim(claim_type="returns" if index < 9 else "mediations"),
            "id": claim_id,
            "order_id": str(900000000 + min(index, 8)),
            "last_updated": "2026-06-20T12:01:00.000Z",
            "date_created": "2026-06-20T12:00:00.000Z",
            "status": "closed",
        }
        if index >= 9:
            claim.pop("item_id", None)
            claim["related_entities"] = []
        return claim

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        del seller_id
        self.hydration_calls.append(("returns", claim_id))
        index = int(claim_id) - 800000000
        if index >= 9:
            raise reconciliation_module.AuthoritativeReturnsNotFoundError()
        payload = _fixture("return_v2.json")
        payload["id"] = f"RETURN-{claim_id}"
        payload["orders"][0]["order_id"] = str(900000000 + index)
        return payload

    async def get_order(self, *, seller_id: str, order_id: str) -> dict[str, Any]:
        self.hydration_calls.append(("order", order_id))
        return {**_order(seller_id=int(seller_id)), "id": int(order_id)}


class TimedCompleteRangeSource(CompleteRangeSource):
    def __init__(self, clock: FakeMonotonicClock) -> None:
        super().__init__()
        self.clock = clock
        self.return_starts: list[float] = []

    async def get_returns(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        self.return_starts.append(self.clock.monotonic())
        return await super().get_returns(seller_id=seller_id, claim_id=claim_id)


@pytest.mark.asyncio
async def test_complete_46_row_inventory_fits_inventory_derived_hard_budget() -> None:
    source = CompleteRangeSource()
    recorder = SourceCallRecorder()

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        recorder=recorder,
    )

    assert snapshot.counters == {
        "inventory_candidates": 46,
        "hydrated_candidates": 34,
        "excluded_terminal_cancellations": 12,
        "excluded_authoritative_no_return_mediations": 25,
        "productive_claims": 9,
        "non_productive_claims": 0,
        "P": 2,
        "R": 68,
        "O": 9,
        "T": 79,
    }
    assert len(snapshot.expected_claim_ids) == 9
    assert len(snapshot.projections) == 9
    assert len(snapshot.exclusions) == 37
    assert recorder.required_capacity == 104
    assert recorder.total == 79


@pytest.mark.asyncio
async def test_complete_inventory_projects_33_intervals_without_changing_104_budget() -> None:
    clock = FakeMonotonicClock(current=0.0)
    source = TimedCompleteRangeSource(clock)
    recorder = SourceCallRecorder()

    await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        recorder=recorder,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert len(source.return_starts) == 34
    assert all(
        later - earlier == pytest.approx(1.25)
        for earlier, later in zip(source.return_starts, source.return_starts[1:], strict=False)
    )
    assert len(clock.sleeps) == 33
    assert sum(clock.sleeps) == pytest.approx(41.25)
    assert recorder.required_capacity == 104
    assert recorder.counts == {"P": 2, "R": 68, "O": 9, "T": 79}


@pytest.mark.asyncio
async def test_two_snapshot_pacing_projection_uses_67_intervals_and_83_75_seconds() -> None:
    clock = FakeMonotonicClock(current=0.0)
    pacer = reconciliation_module.ReturnsAttemptPacer(
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    starts: list[float] = []

    for _ in range(68):
        await pacer.wait_until_allowed(absolute_deadline=165.0)
        pacer.record_start()
        starts.append(clock.monotonic())

    assert starts[0] == 0.0
    assert starts[-1] == pytest.approx(83.75)
    assert len(clock.sleeps) == 67
    assert sum(clock.sleeps) == pytest.approx(83.75)
    assert all(
        later - earlier == pytest.approx(1.25)
        for earlier, later in zip(starts, starts[1:], strict=False)
    )


@pytest.mark.asyncio
async def test_inventory_derived_budget_fails_before_hydration_when_one_attempt_over_cap() -> None:
    source = CompleteRangeSource()
    recorder = SourceCallRecorder(max_total=103)

    with pytest.raises(SourceCallBudgetError, match="inventory-derived"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
        )

    assert recorder.counts == {"P": 2, "R": 0, "O": 0, "T": 2}
    assert source.hydration_calls == []


def test_snapshot_and_run_ledgers_allow_equality_and_do_not_count_cap_plus_one() -> None:
    run = reconciliation_module.SourceRunLedger(max_total=208)
    first = SourceCallRecorder(max_total=104, run_ledger=run)
    second = SourceCallRecorder(max_total=104, run_ledger=run)

    for _ in range(104):
        first.charge("claim_search")
    with pytest.raises(SourceCallBudgetError):
        first.charge("claim_search")

    for _ in range(104):
        second.charge("claim_search")
    with pytest.raises(SourceCallBudgetError):
        second.charge("claim_search")

    third = SourceCallRecorder(max_total=104, run_ledger=run)
    with pytest.raises(SourceCallBudgetError, match="run budget"):
        third.charge("claim_search")

    assert first.total == 104
    assert second.total == 104
    assert third.total == 0
    assert run.total == 208
    assert run.counts == {"P": 208, "R": 0, "O": 0, "T": 208}


@pytest.mark.asyncio
async def test_inventory_derived_budget_above_104_fails_before_detail_work() -> None:
    class OverRangeSource(CompleteRangeSource):
        hydration_candidates = 35

        def __init__(self) -> None:
            super().__init__()
            for response in self.responses:
                response["paging"]["total"] = 47

    source = OverRangeSource()
    recorder = SourceCallRecorder()

    with pytest.raises(SourceCallBudgetError, match="inventory-derived"):
        await reconciliation_module.collect_devoluciones_snapshot(
            source=source,
            seller_id="82453304",
            start=START,
            end=END,
            recorder=recorder,
        )

    assert recorder.required_capacity == 107
    assert recorder.counts == {"P": 2, "R": 0, "O": 0, "T": 2}
    assert source.hydration_calls == []


class _KeysetCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = [deepcopy(document) for document in documents]

    def sort(self, sort_spec: list[tuple[str, int]]) -> _KeysetCursor:
        documents = list(self.documents)
        for field, direction in reversed(sort_spec):
            documents.sort(
                key=lambda document: str(document.get(field) or ""),
                reverse=direction < 0,
            )
        return _KeysetCursor(documents)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        documents = self.documents if length is None else self.documents[:length]
        return [deepcopy(document) for document in documents]


class _KeysetCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = [deepcopy(document) for document in documents]
        self.find_filters: list[dict[str, Any]] = []

    def find(self, filter_spec: dict[str, Any], **_: Any) -> _KeysetCursor:
        self.find_filters.append(deepcopy(filter_spec))
        return _KeysetCursor(
            [
                document
                for document in self.documents
                if _matches_keyset_filter(document, filter_spec)
            ]
        )


class _KeysetDb:
    def __init__(self, *, claims: list[dict[str, Any]], orders: list[dict[str, Any]]) -> None:
        self.claims = _KeysetCollection(claims)
        self.orders = _KeysetCollection(orders)

    def __getitem__(self, name: str) -> _KeysetCollection:
        return {"claims": self.claims, "orders": self.orders}[name]


def _matches_keyset_filter(document: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for field, expected in filter_spec.items():
        if field == "$and":
            if not all(_matches_keyset_filter(document, branch) for branch in expected):
                return False
            continue
        if field == "$or":
            if not any(_matches_keyset_filter(document, branch) for branch in expected):
                return False
            continue
        actual = document.get(field)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$nin" in expected and actual in expected["$nin"]:
                return False
            if "$exists" in expected and (field in document) is not bool(expected["$exists"]):
                return False
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                return False
            if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                return False
            continue
        if actual != expected:
            return False
    return True


def _readiness_claim(
    claim_id: str,
    *,
    order_id: str,
    item_id: str,
    created_at: datetime,
    productive: bool,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "_id": claim_id,
        "seller_id": "82453304",
        "order_id": order_id,
        "item_id": item_id,
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": created_at,
        "productive": productive,
        "claim_version": 9,
        "last_updated": created_at + timedelta(minutes=1),
        "return_last_updated": created_at + timedelta(minutes=2),
        "schema_version": 1,
    }
    if productive:
        document.update(
            {
                "returned_quantity": 1,
                "return_quantity_basis": "v2_return_order",
            }
        )
    else:
        document.update(
            {
                "return_subtype": "low_cost",
                "return_quantity_basis": "verified_low_cost_no_row",
            }
        )
    return document


def _readiness_order(order_id: str, *, item_id: str) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": "82453304",
        "date_created": datetime(2025, 1, 1, tzinfo=UTC),
        "items": [{"item_id": item_id, "qty": 1, "unit_price": "10.00"}],
        "schema_version": 1,
    }


@pytest.mark.asyncio
async def test_joint_verifier_accepts_only_productive_v2_returns() -> None:
    claims = [
        _readiness_claim(
            "claim-1",
            order_id="order-1",
            item_id="MLA1",
            created_at=START,
            productive=True,
        ),
        _readiness_claim(
            "claim-2",
            order_id="order-2",
            item_id="MLA2",
            created_at=START + timedelta(days=1),
            productive=True,
        ),
    ]
    db = _KeysetDb(
        claims=claims,
        orders=[
            _readiness_order("order-1", item_id="MLA1"),
            _readiness_order("order-2", item_id="MLA2"),
        ],
    )

    proof = await verify_devoluciones_read_model(
        db=db,
        seller_id="82453304",
        date_from=START,
        date_to=END,
        expected_claim_ids=frozenset({"claim-1", "claim-2"}),
        page_size=1,
        order_chunk_size=1,
    )

    assert proof.expected_claims == 2
    assert proof.persisted_claims == 2
    assert proof.complete_claims == 2
    assert proof.missing_claims == 0
    assert proof.productive_claims == 2
    assert proof.non_productive_claims == 0
    assert proof.verified_orders == 2
    assert len(db.claims.find_filters) == 3
    assert len(db.orders.find_filters) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-claim",
        "ambiguous-order-line",
        "uncertain-non-productive",
        "missing-source-version",
    ],
)
@pytest.mark.asyncio
async def test_joint_verifier_fails_closed_on_missing_ambiguous_or_uncertain_facts(
    mutation: str,
) -> None:
    claims = [
        _readiness_claim(
            "claim-1",
            order_id="order-1",
            item_id="MLA1",
            created_at=START,
            productive=mutation != "uncertain-non-productive",
        )
    ]
    orders = [_readiness_order("order-1", item_id="MLA1")]
    expected_claim_ids = frozenset({"claim-1"})
    if mutation == "missing-claim":
        expected_claim_ids = frozenset({"claim-1", "claim-2"})
    elif mutation == "ambiguous-order-line":
        orders[0]["items"].append(deepcopy(orders[0]["items"][0]))
    elif mutation == "uncertain-non-productive":
        claims[0]["return_quantity_basis"] = "unknown"
    else:
        claims[0].pop("return_last_updated")

    with pytest.raises(DevolucionesReadModelVerificationError):
        await verify_devoluciones_read_model(
            db=_KeysetDb(claims=claims, orders=orders),
            seller_id="82453304",
            date_from=START,
            date_to=END,
            expected_claim_ids=expected_claim_ids,
        )


@pytest.mark.asyncio
async def test_joint_keyset_readers_have_no_silent_five_thousand_cap() -> None:
    claims = [
        _readiness_claim(
            f"claim-{index:05d}",
            order_id=f"order-{index:05d}",
            item_id=f"MLA{index:05d}",
            created_at=START + timedelta(seconds=index),
            productive=True,
        )
        for index in range(5001)
    ]
    orders = [
        _readiness_order(f"order-{index:05d}", item_id=f"MLA{index:05d}") for index in range(5001)
    ]
    db = _KeysetDb(claims=claims, orders=orders)

    persisted_claims = await read_devoluciones_claims_keyset(
        db=db,
        seller_id="82453304",
        date_from=START,
        date_to=END,
        page_size=1000,
    )
    persisted_orders = await read_devoluciones_orders_by_id_keyset(
        db=db,
        seller_id="82453304",
        order_ids=frozenset(order["_id"] for order in orders),
        chunk_size=1000,
    )

    assert len(persisted_claims) == 5001
    assert len(persisted_orders) == 5001
    assert len(db.claims.find_filters) == 6
    assert len(db.orders.find_filters) == 6
