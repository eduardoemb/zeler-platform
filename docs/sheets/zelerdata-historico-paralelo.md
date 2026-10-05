# ZelerData: coordinación de CUOTAS y AMQP

**Asignación local, no aceptación del producto.** Dos especialistas independientes
con archivos exclusivos; el coordinador integra y es el único operador de Git y
producción. El usuario reanudó trabajo local y coordinación el 5 de octubre de
2026. Los permisos productivos previos siguen condicionados; Full sigue excluido.

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
| Publicación/builds afectados | Coordinador | Calidad final, cambios propios delimitados y commit fuente exacto en main/remoto. | CÓDIGO PUBLICADO, remoto=HEAD limpio observado; builds0/STOP por gate AMQP. Solo gateway+worker afectados, no API/otros. |
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
