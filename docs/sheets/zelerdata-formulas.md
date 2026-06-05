# ZelerData formulas

ZelerData formulas are Google Sheets custom functions backed by the zeler-platform Formula API. Supported formulas return Sheets-safe values today; deferred formulas remain visible for contract compatibility and return `DATA_UNAVAILABLE` until a platform read model is implemented.

## Quick path

1. Save the show-once extension token from `https://app.zeler.ai/sheets/config` in **ZelerData → Settings**.
2. Use the visible seller nickname or canonical seller as `cuenta`.
3. Start with the supported examples below.

`cuenta` must be the seller nickname or canonical seller visible to token scope.

## Supported formulas

| Formula | Example Google Sheets formula | Expected behavior |
|---|---|---|
| `ZELERDATA_CATEGORIAS` | `=ZELERDATA_CATEGORIAS("cuenta", "MLA1")` | Category by item ID. |
| `ZELERDATA_CODIGOML` | `=ZELERDATA_CODIGOML("cuenta", "SKU-1", "MLA1")` | Inventory or ML code by SKU and item ID. |
| `ZELERDATA_CODIGOML2SKUID` | `=ZELERDATA_CODIGOML2SKUID("cuenta", "INV-1", "si")` | Code, item ID, and SKU rows. |
| `ZELERDATA_COMISION` | `=ZELERDATA_COMISION("cuenta", "MLA1", "si")` | Publication commission table for the requested item IDs, backed by listing-price projections. Missing values return `NA`. |
| `ZELERDATA_COMPRADORES` | `=ZELERDATA_COMPRADORES("cuenta", "ORDER-1", "si")` | Buyer/address table with the eight approved fields: Nombre Comprador, Calle, Número, Colonia, Código Postal, Ciudad, Estado, and País. Missing values return `NA`. |
| `ZELERDATA_DASHBOARD` | `=ZELERDATA_DASHBOARD("cuenta", "todos", "todos", "base", "si")` | Current item dashboard table with sales-window metrics. Cart IDs are intentionally omitted. |
| `ZELERDATA_DASHBOARDSINCATALOGO` | `=ZELERDATA_DASHBOARDSINCATALOGO("cuenta", "todos", "todos", "base", "si")` | Dashboard table excluding catalog items, with sales-window metrics. Cart IDs are intentionally omitted. |
| `ZELERDATA_DIASDESDEULTIMAVENTA` | `=ZELERDATA_DIASDESDEULTIMAVENTA("cuenta", "SKU-1", "MLA1")` | Days since the last sale for a SKU and item ID. |
| `ZELERDATA_DIASPUBLICADA` | `=ZELERDATA_DIASPUBLICADA("cuenta", "MLA1")` | Days since publication creation. |
| `ZELERDATA_ID` | `=ZELERDATA_ID("cuenta", "SKU-1")` | Item IDs for a SKU. |
| `ZELERDATA_IDSTOCK` | `=ZELERDATA_IDSTOCK("cuenta", "SKU-1", "si")` | SKU, item ID, and stock rows. |
| `ZELERDATA_IMAGENES` | `=ZELERDATA_IMAGENES("cuenta", "todos", "todos")` | Image URLs from the current item read model. |
| `ZELERDATA_ORDENES` | `=ZELERDATA_ORDENES("cuenta", "2026-01-01", "2026-01-31", "todos", "", "si")` | Orders table for a date range; `ID Carrito` comes only from MercadoLibre `orders.pack_id`. |
| `ZELERDATA_ORDENESPORSKU` | `=ZELERDATA_ORDENESPORSKU("cuenta", "SKU-1", "2026-01-01", "2026-01-31", "todos", "", "si")` | Orders filtered by SKU and date range; `ID Carrito` comes only from MercadoLibre `orders.pack_id`. |
| `ZELERDATA_PAUSADAS` | `=ZELERDATA_PAUSADAS("cuenta", "MLA1")` | Paused days from observed status transitions only; missing pause source returns `NA`. |
| `ZELERDATA_PRECIO` | `=ZELERDATA_PRECIO("cuenta", "SKU-1", "MLA1", "base")` | Selected price by SKU and item ID. |
| `ZELERDATA_PREGUNTAS` | `=ZELERDATA_PREGUNTAS("cuenta", "2026-01-01", "2026-01-31", "00:00", "23:59", "si")` | Questions and answers table for a date and time range. |
| `ZELERDATA_PREGUNTASKPI` | `=ZELERDATA_PREGUNTASKPI("cuenta", "2026-01-01", "2026-01-31", "si")` | Question KPI table for a date range. |
| `ZELERDATA_PRODUCTOSINVENTA` | `=ZELERDATA_PRODUCTOSINVENTA("cuenta", 30, "si")` | Products without sales for the selected day range. |
| `ZELERDATA_PUBLICACIONES` | `=ZELERDATA_PUBLICACIONES("cuenta", "todos", "todos", "base", "", "si")` | Current publication table. |
| `ZELERDATA_SKU` | `=ZELERDATA_SKU("cuenta")` | Unique SKU list. |
| `ZELERDATA_STATUS` | `=ZELERDATA_STATUS("cuenta", "MLA1")` | Current publication status. |
| `ZELERDATA_STOCK` | `=ZELERDATA_STOCK("cuenta", "SKU-1", "MLA1")` | Stock by SKU and item ID. |
| `ZELERDATA_TITULO` | `=ZELERDATA_TITULO("cuenta", "MLA1")` | Current listing title. |
| `ZELERDATA_TOPVENTASDINERO` | `=ZELERDATA_TOPVENTASDINERO("cuenta", "2026-01-01", "2026-01-31", 10, "si")` | Top revenue table for a date range. |
| `ZELERDATA_TOPVENTASUNIDADES` | `=ZELERDATA_TOPVENTASUNIDADES("cuenta", "2026-01-01", "2026-01-31", 10, "si")` | Top units-sold table for a date range. |
| `ZELERDATA_UNIDADESVENDIDAS` | `=ZELERDATA_UNIDADESVENDIDAS("cuenta", "SKU-1", "MLA1", "2026-01-01", "2026-01-31")` | Units sold by SKU and item ID. |
| `ZELERDATA_URL` | `=ZELERDATA_URL("cuenta", "SKU-1", "MLA1")` | Current permalink. |
| `ZELERDATA_VENTAPORDIAS` | `=ZELERDATA_VENTAPORDIAS("cuenta", "SKU-1", "MLA1", 30)` | Units sold over the selected day range. |
| `ZELERDATA_VENTASTOTALES` | `=ZELERDATA_VENTASTOTALES("cuenta", "2026-01-01", "2026-01-31", "todos")` | Total sales amount for a date range. |
| `ZELERDATA_VENTASYSTOCK` | `=ZELERDATA_VENTASYSTOCK("cuenta", "SKU-1", "MLA1", "si")` | 7/15/30-day sales and current stock. |

`ID Carrito` is an order-formula-only column in `ZELERDATA_ORDENES` and `ZELERDATA_ORDENESPORSKU`. Values are never derived from order id, shipment id, message pack fallbacks, buyer data, fees, shipping costs, promo price, or status history. Missing official MercadoLibre `orders.pack_id` values display as `NA`. Historical May rows can still show `NA` if persisted read models do not have `meli_pack_id`; any refresh/backfill for those rows requires separate operational authorization and is not part of this hotfix.

## Deferred formulas

The formulas below are preserved as wrappers for Sheetseller-compatible contracts, but each returns DATA_UNAVAILABLE until a platform read model is implemented.

| Formula | Public expectation |
|---|---|
| `ZELERDATA_CALCULADORA` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_CALIDAD` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_CATALOGO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_CATALOGOBUYBOX` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_CATALOGOSINVINCULAR` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_CATALOGOTIEMPO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_COMPETENCIA` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_COSTOENVIOVENDEDOR` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_DEVOLUCIONES` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_ENVIARAFULL` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_ENVIOSMERCADOENVIOS` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_MEDIDAS` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_MEDIDASGENERAL` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_OBTENER_CATALOGO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_PRECIOHISTORICO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_PUBLICACIONESDESCUIDADAS` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_RETIROS` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_SEMANASCONSTOCK` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_SUPERMERCADO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_TIEMPOACTIVA` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_TIEMPOSINSTOCK` | returns DATA_UNAVAILABLE until a platform read model is implemented. |
| `ZELERDATA_TIEMPOSTOCKACTIVO` | returns DATA_UNAVAILABLE until a platform read model is implemented. |

## Stable error codes

| Code | User expectation |
|---|---|
| `DATA_UNAVAILABLE` | The formula or requested data is not available yet. |
| `TOKEN_MISSING` | Open **ZelerData → Settings** and save a show-once extension token. |
| `TOKEN_REVOKED` | Create a new token in zeler-app and save it again. |
| `SELLER_FORBIDDEN` | The token is not authorized for the requested `cuenta`. |
| `FORMULA_UNKNOWN` | The formula name is not in the public registry. |
| `BAD_ARGUMENT` | The formula arguments or ranges are malformed. |
| `RATE_LIMITED` | Recalculation exceeded the token or seller budget; wait and retry. |
| `INTERNAL` | Unexpected platform issue; contact Zeler support with redacted context. |
