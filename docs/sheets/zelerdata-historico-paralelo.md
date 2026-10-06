# ZelerData: coordinación de CUOTAS y AMQP

**Asignación local, no aceptación del producto.** Dos especialistas independientes
con archivos exclusivos; el coordinador integra y es el único operador de Git y
producción. El usuario reanudó trabajo local y coordinación el 5 de octubre de
2026. Los permisos productivos previos siguen condicionados; Full sigue excluido.

## Estado vigente de la continuación AMQP

El usuario autorizó la inspección necesaria, incluida su ampliación de solo
lectura. La reparación del broker **no** está incluida. El historial de abajo
conserva cada solicitud, consumo y STOP; sus estados anteriores no son el actual.

| Entrega/gate | Responsable | Estado / dependencia |
| --- | --- | --- |
| Código integrado y controles generales | Coordinador; originales CUOTAS/AMQP congelados | Publicado y PASS; no repetir por documentación. |
| Dos imágenes nuevas gateway/worker | Coordinador | SUCCESS/VERIFIED; no pull ni despliegue. API intacta. |
| Compatibilidad Mongo instalada | CUOTAS prepara / coordinador inspecciona | PASS con metadata solamente; no documentos ni aplicación de validators. |
| Estructura AMQP | AMQP prepara / coordinador inspecciona | Prefijo histórico y cinco retries/tres exchanges verificados en ventanas separadas;27 GET acumulados. No snapshot global fresco/entrega/admisión. |
| Existencia exacta de retry1s | AMQP prepara / coordinador opera | Broker404 confirma ausencia; cleanup tool_error, STOP y sin repetir. |
| Reparación retry1s | AMQP prepara / coordinador opera | Declaración compatible confirmada; metadata+binding PASS. Cleanup fallido conservado. |
| Buckets restantes del mismo mecanismo | AMQP prepara / coordinador opera | Cuatro declaraciones compatibles confirmadas y once GET200 PASS; cleanup AMQP fallido conservado. |
| Rollout cerrado, OAuth y aceptación piloto | Coordinador / usuario legítimo | Pendientes de gates; permisos condicionales y presupuestos previos intactos. |

### Nueva asignación exclusiva: comprobación pasiva

Root privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997`.
AMQP es el único escritor de estos cuatro paths nuevos; no modifica entregas
anteriores ni archivos compartidos:

1. `ROOT/amqp-passive-check-20261005/passive_check.py`
2. `ROOT/amqp-passive-check-20261005/passive_supervisor.py`
3. `ROOT/amqp-passive-check-20261005/test_passive_check.py`
4. `docs/sheets/zelerdata-historico-amqp-existencia-informe.md`

Encargo: TDD offline con recursos aislados, recibo sanitizado y cierre del
transporte adquirido antes del handshake. Una conexión AMQP no robusta, un canal
y un único `queue.declare(passive=True)` sobre `zeler.sheets.claims.retry.1s`.
Sin creación, consume/basic.get/ACK, publish/bind, otras colas, Management, Mongo
o Meli. Usar únicamente la configuración legítima instalada, sin fallback.
Conexión8s/RPC4s/cleanup5s/operación55s; remote120s/caller130s+cleanup5s y
máximo300s total. Timeout/error → STOP sin retry; counts inciertos son null,
no cero inventado. Solo el coordinador ejecuta producción después de hashes y
ENTREGADO/cese. CUOTAS continúa congelado.

La declaración pasiva verifica existencia, no prueba entrega ni crea la cola.
Su conexión/RPC se registran separados de los 13 GET ya consumidos; no reinicia
ningún presupuesto. [Propuesta de reparación](zelerdata-historico-amqp-reparacion-propuesta.md)
condicionada a `NOT_FOUND` ya confirmado, ahora autorizada; todavía NO ejecutada.

## 1. Punto de partida y preservación

- Checkout verificado localmente a `2026-10-05T18:47:22Z`: `main`, HEAD
  `7cbd1629ab1fda657d88f5ecf20a798bd6f3ac34`, árbol limpio, sin cambios propios ni
  ajenos pendientes. `origin/main` **local** coincide; no se hizo fetch ni nueva
  comprobación remota. Tras el reinicio del servidor se confirmó otra vez HEAD y
  árbol limpio antes de crear este documento.
- El [handoff](zelerdata-historico-handoff.md), publicado en ese commit, es el
  baseline. Su pausa fue sustituida por esta reanudación expresa, **no** por un
  permiso general de repetir operaciones. No reescribir su evidencia histórica.
- Calidad, builds y runtime son planos distintos: los builds gateway/worker
  `cb63260fcf9e628cfc6ca59783e85b86cfa7c9e2` están verificados, no desplegados;
  la API d78 no tiene un nuevo build. La salud/capacidad pasada no es actual.
- Conservar código y evidencia publicados, las imágenes/override actuales, datos,
  jobs, sesiones, credenciales, backups y stages referidos en el handoff. No borrar
  fixtures/evidencia previa ni sustituir logs de fallos por resultados de mocks.
- Conservar registro **14 permisos sin Full**, seis routing keys y restantes
  clientes/campos. No reaplicar registro/índices por este reparto. Mantener cutoff,
  checkpoints, consumos, proofs, leases, ejecución y plazos; sin reset ni takeover.
- Última configuración observada: HOLD=true, history/recovery/refresh OFF y
  selector82. Preservarla; no es verificación actual ni permiso de activación.
- Al publicar esta asignación, el único cambio nuevo del coordinador debe ser
  este archivo. Cada agente verificará de nuevo el estado al comenzar y registrará
  cambios ajenos como preservados, no como propios.

## 2. Propiedad de escritura: listas cerradas

Los paths son relativos a este checkout. **Solo el propietario indicado escribe.**
Leer otros archivos no concede permiso para editarlos. Una ampliación requiere
reasignación expresa del coordinador en este documento y confirmación del dueño
anterior; nunca inferir ownership por directorio o nombre del test.

### 2.1 CUOTAS — único escritor de estos ocho archivos

| Archivo exacto | Alcance / estado inicial |
| --- | --- |
| `gateway/src/zeler_gateway/proxy/router.py` | Existente: admisión/CAS tardío de GET normales y trazados; reparto fuente/fase. |
| `gateway/src/zeler_gateway/proxy/retry.py` | Existente: hook antes de cada intento físico; cambiar solo si el reparto lo requiere. |
| `modules/sheets/src/zeler_sheets/history_onboarding.py` | Existente: cargo histórico inicial/incremental y coordinación con el gateway. |
| `gateway/tests/test_pilot_get_budget.py` | Existente: preservar regresiones del guard global y sumar reparto cuando corresponda. |
| `gateway/tests/test_history_proxy_attribution.py` | Existente: atribución autenticada y relectura tardía. |
| `gateway/tests/test_pilot_get_budget_allocation.py` | Nuevo, aún no creado: matriz/concurrencia de reparto físico normal+h1 por fase/fuente. |
| `modules/sheets/tests/test_history_execution_controls.py` | Existente: cargo, pacing, deadline/día UTC y preservación de créditos. |
| `docs/sheets/zelerdata-historico-cuotas-informe.md` | Nuevo, aún no creado: informe propio, propuestas para archivos reservados y entrega. |

No es obligatorio cambiar todos los archivos. No tocar consumidores, scheduler,
helper AMQP ni informe AMQP; las propuestas sobre ellos van en el informe CUOTAS.

### 2.2 AMQP — único escritor de estos seis archivos

| Archivo exacto | Alcance / estado inicial |
| --- | --- |
| `infra/operations/zelerdata_amqp_delay_readonly.py` | Nuevo, aún no creado: lector GET-only instrumentado, ejecución explícita y salida sanitizada. |
| `tests/test_zelerdata_amqp_delay_readonly.py` | Nuevo, aún no creado: fixtures/MockTransport, HTTP/path/encoding/counts/STOP/redacción. |
| `modules/sheets/src/zeler_sheets/consumer.py` | Existente: solo protección de WAIT diferido, confirmación antes de ACK y NACK ante fallo. |
| `modules/sheets/src/zeler_sheets/sync_jobs_processor.py` | Existente: solo fence/backoff/preservación de trabajo en WAIT; no cuotas ni otros jobs. |
| `gateway/tests/test_pilot_get_budget_consumers.py` | Existente: pruebas de consumidores/scheduler y publicación diferida; aunque su nombre diga budget, lo escribe solo AMQP. |
| `docs/sheets/zelerdata-historico-amqp-informe.md` | Nuevo, aún no creado: informe propio, herramienta, límites, pruebas y pendientes productivos. |

No es obligatorio cambiar consumidores/scheduler si los controles ya son correctos.
No tocar el proxy, política/cargo histórico ni informe CUOTAS. No añadir otro test
file o fixture compartida sin reasignación; usar primero los paths autorizados.

### 2.3 Compartidos reservados al coordinador

Estos archivos permanecen de solo lectura para ambos especialistas:

| Archivo exacto | Motivo |
| --- | --- |
| `docs/sheets/zelerdata-historico-paralelo.md` | Ownership, dependencias, estado y ledger único de esta continuación. |
| `docs/sheets/zelerdata-historico-handoff.md` | Estado central/traspaso; preservar evidencia fechada. |
| `docs/sheets/zelerdata-historico-al-vincular-especificacion.md` | Contrato y aceptación. |
| `docs/sheets/zelerdata-historico-al-vincular-implementacion.md` | Informe central de implementación/evidencias. |
| `docs/sheets/zelerdata-historico-publicacion-piloto-propuesta.md` | Publicación, imágenes, despliegue y recuperación. |
| `docs/sheets/zelerdata-historico-control-piloto.md` | Runbook canónico del piloto. |
| `docs/sheets/zelerdata-historico-builds-runtime-20261003.md` | Historial de builds/runtime. |
| `docs/deploy.md` | Operación/build/procedencia. |
| `docs/lessons/README.md` | Lecciones centrales. |
| `infra/operations/zelerdata_history_pilot.py` | Prepare/activate/CAS y recibos del piloto. |
| `tests/test_zelerdata_history_pilot.py` | Regresiones del operador compartido. |
| `core/src/zeler_platform_core/history_onboarding.py` | Contrato compartido de ejecución y trazas. |
| `core/src/zeler_platform_core/models/sheets_history.py` | Modelos/persistencia compartidos. |
| `core/src/zeler_platform_core/runtime/retry_delay.py` | Contrato compartido de retries/expiración. |
| `infra/rabbitmq/sheets_devoluciones_topology.py` | Transporte/topología compartida, también usada por otras operaciones. |
| `gateway/src/zeler_gateway/config.py` | Configuración/selector compartidos. |
| `modules/sheets/tests/_amqp_fakes.py` | Fixture compartida. |
| `conftest.py` | Fixtures/targets compartidos. |
| `gateway/tests/conftest.py` | Fixtures/logging compartidos. |
| `pyproject.toml` | Dependencias y configuración de calidad. |
| `uv.lock` | Lockfile compartido. |
| `gateway/Dockerfile` | Imagen gateway. |
| `modules/sheets/Dockerfile.api` | Imagen API. |
| `modules/sheets/Dockerfile.worker` | Imagen worker. |

También quedan reservados Git/staging/commits/push, configuración global y de
runtime, manifiestos/Compose/overrides, schemas/índices/seeds, dependencias,
lockfiles y entornos compartidos. **Todo archivo no incluido en 2.1 o 2.2 queda
sin permiso de escritura para los especialistas.** Sin cambios a otros repos.

Si ambos necesitan un archivo reservado, ambos entregan propuestas por símbolo y
test en sus informes; el coordinador sigue siendo el único escritor. Si AMQP
necesita `router.py`, propone sin editar; si CUOTAS necesita `consumer.py`, propone
sin editar. El coordinador no edita un archivo asignado hasta entrega y cese de
modificaciones confirmado por su dueño.

## 3. Encargos y criterios de entrega

### 3.1 CUOTAS: reparto efectivo, no solo techo global

Leer handoff §§5–8, [control](zelerdata-historico-control-piloto.md), política y
tests asignados; consultar Quick path y L-012/L-013/L-030 de lessons. Ruta directa
delegada para este cierre localizado; no crear un SDD sintético ni subagentes.

1. Inventariar caminos GET normales/eventos/retries/h1 y explicar la brecha:
   `_reserve_pilot_get_send` cobra ejecución global; `PlanBudgetGateway` cobra
   fuente/fase histórica. Determinar origen confiable de fuente/fase para normales
   antes de cambiar comportamiento. Un path `/orders/*` puede pertenecer a más
   de un flujo: no inventar una atribución ni confiar en headers arbitrarios.
2. Cerrar el reparto original mediante el mínimo cambio compatible y TDD estricto:
   primera prueba RED antes de cada cambio no trivial, luego GREEN/regresiones.
   Si hace falta cambiar contrato API/persistencia/policy/selector o un archivo
   reservado, presentar propuesta y dependencia **antes** de implementarlo;
   continuar trabajo independiente, no ampliar diseño unilateralmente.
3. Incluir intentos físicos normales, eventos y todos los retries atribuibles al
   piloto en los límites fuente/fase/global; evitar doble cargo h1 y races normal+h1.
   Acreditar cargo/CAS antes de cada transporte, último crédito concurrente,
   rechazo antes del proveedor al agotarse fuente/fase/global y aislamiento de
   otras cuentas/métodos. Fuente/fase desconocida: gate pendiente o bloqueo seguro,
   nunca permiso de enviar saltándose un límite ni una etiqueta ficticia.
4. Probar preservación de consumos ante fallo/crash/deadline posterior al cargo,
   controles opt-in, día UTC, paused/lease/fence y no reseteo/refund/reasignación de
   cuotas. Rollover natural no amplía el piloto ni sus 90 minutos.
5. Informe: tabla fuente/fase, caminos cubiertos/no atribuibles, estado de cada
   gate, RED/GREEN con comandos/exit/conteos y paths/hashes, propuestas reservadas,
   efectos sobre imágenes y faltantes. Mocks/CAS local no prueban producción.

| Fuente | Inicial máximo adicional |
| --- | ---: |
| orders (órdenes/comisiones) | 800 |
| questions (preguntas/respuestas) | 150 |
| shipments (envíos/costos) | 250 |
| messages | 300 |
| claims_returns (reclamos/devoluciones) | 500 |
| Total inicial | **2,000** |
| Mantenimiento conjunto | **500, máximo 300 por fuente** |
| Techo físico conjunto | **2,500 / 90 minutos / mismo día UTC** |
| Full | **0** |

Son techos autorizados, **no saldo actual**. Deducir saldo de counters/política/
ledger canónicos sin consultas productivas por el especialista. No reiniciar
prepare, checkpoints ni ventana para conseguir saldo.

### 3.2 AMQP: diagnóstico fiable y protección diferida offline

Leer handoff §§5–8 y lessons L-014/L-024/L-027. Examinar fuente y pruebas privadas
anteriores, sin ejecutarlas contra runtime ni modificar sus bytes:

```text
$HOME/Library/Caches/zeler-operations/rescue-corrected-20261004T011204Z/
  amqp-delay-readonly-controls-20261005/amqp_delay_readonly.py
  amqp-delay-readonly-controls-20261005/test_amqp_delay_readonly.py
  pilot-amqp-delay-readonly-20261005T175704Z-{start.json,stdout.log,stderr.log,end.json}
```

SHA256 original reader:
`321273da312473722a2baf73dd027b2957f6c5650d19f64f14a19155ed5fe377`;
tests originales:
`0c97de0649d6993b5706846152058f390d0997a8ecf24e052523fbfd93c3e235`.
Guardar propuestas/nueva herramienta en los paths propios del repo, no reemplazar
el helper fallido ni sus recibos. No leer/volcar archivos env o credenciales.

1. Empezar con RED para el déficit de diagnóstico y reproducir offline 404,
   auth401/403, composición de base/path/vhost/encoding, redirects, timeout,
   JSON inválido, respuesta >64KiB, forma/paginación/truncación y primer error.
   No atribuir la causa real del HTTP404 sin nueva evidencia.
2. Lector default sin ejecutar; únicamente GET Management seleccionados,
   secuenciales, sin retries/redirecciones/probes adicionales/exports generales.
   Instrumentar etapa, etiqueta de endpoint seleccionada sin host/vhost sensible,
   código HTTP o error fijo, GET iniciados y completados, bytes/truncación, tiempo
   y STOP. Errores y cleanup también sanitizados; nunca URL completa, auth, env,
   body crudo, traceback con credenciales ni conexiones AMQP.
3. Conservar el alcance original: **10 colas × (metadata + bindings) + 3 exchanges
   = máximo 23 GET**. Colas: `zeler.sheets.events`, `.events.delay`, `.events.dlq`,
   `zeler.sheets.claims`, `.claims.dlq` y `.claims.retry.{1s,5s,30s,2m,10m}` (todas
   con prefijo `zeler.sheets`). Exchanges: `meli.events`,
   `zeler.sheets.events.dlx`, `zeler.sheets.claims.dlx`. Sin discovery adicional.
   ≤4s por request, ≤60s lectura y ≤5min operación completa incluida limpieza.
   Tras fallo no probar otra URL ni variar credenciales; simplemente STOP.
4. Evaluar TTL/DLX/bindings/policies/consumers con fixtures representativos. Un
   argumento benigno añadido por el broker no justifica mutación. Separar lectura
   de topología, expiración por mensaje y publicación confirmada: GET-only no
   prueba entrega ni tiempo efectivo, y no se publica para obtener esa prueba.
5. Sobre los consumidores/scheduler reales con transporte simulado, acreditar
   WAIT/fence/backoff, conservación de attempt y trabajo/progreso, timedelta con
   expiración wire en ms, mandatory-confirm antes de ACK y NACK si falla publicación.
   No introducir estados/headers/quotas nuevas ni mutar otros flujos. Modificar
   comportamiento solo tras RED; si ya es correcto, entregar pruebas sin churn.
6. Entregar herramienta, hash, comando de ejecución propuesto (no ejecutado),
   selección exacta, deadline/counts, RED/GREEN y límites de evidencia en informe
   propio. La repetición autorizada en §5 la ejecuta **solo el coordinador**.

## 4. Concurrencia, pruebas y entrega de ownership

- Ambos pueden escribir simultáneamente solo sus listas. No abrir más agentes,
  tomar tareas ajenas, cambiar ramas/worktrees, stash/reset/discard, hacer Git de
  escritura, builds Docker/Cloud Build ni llamadas a nube/Meli/Mongo/Rabbit/Sheets
  productivos. No installs/sync ni cambios al `.venv`/config compartidos.
- Pruebas enfocadas con fakes/ASGI/MockTransport y sin sockets externos; el
  especialista inspecciona fixtures y entorno antes de ejecutar. `MONGO_URI` del
  entorno **no garantiza aislamiento**. No imprimirlo ni reutilizar targets existentes.
- Caches/logs/tmp propios fuera del checkout:
  `$HOME/.codex/cache/zelerdata-paralelo-20261005/cuotas/` y
  `$HOME/.codex/cache/zelerdata-paralelo-20261005/amqp/` respectivamente. Evitar
  bytecode/caches de escritura compartidos; usar entorno ya instalado, `uv run
  --no-sync`, `PYTHONDONTWRITEBYTECODE=1`, pytest sin cacheprovider/basetemp propio
  y ruff/mypy con cache propio o desactivado. No imprimir entorno ni secretos.
- **Default: serializar las verificaciones enfocadas** mediante el coordinador.
  Pueden paralelizarse solo tras confirmar recursos, puertos, bases, caches y
  dependencias importadas estables/aisladas; no probar código del otro mientras
  lo edita. Mongo real/protected y proveedores quedan para validación coordinada;
  si no hay aislamiento verificable, serializar o reportar pendiente, no improvisar.
- **Turno actual: coordinador; ambos especialistas ENTREGADOS y congelados.**
  El usuario confirmó cese AMQP después de CUOTAS; el coordinador cotejó hashes
  y no encontró candidatos pytest/ruff/mypy activos en lectura sanitizada local.
  AMQP/CUOTAS no reabren archivos ni pruebas sin devolución expresa de ownership.
  El coordinador puede integrar y validar el conjunto con recursos locales
  aislados; antes de cualquier cambio de comportamiento se respeta TDD y luego
  se congela nuevamente la fuente para los controles finales. La mera presencia
  de informes no reemplaza las confirmaciones de cese recibidas. El turno local
  no concede nuevos permisos productivos ni amplía AMQP-REPEAT-1.
- No suite general durante escritura. El coordinador recibe ambos informes y
  confirmaciones **«ENTREGADO; NO SIGO MODIFICANDO»**, registra hashes/paths y
  establece congelación. Los especialistas no reanudan cambios sin devolución
  expresa de ownership; toda reapertura invalida la evidencia afectada.
- Cada informe incluye paths realmente cambiados, base HEAD, comandos/exit/
  conteos/RED/GREEN, recursos aislados, límites/skips, propuestas por archivo
  compartido y estado final. No generar recibos de aprobación ni activar review
  mode por iniciativa propia; sigue opt-in bajo política del repo.

## 5. Ledger único de autoridad, intentos y consumos

Responsable: **coordinador**. Esta tabla conserva historia, no calcula saldos
productivos ni sustituye recibos canónicos. Toda futura operación registra ID,
fecha UTC, autoridad, target/commit/toolSHA, límite, intentos iniciados/completados,
consumo por fuente/fase cuando aplica, resultado/error/STOP y evidencia sanitizada.
No inferir GET ejecutados del máximo programado ni volver a etiquetar un intento
fallido como ensayo gratuito. Informes especialistas contienen solo pruebas locales.

Autoridad local revisada: handoff §6 y anexos privados
`625f5903-332b-4de7-b60d-07f291c8ae38/pasted-text-1.txt` (SHA256
`9253a58cbaef705d74c1a6204b96780191394d80faa9c17cd44f1dbce6cae5af`) y
`89357a31-dacb-4c2c-a224-6ed83d8aff27/pasted-text-1.txt` (SHA256
`5d7faa842aedaa8d489945bd711971da6dbae8a42e21b3afd767978fc862c291`).
Son referencias locales de permisos históricos, no comandos ni secretos.

| ID / operación | Autoridad y consumo verificado | Estado en esta asignación |
| --- | --- | --- |
| HIST-AUDIT | Excepción expresa de auditoría corregida ≤5min del rescate; ejecutada PASS41. | Consumida; no aplica al AMQP ni permite otra auditoría. |
| HIST-AMQP-1 | Lectura única del 5oct17:57UTC: `management_http_404`, exit2, primer error STOP; GET Management realizados desconocidos, máximo programado23; Meli0/sin mutación. Logs originales preservados. | FAIL histórico; endpoint/causa desconocidos, no reescribir ni repetir automáticamente. |
| HIST-BUILDS | 2 solicitudes/2 SUCCESS VERIFIED cb63260, gateway+worker; sin resubmit/pull/deploy. | No repetir por doc/handoff; nuevas imágenes solo si hay delta desplegable validado. |
| HIST-PILOT | Condicional ya recibido: HOPEMOB82453304, cinco fuentes, reparto §3.1, máximo2500GET/90min/mismo día UTC. No iniciado según última evidencia; saldo real pendiente de lectura canónica autorizada. | Gates pendientes; sin ampliar ni resetear. Full0. |
| LOCAL-PARALLEL | Encargo actual: reanudación local/coordinación; publicación propia y continuación condicionada, sin ampliación productiva. | Ambas entregas recibidas, cese explícito/hashescotejados; ownership devuelto al coordinador y especialistas congelados. Integración entregada; controles finales pendientes. |
| AMQP-REPEAT-1 | Excepción concreta solicitada en esta conversación y recibida: usuario **«Sí, solo esa repetición acotada»**. `platform-vm`, `zeler-platform-dev/us-central1-a`, mismas10colas/3exchanges, ≤23GET Management/60s lectura/5min totales; 0Meli, sin publicaciones/mutaciones; offlineGREEN previo; STOP primer error y sin otro intento. | **CONSUMIDA: 1 operación, reader iniciado, GET iniciados/completados0; exit2 `management_configuration_invalid`, STOP.** Sin otro intento, fallback ni permiso pendiente solicitado. |

Los permisos condicionales de publicación/builds estrictamente necesarios,
rollout seleccionado y piloto ya se recibieron. No volver a pedirlos por analogía
con la excepción AMQP. Los cortes/restores/Full consumidos o excluidos del handoff
no se reabren. Ninguna autorización adicional de recursos/costos/IAM/lifecycle,
colas, limpieza, add-on o otras cuentas se deriva de esta asignación.

## 6. Entregas, dependencias y continuación del coordinador

| Entrega | Responsable | Dependencias | Estado actual |
| --- | --- | --- | --- |
| Ownership/ledger/documento | Coordinador | Handoff, checkout y permisos reales. | PUBLICADO con las unidades propias; ledger de intentos preservado. Estado de publicación abajo. |
| Reparto local por fuente/fase | CUOTAS | Asignación2.1; propuestas para core y flujos normales/eventos compartidos. | ENTREGA RECIBIDA; cese explícito y7hashesPASS originales. Habilitación local normal/eventos integrada directamente y validada; no servida ni prueba productiva. Informe original preservado. |
| Reader404 + protecciones diferidas offline | AMQP | Asignación2.2; originales preservados; RED/GREEN locales. | ENTREGA RECIBIDA;179PASSreportados,9hashestabla+consumer/schedulerPASS; sin producción. Causa404/entrega real pendientes. |
| Integración de propuestas compartidas | Coordinador | Ambas entregas y ownership devuelto. | INTEGRADA/PUBLICADA: intención durable/ownership live/crédito work no fungible/WAIT conservador. CUOTAS-integración entregó y dejó de escribir; coordinador cerró fixes finales. Propuesta legacy TTL fuera del camino WAIT actual. |
| Congelación y calidad del conjunto | Coordinador | Ambas entregas + cese de cambios + coherencia + Mongo local aislado verificado. | PASS con todos los escritores congelados: full6395PASS/20SKIP, rs019PASS, focused455PASS, ruff/formato/mypy665/direct/schemaPASS. Target local propio verificado y retirado; skips documentados, no aceptación. |
| AMQP-REPEAT-1 | Coordinador | Autoridad recibida §5, reader/hash/fixturesGREEN y selección cerrada. | CONSUMIDO/FAIL configuración,0GET; STOP sin retry. |
| Publicación/builds afectados | Coordinador | Calidad final, cambios propios delimitados y commit fuente exacto en main/remoto. | CÓDIGO PUBLICADO;2builds nuevos SUCCESS/VERIFIED source352f3bd6, worker+gateway únicamente. VMpull0/deploy0; gate AMQP bloquea rollout/OAuth/piloto, no builds independientes autorizados. No API/otros. |
| Rollout seleccionado | Coordinador | Gates de topología/reparto/controles, procedencia, capacidad fresca y recuperación compatible. | BLOQUEADO POR GATES; autorización condicional vigente. |
| OAuth/prepare/activate/piloto | Coordinador + humano para OAuth | Runtime/pins/guards servidos, presupuesto/día/deadline/recibo pinned y gates completos. | NO INICIADO en esta coordinación. |
| Aceptación del objetivo | Coordinador | Fuente por fuente/rangos independientes, parcialAPI normal y dos incrementales auténticos dentro del plazo. | PENDIENTE; objetivo NO completado. |

Secuencia original de coordinación (entregas, validación y publicación ya cerradas;
AMQP-REPEAT-1 consumida, no ejecutar nuevamente los pasos completados):

1. Conciliar contratos/cargo/WAIT/herramienta y propuestas; implementar únicamente
   en paths propios o ya entregados. No marcar AMQP runtime sano por fixtures ni
   reparto productivo cerrado por techo global. Si una entrega es incompleta,
   identificar el gate exacto y continuar lo independiente autorizado.
2. Congelar cambios con ambos especialistas. Verificar targets de desarrollo
   aislados antes de Mongo; ejecutar focused + las cuatro gates exigidas:
   `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy .`. Cubrir protected Mongo separadamente sin usar skips como PASS.
   Añadir `uv run python -m infra.lint.check_direct_meli .` por cambios gateway;
   export schemas `--check` si modelos/schema cambian. Reportar fallos previos
   separados, reparar regresiones y repetir evidencia invalidada.
3. Ejecutar como máximo AMQP-REPEAT-1 cuando pase preparación offline; escribir
   inicio antes de la llamada y final/consumos/error/STOP incluso si falla. No
   interpretar 404 como cola ausente ni reparar topología con este permiso.
4. Publicar solo unidades propias con sus tests/docs, staging por paths, sin
   credenciales/ajenos, Conventional Commits/sin atribución AI/force-push. Confirmar
   SHA remoto=HEAD y árbol limpio o identificar trabajo ajeno pendiente. No commit
   adelantado de entregas parciales ni branches/worktrees nuevos.
5. Determinar imágenes afectadas por el **delta final**, no por el número de
   especialistas. Cambios proxy → gateway; cambios consumer/scheduler → worker.
   `history_onboarding.py` también tiene consumidores en API: evaluar el símbolo
   realmente cambiado antes de decidir API. Dockerfiles de API/worker incluyen
   `infra/operations`, pero añadir un reader operativo no obliga por sí solo a
   reconstruir API/worker si puede ejecutarse fuente congelada por stdin en el
   runtime legítimo. No asumirlo instalado en imágenes viejas. Cambios a core o
   dependencias requieren mapa nuevo. No rebuild por docs/tests únicamente.
6. Si hay nuevo delta desplegable, construir solo imágenes necesarias desde
   commit exacto publicado/validado en repositorio conectado, una imagen por build,
   `requestedVerifyOption: VERIFIED`, verificar build/source/procedencia/digest.
   Pins cb63260 se reutilizan únicamente si el cambio no invalida ese servicio;
   no servir versiones anteriores para evitar un build necesario.
7. Cerrar gates antes de rollout/OAuth. Seguir handoff/deploy: capacidad fresca
   bytes/inodos/Mongo/RAM/health/OOM; ≥5GiB raíz antes de **cada** pull; preservar
   override y recuperación compatible; nueva versión exclusiva, worker primero,
   gateway después, sin broad restart. API/registro14 intactos si no afectados.
   Confirmar digest/readiness/componentes/comportamiento tras settling, no solo200.
8. Solo después OAuth humano legítimo → prepare paused/recibo pinned → activate
   CAS, conservando cutoff/consumos/ventana. Contar todos los intentos físicos y
   STOP ante429/error/timeout/inconsistencia/límite/día/deadline. Dos cambios reales,
   no eventos fabricados/renovaciones vacías; si no ocurren, aceptación pendiente
   sin extender plazo. No marcar completado hasta cumplir el handoff §1.

**Entrega de esta fase:** asignación y encargos listos para los dos agentes. No se
han realizado aquí por el coordinador staging/commit/push, pruebas de código,
builds ni operaciones productivas. Los informes propios pertenecen a sus dueños;
su existencia no significa que hayan entregado ni dejado de modificar.

## 7. Seguimiento local — 5 de octubre de 2026

El usuario confirmó CUOTAS corriendo y AMQP esperando turno de pruebas. Una
lectura de `git status --short` encontró cambios en `router.py`,
`test_pilot_get_budget.py`, `test_pilot_get_budget_consumers.py` y nuevos informes
CUOTAS/AMQP, `test_pilot_get_budget_allocation.py` y
`test_zelerdata_amqp_delay_readonly.py`, además de este documento. Todos esos paths
pertenecen a las listas asignadas; se preservaron sin editar archivos de agentes.
Es un snapshot de presencia, no validación de contenido, RED/GREEN o entrega.

El coordinador actualizó únicamente estado/turno en este documento. Sin suite
general ni operación productiva; AMQP-REPEAT-1 continúa autorizada y no consumida.

### Turno transferido a AMQP — 19:34:20 UTC

Por instrucción del usuario **«Ya terminó Cuotas su ejecución, libera el turno de
AMQP»**, se recibió [informe CUOTAS](zelerdata-historico-cuotas-informe.md) con
**«ENTREGADO; NO SIGO MODIFICANDO»** y ownership devuelto. Se comprobaron contra
el checkout los siete hashes de código/tests declarados (7/7PASS) y la existencia
del recibo privado final. SHA256 del informe recibido:
`e8350c31fbafb07a71976a3e88a941f03c100bac5b4cc12c1c2273c39c6b7d9b`.
Una lectura sanitizada de procesos no encontró candidatos de verificación activos.
No se repitieron sus pruebas ni se editó ningún path de especialistas.

La entrega reporta150PASS gateway y6PASS/10deselected pacing, calidad enfocada;
es evidencia reportada, todavía sin validación del conjunto por el coordinador.
El proxy seleccionado queda fail-closed para normales/eventos sin intención h1
confiable: **el gate funcional de esos flujos sigue pendiente**, no se declara
reparto/acquisición productiva completados. Sus propuestas para core/consumidores/
scheduler se integrarán respetando ownership AMQP mientras siga escribiendo.

AMQP ya tiene turno local exclusivo para sus verificaciones enfocadas, TDD y
entrega. CUOTAS queda congelado. Suite general solo tras entrega y cese de AMQP
e integración/congelación final; AMQP-REPEAT-1 sigue sin consumir y reservada al
coordinador. Ningún permiso productivo o presupuesto cambia por este relevo.

### Ambas entregas congeladas e integración directa — 20:00 UTC

AMQP entregó **«ENTREGADO; NO SIGO MODIFICANDO»**. El coordinador cotejó los
nueve hashes de su tabla y los dos sources consumer/scheduler preservados; todos
PASS. Informe recibido SHA256
`2a15d9f3848282de28ed0496101544c767977450e18d392e0fd16d5f72f88347`.
Ambos especialistas originales siguen congelados; sus informes no se reescriben.

El usuario eligió **«No es necesario sdd, haerlo direto»** para la atribución
normal/eventos: integración directa, sin artefactos SDD ni modificación de
presupuestos. Se delega únicamente exploración **de solo lectura** de ese flujo,
sin escritor adicional, pruebas, subagentes, Git, builds ni producción. El
coordinador conserva todos los archivos compartidos. Antes de delegar cualquier
escritura nueva se publicará otra lista cerrada y se congelará de nuevo al terminar.
`gateway/tests/test_proxy_flow.py` queda reservado al coordinador para adaptar la
fixture h1 al cerco de autoridad ya exigido, sin debilitarlo.

Validación del snapshot entregado, congelado (1066 paths; tar SHA256
`07b4085a7a1c161ce3cca18f1e02792208aff1dc1597e5998d746bda4674471b`):
345 pruebas enfocadas PASS; ruff y formato globales PASS; mypy global PASS en
661 archivos; direct-Meli PASS. Suite completa: **4 FAIL, 6312 PASS, 9 SKIP**;
las cuatro pruebas de `test_proxy_flow.py` siembran crédito sin
`authority.kind=account_link_policy`, ahora obligatorio, y reciben412 antes de
transporte. No se silencia ni cuenta como PASS. Protected rs0 separado:8PASS.
Fuente y modos preservados antes/después de cada control. Nueva implementación
invalidará esta evidencia y requerirá congelación/controles del conjunto final.

Recursos locales exclusivos: perfil Colima `zeler-paralelo-8dafff186997`, sin
montajes del host ni activación/cambio de contexto; Mongo PRIMARYrs0 y Rabbit
nuevos en volúmenes propios. Docker default y perfiles existentes preservados.
Sin conexión a bases productivas, providers ni credenciales ambientales.
AMQP-REPEAT-1 continúa sin consumir; preparación offline del supervisor no es
un nuevo intento productivo. Sin staging, commits, push, builds ni despliegue.

### Inicio de la única repetición AMQP

AMQP-REPEAT-1: inicio **2026-10-05T20:02:28.010123+00:00**, intento productivo1.
Reader congelado SHA256 `66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`; supervisor privado
SHA256 `31a298ebb985ab934dd15eef5ee3467c93108c566c76874da654f8df52483e70`, RED/GREEN12PASS (incluye ejecución stdin real sin
configuración/0GET y conservación del recibo exit2). Identidad del único worker
activo y digest servidos se verifican sin lectura de env antes de ejecutar el
reader. Una llamada SSH, sin retry; deadline local300s, supervisor remoto150s,
reader alarm80s más sus límites internos4s/request,60s lectura/5s cleanup.
Máximo23GET Management/0Meli/0AMQPmutaciones. Primer error STOP, sin fallback
endpoint, credenciales, probe adicional o segunda llamada. Inicio privado
registrado antes del comando; se añadirá el resultado incluso en fallo.

### Resultado AMQP-REPEAT-1 — 20:02:46 UTC

**FAIL/STOP `management_configuration_invalid`, exit2.** La selección del único
worker/digest esperado pasó; el lector congelado se inició y rechazó la
configuración antes de red. Management GET iniciados0, headers recibidos0,
completados0; Meli0, mutacionesAMQP0. Una operación nueva consumida, aunque no
hubo GET. Comando7.588s; inicio20:02:28UTC, final20:02:46UTC (≤5min).
No hubo segunda llamada, fallback de endpoint/credenciales, publicación,
declaración, reparación, build, deploy o piloto. **La excepción queda agotada.**

No se inspeccionan ni imprimen valores de entorno. Este resultado no identifica
la causa del404 histórico ni ausencia de recursos; topología/publicación/TTL/
entrega real siguen pendientes. Se detiene toda continuación productiva por esos
gates. Puede continuar únicamente implementación/validación local autorizada.
Recibos privados start/end y logs originales de esta ejecución preservados;
SHA256 del recibo final `3c118933f25097919bde9b5ab7d83fc5c1571a5cc1bd60cd26021e1f29b15342`.

### Ownership de integración directa (listas nuevas, entregas originales preservadas)

El explorador CUOTAS-integración terminó sin editar ni probar. Se reasigna a ese
único writer la lista cerrada siguiente; no es reapertura de los informes de los
especialistas originales. Ambos entregaron y devolvieron ownership previamente.

| Único writer CUOTAS-integración | Encargo |
| --- | --- |
| `modules/sheets/src/zeler_sheets/history_onboarding.py` | Cargo mantenimiento ligado a intención durable por intento, sin crédito h1 fungible nuevo. |
| `modules/sheets/src/zeler_sheets/consumer.py` | Gateway local por entrega; intención/claim real; WAIT conservador. |
| `modules/sheets/src/zeler_sheets/sync_jobs_processor.py` | Topic persistido real y referencia job token/fence; WAIT pending. |
| `modules/sheets/tests/test_history_work_intent.py` | Nuevo: integración handler/replay y aislamiento concurrente. |
| `modules/sheets/tests/test_history_execution_controls.py` | Cargo/trace por intento, pacing, preservación y cuotas. |
| `gateway/tests/test_pilot_get_budget_consumers.py` | Regresiones de WAIT confirmado y jobs. |
| `docs/sheets/zelerdata-historico-cuotas-integracion-informe.md` | Nuevo informe de esta integración, RED/GREEN y cobertura/gaps. |

El coordinador es único writer de `core/src/zeler_platform_core/history_work_intent.py`
(nuevo), `core/tests/test_history_work_intent.py` (nuevo),
`core/src/zeler_platform_core/events/claim_gate.py`,
`core/tests/test_event_claim_gate.py`, `gateway/src/zeler_gateway/proxy/router.py`,
`gateway/tests/test_history_proxy_attribution.py` y `gateway/tests/test_proxy_flow.py`,
además de todos los documentos centrales/config/dependencias/lockfiles ya reservados.
`events/claims.py` y sus tests quedan sin modificación prevista: no cambiar
completado/release/TTL ni renovar leases para esta integración.

Dependencia: interfaz core debe quedar congelada antes del RED del writer, y el
coordinador no editará sus siete archivos hasta nueva entrega/cese explícito.
Sin suite general mientras escriben; pruebas focused fakes locales seriales por
turno y Mongo real exclusivamente coordinador en el target aislado. Sin producción
adicional: AMQP-REPEAT-1 está consumida y STOP vigente.

Prueba adicional reservada al coordinador:
`tests/integration/test_history_work_send_rs0.py` (nuevo): CAS/transacción real en
Mongo loopback PRIMARYrs0 exclusivo, sin MONGO_URI ambiente, nombre de base nuevo;
concurrencia/último nonce, takeover entre read/touch, rollback de fences y rechazo
h1 sin work credit. Se ejecutará focused con core/gateway congelados y source
copiado estable, nunca contra producción ni junto a otra prueba con misma base.

### Entrega integración y congelación final — 2026-10-05T20:23:26.930371+00:00

CUOTAS-integración confirmó **«ENTREGADO; NO SIGO MODIFICANDO»** y devolvió sus
siete paths. Se cotejaron6/6 hashes declarados; informe recibido SHA256
`9fcc9c3723c5ac1abaead7bfde7531462455e62692539b90c3966fbdf93f0e35`.
163PASS/0SKIP reportados (un caso realMongo deselectado), pacing6PASS/10deselected,
ruff/formato/mypy6pathsPASS. Los informes originales se conservan como snapshots
de entrega, no hashes del árbol integrado posterior.

Tras devolución, el coordinador detectó fallback `fetch_resource` después del
unwrap de pacing, aunque la fachada exponía `fetch_resource_once`: RED1 antes
fix; el cliente físico work ahora exige once callable, WAIT sin transporte si
falta, conservando el cargo. Nuevo focused módulo44PASS, ruff/mypy2pathsPASS.
No modifica API/legacy work_intent=None. Se añadió prueba real de integración
cargo→clienteMock→reserva transaccional, pendiente del lote final rs0.

**Todos los escritores quedan congelados, turno exclusivo del coordinador.**
Se hará snapshot nuevo completo con nombres/hashes/modos, Mongo/Rabbit locales
propios verificados y sin entorno sensible; suite general no usa código vivo en
edición. Ruff, formato, mypy global, direct-Meli, pytest completo y protected/rs0
se ejecutan seriales. No publicación/builds/productivo durante controles.
Imágenes efectivamente afectadas: gateway y Sheets worker; API no por ramas
aditivas sin callerwork. Producción sigue STOP por AMQP-REPEAT-1 consumida.

### Controles finales cerrados y cleanup local — 2026-10-05T20:41:50.336213+00:00

Snapshotfinal2 `826774c365b31afcfb886f4e7ec901dc5a0bb804ceb7adc9431927e3f7cf2666`,1072paths, todos los ocho controles
serialesPASS: full6395PASS/20SKIP; protectedrs019PASS; focused455PASS;
ruff/formato/mypyglobal665/direct/schemaPASS. FAIL intermedio del mock ASGI
preservado y corregido únicamente en fixture; suite completa y controles repetidos.
Recibo/manifiesto/limitaciones en [integración](zelerdata-historico-integracion-20261005.md).
No se cuentan skips como aceptación. Metadata/documentación de resultados son
las únicas escrituras posteriores; todo no-Markdown debe coincidir por hash al
publicar. No review RDD solicitado; validación ordinaria, sin recibo de aprobación.

Cleanup propio completado:6containers/8volúmenes/1anónimoMongo y perfil/data
locales; contexto y dos perfiles previos preservados. Recibos/caches originales
intactos. Publicación de dos unidades propias queda autorizada tras esos controles:
readerAMQP+tests/informe, luego core/gateway/worker+regresiones/documentos. Git
solo coordinador, staging exacto, main existente, sin force o ramas/worktrees.
AMQPexcepciónconsumida/STOP, builds/deploy/piloto y aceptación siguen pendientes.

### Publicación de código y relevo — 2026-10-05T20:46:40.180910+00:00

Dos unidades propias publicadas en `main`: reader/test/informe AMQP
`2c657015d5d64a6650811d378ebdae21cc0e6ed2` e integración/tests/documentos
`9149d00b7d979fb4498a4c16ae6c3220172b566f`. Remoto=HEAD y árbol limpio
verificados tras push normal, sin force. Exactamente24paths propios;903blobs
no-Markdown y bits ejecutables Git coinciden con el snapshot final2 probado.
Los permisos POSIX0600 de cuatro archivos preexistentes se conservan localmente;
Git solo representa su modo100644, idéntico al padre, no un cambio de código.
El guard inicial de esa comparación se detuvo antes del push; evidencia preservada.

Esta actualización es exclusivamente documental y no exige repetir suite/builds.
Su identidad se consulta con `git log -1 --format=%H -- docs/sheets/zelerdata-historico-paralelo.md`
sin autorreferencia. No se modifica ninguno de los informes entregados.
**Próximo gate productivo: AMQP configuración/topología/entrega real; STOP.**
Sin retry nuevo, build, despliegue, OAuth, piloto ni cierre de aceptación.
No solicitar de nuevo permisos condicionales vigentes ni resetear plazos/consumos.

### Reanudación de aceptación — 2026-10-05T21:42:13.093048+00:00

Usuario **«Realizalo»**: reanudación de pendientes, no reducción de aceptación
ni extensión de cuotas/plazos. main fuente exacto
`352f3bd6f42c89929bb37006c04385a9492d3031`,903blobs no-Markdown aún iguales al snapshot probado.
El permiso histórico625f5903§5/§6 y handoff§5 separan builds independientes
de rollout/OAuth/piloto bloqueados por AMQP: se preparan dos solicitudes nuevas,
**una por imagen** por el delta ejecutable integrado, no repetición de cb63260.
Gateway y Sheets worker solamente; API/otras imágenes intactas. Connectedrepo,
VERIFIED, timeout600s por build, sin resubmit, sin Docker local ni uploadcheckout.
Sin pullVM/deploy mientras AMQP no pase.

| ID previsto | Target | Límite | Estado inicial |
| --- | --- | --- | --- |
| `BUILD-sheets-worker-20261005T214213Z` | Sheets worker/source352f3bd6 | 1 solicitud/1imagen,600s | PREPARADO,0solicitudes |
| `BUILD-gateway-20261005T214213Z` | gateway/source352f3bd6 | 1 solicitud/1imagen,600s | PREPARADO,0solicitudes |
| AMQP-CONFIG-INSPECT-1 | único worker aprobado/VM existente | 1SSH/1exec,60s inspección/5min total,0red/0mutaciones | SOLICITADO, no recibido/no iniciado |

La excepción nueva solicitada es únicamente presencia/validez estructural de
`RABBITMQ_URL`/`RABBITMQ_MANAGEMENT_URL`, sin valores ni reparación. La anterior
AMQP-REPEAT-1 queda agotada y no se reutiliza; esta inspección tampoco autoriza
posterior GET de topología, conexiones, publish o cambio de configuración.
Especialista AMQP prepara tool+tests/informe nuevos con lista cerrada propia;
coordinador conserva ledger/Git/build/producción. No modifica informes originales.

**Inicio `BUILD-sheets-worker-20261005T214213Z`:** 2026-10-05T21:42:43.852227+00:00; 1solicitud iniciada,
source352f3bd6/connectedrepo/VERIFIED/1imagen. Sin resubmit; ID/resultado
se registrarán tras respuesta del servicio. Meli0/Management0/VMpull0/deploy0.

**Resultado `BUILD-sheets-worker-20261005T214213Z`:** SUCCESS/VERIFIED, buildID `4a4c14a8-bb83-4aab-87f6-b1bb2be1389d`,
source `352f3bd6f42c89929bb37006c04385a9492d3031`/connectedrepo exactos y verificador canónicoPASS.
Imagen `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:69d9da8d5e57c93868844349c489b33d0bf743612e718616d282a7ff6fe64a79`. Tiempos CloudBuild 2026-10-05T21:42:45.448501060Z→2026-10-05T21:43:46.958710Z;
1solicitud consumida/sinresubmit. No pullVM/deploy ni aceptación productiva.

**Inicio `BUILD-gateway-20261005T214213Z`:** 2026-10-05T21:45:30.958707+00:00;1solicitud iniciada,
source352f3bd6/connectedrepo/VERIFIED/1imagen. Sin resubmit, VMpull0/deploy0.

**Resultado `BUILD-gateway-20261005T214213Z`:** SUCCESS/VERIFIED, buildID `86be40be-95d9-4e56-b1b2-f2282c495e89`,
source `352f3bd6f42c89929bb37006c04385a9492d3031`/connectedrepo exactos y verificador canónicoPASS.
Imagen `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:866dca4ecab51600f50e249d21ae3615e803bc803a8f27fdae1052371130e28a`. Tiempos CloudBuild 2026-10-05T21:45:32.695976858Z→2026-10-05T21:46:23.762203Z.
Dos solicitudes nuevas consumidas, una porservicio, ceroresubmit; noAPIbuild.
VMpull0/deploy0/OAuth0/piloto0/Management0/Meli0. Pins son preparación, no runtime.

### Entrega AMQP configuración y congelación — 2026-10-05T21:55:42.013483+00:00

AMQP confirmó **«ENTREGADO; NO SIGO MODIFICANDO»**. Ownership4paths
devuelto,4hashesPASS y binding inspector final/embedding supervisor verificado.
Lista exacta: privados `amqp-config-inspection-20261005/config_inspection.py`,
`config_supervisor.py`, `test_config_inspection.py`, más
[su informe propio](zelerdata-historico-amqp-config-informe.md).
72unittestofflinePASS/0SKIP (45+27), ruff/formato/mypy3PASS. RED de recibo
source/motivo contradictorio preservado; no red/puertos/Mongo/Docker/producción
ni Git mutante por especialista. Originales intactos.

Inspector SHA256 `1550e7cc75915a34c31e66c8e441b68091af65054c40ceb7cceb471a9a5760e4`;
supervisor SHA256 `eb9489b8be679c6318c2356ad02a7cc4d7d20ab0c7bed777c4192b73588c110b`;
informe recibido SHA256 `205aa494ebc057c38405f5eabfbfe72d099f88fc1e5cc8b2df4cfcf45d3ff045`.
No cambiaron después del cese. AST3.9 acredita sintaxis, no runtimehost ni salud.

Coordinador preparó límites del caller **130s+5s cleanup de su propio grupo de
procesos local**, más supervisor150s: máximo285s incluso con inicio SSH tardío,
dentro del techo300s. Sin retry. Este caller todavía NO se ejecutó.
**AMQP-CONFIG-INSPECT-1 continúa SOLICITADO/NO recibido/0intentos.**
No tomar opción preseleccionada como permiso. Una respuesta configuraciónválida
no autoriza otra lecturaHTTP, ni cierra topología/entrega real.
Todos los escritores detenidos; solo publicación documental del coordinador
queda por cerrar. No nuevos checks generales/builds por este delta doc-only.

### Autorización AMQP recibida — 2026-10-05T22:02:00.522495+00:00

Usuario: **«Sí te autorizo la inspeccion AMQP que necesitas, incluso si necesitas
ampliarla»**. AMQP-CONFIG-INSPECT-1 queda AUTORIZADA:1SSH/1exec toolfrozen/
60sinspect/5mintotal/0Management/AMQP/Meli/mutations. No se reutiliza oldrepeat1.
La ampliación se limita a inspección necesaria de sololectura, con STOP de cada
operación fallida y causa/tooling offline identificado antes de otro intento.
Si se requiere lectura Management posterior, conservar10colas/3exchanges y
≤23GET/60sread/5mintotal, sin endpoint/credencial fallback ni retry. Registrar
ID/límite/consumo real antes/después. No es permiso de reparar/declarar/publish/
ACK/configmutations/credrotación/IAM/recursos/Full/Meli o ampliar piloto.
Los demás permisos condicionales vigentes no se vuelven a pedir.

**Inicio AMQP-CONFIG-INSPECT-1:** 2026-10-05T22:02:50.859067+00:00,autoridad recibida/1operación,
1SSH/1execmáximo/hashsupeb9489b8be67,0Management/AMQP/Meli/
mutations,130scaller+cleanup5/remote150/300total, STOP sinretry.

**Resultado AMQP-CONFIG-INSPECT-1:** 2026-10-05T22:02:50.859067+00:00→2026-10-05T22:02:57.207586+00:00,
6.348s/SSHexit2/`management_explicit_invalid`/STOP. Identity/digest
workerPASS e inspectoriniciado; brokerpresente/nonempty yManagementpresente/
nonempty,sourceexplicit. No se imprimieron valores.0Management/AMQP/Meli/
mutations.1operaciónconsumida/no retryigual; descarta faltaManagement, no prueba
credenciales/conectividad/causa404. Recibo SHA256
`38173791b822093c9e03488f4783a9a6592668653a71e711ed9bc9453b1a1d81`.

Ampliación necesaria bajo autoridad recibida: preparar offline discriminación
de regla estructural exacta con outputs fijos/booleanos y0red, no volvera ejecutar
esta herramientaigual. Mantener ledger separado y STOP; ningún cambio deenv/
servicios/colas niMeli. Como máximo una posterior lecturaManagement≤23GET/60s/
5min, solo si destino/config legítimos demostrados y toolcorregido offlineGREEN;
no fallback deURL/credenciales ni cadenas de probes fallidos. Rollout siguecerrado.

**Inicio AMQP-SHAPE-INSPECT-1:** 2026-10-05T22:13:56.423078+00:00;ampliaciónreadonlynecesaria aprobada,
1SSH/1exec shape56offline/hashe2835a65c4c0, workerold79f, Management0/AMQP0/
Meli0/mutations0,60sinspect/300total,STOP/sinretry. Configagregado anterior
no se repite; este tool distingue regla específica. MetadataCUOTASpreparación
local separada4paths/fakes aislados; ningúnotro agenteopera producción.

**Resultado AMQP-SHAPE-INSPECT-1:** 2026-10-05T22:13:56.423078+00:00→2026-10-05T22:14:01.076905+00:00,
4.654s/exit2/`management_userinfo_forbidden`/STOP.0Management/
AMQP/Meli/mutations;oldworkeridentity/digestPASS. Parse/port/host/transport
permitidos, sinquery/fragment/apiDuplicate/dotsegment,placeholderfalse.
CloudAMQPbrokertrue ycredencialesuserinfoigualesalbrokertrue (solo booleanos,
ningúnvalor). Recibo SHA256 `b060cff219abb680cfb1e8afdfc3d286c8072dd086737e89fe47d03f5088d98f`.
Este rechazo distinguecausaactual, no demuestraexactamente404histórico.

Próxima preparación mínima: adaptar SOLO argumentos privados enmemoria del
reader frozen, retirandouserinfo y conservandoauthority/path/transport exactos,
usando BasicAuthbroker que yasecomparóigual. Revalidarformas antesHTTP enruntime,
0envwrites/0configpersistente, nootroendpoint/credentialprobe. TDDoffline y
callerfrozen antesúnicalecturaManagement≤23GET/60sread/5mintotal bajo ampliación
recibida. Nada autorizaAMQPpub/declaración/ACK niMeli/Full. Registry14/datos/jobs/
presupuestos/plazos intactos. Images352fVERIFIEDno requierenrebuildporOPSprivados.

**Inicio AMQP-MGMT-READ-2:** 2026-10-05T22:35:08.879507+00:00;ampliación necesaria aprobada,1SSH/1exec,
reader30offline+calidad3PASS/4hashesbindingPASS, normalizedsource4d391872cc8c,
supervisorf4fc93d91690. SOLOuserinfoseparadoinmemoria/credigual/sametarget,
canonoriginalintacto. ≤23ManagementGET/60sread/4sreq/64KiB/cleanup5/300total;
0AMQPconnections/mutations/Meli/Full. STOPprimererror/noretry/nofallback;
registrarconsumo real, noinferir23ejecutados deltecho. OtroswriterssoloCUOTAS
correcciónannotations/focusedprivadoaislado, sinprod ni suitegeneral.

**Resultado AMQP-MGMT-READ-2:** 2026-10-05T22:35:08.879507+00:00→2026-10-05T22:35:15.330999+00:00,
6.451s/exit2/`queue_policy_requires_review`/STOP.1GET iniciado,
1HTTP200 recibido,1cuerpo completo2315bytes;exacto `/api/queues/{vhost}/zeler.sheets.events`,
sinhost/vhostreal. Normalizaciónuserinfo/sametargetPASS;cleanupErrornull.
NingúnsegundoGET/retry/fallback.0Meli/AMQPconnections/mutations.
Topología/confirmación/tiempos NO acreditados. Recibo SHA256
`e5c8267d180ced67db8b89b5a42cd195008d684928353b7529da186be0428e5d`.

Ampliación necesaria expresamente recibida delusuario: revisarla política real
de ESA cola con UNGET/MISMOtarget, tooloffline antesproducción, outputkeys
públicas/enum/números ysin nombres/valores sensibles. Namedpolicy/HA/lazy podrían
ser benignos, NO asumirlo; lifecycle/TTL/DLX/maxlen/overflow/deliverylimit/unknown
conservan gatecerrado. No aplicar/eliminarpolíticas. Si se demuestra benigno,
preparar toolfull23GET con revisión explícita antesotraejecución; máximo25GET
Management acumulados deltramo ampliado (1yausado+1policyreview+23seleccionados),
no resetear consumoanterior. Las ventanas4srequest/60sread/64KiB/cleanup5/300total
se conservan poroperación; Meli2500/90min/mismoUTC yFull0 NOse amplían.

**Inicio SCHEMA-METADATA-1:** 2026-10-05T22:42:42.064733+00:00;preflightseguridadrolloutcondicionalvigente,
1SSH/1APIexec old3f7/sourcef5f48d429c18/sup7abb8eeefa1c,
35focused+ruff/format/mypy3PASS/4hashes. SolohelloPRIMARY+listCollections3names,
≤2comandosexplícitos/sindocumentqueries/writes/getMore;0Management/Meli/AMQP.
Lectura55s/remote120/caller130+groupcleanup5/300total; noapply/collMod/repair.
Rs019PASS anteriorNOinstalavalidators; esta lectura obtienecompatibilidadreal.

**Resultado SCHEMA-METADATA-1:** 2026-10-05T22:42:42.064733+00:00→2026-10-05T22:42:50.067184+00:00,
8.002s/SSHexit0/PASS/PRIMARYtrue,APIold3f7identity+digesttrue.
2comandosexplícitosiniciados/completados,cleanupclosed,0documentqueries/writes/
Management/Meli/AMQP. Plans:collectionexistente sinvalidator,camposwork/work_sent
compatibles inequívocamente. Claims+sync:validatorsSHA localespermisivosexactos
(`f2358aba...`/`a8e49386...`), strict/errorpresente yhistory_dispatch_fenceallowed.
Noapply/collMod/repair. GateMongoantespull cerradoPASS.
Recibo SHA256 `83131d993581c72e6a33a1a3213ff26e5b15c870a083d067e742486bfe7fba43`.

Calidadmetadatafinal35focused/ruff/formato/mypy3PASS,sourcef5f48d42/sup7abb8eee.
Fallo146annotationsoriginal preservado ycorregido porownerantesexec; no se
redujeronchecks ni se usaronbytesprevios. Rs019 demuestraCASsinvalidators;
esta metadata actual esprueba separada decompatibilidadinstalada,no valida
documentos existentes ni aceptación delpiloto.

**Inicio AMQP-POLICY-INSPECT-1:** 2026-10-05T22:54:06.230713+00:00;UNGETmismo configuredtargetevents para
review efectivo, fuentef793c6592486/supc691407e97a9,
29offline+calidad3+4hashesbindingPASS/ownercesó. Autoridadampliarnecesaria,
cap1GET4s/60sread/64KiB/cleanup5/300total; agregadolímite25(1previoyausado),
0Meli/AMQP/mutations, nopolicychange/norelaxfullreader. STOP/sinretry.

**Resultado AMQP-POLICY-INSPECT-1:** 2026-10-05T22:54:06.230713+00:00→2026-10-05T22:54:12.019462+00:00,
5.788s/exit2/`policy_requires_review`,1GETHTTP200/1complete,
0Meli/AMQPconnections/mutations. Policy+operatorpresentes,nombresnoimpresos;
effective exact `expires=2419200000` (28d),`max-length=10000`,
`max-length-bytes=1073741824` (1GiB),unknownkeys0. SinTTL/DLX/overflow/delivery
limit enlos effectivecampos observados. ArgTTL/DLXesperadosPASS,classic,
consumers1/ready0/unacked0. No afirma benignidadglobal ni delivery/timing.
Recibo SHA256 `88e3a42c64a4335189130bef855ff7e203b99bc6639d79ab9c9c2c17e1b70867`.
AgregadoManagementactual2GET deltramo ampliado,cap25,no23lecturaciegarepetida.

STOPrespectado: sinmodificarpolicy/colas/config/capacidad; reader23 original
conservadoconservador. Evaluar criteriomínimo deheadroom/expiry con docs primarias
y alcance cerrado;2500GET no acotan número de mensajesentrantes. No pedir
otra vezpermisoscondicionales de piloto/despliegue, pero tampoco usar inspección
comoautorización de repairbroker. MongoactualcompatiblePASS/2imagesVERIFIED
son pruebas separadas,no sustituyen este gate.

**Inicio AMQP-REVIEWED-READ-1:** 2026-10-05T23:17:49.037532+00:00;1round23GET10queues/3exchanges bajoampliación
cap25agregado(2yausados);source816e2c4511bf/sup460cb46d78f6,
20offline+calidad3/4hashesfrozen/ownercesó. ExcepciónSOLOtupleoperator3valores/tipos
exactos probados;policiesREALESguardadasenevidencia,nopolicyborrado ni fakeabsencia.
Structuraltopo puedeverificarse,pilotadmission/noLoss/ingressflagsSIEMPREfalse,
rolloutNOautorizadoporresultado.0Meli/AMQPconn/mutations,4s/60s/64KiB/cleanup5/
300total,STOPprimererror/sinretry/fallback,noscopeextra.

**Resultado AMQP-REVIEWED-READ-1:** 2026-10-05T23:17:49.037532+00:00→2026-10-05T23:17:55.394376+00:00,
6.357s/exit2/`management_http_404` en request11 metadata
`zeler.sheets.claims.retry.1s`, ruta `/api/queues/{vhost}/zeler.sheets.claims.retry.1s`.
10GET anteriores200/completos (5colasmetadata+bindings),11iniciados/11headers/
10bodiescompletos. STOPsinrequest12/retry/fallback;0Meli/AMQPconn/mutations,
cleanupnull. AgregadoManagementdeltramo13GETiniciados/13responses/12completed
de techo25;unused no se consume automáticamente.
Policieseffectiveexacttuple preservadas,byte-ready0 exceptoeventsDLQ71411;
noingress/loss/admissionproof. TopologíaglobalFALSE, no rollout/pilot.
Recibo SHA256 `4ba45b9e3cf02a790d8c82bb386a8751624fe44325d4d0fdbde0ade87677c277`.

No concluirausenciacola global/confundirHTTP404coninconsistenciadata. Examinar
localmentecontrato1s delruntime vs expectativahelper antesdecidirrepair
concreto; no declarar/crearcolasbajopermisoinspección. Preservarcampos/estado
y límites previos, no mas rondas fallidas reetiquetadas.

### Reparación condicional solicitada — 2026-10-05T23:36:34.604033+00:00

Se solicitó únicamente crear retry1s si la comprobación pasiva confirma
NOT_FOUND: una declaración/una conexión/≤5min y hasta13GET de verificación
posterior. [Propuesta completa](zelerdata-historico-amqp-reparacion-propuesta.md).
**NO recibida / NO ejecutada.** Opción preseleccionada no es aprobación.
No re-solicitar permisos condicionalesbuild/rollout/piloto ni ampliar sus límites.

**Inicio AMQP-PASSIVE-CHECK-1:** 2026-10-05T23:44:15.011176+00:00;ampliaciónreadonly recibida,
1conexiónpropia/1canal/1Queue.DeclarepassiveTrue exactretry1s,
fuentef66b2070/sup7cbbaf30/4hashes+embedding+16fakesRootPASS/ownercesó.
Connect8/RPC4/cleanupTOTAL5/hard55exec65/remoto120/caller130+group5/300total;
0Management/Meli/Full/mutations. STOP/sinretry/creación/consume/publish/otrascolas.
Management13acumulados se preservan;esta conexión se registra aparte.

**Resultado AMQP-PASSIVE-CHECK-1:** 2026-10-05T23:44:15.011176+00:00→2026-10-05T23:44:21.389565+00:00,
6.378s/SSHexit2/STOP, broker404 `not_found`/existsFalse.
1conexión/1canal/1RPCpasivo iniciados y completados, identidad/digestold79fPASS.
0Management/Meli/Full/mutations deestaoperación;Managementacumulado13 intacto.
Cleanup reportó `tool_error`, owned_transport_closedFalse: no acreditar cierre
limpio por recibo. Pythontransitorio/SSH terminaron; eso no es confirmación
server-side del cierre. Preservar error/STOP, no repetir pasivo ni reparar.
Ausencia exacta confirmada por respuesta broker, no inferenciaHTTP404.
Recibo SHA256 `1dd9998c235674c76691aeb84d88ca1e220a1b07647319c6280faf36d22c25a7`.
Reparación condicional solicitada sigue NO recibida/NO ejecutada. Analizar
cleanup solo offline antes de preparar una herramienta futura; no más pruebas
contra producción para mejorar el recibo. No rollout/OAuth/piloto ni resetplazos.

### Reparación retry1s autorizada — 2026-10-06T00:10:46.561432+00:00

Usuario: **«Bien, resuelve la cola de reintento que hace falta, te autorizo lo
que necesites»**. Autoridad recibida para la reparación puntual propuesta:
una declaración activa compatible retry1s/una conexión/≤5min y hasta13GET
posteriores del inventario pendiente. Sin nueva comprobación pasiva/reintentos.
No otras colas/policies/drain/delete/consume/publish/testmessages/config/IAM/
capacidad ni datos. Registro14/Full0/presupuestos/cutoff/checkpoints/plazos intactos.
El día UTC cambió: esto NO renueva la ventana ni habilita piloto con día/deadline
expirados. Cero Meli en esta reparación. No re-pedir permisos condicionales.

**Asignación nueva exacta — único escritor AMQP:**

1. `ROOT/amqp-retry1s-repair-20261006/repair.py`
2. `ROOT/amqp-retry1s-repair-20261006/repair_supervisor.py`
3. `ROOT/amqp-retry1s-repair-20261006/test_repair.py`
4. `docs/sheets/zelerdata-historico-amqp-reparacion-informe.md`

ROOT privado definido arriba. Entrega dual con acciones explícitas separadas:
`--repair-retry1s` declara únicamente el recurso compatible;
`--verify-remaining` soloGET13: cinco retries metadata+bindings y tres exchanges.
No ejecutar verificación automáticamente tras mutación: Root decide por el recibo.
Fijar perfiles/identidad, preservar helpers/reports anteriores, resolver cleanup
solo offline con TDD y recibos honestos (close solicitado/waiter/cancelación/error,
no prueba remota inventada). AMQP prepara/no producción/Git/build/sharededits/
subagentes; CUOTAS congelado; Root único operador. No suite general necesaria
porque código publicado no cambia; tests locales privados fakes/transport aislado.
Estado: ASIGNADO/PREPARACIÓN, no operación productiva nueva iniciada.

**Inicio AMQP-RETRY1S-REPAIR-1:** 2026-10-06T00:35:27.499625+00:00; autoridadrepairrecibida6Oct,
1conexión/canal/Queue.Declareactivo exactretry1s durableTTL1000/DLXdefault/claims,
fuente8b34b81a/sup472c2398/4hashes+embedding+24fakesRootPASS/ownercesó.
0pasivo/Mgmt/Meli/Full;oneallowedentitydeclare,nootrasmutations.
8/4/cleanupTOTAL5/hard55exec65/remoto120/caller130+5/300total;STOP/sinretry.
SincreatedByUsinference/autoDelete/consume/publish/bind/policies/config/Data;
verificaciónhasta13GET esdecisiónposterior separada, noautomática.

**Resultado AMQP-RETRY1S-REPAIR-1:** 2026-10-06T00:35:27.499625+00:00→2026-10-06T00:35:35.019008+00:00,
7.519s/SSHexit2/`confirmed`/effectconfirmed_equivalent;
1conexión/1canal/1declaraciónactiva iniciados y completados/confirmados.
Vector exactdurableTTL1000/DLXdefault/routingclaims;created_by_usnull (concurrencia).
0Management/Meli/Full;nootrasmutaciones,pasivo/retry/publish/consume/policies.
Cleanup tool_error/waiter_stateerror/local_close_requestedTrue/remoteCloseFalse:
STOP del proceso, no cierre limpio acreditado ni segunda declaración.
Pythontransitorio y SSH terminaron. Recibo SHA256
`8801704c458cab51674fde029211913c8ba6b871dcb2498c54a3c747f301f6a9`.

**Decisión separada del coordinador:** la declaración compatible está confirmada,
no hay incertidumbre de ese RPC. El fallo de cleanup permanece registrado;
no se intenta mejorarlo con otra conexión AMQP. Ejecutar solamente la verificación
Management hasta13GET ya aprobada, como operación distinta de sololectura para
comprobar el recurso. No encadenado automático, no retry de mutación ni nueva
AMQP; STOPprimererror de esa lectura. No afirmar cleanupserver-side o admisión.
Consumo anterior13 se conserva;scope nuevo≤13, máximo conocido del tramo≤26,
no reinicio del antiguo techo25 ni permisoMeli/Full/pilot/window nuevo.

**Inicio AMQP-RETRY1S-VERIFY-1:** 2026-10-06T00:36:45.250555+00:00;verificaciónreadonly aprobada
separada de declaraciónconfirmada/cleanupfallido preservado;sup472c2398/
source8b34b81a/ownercongelado.≤13GET5retriesmetadata+bindings/3exchanges,
4sreq/60sread/64KiB/cleanup5/hard80exec95/remoto150/caller130+5/300total.
0nuevaAMQP/mutations/Meli/Full,STOPprimererror/noretry/nofallback.
13GETpreviosintactos,scopeextra13explicit no globaltopology/admissionclaim.

**Resultado AMQP-RETRY1S-VERIFY-1:** 2026-10-06T00:36:45.250555+00:00→2026-10-06T00:36:50.813547+00:00,
5.563s/SSHexit2/STOP management_http_404 request3metadata5s.
Retry1smetadata+defaultbindingHTTP200 completos: TTL/DLX/identidad/lifecycle/counts
compatibles con el vector aprobado;operatorcaps reales exactos preservados.
3GETiniciados/3headers/2completos,cleanupnull,0AMQP/mutations/Meli/Full.
No request4/retry/fallback. Acumulado conocidoManagement16iniciados/16headers/
14completos;old13 sepreserva. Subset/global/admissionfalse. Recibo SHA256
`c4fec2305f1d8d269789ee072e7a5a2d9369231f66191b79fe7b16bc541b9488`.
HTTP4045s NO prueba ausencia; 1s sí quedó reparada/verificada.

### Continuación necesaria del mismo mecanismo autorizado

«Te autorizo lo que necesites» cubre resolver los buckets requeridos restantes
del contrato de retries, no otros recursos del broker ni piloto. Ante el nuevo
4045s, asegurar **solo5s/30s/2m/10m** por declaraciones compatibles (sin afirmar
ausencia o autoría), TTL5000/30000/120000/600000, mismoDLXdefault/routingclaims.
Una conexión/canal y máximo4RPCactivos secuenciales, STOPprimeroerror sin retry.
No nuevo pasivo, no duplicar declaración1s. Leer después solo4metadata+bindings
y3exchanges=≤11GET separados. Esta lectura ocurre tras cambio confirmado, no
repetición ciega del404. Máximo conocido nuevo16+11=27, countersanteriores
intactos; NO nuevo presupuestoMeli/Full ni ventana/checkpoint/plazo.

**Asignación nueva cerrada — único escritor AMQP:**

1. `ROOT/amqp-retries-restantes-20261006/ensure_retries.py`
2. `ROOT/amqp-retries-restantes-20261006/ensure_supervisor.py`
3. `ROOT/amqp-retries-restantes-20261006/test_ensure_retries.py`
4. `docs/sheets/zelerdata-historico-amqp-retries-restantes-informe.md`

Root conserva proposal/ledger/Git/producción. Entrega localTDD≤20fakes+quality3/
closedreceipts/hashes/cese;helpersanterioresintactos. Active8/4/4cadaRPC/cleanup5/
hard55exec65remote120caller130+5/300;verify11GET4s/60read/64KiB/cleanup5/
hard80exec95remote150caller130+5/300. No suitegeneral/builds ni otras áreas.

**Inicio AMQP-RETRIES-ENSURE-1:** 2026-10-06T00:47:41.947702+00:00;samecanonicalnecessaryrepairauthorized,
source23b3a537/supf108d058/4hashes+embedding+20fakesRootPASS/ownercesó.
ONEconn/channel≤4declfixed5s30s2m10mTTLoriginal/DLXdefault/claims;
0Management/Meli/Full/othermutations/passive/new1sdecl;8/4/RPC4each/cleanup5/
hard55exec65remote120/root130+5/300,STOPfirsterror/noretry.

**Resultado AMQP-RETRIES-ENSURE-1:** 2026-10-06T00:47:41.947702+00:00→2026-10-06T00:47:47.888662+00:00,
5.941s/SSHexit2,confirmed_equivalent4/4RPCreply+confirmed,
ONEconn/channel;fixed5s30s2m10mTTLoriginal/DLXdefaultclaims/createdByUsnull.
0Management/Meli/Full/otrasmutaciones/pasivo/new1sdecl/publish/consume/policies.
Cleanup tool_error/waitererror/localCloseRequestedTrue/remoteFalse → STOPproceso;
PythonSSHterminados,no cleancleanupclaim. Recibo SHA256
`e79899ab97ab74fa1a9bc98c406aa42169be9f9a491223dffbf272f307412894`. No otra declaración.

DecisiónRootseparada:4RPCcompatiblesconfirmados, no incertidumbre de ese efecto;
conservarcleanuperror,no nuevaAMQP para mejorarlo. Únicamente readback11GET
ya previsto del mismo mecanismo, sinmutaciones ni encadenadoautomático.
16Managementpreviosintactos/max27,noMeli/windowreset,STOPfirsterror.

**Inicio AMQP-RETRIES-VERIFY-1:** 2026-10-06T00:48:08.794286+00:00;samecanonicalnecessaryrepairauthorized,
source23b3a537/supf108d058/4hashes+embedding+20fakesRootPASS/ownercesó.
Separatereadonlyafter4confirmed/cleanupfailurepreserved;≤11GET4retrymetadata+bindings/3exchanges,
0newAMQP/mutations/Meli/Full;4s/60read/64KiB/cleanup5/hard80exec95remote150/root130+5/300.
Prev16knownMgmt retained/max27,STOPfirsterror/noretry/no globaladmissionclaim.

**Resultado AMQP-RETRIES-VERIFY-1:** 2026-10-06T00:48:08.794286+00:00→2026-10-06T00:48:14.507921+00:00,
5.713s/SSHexit0/PASS,11GETiniciados/headers/completosHTTP200,
cleanupnull,selected_structure_verifiedTrue. Cuatro retry5s30s2m10mmetadata+
defaultbindingsy3exchangesPASS;TTL5000/30000/120000/600000/DLXdefaultclaims,
0ready/unacked/consumers/bytesready enlos4. Operatorcaps exactos reales retenidos.
0AMQP/mutations/Meli/Full;no retry/fallback. TopologíaGLOBALfresh/publish/timing/
ingress/noLoss/admissionSIEMPREfalse; evidencia anterior1s/prefix separada.
KnownexpandedManagement27started27headers25bodiescompleted (old13+3+11),
no reset. Activas de reparación:2conexiones/canales,5RPCconfirmados (1+4),
createdByUsunknown,cleanupdeAMBAS tool_error/waitererrorpreservado;sinAMQPretries.
Recibo SHA256 `7b3274f8656dc6ace50d4fbafed84cb5f5a8668bca24f73d8e516ec2b514ff97`.

Mecanismo de retries requerido disponible y estructuralmente verificado por
lecturas fechadas; no proofde entrega real/90min/OAuth/piloto/globalacceptance.
Registry14/6routingkeys/datos/jobs/counters/cutoff/checkpoints/plazos/Full0 intactos.
No builds/pulls/deploys nuevos;guard/workerimage source352 listos,no servidos.

Incidente localreportado:GREEN-1.log se redirigió alROOTprivado porerror,
SHA385a2ef4820a8867ee9edaa7426f06293d9a0a091368e88d2c1758080db6885e/2969B,
birth6Oct00:43:11UTC;preservado desdeaviso,copia propia. Sinbaseline previo,
no afirmarbytespreviospreservados.28previousdeliveryhashes/903source intactos.

## Goal de terminación reanudado — 2026-10-06T00:55:29.193559+00:00

Objetivo explícito del usuario: **«termina zelerdata, autorizo todo»**. Goal activo,
sin presupuesto de tokens. Turno previo clasificado **PROGRESS**: cinco retries
restaurados/lecturas verificadas y dos unidades documentales publicadas. No equivale
a aceptación global. Checkoutmain0fc0c952 limpio confirmado al iniciar este goal.

La autoridad amplia permite operaciones necesarias del cierre seleccionado,
con scopes/límites definidos antes de cada llamada, sin volver a pedir permisos
condicionales ya vigentes. Mantener Full excluido/registro14/routingkeys6,
datos/jobs/cutoff/checkpoints/consumos/plazos existentes. No borrar negocio,
resetear cuotas o bypassOAuth por «todo». Primero inspeccionar saldos/estado
canónicos; no inventar2500 libres ni renovar un deadline vencido.

### Encargos independientes exactos de auditoría

| Especialista | Único archivo escritor | Encargo / dependencia / estado |
| --- | --- | --- |
| CUOTAS | `docs/sheets/zelerdata-historico-cuotas-aceptacion-informe.md` | Auditoría local de requisitos/gates/operador y propuesta de lectura de estado canónico sanitizado. No producción/código/shared. ASIGNADO. |
| AMQP | `docs/sheets/zelerdata-historico-amqp-runtime-gates-informe.md` | Auditoría local de gates AMQP/rollout/procedimiento acotado para pruebas reales aisladas si faltan. No producción/código/shared. ASIGNADO. |

Ambos: sin nuevos agentes/Git/build/testsuite/otras áreas. Leen contratos/runbooks
pertinentes, conservan todos los informes/helper/logs anteriores y entregan matriz
con evidencia directa requerida (no intención o testgreen genérico). Root único
writer de documentos centrales/config/deps/lockfiles y único operador productivo.
No editar archivos de especialistas antes de entrega/cese. Cualquier herramienta
nueva recibirá lista de paths exclusiva después de evaluar estas propuestas.

**Inicio RUNTIME-CAPACITY-HEALTH-1:** 2026-10-06T00:58:12.833323+00:00;nuevo goal broadnecessaryauthorization,
READONLY preflightdry-run/hashinstalled+oldoverride,dfbytes/inodes/Mongomount/
RAM/Dockerusage/selected6healthOOMrestartpins.0pull/restart/writes/Mongo/Meli.
Remote90/caller120+owncleanup5/300total,STOPfirsterror/noretry/nocleanup.

**Resultado RUNTIME-CAPACITY-HEALTH-1:** 2026-10-06T00:58:12.833323+00:00→2026-10-06T00:58:18.377492+00:00,
5.544s/SSHexit1/STOPporGoTemplate `.State.Health` ausente enCaddy,
causareconocidaporwhiteliststderr sinvolcarerrores/valores. No IAP/sudoauth/mismatch.
Preflightsource06edd/oldoverrideb7b85PASS ydryrunPASS/root35688504KiBfree/
6233537inodes;MongoMountedseparateext4free46349072KiB/3276153inodes.
RAMtotal4007000KiB/avail907700KiB/swap0;DockerImages12active11size5.57GB,
containers11allactive,volumes8active3,size38.36KiB. Gateway7054/API3f7/worker79f/
Mongo43fd Runninghealthy/OOMfalse/restarts0;Caddy/bootstrapaúnsinhealthproof.
0pull/writes/Mongo/Meli/cleanup/restart. No repetircollectorentero: validarfmt
offline ylecturaspuntuales2componentes restantes con guardmissingHealth.
Recibo SHA256 `83a6013efe28541113a5bd9bc1b9e3d7441b2351c9454ed0a9d3ab9ce7c5d368`.

### Prueba de broker aislada seleccionada — 2026-10-06T01:04:22.477426+00:00

Root recibe informe AMQPruntimegates SHA4110eda2...,sin modificaciones del agente.
Acepta preparar la prueba temporal§4 bajo la autoridad del goal completo; aún
NO ejecutada. Scope exacto:1conexión no robusta/1canal confirmado;2colas
server-named exclusivas auto-delete/no durable/x-expires60000 (delayTTL30000,
DLXdefaultdestino propio),2GETmetadata propios yguards efectivosantespublish;
1publishmandatory nonce propio≤64B/wireexpiry5000 via timedelta,3basic.getmáximo
soloDestino(temprano<5s/después8s/trasACK),1ACK soloownnonce+death-expired verificado,
≤2delete propios if_empty/if_unused.0businesspublish/consume/ACK/colas/DB/Meli/Full.
Connect8/channel4/decl4each/confirm4/work60/cleanupTOTAL5/hard80exec95remote150/
caller130+group5/300total;STOPprimererror sinretry,cleanup soloowned. Nombres/body/
nonce/headers ycredencialesnoimpresos. Cierre TCP yretirada decolas/proofsseparados;
no fabricar cleanSSL ni handlerWAIT352/globaldurability/noLoss/admission.

Management:27previos+fresh23≤50+ownmetadata2≤52;noreset viejo23desconocidoaparte.
Nueva lectura fresh23 necesaria tras cambio broker/nuevogoal, mismafuente frozen,
no retry ciego del404. DosGETprobe no se ejecutan si no pasan gates previos.

**Nueva escritura exclusiva AMQP:**

1. `ROOT/amqp-isolated-delay-probe-20261006/probe.py`
2. `ROOT/amqp-isolated-delay-probe-20261006/probe_supervisor.py`
3. `ROOT/amqp-isolated-delay-probe-20261006/test_probe.py`
4. `docs/sheets/zelerdata-historico-amqp-probe-informe.md`

ROOT privado ya definido. TDD≤24fakes/callbacks/MockTransport,0sockets/Docker/Mongo;
calidad3/hashbinding/closedreceipts/cese antesRootprod. No agentes/Git/build/shared/
previousdeliverychanges, no nuevo research innecesario. Root único operador.

**Inicio RUNTIME-COMPONENTS-REST-1:** 2026-10-06T01:06:11.995972+00:00;SOLO2componentes pendientes+Dockerstats,
old.HealthTemplateRED/newindexGuard2GoFixturesGREEN/noNetwork;no rerunfullcollector.
Remote60/caller90+cleanup5/300,STOPfirsterror/noretry;0writes/pull/restart/Mongo/Meli.

**Resultado RUNTIME-COMPONENTS-REST-1:** 2026-10-06T01:06:11.995972+00:00→2026-10-06T01:06:18.166707+00:00,
6.171s/SSHexit0/PASS. Caddy8344running/OOMfalse/restart0 sinDockerhealthcheck
(healthnull,noinferirhealthyHTTP);bootstrap9806running/healthy/OOMfalse/restart0.
Memorysnapshotworker899.1MiB/API232MiB/gateway127MiB/Mongo609.9MiB/bootstrap58.2MiB;
bootstrappicoCPU33.54% observado/noinferircausa.0writes/DB/Meli/pull/restarts.
HealthmissingKeyrootcausereproducedRED andnewindexguard2fixturesGREENoffline.
No rerun wholecollector. Recibo SHA256 `e1367f510031483bcb3cbecc652d0d934987f3100c67492e9490f270d0c7d561`.

### Estado canónico antes de OAuth/prepare — asignación nueva 2026-10-06T01:14:45.200766+00:00

Root recibió/cotejó auditoría CUOTAS SHA4e3d7e08...;cese confirmado. Riesgoslegacy/
bootstrap se discriminan por lectura real, no asumirbugproductivo ni tocarplanes.
Preparar lectura del informe§2:ONEAPIexecold3f7/DBlegítimaVM,PRIMARY+≤11comandos
Mongo explícitos filtradosseller82,metadata limitada/proyectada,50sbody+cleanup5/
hard70exec85remote130caller140+5/300.0writes/Meli/AMQP/usercredentialcopy/logdump.
Cada aggregate devuelve UNdocumento resumen,batch1,cursorID0;no getMore.
Limitcap+1 detectatruncation⇒unknown/notglobalabsence;maxTimeMS4000 porlectura.
No snapshottransaccional afirmar;timestampsporgrupo+derivadetectada⇒STOPgates.

**Escritura exclusiva CUOTAS:**

1. `ROOT/pilot-state-audit-20261006/state_audit.py`
2. `ROOT/pilot-state-audit-20261006/state_supervisor.py`
3. `ROOT/pilot-state-audit-20261006/test_state_audit.py`
4. `docs/sheets/zelerdata-historico-cuotas-estado-informe.md`

ReusarAPI/runtimeDBfactory instaladas/hashbindingtypefix anterior, no cambiarla.
TDD≤28fakesoffline/resources aislados+calidad3+closedreceipt/hashes/ENTREGADOcese.
No agentes/prod/Git/build/previoushelper/report/sharededits. Rootprodagentúnico.
No `execution_enabled` ficticio/inicio=until−90min;missingcounter no0inventado.
Saldos aritméticos vs ejecutables y day/deadline/identity separar. Sin nuevos UUID,
manualupgrade/upsert/flagbypass ni reset por goalamplio. Condiciones pendientes.

**Inicio AMQP-GOAL-FRESH-1:** 2026-10-06T01:16:13.029383+00:00;nuevoestado trasrepair+nuevogoalauthority,
freshwhole23GET10colasmetadata/bindings3exch,mismo target/auth/816e2c45/460cb46d.
0AMQP/mutations/Meli;4s/60read/64KiB/cleanup5/hard80exec95remote150/root130+5/300.
Known27prev+≤23=50;noresetoldunknownhistory,pilotadmissionflagsfalse/STOPprimererror.

**Resultado AMQP-GOAL-FRESH-1:** 2026-10-06T01:16:13.029383+00:00→2026-10-06T01:16:18.703122+00:00,
5.673s/SSHexit0/fresh10colas+bindings3exchTopoPASS,23GETstartedheaderscomplete,
cleanupnull. Consumers1events/claims,0readyunacked enlive/delay/retries;
eventsDLQ315ready/71411B preservados,otros0. Capsexactreal3tuple/idleexpiryproofFalse.
KnownexpandedManagement50started50headers48bodiescompletos;noresetoldunknown.
0AMQP/mutations/Meli/Full;publish/timing/ingress/noLoss/pilotadmissionFalse.
Recibo SHA256 `b0bf08e40f62ef8576d87afc06d67d60ebd9a9eef255aedca570be2d9573a273`.

### Asentamiento de metadata antes de prueba temporal

Probe original4hashes/embedding+24fakesRootPASS congelados/no ejecución.
APIinstalledbasic_get/ack signatures confirmadas,pero ningún guarantee de
estadísticasHTTP inmediatamente despuésDeclareOk. Documentaciónprimaria
RabbitMQManagement registra emisiónpor defecto cada5s;eso NO prueba valoractual.
Preparar variantecon esperaFIJA6s ENTRE DeclareOk yprimerGET,sinprobesprevios,
reintentos ni relajarcounts/policy/isolationshapes. Counts siguenexigidos0;
si6sno basta⇒STOPsinpublish,noLoop. Work60/hard80/total300 y2GETunchanged.
Originales intactos,nofailedproductionprobe ni otra ejecuciónpara pulido.

**Nuevo escritor AMQP,solo4paths:**

1. `ROOT/amqp-isolated-delay-probe-settled-20261006/probe_settled.py`
2. `ROOT/amqp-isolated-delay-probe-settled-20261006/probe_supervisor.py`
3. `ROOT/amqp-isolated-delay-probe-settled-20261006/test_probe_settled.py`
4. `docs/sheets/zelerdata-historico-amqp-probe-asentado-informe.md`

Wrapper fuenteprobe d49d...SHA-bound/ASTclosedoneinsertionfixedawaitsleep6,
ninguna otra semántica. TDD≤12fakes,quality3,old36hashespreserved,ceseRootbeforeprod.
No newagents/prod/Git/build/general/shared/othercasechanges. Primera llamada
productiva aúnNOiniciada;scopeisolated2GET+tempmsgs original se conserva.

**Inicio AMQP-ISOLATED-DELAY-PROBE-1:** 2026-10-06T01:32:05.444174+00:00;scopeRoot1:04/settle1:23/goalnecessaryauthority,
source2a17d39d/supf14a7f72/4hashbinding+10settled+24originalRootfakesPASS/ownercesó.
ONEownedconn/channelConfirmTrue,2servernamedexclusiveAutoD60000ms queues/
DelayTTL30000/ownDestdefaultDLX;settle6→2ownMgmtpolicyguard→ONEownNoncePub
mandatorywire5000→3ownDestGet/OWNACK1→≤2ownemptyunuseddelete. No business/
foreignMsgs/colas/data/DB/Meli/Full;knownMgmt50+≤2=52. Work60cleanupTOTAL5/
hard80exec95remote150caller130+group5/300;STOPprimererror/noretry/fallback.

**Resultado AMQP-ISOLATED-DELAY-PROBE-1:** 2026-10-06T01:32:05.444174+00:00→2026-10-06T01:32:18.373397+00:00,
12.929s/SSHexit2/policy_invalid/STOPbeforepublish. Conn/channel1/twoownqueues
declared,1ownmetadataGETcompleted/HTTPresponse1;0pub/get/ACK/business/Meli/Mongo.
BothownQueueDeleteconfirmed2 (ifempty/unused);resourceDeletionTrue.
CleanupTCPssl_error/waitererror/localCloseRequestedTrue/remoteFalse,HTTPcleannone.
No assertionbroker/timingpassed, no secondprobe/retry. KnownMgmt51headers51/
49completeBodies;originaloldunknownpreserved. Endpointlabels only,qnames/nonce/body
notprinted. Recibo SHA256 `0fcc63b5390e4ca38473e9e6c4b1335ded843b9adbae5e2fc82afb0a4bd8a705`.

Nextnecessarydiagnosticundergoalauthority isREADONLYactualpolicydefinitions
forconfiguredvhost, notrecreatingfailedprobe to learnfields. Scope2GET(/policies
and/operator-policies),≤50entries/body64KiB/request4/read20/cleanup5/total300;
noAMQP/resource/publish/Meli/DB/policywrite. Recognizeddefinitionnumeric/enums/
matchclassification only,no policyname/rawpattern/host/vhost/URL/foreignpayload.
Unknownkeycount/notrawkeyvalues,syntheticamq.gen22charsmatch explicitnotactualQName.
Known51+≤2=53;notresetoldunusedbudgets.Missingmismatchcausepreserve/STOPnoFallback.

**NewexclusiveAMQPpaths:**
1. `ROOT/amqp-policy-definitions-20261006/policy_definitions.py`
2. `ROOT/amqp-policy-definitions-20261006/policy_supervisor.py`
3. `ROOT/amqp-policy-definitions-20261006/test_policy_definitions.py`
4. `docs/sheets/zelerdata-historico-amqp-politicas-temporales-informe.md`

TDD≤18fakes/Mock,no actualnetwork/DB/Docker/prod/otheragents;quality3/hashes/cese
beforeRootcalls. Allpreviousdeliveredprobereaders/reportserrorspreserved.

**Inicio GOAL-IMAGES-PROVENANCE-1:** 2026-10-06T01:39:27.166364+00:00;READONLYtrustedprojectnumber+2artifactprovenance+2builddescribe,
source352/2existingexactpins,5metadataCLIreads≤25s each,whole180/STOPno retries.
Localcanonicalverify-image outputsownnewmapfiles;0buildsubmit/download/deploy/VMmutation.

**Resultado GOAL-IMAGES-PROVENANCE-1:** 2026-10-06T01:39:27.166364+00:00→2026-10-06T01:39:35.639209+00:00,
8.473s/PASS/projectmetadata+2artifact+2build reads5;canonicalverify-image
source352/connectedrepo/project/subject/build/DigestPASS ambos. Worker69d9/build4a4c14a8,
gateway866d/build86be40be actualesretrievables;maps/metadata privatepreserved.
0buildresubmit/download/deploy,oldservedworker79f/gw7054notconfusedwithbuilds.
Recibo SHA256 `d9e6289a496df0c65da24046ef718bf2b7c15ae779634bf04bcf6de0224aff65`.

### Verificación Mongo real aislada de expresiones — 2026-10-06T01:49:15.477419+00:00

28fakes stateaudit no pruebanservidorMongo. RootcreaperfilColima NUEVO zeler-goal-audit-20261006-470b1fa4
CPU2/RAM2GiB/disk10GiB/nohostmounts/noSSHagent/noactivate/noSSHconfig/templatefalse,
paraMongo7oficialúnico/datosSINTÉTICOS/basepropia/loopbackpuertonuevo.
Perfilesoriginalesdefault+zelerdata-tests-20261002STOPPEDverificados,sepreservan,
contextactualcolimanosecambia. No Dockerbuild/GCP/prod/Meli/backupimport.
CleanupsoloIDs/volúmenes/perfilpropiosdespués,noprune. Registropropio privado.

**CUOTAS nueva integración enfocada (sin alterar entrega congelada):**

1. `ROOT/local-state-pipeline-verify-20261006/test_state_pipeline_mongo.py`
2. `docs/sheets/zelerdata-historico-cuotas-mongo-integracion-informe.md`

WriterCUOTASsoloestos2paths. Recursosdeprueba NUEVOS deRoot,receipt privado con
identidad/context/socketlocal/puertoloopback/basepropia;no usarenvironmentMONGO_URI
ni factoryproductiva. Solo datosSINTÉTICOS localMongo7; no importbackup/datareal,
no GCP/AMQP/HTTPprod/Git/build/suitegeneral. ≤4 escenarios reales: vacíos,
currentpolicy+bootstrapprotegido+saldoscounters/ledger,legacyprogresspreservado,
ycaps/deriva/invalidez si útil. Cadaaudit≤11reads/max4s;insertsfixture propiossolo
basepermitida. Verificarresultado real de las expresiones/cursor0/noGetMore y
salida noSecretRootMarker. Metadatafakes previosintactos; Sourceauditnoeditorial
cambios silenciosos. Fallo⇒entregaREDreal+propuestaRoot/norealDBfallback.
TargetRootreceipt esrequisito antes deejecutar;TDDharness canpreponline sinop.
Rootúnicocrea/retira contenedor/volúmenes/perfil,Writerreport/hash/cese.

**Inicio AMQP-POLICY-DEFINITIONS-1:** 2026-10-06T01:52:07.568392+00:00;readonlyDIFFERENTscopeafterprobeSTOP,
266b039a/ea854650/4hashbinding+17RootfakesPASS/ownercesó.2policyListsGETonly
configuredvhost/50TOTALrules/4req20read64KiB5cleanup/hard45exec60remote120/
root130+5/300;0AMQP/resources/pub/MeliMongo,writes,noproberetry.51prev+≤2=53.

**Resultado AMQP-POLICY-DEFINITIONS-1:** 2026-10-06T01:52:07.568392+00:00→2026-10-06T01:52:13.638279+00:00,
6.070s/SSHexit2/policy_regex_unsupported/STOP;ONEpoliciesGET200complete,
operatorGETNOejecutado (countnull).4policiesenlista,2resumidasantesSTOP.
Row1queuesprio−10 expires2419200000/matchrepresentativeFalse;row2queuesprio−9
{expires60000,max-length1000,message-ttl60000}/regexunsupported/matchnull.
Names/patternsvhostnotprinted/noactualQNameguarantee.0AMQP/mutations/MeliMongo,
HTTPcleanupnull. KnownMgmt52/52/50completedBodies. No retry/policychange/probe2.
Recibo SHA256 `15d76e125be3f97c9c36ad30dff7424eba53e37d6b7a0cfe77cd3bd7167b5995`.

ContinuarSOLOendpointoperator-policies queNOseleyó:1GETrestante delscope2.
No repetir/policies. Diagnosticreader NOevalúa regex:nonevalidatedmatchnull,
requiresReviewTrue/actualQueueVerifiedFalse/probeAuthorizedFalse;type/definition
guards y50entries/64KiB/4req/20read/cleanup5 permanecen. Regexmatchnoesnecesario
para obtenerdefinitions, no relajar un guard de aislamiento/publicación.

**NewexclusiveAMQP4paths:**
1. `ROOT/amqp-operator-policy-read-20261006/operator_policy.py`
2. `ROOT/amqp-operator-policy-read-20261006/operator_supervisor.py`
3. `ROOT/amqp-operator-policy-read-20261006/test_operator_policy.py`
4. `docs/sheets/zelerdata-historico-amqp-operator-informe.md`

≤10fakes/quality3/hash/cese,no sourcesprevias modificadas ni nueva prod/writes/
resources/agents/Git/build. Known52+≤1=53, sin reiniciarconsumo.

### RED real de auditoría canónica, corregir antes de prod — 2026-10-06T01:58:11.907708+00:00

Mongo7local real:empty1PASS/nonempty3FAIL. Aggregate retorna exactamente1resumen
pero cursorIDno0 con batchSize1; readerSTOPcursor_incomplete command2,0getMore/
mutacionesauditor/leaks,fixtures4fingerprintsintactos. Serverexpresiones no vacías
restantesaúnNOprobadas. Source4206 congelada NOseopera enproducción.
Correcciónmínima propuesta:batchSize2 SOLOpara que servidor detecteEOF;pipeline
sigue≤1docresultado,firstBatch≤1/cursorID0/noGetMoreobligatorios,11cmdlimitsintactos.
No es ampliación de consultas/budgets ni prueba productiva fallida repetida.

**CUOTAS nueva variante EOF,exact4writerpaths:**
1. `ROOT/pilot-state-audit-eof-20261006/state_audit_eof.py`
2. `ROOT/pilot-state-audit-eof-20261006/state_supervisor.py`
3. `ROOT/pilot-state-audit-eof-20261006/test_state_audit_eof.py`
4. `docs/sheets/zelerdata-historico-cuotas-estado-eof-informe.md`

Original4delivery4206/6384/91b5/3dec/logs preserved. WrapperSHA-boundAST only
batchSize1→2 parafixed10aggs;validateexactchange andallguards unchanged. ≤12fakes
RED/GREENstandardquality3/embedding/cese, then SAME4realcases withinOWNtestDB
fornonemptyexpressions/fingerprints/11reads/noGetMore. RootAPIprodattempt0.
No agents/prod/Git/build/shared/deps/oldsourcechanges; no newcasepolish.

**Inicio AMQP-OPERATOR-READ-1:** 2026-10-06T02:02:23.116148+00:00;ONLYremainingunattemptedoperatorGET,
42df6bde/a0bf7105/4hash+9Rootfakes/ownercesó;1GET/50rules4req20read64KiB
5cleanup45hard60exec120remote130caller+5/300;0AMQP/resources/pub/MeliMongo.
No/policiesrepeat/regexeval/probe2;known52+≤1=53,STOPfirsterror.

**Resultado AMQP-OPERATOR-READ-1:** 02:02:23.116148→02:02:27.081163UTC3.965s/SSHexit2.
Callerusóflagincorrecto --inspect-policy-definitions;supervisorfrozen exige
--inspect-operator-policy. Stdoutcerrado validadooffline:actionnull/readerStarted
False/explicit_action_required,0Dockerexec/Management/AMQP/Meli/Mongo.
Callerendoriginalmarca receiptinvalid ysepreserva;inspecciónofflineacreditaNOOP
anteCLIguard, no consumo delGETpendiente ni repetición de diagnóstico broker.
KnownMgmt permanece52;corregir SOLOcallerflag validadoantesúnicooperatorGETreal.
Nohost/prodtoolsourcechange/nofallback/retryblind.

**Inicio PILOT-CANONICAL-STATE-1:** 2026-10-06T02:05:11.729609+00:00;FIRSTprodauditAFTER4realMongo+12fakeRootPASS,
3f86e232/3ab036a2/4hashbinding/cese,ONEAPIold3f7execlegitDB PRIMARYhello+
10metadataaggsfiltered82,11explicitreads/50body4per5cleanup70hard85exec130remote
140caller+5/300;0getMore/docwrites/reset/MeliAMQP. EOFbatch2response≤1/cursor0.
No assumedbudget/enable/start;strictcountsunknown/STOPfirsterror/noretry/no OAuthyet.

**Resultado PILOT-CANONICAL-STATE-1:** 2026-10-06T02:05:11.729609+00:00→2026-10-06T02:05:18.660729+00:00,
6.931s/SSHexit2/known7reads7completed/PRIMARYtrue/API3f7identity+mountclear.
Account82active/ownerbindingpresent/authmetadatafresh;registry14exact/noFull/6keys.
PlanIDENTITYmatch butLEGACY policyMatchFalse/authorityFalse/stateunknown;existing
cutoff2026-09-24T05:36:28Z,scopes/canonicalbudget/counters/executionID/day/until
ABSENT/unknown⇒NO2500free/executable/cap/windowinference. Plan/ledgersubsetstable.
Bootstrap13:1succeededcheckpoints7+12failed(11checkpoint6/one0),no leases observed;
protectedexistingjobproven,currentOAuthselector mustpreserveit. Recoverycap1001
reached⇒lowerbound>=1001/unknowninventory,observedcompletedlegacyrows notglobal
absenceofactivejobs. STOPbefore sync/migration/runs/operations groups,no8thread.
0getMore/auditorwrites/MeliAMQP/OAuth/prepare/reset;cleanupclosed.
Recibo SHA256 `abd9250388a6b8ff2487944b97aeb22be121905ba038307eb5dde8100afeb4ff`.

Nextlocalwork:corelegacymigration mustpreservecutoff+existingcounter/progress
before normalOAuth;no manualplanupgrade. Targetedpresencequery forACTIVE recovery
cancloseisolation withoutredoarchive1001 scan;remaining4unreadgroups separately
scoped. Broadgoal permitsfixesnecessary,not deletingjobs/borrowingquotas.

### Encargo local por legacy REAL, antes de modificación compartida

CUOTAS únicowriter nuevo `docs/sheets/zelerdata-historico-cuotas-legacy-propuesta.md`.
Exploración acotada/propuesta sinedicionescore/gateway/test/prod/Git/build/agents:
admit_history_onboarding legacyupgrade debe preservar cutoffexistente ytodos
campos/counters/progress/checkpoints/leases,calendarboundsderivados sinrenewwindow,
idempotenciaconcurrente/CAS/attributionunknownfailclosed. Analizarseed/callback y
regresiones exactas antes de asignartests/Rootwrites. ActualplanpolicyNone/cutoff
Sep24 ybootstrapprotected1succeeded probados;12failed checkpointsnopuedenlimpiarse.
No asumirrecoveryglobalinactive delsubset1001;proponer queryACTIVO dirigida+4unread
groups(no archivefailedredo) con nuevoslímitesreadonly antes de prepararotrotool.
Rootreservacore/contracts/model/config/deps/locks/centraldocs;Fieldassignmentnuevo
se hará solo tras examinarla propuesta, no scopewriter de directorios.

**Inicio AMQP-OPERATOR-READ-2:** 2026-10-06T02:08:15.749980+00:00;CORRECTCLIofflineFakeDispatchPASS,
priorwrongflagNOOPreaderFalse/0HTTPverified. ONLYunattemptedoperatorGET1;
source42df/supa0bf/oldbindingintact,known52+1≤53/0AMQPresourcesMeliMongo,
120remote130caller+5/300STOPnoBrokerRetry/fallback/regexeval/policywrite.

**Resultado AMQP-OPERATOR-READ-2:** 2026-10-06T02:08:15.749980+00:00→2026-10-06T02:08:20.728598+00:00,
4.978s/SSHexit0/PASS/ONEoperatorGET200complete1/cleanupnull,no/policiesredo.
ONEoperatorrule queuesprio0:{max-length10000,max-length-bytes1073741824},unknown0;
regexNOTevaluated/matchnull/requiresReviewTrue/notactualpolicy/probeauthority.
0AMQP/resources/pub/MeliMongo. KnownMgmt53headers53/51bodiescomplete.
WrongCLIpreviousoperationNOOPpreservada,notchargedasGET. Recibo SHA256
`f96bd7590e2b2b5ae552166ae47f5df65e3aba1bd717b3ac42ef2faae93421f6`.

Rootneedsreview minimalSAFEtemporaryprofile distinctfrombusiness28d, based
actualregularrow2{expires60000,maxlen1000,messageTTL60000}+operator1GiB;
conditionalEFFECTIVEMETADATAexactmatch beforeANYpublisherstep, no assumepattern
matchesrealQName fromsynthetic/unevaluatedregex. Neverchangeglobalpolicies or
relaxTTL/DLX/ownership/zeroCounts/noForeignPayload. Probe1failed0pub/ownremoved
remainsfailure; anynewattemptrequirescorrectedTDDfrozenlimitedprocedure,notblindrerun.
AMQP newSOLEwriterproposal `docs/sheets/zelerdata-historico-amqp-probe-policy-propuesta.md`
(readonlyassessmentnohelpercode/prod/Git/build/agents);Rootreviewscopedbeforeassign.

### Asignación de corrección legacy aditiva (directa, sin SDD)

Propuesta CUOTAS recibida SHA256 `95c399adfad7c9ac374f2efd995bdae82af2dd748b958aee6d664bb778a530d7`; propietario cesó. Se acepta el defecto probado y el seed prospectivo pausado, no saldo histórico inferido. La admisión no iniciará ejecución/day/deadline ni reasignará intentos legacy. Antes de prepare será obligatorio demostrar forma/ledgers y quiescencia; los desconocidos permanecen gate, no crédito.

**Root único escritor compartido:** `core/src/zeler_platform_core/history_onboarding.py`, `gateway/src/zeler_gateway/oauth/events.py`, ajustes de compatibilidad a `gateway/tests/test_history_admission_controls.py`, documentos centrales. Settings/deps/locks/modelos se conservan sin cambio. Cambia solo admisión invocada por Gateway: los helpers usados por worker/API no cambian; reconstruir Gateway, no worker/API por mera inclusión del paquete core.

**CUOTAS único escritor nuevo:**
1. `core/tests/test_history_onboarding_admission.py` — REDs unitarios del contrato, fake BSON/dotted/CAS fiel, sin recurso externo.
2. `gateway/tests/test_history_admission_pilot_seed.py` — REDs scope trusted/hold/piloto5 y selector bootstrap conservado.
3. `docs/sheets/zelerdata-historico-cuotas-legacy-implementacion-informe.md` — RED/GREEN/hashes/cese.

CUOTAS comienza solo RED, entrega fallo antes de que Root cambie comportamiento. Interface propuesta `admit_history_onboarding(..., pilot_seed=False)`; seed piloto pausado cinco fuentes, slots Full0, caps originales, no ejecución. CAS whole-doc, solo hojas ausentes, tipos estrictos, preserve null inválido mediante rechazo; lease live/malformed/CAS drift fail closed. Root acepta cambios antes de liberar GREEN. Nada de producción/Git/build/general suite/agentes/código compartido. Fakes sin recursos pueden correr junto a pruebas fake AMQP; Mongo real y suite quedan a cargo Root tras congelación. No editar estos archivos CUOTAS hasta entrega final y cese.

**Root RED Mongo real de admisión:** nuevo path privado exclusivo Root `ROOT/local-state-pipeline-verify-20261006/test_admission_mongo.py`. Target ya creado/owned, verificado ID/label, solo2volúmenes propios y puerto loopback32768. Tres casos sintéticos RED: argumento pilot_seed inexistente2, last_linked retrocede1. Exclusivamente plans del DB `zeler_goal_state_1c48c4c3c0` se limpian antes/después, sin dropDB/URI ambiente. Código repo todavía sin cambios; log admission-real-red.log preservado. Suitegeneral no ejecutada, CUOTAS sigue solo fakes sin sockets.

### Variante AMQP temporal condicional, no policy global

Propuesta AMQP recibida/cese SHA256 `cc6dfe5ff88f7dcefb1633c1125ae81a21471ac849d6530dca598c6046205f0b`. Root acepta UN candidato exacto de metadata efectiva para CADA cola propia: expires60000/max-length1000/message-ttl60000/max-length-bytes1073741824 (ints estrictos, sin keys extra). Hipótesis segura, no match remoto inferido. Dos metadata GET propios prepublish deberán acreditar el candidato; mismatch STOP0publish sin alternativas/poll. Policies globales/business y todos los guards previos intactos; ambos nombres server-returned solo memoria, nunca log/hash de nombres.

**AMQP único writer cuatro nuevos paths (originales congelados):**
1. `ROOT/amqp-isolated-delay-probe-temporary-policy-20261006/probe_temporary_policy.py`
2. `ROOT/amqp-isolated-delay-probe-temporary-policy-20261006/probe_supervisor.py`
3. `ROOT/amqp-isolated-delay-probe-temporary-policy-20261006/test_probe_temporary_policy.py`
4. `docs/sheets/zelerdata-historico-amqp-probe-policy-informe.md`

Variante SHA-bound al settled2a17 y su base d49; cambio admisible cerrado únicamente validación/recibo de perfil temporal exacto, jamás reescribir metadata para simularlo. TDD RED nuevo perfil contra original, GREEN exact4, 0pub ante profile parcial/extra/bool/mismatch; regresiones de propiedad/args/TTL/DLX/counts/deadlines/timing/confirm/redacción/cleanup. ≤16fakes + checks enfocados3, hashes/embedding/cese. Fakes propios sin recursos: paralelos con CUOTAS sin sockets. No código compartido/Git/build/prod/general suite/agentes ni callbacks del otro especialista.

Tras entrega Root verifica y, bajo el goal autorizado, operará **un solo intento corregido nuevo**:1ownedconn/1confirmchannel,2owncolas/settle6/2ownmetadataGET (known53+≤2=55),1nonce≤64B mandatory wire5000,3get propio/1ACK exactnonce/expired1,≤2delete propios ifempty/unused. Work60/cleanupTOTAL5/hard80/exec95/remote150/root130+grupo5/total300. STOP primero, sin fallback/poll/globalrepair/business/MeliMongo. Probe1 fallido y sus2delete/SSLclosefailure se preservan; éxito nuevo no borrará esa evidencia ni demostrará workerWAIT/noLoss/admisión.

Root behavioral correction after CUOTAS RED23(19FAIL/4PASS) + realRED3: aditivo/CAS/pilotseed/scope. First unitGREEN23; realMongo3PASS(0.14s), ruff/mypy2PASS. Adjacent focused29 ran 9fail/20pass: old BSON fake returns None/does not support CAS/$max; old TracedPlans drops result and legacy fixture holds live lease (now deliberately blocked by leaseRED). Root additionally sole writer `gateway/tests/test_oauth_relink_bootstrap_history.py` (not assigned specialist), adjusts faithful result and uses expired legacy fixture for successful-upgrade contract; livelease WAIT already independent strictRED. No weaken lease guard/actualproduction lease changes. No general suite while writers active.

CUOTAS legacy entrega final/cese: coretestab5274fe/GWtest10b8aa02/informe971f2170/receiptf0d6dbef. RED23(19fail4pass)+RED3 preservados; GREEN26/0skip/quality3PASS. Root fuentes compartidas congeladas, focused55PASS+real3PASS; no Full/admisión/runtime ni prepare ejecutados. Se recibieron y verificaron hashes antes de reencargo.

### CUOTAS lectura nueva de presencia activa y grupos nunca leídos

Solo nuevos paths exclusivos (originalaudit7reads/cap1001/logs inmutables):
1. `ROOT/pilot-state-presence-20261006/state_presence.py`
2. `ROOT/pilot-state-presence-20261006/state_supervisor.py`
3. `ROOT/pilot-state-presence-20261006/test_state_presence.py`
4. `ROOT/pilot-state-presence-20261006/test_presence_mongo.py`
5. `docs/sheets/zelerdata-historico-cuotas-presencia-informe.md`

Contrato de propuesta95c399ad: ONE API viejo3f7exec/runtime factory legítima/PRIMARY;7explicitcommands máximo:hello + plan-shape exactS/cap1, recovery ACTIVE sellerV/state pending,running/limit2, migration exactcohort/cap1, sync ACTIVE sellerV pending,running/limit2, runs sellerV cap100, ops sellerV cap100. Sin account/registry/bootstrap/fullarchive repeat. Se proyecta presencia/tipo cerrado para fields/ledgers/lease/counter conocidos: ausencia genuina ≠ null/malformed. Metadata/números/UTC y agregados server-safe; nada de tokens/nonce/QNames/IDs negocio/checkpoints raw. Cutoff realSep24 conservado. No grant ni saldo2500 ni enable/start.

**Consulta ACTIVE es de presencia, no inventario:** 0 coincide ausencia solo filtro/momento; 1/2 coincide presencia; limit2 genera lowerbound y totalnull, no claim globalquiet ni getMore/página adicional. Puede leer grupos restantes independientes dentro7comandos, pero presencia/malformed mantiene gate de aislamiento false. Runs/ops cap101 y plan/cohort duplicate producen STOP; nunca ignorar truncación de inventario. Enum unknown no se transforma en0/quiet.

TDD≤12fakes luego SAME4casos sintéticos nuevos reales con Mongo7owned anterior DBexact/loopback32768 tras identitylabelcheckRoot; fixturewrites SOLO seis colecciones anteriores, delete_many antes/después/NOdropDB/sin ambienteMONGO_URI. 1001completed+2ACTIVE fixture demuestra filtro dirigido sin redoarchivo; null/ledgerunknown/cap/readerror/foreignseller/redacción. Otros3collections/fingerprints sintéticos intactos (nueve físicas previas, plan/ledger duplicaban una). Root no usa Mongo mientras CUOTAS corre estos casos; AMQP solo fakes sin sockets. Writer no crea/borra contenedores ni hace producción/Git/build/shared/Gateway/core edits/agentes/suitegeneral. Quality focused/hashes/embedding/defaultNOOP/cese obligatorios; Root ejecuta producción después de independiente verificación.

Deadline50body+cleanup5/hard70/exec85/remote130/caller140+5/total300;cadaaggmaxTimeMS4000/batch2/único resumen≤1/cursor0/noGetMore/64KiBoutput. O_EXCLdirs/newpaths; defaultNOOP, flagexact nueva documental, bindingAPIimage/identity/mounts/host>=3.9/currenttoolPy3.11. Preservar fuentes anteriores EOF3f86/sup3ab0 y todos failed/oprecibos.

### Preparación local de controles finales (sin ejecutar suite aún)

2026-10-06T02:24:16.842991+00:00 Root nueva infraestructura Colima `zeler-goal-gates-0e221d445eed`,4GiB/2CPU/20GiB/nohostmounts/activateFalse/SSHoff. Contextcolima y perfilespreviosStopped se conservan; target auditMongo separado intacto en uso exclusivo CUOTAS. Snapshot candidato1097paths/alltracked+14ownnew, tarSHA830c34832a9abd09b231b5f600b0186be30dca2d16cc59490c9bb0454968dc54, código Root congelado. Helpers privados siguen escritura; **no suite general**. Preparación únicamente3imágenes públicas por digest ya usados,≥5GiB measured before cada pull y after,1rs0+1Rabbit+runnerLinux--init/Node/git/Python3, ownedvolumes explícitos sin seedsprod. uv sync--frozen--all-packages en runner aislado permitido, no Dockerbuild/localconfig/lockschange. Snapshot read-only: documentos adicionales posteriores validarán por separado; los bytes/modos de todo código probado se conservarán hasta publicación.

**Inicio AMQP-ISOLATED-DELAY-PROBE-2:** 2026-10-06T02:27:59.857658+00:00; cese/hash4/embedding/AST3.9/14RootfakesPASS. SOLO intento nuevo corregido con perfiltemporal exact4 real enAMBASmetadata antespub; source1a96/supc768/CLI--probe-isolated-delay. Known53+≤2=55;1ownedconn/1channel/2exclusivecolas/settle6/1nonce≤64B/expiry5000/3get/1ACK/≤2ownDeleteifemptyunused. Work60/cleanupTOTAL5/hard80/exec95/remote150/root130+grupo5/total300; STOPfirst/no fallback/poll/policychange/business/MeliMongo; originalprobe1SSLfailure0pub/delete2 preservado.

**Resultado AMQP-ISOLATED-DELAY-PROBE-2:** 2026-10-06T02:27:59.857658+00:00→2026-10-06T02:28:14.688578+00:00;14.831s/SSHexit2/reciboVALIDADO/policy_invalid antesANYpublish. ONEownmetadataGET200/completo;known54headers54/bodies52, no55. Source1a96/supc768 no cambian. 0pub/get/ACK/MeliMongo/business;2ownqueues declaradas y2ownDeleteOk confirmadas/resourceDeletionTrue. TCPcleanupssl_error/waitererror/localcloseTrue/remoteFalse/HTTPcleanupnull, conservado. Perfilactual NO observado: fallo local incluye caps/flags de policy, no acredita qué campo discrepó ni rechazo remoto. BrokerpassedFalse/timingnull/NO retry. ReciboSHA46a27f1dea631417a8fbff25b4649949ab7dc951a1aff5296539342812eafe14.

**Siguiente diagnóstico distinto propuesto:** observar SOLO perfiltemporal efectivo real de owncolas, sin publisher/get/ACK y sin intentar pasar un perfil supuesto. Los dos STOP prueban que no se debe ampliar otra whitelist hipotética ni cambiar policyglobal. Reader próximo emitirá exclusivamente cuatro claves operativas conocidas con int/null/presence/type y unknownkeycount(sin nombres), flags policy/operator bool, identity/args/count0 y siempre Reviewed/PublishAuthorizedFalse. No inferencia desde patterns/listados; scope Root previo/TDD/entrega/cese antes1operación. Nada de negocio/otrosqueues/MeliMongo ni repetición de toolfallido.

**AMQP nueva asignación observacional cuatro paths:**
1. `ROOT/amqp-temporary-profile-observation-20261006/profile_observation.py`
2. `ROOT/amqp-temporary-profile-observation-20261006/profile_supervisor.py`
3. `ROOT/amqp-temporary-profile-observation-20261006/test_profile_observation.py`
4. `docs/sheets/zelerdata-historico-amqp-perfil-observado-informe.md`

Modo nuevo `--inspect-isolated-temporary-policy`, defaultNOOP. No reutilizar main del probe para publicar; body observacional cerrado 1ownedconn/channel/2ownqueues mismos argsprivate/settle6/2ownmetadataGET/2ownemptyunusedDelete; **publish/get/ACK máximos0**. Identity/type/flags/args/count0 previos siguen obligatorios; solo definición de policy se OBSERVA, no se acepta para publisher ni se reescribe metadata. Cada rol cerrado destino/delay: flags bool de policy/operator, para cada4knownkeys presence/type enum/int≥0≤signed63 o null; unknownkeycount sin keys/values/URLs/pattern/QName/rawbody/hash. Si metadata identidad/args/count/type corrupción STOP; caps desconocidos tipan unknown y gateReviewed/PublishAuthorizedFalse siempre, no global/noLoss/admission. La muestra real será evidencia para revisar, no permiso automático de otro probe.

TDD≤12fakes RED/GREEN observado vsperfilinferido, mismatched/extra/nonstrings/bool/canary redacted/zero pubsgetsacks/timeouts/ownedcleanup/defaultwrongNOOP; focusedquality3/hashembedding/AST3.9/preservar todos anteriores52+actualfail1/2/cese. Supervisor valida closed receipt y máximos0, no callbacks publisher siquiera. Solo Root opera 1diagnóstico trasverificación: known54+≤2=56, work30/cleanupTOTAL5/hard50/exec65/remote100/root110+grupo5/total300,4sHTTP64KiB; sin nueva lista/policies/foreignqueues/globalpolicywrites/prodGatepass. No builds/Git/shared/suite/general/agentes. Esta es lectura de hecho faltante distinta, no repetición de publicación fallida ni continuación automática hacia tercerprobe.

**Inicio AMQP-TEMPORARY-PROFILE-OBS-1:** 2026-10-06T02:41:07.137056+00:00;AMQPcesó/4hashes10Rootfakes/embedding/AST3.9PASS. Reader08f2/sup9503/flag--inspect-isolated-temporary-policy; distinto inspectorHECHOS/noPublisherGraph, hardmaxpublish/get/ACK0,1conn2owncolas/settle6/2ownmetadataGET/2ownifemptyunusedDelete. Known54+≤2=56;observacionesknown4captypes/números/presence/unknownkeyCOUNTonly, policyNone/empty→Falselegítimo no aprobación. Work30cleanupTOTAL5hard50exec65remote100root110+grupo5total300,STOPfirst/no fallback/repeatprobe/list/globalpolicy/foreign/MeliMongo;Reviewed/PublishAuth/noLoss/admissionFalse siempre.

**Resultado AMQP-TEMPORARY-PROFILE-OBS-1:** 2026-10-06T02:41:07.137056+00:00→2026-10-06T02:41:20.321950+00:00;13.184s/SSH0/VALIDATEDobservation_complete/2ownGET200completos. Known56/56headers/54bodies;2ownDeleteOk/resourceDeletionTrue/cleanupfamiliesnull/waitercompleted/localcloseTrue/remoteFalse(no remoteattestation). 0pub/get/ACK/business/MeliMongo. AMBASmetadataidentity/args/count0PASS,policy/operatorpresentTrue/string, definitionobject/unknownkeys0; EXACTactual3keys {expires:60000,max-length:1000,max-length-bytes:1073741824}. **message-ttl genuinamente MISSING**, no null ni60000. Hipótesis4 previa eraincorrecta; no inferir regla/pattern que lo causó. Reviewed/PublishAuth/broker/noLoss/admissionFalse. ReciboSHAe17922ff1c1679457dda71e7db74683ece1539dbb140d52fc7c3f157b0c6c234. No diag repetido para mejorar cierre: lectura distinta del hecho antes faltante.

### AMQP: una prueba corregida basada en perfil realmente observado

Root revisa recibo e17922ff y aprueba un candidato **medido**, no otra hipótesis:
expires60000/max-length1000/max-length-bytes1073741824, EXACT3keys intestrictos;
message-ttl ausente y ambasflags policy/operatorTrue, AMBAScolas previas alpub.
DelayargumentTTL30000 ywireexpiry5000 siguenmínimo5s; Destination sinTTLpolicy es
aceptable solo para1nonce≤64B,limit1000/1GiB,ownACK+conditionaldelete yexclusive
60sinactivity como respaldo. No confirma pérdida/durabilidad/worker ni autoriza
otra operación si falla. Global/businesspolicies untouched;2failurespreserved.

**AMQP único writer cuatro paths nuevos, original1a96/c768 congelado:**
1. `ROOT/amqp-isolated-delay-probe-observed-policy-20261006/probe_observed_policy.py`
2. `ROOT/amqp-isolated-delay-probe-observed-policy-20261006/probe_supervisor.py`
3. `ROOT/amqp-isolated-delay-probe-observed-policy-20261006/test_probe_observed_policy.py`
4. `docs/sheets/zelerdata-historico-amqp-probe-perfil-real-informe.md`

SHA-bound wrapper modifica SOLO literalCAPS4→3 ysupervisorbinding/CAPS3; bytecode
metadata/body/clock/expiry/cleanup/ownership/typedconfirm exactos al1a96/d49/settled.
≤6fakes RED actual3rechazado por1a96, GREEN exact3/old4/business/unknown/bool/flags
antes0pub; mantiene regresiones genéricas por identidadbytecode. Quality3/AST3.9/
embedding/hashes/cese. Noprod/Git/build/shared/oldedits/agents/suitegeneral.
Root operará ONE nuevo intento solo tras entrega/independentchecks:known56+≤2=58,
1ownedconn2q/settle6/1noncepub/3get/1ACK/2delete;work60cleanup5hard80exec95remote150
root130+grupo5/300. STOPfirst/no blindretry/close-improvement. Este3profile fue
observado realmente en ambascolas; no copiar policieslist ni patrón para inferirlo.
Suitegeneral permanece detenida hasta cese deestewriter; código repo Root congelado.

**Inicio PILOT-ACTIVE-PRESENCE-1:** 2026-10-06T02:47:59.100516+00:00;CUOTAScesó/5hashes/embedding/AST3.9/12fakes+4realMongoRoot16PASS0.90s. Reader8a776/sup062e/flag--inspect-pilot-state-presence exact;ONEAPIold3f7approvedVMVPC legitimateDBfactory PRIMARY+6aggs=7explicitreads. Shapeplan/missing≠null;ACTIVE recovery/sync limit2presencenoarchive; migrationcap1/runsops100. No account/registry/bootstrap reread/reset/leasechange/MeliAMQP/getMore. batch2firstBatch≤1/cursor0/maxTimeMS4000/64KiB;50work5cleanup70hard85exec130remote140caller+grupo5/300;STOPfirstnoRetry/fallback/zerosaldos/startinference.

**Congelación conjunta 2026-10-06T02:52:23.617017+00:00:** AMQPúltimaentregac4ac/7635/d7e3/00cb +6RootfakesPASS;CUOTAS8a77/062e/4e4a/85a3/af13 +16Rootfakes+MongoPASS/cese. Ambosnotificados:sinmodificaciones/pruebas. Root3realCASposttyping3PASS0.18s. Todos905codepaths(bytes+modos)idénticosalsnapshot1097tar830c3483;Docsposterioresindependientes. Suitegeneral ahoraLIBERADA soloRoot/ownLinux(rs0+Rabbitfresh)/sincredencialesambiente; operacionesVM readonly/acotadas usanDB/puertos distintos.

**Resultado PILOT-ACTIVE-PRESENCE-1:** 2026-10-06T02:47:59.100516+00:00→2026-10-06T02:48:05.440791+00:00;6.340s/SSH0/VALIDATEDPASS/PRIMARYtrue/7readsstarted=completed/cleanupclosed/0docwrites/getMore/MeliAMQP. Plan1canonicalidentity/cutoffSep24match; TODOS fields policy/authority/state/eligible/sources/budget/counters/day/deadline/executionID/ledgers/lease/bounds genuinamenteMISSING(validtypes), noNULL/invalid;progressOBJECT4 preservado. No2500histórico libre/arranque. RecoveryACTIVE0 ysyncACTIVE0 solo filtro pending/running sellerV/momento, totalglobalnull/isolationFalse. Cohort1 cutoff2026-08-11T04:01:19.890UTC. Runs8(7failed+1completed), todoslegacy/no liveleases; completadoobservadoJune1→11 nootra cobertura inferida. Operation1succeeded/legacy/coverage_modeactive/epoch0/fence3836/leaseexpired2026-10-06T00:39:41.066UTC; preserveallproofs/jobs. Otros4gruposnuncaantesleídosahoracubiertos, noarchive1001repeat. ReciboSHAa235be5c6c7fd2f2f18c7a30517df473a65d8dfec482a71c78e36747f0328ecb. Quiescencia aúnrequiere flags reales/producer gates, noestablishfromabsencealone.

**Inicio AMQP-ISOLATED-DELAY-PROBE-3-ACTUAL:** 2026-10-06T02:56:24.074269+00:00;AMQPcesó/4hashes6Rootfakes/embedding/AST3.9PASS;SOURCEc4ac/sup7635/CLI--probe-isolated-delay. ONLYactualobserved3profile expires60000/maxlen1000/maxbytes1GiB+bothflagsTrue, 2realOWNmetadata exactprepub; noassumedTTLpolicy/newwhitelist/globalchanges. Known56+≤2=58;1ownedconn2q/settle6/1nonce≤64B mandatorywire5000/3get/1ACK/≤2ifemptyunusedDelete. Work60cleanupTOTAL5hard80exec95remote150root130+grupo5/300;STOPfirst/noRetry/closeimprovement/MeliMongo/business. Localfullsuite correENOTRO VM/DB/Rabbit; amboswriterscongelados ytodos905repocodehashesidénticos.

**Resultado AMQP-ISOLATED-DELAY-PROBE-3-ACTUAL:** 2026-10-06T02:56:24.074269+00:00→2026-10-06T02:56:45.178524+00:00;21.104s/SSH2/VALIDATEDcleanup_failed. **Broker sample PASS**:AMBASmetadata exact3profile/identityargs/count0,2ownGET200complete;1noncepublishtypedconfirmed,earlygetempty4.034744s<5,lateownnonce8.032437s≤10/x-deathexpired1/origexpiry5000,1localACK+get3empty. Sourcec4ac/sup7635 intactos;known58/58headers/56bodies. 2ownDeleteOk0msgs/resourceDeletionTrue; cleanupTLSssl_error/waitererror/localcloseTrue/remoteFalse/HTTPcleanupnull, preservado. TransientDockerexec/SSHterminó, NO afirmar cierre remoto ni toolcleanPASS. 0business/MeliMongo; noLoss/ingress/durability/workerpath/admissionFalse. ReciboSHA975c2d7d0b66e5f3e0cc200b10fe650819d7fb524c8941f0a54a99d86dff3bcd. **No otroprobe para mejorarclose**. Resultado prueba únicamentela muestra de transporte enpar temporal, no rutaWAITworker niaceptación/piloto. Controles/localbuildpueden continuar independientes; evaluación de rolloutcerrado deberá nombrar evidencia aceptada y límites/errores, nunca convertirEXIT2 enPASSlimpio.

**FULL-1 STOP local:** Linux full405.033s/exit1,1FAILED+6420PASS/20SKIP; snapshot intacto. Único fallo `gateway/tests/test_lifespan_rabbit.py::test_successful_oauth_callback_publishes_through_lifespan_adapter`: FakeHistoryPlansCollection devuelveNone y no representa whole-doc CAS/$max/dottedwrites (matched_countAttributeError); el comportamiento real pasó3Mongo. No rebajar CAS ni excluir prueba. Root nuevo único writer exacto `gateway/tests/test_lifespan_rabbit.py`, corrección mecánica del fake con UpdateResult/snapshotdeepcopy/matches/dotted/max fiel y BSONfechasaware preservadas; Root TDDRED queda en logfull, focusedGREEN antes nueva congelación/snapshot y rerun controles. Protected no inició por STOP; ambos especialistas permanecen congelados. Sin Git/build/deploy/OAuth/prepare/piloto.

**Round2 recongelada 2026-10-06T03:09:50.289174+00:00:** Onlytest_lifespan_rabbit.py codechanged vsRound1; fakefaithfulsnapshots/$max/dotted/UpdateResult preservesaware dates, focused4PASS2.42s/mypy1PASS. Runtimecode/no deps/settings changes. Sourceall1101paths tarSHA40f2645a36aafc8e2acae0c47bdd22489f99773249110b6475f905f4e8b2bb01; all905codebytes/modes congelados; mismainfraownrs0/Rabbit/runnerLinux ycredencialesaisladas;SourceOriginal830/tar/failed1logs inmutables. Rerun gates exigidos yFULL tras corrección, protected luego. Sin otroswriters/build/prodmutation/OAuth/prepare.

**Cleanup local propio:** después de CUOTAScese/Root16+3Mongo PASS, Root verificó label/id/2volúmenes y daemonexclusivo; stop15/rmcontainer270ce/rmexact2volúmenes (no prune)/delete SOLOprofilezeler-goal-audit-20261006-470b1fa4. Contextcolima y perfilesoriginalesStopped preservados. Log/recibos/fixtures/hashes en cache persistidos; ningún datos/VM/volumen productivo o ajeno. Profilegates4GiB0e221d445eed sigue activo y separado.

**OAuth frontend, solo lectura CUOTAS:** ../zeler-app existente;7archivosrelevantes (informe mensaje, sinedición). Accounts genera URLOAuthnormal desde session.user.id sinforce pero CTArelink solo revoked/invalid_grant; cuenta824activa sinbotón. /sheets/config gestiona tokens delcomplemento, noML OAuth; force-dynamic noforceBootstrap. No revocar/token-copy/callbackdirecto. Código local no pruebaUIactual; Root inspeccionará flujo legítimo contextual antes de OAuth, después gateway/pins/gates. No frontendbuild/deploy/edit ni preguntas nuevas de permisos condicionales por esta lectura.

**Gates finales Round2 PASS 2026-10-06T03:20:53.107965+00:00:** Full6421PASS/20SKIP405.84spytest(408.201envoltorio), protected19PASS4.64s(5.855envoltorio), focused55PASS0.41s;ruff/format/mypy667/direct-Meli/schemaPASS. All8exit0 yrecibos snapshotunchangedTrue; 905codebytes+modosactualesidénticosalsnapshot1101tar40f2645a36aafc8e2acae0c47bdd22489f99773249110b6475f905f4e8b2bb01. Full1failed1retained;no exclusión de prueba ni SourceRuntimechangeadicional. Mongo PRIMARYrs0/namedDBfresh/Rabbitfresh/NodegitPython3/subreaperLinux/sourceRO/ambientsecretsnone. Docsex posteriorescoherenciavalida independiente; Rootpublicaciónsoloownunitsiguiente yCloudBuildONLYGateway fromexactmain. Worker35269d9reusable/API3f7unchanged ASTproof; No deploy/OAuth/prepare/pilotoaún.

**Publicación exacta:** codeunit1c367664569e2f908298047a6bdc508bf304ab8f(9paths) + evidenceunita10e31496c408f9ab321196fc5ad27f2cc6a10b8(17paths),pushmain/remotoexacto/treeclean alverificar. No ramas/worktrees/stash/reset/force; solo26ownpaths. Todo905codeBLOBScommit a10e coincidecon6421+19/667snapshot40f2645a.

**Inicio GW-LEGACY-BUILD-1:** 2026-10-06T03:22:47.461785+00:00;SourceEXACTmaina10e31496c408f9ab321196fc5ad27f2cc6a10b8/connectedrepo canonical projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform/Gateway ONLY gateway/Dockerfile/images1/requestedVerifyOptionVERIFIED. Una solicitud autorizada goal, no sourcecheckoutupload/localDockerbuild;workerexisting69d9reused/API3f7unchanged/no deploy/OAuth/prepare/piloto. Tagmetadatosnoautoridad;SUCCESS+provenance+digestgates siguenantesdownload.

**Resultado GW-LEGACY-BUILD-1 VERIFIED:** 2026-10-06T03:25:42.554420+00:00;build121b3b08-3d3f-4b12-b40c-2a4f2ba7d590/SUCCESS/VERIFIED/repoSourcea10e exact/canonicalverifyPASS,1request/oneimage. Immutable us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:4f90ba7c48fd2258f35cb4b80a2ab3d8eb93d30786ce761d32a6b6a3475e8268. BuildpreparaciónONLY:0VMpull/deploy/OAuth/prepare/piloto. Reuseworker69d9source352/API3f7no build. Provenance/builderproject/source/digest/map privadosverificados; no permisos/secretos/lockfiles nuevos.

**Inicio VM-CLOSED-BASELINE-1:** 2026-10-06T03:33:42.088500+00:00;Root read-only fresh beforeselectedrollout. Local5RED→5GREEN/hostAST3.9, collectorSHAd8880a1deef53d01fe6bb0e5e9ad6147cf42fcd01b29e4a6fc825fb3a5342112; verifyinstalledpreflight06edd/oldoverlayb7b85, canonicaldryrun/dfbytesinodesRAMMongoSeparate, boundedDockerinventory30/selected7054-79f-3f7/staticcontrolscopes/publicflags/fullbase+oldoverride renderinMEMORY secretneverwritten/printed. ≤7Docker/compose/preflight calls20seach/hard90/SSH120/total300,0downloads/writes/restarts/Meli/Mongoqueries. STOPfirsterror/no retry/fallback; allsource905codefrozenunchanged; Rootsoleoperator.

**Resultado VM-CLOSED-BASELINE-1:** 2026-10-06T03:33:47.618808+00:00;SSH2/STOPgateway_scope_unbounded antes0mutación. ArtifactsSHA/renderENV/pinsall3/canonicaldryrunPASS;Root36,534,845,440bytes+6,233,537inodes, Mongo47,459,823,616bytes+3,276,153inodes/separatedevice, RAMavailable911,876,096bytes/total4,103,168,000/no swap. All11running/restarts0/OOMfalse;selected3healthy/CaddynoDockerHealthcheck. Stopgrace60sGateway/API/worker. HOLDtrue/admission82only/historyworkerOFF/recoveryAPIworkerOFF/refreshOFF/syncpollerON82recoveryScope. **ActualoldGateway budgetguardsetting MISSING**, not82: oldb867doesnotimplementguard. No fallback/nonzeroquotaassumption; necessary NEWexclusiveclosedoverlay mustaddonly GatewaypublicZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS=82453304 withnewimages, keepHOLDtrue andallotherEnv/rendercohort unchanged. Rootwrites sharedconfig solewriter, goalalreadyauthorizesrequiredselectedrollout; no ulangbaseline/helperforbadguard.No download/restart yet. EndSHA2c38d02b514a88546320e1e8a5642e190ea39417ffe857dbe6daf633ba67f845.

**Inicio AMQP-PREDEPLOY-FRESH-1:** 2026-10-06T03:35:47.846105+00:00; mandatoryfreshbaseline beforeclosedrollout, previousPASStopology01:16 aged>2h. Sameimmutable816e/460cbHTTPONLY 23GET10queuesmetadata+bindings/3exchange4sreq60read64KiB5cleanup80hard95exec150remote160caller/total300. Known58+≤23=81/oldunknownseparate. Exactoldworker79f/sourcebinding,0AMQPconnect/publish/declare/ACK/Meli/Mongo/repairs. STOPfirst/no retry; not repeatedTLSprobe. Source/tuple/businessall14permissions/data untouched.

**Inicio VM-CLOSED-STAGE-1:** 2026-10-06T03:39:18.888324+00:00;Goal authorizedselectedclosedrolloutprep. NewexclusiveRootdir/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314 withONLY2images(worker69d/GW4f90)+publicbudgetguard82 (actualbaselineMISSING);HOLDtrue/historyOFF/recoveryOFF/refreshOFF allotherconfigs preservedFULLinmemory deepEq5RED→5GREEN. Image-bindingpublicsnapshot2services forcanonicalonefilepreflight; newmapprivatepath DOESNOToverwriteglobalimage-map. capacitydryrunbefore normalprovenance, SHEETS_ROLLBACK_PREFLIGHT0/noAPIattestationpull/no cleanup. Root acceptspriorlimitednonce/delay/owneddelete asbroker SAMPLEONLY withTLSSTOP retained;fresh23HTTPtopologyPASS andemptylive/5retry/DLQ315preserved. No cleanTCP/globalnoLoss/pilotadmissionclaim. Stage0pull/0restart/0MeliMongo, hard150/SSH180/total300, STOPfirst/no retry. Rollbackoldpins onlyclosedpreOAuth;afterh1forwardnewpinsHOLD/planpaused preservingstate.

**Resultado AMQP-PREDEPLOY-FRESH-1:** 2026-10-06T03:35:53.723858+00:00;SSH0/23GET200allcomplete/topologybindingssameTargetPASS/cleanupnull. Known81starts81headers79bodies;oldunknownseparate. Events/claimsliveconsumers1/readyunacked0;delay/retries5all0; eventsDLQ315/71411bytesretained, capsexpires2419200000/maxlen10000/maxbytes1GiB exactall10. 0AMQPtransport/pub/mutation/Meli/Mongo. Ingressbound/noLoss90/pilotadmissionfalse unchanged; source readerdoesnotcertifypublish/timing. endSHA22ffd416d7f972a050ff6eb3907df952329f5cb889515ba0d3cf4aeea99eb838.

**Inicio VM-CLOSED-DEPLOY-sheets-worker:** 2026-10-06T03:42:21.281992+00:00;Rootselectedauthorizedscope ONLYworker69d/source352 afterpublicconfigexactDelta/normalcanonicalprovenancePASS; old79f runninghealthy0OOM/restart rollbackclosedbeforeOAuthcompatible. FreshTopo23PASS/muestraaislada8s partialwithSSLSTOPacceptedONLYbrokersample, noLossfalse; capacityfresh>=5prepull/postpull/postsettle. Composebase+oldoverlay+newexclusive/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314/closed-overlay.json, allEnvexceptplannedGWpublicguard unchanged/HOLDtrue/historyrecoveryrefreshOFF. Onepullworker, oneup--no-deps--pullnever, Dockergrace60/rootcall310/hard290/compose150/health<=60/settle60;eacherrorSTOP beforeGateway/remaining. No broadrestart/cleanup/APIpull/registry/validator/quotas/Meli/OAuth/piloto. Rootprivatehealthprobecomponentready notactualACKproof.

**OAuth entrada REAL encontrada:** ChromeappTab1685092840/authenticatedAccounts safeDOMactualmuestralinkvisible Vincular otra cuenta. HTTPSgateway.zeler.ai/oauth/authorize conplatform_user_idpresent (nunca valorimpreso) yforceABSENT. LecturacódigolocalCTA-gap no eraUIdeployproof, se corrige conestehecho. No frontendedit/build needed/no sessionAPI/cookie/tokenextraction/revocation/manualowner. OAuth NOclicadohastaGWnuevo/HOLDcontrolado listo, verificarcuentaMeli824enflujo normal.

**Resultado VM-CLOSED-DEPLOY-sheets-worker:** 2026-10-06T03:44:26.077539+00:00;SSH2/STOPdeploy_failed/elapsed124.825s. Prior79fhealthy/0restart/OOM/stopGrace60 andprepullfree36534165504bytes. Pull initiated butcompletionNOTconfirmed(flagimage_pulledFalse), recreate_startedFalse, noGateway/APIrestart/pilot. Exceptionfamily generic notcauseproved; possiblelocal120spulltimeout needsauthoritativeimage/daemonstatus—not inferdownload0/failureglobal. PreservefirstSTOP/no blindrepeat.

**Inicio VM-WORKER-PULL-OBS-1:** 2026-10-06T03:46:43.663902+00:00;RootREADONLYactualstateafterunconfirmedpull:twoDockermetadata calls(runningworker79 identity/health andselectednew69 imagepresence/digest),capacity. No download/restart/authrepair/Meli/Mongo/APIqueries; deadline45SSH60/no retry.

**Resultado VM-WORKER-PULL-OBS-1:** actualselectednew69imageABSENT inspectexit1;runningold79fhealthy0restart/OOM/rootfree36533882880. No activeownCLI confirmed (priorhelperterminated); do not restart basedonlytimeout. Next distinctreadonlyselectedpull evidence:boundedDockerdaemonjournal03:41→03:45 codes ONLY (never messages/URLs/env/auths), ownDockercredential-helper names/counts no values, no GETtoken or pull.

**Resultado VM-PULL-CAUSE-OBS-1:** bounded4Dockerdaemonrecords/5549bytes:3pull/context-canceled markers,0unauthorized/denied/timeout/DNSrefused; rootDockerhelpergcloud/configauthEntries0, no values/tokens read. PriorCLI terminal at~120slimit/imageABSENT/serviceold79healthy supports canceledpull, not authenticationfailure. No livehandle/daemoncompletionknown; this isnot mereobservationexpired. **Root bounded corrected WORKER-PULL-2** necessary deployment downloadONLYimmutable69d afterfresh5GiB, deadline240Docker/hard270/SSH290/total300, no automaticretry. PreviousfirstSTOP preserved; no recreation untilimmutableimagepresentverified. No authconfigchange/newpermissions/Meli/ScopeReset; residualrootcapacity measured.

**Resultado WORKER-PULL-2:** 2026-10-06T03:50:39.531510+00:00;Dockerpull11.145s exit0/selectedimmutable69RepoDigest+size152635627bytes verified, rootfreepre36533587968/post35985833984. 0restarts/Meli/Mongo/state reset, no credentialconfigchange. PreviouscomposepullSTOPnoterased/causeonlycanceledobserved. **Inicio VM-WORKER-RECREATE-1:** 2026-10-06T03:53:20.810414+00:00; resumeAFTERpull verified (0newdownloads),ONLYworkerup--no-deps--pullnever,60sgrace/compose150/hard290/SSH310/settle60/capacitybefore+after/componentsready. No Gateway/APIrestart yet, HOLDtrue/historyOFF/recoveryrefreshOFF/newconfig82budgetguardapplieslaterGW. STOPfirst/no autopull/retry; Rootoldclosed79rollbackconditionalbeforeOAuth ifneeded.

**Resultado VM-WORKER-RECREATE-1:** 2026-10-06T03:54:44.872428+00:00;SSH0/PASS/ONEworkerrecreate old79→new69d9/source352, noRedownload. Initial+60settleHTTP200ready/all2componentsok/restarts0/OOMfalse, rootfree35985764352, history/recovery/refreshOFF/pilotfalse; GW/APIuntouched. **Inicio VM-CLOSED-DEPLOY-gateway:** 2026-10-06T03:57:25.450100+00:00;Root ONLYGatewaynew4f90/sourcea10e verifiedbuild121b3b08,worker dependency69settled2components rechecked, priorGW7054healthy/60grace. Fresh5GiBpre/post directimmutableDockerpull (notcomposepull), thenup--no-deps--pullnever ONLYgateway/HOLDtrue/additivepublicguard82, initialready+settle60+capacity/0restartsOOM, hard290/SSH310/no retry/STOP. allotherenvironments/services/APIdata unchanged; no OAuth/prepare/piloto yet. Rollbackbeforeh1 onlyold7054closed;afterh1forwardnew guardedpins.

**Resultado VM-CLOSED-DEPLOY-gateway:** 2026-10-06T03:59:56.198255+00:00;SSH0/ONEGateway7054→new4f90/sourcea10e pull+recreateonly. Worker69dependency200/all2componentsready;Gatewayinitial+60settle200ready/all2dependenciesok/0restartsOOM, rootfree35675926528. HOLDclosedTRUE/publicbudgetguard82only effective;API3f7 no pull/recreate, allothersuntouched. No Meli/OAuth/prepare/piloto/quotas/cutoff/jobs resets. Selectedrollouttwoimagesnow SERVED butnotproductacceptance. Nextnewcontextpostcontrol/consumerreadonly before HOLDopening.

**Inicio VM-CLOSED-POST-1:** 2026-10-06T04:02:07.603954+00:00;newcontext read-only expected69d/4f90/API3f7+actualfull3fileCompose, nofailedoldguardbaseline replay; samevalidatedsanitizefields. All11Dockerhealth/restarts/OOM/capacityMongo/RAM/stop60/publicflags selectors,0downloads/writes/restarts/Meli/Mongoqueries, hard90SSH120STOPfirst.

**Inicio AMQP-POSTDEPLOY-1:** 2026-10-06T04:02:52.843752+00:00; newservedworker69 context ONLYsupervisorEXPECTED_IMAGE updated(Redoldreject/Greennewfake/ASTallotherssame/reader816eunchanged), SHAffa172757229178c691c5f5a424e1e846fe56c572e5eaa0f1881d372bd9b9c89. Mandatorynewconsumers/topologyafterrecreation, HTTP-only23GET/4sreq60read5cleanup/95exec150remote160caller300total, known81+≤23=104/oldunknownseparate. No AMQPconnect/declare/publish/ACK/MeliMongo/retry/repair, STOPfirst. Contextchanged justifies freshcheck, not oldfailedTLSprobe rerun.

**Root metadata startup readonly inspection:** 2026-10-06T04:07:03.813640+00:00;legitimatepersistence check fromACTUALGCEinstance metadata, notrepo startup substitution. Oneinstancesdescribe only, holdfullmetadataMEMORY/no rawvalues/secret/hash output, fixedderivedbooleans only. No metadataupdate/reboot/download/restart/Meli/Mongo.

**Startup persistence actualhelper readonly:** 2026-10-06T04:12:14.163972+00:00;GCEactualmetadata exec /opt/zeler-platform/zeler-platform-secrets.sh, no directcomposeUp inferred. ReadhelperMEMORYonly to derive finalcompose/publicconfigpaths withoutsecret/output; no sourceRepo substitution/no metadata/env writes.


**Inicio VM-ADMISSION-OPEN-1:** 2026-10-06T04:16:09.876022+00:00;Root ONLY Gateway HOLDtrue→false via nueva admission-overlay.json (closed-overlay preservado), comparador3RED/GREEN/five forbidden mutations; exactFULLrenderdelta ONLYHOLD/allpinsguard82/dependencias/historyrecoveryrefreshOFF verificados. 0pulls/1upGateway--no-deps--pullnever/stopgrace60+settle60/hard290SSH310;freshcapacity≥5GiB, STOPfirst/no retry. Usuario HOPEMOB confirmado enUI; OAuthnormal aúnNOclicado, sinforce/seedmanual/reset/prepare/ejecución.

**Resultado VM-ADMISSION-OPEN-1:** 2026-10-06T04:18:33.332602UTC/143.561sSSH0/PASS;onlyHOLDdeltaTrue/0pull/ONEGatewayrecreate/initial+60settleReady200all2dependencies/workerall2components/0restartOOM/rootfree35666382848. GW4f90 guard82only yhistoryrecoveryrefreshOFF. **Inicio HOPEMOB-OAUTH-1:** 2026-10-06T04:18:40.868385+00:00;actualvisibleAppAccountslink normal sinforce, MLHOPEMOB previamenteverificado/ownerlegítimo, mismospermisos existentes. No copiar token/código/cookies/admisiónmanual; pausa5sourceesperada; STOPsi nueva concesión/CAPTCHA/identidaddistinta/callbackerror.

**Resultado HOPEMOB-OAUTH-1:** 2026-10-06T04:19:24.240971+00:00;actualAppAccountslink→MLcountryMéxico→app/accounts/linked, heading Cuenta MercadoLibre conectada visible/screenshot. SesiónHOPEMOBverificadaantes/noforce/no credential/token/cookie copy/newconsent/CAPTCHA. ÉxitoUI es callbackONLY; planpaused5/progresocutoff/registry14/bootstrap13 aúnreadbackpendiente,0prepare/activar/adquisición.

**Inicio POST-OAUTH-BASELINE-1:** 2026-10-06T04:20:49.369350+00:00;PRIMARY+exact5grupos account,plan,ledger,registry,bootstrap=6commands explícitos max; no recoveryarchive cap1001 repeat/sync/runs/ops. Nuevo readersubset frozenoriginal unchanged salvo seleccion5+EOFbatch2+numericprogresssize/Fullslot+missingwindow/counterledger booleans;3RootRED/GREEN sinred. ONLY oldAPI3f7VMVPC legitimatefactory,maxTime4s/50work5cleanup70hard85exec130remote160SSH/no getMore/writes/MeliAMQP. Comparación previousmetadata no fingerprint exacto retrospectivo deprogress/checkpoints, noidentityproof inventado. STOPfirst/no retry/reset/prepare.

**Resultado POST-OAUTH-BASELINE-1:** 2026-10-06T04:20:55.425848UTC/6.149sSSH0/PASS/PRIMARY/6started6completed/cleanupclosed/0writes. ActiveaccountconnectedJune1retained/OAuthupdated04:18:58; policy/authority/eligibleTrue PAUSED5exact/Fullslotlimit0used0/cutoffSep24 unchanged/range2025Sep24→2026Sep24/progresssize4; caps800150250300500/used0/total2000/daily500300. Window/execution/counterledger genuinelyABSENT (notreset); nohistorical2500saldo inferido. Registry14/6noFull/hash704afe unchanged/bootstrap13sameobservables(1success7cp/11failed6cp/1failed0cp),no newbootstrap. Integridadexactacontenido retrospectiva no acreditada, solo cardinalidadmetadata. Rootasignó ÚNICO nuevo executionID32 privado tras ausencia verificada; aún0prepare.

**Inicio PILOT-PREPARE-PREVIEW-1:** 2026-10-06T04:22:21.686015+00:00;sourcecanónico frozenhash/SAMElocal6421+29tests;RootONLYAPI3f7runtime stdin legítimo, primera preparación propuesta IDs/window previamenteABSENT;dryrun1find/control/no archivo/Mongo mutation/leases/jobs/provider;60hardoperator75exec120remote150SSH;STOP/no retry. Propuesta2000initial+500maint max2500/90min sameUTC yFull0, noreset oldcutoffconsumption.

**Resultado PILOT-PREPARE-PREVIEW-1:** 2026-10-06T04:22:26.441228UTC/4.842sSSH0/PASS/no writes;paused proposed/initial800150250300500/dayrolloverpendingTrue/maintenance availabilityNULL/natural500300, no crédito inventado. **Inicio PILOT-PREPARE-APPLY-1:** 2026-10-06T04:22:53.637251+00:00;primera preparación genuina después camposABSENT yOAuthPAUSED baseline;1wholeDocCAS/1readback exact/sourcecanónico unchanged, recibo exclusivo0600 runtime+VMpreserved. 90minmáximocomienzaAHORA alapply/noextensiónactivate, total2500inclretries/Full0/oldcapsmin/cutoffprogressjobsleases conserved. Worker historyOFF;0activate/providercalls. Deadlines60/75/120/150 STOPfirst/no retry.

**Resultado PILOT-PREPARE-APPLY-1:** 2026-10-06T04:22:58.632614UTC/5.117sSSH0/PASS/ONEwhole-docCAS+readbackexact/PAUSED. Única ventana empieza04:22:57.845386UTC/≤05:52:57.845UTC sameOct6; NO reprepare/extender/reset/otroUUID permitido. CanonicalreceiptappliedTrue/PINb886569d3b56c2957d25cbf4213caed290da96672dd1edc285a893194e22e1e2/resultplanSHA3e1278b0f55066cc881956dd838bda27efebfdca0c2f2e8606ceea6bf643864d/private0600 runtime+VMpreserved. Initialremaining800150250300500/2000/dailyrolloverpendingTrue/natural500300/maintenanceNULL (runtime solo rollovernatural); Full0/cutoff/progress/jobs unchanged porCAS. HistoryOFF/0activate/MeliAMQP.

**Inicio VM-HISTORY-WORKER-ARM-1:** 2026-10-06T04:24:04.112077+00:00;planPAUSED/firstprepare receiptPINfixed/window yaavanza04:22:57→≤05:52:57. ONLYworkernew69 historyflagOFF→ON seller82ONLY, nueva history-overlay.json trasclosed+admission4files;Root3RED/GREEN exactFULLsingleenvdelta/nootrosserviceconfig. 0pull/1workerup--no-deps--pullnever/stopgrace60/initial+60settle/currentguardGW4f90/recoveryrefreshOFF/APIunchanged. 290hard310SSH/capacity≥5prepost/STOPfirst/no retry, noactivate/saldoreset/windowextension.

**Resultado VM-HISTORY-WORKER-ARM-1:** 2026-10-06T04:25:28.576653UTC/84.595sSSH0/PASS/0pull/1workerrecreate/ONLYhistorydelta/seller82ONLY;initial+60settleReady3components/GWready2deps/0restartOOM/rootfree35665825792. PlanPAUSED/windoworiginal04:22:57→≤05:52:57; noactivate/Meli yet. **Inicio PILOT-ACTIVATE-PREVIEW-1:** 2026-10-06T04:27:04.077604+00:00;canonicalreceiptb886 pinned/wholepreparedplanhash/lease/day/deadline caps validation readonly plusactualpinsGW4f90worker69API3f7/envhistory82only/GWbudget82only/legacyOFF eachrechecked. No flags blindlyasserted/previewonly/0CAS/provider;60operator75exec120remote150SSHSTOPnoRetry.

**Resultado PILOT-ACTIVATE-PREVIEW-1:** 2026-10-06T04:27:09.511411UTC/5.467sSSH0/PASS/readonly0CAS;livepins3/envgates/scopes verificadosTrue/appliedpreparePINwholeplanstillmatches/dayuntil/leases/caps valid. **Inicio PILOT-BUSINESS-BASELINE-1:** 2026-10-06T04:28:41.988964+00:00;antesactivate, ONLYPRIMARY+planPAUSED+certs20/freshness5/messages100selected=5reads4smax each/EOFcursor0. Baselinecontent businesshashesmessage enprivateVM0600, sin texto/IDs printed/persisted; fechas>oldcutoff/S82, no created_at updated_at syntheticfields.7RootmonitorRED/GREEN no sockets; no persisted/renewal como2incrementales.60hard85exec130remote160SSH/STOPfirst. No counters/leases/jobs patch niMeliAMQP.

**Resultado PILOT-BUSINESS-BASELINE-1:** 2026-10-06T04:28:47.302724UTC/5.363sSSH0/PASS/PRIMARY5reads/cleanupclosed;planPAUSED/used0/untilREAL05:52:57.845UTC. Messagepostcutoff0selected/matchednoTrunc baselinehash8d832214a9ca5514e1e038062c3119e50f770f0a1ca6832007d03ab5e2c2794c/privatehashesOnly;1certquotaJun1→11 acquisitionSep11 retained, valid_untilOct4expired (metadata no validationproof);freshness3selected/unknownmissing2 no coverageinferida. **Inicio PILOT-ACTIVATE-APPLY-1:** 2026-10-06T04:30:22.767861+00:00;ONEcanonicalCAS PAUSED→ACTIVE conpreparedreceiptPIN+wholeplan stable/runtimepins3/scopesguardhistory82only/legacyOFF rechecked, mismos límites yuntil05:52:57.845UTC. Meli physicalceiling2500allretries 2000initial800150250300500+500maint/source300 Full0; noreset/reprepare/extension. SourceMONITOR frozen/7REDGREEN, RootboundedPRIMARY+≤1030planreads5s→ONEcanonicalpauseonfirsterror/guard/quota/day/deadline/monitorfailure+1messagehashdiff; no businesspayloads/IDs. AfterStopRootselectedworkerOFF graceful; pause noquiescenceinstantánea.

**Resultado PILOT-ACTIVATE-APPLY-1:** 2026-10-06T04:30:28.555053UTC/5.842sSSH0/PASS/ONEcanonicalCAS/readbackACTIVE/sourceexact/controlsverified;receiptPINb16b9918e351f29f8e1ac0e42c2b6e8ba3c462168579657f64e61f2c6f1ad853/runtime+VMprivate0600. Hasta05:52:57.845UTC ORIGINAL (no90min desdeactivate),500maintenancependingnaturalrollover. **Inicio PILOT-MONITOR-1:** 2026-10-06T04:31:16.100501+00:00;RootownedAPI3f7VMVPC 1PRIMARY+≤1030planreads/5s+1messagecontenthashdiff;monitoratfirstsourceerror/failedunit/issue/guard/quota/day/deadline/readerror→ONEcanonicalpauseCAS/exclusive0600receipt/no retry/reset/refund/leasechanges.30s sanitisedobservationframes/32KiBline2MiBtotal/no payloadID/text, elapsedwindowbounded5400hard5450remote5500SSH;source5untiloldsameUTC. Rootsolewriter/production; specialistsexitedfrozen. Pause doesnotproveinstantquiescence; followingnarrowworkerOFF+60settle required, no oldimage rollback.

**STOP PILOT-MONITOR-1:** 2026-10-06T04:32:25.364205UTC/69.807sSSH0(readprocess,no businessPASS);PRIMARY16started16completed/cleanupclosed. MessagespendingreasonValueError→ONEcanonicalpauseCAS PAUSEDtrue at04:32:25.318442/PINe56c2e08b99de3becdd413290aaa876c2cd9093d67f1eafe820438758f43a082/VM+runtimepreserved. Lastsnapshot69charged67sent/56initial+13maint/Full0/no refund;tailinflight finalcountersneedreadback. Initialclaims49/questions3/messages2/shipments2/orders0(existing12unitsreuse). Maintenanceorders9/questions2/messages2/others0. Messagebusinessdiff0selected/0changed, no2genuine gate. Firstwindow/ID/deadline05:52:57.845 retained, no repeatfailedsource/request/reprepare. **Inicio VM-PILOT-FORWARD-CLOSE-1:** 2026-10-06T04:33:45.547290+00:00;Rootforwardnewpins69/4f90/API3f7 unchanged ONLYworkerhistoryOFF+GatewayHOLDtrue newexclusiveoverlay, fullenvdelta2flags/0pull;workerfirstgrace60 thenGatewaynarrow--no-deps--pullnever, initialhealth+60settle/capacity≥5.450hard480SSH no broadrestart/legacy flagsre-enable/reset/oldimage rollback. Sourcecausependinglocal, no claim404/protocolfailurewithout evidence.

**Asignación local acotada CUOTAS/MESSAGES 2026-10-06T04:34:02.900944+00:00:** único writer CUOTAS para `modules/sheets/src/zeler_sheets/history_onboarding.py`, NUEVO `modules/sheets/tests/test_history_messages_checkpoint_resume.py` y su NUEVO `docs/sheets/zelerdata-historico-cuotas-mensajes-checkpoint-informe.md`. Explorar/reproducir ValueError decontinuación mensajes antesfix, NO afirmar causa productiva sinproyección segura. `modules/sheets/src/zeler_sheets/onboarding_sources.py` SOLOlectura/propuesta, noedit: validación identidadcheckpoint sepreserva; Core/Gateway/canonicalpilotoperator/config/deps/locks/Git/docscentrales reservadosRoot. TDDRED→GREEN fakes sin sockets/DB/envcreds, pruebasenfocadas aisladas SOLOestos3paths/sin suitegeneral. No producción/build/Git/agentes/otherarea. Ventana/ID/cutoff/consumos/checkpoints sepreservan; no borrar/rescribir pendientes ni actualizarend decheckpoint para ocultarmismatch. Si requiere otrofile/contrato, entregapropuestasineditar. Cese/hashes obligatorios antesRootintegración/controles. AMQPcongelado.

**Root unidad OPS resume misma ventana:** reservado únicoRootwriter `infra/operations/zelerdata_history_pilot.py`, NUEVO `tests/test_zelerdata_history_pilot_resume.py`, docscentrales. No otroagenttoca. TDDbeforebehavior: originalprepareappliedPIN + currentpauseappliedPIN/wholeplanhash + runtimecompatiblequiescente; patchúnico stateACTIVE, SAMEID/day/until≤originalprepare+90min/endUTC/currentcaps≤receiptboundedremaining/dailybudget/max2500, failclosed lease/race/unknown. No reprepare/newUUID/refund/reset/deadlineextension/job/checkpoint edits. Necesario para reanudación de ejecución ya autorizada despuésfixSource; prodresume solo trasgates/freeze/newworkerVERIFIED/controles actuales ysaldo/plazo restantes. CUOTASsource/test/report3 independientes; ninguna suitegeneral durante escritores.

**Resultado VM-PILOT-FORWARD-CLOSE-1:** 2026-10-06T04:36:19.406375UTC/153.89sSSH0/PASS/0pull/exactONLY2flagdelta/workerfirst+Gatewayrecreatednarrow/60settleReadyworker2components/GW2deps/free35665088512. HistoryOFF/HOLDtrue/legacyOFF/newpins69&4f90/API3f7 unchanged. **Inicio POST-STOP-CHECKPOINT-SHAPE-1:** 2026-10-06T04:39:13.524038+00:00;readonlyPRIMARY+oneplan max2explicitcommands tocompare messageperiodic sweep BSONdate vs immutablecheckpoint ISOstart/end, seller/sourcebool/countsonly/nopayloadID/text, finalcharged/sent69/67check. No repetir endpointfallido/archive1001/seed/admisión/counterreset/leasechanges.60hard85exec130remote160SSHSTOPfirst. HypothesisBSONmillisecondroundtrip fromCUOTAS3REDoffline, actualshape neededbeforeproductattribution.

**Entrega y recongelación 2026-10-06T04:45:27.071672+00:00:** CUOTAS literalENTREGADO;cese/3hashes source2b7a/test5cb5/report4f18 + strictcollector096 unchanged Rootverified; caller27lines/noreset/millisecondguardoriginalISO, realBSONfaithfulRED3+4PASS→GREEN7+focusedquality. RootOPSresume18new+29old+7source=54RootPASS; ruffformat/mypy2RootPASS. Ambos especialistascongelados/sinturnotests;Root4codepaths modificados(2source+2newtests),3docscentral+ownCUOTASreport;ningúndep/lock/config/code adicional. Fullgates exactsnapshotnewsiguenONLYownLinuxprofile0e221d445eed/rs0/Rabbit/sourcenohostmounts/ambientcredsunset;Rootexclusivowriterdesdeahora,cambioinvalidaevidencia. RuntimepermanecePAUSED69/67/historyOFF/HOLDtrue/Full0/until05:52:57.845original; noresume/buildnuevo hastaPASSfull.

**STOP focused Linux nueva unidad:** 2026-10-06T04:45:56.833143UTC/2.08s/exit2/collectionerror tests.test_zelerdata_history_pilot import; source1104snapshot unchanged. Localorder masked cross-package `tests` collisions aftergatewaytest imports. No generalfull inició; no exclusiones ni cambioRuntimeSource. RootmecánicoÚNICOwriter NEWresume testfile: self-contained samefixtures envezcross-test import,18+29+7=54localPASS/ruffformat/mypy2PASS. Lecturalocal Sourcehelper/BaseFake exacto, notnewproductionbug. Ambos agentes siguencongelados. **Recongelación 2026-10-06T04:47:44.436506+00:00:** solo ese testfile changed frente snapshotd787; nuevo1104/all907codebytesmodo freeze; mismosownprofile/rs0/Rabbit,DBfresh distinto, no nuevasinstalaciones. Rerunfocused+all gates/protected, STOPfirst; plazooriginal05:52:57.845 continúa/noreset/build/resume.

**Inicio NATIVE-REENTER-SAME-1:** 2026-10-06T04:49:08.727764+00:00;Laloprivatepilot actualUserTab1685092841, ONLYOrdenesSanasA1 exactexistingARRAY_CONSTRAIN(ZELERDATA_ORDENES(HOPEMOB,Sep1→2),4,4) reentryunchanged/oneattempt; no nuevosargumentos/date/seller/inactive6/compartir/tokenchanges. MenuRefreshprefixnoMatcheswrapperNOinvocado; leerUI actualeditorselector primero. RuntimePAUSED/historyOFF/HOLDtrue/legacyrecoveryOFF, Mongo-only esperado/provider0; backendfreshrequest yetunproven, completionUI/16cells maybecache NOinferfresh. No repeatifunchanged/error/grant.

**NATIVE-REENTER-SAME-1 UI:** exactformula fill enterededitor; firstpress selectorchanged(no_matches) beforecommit, freshsnapshot revealed comboboxA1 then ONEEnter confirmedsameformula/currentA2 outputunchanged/no newgrant. No repeatfmlainvocation. **Inicio NATIVE-API-LOG-READ-1:** 2026-10-06T04:50:28.869244+00:00;selectedAPI3f7onlyDockerlogs afternativeStart/max200records128KiB15s, parse INMEMORY outputONLYroutecounts/status/no payload/token/cookie/IP/IDs. No Mongo/Meli/otherlogs/restart/updates. boundedtail isnotglobalabsenceproof; no fresh nativeclaim without evidence.

**Resultado controles finales resume/source 2026-10-06T04:56:13.345519+00:00:** Rootfrozen1104/tar76db7abc2647614cd9c13512af4a96c5f3e7f2207959b915b587d29b1e71d10b/all907CODEcurrentbyte+modeexact. Full6446PASS20SKIP/402.282s; protected19PASS0SKIP5.666s;focused109PASS;ruff/formato/mypy669/direct/schemaPASS all8exit0/snapshotunchanged. Countsfromstandardterminalprogressglyphs cachedinlogs(no suiteinferida), fullfocusedfirstLinuximportFAILpreserved;only testfixture mechanicalfix. Docsupdatesindependent(no runtimecode edits). **NATIVE-SAME result:** UIformulaunchanged/4x4visible; logreadonly10records897bytes/0formula-route-lines (boundedtail—notglobalabsence), noproofoffreshrecalc/partialAPI; no furthernativeattempt/grant/6inactiveactivation. Rootpublishes ONLY8ownpaths2workunits, then ONEworkerCloudBuild exactmainVERIFIED; GW/API no rebuild. ProductionPAUSED69/67/untiloriginalsame; no newwindow/goalcompletion.

**Publicación Root:** Sourceunitb38dd19 + OPSunit0c7ef48568a13d1ce32bd79024b363be360c9484, ONLY8ownpaths/conventional/pushmainremoteexact/treeclean;all907codeblobs matchfinal76db frozen/6446+19/669gates. **Inicio WORKER-MESSAGES-BUILD-1:** 2026-10-06T04:57:29.828766+00:00;ONECloudBuild connectedcanonicalrepo exactmain0c7ef48568a13d1ce32bd79024b363be360c9484/modules/sheets/Dockerfile.worker/imageONE/optionsVERIFIED;NOlocalDockerbuild/uploadcheckout/GW/APIrebuild. MergedserviceASTproofAPIprogresssame,onlyworkercallerchanged. ProductionstillclosedPAUSED69/67/until05:52:57.845same; no productive source repeat/resume before immutable/provenance+rollout/controls.

**Resultado WORKER-MESSAGES-BUILD-1:** SUCCESS/VERIFIED buildd003b26e-cd2f-4c64-9aef-22af84161717/sourceEXACTmain0c7ef48568a13d1ce32bd79024b363be360c9484/canonicalartifactrepo/project/build/sourcePASS04:59:47.537963UTC/ONErequest/0VMdownloadsdeploy. Immutableworker`sha256:cdcccd2fd3996d6b59b8309ebc67efb6e2397cb1e6b2cc8badf2780d52f98061`. Localverifier initialwrong--image-map-fileflag STOP retained; corrected--map-out withSAMEcachedfiles0productiveRereads PASS, notbuildretry. **Inicio VM-MESSAGES-WORKER-DEPLOY-1:** 2026-10-06T05:03:35.266840+00:00;ONLYworker69→cdcc atclosedPAUSED/HOLDtrue/historyrecoveryrefreshOFF/Originaluntil05:52:57.845. Newexclusivepublicimageoverlay/map Root(no globaloverwrite), FULLrenderdelta ONLY1image/allEnv/GW4f90/API3f7 unchanged, installedpreflightSHA+normalcanonicalONEworkerbinding/cleanupOFF/noAPIattestationpull;freshroot≥5GiB/inodes/MongoSeparate/RAM, selected3runtimepins ready. ONEdirectpull240 thenONEworkerup--no-deps--pullnever150/60grace+60settle;hard550SSH580/STOPfirstnoautoretry/other-service-restarts. Prior69rollback ONLYclosedPAUSED preservespolicyjobs/scopes14, forwardpreferred. No resume/provider/planmutation inthisstep.

**Resultado VM-MESSAGES-WORKER-DEPLOY-1:** 2026-10-06T05:05:25.786610UTC/110.631sSSH0/PASS/canonicalONEworkerbinding/FULLONLYimageDelta/ONEpull+ONEworkerrecreate/initial+60settleReady2components/0restartOOM/historyrecoveryrefreshOFF/GWclosed4f90unchanged/API3f7. Rootfreepre35663036416/post35115220992+6216150inodes;Mongofree47457935360+3276153inodes/separatemount/RAMavailable1815363584 total4103168000/swap0. Newcdcc immutable/source0c7served, prior69retrievablecompatible ONLYclosedPAUSED;no resumedpilot/planwrites. **Inicio AMQP-MESSAGES-POSTDEPLOY-1:** 2026-10-06T05:06:58.236718+00:00;Freshread newworkerCDcc context ONLYEXPECTED_IMAGE literal changed(allfunctionsASTidentical/frozenreader816eunchanged),23HTTPGET/4srequests60read5cleanup95exec150remote180SSH;known104+≤23=127,oldunknownseparate. No TCP/declare/pub/ACK/Meli/Mongo/repair/failedprobe repeat. STOPfirst/no retry; freshconsumer/topologycheck afternewimage, not businessACKproof.

**Inicio PILOT-QUIESCENT-PAUSE-1:** 2026-10-06T05:08:13.372543+00:00;afterworkernewcdcc CLOSED60settle/planPAUSED69/67/HOLDtrue/historyOFF. CanonicalOPSfrompublishedtested0c7 viaAPI3f7stdin,PRIMARY+before+controlfind/CAS/readback+after=5reads ONEstatePAUSEDno-opCAS;wholeplanexactbefore==after required. Newexclusivequiescentreceipt0600 runtime+VMpins latest finalizedstate(afteroldpauseleasefinally), originalprepareb886unchanged. CaptureONLYprioridentifiedmessagesValueError tuple(reason,consecutive_failures,next_attempt_at), no clear/resetcanonicalerrors/checkpoint/quotas/data/leases. Observerprivate4RED/GREEN permits unchangedknownprior tuple ONLYwhennewfiximageverified; newerror changescounter/date/reason triggersSTOP, allguards/caps unchanged.60hard85exec130remote160SSH/no retries/newwindow/sourceendpoint.

**Resultado AMQP-MESSAGES-POSTDEPLOY-1:** SSH0/8.564s/23HTTP200/allcomplete/topologybindings10q3exchangesPASS/2liveconsumersreadyunacked0/5retry0/eventsDLQ31571411bytes preserved; **claimsDLQ1/241bytes NEW vsbaseline0**. Known127starts127headers125bodies+oldunknownseparate,0AMQPTCPpubMeliMongo; noLoss/ingress/globaladmissionFalse. Gate resumeSTOPpendingnewDLQcause, nottopologyrepair/pilotexpand. **Resultado QUIESCENTPAUSE:** 05:08:19.251941UTC/5.953sSSH0/PASSPRIMARY/ONEPAUSEDno-opCAS/wholeplanunchanged69charged67sent/originaluntil05:52:57.845;receiptPIN3c99db2dd8a2e0fd58ae8c9fd83dafefe847a73528eb346b4f7765b84092aa8d/runtime+VMpreserved. PriorValueErrortuplecount1/nextAttempt04:33:23.613 retained(noreset). **Inicio CLAIMS-DLQ-LOG-READ-1:** 2026-10-06T05:11:33.533127+00:00;READONLY actualVMid+CloudLogging selectedVM/seller82/eventworker.message.dlq timestamp04:02→now/cap10;outputONLYtimestamp/error_type/dlqclass/httpstatus/attempts, noevent/resource/business IDs/payload/token.0queueGET/dequeue/replay/ACK/pub/Meli/Mongo,45srequest/90s maxSTOPfirst/no fallback.

**Resultado CLAIMS-DLQ-LOG-READ-1:** readonly2GCPqueries/3.133s/selectedactualVM+seller82/time04:02→05:12/eventworker.message.dlq/cap10; ONEobserved timestamp05:04:38.671521113Z/attempts1/error_typeOperationFailure/dlq_classhttp_5xx/HTTPstatusMISSING. No queueget/body/dequeue/ACK/replay/pub/MeliMongo; Mongoexceptionclass no pruebaHTTP500 ni colección/código121. ClaimsDLQ1/241bytes retained; resume gateSTOP whileRootidentifiesactualcause. **Asignación CUOTAS readonly 2026-10-06T05:15:50.666508+00:00:** max4files core/history_work_intent.py,consumer.py,core/models/operational.py,infra/mongo/schemas/processed_event_claims.json; solo hipótesis/propuesta diagnósticoVMVPCexacto sin editar/tests/prod/Git/build/agentes/otro schema. Source3entregados no touched; AMQPcongelado. SoloRootdecidirá lectura/mutación compatible distinta después evidencia; no validator repair/replay/newwindow. Deadline05:52:57.845 original; data69/67PAUSED/historyOFF/HOLDtrue.

**Inicio CLAIMS-EXISTING-EXCEPTION-META-1:** 2026-10-06T05:17:10.780154+00:00;exactknownlogrecord05:04:38.671521113/seller82/eventworker.message.dlq/GCE/project, max1query1entry45s. Extractadditionalexistingexception ONLY inMEMORY →numericMongo code/codeName labels + applicationframe filenames/function names fixedallowlist/no messages/providerpayload/eventIDs. No anotherbusinessrequest/queueget/replay/Mongo mutation/schema assumptions. RootpriorlookupreadonlyfoundOperationFailure residualhttp5xx, sourceconsumer catchexc_infoTrue suggests tracebackavailable.

**Resultado EXISTINGEXCEPTIONMETA1:** pass1knownrow/1.673s/rawnotpersisted/exception3841chars→code112/WriteConflictTrue/TransientTransactionErrorTrue/validationFalse/unauthorizedFalse; driverframesonlylast14 omitted appframes, no claimschema121 repair. **Inicio CLAIMS-EXISTING-APP-FRAMES-1:** 2026-10-06T05:19:32.427268+00:00;sameEXACTexistingrecord positiveCode112, extractAPPframesonly that previouslast14trim didnot expose;max1query1record45s/MEMORYparse/norawmessages/IDs/driverdata saved. No repeatedbusinessdiagnostic or data mutation/schema query/replay.

**Resultado EXISTINGAPPFRAMES1:** 1existinglogquery1.099s/APPframesconsumer._handle_message:552→handle:1218→core.devoluciones_readiness.acquire_devoluciones_operation:137 freshness.update_one; preceding resultcode112/WriteConflict/TransientTransactionError. Exactfailedstage BEFOREgatewayfetch (readcode), notschema121/upstreamHTTP5xx. PreserveDLQ1/no replay. **Asignación CUOTAS TXN TDD 2026-10-06T05:22:44.027946+00:00:** RootreservaSharedCore `core/src/zeler_platform_core/devoluciones_readiness.py` únicoRootwriter. CUOTASpuedeescribir SOLO NUEVO `core/tests/test_devoluciones_acquire_transient.py` y NUEVO `docs/sheets/zelerdata-historico-cuotas-transient-acquire-informe.md`; entregarpropuesta exacta de retryDBbounded dewholeABORTEDtxn code112+labelTransientTransactionError BEFORE anyMeli, máximo3DBattempts/frozenoperationId/attemptToken/coverage/fence/lease no newbudget/time. No retryUnknownTransactionCommitResult/auth/121/nontransient/no quiescencefaker. REDcontraSourceactualfakesTxnAbort faithful + GREEN againstproposalprivateinMEMORY (no sharedsourceedit); testsnoforeignDB/sockets/ambientcreds/prod/Git/build/agentes. Rootaplicarápropuesta SOURCEsoloafterentrega+cese ysourceTDDreenforced; generalgates no mientraswriteractivo. Corebehaviorpotentialimagesimpactmustbeanalysedratherthanbuildall; no productiveresume/replay/newwindow hasta gates. AMQPfrozen/sin tareasCUOTAS.

**Encargo AMQP original1relay propuesta 2026-10-06T05:28:30.338885+00:00:** agentúnicowriter private`claims-one-recovery-20261006/{recover_one.py,test_recover_one.py}` ypropioNEW`docs/sheets/zelerdata-historico-amqp-claims-one-informe.md`. PrepararNOEXEC tool defaultdry/no sockets, interfaz RootmáximoONEoriginalclaimsDLQ(expected1/241bytes)+expectedEventIDsha256+seller82+wholebodysha/shape, ONEmandatorypublisherconfirmed exactbody→existingretry5s route, ACKoriginalsoloaftertypedconfirm; failure/ambiguouspub retainsoriginal/no automaticretry/no resetheaders/deliverycounter/nonce/sourceDate. Scope0delete/repair/Full/Meli/Mongo/agentes/Git/build/testgeneral. No fakebusinesspub; actualoldmessageRootonlyandonlyaftercode112fix/gates/newworker+SAMEactivewindowremaining until05:52:57.845, no other315eventsDLQ. Ambosfakefocusedpuedenparallel SOLOno sockets/DB/pueros isolatednewtmp own logs, Rootstillsoleprod. Si rawbodyinspection needed happensVMmemory/no logpayload/IDs/text/envsecret. BrokerclientTLScleanupunknown preserved, neveranotherprobejustimprovecierre; proposeprecisebudget/noBlindrelay/duplicationrisk andidempotencycheck. RuntimeexecutionNOTauthorisedbythisdelegation itself.

**CLAIMS-EXACT-EVENT-HASH-1:** 2026-10-06T05:29:33.790603+00:00;oneknownexistinglogrecord/field event_id ONLYinMEMORY→SHA256privateexpected selector/rawIDnotprinted/persisted. No DLQget/replay/Meli/pub yet. Code112+TransientTransactionError/acquirefreshness stage confirmed; CoreDB-only3txnproposalpending, no validatorrepair/permission expansion. Relayfuturetypedconfirm→ACK ONLYoriginalsinglemessage followingfix/gates/SAMEwindow;neverforgedbusiness/other315DLQ.

**Congelación Core112/relay 2026-10-06T05:38:41.707745+00:00:** CUOTASproposal/test+report delivered/cese7GREENshadow,RootsharedCoreexactpatch bodyonce+argsASTunchanged /RootRED3+4→GREEN7new+11existing18PASS/quality2; DBmax3totaltries112+label andNOunknowncommit, no businesscallbacks/newidentity/reset. AMQPprivateRelaybe0e/testb98a/report7f3e6fakePASSquality2/hashRootverified/cese. Todoswritersfrozen; RootgeneralONLYisolatedownprofile0e22/sourcenamedDBfresh/sourceRO/rs0Rabbit/final1107files snapshot. ActualcorecallerWorker affected; APIhandlerReadOnlyonly,DispatcherCloudRunclientnotStageExecutor AST/callgraph evidence; bootstrapJOB futurestale acquire needsverify/buildbeforefutureexecution, notstartforprotectedpilot13. Goalnotcomplete/current69/67PAUSED/Full0/until05:52:57.845unchanged; relayNOTexecuted/duplicatePossibleevenconfirmACKlocal, strictfreshGate/ToolNOOPsource originalONE241bytes only, no global315replay.

**Core112 conjuntos PASS 2026-10-06T05:47:46.618854+00:00:** frozen1107/tar5e19ae784a67311c43a8668362cae3d5ebded1bc07616bbe82eaeeb14aaa92d6 all908currentCODEbytes/modeexact, full6453PASS/20SKIP/395.964s;protected19PASS5.798s;focused127PASS/ruffformat/mypy670/direct/schema all8exit0/sourceunchanged. Bothagentscese beforegeneral; Source once bodyguards untouched; RootpublishesONLY5ownpaths Core/test/2ownreports/ledger. SelectedaffectedWorker onlyrebuild/rollout; bootstrapJOB affectedcallerfutureverify/buildbeforefutureexecution(notdispatcher/API/GW/currentprotected13), no hiddenstale-runtimeclaim. Originalwindow05:52:57.845/69/67/Full0 remains; sourceDLP1 not yetrecovered/pilotnotresumed/nodataRootreset.

**WORKER112BUILD VERIFIED:** abd8a659-33d7-4521-9725-44c4af71c2e9/sourceEXACTmain412360169adc90dd04cd853337bcb895decde464/SUCCESS/optionsVERIFIED/canonicalPASS05:50:26.460214/ONErequest/immutableworker0df26cd905e49ae7e1d0185e967d1f0090491881aba237de86a3fa61a17610bc. API/GW/Dispatcher not affectedservedacquire;BootstrapJOBfuturecallerdriftverify/buildbeforefutureexecution(not start/resetprotected13). **Inicio VM-ACQUIRE112-WORKER-DEPLOY-1:** 2026-10-06T05:51:26.848657+00:00;ONLYworkerCDcc→0df26 withsameALLenv/historyrecoveryrefreshOFF/GWHOLDtrue/planPAUSED69/67/full0. Freshroot≥5GiB/inodes/Mongoseparate/RAM/3selectedpins/currentFULL7-filecompose→ONLYimageDelta/newoverlay/mapexclusive/normalcanonicalONEworker/no cleanup orAPIattestation. ONEdirectpull240/ONEupworker150--no-deps--pullnever/60grace+60settle/hard550SSH580; STOPfirst/noretry. No productivepilotresume/relay;until05:52:57.845originalremains, specificprórrogarequest pending(NOTreceived), notappliedunderbroadauthorisation. Safeclosedrolloutindependentcancompleteafteroriginaldeadline; no newclock/UUID/refund.

**Originalwindowexpired observedclock05:52:59UTC:** no resume/relayexecuted, prórroga authorizationpending/notreceived; no newdeadline/UUID/prepare/refund. **Resultado VM-ACQUIRE112-WORKER-DEPLOY-1:** 05:53:22.234682UTC/115.51sSSH0/PASS/ONEpull+workerup/fullONLYimageDelta/new0df26/source4123601/canonicalbinding/initial+60settleReady2/0restartOOM/GWclosed4f90/API3f7 unchanged/historyrecoveryrefreshOFF. rootfreepre35111440384/post34375737344,inodes6207384;Mongoseparate47457710080/inodes3276153/RAM1888555008 total4103168000swap0;priorCDccclosedPAUSEDrollbackretained. **Inicio PILOT-ORIGINAL-EXPIRY-1:** 2026-10-06T05:56:52.994098+00:00;readonlyPRIMARY+oneexactSplan projection selectedclock/IDbool/counters/Full/sources, max2reads4seach/60hard85exec130remote160SSH/noothercollection/mutations/MeliMQ, confirm expiredoriginaluntil+retainedbalancesinsteadassumption. STOP/no retry.

**Resultado PILOT-ORIGINAL-EXPIRY-1:** 05:56:58.960247UTC/6.077sSSH0/PASSPRIMARY2reads/cleanupclosed; exactsameEID/statePAUSED/until05:52:57.845expired/limit2500/69consumed67sent/total56incremental13/source5noFull/fullused0. No automaticextension/refund/reprepare/relay; requestprórroga específica pendingnotreceived. Rootupdatedhandoff§13/control; QA6453 andruntimeworker0df proven, goalacceptance stillNOTdone.

**Inicio NATIVE-EQUIVALENT-HEADER-1:** 2026-10-06T06:09:40.064718+00:00;independentauthorisedMongo-onlyread sameLaloprivateSheetOrdenesSanasA1/16cells, ONLYencabezadosliteral si→SI (_headers_requested.strip.casefold verifiesTrueboth), sellerHOPEMOB/Sep1→2/todos/buyerempty/ARRAY_CONSTRAIN4x4 unchanged/inactive6untouched; no Token/OAuth/Scope/networkMeli/acquisitionbudget/day/deadline change. Googleofficialcustomfunctionguide sayseditfunctiontriggerrecalc/deterministicargs, no NOW/RAND/extraarg/tempempty/cachefake. ActualUIoriginalfmlaverified beforeoneedit;≤1nativecall/STOP onerror/newgrant, nextboundedAPIlogcorrelation+visualread neededNOTassumefresh. OriginalEID69/67/expireduntilPAUSED remains; specificprórrogapendingnotreceived.

**NATIVEHEADER1 UIresult:** ONEsi→SI commit/displaysguardando then4x4 effectivevisual/no errors/header+3rows at100% preserved; other6tabs untouched. ThisUI isnotalonefreshproof; **Inicio NATIVE-HEADER-LOG-READ-1:** 2026-10-06T06:11:53.273850+00:00;selectedAPI3f7ONLYDockerlogs afterexactoneheaderEdit/max200rows131072bytes/15s parseRAM/printONLYroutecounts+HTTPstatus(no payload/buyerID/token), hard60/noDB/Meli/MQ/mutations; no retry/fallback.

### 6 octubre — prórroga explícita sin reinicio (06:17:23 UTC)

- Usuario autorizó primero el límite 06:30 UTC y después una prórroga adicional
  de hasta dos horas si era necesaria. Se elige el límite absoluto conservador
  **08:17:23 UTC / 02:17:23 Monterrey**, dos horas desde la recepción de la
  segunda autorización; no desde la aplicación futura.
- Única ejecución: `868b413e20184befb7e8358e0051924f`. Deadline original
  `05:52:57.845 UTC` se conserva como lineage. Última lectura: PAUSED,
  69 intentos cobrados / 67 enviados. Total 2500 y caps originales intactos;
  sin UUID nuevo, prepare nuevo, refunds, resets o Full.
- Autorización recibida; extensión **aún no aplicada**. Root reserva
  `infra/operations/zelerdata_history_pilot.py`, monitor y ledger.
- CUOTAS: único escritor de
  `tests/test_zelerdata_history_pilot_extension.py` y
  `docs/sheets/zelerdata-historico-cuotas-extension-informe.md`; propone contrato
  mínimo de extensión con RED real; no edita OPS compartido ni producción.
- AMQP: único escritor de helper privado `claims-one-recovery-20261006/recover_one.py`,
  su `test_recover_one.py` y
  `docs/sheets/zelerdata-historico-amqp-claims-one-informe.md`; adaptación RED/GREEN
  únicamente a autoridad de plazo explícita, sin ejecutar transferencia.
- Ambas pruebas enfocadas usan solo fakes sin red/BD/puertos. Congelar ambos
  escritores antes de controles conjuntos. Aceptación final sigue pendiente.

#### Evidencia nativa independiente — sin nuevas fórmulas ni grants

Lectura UI de Settings confirma `https://sheets.zeler.ai` y token guardado
(solo booleano; no lectura/copia/modificación de credencial). El historial del
proyecto Apps Script asociado muestra `zelerdata_ordenes`, función personalizada,
**Completada el 6 octubre a las 00:09:50 Monterrey / 06:09:50 UTC**, 0.667 s.
Corresponde al único cambio semánticamente equivalente `si` → `SI` empezado a
06:09:40 UTC; la hoja mostró encabezados más tres órdenes en el 4×4 original.
También existen ejecuciones completas a 06:08:49 y 06:08:50 UTC. No se requieren
más reentradas. La cola/log API acotada sin coincidencias no probaba ausencia de
recalculo. Esta evidencia es readback nativo fresco, **no** certificación de
cinco fuentes ni dos cambios incrementales reales.

#### Entregas congeladas y control final de la prórroga

- CUOTAS ENTREGADO; NO SIGO MODIFICANDO: 23 fakes PASS/0 skips,
  ruff/formato/mypy enfocados PASS. Test
  `d445d9820bed4119dfd37c788e6a3fe0e3eb47243ff987330482a20eb8d18d04`;
  informe `573ef89b3042d277d026025df2c077f795294490eab1e173d2d7cd404492b4cf`.
- AMQP ENTREGADO; NO SIGO MODIFICANDO: 8 fakes PASS, checks enfocados PASS.
  Helper `29ed4bc46851a29b17708cdc733b9f9bff45b7f1d7ed3bd9f9b24d8ca160fdce`;
  test `801e532bf53379f94e7673cc2964c9c8054972ccedaf52fdb98d508b01fc89d4`;
  informe `ce648519bc1e957bfaa61c328e0be36a634c50e612b15dd478e1c242c9071191`.
  Originales respaldados/pinados antes de editar; sin transferencia real.
- Root integra `extend-paused` y resume con recibo aplicado; plan patch solo
  `execution_until`, lineage externo en recibo exclusivo, sin modelo/schema nuevo.
  Rama legacy sin extensión conserva límite original. Autoridad recibida
  SHA `f71b683854e4c002933ed38df09a7356063280e6f71e56a91f7593ea4ffd1679`.
- Ambos escritores y código Root congelados antes de gates conjuntos. Exploración
  posterior AMQP es solo lectura de elegibilidad, sin código ni pruebas.
  Target general: perfil Linux local propio, Mongo PRIMARY/broker aislados,
  datos desechables nuevos, sin credenciales ambientales ni conexión productiva.
  No suites generales mientras se escribía código; controles ahora pendientes.

**Gates finales prórroga:** snapshot completo 1109 paths, tar
`129c954bc256382aaf43171d940a6b915a5e20cc4bec6e5b2e80902ef641f51a`,
bytes/modos exactos antes/después en target propio aislado. Ocho gates exit0:
focused **70 PASS** (1 warning de caché por source RO, sin fallo; preservado),
ruff/formato, mypy **671 archivos**, direct-Meli, schemas, full **6476 PASS /
20 SKIP** (410.206 s supervisados; pytest407.53 s), protected **19 PASS /
0 SKIP** (5.819 s). Suite 06:29:38→06:36:28 UTC. No skips como aceptación.
Código actual completo coincide con snapshot validado; actualización de evidencia
MD posterior se valida separadamente. Sin cambios runtime de producto:
**no nuevos builds, pulls ni imágenes** para este operador OPS.

Elegibilidad AMQP sigue bloqueada hasta comprobar clave efectiva: publisher usa
`classified.idempotency_key` en header, distinto de `event_id`/`message_id`.
El hash del evento no autoriza marcar idempotency_eligible=true. Root verificó
classifier y resolución canónica del webhook almacenado; aún falta lectura real
readonly de esa identidad y markers/claim, y cotejo del header antes de publish.
Sin GET de negocio, publish, ACK ni reproducción del original hasta ese gate.

**PILOT-EXTEND-PAUSED-1 aplicado:** 06:38:03.962291 UTC, 8.562 s, SSH0,
PRIMARY y **un CAS** con readback integral: mismo executionID, PAUSED,
**69 cargos / 67 envíos**, nuevo límite absoluto **08:17:23 UTC / 02:17:23
Monterrey**. Cambió únicamente `execution_until`; todos los demás campos exactos
conservados. Deadline original `05:52:57.845 UTC` en lineage externo.
Recibo aplicado SHA
`3a2117639ad3255a303d61d6a843e2815e2eb8aca839cba2e7b5a2e8102bdd59`;
plan resultante `98cbeb7e8fa7efe33bff67f89206b0a5e0aa45480ca435dfc1ed03e3764d1a7f`.
Operador publicado `11000adce98c183c5061049f4512e64e58dab371`, remoto exacto y tree
limpio antes de esta actualización MD. Pins gateway4f9/worker0df/API3f7 saludables,
history/recovery/refresh OFF y gateway HOLD=true comprobados antes del CAS.
No nuevos builds, downloads, recreates, UUIDs, prepare, crédito ni replays.
Saldo aritmético no renovado: inicial orders800/questions147/shipments248/messages298/
claims_returns451; mantenimiento487, dentro del total original2500.

**Siguiente:** reanudar con recibo de extensión real pinado y monitor de fecha exacta;
transferencia original claims condicionada a clave canónica de webhook/markers/claim
readonly y hash del header real antes de publicar. Un event_id no sustituye esa
identidad. Cero GET/publish/ACK de negocio hasta ese gate. La autorización de tiempo
no reduce aceptación; fuente por fuente, parcial API normal y dos incrementales
realmente cambiados siguen pendientes. Full excluido; objetivo NO completado.

### Continuación 6 octubre — entregas auxiliares delimitadas (06:40 UTC)

Turno anterior fue PROGRESO (prórroga aplicada/publicación/quality), no cierre de
objetivo. Deadline **08:17:23 UTC** absoluto; no otra extensión automática.

| Propietario único | Archivos exactos | Encargo/estado/dependencia |
| --- | --- | --- |
| AMQP | Privados `claims-one-recovery-20261006/recover_one.py`, `test_recover_one.py`, nuevos `eligibility_reader.py`, `test_eligibility_reader.py`; propio `docs/sheets/zelerdata-historico-amqp-claims-one-informe.md` | RED/GREEN de header hash + scope efectivo; lector normal readonly inyectado, cero producción. Root necesita hash de clave/markers/lease reales antes de relay. ASIGNADO. |
| CUOTAS | Nuevos privados `source-progress-20261006/progress_reader.py`, `test_progress_reader.py`; propio nuevo `docs/sheets/zelerdata-historico-cuotas-progress-informe.md` | Lector readonly acotado de fuentes/calendarios/certificados y baseline de cambios reales, sin fechas sintéticas. Root ejecuta. ASIGNADO. |
| Root | Ledger/docs centrales, config Compose/flags, supervisor/monitor, selección de log solo RAM, Git/producción | Ningún archivo especialista se edita hasta entrega+cese. Suite final previa cerrada; nuevas pruebas auxiliares solo fakes aislados, sin puertos/BD/red. |

**Corrección previa a cualquier operación:** scope real de consumer es
`zeler.sheets.events` (consumer.py:132 y wiring EventClaimGate; Core
history_work_intent.py:27), **no** `sheets.events`. Fuente servida412 y HEAD sin delta
en esos archivos. AMQP detectó el literal equivocado en el encargo; corregido
antes de consultar markers/claims o broker. El alias corto habría causado falsa
inferencia de ausencia. No se renombran namespaces ni se mutan markers.

**AMQP entregado+cese:** helper hash
`0b2b7b621c2d7323ceeb0975a1df593b60d14eb920aed519bc0b111720fa9c00`,
lector `c60fe436c046111ecf4933ed2b3a925e4487346d3dab2bc2a59aa353f2ba6472`;
16 fakes PASS/0 skips, ruff/formato/mypy4 PASS. Header real debe coincidir con hash
canónico y scope `zeler.sheets.events` antes de cualquier publish/ACK.

**CLAIMS-IDEMPOTENCY:** primer ensamblado detectó SyntaxError local `Trueor` tras
un GET exitoso al log existente; 0 SSH/VM/Mongo/AMQP. STOP preservado, separación
corregida y source completo compilado antes de otro acceso. Primera lectura VM
real PASS **06:51:37 UTC**, 7.613 s, PRIMARY, codec tz-aware, cuatro queries readonly.
Webhook canónico y tenant verificados; clave efectiva SHA
`26e3452804f01cc57bc7b6a25ea0ad8e5afe1fa71184316b41f11fce7e0367bb`;
marker completado activo=false, claim disponible=true. Se conserva gate atómico
normal; esa lectura **no reserva ownership** y debe refrescarse antes de gates20s.
Dos lecturas conocidas del mismo log; cero bodyGET/publish/ACK, cero Meli/writes;
selector y clave crudos solamente RAM, no persistidos ni impresos.

Root prepara únicamente one state-CAS resume + monitor2 con deadline exacto,
recibos nuevos exclusivos y guard probado de error previo sobre copia (sin limpiar
estado canónico). Arming privado flag-only verificado con fakes e igualdad de
render; ningún image download ni cambio a API/Gateway. **Aún no ejecutados.**

**SOURCE-PROGRESS-BASELINE-1:** PASS07:00:24UTC5.431s/PRIMARY9queries/cleanupclosed.
Plan PAUSED69/67, Full0, calendario12 meses y checkpoints/hash retenidos. Orders12
unidades completed; questions1pending, shipments2pending, claims37pending y
messages error previo ValueError pendiente. Readability anual **no acreditada**
por esos contadores. Un certificado June y freshness independientes observados;
no validación conjunta vector/facts. Rango orders observado termina Oct4, por
lo que API normal Sep25–Oct5 necesita responder su cobertura real, no una etiqueta.
Baseline de campos de negocio posteriores al cutoff: subset BSON orders29,
questions1, messages0; hashes privados, no IDs/texto, no ausencia global ni dos
ciclos auténticos. EOF real validado, sin singleBatch forzado ni getMore.

CUOTAS entregó normal API operador separado: 22 fakes PASS/sintaxis GS+CJS PASS,
dosPOST max/true→false, endpoint exacto, redirectsOFF, token solo UserProperties.
Docs Google actuales sí incluyen timeoutSeconds; recuerdo anterior corregido
antes de ejecutar. Configurado9s por POST más guard20s entre requests, sin afirmar
wall20 garantizado. Run wrapper registra solo receipt whitelist, sin valores de
negocio ni secretos. Root añade solo archivo auxiliar al proyecto privado; cuatro
originales/manifest/scopes/tokens/celdas intactos. Sin Marketplace/deploy/triggers.

**API normal real PASS:** Root ONE RunV1 07:10:56→07:10:57UTC, source probado348b
exact9958bytes/UI clipboard+WebCrypto. Dos POST reales: parcial HTTP200, 28 órdenes/
28 filas útiles, noticePARCIAL/coverage.exact=false/acquired_rows_only/rango sin
certificar; control exacto HTTP200 envelope DATA_UNAVAILABLE. No celdas, grants,
tokens nuevos ni Marketplace. Captura privada `normal-api-proof-20261006/normal-api-pass.jpg`.
Resumed firstframe posterior aún69/67 y preflightAPIrecoveryOFF: sin cargo seleccionado
Meli durante esas dos lecturas; no afirmar cero global de otras cuentas.

**Resume2 real:** state-only CAS07:13:39.810926UTC, misma ventana/presupuesto/saldos,
recibo `13afb2b9e54fa634988ac4ccce3671e4f4beef458a2b1e36eca30341549fe6aa`.
Monitor2 permaneció vivo por handleRoot y fue observado, sin reiniciar por timeout;
history OFF, ordinaryclaimsmaintenance sumó3 cargos reales72/70.

**Relay original una vez:** setup1 escogió API antigua sin Corehistory_work_intent;
Root runtime importspec y orden del loader probaron fallo antesfactory/Mongo/GET,
no inferido solo por recibo ausente. Selector corregido ONLYworker0df, API pin separado.
Primer actual Worker relay07:22:18.570303UTC: 1get original241B, headerK26e correcto,
body/properties exactos, 1publish mandatory confirmado y 1ACK local. Cleanup tool_error/
waitererror => **STOP**, duplicate_possible=true; no remoteclose/ACKprotocolproof,
no atomicmove/cleanPASS y **ninguna repetición de publicación**.

Root pause de seguridad07:23:27.654508UTC (un CAS cambio real),75cargos/73envíos,
maintenance19, Full0/until08:17:23 sin reset/refund. Monitor2 detectó PAUSED y emitió
segunda pausa state-only idempotente07:23:31.485433 (registrar ambos intentos), mismo
hash9dc6; cerrado121queries/SSHterminal0, no handle vivo restante.

**Entrega real confirmada sin replay:** postManagement23GET PASS: claimsDLQ0/source0/
retry50/all5retry0 y315eventsDLQ preservados. Lectura canónica exacta07:27:49UTC
PRIMARY2queries/Codecaware: marker completado activo=true para MISMOeventhash4371,
claveK26e y scopezeler.sheets.events. No es solo consumer-ready. Publicación/ACKlocal+
cola0+marker normal completado prueban ese original; cierre ambiguo y no-loss global
siguen sin certificado. KnownMgmt196; lecturas antiguas de consumo desconocido aparte.

**Siguiente bloque de seguridad local:** resume extendido necesita soportar una
pausa posterior real sin falsificar recibo inicial. CanonicalOPS es writerRoot;
CUOTAS solo NUEVOS `tests/test_zelerdata_history_pilot_extension_repause.py` y
`docs/sheets/zelerdata-historico-cuotas-repause-informe.md`, RED real+propuesta con
originalpause3c9 separado/currentpauseA384+hash9dc6/consumptionreceipt real75/73/19.
No nueva extensión, UUID, prepare, imágenes, reset ni edición de checkpoints.
Fuente por fuente/rangos reales y dos incrementales cambiados aún pendientes;
pilotoPAUSED/objetivo NO completo. No再pub del original ya completado.

**Re-pausa implementada Root+validada:** currentpause wholehash siempre comprobado,
originalpause3c9 para lineage/clock de ext3a2, consumo externo REAL
`6c072b63ee0a622aca7aa690fac624687bbddd6c23f8a5ef42a3fd6919384ee1`
(75/73/19, innerpause560a/hash9dc6) liga monotonicidad; saldo actual por fuente/día
no mayor que ext inicial. Defaults None preservan rama legacy/primerresume.
Un CAS exclusivamente state; no recibos viejos reescritos/otro deadline/UUID/prepare.

Ambos especialistas+código Root congelados. FINAL1113 paths/tar
`2fe41165e14ddc970d81fadc1e9b5afe278de6e291d7433bfb4d49d93b212031`,
8gates exit0/snapshot íntegro: focused98PASS(1warning cacheRO),
full**6504PASS/20SKIP** 07:34:27→07:41:09UTC/401.232s; protected19PASS/0SKIP5.899s;
ruff/formato/mypy/direct-Meli/schemas PASS. No skipscomoaceptación. UnidadOPS-only,
ninguna imagen nueva/pull/deploy para este delta.

### Continuación 6 octubre — histórico detenido por Questions 410

Publicación OPS verificada: `main`/remoto
`861f6c81621424334ae98138955e85619c2fe57c`; árbol limpio antes de este apéndice.
No nuevos builds: solo cambió la herramienta del operador, no las imágenes.

| Intento Root | Evidencia / resultado / consumo |
| --- | --- |
| Arming local inicial | Import `datetime.UTC` no disponible en Python 3.10 del host; fallo antes de funciones/red/Compose. Se conservó STOP y se corrigió solo el alias privado a `timezone.utc`. |
| Arming real 07:46:47.429727 UTC | PASS, 84.99 s/SSH0. Exclusivamente worker HISTORY false→true, misma imagen `0df26cd…`; cero pulls. API/Gateway/env restantes intactos; HOLD=true, recovery/refresh=false. Tres componentes saludables, restart0/OOM=false y comprobación tras 60 s. Plan todavía PAUSED75/73. |
| Resume3 07:47:38.702423 UTC | Un CAS state-only real, misma ejecución/caps/cutoff/deadline. Recibo `12756846e7de1600d70ab0c62793a434bfa90e687d6778dbe22fde4b8ef308d1`. |
| Monitor3 STOP 07:47:53.844043 UTC | Questions failed_units1; pausa canónica inmediata. **81 cargos / 79 envíos**, 24 maintenance + 57 iniciales, Full0. Un CAS real, sin reset/refund/checkpoint edit. Monitor terminal07:47:54.375936 UTC/6 lecturas/cleanup cerrado/SSH0. |
| QUESTIONS-FAILED-JOB-SHAPE-1 | STOP por forma/cap; no inferencia de ausencia ni repetición del proveedor. Recibo original preservado. |
| QUESTIONS-FAILED-SCOPED-COHORT-1 | PASS07:52:13.258522 UTC, PRIMARY/2 comandos/1 job. `source_rejected`, attempts1, updated07:47:51.508, available08:02:51.508, lease=null. Rango original 2025-09-24→2026-09-24 retenido. |
| QUESTIONS-EXISTING-FAILURE-LOG-1 | STOP por límite30 del selector de logs existente. No nuevos requests Meli; ninguna ausencia global inferida. |
| QUESTIONS-EXACT-PROXY-REJECTION-1 | Una fila exacta existente `proxy.call`: 07:47:51.503777056 UTC, `/questions/search`, upstream HTTP410; correlación con el job, no causa inventada. |
| QUESTIONS-CHECKPOINT-SHAPE-1 | PASS08:14:30.779453 UTC/4.936 s/PRIMARY4 comandos/cleanup cerrado/SSH0. Mismo job hash `c300216c…`, acquisition_id==job_id; **discover / page_sequence3 / next_cursor_present=true**. Plan sigue PAUSED81/79/24. Cero writes/Meli/AMQP/getMore; cursor literal nunca emitido. |

Pausa final `monitor3-pause.json`, SHA256
`47ba2f0637d49f12b8f8cdcb370d91fd2b5b72120afe8504b613e4fcc51a1848`;
plan completo
`153a6fd318b9cb7804f84b12b61841a101a21deeda068ea0a5bcbf9e49163a91`.
Mismo execution_id y límite absoluto **08:17:23 UTC / 02:17:23 Monterrey**.
HISTORY está ON, pero la autoridad presupuestal está **PAUSED**; no confundir
flag habilitado con permiso para enviar. No nuevos sends/replay tras el STOP.

Ruta histórica real `HistoryQuestionsWorker→QuestionScanStaging` ya envía
`api_version=4`, `search_type=scan` y, al continuar, `scroll_id`; el proxy conserva
`query_params.multi_items()`. Añadir v4 no sería un fix. La
[documentación primaria de scan](https://developers.mercadolibre.com.mx/en_us/manage-questions-answers/items-and-searches)
indexada establece expiración de scroll_id de cinco minutos (apertura directa
403). La pausa anterior superó tres horas: **caducidad es una explicación
compatible**, no prueba del cuerpo/causa exacta de ese410. No se reseteó cursor,
checkpoint, generación, job, datos, plazo o cuotas para comprobarla.

CUOTAS recibe únicamente exploración local readonly de lifecycle en tres archivos
exactos: `modules/sheets/src/zeler_sheets/history_questions.py`,
`modules/sheets/src/zeler_sheets/history_continuation.py` y
`modules/sheets/src/zeler_sheets/history_acquisition.py`. Sin escritura, pruebas,
red, producción ni agentes adicionales; propuesta de preservación, no permiso de
reinicio. AMQP continúa entregado/cese. Root conserva todos los documentos/Git.

**Aceptación actual:** Sheet nativa PASS; API normal parcial28 órdenes + guard
exacto PASS; mensaje original CLAIMS completado por consumidor PASS (cierre del
relay sigue ambiguo, no repetir). Cinco fuentes/calendario anual legible y **dos
ciclos incrementales genuinamente cambiados NO acreditados**. Objetivo NO completo;
no degradar estos gates a health, colas vacías, contadores o pruebas unitarias.
