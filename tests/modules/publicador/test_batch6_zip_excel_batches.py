from __future__ import annotations

import base64
import io
import zipfile
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = docs or []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                return doc
        return None

    async def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(doc)

    async def replace_one(
        self, query: dict[str, Any], replacement: dict[str, Any], *, upsert: bool
    ) -> None:
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs[index] = replacement
                return
        if upsert:
            self.docs.append(replacement)


class FakeDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


@pytest.mark.parametrize("root_folder", [None, "lote-publicador"])
def test_legacy_zip_excel_parser_accepts_root_or_first_folder_contract(
    root_folder: str | None,
) -> None:
    from zeler_publicador.batch_parser import parse_legacy_batch_zip

    parsed = parse_legacy_batch_zip(
        _legacy_zip(
            account="MLM-1",
            rows=[_row("SKU-1"), _row("SKU-2", envio_gratis="NO")],
            image_skus=["SKU-1", "SKU-2"],
            root_folder=root_folder,
        )
    )

    assert parsed.account_id == "MLM-1"
    assert [row.sku for row in parsed.rows] == ["SKU-1", "SKU-2"]
    assert parsed.rows[0].publicar == "SI"
    assert parsed.rows[0].errors == []
    assert parsed.rows[0].images[0].filename == "front.png"
    assert parsed.rows[1].free_shipping is False


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("invalid_marker", "Cuenta Mercado Libre"),
        ("missing_column", "CodigoBarras"),
        ("without_excel", "No se encontró ningún archivo Excel"),
    ],
)
def test_legacy_zip_excel_parser_rejects_global_contract_violations(
    case: str, message: str
) -> None:
    from zeler_publicador.batch_parser import LegacyBatchContractError, parse_legacy_batch_zip

    zip_content = {
        "invalid_marker": _legacy_zip(account="MLM-1", marker="Cuenta:"),
        "missing_column": _legacy_zip(account="MLM-1", omit_columns=["CodigoBarras"]),
        "without_excel": _zip_without_excel(),
    }[case]

    with pytest.raises(LegacyBatchContractError, match=message):
        parse_legacy_batch_zip(zip_content)


def test_legacy_zip_excel_parser_blocks_invalid_rows_and_sku_folder_mismatches() -> None:
    from zeler_publicador.batch_parser import parse_legacy_batch_zip

    parsed = parse_legacy_batch_zip(
        _legacy_zip(
            account="MLM-1",
            rows=[
                _row("SKU-1"),
                _row("SKU-2", codigo_barras="ABC", precio="0", tipo_logistica="carrier"),
                _row("SKU-3", publicar="NO"),
            ],
            image_skus=["SKU-1", "SKU-EXTRA"],
        )
    )

    by_sku = {row.sku: row for row in parsed.rows}
    assert by_sku["SKU-1"].errors == []
    assert by_sku["SKU-2"].publicar == "NO"
    assert by_sku["SKU-2"].errors == [
        "CodigoBarras must be numeric",
        "Precio must be greater than 0",
        "TipoLogistica carrier is not accepted",
        "SKU folder SKU-2 must contain between 3 and 10 images",
    ]
    assert by_sku["SKU-3"].errors == ["Publicar is NO in the Excel row"]
    assert parsed.global_warnings == ["SKU folder SKU-EXTRA is not present in Excel rows"]


@pytest.mark.asyncio
async def test_batch_upload_persists_items_with_row_errors_and_idempotency() -> None:
    from zeler_publicador.batches import PublicadorBatchService

    db = FakeDb()
    service = PublicadorBatchService(
        db,
        clock=lambda: datetime(2026, 5, 16, 23, 0, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db[f'publicador_{prefix}s'].docs) + 1}",
    )
    zip_content = _legacy_zip(
        account="MLM-1",
        rows=[_row("SKU-1"), _row("SKU-2", precio="-1")],
        image_skus=["SKU-1"],
    )

    created = await service.create_from_zip(
        seller_id="111",
        account_id="MLM-1",
        source_filename="legacy.zip",
        content=zip_content,
        actor_id="operator-1",
    )
    duplicate = await service.create_from_zip(
        seller_id="111",
        account_id="MLM-1",
        source_filename="legacy.zip",
        content=zip_content,
        actor_id="operator-2",
    )

    assert duplicate["_id"] == created["_id"]
    assert len(db["publicador_batches"].docs) == 1
    assert created["status"] == "preview_ready"
    assert created["counts"] == {
        "total": 2,
        "queued": 1,
        "blocked": 1,
        "processed": 0,
        "published": 0,
        "failed": 0,
    }
    items = db["publicador_batch_items"].docs
    assert [(item["sku"], item["status"], item["publicar"], item["errors"]) for item in items] == [
        ("SKU-1", "queued", "SI", []),
        (
            "SKU-2",
            "blocked",
            "NO",
            [
                "Precio must be greater than 0",
                "SKU folder SKU-2 must contain between 3 and 10 images",
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_process_and_publish_batch_converts_valid_rows_to_drafts_and_paused_stock() -> None:
    from zeler_publicador.batches import PublicadorBatchService

    db = FakeDb()
    gateway = _FakeMeliGateway()
    service = PublicadorBatchService(
        db,
        meli_gateway=gateway,
        clock=lambda: datetime(2026, 5, 16, 23, 5, tzinfo=UTC),
        id_factory=lambda prefix: f"{prefix}-{len(db[f'publicador_{prefix}s'].docs) + 1}",
    )
    created = await service.create_from_zip(
        seller_id="111",
        account_id="MLM-1",
        source_filename="legacy.zip",
        content=_legacy_zip(account="MLM-1", rows=[_row("SKU-1")], image_skus=["SKU-1"]),
        actor_id="operator-1",
    )

    processed = await service.process_batch(
        seller_id="111", account_id="MLM-1", batch_id=created["_id"], actor_id="operator-2"
    )
    published = await service.publish_batch(
        seller_id="111", account_id="MLM-1", batch_id=created["_id"], actor_id="operator-3"
    )

    publish_payload = next(call[2] for call in gateway.calls if call[:2] == ("POST", "/items"))
    assert publish_payload is not None
    assert processed["status"] == "processed"
    assert db["publicador_batch_items"].docs[0]["draft_id"] == "draft-1"
    assert db["publicador_drafts"].docs[0]["sku"] == "SKU-1"
    assert published["status"] == "published"
    assert db["publicador_batch_items"].docs[0]["status"] == "published"
    assert publish_payload["status"] == "paused"
    assert publish_payload["available_quantity"] == 0
    assert publish_payload["attributes"] == [{"id": "GTIN", "value_name": "7501234567890"}]


@pytest.mark.asyncio
async def test_publicador_batch_api_upload_review_process_publish_contracts_are_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zeler_publicador.api as api
    from zeler_platform_core.auth.jwt import ModuleClaims
    from zeler_publicador.api import build_router

    db = FakeDb()
    app = FastAPI()
    app.state.mongo_db = db
    app.state.publicador_meli_gateway = _FakeMeliGateway()
    app.include_router(build_router(generator=_FakeGenerator(), publisher=_FakePublisher()))

    def fake_verify(_token: str) -> ModuleClaims:
        return ModuleClaims(
            module_id="publicador",
            seller_id=111,
            iss="module:publicador",
            aud="gateway",
            iat=1,
            exp=2,
            token_type="module_admin",  # noqa: S106 - test fixture token type, not a secret
            scopes=["admin:publicador"],
            issued_by="zeler-app",
        )

    monkeypatch.setattr(api, "verify_module_jwt", fake_verify)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        uploaded = await client.post(
            "/publicador/batches",
            headers={"Authorization": "Bearer valid"},
            json={
                "seller_id": "111",
                "account_id": "MLM-1",
                "source_filename": "legacy.zip",
                "content_base64": base64.b64encode(
                    _legacy_zip(account="MLM-1", rows=[_row("SKU-1")], image_skus=["SKU-1"])
                ).decode(),
                "created_by": "operator-1",
            },
        )
        batch_id = uploaded.json()["_id"]
        listed = await client.get(
            "/publicador/batches?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
        )
        detail = await client.get(
            f"/publicador/batches/{batch_id}?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
        )
        processed = await client.post(
            f"/publicador/batches/{batch_id}/process?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"actor_id": "operator-2"},
        )
        published = await client.post(
            f"/publicador/batches/{batch_id}/publish?seller_id=111&account_id=MLM-1",
            headers={"Authorization": "Bearer valid"},
            json={"actor_id": "operator-3"},
        )

    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == "preview_ready"
    assert listed.json()[0]["_id"] == batch_id
    assert detail.json()["items"][0]["sku"] == "SKU-1"
    assert processed.json()["status"] == "processed"
    assert published.json()["status"] == "published"


class _FakeMeliGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, path, json))
        if (method, path) == ("GET", "/categories/MLM-BATCH/attributes"):
            return []
        if (method, path) == ("GET", "/sites/MLM/listing_types"):
            return [{"id": "premium", "name": "Premium"}]
        if (method, path) == ("GET", "/users/111/shipping_preferences"):
            return {"logistics": [{"type": "drop off", "label": "Drop off"}]}
        if (method, path) == ("GET", "/users/111/brands"):
            return []
        if (method, path) == ("GET", "/users/111/stores/search"):
            return []
        if (method, path) == ("POST", "/items/validate"):
            return {"status": "ok", "field_errors": []}
        if (method, path) == ("POST", "/items"):
            return {"id": "MLM123", "permalink": "https://meli.example/MLM123"}
        raise AssertionError(f"unexpected gateway call {method} {path}")


class _FakeGenerator:
    async def generate(self, _product: object) -> object:
        raise AssertionError("not used in Batch 6 tests")


class _FakePublisher:
    async def publish(self, _draft_id: str) -> object:
        raise AssertionError("not used in Batch 6 tests")


def _legacy_zip(
    *,
    account: str,
    rows: list[dict[str, str]] | None = None,
    image_skus: list[str] | None = None,
    root_folder: str | None = None,
    marker: str = "Cuenta Mercado Libre:",
    omit_columns: list[str] | None = None,
) -> bytes:
    rows = rows or [_row("SKU-1")]
    image_skus = image_skus or [row["SKU"] for row in rows if row.get("Publicar", "SI") == "SI"]
    prefix = f"{root_folder}/" if root_folder else ""
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            f"{prefix}plantilla.xlsx",
            _xlsx_bytes(marker=marker, account=account, rows=rows, omit_columns=omit_columns or []),
        )
        for sku in image_skus:
            for filename in ["front.png", "side.png", "back.png"]:
                archive.writestr(f"{prefix}{sku}/{filename}", _png_bytes(width=800, height=800))
    return data.getvalue()


def _zip_without_excel() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("SKU-1/front.png", _png_bytes(width=800, height=800))
    return data.getvalue()


def _row(
    sku: str,
    *,
    codigo_barras: str = "7501234567890",
    precio: str = "1299.99",
    tipo_logistica: str = "drop off",
    tipo_publicacion: str = "premium",
    envio_gratis: str = "si",
    publicar: str = "SI",
) -> dict[str, str]:
    return {
        "SKU": sku,
        "CodigoBarras": codigo_barras,
        "Precio": precio,
        "TipoLogistica": tipo_logistica,
        "TipoPublicacion": tipo_publicacion,
        "EnvioGratis": envio_gratis,
        "Publicar": publicar,
    }


def _xlsx_bytes(
    *, marker: str, account: str, rows: list[dict[str, str]], omit_columns: list[str]
) -> bytes:
    headers = [
        column
        for column in [
            "SKU",
            "CodigoBarras",
            "Precio",
            "TipoLogistica",
            "TipoPublicacion",
            "EnvioGratis",
            "Publicar",
        ]
        if column not in omit_columns
    ]
    sheet_rows = [
        [marker, account],
        headers,
        *[[row.get(header, "") for header in headers] for row in rows],
    ]
    sheet_xml = "".join(
        f'<row r="{index}">'
        f"{''.join(_cell(index, col_index, value) for col_index, value in enumerate(row, start=1))}"
        "</row>"
        for index, row in enumerate(sheet_rows, start=1)
    )
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("xl/workbook.xml", "")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet_xml}</sheetData></worksheet>',
        )
    return data.getvalue()


def _cell(row_index: int, col_index: int, value: str) -> str:
    column = chr(ord("A") + col_index - 1)
    escaped = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<c r="{column}{row_index}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def _png_bytes(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(doc.get(key) == value for key, value in query.items())
