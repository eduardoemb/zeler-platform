# ZelerData formulas

ZelerData formulas are Google Sheets custom functions backed by the zeler-platform Formula API. Supported formulas return Sheets-safe values from seller-scoped local read models; any unsupported active formula would remain visible for contract compatibility and return `DATA_UNAVAILABLE` until a platform read model is implemented.

## Quick path

1. Save the show-once extension token from `https://app.zeler.ai/sheets/config` in **ZelerData → Settings**.
2. Use the visible seller nickname or canonical seller as `cuenta`.
3. Start with the supported examples below.

`cuenta` must be the seller nickname or canonical seller visible to token scope.

## Supported formulas

| Formula | Example Google Sheets formula | Expected behavior |
|---|---|---|
| `ZELERDATA_CALCULADORA` | `=ZELERDATA_CALCULADORA("cuenta", "MLA1", "actual", "si")` | Modern cost projection from local item rows: selected price, seller shipping cost, listing fees, category/catalog/logistics fields, total costs, and estimated net. Missing cost source cells return `NA`. |
| `ZELERDATA_CALIDAD` | `=ZELERDATA_CALIDAD("cuenta", "si")` | Modern quality projection from local item rows: identity/status/publication fields, quality score/level, component statuses/scores, and pending actions. Legacy `PRECIO SUGERIDO` is intentionally not exposed. |
| `ZELERDATA_CATALOGO` | `=ZELERDATA_CATALOGO("cuenta", "base", "si")` | Legacy 24-column catalog matrix from current item rows, catalog buybox snapshots, and local order sales windows. |
| `ZELERDATA_CATALOGOBUYBOX` | `=ZELERDATA_CATALOGOBUYBOX("cuenta", "base", "si")` | Current catalog buybox rows from `sheets_catalog_buybox_snapshots`; values follow visible header order. |
| `ZELERDATA_CATALOGO_COMPLETO` | `=ZELERDATA_CATALOGO_COMPLETO("cuenta", "si")` | Enriched current catalog product rows from local catalog snapshots. |
| `ZELERDATA_CATALOGOSINVINCULAR` | `=ZELERDATA_CATALOGOSINVINCULAR("cuenta", "si")` | Current publications locally marked as catalog-link suggestions. |
| `ZELERDATA_CATALOGOTIEMPO` | `=ZELERDATA_CATALOGOTIEMPO("cuenta", "2026-01-01", "2026-01-31", "todos", "si")` | Catalog winning-time metrics from local catalog time summaries; no formula-time historical MercadoLibre calls. |
| `ZELERDATA_CATEGORIAS` | `=ZELERDATA_CATEGORIAS("cuenta", "MLA1")` | Category by item ID. |
| `ZELERDATA_CODIGOML` | `=ZELERDATA_CODIGOML("cuenta", "SKU-1", "MLA1")` | Inventory or ML code by SKU and item ID. |
| `ZELERDATA_CODIGOML2SKUID` | `=ZELERDATA_CODIGOML2SKUID("cuenta", "INV-1", "si")` | Code, item ID, and SKU rows. |
| `ZELERDATA_COMISION` | `=ZELERDATA_COMISION("cuenta", "MLA1", "si")` | Publication commission table for the requested item IDs, backed by listing-price projections. Missing values return `NA`. |
| `ZELERDATA_COMPRADORES` | `=ZELERDATA_COMPRADORES("cuenta", "ORDER-1", "si")` | Buyer/address table with the eight approved fields: Nombre Comprador, Calle, Número, Colonia, Código Postal, Ciudad, Estado, and País. Missing values return `NA`. |
| `ZELERDATA_COSTOENVIOVENDEDOR` | `=ZELERDATA_COSTOENVIOVENDEDOR("cuenta", "SKU-1", "MLA1")` | Latest realized seller-paid shipment cost per unit from local orders and shipment cost snapshots. |
| `ZELERDATA_DASHBOARD` | `=ZELERDATA_DASHBOARD("cuenta", "todos", "todos", "base", "si")` | Current item dashboard table with sales-window metrics. Cart IDs are intentionally omitted. |
| `ZELERDATA_DASHBOARDSINCATALOGO` | `=ZELERDATA_DASHBOARDSINCATALOGO("cuenta", "todos", "todos", "base", "si")` | Dashboard table excluding catalog items, with sales-window metrics. Cart IDs are intentionally omitted. |
| `ZELERDATA_DIASDESDEULTIMAVENTA` | `=ZELERDATA_DIASDESDEULTIMAVENTA("cuenta", "SKU-1", "MLA1")` | Days since the last sale for a SKU and item ID. |
| `ZELERDATA_DIASPUBLICADA` | `=ZELERDATA_DIASPUBLICADA("cuenta", "MLA1")` | Days since publication creation. |
| `ZELERDATA_DEVOLUCIONES` | `=ZELERDATA_DEVOLUCIONES("cuenta", "2026-01-01", "2026-01-31", "todos", "si")` | Return claims table grouped by item ID and SKU, joined to local orders for title and returned units; cancelled returns are excluded. |
| `ZELERDATA_ENVIOSMERCADOENVIOS` | `=ZELERDATA_ENVIOSMERCADOENVIOS("cuenta", "todos", "si")` | Last 30 days open Mercado Envios labels from local orders and shipment snapshots; missing official pack IDs show `N/A`. |
| `ZELERDATA_ID` | `=ZELERDATA_ID("cuenta", "SKU-1")` | Item IDs for a SKU. |
| `ZELERDATA_IDSTOCK` | `=ZELERDATA_IDSTOCK("cuenta", "SKU-1", "si")` | SKU, item ID, and stock rows. |
| `ZELERDATA_IMAGENES` | `=ZELERDATA_IMAGENES("cuenta", "todos", "todos")` | Image URLs from the current item read model. |
| `ZELERDATA_MEDIDAS` | `=ZELERDATA_MEDIDAS("cuenta", "MLA1", "SKU-1")` | Combined `LARGO * ALTO * ANCHO` measurement cell from local item rows. |
| `ZELERDATA_MEDIDASGENERAL` | `=ZELERDATA_MEDIDASGENERAL("cuenta", "todos", "todos", "si")` | Item/SKU/title table with one combined measurement cell. |
| `ZELERDATA_OBTENER_CATALOGO` | `=ZELERDATA_OBTENER_CATALOGO("cuenta")` | Legacy-simple catalog rows: TITULO, DESCRIPCION, IMAGEN as `=IMAGE("url")`. |
| `ZELERDATA_ORDENES` | `=ZELERDATA_ORDENES("cuenta", "2026-01-01", "2026-01-31", "todos", "", "si")` | Orders table for a date range; `ID Carrito` comes only from MercadoLibre `orders.pack_id`. |
| `ZELERDATA_ORDENESPORSKU` | `=ZELERDATA_ORDENESPORSKU("cuenta", "SKU-1", "2026-01-01", "2026-01-31", "todos", "", "si")` | Orders filtered by SKU and date range; `ID Carrito` comes only from MercadoLibre `orders.pack_id`. |
| `ZELERDATA_PAUSADAS` | `=ZELERDATA_PAUSADAS("cuenta", "MLA1")` | Paused days from observed status transitions only; missing pause source returns `NA`. |
| `ZELERDATA_PRECIO` | `=ZELERDATA_PRECIO("cuenta", "SKU-1", "MLA1", "base")` | Selected price by SKU and item ID. |
| `ZELERDATA_PRECIOHISTORICO` | `=ZELERDATA_PRECIOHISTORICO("cuenta", "todos", "base", "si")` | Latest local price/status history pairs per publication. |
| `ZELERDATA_PREGUNTAS` | `=ZELERDATA_PREGUNTAS("cuenta", "2026-01-01", "2026-01-31", "00:00", "23:59", "si")` | Questions and answers table for a date and time range. |
| `ZELERDATA_PREGUNTASKPI` | `=ZELERDATA_PREGUNTASKPI("cuenta", "2026-01-01", "2026-01-31", "si")` | Question KPI table for a date range. |
| `ZELERDATA_PRODUCTOSINVENTA` | `=ZELERDATA_PRODUCTOSINVENTA("cuenta", 30, "si")` | Products without sales for the selected day range. |
| `ZELERDATA_PUBLICACIONES` | `=ZELERDATA_PUBLICACIONES("cuenta", "todos", "todos", "base", "", "si")` | Current publication table. |
| `ZELERDATA_PUBLICACIONESDESCUIDADAS` | `=ZELERDATA_PUBLICACIONESDESCUIDADAS("cuenta", "base", "si")` | Full paused out-of-stock publications older than 10 days, from current item rows and unavailable-detail fields. |
| `ZELERDATA_RETIROS` | `=ZELERDATA_RETIROS("cuenta", "2026-01-01", "2026-01-31", "si")` | Full withdrawal operation rows from the local fulfillment withdrawal read model. |
| `ZELERDATA_SEMANASCONSTOCK` | `=ZELERDATA_SEMANASCONSTOCK("cuenta", "todos", "todos", "2026-01-01", "2026-01-31", "si")` | Weekly dynamic stock-presence matrix from local stock time metrics; cells emit `Con stock` or `Sin stock`. |
| `ZELERDATA_SKU` | `=ZELERDATA_SKU("cuenta")` | Unique SKU list. |
| `ZELERDATA_STATUS` | `=ZELERDATA_STATUS("cuenta", "MLA1")` | Current publication status. |
| `ZELERDATA_STOCK` | `=ZELERDATA_STOCK("cuenta", "SKU-1", "MLA1")` | Stock by SKU and item ID. |
| `ZELERDATA_SUPERMERCADO` | `=ZELERDATA_SUPERMERCADO("cuenta", "MLA1")` | `Supermercado` when local item tags include `supermarket_eligible`; `Normal` when the item exists without it; `N/A` when the item is missing. |
| `ZELERDATA_TIEMPOACTIVA` | `=ZELERDATA_TIEMPOACTIVA("cuenta", "MLA1")` | Current active-status days from `item_status_states`; missing or non-active rows return `NA`. |
| `ZELERDATA_TIEMPOSINSTOCK` | `=ZELERDATA_TIEMPOSINSTOCK("cuenta", "base", "si")` | Current out-of-stock duration rows from local stockout snapshots. |
| `ZELERDATA_TIEMPOSTOCKACTIVO` | `=ZELERDATA_TIEMPOSTOCKACTIVO("cuenta", "2026-01-01", "2026-01-31", "todos", "si")` | Active-stock time metrics from bounded local stock/status history summaries. |
| `ZELERDATA_TITULO` | `=ZELERDATA_TITULO("cuenta", "MLA1")` | Current listing title. |
| `ZELERDATA_TOPVENTASDINERO` | `=ZELERDATA_TOPVENTASDINERO("cuenta", "2026-01-01", "2026-01-31", 10, "si")` | Top revenue table for a date range. |
| `ZELERDATA_TOPVENTASUNIDADES` | `=ZELERDATA_TOPVENTASUNIDADES("cuenta", "2026-01-01", "2026-01-31", 10, "si")` | Top units-sold table for a date range. |
| `ZELERDATA_UNIDADESVENDIDAS` | `=ZELERDATA_UNIDADESVENDIDAS("cuenta", "SKU-1", "MLA1", "2026-01-01", "2026-01-31")` | Units sold by SKU and item ID. |
| `ZELERDATA_URL` | `=ZELERDATA_URL("cuenta", "SKU-1", "MLA1")` | Current permalink. |
| `ZELERDATA_VENTAPORDIAS` | `=ZELERDATA_VENTAPORDIAS("cuenta", "SKU-1", "MLA1", 30)` | Units sold over the selected day range. |
| `ZELERDATA_VENTASTOTALES` | `=ZELERDATA_VENTASTOTALES("cuenta", "2026-01-01", "2026-01-31", "todos")` | Total sales amount for a date range. |
| `ZELERDATA_VENTASYSTOCK` | `=ZELERDATA_VENTASYSTOCK("cuenta", "SKU-1", "MLA1", "si")` | 7/15/30-day sales and current stock. |

## Readiness gates

These formulas are supported only after their read-model freshness markers prove the requested seller scope. When the required marker is missing, stale, failed, partial, or outside the requested range, the Formula API returns `DATA_UNAVAILABLE` instead of guessing values.

| Formula | Required proof |
|---|---|
| `ZELERDATA_PREGUNTAS` / `ZELERDATA_PREGUNTASKPI` | Historical `questions` reconciliation for the requested date range and required answer/detail fields. Event-only freshness is not enough. |
| `ZELERDATA_DEVOLUCIONES` | `claims` coverage tied to approved/reconciled `orders`; returned quantities must come from explicit positive `returned_quantity`. |
| `ZELERDATA_CATALOGO_COMPLETO` | `catalog_product_snapshots` from scoped item rows with `catalog_product_id`, fetched from `/products/{catalog_product_id}`. |
| `ZELERDATA_CATALOGOBUYBOX` | `catalog_buybox_snapshots` from scoped item rows, fetched from `/items/{item_id}/price_to_win?version=v2`. |

`ID Carrito` is an order-formula-only column in `ZELERDATA_ORDENES` and `ZELERDATA_ORDENESPORSKU`. Values are never derived from order id, shipment id, message pack fallbacks, buyer data, fees, shipping costs, promo price, or status history. Missing official MercadoLibre `orders.pack_id` values display as `NA`. Historical May rows can still show `NA` if persisted read models do not have `meli_pack_id`; any refresh/backfill for those rows requires separate operational authorization and is not part of this hotfix.

## Deferred formulas

No active Seller Data formula is deferred currently. If a future active formula lacks a safe seller-scoped read model, it must remain documented here and return DATA_UNAVAILABLE until that read model exists.

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
