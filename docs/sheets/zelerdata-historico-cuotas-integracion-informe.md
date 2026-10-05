# CUOTAS-integración: intención durable de eventos y replay

**ENTREGADO; NO SIGO MODIFICANDO. Evidencia exclusivamente local.** Interfaz
core y router congelados por el coordinador antes de pruebas. Este informe no
modifica las entregas originales de CUOTAS o AMQP ni acredita aceptación productiva.

Base: `main`, `7cbd1629ab1fda657d88f5ecf20a798bd6f3ac34`.
Ownership: lista cerrada de siete paths al final del
[paralelo](zelerdata-historico-paralelo.md). Ningún otro archivo puede editarlo
este writer. Sin subagentes, Git mutante, builds, producción, dependencias,
configuración ni cambios a core/gateway router.

## Dependencias y alcance

El coordinador fija `history_work_intent`: normalización de documento durable,
resolución de intención seller/event/claim/job, `receipt(path)` y `assert_live`.
`EventClaimGate` real expone identidad de owner scoped; constructor legacy no
autoriza el piloto. El gateway valida la intención por intento mediante CAS
transaccional de claim/job/nonce, sin renovar leases. El writer no implementa
esos contratos compartidos ni prueba código mientras el coordinador los cambia.

Los tests se prepararon sin ejecutar hasta aviso de core congelado. Luego se
observaron RED y GREEN locales para:

- Cargo mantenimiento + receipt nonce en una operación de plan, crédito no
  fungible h1, conservación de consumos previos y headers por intento.
- Fallo físico/retry caller, último crédito concurrente, pérdida de lease y
  deadline cruzado durante pacing.
- Gateway local por entrega concurrente, identidad del claim real, duplicados y
  rechazo de constructor legacy o intención incompleta.
- Replay con topics almacenados realmente (`orders_v2` y `post_purchase`),
  normalización de claim y job token/fence.
- WAIT local con publicación mandatory confirmada antes ACK, NACK ante fallo y
  conservación de attempt/checkpoints de mensajes/jobs.

## Preservación

Registro14 sin Full, seis routing keys, fuentes existentes y presupuesto original
permanecen intactos. No cuota nueva, reset, refund, reprepare, extensión de plazos,
reclasificación de items/catalog como sexta fuente ni cambio de índices/schemas.
Solo cuando existe `plan.execution_id` se integra el contexto de piloto; otras
cuentas conservan el flujo ordinario. Full permanece excluido.

## Implementación y atribución

Solo el plan con `execution_id` presente entra al contexto de piloto; si falta,
cuentas y doubles ordinarios conservan el flujo previo. Una identidad corrupta,
una intención sin origen verificable o un constructor legacy sin claim real
quedan WAIT, no adquieren autoridad por header. Se conserva la clave publicada
`topic:normalized_resource:event_id`; no se cambian markers de idempotencia.
Replay pasa `_id/attempt_token/fence` del job real, sin convertir el `_id` a texto
para consultar. La API actual crea IDs string (`api.py:273`); ObjectId legacy sin
soporte del contrato core queda WAIT y conserva el registro, no se migra aquí.

| Origen comprobado por core | Fuente/fase | Integración |
| --- | --- | --- |
| Evento orders_v2 u orders.updated | orders / maintenance | Gateway local de entrega. |
| Pregunta | questions / maintenance | Mismo cargo y confirmación física. |
| Envío | shipments / maintenance | Comparte límite mantenimiento. |
| Pack de mensajes con recurso/identidad válidos | messages / maintenance | Solo flujo existente o replay; no routing nuevo. |
| post_purchase con acciones válidas | claims_returns / maintenance | Claim, returns y su dependencia `/orders/{id}` permanecen claims_returns. |
| Items, catálogo, Full o normalización desconocida | Sin fuente inventada | WAIT antes de adquirir; replay conserva job/evento. |

`PlanBudgetGateway(work_intent=...)` fija mantenimiento, verifica ownership antes
del cargo y añade en **el mismo CAS** `execution_work.<nonce>` con receipt,
credit1/sent0/path. Incrementa únicamente los contadores existentes de
mantenimiento/fuente/ejecución; **no** crea crédito agregado `execution_charged`
que un h1 histórico pudiera consumir. Cada retry caller usa nonce nuevo; errores
y vencimiento después del cargo lo conservan sin refund. Un lock exclusivamente
work evita cruzar nonce/headers si dos llamadas anidadas comparten un wrapper;
el handler no muta su cliente compartido.

Work exige controles execution hasta/día/cap/consumo, counters de mantenimiento
enteros no negativos y mapa `execution_work` ausente u object, antes del cargo y
en CAS. **No rollover, reparación ni reset del plan piloto.** La rama histórica
`work_intent=None` conserva su política diaria y crédito h1 previos.

Después del cargo se respeta pacing y recheck síncrono de ventana sin await Mongo
entre pacing/RPC. `fetch_resource_once` es obligatorio para work; cliente real
marca retry disabled y requiere metadata de un intento. El coordinador es dueño
de la transacción tardía gateway, del contador sent y sus pruebas Mongo: los
fixtures del writer no prueban atomicidad ni recepción de MercadoLibre.

`HistoryWorkWaitError` del resolver/owner se convierte a `HistoryPolicyWaitError`.
Consumer conserva death count y exige publicación mandatory confirmada antes ACK;
si falla, NACK requeue mantiene original. Sync deja pending/backoff mediante
token/fence, conserva requested_at/cursor/attempt y no marca failed por ese WAIT.
Un intento real fallido mantiene su tratamiento previo, no se etiqueta como gratuito.

## RED, GREEN y recursos

Turno focused serial confirmado por el coordinador tras congelación core y luego
router; se pausó durante su ajuste de key real y guard de shapes. Sin suite
general, Mongo, broker ni proveedor. Entorno hijo whitelisted sin variables de
credenciales/targets heredadas, `uv run --offline --no-sync`, `.venv` intacto,
`PYTHONDONTWRITEBYTECODE=1`, pytest sin cacheprovider y tmp/caches propios en
`$HOME/.codex/cache/zelerdata-paralelo-20261005/cuotas-integracion/`. Los finales
también prohíben `socket.connect/connect_ex` para todo el proceso.

| Control | Resultado / exit | Evidencia privada |
| --- | --- | --- |
| RED inicial de integración | 13 FAILED, exit1; colección correcta, antes de implementar el flujo. | red.log |
| RED WAIT operativo con routing anterior | 5 FAILED, exit1; original enviaba DLQ / job failed. | red-wait.log |
| GREEN inicial | 84 PASS, exit0. | green.log |
| RED counters/rollover | 8 FAILED y 4 PASS de controles obligatorios, exit1. | red-controls.log |
| GREEN ampliado | 98 PASS, exit0. | green-controls.xml |
| RED unknown replay / execution ID malformed | 4 FAILED / 9 PASS, exit1. | red-drift.xml |
| RED mapa execution_work malformed | 3 FAILED / 9 PASS, exit1. | red-workshape.xml |
| FINAL cinco archivos focused | **163 PASS / 0 SKIP**, pytest0.661s, exit0; 1 test realMongo deselected expresamente. | final-focused.xml / .log |
| FINAL pacing separado | **6 PASS / 10 deselected**, pytest0.396s, exit0. | final-pacing.xml / .log |
| Ruff y formato seis paths Python asignados | PASS / PASS, exit0. | ruff.log / format.log |
| Mypy seis paths Python asignados | PASS, exit0. No mypy completo del repo. | mypy.log |
| Git diff --check de paths propios existentes | PASS, exit0; lectura, no staging. | Recibo final privado. |

El primer mypy encontró cinco errores **solo del nuevo fixture** por nombres de
argumentos del protocolo Claims y tipo inferido del diccionario; corregidos y
control repetido. Los lotes intermedios no se suman al final. No se cuentan tests
deselectados como cobertura: Mongo/atomicidad y los diez casos restantes de
execution_controls corresponden a la integración final del coordinador.

Comandos finales reproducibles solo cuando el coordinador reserve turno:

```bash
Q="$HOME/.codex/cache/zelerdata-paralelo-20261005/cuotas-integracion"
UV_BIN=$(command -v uv)
env -i PATH="$PATH" HOME="$HOME" UV_CACHE_DIR="$Q/uv" PYTHONDONTWRITEBYTECODE=1 \
  "$UV_BIN" run --offline --no-sync python -c 'import socket,sys,pytest; denied=lambda *a,**kw: (_ for _ in ()).throw(AssertionError("CUOTAS integration socket forbidden")); socket.socket.connect=denied; socket.socket.connect_ex=denied; sys.exit(pytest.main(sys.argv[1:]))' \
  -q -p no:cacheprovider --basetemp="$Q/final-focused-tmp3" --junitxml="$Q/final-focused.xml" \
  modules/sheets/tests/test_history_work_intent.py \
  gateway/tests/test_pilot_get_budget_consumers.py \
  modules/sheets/tests/test_consumer_error_handling.py \
  modules/sheets/tests/test_consumer_phase6.py \
  modules/sheets/tests/test_sync_jobs_processor.py -k 'not real_mongo'
```

Pacing usa el mismo wrapper con `modules/sheets/tests/test_history_execution_controls.py`
y `-k 'concurrent_policy_charges or reserved_credit'`. Ruff/check y format/check
usan `--no-cache`; mypy usa `--cache-dir "$Q/mypy"`. Los seis paths son los seis
Python de ownership, aunque execution_controls permaneció intacto.

## Archivos y preservación

Se cambiaron seis paths propios: tres fuentes, nuevo test, test consumer recibido
de AMQP e informe. No se tocó el séptimo, execution_controls. Las pruebas AMQP
existentes se preservaron; el diff contra HEAD contiene también su delta previo,
no se atribuye íntegramente a esta integración.

| Archivo | SHA256 final |
| --- | --- |
| modules/sheets/src/zeler_sheets/history_onboarding.py | db358ff6648be0fca6f314937d85f9f839bfa9a9149b3261a83654a072fd90a7 |
| modules/sheets/src/zeler_sheets/consumer.py | 1bc0813c12210950ad3f10d7a02573c4d9b0f6cc6321e34c4a71ab634d3160f9 |
| modules/sheets/src/zeler_sheets/sync_jobs_processor.py | 929a0f2967ea674185d57416741fc68b85bb081ad68f1128c19a2e574a582573 |
| modules/sheets/tests/test_history_work_intent.py | 5923bdd8a0999ca30f905cc90898a1428ddeb0113818b956861cb1b736669f56 |
| gateway/tests/test_pilot_get_budget_consumers.py | 708de4107f5e8d6fc12ebd9b18284a3231a7e552f6051dc9645910e8f57447a6 |
| modules/sheets/tests/test_history_execution_controls.py — intacto | 8cf92b1e79cc2cdc3a74aa232b193cfbf4bca7b69afc7cfc46f990207e60f0c6 |
| Este informe | SHA final en cuotas-integracion-final-receipt.json; no autorreferencia circular. |

Cambios del coordinador en core/router/proxyfixture/documentos y entregas previas
AMQP/CUOTAS permanecieron ajenos y preservados. Solo lecturas Git status/diff;
sin staging/commit/push, branch/worktree/stash/reset, installs/dependencias,
Docker/Cloud Builds, producción o cambios a otros repos.

## Imágenes y gates pendientes

- **Sheets worker afectado**: `consumer.run()` crea handler/replay; los nuevos
  kwargs solo se usan cuando existe intención work del piloto. PlanBudgetGateway
  y WAIT son comportamiento de ese worker.
- **Gateway afectado por integración del coordinador**, no por edición del writer.
- **API no requiere rebuild por este delta**: api.py no construye ni llama a
  SheetsEventHandler/SyncJobsProcessor. DevolucionesRunner crea PlanBudgetGateway
  sin work_intent y conserva esa rama; agregar imports core/reader no basta para
  declarar una imagen afectada. Revalidar este mapa sobre el delta final completo.
- Mantener fuentes/registro14/six-routing/HOLD y presupuestos originales
  initial2000, mantenimiento500/≤300 fuente, ejecución2500/90min/mismoUTC. Son
  techos, no saldo consultado. No operador prepare/activate ni cuotas nuevas.
- Mensajes con path legacy no pack válido, ObjectId no soportado y fuentes
  desconocidas quedan WAIT sin remapear. No añadir ruta, permiso o sexta fuente.
- Cuatro gates generales, Mongo real/CAS tardío, digest/runtime/topología/entrega,
  OAuth y aceptación anual/parcialAPI/nativa/dos incrementales reales siguen a
  cargo del coordinador; estos mocks no los acreditan.
- AMQP-REPEAT-1 consumida FAIL/STOP por el coordinador: este writer no la repite
  ni cambia endpoint/credenciales/topología; producción continúa bloqueada.

**ENTREGADO; NO SIGO MODIFICANDO.** Ownership de los siete paths devuelto al
coordinador. Cualquier reapertura requiere encargo explícito y nueva evidencia.

## Key Learnings:

1. El crédito por intento de work debe quedar separado del h1 agregado para no
   permitir que un request histórico consuma una reserva de evento diferente.
2. Backpressure de política local necesita handling propio; no debe convertirse
   en DLQ ni fallo terminal del job.
