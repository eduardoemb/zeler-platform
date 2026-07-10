from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import zeler_sheets.claim_projection as claim_projection_module
import zeler_sheets.devoluciones_reconciliation as reconciliation_module
from zeler_platform_core.devoluciones_readiness import DevolucionesOperationContext
from zeler_sheets.claim_projection import (
    ClaimProjectionError,
    build_claim_projection,
    persist_claim_projection,
    project_claim,
)
from zeler_sheets.devoluciones_reconciliation import (
    ClaimInventoryError,
    DevolucionesReadModelVerificationError,
    claim_inventory_search_params,
    collect_devoluciones_projections,
    read_devoluciones_claims_keyset,
    read_devoluciones_orders_by_id_keyset,
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
    "page",
    [
        {"data": [], "paging": {"offset": "0", "limit": 100, "total": 0}},
        {"data": [], "paging": {"offset": 1, "limit": 100, "total": 0}},
        {"data": [], "paging": {"offset": 0, "limit": 101, "total": 0}},
        {"data": [], "paging": {"offset": 0, "limit": 100, "total": 1}},
        {
            "data": [{"id": "1", "last_updated": "a"}],
            "paging": {"offset": 0, "limit": 1, "total": 2},
        },
    ],
)
@pytest.mark.asyncio
async def test_inventory_rejects_unproven_paging_contract(page: dict[str, Any]) -> None:
    source = ScriptedInventorySource([page])

    with pytest.raises(ClaimInventoryError):
        await verify_claim_inventory(source=source, seller_id="82453304", start=START, end=END)


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


def test_verified_low_cost_without_order_row_is_complete_non_productive() -> None:
    projection = build_claim_projection(
        seller_id="82453304",
        claim=_claim(),
        returns=_fixture("low_cost.json"),
        order=_order(),
    )

    assert projection["productive"] is False
    assert projection["return_quantity_basis"] == "verified_low_cost_no_row"
    assert "returned_quantity" not in projection


def test_verified_low_cost_null_orders_has_complete_non_productive_projection() -> None:
    projection = build_claim_projection(
        seller_id="82453304",
        claim=_claim(),
        returns=_fixture("low_cost_orders_null.json"),
        order=_order(),
    )

    assert projection == {
        "schema_version": 1,
        "_id": "519988001",
        "seller_id": "82453304",
        "buyer_id": "90001",
        "item_id": "MLA1",
        "order_id": "2001",
        "claim_version": 3,
        "last_updated": datetime(2026, 6, 15, 12, 5, tzinfo=UTC),
        "return_id": "RETURN-LOW-COST-1",
        "return_last_updated": datetime(2026, 6, 16, 9, 10, tzinfo=UTC),
        "return_status": "closed",
        "return_subtype": "low_cost",
        "return_quantity_basis": "verified_low_cost_no_row",
        "productive": False,
        "status": "closed",
        "stage": "claim",
        "type": "returns",
        "date_created": datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
    }


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
        low_cost = _fixture("low_cost.json")
        self.claims = {"519988001": _claim(), "519988002": mediation}
        self.returns = {
            "519988001": _fixture("return_v2.json"),
            "519988002": low_cost,
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
    assert projections[1]["productive"] is False
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
async def test_low_cost_null_orders_produces_complete_snapshot_proof_fingerprints() -> None:
    source = HydratingSource()
    source.returns["519988002"] = _fixture("low_cost_orders_null.json")

    snapshot = await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert len(snapshot.projections) == 2
    assert snapshot.projections[1]["productive"] is False
    assert snapshot.projections[1]["return_quantity_basis"] == "verified_low_cost_no_row"
    assert "returned_quantity" not in snapshot.projections[1]
    assert (
        snapshot.inventory.fingerprint
        == "ffb186c7f3fa4cb44462c6c9723cbbcc6b8456f1892e40b837752e4295e33b68"
    )
    assert (
        snapshot.source_fingerprint
        == "28af151c4cd83d5c29e6fdb90b8febbd413245d6641d5c8ce29663383435ad88"
    )
    assert (
        snapshot.read_model_fingerprint
        == "21e6d32ec1580e541d46a073c9dcad960e3dcd2c984c60f361535c430de3d61b"
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
    claims = [deepcopy(projection) for projection in snapshot.projections]
    orders = [_persisted_readiness_order(order) for order in snapshot.orders]
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
async def test_collection_skips_unrelated_claim_type_without_fabricating_return() -> None:
    source = HydratingSource()
    source.claims["519988002"] = {
        **source.claims["519988002"],
        "type": "cancel_purchase",
        "related_entities": [],
    }

    projections, _ = await collect_devoluciones_projections(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
    )

    assert [projection["_id"] for projection in projections] == ["519988001"]
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
async def test_joint_verifier_accepts_productive_and_verified_non_productive_returns() -> None:
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
            productive=False,
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
    assert proof.productive_claims == 1
    assert proof.non_productive_claims == 1
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
