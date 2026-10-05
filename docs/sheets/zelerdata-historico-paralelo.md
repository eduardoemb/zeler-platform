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
| Estructura AMQP | AMQP prepara / coordinador inspecciona | STOP: request11 HTTP404 en retry1s; 13 GET Management acumulados del tramo ampliado. |
| Existencia exacta de retry1s | AMQP prepara / coordinador opera | Broker404 confirma ausencia; cleanup tool_error, STOP y sin repetir. |
| Reparación puntual condicional | Coordinador | Propuesta preparada; NO autorizada ni ejecutada. |
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
condicionada a `NOT_FOUND` ya confirmado, todavía NO autorizada.

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
