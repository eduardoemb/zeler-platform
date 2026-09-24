# Cierre de avance de ZelerData — 11 de septiembre de 2026

Estado: entrega de cierre solicitada por el usuario. Corte de observación:
2026-09-11, con el worker verificado en la imagen
`sheets-worker-39849ad-20260911T195000Z` (`sha256:23f0e55a…`) y el API en
`sheets-api-648d449-20260911T140119Z` (`sha256:14bda442…`), ambos healthy.

El documento conserva la línea base del 2026-09-07 y las secciones históricas;
las secciones de despliegue, ciclo de refresco, alertas y precalculado reflejan
el estado final verificado. El apartado «Pendiente al entregar» lista lo que
queda fuera de esta entrega.

## Resumen antes/ahora

Línea base documentada el 2026-09-07 sobre `main` en
`c5a2e097`: la API de fórmulas devolvía `DATA_UNAVAILABLE` sin programar
recuperación; la ejecución productiva de la reconciliación no aparecía en
`systemd` y la procedencia de las imágenes seguía sin resolver; las lecturas de
artículos, SKU y órdenes truncaban silenciosamente en 500/500/1,000 filas; el
estado del read model del piloto 82453304 era `degraded` (7 modelos faltantes, 9
reconciliados, 1 vencido) y las 17 entradas de inventario fallaban la ventana
productiva. Gateway, API/worker de Sheets y Mongo estaban saludables, pero la
salud de los contenedores no probaba disponibilidad ni exactitud de datos.

Estado actual: 219 commits después, la ruta de recuperación asíncrona existe y
está conectada a la API y al worker; las lecturas ya no truncan en los casos
cubiertos por sus pruebas; se corrigieron recuperación de órdenes, envíos,
catálogo, precios, atributos de variación, preguntas y calidad de publicación; y
las 52 fórmulas se ejecutaron en una pestaña real con 52 respuestas HTTP 200.
Esa ejecución prueba que las fórmulas responden, no que todos sus valores sean
correctos: el recibo declara `correctness_verified=false`.

| Dimensión | Antes (2026-09-07) | Ahora (2026-09-10) |
| --- | --- | --- |
| Recuperación asíncrona | Ausente en la ruta de fórmulas | Conectada a API/worker, con continuidad de artículos y reintentos acotados |
| Lecturas de datos | Truncadas en 500/500/1,000 filas | Corregidas en los casos cubiertos por pruebas; revisión global pendiente |
| Reconciliación del piloto | No ejecutada con veredicto autoritativo | Dry-run diagnóstico autoritativo para reclamos; conteos de catálogo en revisión |
| 52 fórmulas | Sin smoke productivo | 52 HTTP 200 en Google Sheet real; exactitud sin verificar |
| Imágenes desplegadas | Procedencia sin resolver | API y worker saludables en las imágenes de `5a03f06` |
| Seguridad y ciclo de datos | Gate abierto | Gate abierto; aislamiento de auditoría corregido, eliminación sin prueba |
| Conteo de catálogo | Sin criterio de participación | Corrección `43e4a29` probada (197 casos) y desplegada en `5a03f06` |
| Simplificación | Sin inventario de consumidores | Pendiente de cierre explícito |

El avance es material, pero no equivale a cierre: falta demostrar que los datos
reconciliados son completos y correctos, que la recuperación automática produce
lecturas posteriores confiables y que se cumplen los gates de seguridad, latencia,
simplificación y aceptación en superficies reales.

## Avance demostrado

- Hay evidencia de ejecución de las 52 fórmulas desde la pestaña real autorizada
  `Goal_Pruebas_20260909`: 52 eventos HTTP 200 y lectura de tres filas por ancla.
  El recibo declara `correctness_verified=false`: prueba ejecución y una muestra
  de resultados, pero no integridad ni exactitud de todos los campos.
- La corrección de recuperación de solicitudes de artículos mayores de 20 IDs
  está implementada en `208decf`, con continuidad persistida y pruebas de
  reinicio/fallo. Su despliegue anterior está registrado; falta el ejercicio
  productivo específico con lectura posterior del trabajo persistido.
- Las correcciones `2e7fdd5`, `bb0cb4d` y `849b290` permiten que la reconciliación
  contabilice metadatos de catálogo ausentes y respuestas individuales 404 sin
  impedir obtener los demás recursos válidos. Las pruebas enfocadas están
  registradas en el informe de avance.
- La consulta actual a la VM confirma API y worker de Sheets saludables.
- La evidencia histórica registra la corrección y despliegue del aislamiento
  de identidad de auditoría. No debe presentarse ese defecto como todavía abierto.

## Estado actual del despliegue

Consulta de solo lectura a la VM el 2026-09-10: API y worker de Sheets llevan
más de 7 horas saludables, en las imágenes desplegadas de `5a03f06`.

| Servicio | Digest activo y saludable | Commit de origen |
| --- | --- | --- |
| Sheets worker | `sha256:8eb6eba098989c356205a25addc862045c17efcc4b85e15765ef762b10be5e2f` | `5a03f06` |
| Sheets API | `sha256:82fce845db8e76fe689bb640650549e9047a9f7ebc2f956c9e445712ece7a6e0` | `5a03f06` |

En esta sesión se construyeron y desplegaron dos pares de imágenes: primero
`43e4a29` (conteo de catálogo por participación explícita) y después `5a03f06`
(espera de Retry-After en adquisición de catálogo). Cada despliegue terminó con
código 0, con respaldo Compose por servicio y verificación de digest y salud.

El despliegue worker → API que llevó al runtime actual terminó con código 0, con
respaldos Compose por servicio y más de 5 GiB libres. La corrección de conteo de
catálogo (`43e4a29`) ya está incluida en las imágenes desplegadas de `5a03f06`:
usa la ruta de recuperación de metadatos de catálogo del backfill y exige
participación explícita más identidad de producto. Los 389 snapshots buybox
reportados antes contra expectativas que incluían 529 publicaciones no
participantes ya no son la referencia vigente; el alcance de buybox sigue sin
certificarse porque hay participaciones desconocidas.

## Pendientes para aceptación final

| Requisito | Evidencia que falta o acción siguiente |
| --- | --- |
| Última versión operativa | Activación y salud comprobadas; falta aceptación funcional posterior. |
| Datos completos y confiables | El dry-run autoritativo y la primera escritura ya se ejecutaron para el piloto 82453304 y rango 2026-08-08 a 2026-09-06. Falta resolver los 351 snapshots de precio/stock, certificar el alcance de buybox con participaciones desconocidas y repetir la escritura sin el aborto por `--error-threshold` para publicar marcadores de frescura y verificar la lectura posterior. |
| Recuperación automática | Demostrar solicitud faltante → trabajo asíncrono → adquisición Mercado Libre → Mongo → consulta posterior, incluida la continuación de artículos mayores de 20 IDs. |
| Ausencias honestas | Verificar razones persistidas y visibles de los recursos no recuperables. Seis artículos devolvieron 404 en la prueba previa; eso no demuestra que toda ausencia histórica sea irrecuperable. No convertir errores temporales en ausencia definitiva. |
| 52 fórmulas y superficies actuales | Completar comparación de valores/contratos contra datos fuente, y aceptación representativa en la Sheet real y superficies existentes de zeler-app. HTTP 200 no basta para probar valores correctos. |
| Latencia | Medir ejecución completa de Apps Script/Sheets y demostrar el límite de 30 segundos; fijar el presupuesto p95 a partir de esa medición. Los tiempos del endpoint excluyen sobrecarga de Google. |
| Contrato actual de órdenes | Consolidar evidencia de adquisición, normalización y lectura con el contrato nuevo, incluidas asociaciones de envíos; no extrapolar una prueba parcial a toda la migración. |
| Seguridad mínima y ciclo de datos | Completar evidencia de cifrado, aislamiento, roles, auditoría, logs sanitizados y eliminación. La eliminación de credenciales no prueba eliminación de datos de negocio; sigue pendiente un ciclo verificable de eliminación dentro del alcance. |
| Simplificación | Cerrar inventario de consumidores y justificar qué mecanismos, compatibilidades, documentación o pruebas se conservaron o retiraron. No eliminar controles críticos para reducir volumen. |
| Capacidad y entrega | Verificar capacidad final frente a la referencia previa y explicar cualquier diferencia permanente; consolidar regresión final, evidencia, correspondencia código/imágenes y pendientes. |

No se asigna porcentaje global: las 52 ejecuciones no equivalen a 52 fórmulas
aceptadas y todavía faltan controles obligatorios. El estado verificable es
implementación avanzada con aceptación funcional y operativa incompleta.

## Resultado de la reconciliación productiva

Con `43e4a29` desplegado, el dry-run completo del piloto 82453304 y rango
2026-08-08 a 2026-09-06 terminó con código 0 y comprobación de fuente autoritativa
de reclamos. Ya con los conteos corregidos, los faltantes reales fueron mucho
menores que los 389 reportados antes: 1 snapshot de producto de catálogo, 5 filas
de fórmula, 11 entradas de índice SKU y 351 snapshots observados de precio/stock.

La primera escritura productiva se detuvo sin persistir por un HTTP 429 del
gateway (`retry_after=22s`) durante la adquisición de catálogo. Eso motivó
`5a03f06`: la adquisición de producto de catálogo y de buybox ahora espera el
Retry-After real (hasta tres intentos) en lugar de abortar; el 404 y el header no
numérico conservan el comportamiento previo.

La segunda escritura productiva pasó esa adquisición y avanzó hasta el umbral de
abortado configurado (`--error-threshold 50`), por lo que se detuvo antes de
publicar marcadores de frescura. Sí alcanzó a persistir la fase histórica. La
lectura posterior, independiente y de solo conteo, confirma:

| Read model | Antes de escribir | Después de escribir |
| --- | --- | --- |
| catalog_product_snapshots | 886 de 887 (1 faltante) | 887 de 887 (0 faltantes) |
| catalog_buybox_snapshots | 938 (alcance no certificable) | 938 (alcance no certificable) |
| sheets_item_formula_rows | 2872 de 2877 (5 faltantes) | 2881 de 2895 (14 faltantes) |
| sheets_item_sku_index | 2899 de 2910 (11 faltantes) | 2895 de 2888 |
| price_history_snapshots | 1567 de 1918 (351 faltantes) | 1567 de 1918 (351 faltantes) |
| stockout_snapshots | 1567 de 1918 (351 faltantes) | 1567 de 1918 (351 faltantes) |
| orders / shipments / items / questions / claims | 100/100/57/3/3 con referencias 103 | igual, sin faltantes |

Las expectativas de fórmula y SKU cambiaron entre ambas corridas (2877 → 2895 y
2910 → 2888) porque el universo de publicaciones se sigue moviendo; por eso
`missing_count` no es comparable como una simple resta entre corridas. Los 351
snapshots observados de precio y stock siguen sin escribirse, y el alcance de
buybox sigue sin poder certificarse porque hay participaciones desconocidas.

Ninguna fórmula quedó certificada como correcta por esta escritura: los marcadores
de frescura no se publicaron y el umbral de abortado impidió completar la fase.
Los datos persistidos sí quedaron en Mongo para consultas futuras, que es el
contrato pedido.

## Fuentes y continuación

Actualización posterior (13:30 UTC): el dry-run sobre `849b290` terminó con
código 1 y `mandatory_source_gate.authoritative=false`. Siguen sin fuente
esperada válida los conteos históricos de órdenes, envíos, artículos, preguntas
y reclamos; no se ejecutó escritura. Reportó 5 filas de fórmulas y 11 entradas
SKU faltantes, y 389 snapshots buybox faltantes respecto de sus expectativas.
Estos conteos no prueban por sí solos el origen ni la recuperabilidad de cada
ausencia.

Una consulta de solo conteo en Mongo desde el worker confirmó siete artículos
del piloto con `catalog_listing=true` sin ID de producto. El commit `4209304`
corrige ese caso reproducido por prueba, está en GitHub y tiene builds en curso:
worker `9928ace9-e389-482b-aedb-9ce72b8658e7`, API
`57f2cd9f-27cc-478e-9a37-edf68b918f84`. Ambos registros de Cloud Build señalan
la revisión exacta `42093046fac89de00869e85ca0c1c713d8fa3d9e` y estado WORKING
en la última observación. No se ha desplegado esa corrección ni se ha demostrado
que explique por completo la excepción histórica. Observar estos builds;
no repetirlos. El runtime observado sigue en `849b290`.

Actualización posterior de despliegue: ambos builds finalizaron SUCCESS con la
revisión exacta `42093046fac89de00869e85ca0c1c713d8fa3d9e`. El despliegue
worker → API terminó con código 0 y verificó ambos contenedores saludables.
Los digests activos verificados por el despliegue son:

- Worker: `sha256:4585407aca40d78d3eaa5da41a1371f5d5d0704127acc779ff0a21c60b068656`.
- API: `sha256:38b5b6ee19b8b1a19b9f05eca6547bdc1a4420b126f79a1fbd86d711281da7c5`.

Ambos preflights superaron 5 GiB libres (22 GiB observados). Los respaldos Compose
por servicio tienen sufijo `pre-<servicio>-4209304`. Los digests anteriores de
`849b290` quedan en la tabla para referencia. El cambio posterior `9409ff0` es
solo documentación y no requiere nueva imagen. Se inició un nuevo dry-run
diagnóstico (sesión local 8497), limitado a clases de excepción, estado HTTP,
funciones/líneas y conteos; todavía falta su resultado. No hubo escrituras de
reconciliación ni se afirma aceptación funcional por la salud del despliegue.

Resultado posterior del diagnóstico 8497: finalizó con código 0 y comprobación
de fuente de reclamos `authoritative=true`, sin códigos de incidencia. La fuente
histórica ahora reporta 103 órdenes, 100 envíos, 57 artículos, 3 preguntas y 3
reclamos; sus conteos de referencias faltantes son cero. El conteo de órdenes
persistidas en el intervalo es 100, por lo que aún debe explicarse la diferencia
de alcance temporal frente a las 103 referencias fuente antes de afirmar igualdad.

Se encontró otro defecto en la evaluación de catálogo:
`_collect_catalog_expected_counts` considera cada artículo con producto asociado
como candidato buybox, sin consultar `catalog_listing`, y omite productos de
variaciones. Una consulta de solo conteo desde Mongo en el worker devolvió
938 asociaciones con participación true, 529 false y cero desconocidas; además
hay siete participantes true sin producto. Los 1,467 candidatos del informe
incluyen los 529 no participantes. Por tanto, los 389 supuestos faltantes no
son evidencia suficiente para adquirir o marcar cobertura masivamente. Próximo
trabajo: corregir las expectativas con participación explícita y fuentes de
variaciones, conservar desconocido separado de false, probar ese contrato y
volver a validar los conteos. No se ejecutó escritura de reconciliación.

- [Recibo de las 52 ejecuciones](zelerdata-goal-smoke-20260910.json).
- [Registro de avance y pruebas](../zelerdata-goal-progress.md), incluidas las
  secciones de identidad de auditoría, controles mínimos y últimos despliegues.
- Objetivo original: archivo adjunto `pasted-text-1.txt` de esta misión.
- Consulta actual: `docker compose ps sheets-worker sheets-api` y árbol de
  procesos remoto, desde la VM autorizada, con salida limitada a servicio,
  imagen, salud y proceso de despliegue.

La siguiente acción técnica es el dry-run de reconciliación con la versión
desplegada, seguido de validación funcional y lectura persistida. Este informe no
autoriza ni recomienda borrar datos productivos como parte del cierre.

## Actualización de cierre — 11 de septiembre de 2026

Corte de observación: 2026-09-11 12:20Z. Esta sección reemplaza como referencia
vigente a las cifras de despliegue anteriores. Todas las mediciones son de solo
lectura o de overlay en contenedor, sin escrituras de reconciliación nuevas.

### Antes y ahora

| Dimensión | Antes (2026-09-07, `c5a2e097`) | Ahora (2026-09-11, `ac48e52`) |
| --- | --- | --- |
| Refresco programado | Inexistente; nadie renovaba marcas | En producción con `ZELERDATA_REFRESH_ENABLED=true`, seller `82453304`, intervalo 900 s y cuota 180 req/min |
| Marcadores de frescura | Vencidos y sin dueño | `orders` y `questions` renovándose en producción cada ~15 min; `devoluciones` y los cuatro modelos observados renovados por código nuevo (aún no desplegado) |
| Devoluciones | Timer systemd apagado desde el 2026-08-25 | Absorbidas al bucle de refresco; corrida autorizada `completed`, readback `5/5` y fórmula `OK rows=4` en producción |
| Fórmulas pesadas | 5 de 71 ejecuciones en 503 por el corte de 20 s | Precalculado implementado y probado; corte interno en 25 s ya en la imagen desplegada |
| Cola de descarte | 412 mensajes estancados del 2026-06-01 | Archivado real ejecutado: 282 archivados / 130 retenidos en `sheets_dlq_archives` |
| Alertas de frescura | Solo un mensaje al log | Código de alerta y evaluador en `main`, probados; canal y política reales en GCP **pendientes** |
| Imágenes desplegadas | `5a03f06` | Worker `548d73ed7e18` y API `4beec42b840d`, ambos saludables, **20 commits por detrás de `main`** |
| Fórmulas ejecutables | 52 HTTP 200 sin exactitud verificada | 45/52 con dato real y 0 errores en el rango de sondeo previo (era 41), y 47/52 en el rango vigente, medido con overlay de `main` |

### Fórmulas: medición de hoy

Con el overlay de `main` (`ac48e52`) sobre la imagen desplegada y datos reales del
piloto, el sondeo de las 52 fórmulas dio **0 ERROR** en todas las corridas.
Medido con el mismo rango (2026-08-08 a 2026-09-06), el resultado pasó de **41 OK /
11 UNAVAILABLE** a **45 OK / 7 UNAVAILABLE**. Ese delta viene de ejecutar el código
nuevo de renovación de marcadores en el overlay, no de un despliegue: el runtime
sigue en la imagen anterior. Con el rango vigente (2026-08-09 a 2026-09-10) el
resultado es **47 OK / 5 UNAVAILABLE**.

De las 7 UNAVAILABLE en el rango previo, cinco son las mismas del rango vigente y
dos (`ZELERDATA_PREGUNTAS`, `ZELERDATA_PREGUNTASKPI`) dependen de la ventana
conciliada de `questions`: al consultar un rango que empieza antes de esa ventana
la fórmula falla a propósito. Ninguna de las restantes es fallo de ejecución; su
causa es de origen de datos:

- `ZELERDATA_TIEMPOSTOCKACTIVO` y `ZELERDATA_SEMANASCONSTOCK` dependen de
  `stock_time_metrics`, y `ZELERDATA_CATALOGOTIEMPO` de `catalog_time_metrics`.
  `ZELERDATA_RETIROS` depende de `full_withdrawals`. Las tres colecciones
  (`sheets_stock_time_metrics`, `sheets_catalog_time_metrics`,
  `sheets_full_withdrawals`) tienen **0 documentos** para el piloto.
- La causa está medida: sus fuentes `item_history_projection`, `meli_item_events` y
  `withdrawal_records` **no existen** en la base productiva, así que el importador
  source-gated reporta `planned=0`, `source_inventory_counts=0` y
  `coverage_complete=false` para los tres modelos. No es recuperable
  sincrónicamente desde Mercado Libre con lo que hay hoy.
- `ZELERDATA_DEVOLUCIONES` responde `OK rows=4` con el marcador renovado. Sigue
  apareciendo como UNAVAILABLE en el sondeo porque su ventana conciliada es
  2026-06-01..2026-06-11 y el sondeo pide rangos posteriores; no es un fallo de
  ejecución sino un rango fuera de la cobertura certificada.

Nota metodológica: un rango que empieza antes de la cobertura conciliada produce
UNAVAILABLE aunque haya dato debajo. Al sondear 2026-06-01..2026-06-10 quedaron
fuera, por esa razón, `ZELERDATA_PREGUNTAS`, `ZELERDATA_PREGUNTASKPI` y seis
fórmulas de órdenes (`ORDENES`, `UNIDADESVENDIDAS`, `ORDENESPORSKU`,
`TOPVENTASUNIDADES`, `TOPVENTASDINERO`, `VENTASTOTALES`); todas responden cuando el
rango cae dentro de la ventana conciliada. El sondeo debe usar el rango del periodo
que la fórmula va a consultar de verdad.

### Devoluciones: verificación E2E de hoy

- `advance_due_devoluciones_run(..., advance_enabled=False)` sobre producción
  movió el marcador de `stale` (source `devoluciones_operation_acquire`, escrito
  por el recovery de `orders`) a `reconciled` (source `zelerdata_devoluciones_quota_run`),
  con `date_from=2026-06-01`, `reconciled_until=2026-06-11` y lease de 30 min.
- Inmediatamente después, `ZELERDATA_DEVOLUCIONES` ejecutó en **0.02 s** y
  devolvió **4 filas** de 5 reclamos (`claims_count=5`, `order_count=5`,
  `rows_count=4`).
- La renovación solo lee Mongo y republica un finalize ya probado;
  nunca llama a Mercado Libre ni amplía cobertura.

### Despliegue (resuelto el 2026-09-11)

El bloqueo de autenticación quedó resuelto y el despliegue se completó. Estado
verificado:

| Servicio | Imagen desplegada | Digest | Estado |
| --- | --- | --- | --- |
| `sheets-worker` | `sheets-worker-39849ad-20260911T195000Z` | `sha256:23f0e55a…` | healthy |
| `sheets-api` | `sheets-api-648d449-20260911T140119Z` | `sha256:14bda442…` | healthy |

La imagen del worker ya incluye `formulas/precalculated.py`,
`observed_read_model_markers.py`, `devoluciones_runner.py` y
`zelerdata_freshness_alarm.py`. Los cuatro marcadores observados se renuevan
cada ciclo (medido: `item_status_states`, `price_history_snapshots`,
`shipments`, `stockout_snapshots` con lease nuevo), las diez entradas de
`sheets_formula_precalculated` se refrescan y las 52 fórmulas respondieron 200
en una ejecución real de la hoja a las 18:41 UTC.

El `sheets-api` no se reconstruyó porque el barrido de recuperación vive en el
worker; la API solo encola (`FormulaRecoveryQueue`) y su imagen actual ya expone
esa ruta.

#### Defectos corregidos durante el despliegue

1. El barrido de `orders` adquiría el lease compartido con
   `invalidate_readiness=True` y retiraba el marcador probado de
   `devoluciones` en cada ciclo. Ahora adquiere con `False`, igual que el
   handler de eventos `orders.*`; solo `claims.*` invalida readiness.
2. `renew_devoluciones_marker_if_proven` solo extendía el lease cuando ya había
   expirado, dejando una ventana indisponible cada media hora. Ahora es un
   latido por ciclo.
3. La renovación exigía igualdad byte a byte del `proof_fingerprint`, que
   incluye conteos vivos de `claims`. El primer reclamo legítimo dentro del
   rango la congelaba para siempre (`reason=proof_changed` medido en
   producción). Ahora certifica que el rango siga completo: mismos límites,
   mismo esperado, sin faltantes y todas las filas persistidas y completas.
4. Cada rechazo del latido registra su motivo
   (`zelerdata.devoluciones_renewal_refused`) para que un latido detenido sea
   diagnosticable.

Verificación posterior al despliegue: `devoluciones` renovó por ciclo propio a
las 20:33 UTC (lease hasta 21:03), `ZELERDATA_DEVOLUCIONES` respondió 4 filas en
0.02 s y `evaluate_refresh_alarms` devolvió `()`.

También se activó `ZELERDATA_FRESHNESS_ALERTS_ENABLED=true` en
`/opt/zeler-platform/env/sheets-worker.env` (respaldo
`.bak-pre-freshness-alerts-20260911`), con lo que un modelo detenido emite ahora
la alarma `zelerdata.freshness_alarm` hacia la política
`zelerdata-freshness-alarm` y el canal `zelerdata-ops-email`.

### Alertas y archivado

El archivado de la cola de descarte sí se ejecutó: `sheets_dlq_archives` tiene 282
documentos del 2026-09-11.

La alerta de frescura ya existe como recurso de GCP, creada el 2026-09-11:

| Recurso | Identificador |
| --- | --- |
| Métrica log-based | `zelerdata_freshness_alarm` |
| Canal de correo | `zelerdata-ops-email` → `laloramirez@zeler.ai` |
| Canal existente | `zeler-ops-email` → `ops@zeler.ai` |
| Política | `zelerdata-freshness-alarm` (umbral > 0 en 300 s) |

El reportero corre en el worker con `ZELERDATA_FRESHNESS_ALERTS_ENABLED=true` y
`evaluate_refresh_alarms` devolvió `()` con los siete modelos esperados, así que
la política no está disparando por ruido. Pendiente del lado del usuario: aceptar
la invitación de verificación que Google envió a `laloramirez@zeler.ai`; el canal
existe y está `enabled`, pero sin confirmar el correo no entregará avisos.

### Fórmulas pesadas: precalculado verificado E2E

Entrega 2 verificada hoy contra producción con el overlay de `main`. El warmer
del ciclo de refresco calculó y almacenó **10 entradas** (5 fórmulas × 2 variantes
de encabezados) en 33.18 s de trabajo de fondo:

| Fórmula | Filas por variante | Lectura desde el store |
| --- | --- | --- |
| `ZELERDATA_CALIDAD` | 1920 / 1919 | 0.0105 s / 0.0148 s |
| `ZELERDATA_CATALOGO` | 163 / 181 | 0.0053 s / 0.0034 s |
| `ZELERDATA_CATALOGOBUYBOX` | 165 / 164 | 0.0025 s / 0.0022 s |
| `ZELERDATA_CATALOGO_COMPLETO` | 193 / 187 | 0.0026 s / 0.0028 s |
| `ZELERDATA_DASHBOARD` | 2873 / 2872 | 0.0299 s / 0.0311 s |

Todas las lecturas devuelven `precalculated=true`, con `valid_until` de la misma
ventana que las marcas de frescura. La llamada de fórmula pasa así de 2.4–5.6 s de
cálculo en vivo a 2–31 ms de lectura acotada, que es el puente acordado (Q3, Q8,
Q16) frente al corte de 30 s de Google. Ya desplegado en el worker
`sheets-worker-39849ad-20260911T195000Z`.

### Latencia de las fórmulas

Medición de hoy con el overlay de `main` sobre producción, ejecutando las 52
contratos en proceso contra Mongo real (no incluye la sobrecarga de Apps Script):

| Métrica | Valor |
| --- | --- |
| Deadline interno | 25.0 s (`FORMULA_DEADLINE_SECONDS`, ya en la imagen desplegada) |
| p50 | 0.093 s |
| p95 | 4.297 s |
| Máximo | 5.607 s (`ZELERDATA_MEDIDASGENERAL`) |
| Fórmulas sobre el deadline | 0 |

El margen frente al corte de 30 s de Google es amplio incluso para la fórmula más
lenta. Las cinco más lentas (`MEDIDASGENERAL`, `CALCULADORA`, `OBTENER_CATALOGO`,
`MEDIDAS`, `SUPERMERCADO`) quedan entre 3.4 s y 5.6 s.

### Ciclo de refresco vivo (estado final)

El defecto quedó corregido y desplegado. Estado verificado tras el despliegue:

| Marcador | Renovación observada | Estado |
| --- | --- | --- |
| `devoluciones` | ciclo propio a las 20:33Z, lease hasta 21:03Z | abierto, sin rechazos |
| `orders` | ciclo a las 20:19Z, lease hasta 20:49Z | abierto |
| `questions` | ciclo a las 20:18Z | abierto |
| `item_status_states`, `price_history_snapshots`, `shipments`, `stockout_snapshots` | ciclo a las 20:36Z | abiertos |

`ZELERDATA_DEVOLUCIONES` respondió 4 filas en 0.02 s
(`claims_count=5`, `order_count=5`) y las 10 entradas de
`sheets_formula_precalculated` se refrescan cada ciclo. Las 52 fórmulas
respondieron 200 en una ejecución real de la hoja a las 18:41Z.

El latido de `devoluciones` no produjo ningún
`zelerdata.devoluciones_renewal_refused` después del despliegue.

### Cambio de configuración aplicado en la VM

En `/opt/zeler-platform/env/sheets-worker.env` están activas, con respaldo
previo por cada cambio:

| Variable | Valor | Respaldo |
| --- | --- | --- |
| `ZELERDATA_DEVOLUCIONES_ADVANCE_ENABLED` | `true` | `.bak-pre-devoluciones-advance-20260911` |
| `ZELERDATA_PRECALCULATED_FORMULAS_ENABLED` | `true` | `.bak-pre-precalc-20260911` |
| `ZELERDATA_FRESHNESS_ALERTS_ENABLED` | `true` | `.bak-pre-freshness-alerts-20260911` |

La renovación de un marcador ya probado **no** depende de la bandera de
devoluciones: solo gobierna el trabajo de fuente.

### Verificación de calidad en `main`

- `uv run pytest`: exit 0.
- `uv run ruff check .`: All checks passed.
- `uv run mypy .`: Success, 526 archivos.
- `uv run ruff format --check .`: 526 archivos ya formateados, sin drift.


## Aceptación de fórmulas sin histórico

Decisión de producto del 2026-09-24: `DATA_UNAVAILABLE` es un resultado
aceptable cuando falta el histórico requerido para `ZELERDATA_CATALOGOTIEMPO`,
`ZELERDATA_TIEMPOSTOCKACTIVO`, `ZELERDATA_SEMANASCONSTOCK` y
`ZELERDATA_RETIROS`. Dependen de `catalog_time_metrics`, `stock_time_metrics`
y `full_withdrawals`, que tienen 0 documentos para el piloto; sus fuentes
(`item_history_projection`, `meli_item_events`, `withdrawal_records`) no
existen en la base productiva. Las cuatro fórmulas permanecen en el contrato
de 52; esta decisión no certifica cobertura histórica ni autoriza presentar
datos actuales como si fueran históricos.

## Pendiente al entregar

Estos puntos quedan **fuera** de lo entregado y no están bloqueados por un
defecto del código:

1. **Aceptación del canal de alertas.** El canal `zelerdata-ops-email`
   (`laloramirez@zeler.ai`) existe y está `enabled`, pero Google exige que el
   destinatario acepte la invitación de verificación antes de entregar correo.
2. **Ventana de una semana sin errores.** El criterio de éxito acordado (cero
   fórmulas en error durante una semana completa de uso real) empieza a contar
   con esta entrega; no puede declararse cumplido todavía.
3. **Drift de tres marcadores legacy.** `catalog_buybox_snapshots`,
   `catalog_product_snapshots`, `claims` e `item_formula_rows` están
   `reconciled` sin `valid_until` y con marcador de junio/julio. No los renueva
   el ciclo (no forman parte de los modelos con dueño) y quedan como
   reconciliaciones puntuales, no como latido.
4. **Reintentos y limpieza de la cola de descarte.** Cerrado el 2026-09-11:
   el reintento con espera creciente ya estaba implementado
   (`MAX_ATTEMPTS=3`, backoff 30s·2^(n-1)); el archivado automático quedó
   conectado al ciclo de refresco y desplegado en
   `sheets-worker-87deeee-20260911T221519Z`. La primera corrida automática
   registró `archived=0`, `retained=134`, `stopped_reason=None`; los 134
   mensajes retenidos son `items.updated` (82), `shipments.updated` (50) e
   `items.price_updated` (2) del 2026-08-13 al 2026-09-11. Ninguno cumple hoy
   la evidencia de `window_reconciled` ni `age_exceeded`, así que no deben
   eliminarse: quedan en cola con motivo, y la corrida automática diaria los
   volverá a evaluar.
5. **Hojas de cálculo y Apps Script.** Por Q35 quedaron explícitamente fuera
   hasta que ZelerData esté estable.
