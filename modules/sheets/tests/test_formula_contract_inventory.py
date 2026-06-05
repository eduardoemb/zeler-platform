# ruff: noqa: S105,S106

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from zeler_sheets.formulas.handlers_core import CORE_FORMULA_NAMES
from zeler_sheets.formulas.handlers_orders_questions import BATCH_B_IMPLEMENTED_FORMULAS
from zeler_sheets.formulas.registry import FormulaRegistry
from zeler_sheets.formulas.runtime_states import (
    build_explicit_unsupported_formula_handlers,
    get_formula_runtime_states,
)

FIXTURE_PATH = (
    Path(__file__).parents[3]
    / "tests"
    / "sheets"
    / "fixtures"
    / "sheetseller_formula_contracts.json"
)
COLUMN_FIXTURE_PATH = (
    Path(__file__).parents[3]
    / "tests"
    / "sheets"
    / "fixtures"
    / "sheetseller_formula_output_columns.json"
)

EXPECTED_FORMULA_SUFFIXES = [
    "PUBLICACIONES",
    "SKU",
    "ID",
    "STOCK",
    "TITULO",
    "URL",
    "PRECIO",
    "IDSTOCK",
    "STATUS",
    "PAUSADAS",
    "CODIGOML",
    "ENVIARAFULL",
    "CODIGOML2SKUID",
    "DIASPUBLICADA",
    "PUBLICACIONESDESCUIDADAS",
    "CATALOGO",
    "DASHBOARD",
    "TIEMPOSINSTOCK",
    "TIEMPOACTIVA",
    "CATALOGOSINVINCULAR",
    "CATALOGOBUYBOX",
    "COMISION",
    "DEVOLUCIONES",
    "COMPETENCIA",
    "CATALOGOTIEMPO",
    "PRECIOHISTORICO",
    "TIEMPOSTOCKACTIVO",
    "DASHBOARDSINCATALOGO",
    "CALIDAD",
    "CALCULADORA",
    "RETIROS",
    "IMAGENES",
    "SEMANASCONSTOCK",
    "MEDIDASGENERAL",
    "MEDIDAS",
    "CATEGORIAS",
    "SUPERMERCADO",
    "OBTENER_CATALOGO",
    "ORDENES",
    "UNIDADESVENDIDAS",
    "ORDENESPORSKU",
    "DIASDESDEULTIMAVENTA",
    "PRODUCTOSINVENTA",
    "VENTAPORDIAS",
    "VENTASYSTOCK",
    "TOPVENTASUNIDADES",
    "TOPVENTASDINERO",
    "COSTOENVIOVENDEDOR",
    "VENTASTOTALES",
    "COMPRADORES",
    "ENVIOSMERCADOENVIOS",
    "PREGUNTAS",
    "PREGUNTASKPI",
]
EXPECTED_FORMULA_NAMES = [f"ZELERDATA_{suffix}" for suffix in EXPECTED_FORMULA_SUFFIXES]

EXPECTED_ERROR_CODES = [
    "TOKEN_MISSING",
    "TOKEN_REVOKED",
    "SELLER_FORBIDDEN",
    "FORMULA_UNKNOWN",
    "BAD_ARGUMENT",
    "DATA_UNAVAILABLE",
    "RATE_LIMITED",
    "INTERNAL",
]

RANGE_INPUT_CASES = ["scalar", "row_range", "column_range", "rectangular_range"]


def _fixture() -> dict[str, Any]:
    loaded = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", loaded)


def _column_fixture() -> dict[str, Any]:
    loaded = json.loads(COLUMN_FIXTURE_PATH.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", loaded)


def test_fixture_locks_all_53_zelerdata_formula_names_in_order() -> None:
    fixture = _fixture()
    contracts = fixture["contracts"]

    assert [contract["name"] for contract in contracts] == EXPECTED_FORMULA_NAMES
    assert len({contract["name"] for contract in contracts}) == 53
    assert fixture["stable_error_codes"] == EXPECTED_ERROR_CODES
    assert all(contract["name"].startswith("ZELERDATA_") for contract in contracts)
    assert all("SHEETSELLER" not in contract["name"] for contract in contracts)
    assert all("sheetseller" not in contract["name"] for contract in contracts)


def test_registry_matches_the_contract_fixture_exactly() -> None:
    fixture = _fixture()
    registry = FormulaRegistry.default()

    assert registry.error_codes == tuple(fixture["stable_error_codes"])
    assert [contract.to_json_dict() for contract in registry.list_contracts()] == fixture[
        "contracts"
    ]


def test_representative_signatures_defaults_batches_and_outputs_are_preserved() -> None:
    registry = FormulaRegistry.default()

    publicaciones = registry.get("ZELERDATA_PUBLICACIONES")
    assert publicaciones.signature == (
        '(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", '
        'imagen="", encabezados="")'
    )
    assert [parameter.default for parameter in publicaciones.parameters] == [
        None,
        "todos",
        "todos",
        "base",
        "",
        "",
    ]
    assert publicaciones.batch == "A"
    assert publicaciones.output_shape == "table"

    semanas_con_stock = registry.get("ZELERDATA_SEMANASCONSTOCK")
    assert semanas_con_stock.signature == (
        '(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, '
        'fecha_final, encabezados="")'
    )
    assert [parameter.name for parameter in semanas_con_stock.parameters] == [
        "cuenta",
        "id_publicaciones",
        "skus",
        "fecha_inicial",
        "fecha_final",
        "encabezados",
    ]
    assert [parameter.required for parameter in semanas_con_stock.parameters] == [
        True,
        False,
        False,
        True,
        True,
        False,
    ]
    assert semanas_con_stock.batch == "C"

    ventas_totales = registry.get("ZELERDATA_VENTASTOTALES")
    assert ventas_totales.output_shape == "scalar"
    assert ventas_totales.parameters[-1].default == "todos"


def test_lookup_contracts_preserve_scalar_and_range_input_cases() -> None:
    registry = FormulaRegistry.default()

    stock = registry.get("ZELERDATA_STOCK")
    stock_inputs = {parameter.name: parameter.input_cases for parameter in stock.parameters}
    assert stock_inputs["skus"] == tuple(RANGE_INPUT_CASES)
    assert stock_inputs["id_publicaciones"] == tuple(RANGE_INPUT_CASES)

    ordenes_por_sku = registry.get("ZELERDATA_ORDENESPORSKU")
    sku_parameter = next(
        parameter for parameter in ordenes_por_sku.parameters if parameter.name == "skus"
    )
    compradores_parameter = next(
        parameter for parameter in ordenes_por_sku.parameters if parameter.name == "compradores"
    )
    assert sku_parameter.input_cases == tuple(RANGE_INPUT_CASES)
    assert compradores_parameter.input_cases == tuple(RANGE_INPUT_CASES)


def test_unknown_formula_returns_stable_formula_unknown_code() -> None:
    registry = FormulaRegistry.default()

    assert registry.find("ZELERDATA_NO_EXISTE") is None
    assert registry.find("SHEETSELLER_SKU") is None
    assert registry.find("sheetseller_sku") is None
    assert registry.unknown_formula_error_code == "FORMULA_UNKNOWN"


def test_dashboard_output_column_fixture_locks_mvp_and_deferred_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]
    expected_dashboard = [
        "ID Publicación",
        "Título",
        "SKU",
        "Stock Actual",
        "Precio",
        "Logística",
        "URL",
        "Tipo De Publicación",
        "Status",
        "Código ML",
        "Días Pausada",
        "Ventas (7 días)",
        "Ventas (15 días)",
        "Ventas (30 días)",
        "Ventas (60 días)",
        "Ventas (90 días)",
        "Envió A Cargo De",
        "Costo De Envío",
        "% Comisión",
        "Comisión",
        "Costo Por Unidad",
        "Tiene Catálogo",
    ]

    for formula in ["ZELERDATA_DASHBOARD", "ZELERDATA_DASHBOARDSINCATALOGO"]:
        columns = formulas[formula]["columns"]
        assert [
            column["name"] for column in columns[: len(expected_dashboard)]
        ] == expected_dashboard
        assert [column["name"] for column in columns if column["status"] == "mvp"] == [
            "ID Publicación",
            "Título",
            "SKU",
            "Stock Actual",
            "Precio",
            "Logística",
            "URL",
            "Tipo De Publicación",
            "Status",
            "Código ML",
            "Días Pausada",
            "Ventas (7 días)",
            "Ventas (15 días)",
            "Ventas (30 días)",
            "Ventas (60 días)",
            "Ventas (90 días)",
            "Envió A Cargo De",
            "Costo De Envío",
            "Tiene Catálogo",
        ]
        assert [column["name"] for column in columns if column["status"] == "explicit_na"] == [
            "% Comisión",
            "Comisión",
            "Costo Por Unidad",
            "Precio Promo",
        ]
        paused_column = next(column for column in columns if column["name"] == "Días Pausada")
        assert paused_column == {
            "name": "Días Pausada",
            "source": (
                "sheets_item_formula_rows.current.paused_since from observed status transitions"
            ),
            "status": "mvp",
            "reason": "Returns NA when observed status-history source truth is missing.",
        }
        assert "Categoría" not in [column["name"] for column in columns]
        assert "Imagen" not in [column["name"] for column in columns]
        assert all("source" in column or "legacy_source_note" in column for column in columns)

    assert formulas["ZELERDATA_DASHBOARDSINCATALOGO"]["compatibility_note"] == (
        "Excludes rows when current.catalog_product_id is present; richer catalog/buybox "
        "semantics remain blank-compatible unless represented in current item rows."
    )

    pause_time_column = next(
        column
        for column in formulas["ZELERDATA_PUBLICACIONES"]["columns"]
        if column["name"] == "Tiempo En Pausa"
    )
    assert pause_time_column == {
        "name": "Tiempo En Pausa",
        "source": (
            "sheets_item_formula_rows.current.paused_since from observed status transitions"
        ),
        "status": "mvp",
        "reason": "Returns NA when observed status-history source truth is missing.",
    }


def test_batch_b_output_column_fixture_locks_mvp_and_deferred_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]
    buyer_address_columns = [
        "Nombre Comprador",
        "Calle",
        "Número",
        "Colonia",
        "Código Postal",
        "Ciudad",
        "Estado",
        "País",
    ]

    assert [column["name"] for column in formulas["ZELERDATA_ORDENES"]["columns"]] == [
        "Fecha",
        "ID Orden",
        "Título",
        "SKU",
        "ID Publicación",
        "Unidades Vendidas",
        "Precio",
        "ID Carrito",
        "% Comisión",
        "Comisión",
        "Costo Por Unidad",
        "Costo De Envío",
        "Status",
    ]
    assert [
        column["name"]
        for column in formulas["ZELERDATA_ORDENES"]["optional_columns_when_compradores"]
    ] == buyer_address_columns

    assert [column["name"] for column in formulas["ZELERDATA_ORDENESPORSKU"]["columns"]] == [
        "Fecha",
        "ID Orden",
        "Título",
        "SKU",
        "ID Publicación",
        "Unidades Vendidas",
        "Precio",
        "ID Carrito",
        "% Comisión",
        "Comisión",
        "Costo Por Unidad",
        "Costo De Envío",
        "Status",
    ]
    assert [
        column["name"]
        for column in formulas["ZELERDATA_ORDENESPORSKU"]["optional_columns_when_compradores"]
    ] == buyer_address_columns

    assert [column["name"] for column in formulas["ZELERDATA_VENTASTOTALES"]["columns"]] == [
        "Total ventas"
    ]
    assert formulas["ZELERDATA_VENTASTOTALES"]["columns"][0]["status"] == "mvp"

    assert [column["name"] for column in formulas["ZELERDATA_UNIDADESVENDIDAS"]["columns"]] == [
        "Unidades vendidas"
    ]
    assert formulas["ZELERDATA_UNIDADESVENDIDAS"]["columns"][0]["status"] == "mvp"

    assert [column["name"] for column in formulas["ZELERDATA_VENTAPORDIAS"]["columns"]] == [
        "Unidades vendidas"
    ]
    assert formulas["ZELERDATA_VENTAPORDIAS"]["columns"][0]["status"] == "mvp"

    assert [column["name"] for column in formulas["ZELERDATA_VENTASYSTOCK"]["columns"]] == [
        "Unidades Vendidas (7 días)",
        "Unidades Vendidas (15 días)",
        "Unidades Vendidas (30 días)",
        "Stock actual",
    ]

    assert [column["name"] for column in formulas["ZELERDATA_TOPVENTASUNIDADES"]["columns"]] == [
        "ID Publicación",
        "SKU",
        "Título",
        "Unidades Vendidas",
    ]

    assert [column["name"] for column in formulas["ZELERDATA_TOPVENTASDINERO"]["columns"]] == [
        "ID Publicación",
        "SKU",
        "Título",
        "Unidades Vendidas",
        "Cantidad De Dinero",
    ]

    preguntas_kpi_columns = formulas["ZELERDATA_PREGUNTASKPI"]["columns"]
    assert [column["name"] for column in preguntas_kpi_columns[:2]] == ["Métrica", "Valor"]
    assert [column["status"] for column in preguntas_kpi_columns] == [
        "mvp",
        "mvp",
        "deferred",
        "deferred",
    ]
    assert all(
        "source" in column or "legacy_source_note" in column for column in preguntas_kpi_columns
    )

    assert [column["name"] for column in formulas["ZELERDATA_PREGUNTAS"]["columns"]] == [
        "ID Pregunta",
        "Fecha",
        "Item ID",
        "Buyer ID",
        "Estado",
        "Pregunta",
        "Respuesta",
        "Fecha respuesta",
    ]

    assert [column["name"] for column in formulas["ZELERDATA_DIASDESDEULTIMAVENTA"]["columns"]] == [
        "Días desde última venta"
    ]
    assert formulas["ZELERDATA_DIASDESDEULTIMAVENTA"]["columns"][0]["status"] == "mvp"

    assert [column["name"] for column in formulas["ZELERDATA_PRODUCTOSINVENTA"]["columns"]] == [
        "Título",
        "Código ML",
        "ID Publicación",
        "SKU",
        "Stock Actual",
        "Fecha Ultimo Cambio",
        "Status Actual",
        "Envío A Cargo De",
    ]
    assert formulas["ZELERDATA_PRODUCTOSINVENTA"]["columns"][-1]["status"] == "mvp"


def test_every_legacy_formula_has_an_explicit_runtime_state() -> None:
    registry = FormulaRegistry.default()
    runtime_states = get_formula_runtime_states()
    contract_names = {contract.name for contract in registry.list_contracts()}

    assert set(runtime_states) == contract_names
    assert {
        formula for formula, state in runtime_states.items() if state.state == "implemented"
    } == CORE_FORMULA_NAMES | BATCH_B_IMPLEMENTED_FORMULAS

    unsupported = {
        formula: state.reason
        for formula, state in runtime_states.items()
        if state.state == "unsupported"
    }
    assert len(unsupported) == 24
    assert unsupported["ZELERDATA_COMPRADORES"] == (
        "Current canonical orders do not expose buyer/shipping address fields."
    )
    assert unsupported["ZELERDATA_CATALOGO"] == (
        "Catalog/buybox snapshot read model is not available in zeler-platform yet."
    )
    assert unsupported["ZELERDATA_COSTOENVIOVENDEDOR"] == (
        "Seller-paid shipping cost read model is not available in zeler-platform yet."
    )
    assert all(reason for reason in unsupported.values())


def test_output_fixture_documents_every_explicitly_unsupported_formula_blocker() -> None:
    fixture = _column_fixture()
    unsupported_states = {
        formula: state.reason
        for formula, state in get_formula_runtime_states().items()
        if state.state == "unsupported"
    }

    assert fixture["unsupported_formulas"] == {
        formula: {"status": "unsupported", "reason": reason}
        for formula, reason in unsupported_states.items()
    }


@pytest.mark.asyncio
async def test_explicit_unsupported_handlers_are_routed_and_raise_data_unavailable() -> None:
    handlers = build_explicit_unsupported_formula_handlers()
    unsupported_states = {
        formula: state
        for formula, state in get_formula_runtime_states().items()
        if state.state == "unsupported"
    }

    assert set(handlers) == set(unsupported_states)

    with pytest.raises(Exception) as exc_info:
        await handlers["ZELERDATA_COMPRADORES"](  # type: ignore[misc]
            _formula_context("ZELERDATA_COMPRADORES", {"id_ordenes": ["order-1"]})
        )

    assert type(exc_info.value).__name__ == "FormulaDataUnavailableError"
    assert str(exc_info.value) == (
        "ZELERDATA_COMPRADORES data is not available yet: "
        "Current canonical orders do not expose buyer/shipping address fields."
    )


def _formula_context(formula: str, args: dict[str, Any]) -> Any:
    from zeler_sheets.formulas.dispatcher import FormulaExecutionContext

    return FormulaExecutionContext(
        contract=FormulaRegistry.default().find_required(formula),
        cuenta="HOPEMOB",
        seller_id="seller-1",
        seller_nickname="HOPEMOB",
        token_id="token-1",
        args=args,
        request_id="req-1",
    )
