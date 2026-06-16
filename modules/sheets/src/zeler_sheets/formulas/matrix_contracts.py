from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormulaMatrixContract:
    name: str
    signature: str
    batch: str
    output_shape: str
    output_contract: str
    visible_headers: tuple[str, ...] = ()

    def to_raw_contract(self) -> tuple[str, str, str, str, str]:
        return (
            self.name,
            self.signature,
            self.batch,
            self.output_shape,
            self.output_contract,
        )


@dataclass(frozen=True, slots=True)
class DeprecatedFormula:
    name: str
    reason: str
    replacement: str | None = None


CATALOGOBUYBOX_VISIBLE_HEADERS = (
    "TITULO",
    "ID PUBLICACION",
    "ID CATALOGO",
    "STOCK ACTUAL",
    "STATUS",
    "PRECIO",
    "PRECIO GANADOR",
    "# DE GANADORES",
    "UNICO COMPETIDOR",
)
CATALOGO_COMPLETO_VISIBLE_HEADERS = (
    "TITULO",
    "DESCRIPCION",
    "IMAGEN",
    "MARCA",
    "MODELO",
    "GTIN",
)
OBTENER_CATALOGO_VISIBLE_HEADERS = ("TITULO", "DESCRIPCION", "IMAGEN")
CATALOGO_VISIBLE_HEADERS = (
    "ID CATALOGO",
    "URL CATALOGO",
    "ID PUBLICACION",
    "URL",
    "TITULO",
    "SKU",
    "CODIGO ML",
    "ENVIO A CARGO DE",
    "STOCK ACTUAL",
    "VENTAS 7 DIAS",
    "VENTAS 15 DIAS",
    "VENTAS 30 DIAS",
    "VENTAS 60 DIAS",
    "VENTAS 90 DIAS",
    "VENTAS 365 DIAS",
    "STATUS PUBLICACION CATALOGO",
    "STATUS WINNER CATALOGO",
    "% TIEMPO GANANDO CATALOGO SOBRE EL COMPETIDO",
    "PRECIO GANADOR CATALOGO",
    "MI PRECIO ACTUAL CATALOGO",
    "USUARIO GANADOR CATALOGO",
    "COMPARTIENDO CATALOGO CON USUARIOS",
    "PRICE TO WIN",
    "UNICO COMPETIDOR",
)
TIEMPOS_SIN_STOCK_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "TITULO",
    "SKU",
    "PRECIO",
    "LOGISTICA",
    "URL",
    "STATUS",
    "TIEMPO SIN STOCK",
)
TIEMPO_STOCK_ACTIVO_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "URL",
    "TIEMPO ACTIVA",
    "TIEMPO TOTAL",
    "% TIEMPO ACTIVA",
)
PRECIO_HISTORICO_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "TITULO",
    "PRECIO 1",
    "STATUS 1",
    "PRECIO 2",
    "STATUS 2",
    "PRECIO 3",
    "STATUS 3",
)
CATALOGOTIEMPO_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "TITULO",
    "URL",
    "TIEMPO GANANDO CATALOGO EN HORAS",
    "TOTAL DE HORAS DISPONIBLE EN CATALOGO",
    "% DE TIEMPO GANANDO CATALOGO",
)
RETIROS_VISIBLE_HEADERS = (
    "ID PRINCIPAL RETIRO",
    "ID SECUNDARIO RETIRO",
    "CODIGO ML",
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "UNIDADES SOLICITADAS",
    "FECHA DE CREACION",
    "FECHA DE ENTREGA",
)
CALIDAD_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "STATUS",
    "URL",
    "STOCK ACTUAL",
    "TIPO DE PUBLICACION",
    "PUNTAJE CALIDAD",
    "NIVEL CALIDAD",
    "CALCULADO EN",
    "ESTADO GTIN",
    "PUNTAJE GTIN",
    "ESTADO IMAGENES",
    "PUNTAJE IMAGENES",
    "ESTADO TITULO",
    "PUNTAJE TITULO",
    "ESTADO MERCADO ENVIOS",
    "PUNTAJE MERCADO ENVIOS",
    "ACCIONES PENDIENTES",
)
CALCULADORA_VISIBLE_HEADERS = (
    "ID PUBLICACION",
    "SKU",
    "TITULO",
    "DIVISA",
    "PRECIO",
    "COSTO ENVIO VENDEDOR",
    "COMISION",
    "% COMISION",
    "COSTO FIJO POR UNIDAD",
    "CATEGORIA",
    "CATALOGO",
    "LOGISTICA",
    "TIPO DE PUBLICACION",
    "TOTAL COSTOS",
    "NETO ESTIMADO",
)

_VISIBLE_HEADERS_BY_FORMULA = {
    "ZELERDATA_CATALOGO": CATALOGO_VISIBLE_HEADERS,
    "ZELERDATA_CATALOGOBUYBOX": CATALOGOBUYBOX_VISIBLE_HEADERS,
    "ZELERDATA_CATALOGO_COMPLETO": CATALOGO_COMPLETO_VISIBLE_HEADERS,
    "ZELERDATA_CATALOGOTIEMPO": CATALOGOTIEMPO_VISIBLE_HEADERS,
    "ZELERDATA_CALIDAD": CALIDAD_VISIBLE_HEADERS,
    "ZELERDATA_CALCULADORA": CALCULADORA_VISIBLE_HEADERS,
    "ZELERDATA_OBTENER_CATALOGO": OBTENER_CATALOGO_VISIBLE_HEADERS,
    "ZELERDATA_PRECIOHISTORICO": PRECIO_HISTORICO_VISIBLE_HEADERS,
    "ZELERDATA_RETIROS": RETIROS_VISIBLE_HEADERS,
    "ZELERDATA_TIEMPOSINSTOCK": TIEMPOS_SIN_STOCK_VISIBLE_HEADERS,
    "ZELERDATA_TIEMPOSTOCKACTIVO": TIEMPO_STOCK_ACTIVO_VISIBLE_HEADERS,
}

_ACTIVE_RAW_CONTRACTS: tuple[tuple[str, str, str, str, str], ...] = (
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
        "ZELERDATA_CATALOGO_COMPLETO",
        '(cuenta, encabezados="")',
        "D",
        "table",
        "complete catalog product table",
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

ACTIVE_FORMULA_CONTRACTS = tuple(
    FormulaMatrixContract(
        name=name,
        signature=signature,
        batch=batch,
        output_shape=output_shape,
        output_contract=output_contract,
        visible_headers=_VISIBLE_HEADERS_BY_FORMULA.get(name, ()),
    )
    for name, signature, batch, output_shape, output_contract in _ACTIVE_RAW_CONTRACTS
)
ACTIVE_FORMULA_NAMES = tuple(contract.name for contract in ACTIVE_FORMULA_CONTRACTS)
ACTIVE_FORMULA_RAW_CONTRACTS = tuple(
    contract.to_raw_contract() for contract in ACTIVE_FORMULA_CONTRACTS
)
DEPRECATED_FORMULAS = {
    "ZELERDATA_COMPETENCIA": DeprecatedFormula(
        name="ZELERDATA_COMPETENCIA",
        reason="Deprecated by the approved Seller Data matrix; removed from active exposure.",
    ),
    "ZELERDATA_ENVIARAFULL": DeprecatedFormula(
        name="ZELERDATA_ENVIARAFULL",
        reason="Deprecated by the approved Seller Data matrix; removed from active exposure.",
    ),
}
_CONTRACTS_BY_NAME = {contract.name: contract for contract in ACTIVE_FORMULA_CONTRACTS}


def get_matrix_contract(name: str) -> FormulaMatrixContract:
    return _CONTRACTS_BY_NAME[name]
