from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from zeler_sheets.formulas.registry import FormulaRegistry

FIXTURE_PATH = (
    Path(__file__).parents[3]
    / "tests"
    / "sheets"
    / "fixtures"
    / "sheetseller_formula_contracts.json"
)

EXPECTED_FORMULA_NAMES = [
    "SHEETSELLER_PUBLICACIONES",
    "SHEETSELLER_SKU",
    "SHEETSELLER_ID",
    "SHEETSELLER_STOCK",
    "SHEETSELLER_TITULO",
    "SHEETSELLER_URL",
    "SHEETSELLER_PRECIO",
    "SHEETSELLER_IDSTOCK",
    "SHEETSELLER_STATUS",
    "SHEETSELLER_PAUSADAS",
    "SHEETSELLER_CODIGOML",
    "sheetseller_enviarafull",
    "SHEETSELLER_CODIGOML2SKUID",
    "SHEETSELLER_DIASPUBLICADA",
    "SHEETSELLER_PUBLICACIONESDESCUIDADAS",
    "SHEETSELLER_CATALOGO",
    "SHEETSELLER_DASHBOARD",
    "SHEETSELLER_TIEMPOSINSTOCK",
    "SHEETSELLER_TIEMPOACTIVA",
    "SHEETSELLER_CATALOGOSINVINCULAR",
    "SHEETSELLER_CATALOGOBUYBOX",
    "SHEETSELLER_COMISION",
    "SHEETSELLER_DEVOLUCIONES",
    "SHEETSELLER_COMPETENCIA",
    "SHEETSELLER_CATALOGOTIEMPO",
    "SHEETSELLER_PRECIOHISTORICO",
    "SHEETSELLER_TIEMPOSTOCKACTIVO",
    "SHEETSELLER_DASHBOARDSINCATALOGO",
    "SHEETSELLER_CALIDAD",
    "SHEETSELLER_CALCULADORA",
    "SHEETSELLER_RETIROS",
    "SHEETSELLER_IMAGENES",
    "SHEETSELLER_SEMANASCONSTOCK",
    "SHEETSELLER_MEDIDASGENERAL",
    "SHEETSELLER_MEDIDAS",
    "SHEETSELLER_CATEGORIAS",
    "SHEETSELLER_SUPERMERCADO",
    "sheetseller_obtener_catalogo",
    "SHEETSELLER_ORDENES",
    "SHEETSELLER_UNIDADESVENDIDAS",
    "SHEETSELLER_ORDENESPORSKU",
    "SHEETSELLER_DIASDESDEULTIMAVENTA",
    "SHEETSELLER_PRODUCTOSINVENTA",
    "SHEETSELLER_VENTAPORDIAS",
    "SHEETSELLER_VENTASYSTOCK",
    "SHEETSELLER_TOPVENTASUNIDADES",
    "SHEETSELLER_TOPVENTASDINERO",
    "SHEETSELLER_COSTOENVIOVENDEDOR",
    "SHEETSELLER_VENTASTOTALES",
    "SHEETSELLER_COMPRADORES",
    "SHEETSELLER_ENVIOSMERCADOENVIOS",
    "SHEETSELLER_PREGUNTAS",
    "SHEETSELLER_PREGUNTASKPI",
]

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


def test_fixture_locks_all_53_legacy_formula_names_in_order() -> None:
    fixture = _fixture()
    contracts = fixture["contracts"]

    assert [contract["name"] for contract in contracts] == EXPECTED_FORMULA_NAMES
    assert len({contract["name"] for contract in contracts}) == 53
    assert fixture["stable_error_codes"] == EXPECTED_ERROR_CODES


def test_registry_matches_the_contract_fixture_exactly() -> None:
    fixture = _fixture()
    registry = FormulaRegistry.default()

    assert registry.error_codes == tuple(fixture["stable_error_codes"])
    assert [contract.to_json_dict() for contract in registry.list_contracts()] == fixture[
        "contracts"
    ]


def test_representative_signatures_defaults_batches_and_outputs_are_preserved() -> None:
    registry = FormulaRegistry.default()

    publicaciones = registry.get("SHEETSELLER_PUBLICACIONES")
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

    semanas_con_stock = registry.get("SHEETSELLER_SEMANASCONSTOCK")
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

    ventas_totales = registry.get("SHEETSELLER_VENTASTOTALES")
    assert ventas_totales.output_shape == "scalar"
    assert ventas_totales.parameters[-1].default == "todos"


def test_lookup_contracts_preserve_scalar_and_range_input_cases() -> None:
    registry = FormulaRegistry.default()

    stock = registry.get("SHEETSELLER_STOCK")
    stock_inputs = {parameter.name: parameter.input_cases for parameter in stock.parameters}
    assert stock_inputs["skus"] == tuple(RANGE_INPUT_CASES)
    assert stock_inputs["id_publicaciones"] == tuple(RANGE_INPUT_CASES)

    ordenes_por_sku = registry.get("SHEETSELLER_ORDENESPORSKU")
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

    assert registry.find("SHEETSELLER_NO_EXISTE") is None
    assert registry.unknown_formula_error_code == "FORMULA_UNKNOWN"
