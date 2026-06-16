# ruff: noqa: S105,S106

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unicodedata import normalize

import pytest

from zeler_sheets.formulas.handlers_core import (
    CORE_FORMULA_NAMES,
)
from zeler_sheets.formulas.handlers_core import (
    DASHBOARD_LEGACY_HEADERS as CORE_DASHBOARD_LEGACY_HEADERS,
)
from zeler_sheets.formulas.handlers_item_shipping_catalog import (
    ITEM_SHIPPING_CATALOG_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.handlers_orders_questions import BATCH_B_IMPLEMENTED_FORMULAS
from zeler_sheets.formulas.handlers_quality_calculator import (
    CALCULADORA_HEADERS,
    CALIDAD_HEADERS,
    QUALITY_CALCULATOR_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.handlers_remaining_phase4 import (
    CATALOGO_HEADERS,
    CATALOGOTIEMPO_HEADERS,
    PRECIO_HISTORICO_HEADERS,
    REMAINING_PHASE4_IMPLEMENTED_FORMULAS,
    RETIROS_HEADERS,
    TIEMPO_STOCK_ACTIVO_HEADERS,
    TIEMPOS_SIN_STOCK_HEADERS,
)
from zeler_sheets.formulas.handlers_returns_histories_withdrawals import (
    RETURNS_HISTORIES_WITHDRAWALS_IMPLEMENTED_FORMULAS,
)
from zeler_sheets.formulas.matrix_contracts import get_matrix_contract
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
    "CODIGOML2SKUID",
    "DIASPUBLICADA",
    "PUBLICACIONESDESCUIDADAS",
    "CATALOGO",
    "DASHBOARD",
    "TIEMPOSINSTOCK",
    "TIEMPOACTIVA",
    "CATALOGOSINVINCULAR",
    "CATALOGOBUYBOX",
    "CATALOGO_COMPLETO",
    "COMISION",
    "DEVOLUCIONES",
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
DEPRECATED_FORMULA_NAMES = {"ZELERDATA_COMPETENCIA", "ZELERDATA_ENVIARAFULL"}
RUNTIME_SMOKE_ANOMALY_FORMULAS = {
    "ZELERDATA_PUBLICACIONESDESCUIDADAS",
    "ZELERDATA_SUPERMERCADO",
    "ZELERDATA_MEDIDASGENERAL",
    "ZELERDATA_MEDIDAS",
    "ZELERDATA_TIEMPOACTIVA",
    "ZELERDATA_CATALOGOSINVINCULAR",
    "ZELERDATA_CALIDAD",
    "ZELERDATA_CALCULADORA",
    "ZELERDATA_COSTOENVIOVENDEDOR",
    "ZELERDATA_ENVIOSMERCADOENVIOS",
}

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
CATALOGOBUYBOX_VISIBLE_HEADERS = [
    "TITULO",
    "ID PUBLICACION",
    "ID CATALOGO",
    "STOCK ACTUAL",
    "STATUS",
    "PRECIO",
    "PRECIO GANADOR",
    "# DE GANADORES",
    "UNICO COMPETIDOR",
]
CATALOGO_COMPLETO_VISIBLE_HEADERS = [
    "TITULO",
    "DESCRIPCION",
    "IMAGEN",
    "MARCA",
    "MODELO",
    "GTIN",
]


def _fixture() -> dict[str, Any]:
    loaded = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", loaded)


def _column_fixture() -> dict[str, Any]:
    loaded = json.loads(COLUMN_FIXTURE_PATH.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", loaded)


def _is_uppercase_without_accents(value: str) -> bool:
    return value == normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").upper()


def test_fixture_locks_final_active_zelerdata_formula_names_in_order() -> None:
    fixture = _fixture()
    contracts = fixture["contracts"]

    assert [contract["name"] for contract in contracts] == EXPECTED_FORMULA_NAMES
    assert len({contract["name"] for contract in contracts}) == 52
    assert fixture["stable_error_codes"] == EXPECTED_ERROR_CODES
    assert all(contract["name"].startswith("ZELERDATA_") for contract in contracts)
    assert all("SHEETSELLER" not in contract["name"] for contract in contracts)
    assert all("sheetseller" not in contract["name"] for contract in contracts)
    assert DEPRECATED_FORMULA_NAMES.isdisjoint({contract["name"] for contract in contracts})


def test_matrix_contract_module_locks_active_deprecated_and_new_inventory() -> None:
    from zeler_sheets.formulas.matrix_contracts import (
        ACTIVE_FORMULA_NAMES,
        DEPRECATED_FORMULAS,
        get_matrix_contract,
    )

    assert list(ACTIVE_FORMULA_NAMES) == EXPECTED_FORMULA_NAMES
    assert set(DEPRECATED_FORMULAS) == DEPRECATED_FORMULA_NAMES
    assert DEPRECATED_FORMULAS["ZELERDATA_COMPETENCIA"].replacement is None
    assert DEPRECATED_FORMULAS["ZELERDATA_ENVIARAFULL"].replacement is None
    catalogo_completo = get_matrix_contract("ZELERDATA_CATALOGO_COMPLETO")
    assert catalogo_completo.signature == '(cuenta, encabezados="")'
    assert catalogo_completo.visible_headers == tuple(CATALOGO_COMPLETO_VISIBLE_HEADERS)


def test_registry_matches_the_contract_fixture_exactly() -> None:
    fixture = _fixture()
    registry = FormulaRegistry.default()

    assert registry.error_codes == tuple(fixture["stable_error_codes"])
    assert [contract.to_json_dict() for contract in registry.list_contracts()] == fixture[
        "contracts"
    ]


def test_removed_seller_data_formulas_are_not_registry_contracts() -> None:
    registry = FormulaRegistry.default()

    for deprecated_formula in DEPRECATED_FORMULA_NAMES:
        assert registry.find(deprecated_formula) is None


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
    assert registry.find("ZELERDATA_COMPETENCIA") is None
    assert registry.find("ZELERDATA_ENVIARAFULL") is None
    assert registry.unknown_formula_error_code == "FORMULA_UNKNOWN"


def test_catalog_matrix_headers_are_uppercase_no_accent_and_buybox_visible_order() -> None:
    from zeler_sheets.formulas.matrix_contracts import get_matrix_contract

    catalogobuybox_headers = get_matrix_contract("ZELERDATA_CATALOGOBUYBOX").visible_headers
    catalogo_completo_headers = get_matrix_contract("ZELERDATA_CATALOGO_COMPLETO").visible_headers
    obtener_catalogo_headers = get_matrix_contract("ZELERDATA_OBTENER_CATALOGO").visible_headers

    assert list(catalogobuybox_headers) == CATALOGOBUYBOX_VISIBLE_HEADERS
    assert list(catalogo_completo_headers) == CATALOGO_COMPLETO_VISIBLE_HEADERS
    assert list(obtener_catalogo_headers) == ["TITULO", "DESCRIPCION", "IMAGEN"]
    for header in [*catalogobuybox_headers, *catalogo_completo_headers, *obtener_catalogo_headers]:
        assert _is_uppercase_without_accents(header), header


def test_dashboard_output_column_fixture_locks_mvp_and_deferred_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]
    fixed_fee_source = (
        "sheets_item_formula_rows.current.listing_price_fixed_fee.fixed_fee from "
        "/sites/{site}/listing_prices.sale_fee_details.fixed_fee"
    )
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
            "% Comisión",
            "Comisión",
            "Costo Por Unidad",
            "Tiene Catálogo",
            "Precio Promo",
        ]
        assert [column["name"] for column in columns if column["status"] == "explicit_na"] == []
        paused_column = next(column for column in columns if column["name"] == "Días Pausada")
        assert paused_column == {
            "name": "Días Pausada",
            "source": (
                "sheets_item_formula_rows.current.paused_since as the effective current "
                "pause basis observed by Zeler"
            ),
            "status": "mvp",
            "reason": (
                "Counts from the first synchronization where Zeler observed the current "
                "paused period when Mercado Libre does not provide pause-start history; "
                "returns NA outside current paused rows or when the basis is missing."
            ),
        }
        assert next(column for column in columns if column["name"] == "% Comisión") == {
            "name": "% Comisión",
            "source": "sheets_item_formula_rows.current.listing_fee_projection.percentage_fee",
            "status": "mvp",
            "reason": "Source-backed MercadoLibre listing-price percentage fee estimate.",
        }
        assert next(column for column in columns if column["name"] == "Comisión") == {
            "name": "Comisión",
            "source": "sheets_item_formula_rows.current.listing_fee_projection.sale_fee_amount",
            "status": "mvp",
            "reason": "Source-backed MercadoLibre listing-price commission amount estimate.",
        }
        unit_cost_column = next(
            column for column in columns if column["name"] == "Costo Por Unidad"
        )
        assert unit_cost_column == {
            "name": "Costo Por Unidad",
            "source": fixed_fee_source,
            "status": "mvp",
            "reason": (
                "Returns NA unless a validated persisted listing-prices fixed-fee projection "
                "is present."
            ),
        }
        cart_columns = [column for column in columns if column["name"].startswith("ID Carrito (")]
        assert cart_columns == []
        assert "Categoría" not in [column["name"] for column in columns]
        assert "Imagen" not in [column["name"] for column in columns]
        assert all("source" in column or "legacy_source_note" in column for column in columns)

    assert expected_dashboard == CORE_DASHBOARD_LEGACY_HEADERS

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
            "sheets_item_formula_rows.current.paused_since as the effective current "
            "pause basis observed by Zeler"
        ),
        "status": "mvp",
        "reason": (
            "Counts from the first synchronization where Zeler observed the current paused "
            "period when Mercado Libre does not provide pause-start history; returns NA "
            "outside current paused rows or when the basis is missing."
        ),
    }

    assert formulas["ZELERDATA_PUBLICACIONESDESCUIDADAS"]["compatibility_note"] == (
        "Uses current seller-scoped item rows only: full paused out-of-stock listings with "
        "the shared effective paused-days basis older than 10 days. If Mercado Libre does "
        "not report when a listing became paused, Zeler counts from the first accepted "
        "synchronization where it observed the listing paused."
    )


def test_commission_output_column_fixture_locks_source_backed_columns_and_runtime_support() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]
    runtime_states = get_formula_runtime_states()

    assert runtime_states["ZELERDATA_COMISION"].state == "implemented"
    assert "ZELERDATA_COMISION" not in fixture["unsupported_formulas"]
    assert formulas["ZELERDATA_COMISION"]["columns"] == [
        {
            "name": "ID Publicación",
            "source": "sheets_item_formula_rows.item_id",
            "status": "mvp",
        },
        {
            "name": "% Comisión",
            "source": "sheets_item_formula_rows.current.listing_fee_projection.percentage_fee",
            "status": "mvp",
            "reason": "Source-backed MercadoLibre listing-price percentage fee estimate.",
        },
        {
            "name": "Comisión",
            "source": "sheets_item_formula_rows.current.listing_fee_projection.sale_fee_amount",
            "status": "mvp",
            "reason": "Source-backed MercadoLibre listing-price commission amount estimate.",
        },
        {
            "name": "Costo De Envío",
            "source": "sheets_item_formula_rows.current.seller_shipping_cost",
            "status": "mvp",
            "reason": (
                "Item-level estimated seller shipping cost only; unavailable source remains NA."
            ),
        },
    ]


def test_batch_b_output_column_fixture_locks_mvp_and_deferred_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]
    fixed_fee_source = (
        "sheets_item_formula_rows.current.listing_price_fixed_fee.fixed_fee from "
        "/sites/{site}/listing_prices.sale_fee_details.fixed_fee"
    )
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
    for formula in ["ZELERDATA_ORDENES", "ZELERDATA_ORDENESPORSKU"]:
        cart_column = next(
            column for column in formulas[formula]["columns"] if column["name"] == "ID Carrito"
        )
        assert cart_column == {
            "name": "ID Carrito",
            "source": "orders.meli_pack_id from MercadoLibre orders.pack_id",
            "status": "mvp",
            "reason": "Returns NA when the official MercadoLibre pack_id is missing.",
        }
        commission_percent_column = next(
            column for column in formulas[formula]["columns"] if column["name"] == "% Comisión"
        )
        assert commission_percent_column == {
            "name": "% Comisión",
            "source": "orders.items.sale_fee / orders.items.unit_price from /orders/{id}",
            "status": "mvp",
            "reason": (
                "Returns MercadoLibre UI-style whole percentage label, e.g. 14%, when "
                "persisted order fee source is available."
            ),
        }
        commission_column = next(
            column for column in formulas[formula]["columns"] if column["name"] == "Comisión"
        )
        assert commission_column == {
            "name": "Comisión",
            "source": "orders.items.sale_fee * orders.items.quantity from /orders/{id}",
            "status": "mvp",
            "reason": "Returns total realized MercadoLibre commission for the order item row.",
        }
        unit_cost_column = next(
            column
            for column in formulas[formula]["columns"]
            if column["name"] == "Costo Por Unidad"
        )
        assert unit_cost_column == {
            "name": "Costo Por Unidad",
            "source": fixed_fee_source,
            "status": "mvp",
            "reason": (
                "Returns NA unless a validated persisted listing-prices fixed-fee projection "
                "is present for the order line item."
            ),
        }
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


def test_catalog_foundation_fixture_locks_new_and_corrected_contract_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]

    assert [
        column["name"] for column in formulas["ZELERDATA_CATALOGOBUYBOX"]["columns"]
    ] == CATALOGOBUYBOX_VISIBLE_HEADERS
    assert [
        column["name"] for column in formulas["ZELERDATA_CATALOGO_COMPLETO"]["columns"]
    ] == CATALOGO_COMPLETO_VISIBLE_HEADERS
    assert formulas["ZELERDATA_CATALOGOBUYBOX"]["compatibility_note"] == (
        "Values must follow the visible header order; legacy row order inverted ID "
        "PUBLICACION and ID CATALOGO."
    )
    for formula in ["ZELERDATA_CATALOGOBUYBOX", "ZELERDATA_CATALOGO_COMPLETO"]:
        for column in formulas[formula]["columns"]:
            assert _is_uppercase_without_accents(column["name"]), column


def test_quality_calculator_fixture_locks_modern_columns() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]

    calidad_headers = [column["name"] for column in formulas["ZELERDATA_CALIDAD"]["columns"]]
    calculadora_headers = [
        column["name"] for column in formulas["ZELERDATA_CALCULADORA"]["columns"]
    ]

    assert calidad_headers == CALIDAD_HEADERS
    assert calculadora_headers == CALCULADORA_HEADERS
    assert list(get_matrix_contract("ZELERDATA_CALIDAD").visible_headers) == CALIDAD_HEADERS
    assert list(get_matrix_contract("ZELERDATA_CALCULADORA").visible_headers) == CALCULADORA_HEADERS
    assert "PRECIO SUGERIDO" not in calidad_headers
    for header in [*calidad_headers, *calculadora_headers]:
        assert _is_uppercase_without_accents(header), header


def test_remaining_phase4_fixture_locks_headers_and_runtime_support() -> None:
    fixture = _column_fixture()
    formulas = fixture["formulas"]

    expected_headers = {
        "ZELERDATA_CATALOGO": CATALOGO_HEADERS,
        "ZELERDATA_TIEMPOSINSTOCK": TIEMPOS_SIN_STOCK_HEADERS,
        "ZELERDATA_TIEMPOSTOCKACTIVO": TIEMPO_STOCK_ACTIVO_HEADERS,
        "ZELERDATA_PRECIOHISTORICO": PRECIO_HISTORICO_HEADERS,
        "ZELERDATA_CATALOGOTIEMPO": CATALOGOTIEMPO_HEADERS,
        "ZELERDATA_RETIROS": RETIROS_HEADERS,
    }

    for formula, headers in expected_headers.items():
        assert [column["name"] for column in formulas[formula]["columns"]] == headers
        assert list(get_matrix_contract(formula).visible_headers) == headers
        for header in headers:
            assert _is_uppercase_without_accents(header), header

    assert "ZELERDATA_SEMANASCONSTOCK" in formulas
    assert "ZELERDATA_CATALOGO" not in fixture["unsupported_formulas"]


def test_every_legacy_formula_has_an_explicit_runtime_state() -> None:
    registry = FormulaRegistry.default()
    runtime_states = get_formula_runtime_states()
    contract_names = {contract.name for contract in registry.list_contracts()}

    assert set(runtime_states) == contract_names
    assert DEPRECATED_FORMULA_NAMES.isdisjoint(runtime_states)
    assert (
        {formula for formula, state in runtime_states.items() if state.state == "implemented"}
        == CORE_FORMULA_NAMES
        | BATCH_B_IMPLEMENTED_FORMULAS
        | ITEM_SHIPPING_CATALOG_IMPLEMENTED_FORMULAS
        | RETURNS_HISTORIES_WITHDRAWALS_IMPLEMENTED_FORMULAS
        | QUALITY_CALCULATOR_IMPLEMENTED_FORMULAS
        | REMAINING_PHASE4_IMPLEMENTED_FORMULAS
    )

    unsupported = {
        formula: state.reason
        for formula, state in runtime_states.items()
        if state.state == "unsupported"
    }
    assert unsupported == {}
    assert "ZELERDATA_COMPRADORES" not in unsupported
    assert "ZELERDATA_COMISION" not in unsupported
    assert "ZELERDATA_COMPETENCIA" not in unsupported
    assert "ZELERDATA_ENVIARAFULL" not in unsupported
    assert "ZELERDATA_CATALOGO_COMPLETO" not in unsupported
    assert "ZELERDATA_COSTOENVIOVENDEDOR" not in unsupported
    assert "ZELERDATA_DEVOLUCIONES" not in unsupported
    assert "ZELERDATA_PUBLICACIONESDESCUIDADAS" not in unsupported
    assert "ZELERDATA_TIEMPOACTIVA" not in unsupported
    assert "ZELERDATA_CALIDAD" not in unsupported
    assert "ZELERDATA_CALCULADORA" not in unsupported
    for formula in REMAINING_PHASE4_IMPLEMENTED_FORMULAS:
        assert runtime_states[formula].state == "implemented"


def test_formula_api_default_dispatcher_wires_every_implemented_runtime_formula() -> None:
    from zeler_sheets.api import _runtime_dispatcher
    from zeler_sheets.formulas.dispatcher import FormulaDispatcher

    class FakeDb:
        def __getitem__(self, _name: str) -> object:
            return object()

    runtime_states = get_formula_runtime_states()
    implemented = {
        formula
        for formula, runtime_state in runtime_states.items()
        if runtime_state.state == "implemented"
    }
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(mongo_db=FakeDb())))

    dispatcher = _runtime_dispatcher(
        request,  # type: ignore[arg-type]
        None,
        now=lambda: datetime.now(UTC),
    )

    assert isinstance(dispatcher, FormulaDispatcher)
    handlers = dispatcher._handlers  # noqa: SLF001 - regression locks API dispatcher wiring.
    assert implemented >= RUNTIME_SMOKE_ANOMALY_FORMULAS
    assert sorted(implemented - set(handlers)) == []
    assert sorted(RUNTIME_SMOKE_ANOMALY_FORMULAS - set(handlers)) == []
    assert sorted(set(build_explicit_unsupported_formula_handlers()) & implemented) == []


def test_output_fixture_documents_every_explicitly_unsupported_formula_blocker() -> None:
    fixture = _column_fixture()
    unsupported_states = {
        formula: state.reason
        for formula, state in get_formula_runtime_states().items()
        if state.state == "unsupported"
    }
    assert unsupported_states == {}

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
    assert DEPRECATED_FORMULA_NAMES.isdisjoint(handlers)
    assert handlers == {}


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
