# ZelerData: implementación local del histórico al vincular

Fecha: 2 de octubre de 2026. Este informe acredita desarrollo local y pruebas
aisladas, **no despliegue ni aceptación productiva**, y no convierte una fuente
pendiente en completa. Commit/push propios publicados después del cierre local: fuente
`4216e18b62da289c1e67acd1ac8d6db4ba0c9217`. Su ejecución e identidad se registran en el
[recibo de publicación](zelerdata-historico-publicacion-20261002.md).

Referencia de aceptación:
[especificación](zelerdata-historico-al-vincular-especificacion.md).

## Estado de los cuatro cierres solicitados

| Clasificación | Resultado |
| --- | --- |
| **Completado localmente** | Mensaje nuevo de orden antigua sin cambios: recuperación periódica real; tabla de 9,999 órdenes adquiridas + 1 pendiente mediante API autenticada normal; capacidad compartida de dos fuentes no vacías y certificados de 1,000 membresías. |
| **Bloqueado por evidencia externa concreta** | Mapeo positivo RETIROS Full: no se acredita aún jerarquía retiro/bulto, cantidad originalmente solicitada ni fecha de solicitud. Investigación pública cerrada; [muestra propuesta](zelerdata-full-validacion-acotada.md), ≤10 GET reales, no ejecutada. |
| **Pendiente de validación productiva** | Backup consistente/restore aislado, builds/deploy por autorizar, permisos/digests/readiness actuales, OAuth legítimo, carga real por fuente, dos cambios reales y fórmulas nativas. |

[Propuesta de publicación/piloto con respaldo y rollback](zelerdata-historico-publicacion-piloto-propuesta.md).
Las tres categorías no se intercambian: una fuente bloqueada no impide los datos
útiles de las demás; una prueba local no demuestra despliegue ni aceptación real.

## Lectura rápida

- OAuth admite una intención durable antes de omitir un bootstrap ya completado.
  Relink no usa `force` para reiniciar el histórico ni reemplaza sus checkpoints.
- La ejecución se activa por separado con `ZELERDATA_HISTORY_ON_LINK_ENABLED`.
  Dentro de esa activación, las cuentas elegibles usan una política persistida,
  sin prompts por mes y sin una lista fija de vendedores piloto.
- Hay progreso independiente por fuente, presupuestos, leases, checkpoints,
  parciales identificados y mantenimiento incremental. Packs conocidos antiguos
  reciben una recuperación periódica acotada aunque la orden no cambie. La cobertura exacta se
  comprueba por sus lectores/certificados; el estado del plan no la sustituye.
- **Retiros Full sigue pendiente de cerrar su contrato de fuente**. Se implementa
  adquisición auténtica de operaciones, pero no se convierten operaciones de
  stock en filas de RETIROS inventando identidades o cantidades solicitadas.
- Falta validar el circuito real: autorización de build/despliegue,
  backup consistente, OAuth, lectura nativa y dos actualizaciones productivas.

## Qué se integra y qué no se promete

| Fuente | Camino local | Límite de interpretación |
| --- | --- | --- |
| Órdenes/comisiones | Plan fijo, jobs históricos y escritores existentes; fallback parcial por identidad. | `sale_fee` no es facturación. Un rango sin prueba no es un total exacto; canceladas nunca enumerables no quedan certificadas. |
| Preguntas/respuestas | Adquisición histórica y escritor canónico; respuesta incompleta queda pendiente. | No inventar respuesta ni KPI por un estado `ANSWERED` insuficiente. |
| Envíos/costos | Dependencias deduplicadas de órdenes adquiridas. | Orden ausente o costo ausente afecta su dependencia; costo desconocido no es cero. |
| Reclamos/devoluciones | Autoridad de onboarding sobre runs exactos existentes, ventanas acotadas y mantenimiento. | Certificados conjuntos siguen fail-closed; otro período no invalida uno independiente ya sano. |
| Mensajes | Enumeración por packs, paginación, checkpoints y modelo canónico. | Solo lectura con `mark_as_read=false`; no enviar, responder ni marcar leído. |
| Full | Operaciones reales por vendedor/fechas y scroll, con progreso separado. | No certifica el contrato de RETIROS mientras falte el mapeo auténtico requerido. |

No se agregan visitas, facturación, liquidaciones, nuevas fórmulas, otro frontend,
reconstrucción retroactiva de snapshots ni adquisiciones productivas implícitas.

## Autoridad, disponibilidad y visibilidad

La política conserva vendedor, versión, corte, intervalo, fuentes y presupuesto.
Cada intento remoto se cobra antes del envío. La adquisición comprueba identidad,
pertenencia, elegibilidad y ámbito; una revocación no permite seguir usando el
plan como una autorización independiente de la cuenta.

La carga inicial conserva su presupuesto y corte originales. El mantenimiento
usa una política diaria aparte; renovar esa cuota no reinicia jobs anuales.
Onboarding y recovery existente comparten el pacer de adquisición. Los jobs
admitidos por la política llevan una autoridad que los workers legacy excluyen:
compartir colas no autoriza ejecutarlos por otra ruta ni eludir su contabilidad.
Los jobs legacy previos pueden drenar bajo su autoridad anterior, sin takeover.

Los estados y observaciones se exponen mediante la ruta autenticada existente
`GET /sheets/backfill/progress?seller_id=...`. La respuesta añade estado de
onboarding, fuentes, presupuesto e intervalo solicitado. Su `exact_coverage=false`
declara que este resumen no certifica toda la incorporación. La aplicación y
Apps Script no deben inferir exactitud del estado agregado ni de un conteo de filas.

Un fallo de detalle puede producir filas canónicas útiles y un pendiente durable.
El lector exacto sigue rechazando el intervalo afectado sin su prueba. No se
cambia silenciosamente el contrato de tablas/agrupaciones ni se presenta una suma
parcial como total. Esta entrega no demuestra consumo parcial nativo en Sheets.

### Consulta real de los parciales mediante el API normal

La petición autenticada a `POST /sheets/formulas:execute` admite opt-in estricto
`allow_partial: true` **solo para `ZELERDATA_ORDENES`**. Reutiliza el handler,
proyección y autorización por cuenta actuales; no añade otra fórmula/frontend.

```json
{
  "formula": "ZELERDATA_ORDENES",
  "cuenta": "PILOT",
  "allow_partial": true,
  "args": {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30"}
}
```

Ejemplo de contrato, no ejecución ni datos de una cuenta real. La prueba
[API parcial](../../modules/sheets/tests/test_partial_history_api.py) adquiere
10,000 identidades con validadores reales y un detalle fallido. Consulta el
endpoint con token normal de extensión, limitado a la cuenta del fixture:
**9,999 líneas reales**, cantidad/precio/comisión, costos ausentes `NA`, más una
fila de aviso `PARCIAL` del ancho de la tabla. `meta.coverage` indica `exact=false`,
`scope=acquired_rows_only`, rango y motivo; pendiente desconocido queda `null`,
no cero inventado. Aviso visible aunque un consumidor descarte metadatos.

Default y `ZELERDATA_VENTASTOTALES` afectados siguen `DATA_UNAVAILABLE`; pedir
opt-in para un agregado devuelve `BAD_ARGUMENT`. Un argumento interno falsificado
no habilita parciales; token ajeno/inválido no consulta los datos. Rango sano
independiente permanece legible y su certificado intacto. Incluso vacío sin
prueba devuelve aviso, no el significado falso de "cero ventas". Con prueba válida,
el opt-in conserva el resultado exacto existente.

**Límite:** no se modificó la firma del add-on; no solicita este opt-in. Esta
entrega demuestra API normal, no consumo parcial nativo ni nueva UI de Sheets.

### Mensajes antiguos: continuidad acotada y reinicio

La [prueba de coordinador](../../modules/sheets/tests/test_history_old_messages.py)
cubre una orden de 200 días sin cambios, con mensaje posterior al cutoff. Se
recupera por pack conocido, no por selección exclusiva de órdenes recientes.
Cursor separado `message_periodic_recovery`, batches de **40 packs** deduplicados,
**dos páginas máximas por turno**, alternancia con el histórico inicial y cuota
incremental/pacer/lease comunes. No se reinician ni reemplazan jobs anuales.

Cada sweep congela fin y filtra por creación **del mensaje**: primer intervalo
cutoff−5 minutos→inicio del sweep; posteriores solapan cinco minutos. Terminado
el sweep, espera al menos 15 minutos. Offset/cursor reanudan; agotar cuota tras
una página exitosa conserva ese avance para el siguiente día, en lugar de repetir
eternamente la primera página. CAS impide publicar checkpoint bajo lease reemplazado.
Progreso sanitizado aparece en `/sheets/backfill/progress`, sin IDs ni texto.

La API de packs no acredita orden incremental/filtrado remoto por fecha. Visitar
un pack puede requerir páginas antiguas; no se afirma catch-up de una llamada,
latencia fija ni descubrimiento de packs desconocidos. La carga está acotada por
turno/cuota y no vuelve a admitir el año; el volumen anual remoto sigue por medir.

El piloto dispone de scope opcional `ZELERDATA_HISTORY_ON_LINK_SELLERS`: restringe
el **claim real**, antes de renovación/adquisición. Ausente conserva producto
multicuenta normal; lista explícita vacía/wildcard/ID no canónico falla startup.
[Test de scope](../../modules/sheets/tests/test_history_pilot_scope.py) confirma que
otra cuenta/plan queda completamente intacta. El allowlist de recovery ajeno no
se usa como prueba de este límite.

### Full: evidencia y bloqueo preciso

La documentación oficial consultada el 2 de octubre de 2026 describe
`/stock/fulfillment/operations/search`, rango máximo de 60 días, páginas de hasta
1000 operaciones y scroll de cinco minutos, terminado por `scroll=null`. La
fecha final de consulta excluye ese día. Distingue reserva/cancelación de retiro
físico y de descarte/remoción.
[Fuente oficial](https://developers.mercadolibre.com.mx/es_mx/envios-fulfillment).

Ese contrato público no demuestra todos los identificadores/detalles y la
cantidad solicitada exigidos por el contrato actual de RETIROS. No se deduce de
ello que ningún recurso legítimo pueda proporcionarlos: queda por acreditar el
recurso/mapeo compatible. Mientras tanto, no se fabrica `withdrawal_id`, no se
usa el ID de operación como si fuera el de retiro, no se rellena una cantidad
desconocida y no se publica cobertura de `sheets_full_withdrawals`.

La [protección normal](../../modules/sheets/tests/test_full_onboarding_handler.py)
prueba colector real→operaciones en Mongo→dispatcher/handler RETIROS/lector normal:
**dos casos** rechazan rango no certificado, incluso con delta y referencia
candidata sintética. Es prueba negativa de protección, **no mapeo positivo**.
Faltan evidencia real de campos/semántica y un retiro conocido para contrastarlos;
la [propuesta exacta](zelerdata-full-validacion-acotada.md) fija presupuesto/rutas,
plazo y criterio de parada. No se copió la derivación legacy por siete dígitos ni
se abrió facturación fuera del alcance.

Un 403 es restricción de acceso, no evidencia de "no aplica". Una enumeración
vacía tampoco prueba que el vendedor carezca de Full. Se conservan datos legacy
y su procedencia; no se los reetiqueta como adquiridos por API.

### Contratos de fuente y horizonte

Consulta de referencias oficiales: 2 de octubre de 2026, mediante contenido
indexado; algunos accesos directos devolvieron 403. No fue una consulta autenticada
de API ni comprobación de permisos del vendedor. El corte se guarda en UTC y la
resta es de meses calendario, no de 365 días; el filtro de cada fuente se adapta
sin confundir límites de consulta con retención.

| Fuente y referencia oficial | Contrato usado / límite que debe seguir visible |
| --- | --- |
| [Órdenes](https://developers.mercadolibre.com.mx/gestiona-ventas), actualización 21/09/2026 | Búsqueda por creación/modificación y detalle; horizonte documentado de 12 meses. El buscador de vendedor puede omitir canceladas; conocer una cancelada y revalidarla no prueba descubrimiento de todas las desconocidas. |
| [Preguntas](https://developers.mercadolibre.com.mx/en_us/listing-types-item-upgrades-tutorial/manage-questions-and-answers), actualización 15/01/2026 | `api_version=4`, orden por `date_created` ASC/DESC. El incremental verifica monotonicidad antes de detenerse en el borde antiguo. La eliminación de preguntas sin respuesta mayores a siete meses no acredita un horizonte universal para respondidas ni recuperación anual completa. |
| [Mensajes](https://developers.mercadolibre.com.mx/es_ar/manejo-de-pagos/mensajeria-post-venta), actualización 27/04/2026 | `limit/offset`, total y `mark_as_read=false`. No se encontró garantía de orden cronológico, filtro de fecha ni retención anual universal. El incremental limita packs a órdenes recientes/cambiadas; cambios de packs antiguos inactivos sin evento/cambio de orden **no quedan demostrados**. |
| [Reclamos](https://developers.mercadolibre.com.mx/que-es-un-reclamo), actualización 20/08/2026 | Vendedor mediante `players.user_id`/rol; rangos de creación/actualización con milisegundos, `limit≤100` y `offset+limit<10000`. Ventanas densas se subdividen acotadamente; una ventana irreducible queda pendiente, no completa. No se garantiza retención anual universal. |
| [Devoluciones](https://developers.mercadolibre.com.mx/en_us/introduction-services/ml-returns), actualización 25/03/2024 | Detalle `/post-purchase/v2/claims/{id}/returns`, relacionado con reclamos/órdenes. No es una fuente independiente de totalidad anual ni movimientos financieros. |
| Full, referencia anterior | Solicitud máxima de 60 días, partición del coordinador de 59 días. La nota de stock de 12 meses no demuestra retención de operaciones. El contrato completo de RETIROS permanece pendiente. |

Se reutilizan adquiridores de envíos/costos y se valida pertenencia/relación.
El ensayo productivo todavía debe confirmar acceso y datos reales por fuente;
ninguna referencia pública sustituye esa aceptación.

## Evidencia aislada y sus límites

### Capacidad compartida de esta continuación

[Prueba representativa](../../modules/sheets/tests/test_history_onboarding_shared_capacity.py),
**1 passed, 12.94 s**, Mongo rs0 real y validadores/índices canónicos. Dos
instancias de `HistoryOnboardingWorker.process_once` y pacer compartido, sin
reemplazar scheduler ni llamar colectores directamente como aceptación.

| Medición | Resultado local |
| --- | --- |
| Cuentas / turnos reales | Dos / 168. |
| Certificados poblados | 12 × 1,000 membresías; 12,000 reclamos y 12,000 órdenes. |
| Fuentes no vacías | 2,000 mensajes (pasos de 200) y 50 preguntas (0→20→45→50), adquisición/publicación con workers reales. |
| Intentos físicos | 158; 79 por cuenta, igualdad física/cobro por fuente y total inicial/diario dentro de límites. |
| Adquisición inicial | 3.425 s, proveedor simulado. |
| Pacer compartido | 52.333 s de espera **simulada**, no tiempo HTTP real. |
| Renovación | A 15/30/45/60 minutos, pendientes 12→0 por ciclo; seis certificados/cuenta en el batch, chequeo individual <5 s, vigencia restante >28 minutos. |
| Ciclo de seis turnos, renovación + fuentes | Máximo 0.807 s; ambas fuentes continúan efectuando solicitudes. |
| Mongo vivo concurrente | 707 operaciones, latencia máxima 38.6 ms. |

El lector normal de proof valida 1,000 reclamos/órdenes por certificado y
conserva membresía/hash; renovar no certifica actualización remota. Preguntas y
mensajes no vacíos comparten coordinador con las renovaciones. Órdenes/reclamos
están en backoff de fixture y Full usa respuesta vacía: **no** benchmark remoto
anual de esas adquisiciones, Mongo RSS, HTTP/broker vivo ni Sheets nativo. Esto
cierra capacidad **representativa local**, no perfección ni SLA.

### Capacidad de la primera entrega

[Prueba ejecutable](../../modules/sheets/tests/test_history_onboarding_capacity.py):
Mongo real, replica set desechable, validadores/índices de mensajes y certificados.

| Medición | Resultado local |
| --- | --- |
| Mensajes anuales | 20,000; 10,000 por vendedor, dos vendedores. |
| Llamadas de fuente | 400; límite físico de 200 por cuenta. |
| Adquisición | 39.642 s; backlog 20,000 → 0, publicación progresiva y checkpoint persistido/readback. |
| Memoria Python | Máximo 659,154 bytes con `tracemalloc`; no es RSS de Mongo. |
| Trabajo Mongo concurrente | 3,156 operaciones; latencia máxima observada 0.0108 s. |
| Certificados anuales | 74; 37 por cuenta, 74 reclamos y 74 órdenes relacionadas, no vacíos. |
| Renovación | Scheduler real, minutos 15/30/45/60 con reloj controlado; pendientes 74 → 0 por ciclo. |
| Verificación local | Lote de dos cuentas máximo 0.417 s; memoria Python máxima 325,090 bytes. |
| Justicia | Las seis fuentes reciben turnos para ambas cuentas aunque una adquisición simulada falle. |

Comando de capacidad: `uv run pytest modules/sheets/tests/test_history_onboarding_capacity.py -s`:
**3 passed, 44.03 s**. Medición adicional de renovación: **1 passed, 2 deselected,
4.82 s**. Estos tiempos son mediciones, no SLA.

La carga de mensajes usa un harness round-robin y la renovación usa scheduler
real con adquisición simulada fallida. **No** demuestra adquisición remota anual
de 10,000 órdenes/reclamos, tráfico vivo HTTP/Meli/broker, memoria Mongo,
ausencia universal de hambre ni fórmulas nativas. T-22 tiene evidencia relevante,
pero su aceptación integral por todas las fuentes permanece pendiente.

### Backup/restauración local

Se comprobó `mongodump`/`mongorestore` de un fixture quiescente en bases
desechables distintas: **10,000 filas, ocho colecciones, 16 índices**, igualdad de
hashes de BSON canónico antes/después y conservación en el origen de un hecho
posterior y un sentinel de versión de cuenta. Archivo comprimido de 48,496 bytes,
permisos `0600`, eliminado después del ensayo; dump/restauración 0.501 s.

Esto verifica transporte/integridad de un respaldo sintético aislado. No acredita
consistencia entre colecciones productivas con writers concurrentes, restauración
de todos los nuevos contratos ni rollback de tokens/datos reales. Nunca se
restauró sobre el origen ni sobre producción.

### Controles finales de esta continuación

Código/configuración/tests congelados: **36 archivos**, hashes estables durante
la suite; documentos actualizados aparte. Mismo destino desechable explícito,
Mongo rs0 PRIMARY/sesiones, Rabbit loopback, Linux Python 3.11/Node18/`--init`,
checkout solo lectura y caches fuera del checkout; aceptación secuencial, sin OOM.

| Control | Resultado final |
| --- | --- |
| `uv run pytest` completo, sin exclusiones | **5,808 passed, 9 skipped, 402.77 s**; cero fallos. |
| Ocho tests protegidos stock-time, `MONGO_URI` ausente y rs0 explícito | **8 passed, 0 skipped, 2.10 s**; adquisición, commit/abort y rollback con Mongo real. |
| Ruff | Aprobado. |
| Format | Aprobado; 643 archivos. |
| Mypy completo | Aprobado; 643 archivos, no selección reducida de CI. |
| Direct Meli lint y schema export `--check` | Aprobados. |
| Cinco controles estáticos nativos macOS | Aprobados sobre el mismo snapshot final. |
| Diff check, enlaces locales de los tres reportes y preservación de HEAD ajeno | Aprobados. |

Los ocho skips de la suite completa son la protección de URI ambiente y quedaron
cubiertos por la corrida separada. El restante es Caddy sin claves requeridas;
no acredita TLS/ingress real. No se repitió la suite completa nativa de macOS:
las doce incompatibilidades Bash3.2 anteriores siguen documentadas como baseline,
no se modificaron scripts ajenos ni se las ocultó para declarar aceptación.

TDD de los cierres: API normal no permitía parciales antes del cambio; coordinador
no encontraba mensaje de orden antigua; guard de piloto ausente; pérdida de
checkpoint al agotarse cuota a mitad de turno. Se observaron fallos, se corrigió
la causa y se repitieron checks. Capacidad no requería cambio ejecutable de
producto: fixture y aserciones se fortalecieron con ambas fuentes no vacías.
Protección Full ya existía: caracterización negativa, no red artificial ni mapeo.

Cierre de recursos: retirados únicamente los tres contenedores propios de esta
continuación y sus volúmenes desechables; imágenes preexistentes preservadas,
profile dedicado detenido y contexto Docker original `colima` conservado.
Al cerrar las pruebas locales no hubo commit/push, build de imágenes, consulta
autenticada ni mutación productiva. La autorización posterior de publicación y
el intento de búsqueda UI de solo lectura se distinguen en el recibo; no
autorizan builds, API reales ni operación productiva.

### Controles del repositorio — primera entrega

Snapshot final congelado: 30 archivos de código/configuración/tests con hash
estable durante la aceptación; reporte documental separado. Checkout montado
solo lectura en contenedor Linux Python 3.11, Node 18, PID 1 con `--init`, caches
fuera del checkout; **sin build de imágenes**. Mongo rs0 desechable y RabbitMQ
solo loopback, sin credenciales ni datos productivos. Profile de pruebas separado,
default Colima conservado detenido. Al finalizar se retiraron exclusivamente
los cinco contenedores propios y sus volúmenes desechables, se eliminó la imagen
Mongo adicional descargada para este ensayo (sin builds/prune) y se detuvo el
profile de pruebas. Contexto Docker original `colima` conservado; ambos profiles
quedaron detenidos, como al inicio. Las imágenes preexistentes no se retiraron.

| Control final | Resultado |
| --- | --- |
| `uv run pytest` completo, sin exclusiones | **5,777 passed, 9 skipped, 356.62 s**; cero fallos. |
| `uv run ruff check .` | Aprobado. |
| `uv run ruff format --check .` | Aprobado; 638 archivos. |
| `uv run mypy .` | Aprobado; 638 archivos, no solo selección de CI. |
| `uv run python -m infra.lint.check_direct_meli .` | Aprobado. |
| `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check` | Aprobado. |

Los cinco controles estáticos se repitieron también en macOS sobre el snapshot
final: aprobados. `git diff --check` y enlaces locales del reporte: aprobados.

Ocho skips de la suite completa corresponden a la protección explícita de tests
stock-time contra `MONGO_URI` ambiente. Se ejecutan aparte con URI rs0 loopback y
sin esa variable: **8 passed, 0 skipped** (adquisición, commit/abort transaccional
y rollback con Mongo real, **1.92 s**). El noveno es un contrato Caddy
sin claves requeridas; no acredita TLS/ingress vivo.

Un intento previo de ejecutar dos suites en paralelo agotó memoria del Mongo
desechable (OOM). Se interrumpieron exclusivamente procesos propios: **ese intento
no cuenta como evidencia**. Se recreó la base de pruebas, limitó caché WiredTiger
y corrió aceptación secuencial; Mongo permaneció vivo sin OOM. Un primer Linux
carecía de Node, caches escribibles y PID 1 que recolectara descendientes; se
corrigió el entorno, no se ocultaron tests. Las cuatro regresiones propias de ese
primer gate (fixture OAuth, dos expectativas de scopes y verificador de rollback)
se corrigieron y volvieron a incluirse en la suite completa verde.
El diagnóstico inicial de macOS encontró 12 fallos de wrappers que invocan
`/bin/bash`. Se reprodujeron los mismos 12 contra una exportación inmutable del
commit inicial `84e5df2a46bfc5d8bcbf2f61c6f7a54653f9c9b6` (**148 passed, 12 failed**
en los dos archivos afectados), sin cambiar scripts ajenos. En un contenedor
Linux Python 3.11 preexistente, ambos archivos dieron **160 passed, 3.66 s**.

Reproducción de tests protegidos (con rs0 desechable ya verificado):

```sh
# URI privada de desarrollo/test, explícitamente loopback; nunca producción.
unset MONGO_URI
export ZELER_RS0_TEST_URI='<URI del rs0 local desechable>'
uv run pytest tests/integration/test_stock_time_forward_acquisition_rs0.py \
  tests/integration/test_stock_time_forward_execution_rs0.py \
  tests/integration/test_stock_time_forward_rollback_rs0.py
```

No se resume el resultado como «todos los tests sin skips»: permanece un skip de
contrato Caddy que no tiene claves requeridas.

### Matriz T-01–T-22: dónde se comprueba y qué queda fuera

Pruebas nuevas: [coordinador](../../modules/sheets/tests/test_history_onboarding.py),
[fuentes](../../modules/sheets/tests/test_onboarding_sources.py),
[parciales](../../modules/sheets/tests/test_partial_history.py),
[autoridad DEVOLUCIONES](../../modules/sheets/tests/test_devoluciones_onboarding.py),
[integración DEVOLUCIONES](../../tests/integration/test_devoluciones_onboarding.py),
[capacidad](../../modules/sheets/tests/test_history_onboarding_capacity.py) e
[índices](../../modules/sheets/tests/test_onboarding_indexes.py).

Regresiones reutilizadas: [órdenes](../../modules/sheets/tests/test_history_orders.py),
[preguntas](../../modules/sheets/tests/test_history_questions.py),
[recovery](../../modules/sheets/tests/test_formula_recovery.py) y
[proyección concurrente](../../modules/sheets/tests/test_formula_recovery_history_projection.py).

| Caso | Evidencia local | Límite / pendiente |
| --- | --- | --- |
| T-01 | Coordinador: OAuth/relink admite plan; año automático con workers reales y fuente simulada. | No prueba OAuth remoto ni despliegue del consumidor. |
| T-02 | Coordinador/reclamos: cutoff, progreso, junio y rango nuevo preservados. | Baseline real del vendedor sigue pendiente. |
| T-03 | Mongo concurrente: carrera de admisión, lease único y separación de workers legacy/policy. | El worker antiguo sin esa frontera no es rollback compatible. |
| T-04 | Calendario bisiesto, fin de mes, UTC y rangos ordinarios. | No se realizó revisión visual de zona en UI nativa. |
| T-05 | Recovery histórico: páginas, total cambiante, vacíos, subdivisión; Full scroll repetido/expirado. | Proveedor simulado; volumen anual remoto no acreditado. |
| T-06 | API normal autenticada: 9,999 líneas canónicas útiles + un pendiente, aviso/NA/cobertura explícita; máximo tres intentos. | Opt-in solo tabla ORDENES; rango exacto/totales afectados siguen no disponibles. |
| T-07 | Dependencias/estado agregado no dan disponibilidad si solo hay bloqueos o enumeración desconocida. | No se inventa porcentaje/denominador. |
| T-08 | Recovery existente: listado con detalle 404 y pregunta local omitida revalidada. | Sin prueba de respuestas remotas actuales. |
| T-09 | Cancelada conocida ausente de search, actualización y conservación. | Las desconocidas no enumerables siguen siendo un límite explícito. |
| T-10 | Packs deduplicados, dependencias pendientes y costos ausentes como NA. | No hubo escenario remoto integral orden faltante + envío. |
| T-11 | Pregunta sin respuesta válida permanece pendiente; otra respuesta válida se conserva. | No se fabrica KPI. |
| T-12 | Reinicio por lease/checkpoint, hidratación interrumpida, scroll expirado y CAS tras respuesta tardía. | No se mató el proceso OS exactamente en todas las fases. |
| T-13 | Dos cuentas, checkpoints scoped y hechos recientes protegidos frente a adquisición vieja/ajena. | Sin cuentas productivas. |
| T-14 | Revocación/pausa, 429/503, backoff, límites y relink preservando avance. | Renovación OAuth remota no ejecutada. |
| T-15 | Full: tipos, scroll, permisos/empty no equivalen a no aplica; lector RETIROS permanece cerrado. | **Mapeo auténtico obligatorio pendiente (H-13).** |
| T-16 | Workers reales + Mongo: orden paid → cancelled; preguntas/claims incrementales; mensaje nuevo en orden antigua sin cambios mediante cursor periódico real. | Solo packs conocidos, latencia/volumen remotos no acreditados. |
| T-17 | Certificados/rangos independientes, gap entre períodos rechazado, renovación más allá de dos vigencias. | No se probó un nuevo escenario dedicado de fórmula con certificado expirado; se conserva fail-closed existente. |
| T-18 | Endpoint normal de fórmula con opt-in y 9,999 filas, aviso visible, meta.coverage y default/agregados cerrados; período sano conservado. | Add-on no solicita opt-in; API no prueba consumo nativo. |
| T-19 | Importadores GET/read-only, `mark_as_read=false`, timestamps de lectura conservados. | No operaciones reales de comunicación o tokens. |
| T-20 | Dump/restauración sintética aislada y hashes; origen posterior intacto. | Backup concurrente productivo y rollback de imágenes pendientes. |
| T-21 | Política persistida, cuotas/rangos, autoridad diaria y scope opcional en claim real; otra cuenta/plan intacta. | Aplicación/activación productiva requiere autorización. |
| T-22 | Nueva prueba: coordinador real compartido, preguntas/mensajes no vacíos y 12 certificados×1,000 miembros renovados60min; volumen anterior conservado. | Representativa local; no benchmark anual remoto de todas las fuentes/HTTP/broker/RSS. |

Focused final del escritor: **171 passed, 1 deselected, 20.96 s**. El deselect fue
solo la prueba volumétrica de 10,000 órdenes, ya ejecutada por separado en
**50.92 s** y que vuelve a incluirse en la suite completa final. No se interpreta
esta matriz como 22 pruebas de aceptación productiva aprobadas.

## Artefactos y propietarios de runtime

| Área | Archivos relevantes | Propietario operativo |
| --- | --- | --- |
| Intención OAuth | `gateway/src/zeler_gateway/oauth/events.py`, `core/src/zeler_platform_core/history_onboarding.py` | Gateway. |
| Coordinación y fuentes | `modules/sheets/src/zeler_sheets/history_onboarding.py`, `onboarding_sources.py`, `partial_history.py`, `consumer.py` | Sheets worker. |
| Exactitud, convivencia y renovación | `devoluciones_runner.py`, `formulas/recovery.py`, `formulas/recovery_worker.py`, `pilot_history_backfill.py` | Sheets worker; lectura compatible en Sheets API. |
| Progreso, tabla parcial y registro | `modules/sheets/src/zeler_sheets/api.py`, `formulas/handlers_orders_questions.py`, manifest y seed de registro | Sheets API. |
| Índices | `infra/mongo/indexes/sheets_history_receipts.json`, `sheets_history_backfill_plans.json`, `sheets_history_pending_records.json`, `sheets_full_operations.json` | Aplicación separadamente autorizada desde VM/VPC. |
| Verificador de rollback | `infra/deploy/sheets_rollback.py` | Herramienta operativa; actualizarla en el destino solo con autorización. |

El plan, jobs de recovery y metadatos nuevos usan colecciones internas sin
validador core existente; las guardas de runtime no son un validador Mongo nuevo.
Se reutilizan los esquemas de adquisiciones, recibos, rangos y certificados exactos.
La exportación debe comprobarse sin afirmar que certifica colecciones dinámicas.

El registro de Sheets necesita scopes de lectura para packs de mensajes y
búsqueda de operaciones Full. **Seed y manifest deben coincidir**: aplicar solo
el seed no basta si el registro al iniciar la API vuelve a retirar los permisos.
Verificar el fingerprint completo y clientes de descubrimiento/detalle por
separado. No se amplían scopes de comunicación ni se conceden permisos reales
por editar estos archivos localmente.

El contrato canónico queda en **15 scopes**; se actualiza también su verificador
de rollback, no solo los fixtures. Fingerprint de registro completo:
`bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
Una imagen anterior de 13 scopes no acredita ese contrato. Antes de activar
permisos/policy, conservar una imagen de rollback recuperable que respete los
15 scopes y la frontera `policy_authority`; un tag o fingerprint antiguo no basta.

No hubo cambios al ejecutor bootstrap ni evidencia que obligue a reconstruir su
imagen por una modificación de comportamiento; revisar dependencias finales en
la propuesta exacta, sin desplegar servicios ajenos por copiar el mismo workspace.

## Qué falta antes de producción

[Propuesta preparada](zelerdata-historico-publicacion-piloto-propuesta.md): separa
publicación, probe Full, backup/restore, builds, despliegue y piloto; una cuenta,
90 minutos/día UTC, máximos 2,000 GET iniciales + 500 de mantenimiento (Full aparte,
≤10 GET). Son límites propuestos, **no autorización ni adquisición ejecutada**.
El SHA publicado se registra solo tras verificar el envío; no se fija un digest
sin build real. RETIROS Full permanece pendiente sin bloquear las otras fuentes.
La [adaptación mínima del complemento](zelerdata-ordenes-parciales-complemento-propuesta.md)
es documental: opt-in final opcional, aviso visible y default exacto sin cambios;
**no implementada ni disponible en Sheets**.

1. Cerrar el recurso/mapeo auténtico de RETIROS Full o acordar explícitamente una
   adaptación compatible; no presentar el pendiente como implementación completa.
2. Commit/push propios autorizados: comprobar su resultado en el recibo y usar
   el commit fuente exacto publicado en `main`; el checkout local no es autoridad
   de build. Builds y despliegue conservan autorización separada.
3. Preparar baseline sanitizado por fuente, junio/otros períodos sanos, salud y
   capacidad; identificar imágenes anteriores inmutables y rollback compatible.
4. Autorizar backup consistente desde VM/VPC y restauración aislada. Proteger y
   delimitar el respaldo, preservar OAuth/hechos posteriores y no restaurar toda
   la base a ciegas. El fixture local no sustituye este paso.
5. Autorizar cambios mínimos de registro/índices requeridos, builds separados y
   despliegue acotado. Una autorización no implica la otra. Activar el flag solo
   después de comprobar consumidores, permisos y compatibilidad.
6. Autorizar piloto con vendedor, fuentes/fechas, máximo de consultas, concurrencia,
   pausas y criterios de parada concretos. OAuth/relink auténtico, sin force,
   tokens copiados ni limpieza para simular una cuenta vacía.
7. Verificar digest en ejecución, readiness, progreso persistido y lectores por
   fuente. Observar capacidad/salud después del asentamiento y medir carga anual
   representativa con el pacing real, no extrapolar los tiempos sintéticos.
8. Autorizar celdas/rangos de Sheets y verificar fórmulas nativas. Observar dos
   ciclos con cambios reales posteriores al corte; ciclos vacíos y renovación
   local de pruebas no demuestran procesamiento incremental remoto.

Seguir [runbook](../deploy.md) y la propuesta de piloto de la especificación:
destino documentado `zeler-platform-dev`, `platform-vm`, `us-central1-a`, sujeto a
confirmación actual. No hubo consulta local de Mongo productivo ni acceso al VM.

## Git, conservación y reversibilidad

En el cierre local previo a la autorización, la implementación permanecía sin
commit; la publicación posterior se documenta en el recibo. Durante el trabajo,
otro actor publicó
`124fd236fea600ead8c1436560a22b1909d7c3c8` (diagnóstico OAuth), avanzando desde el
HEAD inicial anterior. No pertenece a esta implementación; se preservó su estado
y no se hizo stash, reset, cambio de rama ni worktree.

La retirada local debe limitarse a archivos/hunks propios y sus tests/documentación,
nunca usar `git reset --hard` sobre el checkout compartido. En runtime, desactivar
el poller detiene admisión/ejecución futura, no borra planes, hechos ni certificados.
Un rollback de imágenes exige compatibilidad de scopes y datos nuevos antes de
arrancar writers antiguos. Un worker anterior que desconozca `policy_authority`
no es rollback compatible con jobs onboarding pendientes: detener/drenar esas
unidades o conservar una imagen que respete la misma frontera de claim; no borrar
los jobs ni su evidencia. No hay aprobación/recibo de review fabricado:
entrega `disabled/unmanaged` conforme a política opt-in.
