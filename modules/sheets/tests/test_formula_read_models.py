from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
from zeler_sheets.formulas.read_models import (
    FormulaReadModelRepository,
    read_model_reconciliation_marker_covers,
)


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.sort_spec: list[tuple[str, int]] | None = None
        self.to_list_length: int | None | object = _UNSET

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = sort_spec
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(key=lambda doc: str(doc.get(key, "")), reverse=direction < 0)
        self._docs = sorted_docs
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        self.to_list_length = length
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.last_cursor: FakeCursor | None = None

    def find(self, filter_spec: dict[str, Any]) -> FakeCursor:
        del filter_spec
        self.last_cursor = FakeCursor(self._docs)
        return self.last_cursor

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        return None


class FakeDb:
    def __init__(self, item_rows: list[dict[str, Any]]) -> None:
        self._collections = {"sheets_item_formula_rows": FakeCollection(item_rows)}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection([]))


_UNSET = object()


@pytest.mark.parametrize("state", ["reconciled", "stale"])
@pytest.mark.parametrize("retained_expired", [False, True])
def test_order_interval_proofs_expire_independently(state: str, retained_expired: bool) -> None:
    now = datetime.now(UTC)
    start = now - timedelta(days=90)
    end = start + timedelta(days=30)
    marker = {
        "read_model": "orders",
        "state": state,
        "date_from": now - timedelta(days=10),
        "reconciled_until": now,
        "valid_until": now - timedelta(seconds=1),
        "retained_intervals": [
            {
                "state": "reconciled",
                "date_from": start,
                "reconciled_until": end,
                "valid_until": now + timedelta(minutes=-1 if retained_expired else 1),
            }
        ],
    }
    assert read_model_reconciliation_marker_covers(marker, date_from=start, date_to=end) is (
        state == "reconciled" and not retained_expired
    )
    assert not read_model_reconciliation_marker_covers(marker, date_from=start, date_to=now)
    assert not read_model_reconciliation_marker_covers(
        marker, date_from=now - timedelta(days=1), date_to=now
    )


def test_expired_recovery_proof_does_not_authorize_formula_reads() -> None:
    now = datetime.now(UTC)
    marker = {
        "state": "reconciled",
        "date_from": now - timedelta(days=30),
        "reconciled_until": now,
        "valid_until": now - timedelta(seconds=1),
    }
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=now - timedelta(days=2),
        date_to=now,
    )


def test_future_hours_are_never_required_as_reconciled_coverage() -> None:
    # A "last N days" formula asks for the whole local day, which ends in the
    # future. No acquisition can reconcile hours that have not happened, so the
    # requirement must stop at the read instant instead of blocking forever.
    now = datetime(2026, 9, 10, 14, 44, tzinfo=UTC)
    marker = {
        "state": "reconciled",
        "date_from": datetime(2026, 8, 12, 7, tzinfo=UTC),
        "reconciled_until": datetime(2026, 9, 11, 7, tzinfo=UTC),
        "valid_until": now + timedelta(minutes=25),
    }
    assert read_model_reconciliation_marker_covers(
        marker,
        date_from=datetime(2026, 8, 13, tzinfo=UTC),
        date_to=datetime(2026, 9, 10, 23, 59, 59, 999999, tzinfo=UTC),
        now=now,
    )
    # The same window still fails when the marker has not reached the read
    # instant, so old data is never presented as current.
    stale = {**marker, "reconciled_until": datetime(2026, 9, 10, 7, tzinfo=UTC)}
    assert not read_model_reconciliation_marker_covers(
        stale,
        date_from=datetime(2026, 8, 13, tzinfo=UTC),
        date_to=datetime(2026, 9, 10, 23, 59, 59, 999999, tzinfo=UTC),
        now=now,
    )
    # Exact interval proofs keep their strict equality semantics.
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=datetime(2026, 8, 12, 7, tzinfo=UTC),
        date_to=datetime(2026, 9, 11, 7, tzinfo=UTC),
        exact_interval=True,
        now=now,
    )


def test_current_claim_stays_readable_until_its_validity_window_expires() -> None:
    # The fast refresh publishes coverage a few minutes behind the read instant
    # and stays valid for two cycles. While that claim is live the answer must
    # be served; once it expires the same read must fail instead of silently
    # presenting stale data as current.
    now = datetime(2026, 9, 10, 14, 44, tzinfo=UTC)
    requested_from = datetime(2026, 8, 13, 7, tzinfo=UTC)
    marker = {
        "read_model": "orders",
        "state": "reconciled",
        "date_from": datetime(2026, 8, 13, 7, tzinfo=UTC),
        "reconciled_until": now - timedelta(minutes=10),
        "fresh_until": now - timedelta(minutes=10),
        "valid_until": now + timedelta(minutes=20),
    }
    assert read_model_reconciliation_marker_covers(
        marker, date_from=requested_from, date_to=now, now=now
    )

    expired = {**marker, "valid_until": now - timedelta(seconds=1)}
    assert not read_model_reconciliation_marker_covers(
        expired, date_from=requested_from, date_to=now, now=now
    )

    # A range that lies entirely in the future is never authorized.
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=now + timedelta(days=1),
        date_to=now + timedelta(days=2),
        now=now,
    )


def test_retained_interval_validity_does_not_extend_its_coverage() -> None:
    # Historical proofs expire independently, but their validity window must
    # never certify hours after the range they actually acquired.
    now = datetime(2026, 9, 10, 14, 44, tzinfo=UTC)
    marker = {
        "read_model": "orders",
        "state": "reconciled",
        "date_from": now - timedelta(minutes=10),
        "reconciled_until": now,
        "fresh_until": now,
        "valid_until": now + timedelta(minutes=20),
        "retained_intervals": [
            {
                "state": "reconciled",
                "date_from": now - timedelta(days=60),
                "reconciled_until": now - timedelta(days=30),
                "valid_until": now + timedelta(minutes=20),
            }
        ],
    }
    assert not read_model_reconciliation_marker_covers(
        marker,
        date_from=now - timedelta(days=60),
        date_to=now - timedelta(days=15),
        now=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["fresh", "reconciled"])
@pytest.mark.parametrize("validity", ["expired", "invalid", "valid"])
async def test_productive_gate_respects_proof_expiration(state: str, validity: str) -> None:
    now = datetime.now(UTC)
    expiry = {
        "expired": now - timedelta(seconds=1),
        "invalid": "not-a-date",
        "valid": now + timedelta(minutes=5),
    }[validity]

    class MarkerCollection(FakeCollection):
        async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any]:
            assert filter_spec["seller_id"] == "seller-1"
            return {"state": state, "fresh_until": now, "valid_until": expiry}

    db = FakeDb([])
    db._collections["sheets_read_model_freshness"] = MarkerCollection([])
    repository = FormulaReadModelRepository(db=db)

    async def check() -> None:
        await repository.require_read_model_productive(
            seller_id="seller-1", read_model="orders", date_to=now, formula="ZELERDATA_TEST"
        )

    if validity == "valid":
        await check()
    else:
        with pytest.raises(FormulaDataUnavailableError):
            await check()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "read_model", "has_start"),
    [
        ("require_questions_read_model_productive", "questions", True),
        ("require_read_model_productive", "item_formula_rows", False),
        ("require_read_model_reconciled_range", "stock_time_metrics", True),
    ],
)
async def test_missing_model_identifies_exact_recovery_scope(
    method: str, read_model: str, has_start: bool
) -> None:
    start = datetime(2026, 8, 8, tzinfo=UTC)
    end = datetime(2026, 9, 7, tzinfo=UTC)
    kwargs: dict[str, Any] = {"seller_id": "seller-1", "date_to": end, "formula": "ZELERDATA_TEST"}
    if has_start:
        kwargs["date_from"] = start
    if read_model != "questions":
        kwargs["read_model"] = read_model

    with pytest.raises(FormulaDataUnavailableError) as caught:
        await getattr(FormulaReadModelRepository(db=FakeDb([])), method)(**kwargs)

    assert caught.value.read_model == read_model
    assert caught.value.date_from == (start if has_start else None)
    assert caught.value.date_to == end


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "collection", "count", "kwargs"),
    [
        ("find_item_formula_rows", "sheets_item_formula_rows", 501, {}),
        ("find_sku_index_rows", "sheets_item_sku_index", 501, {}),
        (
            "find_orders",
            "orders",
            1001,
            {"date_from": "2026-08-08", "date_to": "2026-09-07"},
        ),
    ],
)
async def test_formula_sources_do_not_silently_truncate_complete_results(
    method: str, collection: str, count: int, kwargs: dict[str, Any]
) -> None:
    db = FakeDb([])
    db._collections[collection] = FakeCollection(
        [{"_id": str(index), "seller_id": "seller-1"} for index in range(count)]
    )
    repository = FormulaReadModelRepository(db=db)

    rows = await getattr(repository, method)(seller_id="seller-1", **kwargs)

    assert len(rows) == count


@pytest.mark.asyncio
async def test_item_formula_rows_can_use_publication_order_without_500_row_truncation() -> None:
    rows = [
        {"_id": f"row-{index}", "seller_id": "seller-1", "item_id": f"MLA{index:03d}"}
        for index in range(501)
    ]
    db = FakeDb(rows)
    repository = FormulaReadModelRepository(db=db)

    result = await repository.find_item_formula_rows(
        seller_id="seller-1",
        sort_by="publication",
        limit=None,
    )

    assert len(result) == 501
    cursor = db["sheets_item_formula_rows"].last_cursor
    assert cursor is not None
    assert cursor.sort_spec == [
        ("item_id", 1),
        ("variation_id", 1),
        ("normalized_sku", 1),
        ("_id", 1),
    ]
    assert cursor.to_list_length is None


class _ResolutionDb:
    """Mongo surface for the marker-first item row resolver."""

    def __init__(
        self,
        *,
        marker: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        recovery_job: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self._collections: dict[str, Any] = {
            "sheets_item_formula_rows": FakeCollection(rows),
            "items": FakeCollection(items or []),
        }
        self._marker = marker
        self._recovery_job = recovery_job

    def __getitem__(self, name: str) -> Any:
        if name == "sheets_read_model_freshness":

            class MarkerCollection:
                def __init__(self, marker: dict[str, Any] | None) -> None:
                    self._marker = marker

                async def find_one(self, filter_spec: dict[str, Any]) -> Any:
                    return self._marker

            return MarkerCollection(self._marker)
        if name == "sheets_formula_recovery_jobs":

            class JobCollection:
                def __init__(self, job: dict[str, Any] | None) -> None:
                    self._job = job

                async def find_one(self, filter_spec: dict[str, Any]) -> Any:
                    return self._job

            return JobCollection(self._recovery_job)
        return self._collections.setdefault(name, FakeCollection([]))


def _inventory_item(item_id: str, *, observed: datetime) -> dict[str, Any]:
    return {
        "_id": item_id,
        "seller_id": "seller-1",
        "last_meli_sync_at": observed,
        "title": f"Item {item_id}",
    }


def _inventory_row(item_id: str, *, item: dict[str, Any]) -> dict[str, Any]:
    from zeler_sheets.item_projection import item_source_fingerprint

    return {
        "_id": f"seller-1:SKU-{item_id}:{item_id}",
        "seller_id": "seller-1",
        "item_id": item_id,
        "sku": f"SKU-{item_id}",
        "normalized_sku": f"SKU-{item_id}".upper(),
        "source_snapshot": {
            "fingerprint": item_source_fingerprint(item),
            "observed_at": item["last_meli_sync_at"],
            "rows_count": 1,
        },
    }


@pytest.mark.asyncio
async def test_resolver_prefers_the_reconciled_marker_over_any_enumeration() -> None:
    now = datetime.now(UTC)
    item = _inventory_item("MLA1", observed=now)
    rows = [_inventory_row("MLA1", item=item)]
    db = _ResolutionDb(
        marker={
            "seller_id": "seller-1",
            "read_model": "item_formula_rows",
            "state": "reconciled",
            "fresh_until": now + timedelta(minutes=10),
        },
        rows=rows,
        items=[item],
    )

    resolution = await FormulaReadModelRepository(db=db).resolve_item_formula_rows(
        seller_id="seller-1", formula="ZELERDATA_MEDIDAS", now=now
    )

    assert resolution.inventory_scope is False
    assert resolution.rows == rows
    assert resolution.missing_items == ()
    assert resolution.recovery is None


@pytest.mark.asyncio
async def test_resolver_falls_back_to_verified_inventory_when_marker_is_not_productive() -> None:
    now = datetime.now(UTC)
    observed = now - timedelta(minutes=5)
    item = _inventory_item("MLA1", observed=observed)
    # The whole-seller enumeration is only defined for a numeric seller.
    numeric_seller = "82453304"
    item["seller_id"] = numeric_seller
    rows = [_inventory_row("MLA1", item=item)]
    for row in rows:
        row["seller_id"] = numeric_seller
    db = _ResolutionDb(
        marker=None,
        rows=rows,
        recovery_job={
            "seller_id": numeric_seller,
            "read_model": "item_formula_rows",
            "inventory_scope": True,
            "state": "pending",
            "inventory_ids": ["MLA1", "MLA2"],
            "inventory_offset": 2,
            "inventory_observed_at": observed,
        },
        items=[item],
    )

    resolution = await FormulaReadModelRepository(db=db).resolve_item_formula_rows(
        seller_id=numeric_seller, formula="ZELERDATA_MEDIDAS", now=now
    )

    assert resolution.inventory_scope is True
    assert resolution.enumeration_current is True
    assert [row["item_id"] for row in resolution.rows] == ["MLA1"]
    # MLA2 was enumerated but not verified, so it must stay explicitly missing.
    assert resolution.missing_items == ("MLA2",)
    assert resolution.recovery is not None
    assert resolution.recovery.read_model == "item_formula_rows"


@pytest.mark.asyncio
async def test_resolver_verifies_an_explicit_selection_without_enumeration() -> None:
    now = datetime.now(UTC)
    observed = now - timedelta(minutes=5)
    item = _inventory_item("MLA1", observed=observed)
    rows = [_inventory_row("MLA1", item=item)]
    db = _ResolutionDb(
        marker=None,
        rows=rows,
        items=[item],
    )

    resolution = await FormulaReadModelRepository(db=db).resolve_item_formula_rows(
        seller_id="seller-1",
        formula="ZELERDATA_MEDIDAS",
        now=now,
        item_ids=["MLA1"],
    )

    assert resolution.inventory_scope is True
    assert [row["item_id"] for row in resolution.rows] == ["MLA1"]
    assert resolution.missing_items == ()
    assert resolution.recovery is None
