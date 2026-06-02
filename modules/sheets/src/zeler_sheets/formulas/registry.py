from __future__ import annotations

from collections.abc import Iterable, Sequence

from zeler_sheets.formulas.schemas import FormulaContract, FormulaParameterContract

STABLE_ERROR_CODES = (
    "TOKEN_MISSING",
    "TOKEN_REVOKED",
    "SELLER_FORBIDDEN",
    "FORMULA_UNKNOWN",
    "BAD_ARGUMENT",
    "DATA_UNAVAILABLE",
    "RATE_LIMITED",
    "INTERNAL",
)

_SCALAR_INPUT_CASES = ("scalar",)
_RANGE_INPUT_CASES = ("scalar", "row_range", "column_range", "rectangular_range")
_RANGE_INPUT_PARAMETER_NAMES = {
    "skus",
    "id_publicaciones",
    "codes",
    "codigo_ml",
    "compradores",
    "id_ordenes",
}

_RAW_CONTRACTS = (
    (
        "ZELERDATA_PUBLICACIONES",
        '(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", '
        'imagen="", encabezados="")',
        "A",
        "table",
        "publication table rows",
    ),
    ("ZELERDATA_SKU", '(cuenta, skus="todos")', "A", "list", "1-column unique SKU list"),
    (
        "ZELERDATA_ID",
        '(cuenta, skus="todos")',
        "A",
        "lookup_rows",
        "item ID rows, duplicates allowed",
    ),
    (
        "ZELERDATA_STOCK",
        "(cuenta, skus, id_publicaciones)",
        "A",
        "lookup_rows",
        "stock by SKU+item ID",
    ),
    ("ZELERDATA_TITULO", "(cuenta, id_publicaciones)", "A", "lookup_rows", "title by item ID"),
    (
        "ZELERDATA_URL",
        "(cuenta, skus, id_publicaciones)",
        "A",
        "lookup_rows",
        "permalink by SKU+item ID",
    ),
    (
        "ZELERDATA_PRECIO",
        '(cuenta, skus, id_publicaciones, tipo_precio="base")',
        "A",
        "lookup_rows",
        "selected price by SKU+item ID",
    ),
    (
        "ZELERDATA_IDSTOCK",
        '(cuenta, skus, encabezados="")',
        "A",
        "table",
        "item ID + stock table",
    ),
    ("ZELERDATA_STATUS", "(cuenta, id_publicaciones)", "A", "lookup_rows", "status by item ID"),
    (
        "ZELERDATA_PAUSADAS",
        "(cuenta, id_publicaciones)",
        "C",
        "lookup_rows",
        "paused days by item ID",
    ),
    (
        "ZELERDATA_CODIGOML",
        "(cuenta, skus, id_publicaciones)",
        "A",
        "lookup_rows",
        "inventory/ML code by SKU+item ID",
    ),
    (
        "ZELERDATA_ENVIARAFULL",
        "(cuenta, codes)",
        "C",
        "table",
        "recommended Full quantities",
    ),
    (
        "ZELERDATA_CODIGOML2SKUID",
        '(cuenta, codigo_ml, encabezados="")',
        "A/D",
        "table",
        "item ID + SKU by ML code",
    ),
    (
        "ZELERDATA_DIASPUBLICADA",
        "(cuenta, id_publicaciones)",
        "A",
        "lookup_rows",
        "days since publication creation",
    ),
    (
        "ZELERDATA_PUBLICACIONESDESCUIDADAS",
        '(cuenta, tipo_precio="base", encabezados="")',
        "C",
        "table",
        "neglected full publications table",
    ),
    (
        "ZELERDATA_CATALOGO",
        '(cuenta, tipo_precio="base", encabezados="")',
        "D",
        "table",
        "catalog/buybox metrics table",
    ),
    (
        "ZELERDATA_DASHBOARD",
        '(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="")',
        "A/C",
        "table",
        "item dashboard table",
    ),
    (
        "ZELERDATA_TIEMPOSINSTOCK",
        '(cuenta, tipo_precio="base", encabezados="")',
        "C",
        "table",
        "out-of-stock duration table",
    ),
    (
        "ZELERDATA_TIEMPOACTIVA",
        "(cuenta, id_publicaciones)",
        "C",
        "lookup_rows",
        "active time by item ID",
    ),
    (
        "ZELERDATA_CATALOGOSINVINCULAR",
        '(cuenta, encabezados="")',
        "D",
        "table",
        "recommended unlinked catalog table",
    ),
    (
        "ZELERDATA_CATALOGOBUYBOX",
        '(cuenta, tipo_precio="base", encabezados="")',
        "D",
        "table",
        "catalog competition/buybox table",
    ),
    (
        "ZELERDATA_COMISION",
        '(cuenta, id_publicaciones, encabezados="")',
        "C",
        "table",
        "fees/commission/shipping table",
    ),
    (
        "ZELERDATA_DEVOLUCIONES",
        '(cuenta, fecha_inicio, fecha_final, id_publicaciones="todos", encabezados="")',
        "C",
        "table",
        "returns table for date range",
    ),
    (
        "ZELERDATA_COMPETENCIA",
        '(cuenta, id_publicaciones="todos", encabezados="")',
        "D",
        "table",
        "competitor sellers/URLs/units table",
    ),
    (
        "ZELERDATA_CATALOGOTIEMPO",
        '(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="")',
        "D/C",
        "table",
        "catalog winning-time metrics",
    ),
    (
        "ZELERDATA_PRECIOHISTORICO",
        '(cuenta, id_publicaciones="todos", tipo_precio="base", encabezados="")',
        "C",
        "table",
        "price history snapshots",
    ),
    (
        "ZELERDATA_TIEMPOSTOCKACTIVO",
        '(cuenta, fecha_inicial, fecha_final, id_publicaciones="todos", encabezados="")',
        "C",
        "table",
        "stock-available time metrics",
    ),
    (
        "ZELERDATA_DASHBOARDSINCATALOGO",
        '(cuenta, skus="todos", tipo_almacenamiento="todos", tipo_precio="base", encabezados="")',
        "A/C",
        "table",
        "dashboard excluding catalog items",
    ),
    (
        "ZELERDATA_CALIDAD",
        '(cuenta, encabezados="")',
        "D",
        "table",
        "listing quality/health table",
    ),
    (
        "ZELERDATA_CALCULADORA",
        '(cuenta, id_publicaciones, tipo_precio="actual", encabezados="")',
        "C/D",
        "table",
        "costs/category/catalog calculator table",
    ),
    (
        "ZELERDATA_RETIROS",
        '(cuenta, fecha_inicial, fecha_final, encabezados="")',
        "C",
        "table",
        "Full withdrawals table",
    ),
    (
        "ZELERDATA_IMAGENES",
        '(cuenta, id_publicaciones="todos", skus="todos", imagen="principal", '
        'tipo_almacenamiento="todos")',
        "A/C",
        "lookup_rows",
        "image URLs by item/SKU",
    ),
    (
        "ZELERDATA_SEMANASCONSTOCK",
        '(cuenta, id_publicaciones="todos", skus="todos", fecha_inicial, fecha_final, '
        'encabezados="")',
        "C",
        "table",
        "weekly stock-presence table",
    ),
    (
        "ZELERDATA_MEDIDASGENERAL",
        '(cuenta, id_publicaciones="todos", skus="todos", encabezados="")',
        "C",
        "table",
        "ID/SKU/title/measurement table",
    ),
    (
        "ZELERDATA_MEDIDAS",
        '(cuenta, id_publicaciones="todos", skus="todos")',
        "C",
        "lookup_rows",
        "measurement-only rows",
    ),
    (
        "ZELERDATA_CATEGORIAS",
        "(cuenta, id_publicaciones)",
        "A/D",
        "lookup_rows",
        "category by item ID",
    ),
    (
        "ZELERDATA_SUPERMERCADO",
        "(cuenta, id_publicaciones)",
        "D",
        "lookup_rows",
        "supermarket/regular flag",
    ),
    (
        "ZELERDATA_OBTENER_CATALOGO",
        "(cuenta)",
        "E/D",
        "table",
        "catalog info + image formula output",
    ),
    (
        "ZELERDATA_ORDENES",
        '(cuenta, fecha_inicial, fecha_final, estado="todos", compradores="", encabezados="")',
        "B",
        "table",
        "orders table",
    ),
    (
        "ZELERDATA_UNIDADESVENDIDAS",
        "(cuenta, skus, id_publicaciones, fecha_inicial, fecha_final)",
        "B",
        "lookup_rows",
        "units sold by SKU+item ID",
    ),
    (
        "ZELERDATA_ORDENESPORSKU",
        '(cuenta, skus, fecha_inicial, fecha_final, estado="todos", compradores="", '
        'encabezados="")',
        "B",
        "table",
        "orders filtered by SKU/date",
    ),
    (
        "ZELERDATA_DIASDESDEULTIMAVENTA",
        "(cuenta, skus, id_publicaciones)",
        "B/C",
        "lookup_rows",
        "days since last sale",
    ),
    (
        "ZELERDATA_PRODUCTOSINVENTA",
        '(cuenta, rango_dias, encabezados="")',
        "B/C",
        "table",
        "products without sales table",
    ),
    (
        "ZELERDATA_VENTAPORDIAS",
        "(cuenta, skus, id_publicaciones, rango_dias)",
        "B",
        "lookup_rows",
        "units sold over last N days",
    ),
    (
        "ZELERDATA_VENTASYSTOCK",
        '(cuenta, skus, id_publicaciones, encabezados="")',
        "B/A",
        "table",
        "7/15/30 sales + current stock",
    ),
    (
        "ZELERDATA_TOPVENTASUNIDADES",
        '(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="")',
        "B",
        "table",
        "top units-sold table",
    ),
    (
        "ZELERDATA_TOPVENTASDINERO",
        '(cuenta, fecha_inicial, fecha_final, cantidad_top, encabezados="")',
        "B",
        "table",
        "top revenue table",
    ),
    (
        "ZELERDATA_COSTOENVIOVENDEDOR",
        "(cuenta, skus, id_publicaciones)",
        "B/C",
        "lookup_rows",
        "seller-paid shipping cost",
    ),
    (
        "ZELERDATA_VENTASTOTALES",
        '(cuenta, fecha_inicial, fecha_final, estado="todos")',
        "B",
        "scalar",
        "total sales amount",
    ),
    (
        "ZELERDATA_COMPRADORES",
        '(cuenta, id_ordenes, encabezados="")',
        "B",
        "table",
        "buyer/shipping address table",
    ),
    (
        "ZELERDATA_ENVIOSMERCADOENVIOS",
        '(cuenta, estado_etiqueta="todos", encabezados="")',
        "B",
        "table",
        "shipping/label state table",
    ),
    (
        "ZELERDATA_PREGUNTAS",
        '(cuenta, fecha_inicial, fecha_final, horario_inicial, horario_final, encabezados="")',
        "B",
        "table",
        "questions/answers table",
    ),
    (
        "ZELERDATA_PREGUNTASKPI",
        '(cuenta, fecha_inicio, fecha_final, encabezados="")',
        "B",
        "table",
        "question KPI table",
    ),
)


class FormulaRegistry:
    def __init__(self, contracts: Iterable[FormulaContract]) -> None:
        self._contracts = tuple(contracts)
        self._contracts_by_name = {contract.name: contract for contract in self._contracts}
        if len(self._contracts_by_name) != len(self._contracts):
            raise ValueError("formula contracts must have unique names")

    @property
    def error_codes(self) -> tuple[str, ...]:
        return STABLE_ERROR_CODES

    @property
    def unknown_formula_error_code(self) -> str:
        return "FORMULA_UNKNOWN"

    @classmethod
    def default(cls) -> FormulaRegistry:
        return cls(_build_contracts(_RAW_CONTRACTS))

    def list_contracts(self) -> tuple[FormulaContract, ...]:
        return self._contracts

    def find(self, name: str) -> FormulaContract | None:
        return self._contracts_by_name.get(name)

    def get(self, name: str) -> FormulaContract:
        contract = self.find(name)
        if contract is None:
            raise KeyError(name)
        return contract

    def find_required(self, name: str) -> FormulaContract:
        return self.get(name)


def _build_contracts(
    raw_contracts: Sequence[tuple[str, str, str, str, str]],
) -> tuple[FormulaContract, ...]:
    return tuple(
        FormulaContract(
            name=name,
            signature=signature,
            batch=batch,
            output_shape=output_shape,
            output_contract=output_contract,
            parameters=_parameters_from_signature(signature),
        )
        for name, signature, batch, output_shape, output_contract in raw_contracts
    )


def _parameters_from_signature(signature: str) -> tuple[FormulaParameterContract, ...]:
    raw_parameters = signature.removeprefix("(").removesuffix(")").split(", ")
    return tuple(_parameter_from_token(raw_parameter) for raw_parameter in raw_parameters)


def _parameter_from_token(token: str) -> FormulaParameterContract:
    name, separator, default_value = token.partition("=")
    return FormulaParameterContract(
        name=name,
        required=separator == "",
        default=_decode_default(default_value) if separator else None,
        input_cases=_input_cases_for_parameter(name),
    )


def _decode_default(value: str) -> str:
    return value.removeprefix('"').removesuffix('"')


def _input_cases_for_parameter(name: str) -> tuple[str, ...]:
    if name in _RANGE_INPUT_PARAMETER_NAMES:
        return _RANGE_INPUT_CASES
    return _SCALAR_INPUT_CASES
