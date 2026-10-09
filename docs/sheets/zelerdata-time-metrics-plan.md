# ZelerData: plan para las 4 fórmulas de tiempo y retiros

Estado al 2026-10-08. Documento de decisión, no de implementación. Criterio del
usuario: "suficientemente bueno, no perfecto"; sin nuevos gates ni ledgers.

Las fórmulas `ZELERDATA_CATALOGOTIEMPO`, `ZELERDATA_TIEMPOSTOCKACTIVO`,
`ZELERDATA_SEMANASCONSTOCK` y `ZELERDATA_RETIROS` responden `DATA_UNAVAILABLE`
porque `sheets_catalog_time_metrics`, `sheets_stock_time_metrics` y
`sheets_full_withdrawals` tienen 0 documentos para el piloto y sus fuentes
(`item_history_projection`, `meli_item_events`, `withdrawal_records`) no existen
en la base productiva
([cierre 2026-09-10](zelerdata-cierre-avance-20260910.md), sección "Fórmulas:
medición de hoy"). El 2026-09-24 se aceptó UNAVAILABLE mientras falte el
histórico (misma nota, "Aceptación de fórmulas sin histórico").

## Resumen y recomendación

| Fórmula | Ruta mínima | Tamaño | ¿SDD? |
|---|---|---|---|
| Las 4 (paso 0) | Reemplazar el mensaje genérico por uno claro "sin histórico, se acumula desde <fecha>" | XS | No |
| `TIEMPOSTOCKACTIVO` + `SEMANASCONSTOCK` | Bitácora propia de disponibilidad (cambios de estado/stock), escrita junto al `stockout_snapshots`; las dos fórmulas leen de ella | M | Sí, ligero (colección nueva) |
| `CATALOGOTIEMPO` | Leer `sheets_catalog_competition_observations` (ya existe, ya se alimenta de webhooks) | S–M | No, si no cambia contratos |
| `RETIROS` | Explorar Mercado Libre Full primero; si no hay `withdrawal_id` real en las operaciones, declarar "no disponible" | M–L (tras explorar) | Probablemente sí, si hay persistencia nueva |

No reutilizar la maquinaria stock-time forward (sección 2). Antes de decidir el
orden hay que correr la sonda de solo lectura (sección 4): define si
`CATALOGOTIEMPO` es barata o no.

## 1. Qué calcula cada fórmula en el add-on legado

El add-on (`../sheetsellerappindividual/addon/Publications.gs`) solo hace de cliente
HTTP; el cálculo vive en `../sheetsellerappindividual/sheetsellerapi/src/colecciones/router_publicaciones.py`
y los datos los escribe `../sheetsellerappindividual/notificaciones/consumer/src/main.py`.
Todas se calculan en zona America/Mexico_City y recortan el fin del rango a "ahora"
si el rango incluye hoy.

**`CATALOGOTIEMPO`** (`SHEETSELLER_CATALOGOTIEMPO`, endpoint `/publications/diasganando`).
Por publicación de catálogo: horas ganando el buybox, horas con stock en catálogo y
el porcentaje. Dato: `catalog_history`, lista de `{status2, changed_at}` con
`Ganando`, `Perdiendo`, `Sin_stock`, `No compitiendo`. El consumidor lo escribe al
recibir el aviso de competencia (`price_to_win`): `winning` y `sharing_first_place`
→ `Ganando`, `competing` → `Perdiendo`, cualquier otro → `No compitiendo`, y stock 0
→ `Sin_stock`. "Con stock" cuenta de `Ganando`/`Perdiendo` hasta `Sin_stock` o
`No compitiendo`.

**`TIEMPOSTOCKACTIVO`** (endpoint `/publications/tiempodisponible`). Por publicación
y SKU (variación): tiempo activa, tiempo total del rango y porcentaje. Dato:
`variations_history[sku]`, lista de `{status2, changed_at}` con `active` o `paused`.
`active` significa estado de la publicación activo **y** stock mayor que 0; `paused`
es estado pausado/cerrado o stock 0. Se escribe solo cuando cambia (por evento).

**`SEMANASCONSTOCK`** (endpoint `/publications/weeks`). Por publicación y SKU: una
matriz de semanas ISO del rango con `Con stock` / `Sin stock`. Misma fuente que
`TIEMPOSTOCKACTIVO` (`variations_history`); una semana es `Con stock` si la última
entrada de historial en esa semana o antes es `active`. Sin historial usa el estado
y `last_updated` actuales de la publicación.

**`RETIROS`** (endpoint `/publications/retiros`). Filas de retiros de Full: id
principal, id secundario (bulto), código ML, publicación, SKU, título, unidades
solicitadas, fecha de creación y de entrega. No hay recurso de Mercado Libre para
retiros: el legado recorre las operaciones de stock fulfillment por `inventory_id`,
se queda con las de crear y entregar retiro, y deriva el id principal como los
primeros 7 dígitos del `withdrawal_id` de la operación (bulto). Solo conservaba los
últimos 2 meses (`Docs/docs/SheetsellerApp/compute_engine.md`).

Las tres primeras son **historia de estados**: no se pueden reconstruir de lo
actual, hay que haber observado los cambios. Por eso nacen "hacia adelante".

## 2. Qué existe hoy y si conviene reutilizarlo

**Lectura (ya hecha).** Los handlers están en
`modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py` y leen
`sheets_stock_time_metrics`, `sheets_catalog_time_metrics` y `sheets_full_withdrawals`
con `require_read_model_reconciled_range`, que en
`modules/sheets/src/zeler_sheets/formulas/read_models.py` exige marcador
`coverage_basis="legacy_imported"` y rango exacto. Los encabezados ya cumplen el
contrato (`formulas/matrix_contracts.py`). Esa compuerta solo sirve para datos
importados del legado; un acumulado hacia adelante no la pasaría.

**Escritura legada (importador).** `source_gated_read_model_writers.py`
(`run_source_gated_read_model_import`, `plan_stock_time_metrics_reconcile`) construye
las métricas leyendo `item_history_projection` (copia del `variations_history` /
`catalog_history` del legado), `meli_item_events` y `withdrawal_records`. Lo invoca
`infra/operations/zelerdata_read_model_reconcile.py`, y contra producción da
`planned=0` porque esas colecciones no existen.

**Maquinaria stock-time forward (etapa Codex).**
`_stock_time_forward_artifact.py` valida un sobre JSON revisado (sha256, EJSON
canónico, máximo 250 filas) y lo materializa; `_stock_time_forward_engine.py`
(2256 líneas) ejecuta el plan en una transacción con bitácora de operaciones,
preimágenes, marcador y reversa; `infra/operations/zelerdata_stock_time_rollback.py`
es la CLI de reversa. Los PRs #369/#371/#377 son el contrato de índices, el preflight
de runtime y la ejecución atómica.

- ¿Conectada? **No.** Fuera de pruebas, lo único que importa el motor es la CLI de
  reversa. Nadie llama `_execute_sealed_forward_operation`, `_seal_forward_plan` ni el
  cargador de artefactos desde un worker, un job o una CLI de avance. Sus
  tests (`tests/integration/test_stock_time_forward_*_rs0.py`,
  `modules/sheets/tests/test_stock_time_forward_*.py`) pasan en aislado.
- ¿Qué falta para que produzca filas? Alguien que genere el sobre (el
  `source_inventory` sale de la proyección legada que no existe), un ejecutor, y que
  el lector acepte su marcador. Es decir, casi todo el flujo de entrada.
- ¿Reutilizar? **No.** Resuelve otro problema: importar con auditoría y reversa un
  histórico ya calculado y revisado a mano. Un acumulado hacia adelante no necesita
  sobres, preimágenes ni reversa; basta con agregar observaciones y calcular al leer.
  Se deja donde está (no se borra: está fuera de alcance y tiene pruebas), pero la
  ruta nueva no depende de él. Solo valdría la pena resucitarlo si alguien entregara
  una exportación revisada del Mongo legado del piloto, y eso contradice la regla de
  no depender de bases legadas.

**Lo que sí sirve, porque ya corre cada ciclo.**

| Fuente | Qué guarda | Sirve para |
|---|---|---|
| `item_status_states` (`event_persistence.py`) | Estado actual por publicación, `first_observed_at`, `status_started_at` | Dónde empieza la cobertura; no da intervalos |
| `item_status_transitions` (mismo archivo, `_status_transition_document`) | Cada cambio de estado `from_status → to_status` con `observed_at` | Tiempo "activa" por estado, sin stock |
| `sheets_stockout_snapshots` (`remaining_read_model_writers.py`) | Un solo documento por publicación: stock actual y `out_of_stock_since` | Solo el último quiebre; sin historia |
| `sheets_catalog_competition_observations` (`catalog_observations.py`) | Observación `{status, available_quantity, observed_at}` por aviso `price_to_win` y por recuperación de buybox; `coverage_basis="observed_only"` | `CATALOGOTIEMPO`, casi tal cual |
| `sheets_full_operations` (`onboarding_sources.py`) | Operaciones Full de retiro tal como llegan de Mercado Libre | `RETIROS`, si traen identificador |
| Marcadores "observed-only" (`observed_read_model_markers.py`) | Latido que certifica que la fuente se está renovando, sin pretender cobertura histórica | Patrón para gatear los acumulados |

`record_stockout_observation` se llama desde `event_persistence.py` cada vez que se
acepta una observación de publicación (eventos y re-observación del inventario). Es
el punto de enganche natural para registrar cambios de disponibilidad.

## 3. Ruta mínima por fórmula

### Paso 0, común (XS, sin SDD)

Hoy el usuario ve "Read model X has not passed freshness/reconciliation for the
requested range." Cambiar, en los cuatro handlers, el mensaje de
`FormulaDataUnavailableError` por algo como "Sin histórico: esta métrica se calcula
solo con datos observados desde <fecha>". No toca contratos ni persistencia. Con
cualquiera de las rutas siguientes el mensaje pasa a decir desde cuándo hay datos.

### `TIEMPOSTOCKACTIVO` y `SEMANASCONSTOCK`: acumular hacia adelante (M, SDD ligero)

Una sola fuente para las dos. Cuando `record_stockout_observation` ve una publicación
(o SKU de variación) cuyo `disponible = estado activo y stock > 0` cambió respecto de
la última entrada, agrega una fila a una colección nueva append-only (nombre
tentativo `sheets_item_availability_transitions`: `seller_id`, `item_id`, `sku`,
`available`, `status`, `available_quantity`, `observed_at`). Los handlers actuales
dejan de leer `stock_time_metrics`, calculan sobre la marcha lo mismo que el legado
(intervalos entre cambios, recortados al rango y a "ahora") y publican igual
encabezados. Sin precálculo, sin marcador reconciliado.

- Cobertura: el primer documento por publicación marca desde cuándo hay datos. Rango
  que empieza antes: calcular la parte cubierta y decirlo en el mensaje, o responder
  el mensaje del paso 0; elegir una y no más (propongo el mensaje, es más honesto y
  más simple).
- Gate de frescura: reutilizar el patrón de `observed_read_model_markers.py` o,
  más simple, exigir que `item_status_states.last_observed_at` sea reciente.
- Limitación aceptada: la precisión es la del ciclo de observación (inventario cada
  10 minutos más eventos), no minuto exacto como el legado.
- Variante sin colección nueva: `item_status_transitions` ya existe y daría "tiempo
  con estado activo", pero ignora el stock 0, que es parte de lo que el legado llama
  activa. Sirve como primer paso solo si se rotula distinto; no la recomiendo.
- SDD: la colección nueva es persistencia (validator en `core/src/zeler_platform_core/cli/export_schemas.py`, índices
  en `infra/mongo/`, regla de `AGENTS.md`). Un `/sdd-ff` corto alcanza.
- Verificar con la sonda: que `item_status_transitions` tenga filas y desde cuándo, y
  cuántas publicaciones tienen variaciones (el SKU por variación complica el
  enganche).

### `CATALOGOTIEMPO`: leer lo que ya se observa (S–M, probablemente sin SDD)

`sheets_catalog_competition_observations` ya recibe un documento por aviso
`catalog_item_competition_status.updated` (cadena completa: clasificador del gateway,
topología, `consumer.py`, `acquire_catalog_event`) y por recuperación de buybox
(`formulas/recovery_worker.py`). Cada fila trae estado y stock en ese instante, que es
exactamente lo que el legado guardaba en `catalog_history`. El handler aplicaría la
misma regla de mapeo del legado (`winning`/`sharing_first_place` → ganando,
`competing` → perdiendo, stock 0 → sin stock, otro → no compite) y calcularía
intervalos entre observaciones al leer, sin colección derivada.

- Riesgo real: una publicación que lleva meses ganando no genera aviso hasta que
  cambia. Si la recuperación de buybox no la observa periódicamente, quedaría sin
  filas o con una sola fila reciente. La sonda mide publicaciones de catálogo vs
  publicaciones con alguna observación y desde cuándo. Si la cobertura es baja, el
  trabajo real es una pasada periódica que registre el estado actual de cada
  publicación de catálogo (hay que reutilizar `record_catalog_observation`).
- No cambia encabezados ni esquema; es un cambio de lectura. Sin SDD si se mantiene
  así.

### `RETIROS`: explorar primero (M–L, tras explorar)

El colector de operaciones Full (`collect_full_operations` en `onboarding_sources.py`)
existe y guarda en `sheets_full_operations`, pero hoy se usa en el alta de la cuenta
(`history_onboarding.py`) y se bloquea a propósito con
`full_withdrawal_contract_incompatible`: la documentación de Mercado Libre no
garantiza `withdrawal_id`, id de bulto ni cantidad solicitada original. La prueba
`modules/sheets/tests/test_full_onboarding_handler.py` maneja un `external_references`
con `type: "withdrawal_id"` solo como **candidato** sin confirmar.

Ruta mínima en dos decisiones:

1. Sonda de solo lectura: ¿hay operaciones reales en `sheets_full_operations`, y traen
   `external_references` con tipo `withdrawal_id`? (La sonda no imprime valores.)
2. Si sí, una exploración acotada contra Mercado Libre para confirmar la regla
   del legado (primeros 7 dígitos = retiro, resto = bulto) y la cantidad
   (`detail.not_available_detail`). Con eso, `RETIROS` se calcula desde operaciones
   (reserva = creación y unidades; entrega = fecha de entrega) y habría que decidir
   si necesita una colección derivada. Si no, declarar "RETIROS no disponible: Mercado
   Libre no expone el identificador del retiro" con ese mensaje claro, y cerrar.

Quedó fuera de alcance explorar Mercado Libre en vivo; esta sesión no lo hizo.

## 4. Sonda de producción

`infra/operations/zelerdata_time_metrics_probe.py` es de solo lectura (usa
`list_collection_names`, `count_documents`, `find` limitado y `aggregate` pequeño).
Imprime conteos, nombres de campos, valores enumerados de Mercado Libre (estado, tipo
de operación, tipo de referencia) y el rango de fechas de cada fuente. No imprime
identificadores, títulos ni SKUs. Se corre desde la sesión principal en el contexto
aprobado de la VM, nunca desde local:

```bash
MONGO_URI=... MONGO_DB=... python -m infra.operations.zelerdata_time_metrics_probe --seller-id 82453304
```

Responde: existencia/conteo de las 3 fuentes legadas y de las 3 colecciones destino;
y para `item_status_states`, `item_status_transitions`, `sheets_stockout_snapshots`,
`sheets_price_history_snapshots`, `sheets_catalog_competition_observations`,
`sheets_catalog_buybox_snapshots` y `sheets_full_operations`: conteo, publicaciones
distintas, primera y última observación, campos y distribución por estado/tipo.
Además cuántas publicaciones son Full, de catálogo, con `inventory_id` o con
variaciones, y el estado de los marcadores de frescura de los seis modelos.

Cómo leer el resultado:

- `item_status_transitions` con filas y varios días de antigüedad: la ruta de
  disponibilidad tiene base inmediata.
- `sheets_catalog_competition_observations` con muchas publicaciones distintas
  frente a las de catálogo: `CATALOGOTIEMPO` es barata.
- `sheets_full_operations` con `with_external_references` > 0 y tipo `withdrawal_id`:
  vale explorar `RETIROS`; en 0 o sin colección: declararla no disponible.

## 5. Orden propuesto

1. Correr la sonda (sesión principal).
2. Paso 0, mensaje claro en las cuatro (mismo PR, rápido).
3. `CATALOGOTIEMPO` si la sonda muestra cobertura útil; si no, la pasada periódica
   primero.
4. Disponibilidad (`TIEMPOSTOCKACTIVO` + `SEMANASCONSTOCK`) con `/sdd-ff` corto.
5. `RETIROS` solo tras la exploración; puede quedar declarada no disponible.

Mientras no exista histórico propio, estas fórmulas no deben presentar el estado
actual como si fuera histórico (decisión del 2026-09-24, sigue vigente).
