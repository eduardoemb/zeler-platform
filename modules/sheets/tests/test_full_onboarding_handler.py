"""Protection evidence, not an authenticated provider fixture or completed mapping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from zeler_sheets.formulas.dispatcher import (
    FormulaDataUnavailableError,
    FormulaDispatcher,
    FormulaExecutionContext,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    build_remaining_phase4_formula_handlers,
)
from zeler_sheets.formulas.read_models import (
    FULL_WITHDRAWALS_READ_MODEL,
    FormulaReadModelRepository,
)
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.onboarding_sources import collect_full_operations

START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)
SELLER = "123"


@pytest_asyncio.fixture
async def full_db() -> AsyncIterator[Any]:
    # Dedicated loopback rs0 only; do not inherit an ambient potentially real MONGO_URI.
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27028/?replicaSet=rs0&directConnection=true",
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
    )
    database = client["zeler_full_handler_" + uuid4().hex]
    try:
        hello = await client.admin.command("hello")
        assert hello["isWritablePrimary"] and hello["setName"] == "rs0"
        yield database
    finally:
        await client.drop_database(database.name)
        client.close()


class DocumentaryOperationGateway:
    """Documented operation fields with explicitly synthetic, unproven references.

    Official Full docs specify inventory, seller, operation ID/date/type, deltas,
    and external references. They do NOT establish a withdrawal/package mapping.
    Adding a plausible field name must not magically make that mapping authentic.
    """

    def __init__(self, *, candidate_reference: bool) -> None:
        self.candidate_reference = candidate_reference
        self.paths: list[str] = []

    async def fetch_resource(self, *, seller_id: str, path: str) -> dict[str, Any]:
        assert seller_id == SELLER
        self.paths.append(path)
        params = parse_qs(urlsplit(path).query)
        assert params["seller_id"] == [SELLER]
        kind = params["type"][0]
        if kind not in {"WITHDRAWAL_RESERVATION", "WITHDRAWAL_DELIVERY"}:
            return {"paging": {"scroll": None}, "results": []}
        reservation = kind == "WITHDRAWAL_RESERVATION"
        return {
            "paging": {"scroll": None},
            "results": [
                {
                    "id": 501 if reservation else 502,
                    "seller_id": int(SELLER),
                    "inventory_id": "INV1",
                    "date_created": (
                        "2026-06-03T10:00:00Z" if reservation else "2026-06-05T11:00:00Z"
                    ),
                    "type": kind,
                    "detail": {
                        "available_quantity": -4 if reservation else 0,
                        "not_available_quantity": 4 if reservation else -4,
                        "not_available_detail": [
                            {"status": "withdrawal", "quantity": 4 if reservation else -4}
                        ],
                    },
                    "external_references": (
                        [{"type": "withdrawal_id", "value": "12345678901"}]
                        if self.candidate_reference
                        else []
                    ),
                }
            ],
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_reference", [False, True])
async def test_collected_stock_operations_cannot_unlock_normal_retiros_handler(
    full_db: Any, candidate_reference: bool
) -> None:
    await full_db.items.insert_one(
        {
            "_id": "MLM1",
            "seller_id": SELLER,
            "inventory_id": "INV1",
            "shipping": {"logistic_type": "fulfillment"},
            "variations": [],
        }
    )
    gateway = DocumentaryOperationGateway(candidate_reference=candidate_reference)
    result = await collect_full_operations(
        db=full_db,
        gateway=gateway,
        seller_id=SELLER,
        start=START,
        end=END,
        max_requests=5,
        now=END,
    )
    assert len(gateway.paths) == 5
    assert result["discovery_complete"]
    assert result["persisted"] == 2
    assert result["blocked_reason"] == "full_withdrawal_contract_incompatible"
    assert not result["coverage_complete"]
    assert await full_db.sheets_full_operations.count_documents({"seller_id": SELLER}) == 2
    stored = await full_db.sheets_full_operations.find_one({"operation_id": "501"})
    assert stored["detail"]["not_available_detail"][0]["quantity"] == 4
    if candidate_reference:
        assert stored["external_references"][0]["value"] == "12345678901"
    assert await full_db.sheets_full_withdrawals.count_documents({}) == 0
    assert await full_db.sheets_read_model_freshness.count_documents({}) == 0

    # This is the real product handler/dispatcher and Mongo reader, not a direct
    # repository-row assertion or a fake method made to raise the desired error.
    dispatcher = FormulaDispatcher(
        build_remaining_phase4_formula_handlers(FormulaReadModelRepository(db=full_db))
    )
    context = FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required("ZELERDATA_RETIROS"),
        cuenta="LOCAL_FIXTURE",
        seller_id=SELLER,
        seller_nickname="LOCAL_FIXTURE",
        token_id=uuid4().hex,
        args={"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30"},
        request_id="full-protection-local",
    )
    with pytest.raises(FormulaDataUnavailableError, match="ZELERDATA_RETIROS") as error:
        await dispatcher.execute(context)
    assert error.value.read_model == FULL_WITHDRAWALS_READ_MODEL
    assert error.value.date_from == START
    assert error.value.date_to == END
    assert await full_db.sheets_full_withdrawals.count_documents({}) == 0
