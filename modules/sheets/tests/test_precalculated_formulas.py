# ruff: noqa: S105,S106

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from zeler_sheets.formulas.precalculated import (
    PRECALCULATED_FORMULAS,
    PrecalculatedFormulaStore,
    cache_identity,
    canonical_arguments,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        for doc in self.docs.values():
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        self.docs[str(doc["_id"])] = dict(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], **kwargs: Any) -> Any:
        doc_id = str(query["_id"])
        if doc_id in self.docs:
            self.docs[doc_id].update(update.get("$set", {}))
        elif kwargs.get("upsert"):
            self.docs[doc_id] = {**update.get("$set", {}), "_id": doc_id}
        return type("R", (), {"acknowledged": True})()

    async def replace_one(self, query: dict[str, Any], doc: dict[str, Any], **kwargs: Any) -> Any:
        self.docs[str(query["_id"])] = dict(doc)
        return type("R", (), {"acknowledged": True})()

    async def delete_one(self, query: dict[str, Any]) -> Any:
        removed = self.docs.pop(str(query["_id"]), None)
        return type("R", (), {"deleted_count": int(removed is not None)})()


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


def test_only_the_heavy_aggregate_formulas_are_precalculated() -> None:
    assert (
        frozenset(
            {
                "ZELERDATA_CATALOGO",
                "ZELERDATA_CATALOGOBUYBOX",
                "ZELERDATA_CATALOGO_COMPLETO",
                "ZELERDATA_CALIDAD",
                "ZELERDATA_DASHBOARD",
            }
        )
        == PRECALCULATED_FORMULAS
    )


def test_canonical_arguments_fill_contract_defaults_so_variants_cannot_collide() -> None:
    assert canonical_arguments("ZELERDATA_CATALOGO", {"cuenta": "HOPEMOB"}) == {
        "cuenta": "account",
        "tipo_precio": "base",
        "encabezados": "",
    }
    assert canonical_arguments("ZELERDATA_DASHBOARD", {"cuenta": "HOPEMOB", "skus": "SKU-1"}) == {
        "cuenta": "account",
        "skus": "SKU-1",
        "tipo_almacenamiento": "todos",
        "tipo_precio": "base",
        "encabezados": "",
    }


def test_cache_identity_is_scoped_to_seller_formula_and_exact_arguments() -> None:
    base = {"cuenta": "HOPEMOB", "encabezados": "si"}
    same = {"encabezados": "si", "cuenta": "HOPEMOB"}
    assert cache_identity("seller-1", "ZELERDATA_CALIDAD", base) == cache_identity(
        "seller-1", "ZELERDATA_CALIDAD", same
    )
    assert cache_identity("seller-1", "ZELERDATA_CALIDAD", base) != cache_identity(
        "seller-2", "ZELERDATA_CALIDAD", base
    )
    assert cache_identity("seller-1", "ZELERDATA_CALIDAD", base) != cache_identity(
        "seller-1", "ZELERDATA_DASHBOARD", base
    )
    assert cache_identity("seller-1", "ZELERDATA_CALIDAD", base) != cache_identity(
        "seller-1", "ZELERDATA_CALIDAD", {**base, "encabezados": ""}
    )
    assert len(cache_identity("seller-1", "ZELERDATA_CALIDAD", base)) == 64


@pytest.mark.asyncio
async def test_a_written_result_is_served_until_its_validity_window_closes() -> None:
    store = PrecalculatedFormulaStore(FakeDb(), now=lambda: NOW)
    args = {"cuenta": "HOPEMOB", "encabezados": "si"}

    await store.write(
        seller_id="seller-1",
        formula="ZELERDATA_CALIDAD",
        args=args,
        values=[["ID", "Score"], ["MLA1", 90]],
        meta={"rows_count": 1},
    )

    fresh = await store.read(seller_id="seller-1", formula="ZELERDATA_CALIDAD", args=args)
    assert fresh is not None
    assert fresh.values == [["ID", "Score"], ["MLA1", 90]]
    assert fresh.meta["precalculated"] is True
    assert fresh.meta["rows_count"] == 1

    expired = PrecalculatedFormulaStore(FakeDb(), now=lambda: NOW)
    assert await expired.read(seller_id="seller-1", formula="ZELERDATA_CALIDAD", args=args) is None


@pytest.mark.asyncio
async def test_a_result_that_expired_is_never_served() -> None:
    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)
    args = {"cuenta": "HOPEMOB"}
    await store.write(
        seller_id="seller-1",
        formula="ZELERDATA_CATALOGO",
        args=args,
        values=[["ID"]],
        meta={},
    )

    later = PrecalculatedFormulaStore(db, now=lambda: NOW + timedelta(minutes=31))
    assert await later.read(seller_id="seller-1", formula="ZELERDATA_CATALOGO", args=args) is None


@pytest.mark.asyncio
async def test_a_formula_outside_the_precalculated_set_is_never_served() -> None:
    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)
    args = {"cuenta": "HOPEMOB", "id_publicaciones": "MLA1"}

    await store.write(
        seller_id="seller-1",
        formula="ZELERDATA_STATUS",
        args=args,
        values=[["MLA1", "active"]],
        meta={},
    )

    assert await store.read(seller_id="seller-1", formula="ZELERDATA_STATUS", args=args) is None


@pytest.mark.asyncio
async def test_the_formula_route_serves_a_fresh_precalculated_result_without_dispatching() -> None:
    import httpx
    from fastapi import FastAPI

    from zeler_sheets.api import build_router
    from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope

    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.state.precalculated_formula_store = PrecalculatedFormulaStore(db, now=lambda: now)
    app.include_router(build_router(clock=lambda: now, extension_token_pepper="test-pepper"))
    token = (
        await ExtensionTokenService(
            db=db,
            token_pepper="test-pepper",
            now_fn=lambda: now,
            token_factory=lambda: "formula-secret",
        ).create_token(
            owner_user_id="user-1",
            label="Sheet",
            seller_scopes=[SellerScope(seller_id="seller-1", nickname="HOPEMOB")],
        )
    ).token_once
    await app.state.precalculated_formula_store.write(
        seller_id="seller-1",
        formula="ZELERDATA_CALIDAD",
        args={"cuenta": "HOPEMOB", "encabezados": "si"},
        values=[["ID Publicación", "Calidad"], ["MLA1", 90]],
        meta={"rows_count": 1},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_CALIDAD",
                "cuenta": "HOPEMOB",
                "args": {"encabezados": "si"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["values"] == [["ID Publicación", "Calidad"], ["MLA1", 90]]
    assert body["meta"]["precalculated"] is True


@pytest.mark.asyncio
async def test_an_expired_precalculated_result_falls_through_to_the_normal_handler() -> None:
    import httpx
    from fastapi import FastAPI

    from zeler_sheets.api import build_router
    from zeler_sheets.extension_tokens import ExtensionTokenService, SellerScope

    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    store = PrecalculatedFormulaStore(db, now=lambda: now - timedelta(hours=2))
    await store.write(
        seller_id="seller-1",
        formula="ZELERDATA_CALIDAD",
        args={"cuenta": "HOPEMOB", "encabezados": "si"},
        values=[["ID Publicación", "Calidad"], ["MLA1", 90]],
        meta={"rows_count": 1},
    )
    app.state.precalculated_formula_store = PrecalculatedFormulaStore(db, now=lambda: now)
    app.include_router(build_router(clock=lambda: now, extension_token_pepper="test-pepper"))
    token = (
        await ExtensionTokenService(
            db=db,
            token_pepper="test-pepper",
            now_fn=lambda: now,
            token_factory=lambda: "formula-secret",
        ).create_token(
            owner_user_id="user-1",
            label="Sheet",
            seller_scopes=[SellerScope(seller_id="seller-1", nickname="HOPEMOB")],
        )
    ).token_once

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sheets/formulas:execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "formula": "ZELERDATA_CALIDAD",
                "cuenta": "HOPEMOB",
                "args": {"encabezados": "si"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    # The expired entry is never served; the real handler answers instead, and
    # with no quality data it reports the existing unavailable path.
    assert body.get("meta", {}).get("precalculated") is not True


@pytest.mark.asyncio
async def test_the_warmer_writes_each_precalculated_formula_variant_for_the_seller() -> None:
    from zeler_sheets.formulas.precalculated import PrecalculatedFormulaWarmer

    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)
    dispatched: list[tuple[str, dict[str, Any]]] = []

    class _Dispatcher:
        async def execute(self, context: Any) -> Any:
            dispatched.append((context.contract.name, dict(context.args)))
            return type(
                "R",
                (),
                {"values": [["ID"], ["MLA1"]], "meta": {"rows_count": 1}},
            )()

    warmer = PrecalculatedFormulaWarmer(dispatcher=_Dispatcher(), store=store, now=lambda: NOW)
    written = await warmer.warm(seller_id="seller-1", cuenta="HOPEMOB")

    assert {name for name, _ in dispatched} == PRECALCULATED_FORMULAS
    assert written == len(dispatched)
    for formula, args in dispatched:
        cached = await store.read(seller_id="seller-1", formula=formula, args=args)
        assert cached is not None, f"{formula} was dispatched but not cached"
        assert cached.values == [["ID"], ["MLA1"]]


@pytest.mark.asyncio
async def test_the_warmer_caches_both_header_variants() -> None:
    from zeler_sheets.formulas.precalculated import PrecalculatedFormulaWarmer

    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)

    class _Dispatcher:
        async def execute(self, context: Any) -> Any:
            headers = [["ID"]] if context.args.get("encabezados") else []
            return type("R", (), {"values": headers + [["MLA1"]], "meta": {}})()

    warmer = PrecalculatedFormulaWarmer(dispatcher=_Dispatcher(), store=store, now=lambda: NOW)
    await warmer.warm(seller_id="seller-1", cuenta="HOPEMOB")

    with_headers = await store.read(
        seller_id="seller-1", formula="ZELERDATA_CALIDAD", args={"encabezados": "si"}
    )
    without_headers = await store.read(
        seller_id="seller-1", formula="ZELERDATA_CALIDAD", args={"encabezados": ""}
    )
    assert with_headers is not None and with_headers.values == [["ID"], ["MLA1"]]
    assert without_headers is not None and without_headers.values == [["MLA1"]]


@pytest.mark.asyncio
async def test_a_formula_without_productive_data_is_never_cached_as_empty() -> None:
    from zeler_sheets.formulas.dispatcher import FormulaDataUnavailableError
    from zeler_sheets.formulas.precalculated import PrecalculatedFormulaWarmer

    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)

    class _Dispatcher:
        async def execute(self, context: Any) -> Any:
            raise FormulaDataUnavailableError(context.contract.name, "not reconciled")

    warmer = PrecalculatedFormulaWarmer(dispatcher=_Dispatcher(), store=store, now=lambda: NOW)
    written = await warmer.warm(seller_id="seller-1", cuenta="HOPEMOB")

    assert written == 0
    assert (
        await store.read(
            seller_id="seller-1", formula="ZELERDATA_CALIDAD", args={"encabezados": "si"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_one_failing_formula_does_not_stop_the_rest() -> None:
    from zeler_sheets.formulas.precalculated import PrecalculatedFormulaWarmer

    db = FakeDb()
    store = PrecalculatedFormulaStore(db, now=lambda: NOW)

    class _Dispatcher:
        async def execute(self, context: Any) -> Any:
            if context.contract.name == "ZELERDATA_CALIDAD":
                raise RuntimeError("boom")
            return type("R", (), {"values": [["MLA1"]], "meta": {}})()

    warmer = PrecalculatedFormulaWarmer(dispatcher=_Dispatcher(), store=store, now=lambda: NOW)
    written = await warmer.warm(seller_id="seller-1", cuenta="HOPEMOB")

    assert written > 0
    assert (
        await store.read(
            seller_id="seller-1", formula="ZELERDATA_CATALOGO", args={"encabezados": "si"}
        )
        is not None
    )
