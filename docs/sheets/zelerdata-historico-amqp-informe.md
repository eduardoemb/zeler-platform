# ZelerData AMQP — lector instrumentado y protecciones locales

**Estado: ENTREGA LOCAL COMPLETA; producción NO ejecutada.** Fecha: 2026-10-05 UTC.
Base HEAD leída: `7cbd1629ab1fda657d88f5ecf20a798bd6f3ac34`.
Asignación: [paralelo §2.2, §3.2 y §4](zelerdata-historico-paralelo.md).
Baseline: [handoff §§5–8](zelerdata-historico-handoff.md).

Turno exclusivo AMQP concedido por el usuario y §4 después de congelación CUOTAS.
Lector implementado tras RED observado; **179 pruebas locales PASS**, ruff,
formato y mypy enfocados PASS. No cambios ejecutables en consumidores/scheduler.
La topología productiva, el origen del HTTP404 histórico, publicación confirmada
y tiempos efectivos siguen sin acreditarse; no se habilita rollout ni piloto.

## Quick path para el coordinador

1. Revisar selección/límites y hashes de herramienta/fixtures de este informe.
2. Integrar con CUOTAS y ejecutar calidad general solo tras ambas congelaciones.
3. Si procede bajo el ledger, ejecutar la única repetición GET-only autorizada.
   Primer error STOP, sin otra URL/credencial/retry; registrar recibo sanitizado.
4. No confundir lectura de topología o estos mocks con entrega real de mensajes.

## 1. Paths propios y preservación

| Path exclusivo AMQP | Estado |
| --- | --- |
| `infra/operations/zelerdata_amqp_delay_readonly.py` | Nuevo: lector GET-only implementado y probado offline. |
| `tests/test_zelerdata_amqp_delay_readonly.py` | Nuevo: 113 casos offline PASS; sockets prohibidos. |
| `modules/sheets/src/zeler_sheets/consumer.py` | Solo leído; comportamiento preservado. |
| `modules/sheets/src/zeler_sheets/sync_jobs_processor.py` | Solo leído; comportamiento preservado. |
| `gateway/tests/test_pilot_get_budget_consumers.py` | 66 casos PASS: anteriores y caracterizaciones nuevas; sockets prohibidos. |
| `docs/sheets/zelerdata-historico-amqp-informe.md` | Informe final de evidencia local, límites y pendientes productivos. |

Cambios ajenos observados y preservados: documento de asignación del coordinador,
`gateway/src/zeler_gateway/proxy/router.py`, `gateway/tests/test_pilot_get_budget.py`,
`gateway/tests/test_pilot_get_budget_allocation.py` e informe CUOTAS. No se tomaron
como propios ni se editaron. No subagentes, Git mutante, installs/sync, cambios
globales de entorno o ediciones a archivos compartidos.

## 2. Originales preservados

Directorio privado: `$HOME/Library/Caches/zeler-operations/rescue-corrected-20261004T011204Z`.
Se leyeron fuentes y se calcularon hashes; no se ejecutó ni sobrescribió el helper.
No se volcaron logs crudos ni env/credenciales. Hashes observados:

| Archivo relativo al directorio privado | SHA256 |
| --- | --- |
| `amqp-delay-readonly-controls-20261005/amqp_delay_readonly.py` | `321273da312473722a2baf73dd027b2957f6c5650d19f64f14a19155ed5fe377` |
| `amqp-delay-readonly-controls-20261005/test_amqp_delay_readonly.py` | `0c97de0649d6993b5706846152058f390d0997a8ecf24e052523fbfd93c3e235` |
| `pilot-amqp-delay-readonly-20261005T175704Z-start.json` | `143f9b49de0e5b91fcc7cd53d05c9d2fefbba23516ea2d394b6f91f343f1cb44` |
| `pilot-amqp-delay-readonly-20261005T175704Z-stdout.log` | `49e3c2bd94b21cca2b6c1e4f0e1c5e765b64eecce09a415c200a4cf3c4e70f8b` |
| `pilot-amqp-delay-readonly-20261005T175704Z-stderr.log` | `5444cd70365e9587f6e2d566306f73340b6fd59461883752c13d03c35bc9bafb` |
| `pilot-amqp-delay-readonly-20261005T175704Z-end.json` | `b075f796452ee6f6c2e337682be471ec3a8f0794619ae67adfc284f779bf4b9e` |

El HTTP404 histórico no permite identificar cola ausente, autenticación incorrecta,
ruta/vhost equivocado ni ninguna causa concreta. No se reescribe su consumo:
número de GET desconocido, máximo programado23, primer error STOP.

## 3. Herramienta implementada y límites

- Default sin ejecución; `--inspect` explícito. Sin constructor AMQP ni imports
  capaces de abrir una conexión al broker. Credenciales solo en memoria del
  proceso autorizado, nunca en argumentos, reportes ni representaciones.
- GET Management secuenciales: diez colas, metadata+bindings, tres exchanges,
  máximo23, sin discovery, retries, redirects, exports, PUT/POST/DELETE ni probes.
- Las diez colas y tres exchanges son exactamente los de paralelo §3.2.
- Construcción de base Management con `/api` una sola vez; preservar prefijo
  explícito; decodificar vhost AMQP una vez y codificarlo como segmento una vez.
  No adivinar otra URL ni otras credenciales tras un fallo.
- Recibo por request: operación GET, etapa, etiqueta de recurso canónico,
  plantilla de ruta con `{vhost}` (sin host/vhost real), secuencia, estado HTTP
  o error fijo, bytes observados/truncación y tiempo. Totales iniciados,
  respuestas recibidas y cuerpos completados separados; STOP en primer error.
- Límites no ampliables:4s/request de pared,60s lectura y64KiB/body. Cleanup
  máximo5s, conserva error anterior y degrada éxito si falla; lectura+cleanup
  quedan hasta65s en transporte cooperativo. El coordinador impone300s para la
  operación completa, incluido staging/arranque/limpieza fuera del lector.
- No body crudo, URL completa, headers auth, error libre del proveedor o traceback.
  Shape/paginación incompleta no constituye topología verificada.

Fixtures probadas: bases raíz y `/api`/prefijo; vhost raíz, espacios/slash,
porcentaje literal y Unicode; errores401/403/404/429/5xx y redirects en distintas
etapas; timeout/transporte; JSON inválido y >64KiB, stream sin Content-Length;
paginación/identidad incorrecta; Content-Length inconsistente; count/deadline/
cleanup agotados, filtros de logs de HTTPX/HTTPCore restaurados y sanitización.
El lector solicita Accept-Encoding identity y rechaza compresión antes de leer.

**Counts:** requests_started cuenta el inicio de la operación HTTP (no garantiza
que un paquete llegue al servidor); responses_received cuenta headers recibidos;
requests_completed cuenta cuerpos HTTP200 leídos completos dentro del límite,
no validez JSON/topológica. Un HTTP404 recibido queda started1/received1/completed0
porque no se descarga su body. En error de JSON/shape puede haber completed1.
bytes_received registra bytes realmente observados, nunca longitud declarada.
truncated distingue cortes por size/mismatch; no revela el body. Cada error
queda en su endpoint: bindings se validan al leerlos, no en un exchange posterior.

## 4. Evidencia separada

| Plano | Qué corresponde comprobar | Estado actual |
| --- | --- | --- |
| Lectura fuente/configuración | Durable/exclusive/autodelete; TTL de delay30000ms y buckets1000/5000/30000/120000/600000ms; DLX y routing key; policies efectivas/operator; bindings topic/direct/default; consumers y contadores. | Fuente revisada y fixtures PASS; sin lectura actual de broker. |
| Prueba local | WAIT conserva body/identidad/attempt0–4; timedelta genera wire ms para eventos; claims usa TTL de cola sin TTL por mensaje; barrera demuestra espera de confirmación antes de ACK; NACK requeue ante False/None/excepción; scheduler conserva progreso/counters y aplica fence/backoff. | 66 casos PASS con cliente/consumer/scheduler reales y transporte simulado. |
| Prueba activa | Confirmación real del broker, enrutamiento/entrega, expiración/dead-lettering efectivo, orden y tiempos medidos, reacción a devolución/fallo real. | NO demostrada ni autorizada al especialista. GET-only no la demuestra. |

La cola de eventos delay tiene TTL30000ms esperado: puede limitar una expiración
por mensaje mayor. Los buckets claims redondean hacia arriba y se limitan a10min;
no inferir tiempos precisos de entrega. El cliente real MeliGatewayClient
limita Retry-After a1–30s (fuente core revisada), de modo que WAIT recibido por
ese cliente elige hasta30s; no se cambió ese contrato ni se prometen waits mayores.
La lectura de bindings no prueba recepción.
Una policy no vacía o metadata faltante exige revisión/STOP, nunca reparación
automática. `x-queue-type=classic` benigno no justifica mutación.

## 5. TDD y verificación enfocada

Cache aislado: `$HOME/.codex/cache/zelerdata-paralelo-20261005/amqp` (`AMQP`).
Entorno existente con `uv run --offline --no-sync`, bytecode desactivado,
pytest sin cacheprovider y basetemp propio. Antes de pytest se quitaron solo en
el proceso hijo MONGO_URI/RABBITMQ_URL/RABBITMQ_MANAGEMENT_URL; nunca se imprimieron.
Las dos suites bloquean socket.connect/connect_ex; solo MockTransport, AsyncMock
y dobles en memoria. Sin Mongo real, puertos externos, installs, suite general,
review mode, builds o producción.

| Recibo/log propio | Resultado observado | Motivo |
| --- | --- | --- |
| `reader-red.log` | exit2, 1 error de collection, 0.09s | ModuleNotFoundError antes de implementar lector. |
| `green1.log` | exit1, 21 failed/153 passed, 1.02s | Un código de metadata incompleta incorrecto y20 expectativas de delay ignoraban el clamp1–30s del cliente. |
| `reader-safety-red.log` | exit1, 3 failed/108 deselected, 0.08s | Logs DEBUG revelaban vhost; binding se diagnosticaba en etapa posterior; faltaba rechazo de compresión. |
| `green2.log` | exit0, 177 passed, 1.03s | Instrumentación y expectativas corregidas; consumer/core intactos. |
| `reader-length-red.log` | exit1, 1 failed/1 passed/111 deselected, 0.07s | Content-Length inconsistente no detenía su endpoint. |
| `green3.log` | exit0, 179 passed, 0.75s | Lector113 + consumidores66, sin skips/deselections. |
| `ruff-first.log` / primer format-check | exit1 | Imports/line length y marcador sintético; corregidos solo en archivos propios. |
| `mypy-first.log` | exit1, 4 errores locales | Factory fixture retornaba Any; tipada Callable[..., Response]. |
| `final-pytest.log` | exit0, 179 passed/0 skips, 0.77s | Código final; sin deselections. |
| `final-ruff.log` / `final-format.log` / `final-mypy.log` | exit0 los tres; 3 archivos | Ruff PASS, 3 ya formateados; mypy sin issues. |

Comandos base reales (sufijos de basetemp/log por ronda en tabla):

```bash
AMQP="$HOME/.codex/cache/zelerdata-paralelo-20261005/amqp"
export PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR="$AMQP/uv"
env -u MONGO_URI -u RABBITMQ_URL -u RABBITMQ_MANAGEMENT_URL \
  uv run --offline --no-sync pytest -p no:cacheprovider \
  --basetemp="$AMQP/green3-tmp" \
  tests/test_zelerdata_amqp_delay_readonly.py \
  gateway/tests/test_pilot_get_budget_consumers.py
uv run --offline --no-sync ruff check --no-cache \
  infra/operations/zelerdata_amqp_delay_readonly.py \
  tests/test_zelerdata_amqp_delay_readonly.py gateway/tests/test_pilot_get_budget_consumers.py
uv run --offline --no-sync ruff format --no-cache --check \
  infra/operations/zelerdata_amqp_delay_readonly.py \
  tests/test_zelerdata_amqp_delay_readonly.py gateway/tests/test_pilot_get_budget_consumers.py
uv run --offline --no-sync mypy --cache-dir="$AMQP/mypy" \
  infra/operations/zelerdata_amqp_delay_readonly.py \
  tests/test_zelerdata_amqp_delay_readonly.py gateway/tests/test_pilot_get_budget_consumers.py
```

### Ejecución futura propuesta — NO ejecutada aquí

Solo coordinador, desde VM/VPC `platform-vm`, `zeler-platform-dev/us-central1-a`,
con identidad del contenedor trabajador aprobado y fuente congelada/verificada.
El siguiente comando usa variables **a resolver antes de operar**, no selecciona
un contenedor ni copia credenciales por sí mismo:

```bash
# En VM; AUTHORIZED_WORKER_CONTAINER identificado por el coordinador.
# FROZEN_READER contiene exactamente la fuente cuyo SHA figura en §8.
docker exec -i "$AUTHORIZED_WORKER_CONTAINER" /app/.venv/bin/python - --inspect \
  < "$FROZEN_READER" > "$NEW_SANITIZED_RECEIPT"
```

No se presupone que el módulo nuevo esté instalado en la imagen antigua; stdin
usa Python3.11 y entorno legítimo del proceso dentro del runtime. No sobrescribir
logs previos. Controles internos23/4s/60s/64KiB/cleanup5s; supervisor del coordinador
≤300s totales incluyendo transferencia/staging/cleanup, sin huérfanos ni reintento.
Si no puede verificar supervisor/target/dependencias/toolSHA/ledger, no ejecutar.
La autorización de repetición la posee solo el coordinador: cero GET productivos
nuevos consumidos por AMQP. Ante error, guardar endpoint/counts/tiempo y STOP;
no corregir vhost, credenciales, policies o topology para probar otra vez.

## 6. Propuestas reservadas y efectos sobre imágenes

En `core/src/zeler_platform_core/runtime/retry_delay.py`, el publisher legacy
usa `expiration=delay_ms` numérico. El `aio_pika` instalado convierte números
desde segundos a milisegundos; timedelta usa su duración. El WAIT controlado
de `consumer.py` ya usa timedelta y no llama ese helper legacy. Esta diferencia
no identifica la causa404 ni prueba un timing productivo. **Propuesta para el
coordinador**, fuera del alcance: si abre el camino legacy, agregar RED de wire
ms y evaluar timedelta más mandatory/confirm-before-ACK en ese flujo, sin
editarlo desde AMQP ni ampliar unilateralmente el encargo a otros errores.

Los cambios actuales son lector operacional, tests y documentación; no cambian
comportamiento servido de gateway/API/worker. No requieren por sí mismos rebuild
de servicio: la operación propuesta carga fuente fijada por stdin.
Si la validación detecta un fix necesario en consumer/scheduler, deberá registrarse
el delta de sheets-worker y quedar build/deploy separados. El lector operacional
no debe presentarse como control desplegado ni como autorización de rollout.

## 7. Pendientes y cese de modificaciones

- El 404 histórico conserva causa desconocida: el reader nuevo aún no se ha
  ejecutado contra Management. Lectura actual requiere la repetición del coordinador.
- Topología sana no prueba entrega confirmada, TTL efectivo ni NACK real ante fallo.
  Esos criterios exigen prueba activa separada/autorizada; no publicar para inferirlos.
- El coordinador integra con CUOTAS, revisa propuestas compartidas y ejecuta gates
  generales tras congelación. No hay aceptación productiva, rollout o piloto nuevo.
- Originales privados preservados por SHA; no cambios a consumidores/scheduler.
- Ownership AMQP se entrega al coordinador; después de esta entrega no continuar
  ediciones ni pruebas sin devolución expresa de ownership/turno.

## 8. Identidades propias al entregar

| Archivo | SHA256 |
| --- | --- |
| `infra/operations/zelerdata_amqp_delay_readonly.py` | `66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb` |
| `tests/test_zelerdata_amqp_delay_readonly.py` | `5a2988a2412f8fc172714169b89768650fd7e32d5adee6e7846d19bad8c3d1f9` |
| `gateway/tests/test_pilot_get_budget_consumers.py` | `9808aae3d54dfeb45ac8d43a6c784246941a03a2f0ec8de2ca89e344f8ad6383` |

El hash del propio informe se registra fuera de él en `final-local-receipt.json`
para evitar autorreferencia. Consumer fuente preservado:
`23ed53f3640b2268f94489b28b30739990f17863176cc73503b6ff5a42aa7fef`;
scheduler preservado:
`27d8a83e6a9597571bf5bc4f6955b71f91fe14b225103b8e5d892231cac9dc4f`.
El recibo final conserva hashes de los archivos propios y originales privados;
no es recibo de aprobación ni prueba de producción.
