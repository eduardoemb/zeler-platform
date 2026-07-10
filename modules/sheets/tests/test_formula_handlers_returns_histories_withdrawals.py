# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    build_returns_histories_withdrawals_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    CLAIMS_READ_MODEL,
    ITEM_FORMULA_ROWS_READ_MODEL,
    ITEM_STATUS_STATES_READ_MODEL,
    ORDERS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, sort_spec: list[tuple[str, int]]) -> FakeCursor:
        sorted_docs = list(self._docs)
        for key, direction in reversed(sort_spec):
            sorted_docs.sort(
                key=lambda doc: str(_dotted_value(doc, key) or ""), reverse=direction < 0
            )
        return FakeCursor(sorted_docs)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return [dict(doc) for doc in self._docs]
        return [dict(doc) for doc in self._docs[:length]]


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.last_find_filter: dict[str, Any] | None = None

    async def find_one(self, filter_spec: dict[str, Any]) -> dict[str, Any] | None:
        self.last_find_filter = dict(filter_spec)
        for doc in self.documents.values():
            if _matches(doc, filter_spec):
                return dict(doc)
        return None

    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        del projection
        self.last_find_filter = dict(filter_spec)
        return FakeCursor(
            [dict(doc) for doc in self.documents.values() if _matches(doc, filter_spec)]
        )


class MutatingFindCollection(FakeCollection):
    def __init__(self, *, mutate: Any) -> None:
        super().__init__()
        self._mutate = mutate

    def find(
        self, filter_spec: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        cursor = super().find(filter_spec, projection)
        self._mutate()
        return cursor


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_devoluciones_groups_return_claims_by_item_and_sku() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc("CLAIM-1", order_id="ORDER-1", days_ago=2, returned_quantity=1),
        "claim-2": _claim_doc("CLAIM-2", order_id="ORDER-2", days_ago=1, returned_quantity=1),
        "claim-cancelled": _claim_doc(
            "CLAIM-CANCELLED", order_id="ORDER-CANCELLED", days_ago=1, status="cancelled"
        ),
        "claim-mediation": _claim_doc(
            "CLAIM-MEDIATION", order_id="ORDER-MEDIATION", days_ago=1, claim_type="mediations"
        ),
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc(
            "ORDER-1",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=2,
        ),
        "ORDER-2": _order_doc(
            "ORDER-2",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=1,
        ),
        "ORDER-CANCELLED": _order_doc(
            "ORDER-CANCELLED",
            sku="sku-2",
            item_id="MLA2",
            title="Cancelled return",
            quantity=9,
        ),
        "ORDER-MEDIATION": _order_doc(
            "ORDER-MEDIATION",
            sku="sku-3",
            item_id="MLA3",
            title="Mediation item",
            quantity=5,
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context(
            "ZELERDATA_DEVOLUCIONES",
            {
                "fecha_inicio": "2026-06-01",
                "fecha_final": "2026-06-15",
                "id_publicaciones": ["MLA1", "MLA2"],
                "encabezados": "si",
            },
        )
    )

    assert result.values == [
        ["ID PUBLICACION", "SKU", "UNIDADES DEVUELTAS", "TITULO"],
        ["MLA1", "SKU-1", 2, "Returned item"],
    ]
    assert result.meta == {
        "claims_count": 2,
        "order_count": 2,
        "rows_count": 1,
        "columns": "legacy_returns",
    }


@pytest.mark.asyncio
async def test_devoluciones_never_falls_back_to_single_order_line_quantity() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc("CLAIM-1", order_id="ORDER-1", days_ago=2),
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc(
            "ORDER-1",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=2,
        ),
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {
                    "fecha_inicio": "2026-06-01",
                    "fecha_final": "2026-06-15",
                    "id_publicaciones": ["MLA1"],
                    "encabezados": "si",
                },
            )
        )
    assert "returned quantity" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_never_falls_back_to_raw_order_item_quantity() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc("CLAIM-1", order_id="ORDER-1", days_ago=2, item_id="MLA1"),
    }
    db["orders"].documents = {
        "ORDER-1": {
            "_id": "ORDER-1",
            "seller_id": "seller-1",
            "date_created": NOW - timedelta(days=1),
            "status": "paid",
            "order_items": [
                {
                    "item": {
                        "id": "MLA1",
                        "title": "Raw returned item",
                        "seller_sku": "raw-sku-1",
                    },
                    "quantity": 4,
                }
            ],
        },
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {
                    "fecha_inicio": "2026-06-01",
                    "fecha_final": "2026-06-15",
                    "id_publicaciones": ["MLA1"],
                    "encabezados": "si",
                },
            )
        )
    assert "returned quantity" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_never_falls_back_to_matching_order_line_quantity() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc("CLAIM-1", order_id="ORDER-1", days_ago=2, item_id="MLA2"),
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc_from_lines(
            "ORDER-1",
            [
                {"sku": "sku-1", "item_id": "MLA1", "title": "First item", "quantity": 1},
                {"sku": "sku-2", "item_id": "MLA2", "title": "Second item", "quantity": 3},
            ],
        ),
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {
                    "fecha_inicio": "2026-06-01",
                    "fecha_final": "2026-06-15",
                    "id_publicaciones": ["MLA2"],
                    "encabezados": "si",
                },
            )
        )
    assert "returned quantity" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_blocks_missing_quantity_with_ambiguous_order_scope() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc("CLAIM-1", order_id="ORDER-1", days_ago=2),
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc_from_lines(
            "ORDER-1",
            [
                {"sku": "sku-1", "item_id": "MLA1", "title": "First item", "quantity": 1},
                {"sku": "sku-2", "item_id": "MLA2", "title": "Second item", "quantity": 3},
            ],
        ),
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {
                    "fecha_inicio": "2026-06-01",
                    "fecha_final": "2026-06-15",
                    "id_publicaciones": ["MLA1"],
                },
            )
        )

    assert "scoped order line" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_fails_closed_when_claim_order_is_absent() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc(
            "CLAIM-1",
            order_id="ORDER-MISSING",
            days_ago=2,
            item_id="MLA1",
            returned_quantity=1,
        ),
    }
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {
                    "fecha_inicio": "2026-06-01",
                    "fecha_final": "2026-06-15",
                    "id_publicaciones": ["MLA1"],
                },
            )
        )

    assert "matching order" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("interleaving", ["stale", "republished"])
async def test_devoluciones_revalidates_marker_revision_after_fact_reads(
    interleaving: str,
) -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    marker = db["sheets_read_model_freshness"].documents["seller-1:devoluciones"]

    def mutate_marker() -> None:
        if interleaving == "stale":
            marker["state"] = "stale"
            marker["valid_until"] = NOW
        else:
            marker["revision"] = "attempt-republished"
            marker["proof_fingerprint"] = "proof-republished"

    claims = MutatingFindCollection(mutate=mutate_marker)
    claims.documents = {
        "claim-1": _claim_doc(
            "CLAIM-1",
            order_id="ORDER-1",
            days_ago=2,
            returned_quantity=1,
            item_id="MLA1",
        )
    }
    db.collections["claims"] = claims
    db["orders"].documents = {
        "ORDER-1": _order_doc(
            "ORDER-1",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=1,
        )
    }

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES"):
        await _dispatcher(db).execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            )
        )


@pytest.mark.asyncio
async def test_publicaciones_descuidadas_uses_current_full_out_of_stock_paused_rows() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Neglected item",
            status="paused",
            available_quantity=0,
            paused_since=NOW - timedelta(days=11),
            logistic_type="fulfillment",
            unavailable_quantity=4,
            unavailable_reason="damaged",
        ),
        "seller-1:SKU-2:MLA2": _item_row(
            item_id="MLA2",
            sku="sku-2",
            title="Too recent",
            status="paused",
            available_quantity=0,
            paused_since=NOW - timedelta(days=4),
            logistic_type="fulfillment",
        ),
        "seller-1:SKU-3:MLA3": _item_row(
            item_id="MLA3",
            sku="sku-3",
            title="Not full",
            status="paused",
            available_quantity=0,
            paused_since=NOW - timedelta(days=20),
            logistic_type="xd_drop_off",
        ),
        "seller-1:SKU-4:MLA4": _item_row(
            item_id="MLA4",
            sku="sku-4",
            title="Has stock",
            status="paused",
            available_quantity=3,
            paused_since=NOW - timedelta(days=20),
            logistic_type="fulfillment",
        ),
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONESDESCUIDADAS", {"encabezados": "si"})
    )

    assert result.values == [
        [
            "ID PUBLICACION",
            "TITULO",
            "SKU",
            "STOCK ACTUAL",
            "STOCK A RETIRAR",
            "MOTIVO DE RETIRO",
            "PRECIO",
            "LOGISTICA",
            "URL",
            "TIPO DE PUBLICACION",
            "STATUS",
            "CODIGO ML",
        ],
        [
            "MLA1",
            "Neglected item",
            "sku-1",
            0,
            4,
            "damaged",
            120,
            "fulfillment",
            "https://meli.example/MLA1",
            "gold_pro",
            "paused",
            "INV-MLA1",
        ],
    ]
    assert result.meta == {
        "rows_count": 1,
        "threshold_days": 10,
        "columns": "legacy_neglected_publications",
    }


@pytest.mark.asyncio
async def test_publicaciones_descuidadas_requires_effective_observed_pause_basis() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_FORMULA_ROWS_READ_MODEL)
    db["sheets_item_formula_rows"].documents = {
        "seller-1:SKU-1:MLA1": _item_row(
            item_id="MLA1",
            sku="sku-1",
            title="Effective pause basis",
            status="paused",
            available_quantity=0,
            paused_since=NOW - timedelta(days=11),
            logistic_type="fulfillment",
        ),
        "seller-1:SKU-2:MLA2": _item_row(
            item_id="MLA2",
            sku="sku-2",
            title="Legacy scalar only",
            status="paused",
            available_quantity=0,
            paused_since=NOW - timedelta(days=11),
            logistic_type="fulfillment",
        ),
    }
    stale_scalar_only = db["sheets_item_formula_rows"].documents["seller-1:SKU-2:MLA2"]
    stale_scalar_only["current"]["status_started_at"] = stale_scalar_only["current"].pop(
        "paused_since"
    )

    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_PUBLICACIONESDESCUIDADAS", {"encabezados": "si"})
    )

    assert [row[0] for row in result.values[1:]] == ["MLA1"]
    assert result.meta["rows_count"] == 1


@pytest.mark.asyncio
async def test_tiempoactiva_uses_item_status_state_history_not_current_row_guessing() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, ITEM_STATUS_STATES_READ_MODEL)
    db["item_status_states"].documents = {
        "seller-1:MLA1": {
            "_id": "seller-1:MLA1",
            "seller_id": "seller-1",
            "item_id": "MLA1",
            "current_status": "active",
            "first_observed_at": NOW - timedelta(days=20),
            "last_observed_at": NOW,
            "status_started_at": NOW - timedelta(days=3),
            "schema_version": 1,
        },
        "seller-1:MLA2": {
            "_id": "seller-1:MLA2",
            "seller_id": "seller-1",
            "item_id": "MLA2",
            "current_status": "paused",
            "first_observed_at": NOW - timedelta(days=20),
            "last_observed_at": NOW,
            "status_started_at": NOW - timedelta(days=1),
            "schema_version": 1,
        },
    }
    dispatcher = _dispatcher(db)

    result = await dispatcher.execute(
        _context("ZELERDATA_TIEMPOACTIVA", {"id_publicaciones": ["MLA1", "MLA2", "MLA3"]})
    )

    assert result.values == [[3], ["NA"], ["NA"]]
    assert result.meta == {"partial_misses": 2, "columns": "active_status_days"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        (
            "ZELERDATA_DEVOLUCIONES",
            {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            "devoluciones",
        ),
        ("ZELERDATA_PUBLICACIONESDESCUIDADAS", {}, ITEM_FORMULA_ROWS_READ_MODEL),
        ("ZELERDATA_TIEMPOACTIVA", {"id_publicaciones": ["MLA1"]}, ITEM_STATUS_STATES_READ_MODEL),
    ],
)
async def test_returns_histories_formulas_require_fresh_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    dispatcher = _dispatcher(FakeDb())

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("formula", "args", "read_model"),
    [
        (
            "ZELERDATA_DEVOLUCIONES",
            {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            "devoluciones",
        ),
        ("ZELERDATA_PUBLICACIONESDESCUIDADAS", {}, ITEM_FORMULA_ROWS_READ_MODEL),
        ("ZELERDATA_TIEMPOACTIVA", {"id_publicaciones": ["MLA1"]}, ITEM_STATUS_STATES_READ_MODEL),
    ],
)
async def test_returns_histories_formulas_reject_stale_read_model_marker(
    formula: str, args: dict[str, Any], read_model: str
) -> None:
    db = FakeDb()
    if formula == "ZELERDATA_DEVOLUCIONES":
        _mark_devoluciones_reconciled(db, valid_until=NOW)
    else:
        _mark_read_model_fresh(db, read_model, fresh_until=NOW - timedelta(days=1))
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match=formula) as error:
        await dispatcher.execute(_context(formula, args))

    assert read_model in str(error.value)
    assert "freshness/reconciliation" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_requires_joint_marker_when_legacy_claim_marker_is_fresh() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CLAIMS_READ_MODEL)
    dispatcher = _dispatcher(db)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await dispatcher.execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            )
        )

    assert "joint" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_uses_only_enclosing_unexpired_joint_marker() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "claim-1": _claim_doc(
            "CLAIM-1",
            order_id="ORDER-1",
            days_ago=1,
            item_id="MLA1",
            returned_quantity=1,
        )
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc(
            "ORDER-1",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=1,
        )
    }

    result = await _dispatcher(db).execute(
        _context(
            "ZELERDATA_DEVOLUCIONES",
            {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
        )
    )

    assert result.values == [["MLA1", "SKU-1", 1, "Returned item"]]
    assert db["sheets_read_model_freshness"].last_find_filter == {
        "_id": "seller-1:devoluciones",
        "seller_id": "seller-1",
        "read_model": "devoluciones",
        "state": "reconciled",
        "revision": "attempt-original",
        "proof_fingerprint": "proof-original",
        "$expr": {"$gt": ["$valid_until", "$$NOW"]},
    }


@pytest.mark.parametrize(
    ("marker_changes", "reason"),
    [
        ({"date_from": datetime(2026, 6, 2, tzinfo=UTC)}, "late"),
        ({"reconciled_until": datetime(2026, 6, 15, tzinfo=UTC)}, "early"),
        ({"date_from": datetime(2026, 6, 20, tzinfo=UTC)}, "disjoint"),
        ({"valid_until": NOW}, "expired"),
        ({"state": "stale"}, "stale"),
        ({"reconciled_until": None}, "uncertain"),
        ({"fresh_until": datetime(2026, 6, 15, tzinfo=UTC)}, "inconsistent"),
        ({"source": "legacy_marker"}, "wrong-source"),
    ],
)
@pytest.mark.asyncio
async def test_devoluciones_rejects_late_disjoint_expired_or_uncertain_joint_marker(
    marker_changes: dict[str, Any], reason: str
) -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db, **marker_changes)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES"):
        await _dispatcher(db).execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            )
        )

    assert reason


@pytest.mark.asyncio
async def test_devoluciones_rejects_separate_legacy_claim_and_order_markers() -> None:
    db = FakeDb()
    _mark_read_model_fresh(db, CLAIMS_READ_MODEL)
    _mark_read_model_fresh(db, ORDERS_READ_MODEL)

    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_DEVOLUCIONES") as error:
        await _dispatcher(db).execute(
            _context(
                "ZELERDATA_DEVOLUCIONES",
                {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
            )
        )

    assert "joint" in str(error.value)


@pytest.mark.asyncio
async def test_devoluciones_claim_range_is_half_open_at_next_utc_midnight() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        "included": _claim_doc(
            "INCLUDED",
            order_id="ORDER-1",
            days_ago=0,
            item_id="MLA1",
            returned_quantity=1,
        ),
        "excluded": {
            **_claim_doc(
                "EXCLUDED",
                order_id="ORDER-2",
                days_ago=0,
                item_id="MLA2",
                returned_quantity=9,
            ),
            "date_created": datetime(2026, 6, 16, tzinfo=UTC),
        },
    }
    db["orders"].documents = {
        "ORDER-1": _order_doc("ORDER-1", sku="sku-1", item_id="MLA1", title="Included", quantity=1),
        "ORDER-2": _order_doc("ORDER-2", sku="sku-2", item_id="MLA2", title="Excluded", quantity=1),
    }

    result = await _dispatcher(db).execute(
        _context(
            "ZELERDATA_DEVOLUCIONES",
            {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
        )
    )

    assert result.values == [["MLA1", "SKU-1", 1, "Included"]]


@pytest.mark.asyncio
async def test_devoluciones_formula_has_no_silent_five_thousand_cap() -> None:
    db = FakeDb()
    _mark_devoluciones_reconciled(db)
    db["claims"].documents = {
        f"claim-{index:05d}": {
            **_claim_doc(
                f"CLAIM-{index:05d}",
                order_id=f"ORDER-{index:05d}",
                days_ago=1,
                item_id="MLA1",
                returned_quantity=1,
            ),
            "date_created": NOW - timedelta(days=1) + timedelta(microseconds=index),
        }
        for index in range(5001)
    }
    db["orders"].documents = {
        f"ORDER-{index:05d}": _order_doc(
            f"ORDER-{index:05d}",
            sku="sku-1",
            item_id="MLA1",
            title="Returned item",
            quantity=1,
        )
        for index in range(5001)
    }

    result = await _dispatcher(db).execute(
        _context(
            "ZELERDATA_DEVOLUCIONES",
            {"fecha_inicio": "2026-06-01", "fecha_final": "2026-06-15"},
        )
    )

    assert result.values == [["MLA1", "SKU-1", 5001, "Returned item"]]
    assert result.meta["claims_count"] == 5001


def _dispatcher(db: FakeDb) -> FormulaDispatcher:
    repository = FormulaReadModelRepository(db=db)
    return FormulaDispatcher(
        build_returns_histories_withdrawals_formula_handlers(repository, now_fn=lambda: NOW)
    )


def _mark_read_model_fresh(
    db: FakeDb,
    read_model: str,
    *,
    fresh_until: datetime = NOW + timedelta(days=1),
) -> None:
    db["sheets_read_model_freshness"].documents[f"seller-1:{read_model}"] = {
        "_id": f"seller-1:{read_model}",
        "seller_id": "seller-1",
        "read_model": read_model,
        "state": "fresh",
        "fresh_until": fresh_until,
        "reconciled_until": fresh_until,
        "updated_at": NOW,
        "schema_version": 1,
    }


def _mark_devoluciones_reconciled(db: FakeDb, **changes: Any) -> None:
    marker = {
        "_id": "seller-1:devoluciones",
        "seller_id": "seller-1",
        "read_model": "devoluciones",
        "state": "reconciled",
        "date_from": datetime(2026, 6, 1, tzinfo=UTC),
        "fresh_until": datetime(2026, 6, 16, tzinfo=UTC),
        "reconciled_until": datetime(2026, 6, 16, tzinfo=UTC),
        "last_event_synced_at": datetime(2026, 6, 1, tzinfo=UTC),
        "valid_until": NOW + timedelta(minutes=30),
        "updated_at": NOW,
        "source": "zelerdata_devoluciones_joint_reconcile",
        "revision": "attempt-original",
        "proof_fingerprint": "proof-original",
        "schema_version": 1,
    }
    marker.update(changes)
    db["sheets_read_model_freshness"].documents["seller-1:devoluciones"] = marker


def _context(formula: str, args: dict[str, Any]) -> FormulaExecutionContext:
    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="seller-1",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
    )


def _claim_doc(
    claim_id: str,
    *,
    order_id: str,
    days_ago: int,
    status: str = "opened",
    claim_type: str = "returns",
    returned_quantity: int | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    document = {
        "_id": claim_id,
        "seller_id": "seller-1",
        "order_id": order_id,
        "status": status,
        "stage": "claim",
        "type": claim_type,
        "date_created": NOW - timedelta(days=days_ago),
        "schema_version": 1,
    }
    if item_id is not None:
        document["item_id"] = item_id
    if returned_quantity is not None:
        document["returned_quantity"] = returned_quantity
    return document


def _order_doc(
    order_id: str,
    *,
    sku: str,
    item_id: str,
    title: str,
    quantity: int,
) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": "seller-1",
        "date_created": NOW - timedelta(days=1),
        "status": "paid",
        "items": [
            {
                "sku": sku,
                "item_id": item_id,
                "title": title,
                "quantity": quantity,
            }
        ],
    }


def _order_doc_from_lines(order_id: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_id": order_id,
        "seller_id": "seller-1",
        "date_created": NOW - timedelta(days=1),
        "status": "paid",
        "items": lines,
    }


def _item_row(
    *,
    item_id: str,
    sku: str,
    title: str,
    status: str,
    available_quantity: int,
    paused_since: datetime,
    logistic_type: str,
    unavailable_quantity: int | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    current: dict[str, Any] = {
        "title": title,
        "status": status,
        "available_quantity": available_quantity,
        "paused_since": paused_since,
        "base_price": Decimal("120"),
        "shipping_logistic_type": logistic_type,
        "permalink": f"https://meli.example/{item_id}",
        "listing_type_id": "gold_pro",
        "inventory_id": f"INV-{item_id}",
    }
    if unavailable_quantity is not None or unavailable_reason is not None:
        current["unavailable_details"] = {
            "quantity": unavailable_quantity,
            "reason": unavailable_reason,
        }
    return {
        "_id": f"seller-1:{sku.upper()}:{item_id}",
        "seller_id": "seller-1",
        "item_id": item_id,
        "sku": sku,
        "normalized_sku": sku.upper(),
        "inventory_id": f"INV-{item_id}",
        "current": current,
    }


def _matches(doc: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    for key, expected in filter_spec.items():
        if key == "$and":
            if not all(_matches(doc, branch) for branch in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        if key == "$expr":
            left, right = expected["$gt"]
            left_value = _dotted_value(doc, str(left).removeprefix("$"))
            right_value = NOW if right == "$$NOW" else right
            if left_value is None or left_value <= right_value:
                return False
            continue
        value = _dotted_value(doc, key)
        if isinstance(expected, dict):
            try:
                if "$in" in expected and value not in expected["$in"]:
                    return False
                if "$ne" in expected and value == expected["$ne"]:
                    return False
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$gt" in expected and value <= expected["$gt"]:
                    return False
                if "$lt" in expected and value >= expected["$lt"]:
                    return False
                if "$lte" in expected and value > expected["$lte"]:
                    return False
            except TypeError:
                return False
        elif value != expected:
            return False
    return True


def _dotted_value(doc: dict[str, Any], key: str) -> Any:
    current: Any = doc
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
