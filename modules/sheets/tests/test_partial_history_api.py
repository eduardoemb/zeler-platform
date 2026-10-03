"""Product-route evidence, not just a private repository read (disposable rs0)."""

# ruff: noqa: S106 -- public disposable fixture pepper, never a runtime secret.

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from test_partial_history import END, OBSERVED, START, Worker, seed
from test_partial_history import db as db

from zeler_sheets.api import build_router
from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope
from zeler_sheets.formulas.refresh import reconciled_marker
from zeler_sheets.partial_history import advance_partial_history


async def product_client(database: Any) -> tuple[httpx.AsyncClient, str]:
    app = FastAPI()
    app.state.mongo_db = database
    app.include_router(build_router(clock=lambda: OBSERVED, extension_token_pepper="local-test"))
    issued = await ExtensionTokenService(
        db=database, token_pepper="local-test", now_fn=lambda: OBSERVED
    ).create_token(
        owner_user_id="isolated-user",
        label="isolated product test",
        seller_scopes=[SellerScope(seller_id="123", nickname="PILOT")],
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ), issued.token_once


async def execute(
    client: httpx.AsyncClient, token: str, *, formula: str = "ZELERDATA_ORDENES", **kwargs: Any
) -> httpx.Response:
    return await client.post(
        "/sheets/formulas:execute",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "formula": formula,
            "cuenta": "PILOT",
            "args": {"fecha_inicial": START.isoformat(), "fecha_final": END.isoformat()},
            **kwargs,
        },
    )


@pytest.mark.asyncio
async def test_normal_api_partial_is_explicit_and_defaults_and_totals_stay_exact(db: Any) -> None:
    job = await seed(db)
    await advance_partial_history(db=db, worker=Worker({"1"}), job=job, max_details=3)
    client, token = await product_client(db)
    async with client:
        response = await execute(client, token, allow_partial=True)
        body = response.json()
        assert response.status_code == 200 and body["ok"], body
        assert body["meta"]["coverage"]["exact"] is False
        assert body["meta"]["coverage"]["scope"] == "acquired_rows_only"
        assert "PARCIAL" in body["values"][0][0]
        assert len(body["values"][0]) == len(body["values"][1]) == 13
        assert {row[1] for row in body["values"][1:]} == {"2", "3"}
        assert all(row[10] == "NA" for row in body["values"][1:])
        exact = await execute(client, token)
        assert exact.json()["error"]["code"] == "DATA_UNAVAILABLE"
        totals = await execute(client, token, formula="ZELERDATA_VENTASTOTALES")
        assert totals.json()["error"]["code"] == "DATA_UNAVAILABLE"
        invalid = await execute(
            client, token, formula="ZELERDATA_VENTASTOTALES", allow_partial=True
        )
        assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "BAD_ARGUMENT"
        unauthenticated = await execute(client, "wrong", allow_partial=True)
        assert unauthenticated.json()["error"]["code"] == "TOKEN_REVOKED"
        forged = await execute(
            client,
            token,
            args={
                "fecha_inicial": START.isoformat(),
                "fecha_final": END.isoformat(),
                "_allow_partial": True,
            },
        )
        assert forged.json()["error"]["code"] == "DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_normal_api_9999_usable_orders_one_pending_and_independent_range(db: Any) -> None:
    async with asyncio.timeout(400):
        await seed(db, count=10000)
        worker = Worker({"5000"})
        for _ in range(510):
            saved = await db.sheets_formula_recovery_jobs.find_one({"_id": "job"})
            result = await advance_partial_history(db=db, worker=worker, job=saved, max_details=20)
            if result["complete"]:
                break
        assert result["complete"] and result["persisted"] == 9999 and result["pending_count"] == 1
        healthy_start = START.replace(month=5)
        marker = reconciled_marker(
            seller_id="123", read_model="orders", start=healthy_start, end=START, now=OBSERVED
        )
        await db.sheets_read_model_freshness.insert_one(marker)
        client, token = await product_client(db)
        async with client:
            body = (await execute(client, token, allow_partial=True)).json()
            assert body["ok"], body
            assert body["meta"]["orders_count"] == 9999
            assert len(body["values"]) == 10000  # explicit notice + 9999 actual order lines
            identities = {row[1] for row in body["values"][1:]}
            assert identities == {str(i) for i in range(1, 10001)} - {"5000"}
            assert all(row[5] == 1 and row[6] == 10 and row[9] == 1 for row in body["values"][1:])
            assert body["meta"]["coverage"]["exact"] is False
            assert body["meta"]["coverage"]["date_from"] == START.isoformat()
            assert body["meta"]["coverage"]["date_to"] == END.isoformat()
            assert "no es un total" in body["values"][0][0]
            assert (await execute(client, token)).json()["error"]["code"] == "DATA_UNAVAILABLE"
            assert (await execute(client, token, formula="ZELERDATA_VENTASTOTALES")).json()[
                "error"
            ]["code"] == "DATA_UNAVAILABLE"
            healthy = (
                await execute(
                    client,
                    token,
                    args={
                        "fecha_inicial": healthy_start.isoformat(),
                        "fecha_final": START.isoformat(),
                    },
                )
            ).json()
            assert healthy["ok"] and healthy["values"] == []
        assert await db.sheets_read_model_freshness.find_one({"_id": marker["_id"]}) == marker
        assert await db.sheets_history_pending_records.count_documents({"seller_id": "123"}) == 1


@pytest.mark.asyncio
async def test_partial_empty_is_notice_not_certified_zero_and_strict_opt_in(db: Any) -> None:
    client, token = await product_client(db)
    async with client:
        body = (await execute(client, token, allow_partial=True)).json()
        assert body["ok"] and body["meta"]["orders_count"] == 0
        assert body["meta"]["coverage"]["exact"] is False
        assert len(body["values"]) == 1 and "PARCIAL" in body["values"][0][0]
        invalid = await execute(client, token, allow_partial="true")
        assert invalid.status_code == 422
        assert (await execute(client, token)).json()["error"]["code"] == "DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_certified_opt_in_keeps_existing_table_and_headers(db: Any) -> None:
    await db.sheets_read_model_freshness.insert_one(
        reconciled_marker(seller_id="123", read_model="orders", start=START, end=END, now=OBSERVED)
    )
    job = await seed(db)
    await advance_partial_history(db=db, worker=Worker(), job=job, max_details=3)
    client, token = await product_client(db)
    args = {"fecha_inicial": START.isoformat(), "fecha_final": END.isoformat(), "encabezados": "si"}
    async with client:
        exact = (await execute(client, token, args=args)).json()
        optional = (await execute(client, token, allow_partial=True, args=args)).json()
        assert exact == optional
        assert exact["ok"] and exact["values"][0][1] == "ID Orden"
        assert len(exact["values"]) == 4 and "coverage" not in exact["meta"]


@pytest.mark.asyncio
async def test_progress_exposes_bounded_old_pack_recovery_without_private_targets(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_pilot_sheets_config_progress import SELLER, _app

    await db.sheets_history_backfill_plans.insert_one(
        {
            "_id": SELLER,
            "seller_id": SELLER,
            "onboarding_status": "ready_with_observations",
            "message_periodic_recovery": {
                "state": "running",
                "packs_completed": 14,
                "persisted": 28,
                "checkpoint": {
                    "target_ids": ["private-pack-a", "private-pack-b"],
                    "target_index": 1,
                    "offset": 50,
                    "persisted": 3,
                    "issue_count": 1,
                },
            },
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(monkeypatch, db)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sheets/backfill/progress",
            params={"seller_id": SELLER},
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    progress = response.json()["message_periodic_recovery"]
    assert progress["packs_completed"] == 14 and progress["batch_size"] == 2
    assert progress["persisted"] == 31 and progress["max_requests_per_turn"] == 2
    assert progress["coverage_complete"] is False
    assert "private-pack" not in response.text and "target_ids" not in response.text
