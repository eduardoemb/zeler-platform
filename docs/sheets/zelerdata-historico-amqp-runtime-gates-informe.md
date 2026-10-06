# ZelerData: gates AMQP restantes para rollout cerrado y aceptación

**ENTREGADO; NO SIGO MODIFICANDO.** Auditoría local, sin producción, pruebas,
código/config/helper nuevo, builds, Git mutante ni agentes. Solo este informe.
**Faltan snapshot AMQP fresco, prueba aislada de entrega y rollout de352;**
la conducta real WAIT/ACK/backoff del worker nuevo solo puede comprobarse después.
No equivaler reparación estructural a piloto seguro ni aceptación global.

## Quick path de Root

1. Registrar scope y presupuesto de cada operación; conservar errores/consumos.
2. Nueva lectura completa23 tras reparación y contexto fresco de capacidad/readiness.
3. Preparar y aprobar por Root el scope cerrado de la prueba temporal de abajo;
   implementar/verificar offline por asignación nueva antes de operarla. Nada implementado aquí.
4. Con gates predeploy resueltos, rollout cerrado worker69d9 primero/gateway866d después;
   HOLD/guard82/lanesOFF/API intacta; nunca base Compose sola.
5. OAuth legítimo y trabajo real, saldos/plazos canónicos y evidencia de WAIT/ACK/backoff;
   aceptación exige resultados auténticos. Ningún permiso condicional se vuelve a solicitar.

Autoridad actual: [paralelo](zelerdata-historico-paralelo.md), líneas973–999:
«termina zelerdata, autorizo todo» permite cierre necesario delimitado **antes**
de cada llamada, no borrar negocio/Full/reset/bypassOAuth. Root único operador.
Ownership central/config/deps/CUOTAS se conserva. Este documento no amplía piloto.

## 1. Evidencia que existe y lo que NO demuestra

| Evidencia fechada | Cobertura / límite |
| --- | --- |
| Prefix10GET del5oct23:17 | Cinco roots metadata+bindings; no snapshot actual. Handoff404–407. |
| 1s readback6oct00:36 | Metadata+defaultbinding PASS, separado del resto. Handoff430–434. |
| Cuatro retries +3exchanges6oct00:48 |11GET200 completos, TTL/DLX/caps reales; cuatro retries0ready/unacked/consumers/bytes. Handoff448–467; paralelo951–966. |
| Dos acciones activas |5declarations equivalentes confirmadas, creación por nosotros desconocida. Ambas cleanup tool_error/waitererror; solicitud local True, remotoFalse, procesos terminaron. Paralelo932–960. |
| Builds | Source352 VERIFIED y no servido; no APIbuild. Paralelo613–625. |

**No repetir conexiones/declaraciones fallidas para mejorar cleanup.** Mantener sus
fallos; fin de proceso/SSH no confirma cierre server-side. HTTPreadback posterior
cerró sin error, pero no corrige retrospectivamente cleanupAMQP.
Cinco retries requeridos sí tienen evidencia estructural fechada; no fresh-global,
confirmedpublish, timing, noLoss90min ni ingreso futuro acotado.
Referencias: [handoff](zelerdata-historico-handoff.md)448–474 y
[ledger](zelerdata-historico-paralelo.md)951–966.

## 2. Gates ANTES del despliegue cerrado

| Gate | Evidencia mínima y STOP |
| --- | --- |
| Identidad/autoridad |VM platform-vm/proyecto zeler-platform-dev/us-central1-a; contenedor/digest actual, fuente/hash de lector y source352 de destinos. Drift/ambigüedad→STOP. |
| SnapshotAMQP nuevo |10colas metadata+bindings +3exchanges, todos de una ronda posterior a reparación. TTL/DLX/defaultbindings/types/consumers/shapes/caps exactos. Primer error→STOP, no repair automático. |
| Riesgo de límites |Guardar ready/unacked/consumers, bytesready nullable y caps reales por cola. Headroom calculable no es bound de ingreso futuro. Falta bytes/bound→no afirmar noLoss/admisión segura. |
| Broker entrega/timing aislados |Prueba temporal§4, bajo namespace de evidencia propio. No business/history y no atribuirla al handler nuevo. |
| Recuperación/capacidad |Pins/rollback-forward compatibles con policy_authority, registro14/6 y datos existentes; capacidad actual antes de cada pull, margen real e inodos/RAM/Mongo aparte. |
| Interlock/render |Base + override nuevo exclusivo derivado del actual preservado; worker primero, gateway después, API intacta. HOLDtrue/guard82453304/history/recovery/refreshOFF. |

[Handoff](zelerdata-historico-handoff.md)140–153 exige AMQP real antes del guard
pero coloca WAIT/ACKNACK sobre runtime nuevo como protección diferida; no exigir
que352 se pruebe en servicio antes de desplegarlo ni trasladar gates silenciosamente.
Freshestructura + prueba aislada permiten **evaluar** el gate broker para rollout
cerrado; Root debe registrar qué evidencia acepta. No certificar por ello el
handler352 ni el piloto. Si una aceptación exige publicación por ese handler
antes de instalarlo, hay dependencia circular: documentarla, no falsificarla.

### Lectura fresca23: alcance exacto, no retry ciego

Nuevo estado después de reparación y nueva autoridad; operación nueva de Root,
no repetición para ocultar404. Reutilizable lector reviewed816e2c45 + supervisor460cb46d
con hashes completos en [informe revisado](zelerdata-historico-amqp-revisado-informe.md)105–109;
solo mientras el worker siga en old79f aprobado (informe76–85).

- Colas: zeler.sheets.events, events.delay, events.dlq; zeler.sheets.claims,
  claims.dlq; claims.retry.1s/5s/30s/2m/10m. Nombres completos con prefijo zeler.sheets.
- Dos GET por cola y tres exchanges: meli.events, zeler.sheets.events.dlx,
  zeler.sheets.claims.dlx.23 máximo, secuenciales; mismo target/auth, sin fallback.
-4s/request,60sread,64KiB/body,cleanup5,hard80/exec95/remoto150/root130+grupo5/total≤300s.
- Normalización userinfo solo memoria; policy/operatorflags y tuple real exacto
  expires2419200000/max-length10000/max-length-bytes1073741824; nada se cambia.
- Guardar contadores y estado de cada GET.27 iniciados conocidos previos +≤23 =≤50
  del tramo ampliado;27headers/25cuerpos previos intactos. Primer intento17:57 con
  GETdesconocidos permanece **desconocido** y aparte, no inventar totalglobal exacto.
- Primera excepción/HTTPerror/shape/drift/cap/timeout→STOP; nada de red restante.

Fuente de inventario y flujo: [canon](../../infra/operations/zelerdata_amqp_delay_readonly.py)
25–55,256–288,420–457. El lector solo prueba metadata y conserva
`runtime_confirmed_publish_verified=false`/timingfalse. Informe revisado64–85
mantiene ingress/noLoss/pilotadmissionfalse aunque la estructura pase.

### Headroom y expiración: criterio proporcional, no policy-mutación

Con R=ready y B=bytesready: margenmensajes=10000−R y margenbytes=1073741824−B;
B=null significa margenbytes desconocido. Para garantizar una pausa de duraciónΔ,
se necesitaría bound auténtico de ingreso/mensajes/bytes duranteΔ menor al margen,
incluidas ráfagas y tráfico ajeno.2500 GET **no** es2500 mensajes. Observar una tasa
pasada o backlog0 no limita entrada futura; controles de presupuesto no prueban
no-loss global. `expires=28d` cuenta inactividad de cola, no duración de un mensaje
ni tiempo restante derivable de idle_since. [RabbitMQ TTL](https://www.rabbitmq.com/docs/ttl)
y [límites de cola](https://www.rabbitmq.com/docs/maxlength).

Los máximos afectan mensajes ready, no unacked; con overflow por defecto pueden
eliminar/deadletter los más antiguos. Monitorear headroom/backlog/restarts y parar
admisión propia ante deterioro no constituye límite duro de ingreso externo.
Estas reglas por sí solas no prueban inseguridad de90min, pero tampoco benignidad
ni no pérdida. No borrar policies globales, ampliar broker ni relajar guard ciego.
Para rollout cerrado: baseline fresco y ventana de indisponibilidad delimitada,
forwardcompatible y observación; no activar piloto mientras bound/riesgo exigido
siga sin resolver. [RabbitMQ máximo de cola](https://www.rabbitmq.com/docs/maxlength).

## 3. Rollout necesario, sin nuevos builds ni contrato regresivo

Sourceexacto `352f3bd6f42c89929bb37006c04385a9492d3031`:

| Servicio | Destino inmutable ya VERIFIED |
| --- | --- |
| sheets-worker |us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:69d9da8d5e57c93868844349c489b33d0bf743612e718616d282a7ff6fe64a79 |
| gateway |us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:866dca4ecab51600f50e249d21ae3615e803bc803a8f27fdae1052371130e28a |
| sheets-api |Conservar3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417/d78; sin rebuild/recreate. |

[Paralelo](zelerdata-historico-paralelo.md)613–625 e [handoff](zelerdata-historico-handoff.md)74–76,386–391.
Preservar base y override actual interlocked-b867; preparar nueva versión exclusiva,
no editarla todavía en esta auditoría. Orden y controles en handoff322–330 y
[propuesta seleccionada](zelerdata-historico-publicacion-piloto-propuesta.md)83–100.

1. Captura readonly fresca: bytes/inodos de raíz y Mongo, mountMongo/RAM/Docker,
   IDs/digests/restarts/OOM, gatewayready, workerhealth/componentes/consumidores,
   API registry14 y bootstrapdependency; sin envraw ni documentos de negocio.
   Root define por llamada≤300s,≤4readinessHTTP/5s cada uno y recursos exactos;
   readiness puede abrir probes internos: no declarar por ello0AMQP/Mongo ficticio.
2. Atestiguar source/build/procedencia y recuperación compatible recuperable;
   preservar override/registry14/6/índices/datos. Gateway viejo sin guard no sirve
   después de activar; worker legacy no sirve sobre policy_authority.
3. Render completo base+nueva versión override **en memoria**, validar solo campos
   allowlisted sin imprimir env/config completa. Verificar pins e interlocks.
   Preflight usa UNarchivo (ver contradicción§6); Root debe resolver binding al
   render real antes de operar, no pasar gate sobre base distinta.
4. Preflight fresco≥5GiB en `/` antes de pullworker, incluso descargas deattestation;
   recheck después; recreate solo worker con `--no-deps`, preservando grace.
   Identidad/newdigest/consumerreadiness antes de avanzar; STOP ante fallo.
5. Repetir preflight≥5GiB antes de pullgateway y recheck después; recreate solo gateway
   con base+override nuevo. Verificar ready/dependencias, HOLDtrue y fuente/digest.
6. Ventana de asentamiento propuesta60s, un nuevo contexto readonly acotado≤4HTTP;
   health/restarts/OOM/capacidad/backlog/componente. Outercommand debe exceder
   Dockerstopgrace **medido**, no asumir un valor desde base local.
7. Fallo→STOP y operación de recuperación forward cerrada previamente: pins nuevos,
   HOLDtrue/planpaused/historyOFF; conservar leases/hechos/cutoff/checkpoints/consumos.
   No downgrade13, oldworker, restoreMongo, broadrestart, prunevolúmenes ni
   reaplicar índices/validadores por costumbre. No llamarlo rollback de versión.

[Deploy](../deploy.md)520–568,602–610,660–713; [propuesta](zelerdata-historico-publicacion-piloto-propuesta.md)367–381,422–452.
Dockerstartup del runner declara exchanges/colas/bindings equivalentes de su
contrato (consumer459–520), incluido replayexchange que no cubre el reader23.
No prometer despliegue «0declarations» ni ampliar reader espontáneamente:
startup/readiness del componente y sus dependencias necesitan evidencia aparte.

## 4. Propuesta de prueba REAL aislada — NO implementada/NO ejecutada

Root debe fijar este scope en ledger y aprobar la preparación antes de una llamada.
Es prueba de broker, no fuente business ni histórico sintético, sin Meli/Mongo.
Puede ejecutarse **antes** del rollout en contexto old79f, para gatebroker;
no reejecutarla luego por pulido. No demuestra publisher de352 instalado.

| Recurso/operación | Máximo fijo |
| --- | --- |
| AMQP |1conexión propia no robusta/1canal publisher_confirmsTrue,on_return_raisesTrue. |
| Colas |2Queue.Declare server-named(name=""), durableFalse/exclusiveTrue/auto_deleteTrue/nowaitFalse; nombres retornados únicamente en memoria. Sin exchange.create/bind. |
| destination |Argumentos exactos `{x-expires:60000}`; no DLX/TTL, sin consumidores. |
| delay |`{x-message-ttl:30000,x-dead-letter-exchange:"",x-dead-letter-routing-key:<destination propio>,x-expires:60000}`. |
| Management |2GET metadata de SOLO esas colas propias, antes del publish; sameauth/target/4s/64KiB. Validar argumentos efectivos, tipo classic y reglas empty o tuple conocido; unknown/routing/TTL distinto→STOP. |
| Publish |1basic.publish al defaultExchange, routingkey=delay propio, mandatoryTrue; cuerpo nonce aleatorio≤64B/noSheetsEvent/noJSONnegocio, sin seller/jobs/source business; expirywire exactamente"5000" mediante timedelta(5000ms). ConfirmOK y ningún return. |
| Poll |3basic.get como máximo SOLOdestination/no_ackFalse: uno temprano, uno después de5s y uno después delACK; no get a delay/colas business. |
| ACK |1ACK únicamente tras nonce/propiedades/death reasonexpired propios verificados;0NACK/republish/consume. |
| Retirada |≤2Queue.Delete SOLO nombres propios retornados, if_emptyTrue/if_unusedTrue/nowaitFalse; nunca purge. Closeowntransport≤5s preservando errores; exclusive+x-expires son fallback, no certificado de cleanupremoto. |

Los2GET adicionales son guard de aislamiento: no asumir que patrones de policy de
colas business se aplican igual a nombres temporales. Verificación efectiva antes
de publicar impide un DLX/TTL de policy inesperado hacia negocio. Si no se puede
verificar ese aislamiento, no publicar. Techo conocido nuevo≤50+2=52, más intento
histórico originaldesconocido aparte; gastos Meli/piloto no se cambian.

Timing monotónico: t0 antes de publish;confirm≤4s y STOP si llega tarde para sondeo
temprano. Get temprano en t0+4s con RPC≤0.5s, debe terminar antes det0+5s y ser vacío.
Segundo get en t0+8s/RPC≤2s: debe traer el único nonce; si vacío STOP sin polling
adicional. Verificar x-deathreasonexpired/count1/queue propio y original-expiration5000
(si no está disponible, no afirmar ese flagwire); no emitir headers/body/nonce.
ACK propio; tercer get≤2s vacío. Reportar tiempos observados/ventana, no exactitud
matemática5s ni garantía a otros mensajes/backlog. TTL efectivo usa el menor entre
queue30s y mensaje5s, no25s/35s. [RabbitMQ TTL](https://www.rabbitmq.com/docs/ttl).

Límites: connect8/canal4/declare4cada uno/publishconfirm4; operaciónwork≤60s,
cleanupTOTAL5,hard80/exec95/remoto150/root130+grupo5/total≤300s. Una operación,
sin autoreconnect/retry ni fallo inducido; STOPprimer error, inconsistencia,
creds/identity drift, return/nack, nonceajeno, clock/deadline/cleanup. En STOP
solo cleanup propio delimitado; progress desconocido=null y remoto no certificado.

**Qué prueba:** un publish confirmado en el broker configurado, expiración/deadletter
observados antes de30s, recepción de nonce y ACK local propios. No durabilidad de
colas durable, HA/failover, DLX sin pérdida global, topología business real, worker
handle/counters/WAIT, OAuth/Meli/Mongo/Sheets ni SLA de90min.
Confirms y ACK del consumidor son independientes; un confirm de mensaje unroutable
no es éxito si hubo return. [RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms).
DLX clásico puede perder mensajes si el destino falla; observar una copia no prueba
at-least-once universal. [RabbitMQ DLX](https://www.rabbitmq.com/docs/dlx).

## 5. Gates DESPUÉS del rollout: trabajo legítimo, no eventos inventados

- Probar digest/fuente352 **en ejecución** y selector82/HOLD/lanesOFF reales; worker
  health + consumers/componentes/gatewayready, luego nueva observación tras60s.
  healthsidecar depende de is_ready y estados (worker_health57–66), no ACKprogress.
- OAuth normal solo humano legítimo; no force/token-copy/patchlinked. Preparar/activar
  plan solo con saldos/rangos/deadline vigentes y recepción CAS pinnada (CUOTAS/Root).
- Con entrega/evento **auténtico** ya permitido: observar correlación segura WAIT→
  copia delayconfirmada/mandatory sin return→ACK de original; intento no aumenta
  por WAIT, jobpending/fence/backoff/autoridad permanecen. No provocar429 ni
  desactivar auth para probar fallos. Consumer553–594 conserva attempt y orden.
- Reanudar solo por protocolo y crédito legítimo, comprobar progreso/persistencia/
  Sheets por flujo normal y dos cambiosauténticos en ventana autorizada. Backlog/
  unacked no deben quedar congelados ni esconder un fallo en DLQ.
- NACKrequeueTrue ante fallo real de publish: observar si ocurre naturalmente,
  nunca inyectar fallo productivo ni copiar business a probe. Si no ocurre,
  registrar **rama no ejercitada en vivo**; pruebas offline previas no se convierten
  en runtimeproof ni la pareja temporal prueba fallback de consumer.
- Si no hay trabajo/transición auténtica dentro del plazo, cobertura pendiente;
  no fabricar eventos, renovar90min/díaUTC, resetearattempt/counter/lease ni afirmar
  que todos los gates pasaron por health/build/read23.

[Consumer](../../modules/sheets/src/zeler_sheets/consumer.py)553–594,775–851,1048–1061;
[handoff](zelerdata-historico-handoff.md)151–153,331–342. Ack confirma procesamiento
en esa entrega, no la conducta completa del plan. [RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms).

## 6. Contradicciones/documentos que NO deben ejecutarse literalmente

| Texto / referencia | Resolución requerida por Root |
| --- | --- |
| deploy116–122 habla13scopes |Actual14 sinFull/6keys; fingerprint exacto autoritativo, no restaurar13. |
| propuesta3 «no reanudar» y67–76 pinscb632/2153/51cc |Histórico; goalnuevo(paralelo975–985) y pins352/69d9/866d actuales prevalecen. |
| handoff357–394 «detenida», permisoinspecciónpendiente y416–418repairnoautorizada |Etapas históricas conservadas; goal y repairresult448–474/ledgernewgoal son posteriores. |
| preflight18–20 lee UNCOMPOSE_FILE; deploy614/673/676 usa base sola |No fusiona overrides; dry-run244–249 solo sintaxis/capacidad. Binding y operación deben apuntar al render efectivo base+nuevooverride, nunca pasar sobre otro archivo. Preparación del puente seguro reservada a Root; no implementado aquí. |
| reader23 no publica/ACK(timing flagsfalse) |No cerrar entrega real con su salida; namespace separado para probe y postworker. |
| consumerstart459–520 declara replayexchange, reader23 solo tres |Reader no cubre toda dependencia de startup; exigir startup/consumerhealth actual, no snapshotglobalfake. |
| CoreRetryDelayPublisher.expiration=delay_ms numérico, retry_delay28–34 |aio_pika local message31–54/182 define numérico en segundos; no5swire por el nombre. Mandatory nuevo usa timedelta(consumer819). No tocarhelperlegacy ni afirmar que probe arregla ese camino. |

No editar fuentes/reportes/logs previos, documentos centrales ni lock/deps.
Root recibe matriz/propuesta; asignación nueva y scope firmado antes de herramientas
u operaciones. **ENTREGADO; NO SIGO MODIFICANDO.**
