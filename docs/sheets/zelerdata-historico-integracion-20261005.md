# ZelerData: integración directa del 5 de octubre de 2026

> **Continuación posterior a «Realizalo»:** dos nuevas imágenes necesarias
> SUCCESS/VERIFIED desde main352f3bd6, aún NO desplegadas. La nueva inspección
> AMQP de solo lectura ya fue autorizada y ejecutada con STOP: HTTP404 de retry1s.
> El broker confirma ausencia exacta; cleanup falló, sin repetir. El usuario autorizó
> reparar el mecanismo el 6 de octubre UTC: retry1s declarada compatible y metadata/
> binding PASS; cuatro buckets restantes declarados compatibles y once GET200 PASS.
> Cleanup AMQP fallido conservado; no prueba de entrega real/admisión. Los resultados
> previos conservan su fecha/alcance.

**Aceptación pendiente; producción detenida.** Continuación local autorizada del
[handoff](zelerdata-historico-handoff.md), sin SDD por decisión expresa del usuario.
Ownership, presupuestos y registro único de operaciones:
[zelerdata-historico-paralelo.md](zelerdata-historico-paralelo.md).

## Qué cambia y qué se conserva

- Las entregas originales CUOTAS y AMQP están recibidas y congeladas. Se preservan
  sus informes, hashes, helper/logs originales y evidencia histórica de fallos.
- Históricos h1 siguen utilizando crédito fuente/fase prepagado y reserva tardía.
  Normales/eventos del vendedor con ejecución opt-in no pueden usar una etiqueta
  libre ni saltarse la política. El guard sin intención sigue fail-closed.
- La intención de mantenimiento se resuelve desde `webhook_events`: vendedor,
  topic persistido, recurso normalizado y acciones válidas de post-purchase.
  Se exige el propietario real de `processed_event_claims`; replay exige también
  job running, attempt_token/fence, lease vigente y evento dentro del delta.
- Se conserva la **clave real** del publisher
  `topic:recurso_normalizado:notification_id`; no reemplazarla por
  `event_type:notification_id` ni invalidar completed markers existentes.
- Cada cargo de trabajo crea un nonce/recibo `execution_work` en el mismo plan.
  No incrementa `execution_charged` legacy: ese crédito fungible no puede pagar un
  trabajo ni robarle su prepayment. El contador global y la política fuente/fase
  son compartidos, sin nuevo presupuesto, refunds, transferencias o resets.
- El header `X-Zeler-History-Work` solo localiza ese recibo; no es autoridad.
  Gateway lo elimina antes del proveedor y reserva una única vez mediante
  transacción snapshot/majority: verifica evento y ownership live, toca los
  documentos de ownership sin renovar leases y CAS del nonce/global. Un takeover
  entre lectura y escritura provoca conflicto/WAIT; no se reintenta la transacción.
- Reservar/cobrar y después fallar conserva consumos. `execution_work_sent_by_source`
  registra reserva de trabajo, separada de las reservas legacy h1. Una reserva no
  prueba recepción del proveedor, write Sheets, publicación AMQP o entrega real.

## Límites intactos

Registro14 sin Full y seis routing keys. Inicial adicional2000: orders800,
questions150, shipments250, messages300, claims_returns500. Mantenimiento500,
≤300/fuente; total adicional2500,90min y mismo díaUTC. Son techos, no saldo
medido. No se reinician cuotas, cutoff, checkpoints, leases, ejecución o plazos.
History/recovery/refresh OFF y HOLDtrue se preservan hasta gates/rollout legítimos.
Items/catalog/Full y trabajos sin intención justificable no reciben una sexta
fuente: permanecen WAIT o fuera de la adquisición activada, según el flujo.

## Evidencia local (no prueba productiva)

| Control | Estado |
| --- | --- |
| Snapshot entregas original | Ruff/formato/direct PASS; mypy661 PASS; focused345 PASS. Suite4FAIL/6312PASS/9SKIP, fixture h1 sin authority detectada. |
| Corrección fixture h1 | Nuevo cerco preservado; focused proxy real Mongo22PASS en copia estable. |
| Contrato core / clave publisher | RED módulo/funcional y clave real observados; core/gate35PASS, calidad enfocada PASS. |
| Hook gateway work | RED4 → focused154PASS, calidad enfocada PASS. |
| Mongo rs0 real | 10PASS: último nonce concurrente, h1 no roba crédito, rollback completo de ownership touches y takeover claim/job entre snapshotread/touch. Snapshot/majority observado; codecs UTC naive normales. |
| Integración Sheets | ENTREGADO/congelado,6hashesPASS; RED13/WAIT5/counters8 y GREEN163PASS reportados; pacing6PASS; calidad6pathsPASS. Coordinador cerró fallbackonce postpacing RED1→44PASS. |
| Calidad del conjunto final | PASS: snapshot final2 congelado1072paths; pytest6395PASS/20SKIP, protectedrs019PASS, focused455PASS, ruff/formato/mypy665/direct/schemaPASS. Sin source drift. |

Target local nuevo y exclusivo: perfil Colima `zeler-paralelo-8dafff186997`, sin
host mounts ni cambio de contexto; Mongo PRIMARYrs0 loopback27028, Rabbit nuevo
loopback5673 y volúmenes propios. Ninguna URI ambiental ni base de producción.
No Docker builds locales. Los recursos propios ya se retiraron por identidad;
perfiles/datos/contextos anteriores se preservaron (recibo de cleanup abajo).

## Producción: STOP sin nuevo permiso solicitado

Única excepción **AMQP-REPEAT-1**, ejecutada20:02:28–20:02:46UTC, consumida.
`management_configuration_invalid`, exit2; reader iniciado tras comprobar el
worker/digest esperado, **0 GET Management,0Meli,0mutaciones**. No fallback,
credenciales alternas, segundo probe o retry. El resultado no identifica causa404
histórica ni verifica topología/publicación/TTL/entrega. Recibos/hashes en ledger.

Por esos gates, builds, despliegue y piloto no continúan. Los permisos
condicionales anteriores no se solicitan de nuevo ni se amplían. Publicar código
local validado, construir una imagen, desplegar y alcanzar aceptación son pruebas
separadas. No declarar cierre del producto por tests/build/health200.


## Recibo final de calidad y límites

Snapshot `826774c365b31afcfb886f4e7ec901dc5a0bb804ceb7adc9431927e3f7cf2666`,1072paths; HEAD de base7cbd más delta
propio aún sin commit en el momento del snapshot. Manifiesto no-Markdown SHA256 `83644e5e0085c0b47c984f88cc0439da7246b820afdbfe75650bb1ddfbcdc6c6`.
Controles exactos: `uv run --no-sync pytest`, `ruff check .`,
`ruff format --check .`, `mypy .`; direct-Meli y export_schemas --check adicionales.
Los20skips incluyen19 protegidos rs0 ejecutados aparte (19PASS); smoke Caddy
condicionado no se ejecutó. No se reduce mypy al job CI ni se suman lotes repetidos.
La primera prueba pipeline rs0 falló por copiar headers httpx con mayúsculas en
un mock ASGI. Se preservó FAIL; la fixture ahora normaliza lowercase y exige
marcador de intento1. Corregida11rs0PASS; después se repitieron los ocho controles
sobre final2: todoPASS, incluida suite completa6395PASS/20SKIP (392.89s).
No se modificó comportamiento runtime para resolver esa fixture.

Se retiraron por identidad seis containers, ocho volúmenes propios y un volumen
anónimo Mongo del perfil local, luego perfil/data exclusivamente propios.
Contexto Docker y dos perfiles anteriores idénticos; evidencia privada preservada.
El primer fence de cleanup rechazó IDs abreviados de `docker ps`; se usó
`--no-trunc`, se cotejaron IDs completos antes de borrar y no se relajó ownership.
Sin prune ni recursos de producción. Solo documentos de resultados cambian
tras este snapshot; código/tests/config/dependencias siguen byte-identical a lo
validado. La publicación vinculará esos hashes al commit final, no inventa un SHA
fuente ya validado en main.

**Siguiente gate:** configuración Management válida y diagnóstico/topología/
entrega real bajo autoridad nueva explícita si el usuario decide reabrirlo.
AMQP-REPEAT-1 no puede usarse otra vez. No re-solicitar los permisos condicionales
vigentes ni construir/desplegar API no afectada. Gateway y Sheets worker sí
requieren nuevas imágenes desde el main publicado exacto cuando se pueda
continuar: buildsVERIFIED separados, pins/digests/recuperación/capacidad y runtime
verificados; build/deploy no prueban aceptación anual/parcialAPI/nativa ni dos
incrementales con cambios reales. Sin datos fabricados o extensión de plazos.

## Publicación verificada — 2026-10-05T20:46:40.180910+00:00

- Reader AMQP: `2c657015d5d64a6650811d378ebdae21cc0e6ed2`.
- Integración directa: `9149d00b7d979fb4498a4c16ae6c3220172b566f`.
- Push normal de24paths propios; SHA remoto=HEAD y árbol limpio observados.
  Los903blobs no-Markdown y bits ejecutables Git son iguales al snapshot final2.
  Cuatro archivos ajenos al delta mantienen permisos POSIX0600 locales y modo
  Git100644 ya presente en el padre: Git no almacena esos bits rw; sin chmod.
  Solo los tres documentos de resultados difieren, validados separadamente.
- Actualización de estado posterior: doc-only, identidad consultable por `git log`;
  no nueva fuente ejecutable ni nueva prueba runtime. Recibos privados conservados.

Imágenes necesarias cuando gates/autoridad permitan: **gateway + Sheets worker**
desde el commit exacto autorizado en main; las imágenes antiguas/builds cb63260 no
incorporan esta integración. No API u otros rebuilds. Verificar procedencia/digest,
capacidad/rollback, dependencia y consumidores, y comportamiento afectado tras
settling antes del piloto. Ningún build/deploy se ejecutó por detectar drift.
**Aceptación pendiente. AMQP-REPEAT-1 agotada; no nueva autorización solicitada.**

## Imágenes nuevas de la reanudación — no runtime

Fuente única `352f3bd6f42c89929bb37006c04385a9492d3031` en repositorio conectado,
903blobs no-Markdown iguales al snapshot probado. Una solicitud porimagen,
`requestedVerifyOption: VERIFIED`, sinresubmit; verificador canónico de
source/repo/subject/digest/build PASS para ambas.

| Servicio | BuildID | Pin inmutable | CloudBuild inicio→fin |
| --- | --- | --- | --- |
| Sheets worker | `4a4c14a8-bb83-4aab-87f6-b1bb2be1389d` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:69d9da8d5e57c93868844349c489b33d0bf743612e718616d282a7ff6fe64a79` | 2026-10-05T21:42:45.448501060Z→2026-10-05T21:43:46.958710Z |
| gateway | `86be40be-95d9-4e56-b1b2-f2282c495e89` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:866dca4ecab51600f50e249d21ae3615e803bc803a8f27fdae1052371130e28a` | 2026-10-05T21:45:32.695976858Z→2026-10-05T21:46:23.762203Z |

API no reconstruida. Dos solicitudes nuevas consumidas; no repetir builds
cb63260 ni estos por documentación/polling de procedencia. VMpull0/deploy0/
OAuth0/piloto0/Management0/Meli0 en esta reanudación. Los pins no prueban
readiness/consumidores ni aceptación. Recibo privado `two-verified-builds-receipt.json`
y ledger único en el documento paralelo.

El despliegue seleccionado sigue pendiente de AMQP: worker primero/gateway
después, base+overrideactual preservados, versión nueva exclusiva con estospins,
HOLDtrue/guard82453304/historyOFF/recoveryOFF/refreshOFF y registro14sinFull.
Revalidar capacidad/digests/consumidores/aislamiento/recuperación compatible antes
de cualquier pull; ≥5GiBraíz porpull, sinprune/limpieza/resize implícitos.
Recuperación forward compatible con los mismos pins/HOLD/paused/historyOFF si
hay policy_authority; no workerlegacy ni gatewayold sinbudgetguard después de
activar, no restores/quotaresets. AbrirOAuth/piloto solo con gates completos.

**AMQP-CONFIG-INSPECT-1:** excepción únicamente solicitada, NO recibida/NO ejecutada.
Inspección estructural de dos variables en el worker, 0red, 60s/5min, sin valores
ni cambios; no autoriza posterior topología GET/publish/corrección. AMQP-REPEAT-1
continúa agotada. No re-pedir los permisos condicionalesbuild/rollout/piloto.

La preparación de la excepción estructural está entregada/congelada:72pruebas
offlinePASS y calidad3fuentesPASS;4hashes/bindingcotejados porcoordinador.
[Informe propio AMQP configuración](zelerdata-historico-amqp-config-informe.md).
No es producción ni otra lectura. Autorización sigue pendiente,0intentos.
No se reinicia el plazo del piloto ni se reutilizan excepciones históricas.

## Inspección ampliada autorizada — estado actual

El usuario autorizó «la inspeccion AMQP que necesitas, incluso si necesitas
ampliarla». Alcance de solo lectura: no broker/config/credenciales/IAM/capacidad,
datos o presupuestos de piloto. El [ledger único](zelerdata-historico-paralelo.md)
conserva tiempos, recibos, consumos y STOP de cada operación.

- Rechazo actual identificado: Management incluye userinfo legítimo, igual al
  broker. La herramienta lo separa **solo en memoria**, sin cambiar target o
  configuración, y usa BasicAuth de la misma cuenta. No atribuir por eso la causa
  exacta del 404 histórico.
- Mongo instalado: PRIMARY y metadata de las tres colecciones PASS; dos comandos
  explícitos, cero lecturas de documentos/mutaciones. Plans sin validator;
  claims/sync con validators compatibles exactos. Esto cubre el gate real que
  las pruebas rs0 sin validators no acreditaban.
- Operator limits efectivos conservados: expires2419200000, max-length10000,
  max-length-bytes1073741824. La excepción estructural acepta solo ese tuple;
  ingress/no-loss/pilot-admission permanecen false. No modificar policies.
- Ronda revisada: diez GET200 completos (cinco colas+bindings); request11 HTTP404
  sobre `zeler.sheets.claims.retry.1s` → STOP sin request12/retry/fallback. Total
  del tramo ampliado:13 iniciados/13 respuestas/12 cuerpos completos de techo25.
  Cero Meli/Full, conexiones AMQP o mutaciones hasta este punto.
- El bucket1s es requerido por el primer retry y no se autodeclara al arrancar.
  HTTP404 no bastaba para afirmar ausencia. Una conexión propia y un único
  `queue.declare(passive=True)` recibieron broker404/not_found: ausencia confirmada
  a23:44:15–21UTC. Conexión/canal/RPC1 iniciados y completados;0Management/Meli/
  mutaciones. Cleanup tool_error/owned_transport_closedFalse, STOP sin repetir.
  El proceso transitorio terminó; no afirmar cierre limpio/server-side por eso.

Con `NOT_FOUND` confirmado, existe una [propuesta puntual](zelerdata-historico-amqp-reparacion-propuesta.md)
para crear solo ese bucket compatible. **No autorizada/no ejecutada**; no usar
`prestart` general, que también puede drenar/eliminar legacy. No volver a pedir
los permisos condicionales de builds/despliegue/piloto. Ninguna evidencia nueva
es aceptación anual/parcialAPI/nativa ni dos incrementales reales.

### Reparación del mecanismo — 6 de octubre UTC

El usuario autorizó resolver la cola y lo necesario del mismo mecanismo. Root
confirmó una declaración compatible retry1s a00:35:27–35UTC, con vector durable/
TTL1000/DLXdefault/routingclaims exacto. El cleanup reportó tool_error/waitererror;
close solicitado localmente, proceso terminado, sin afirmar cierre remoto limpio
ni repetir la declaración. Autoría de creación desconocida (`created_by_us=null`).

La lectura Management separada a00:36:45–50UTC verificó retry1s metadata+binding
HTTP200, después STOP request3HTTP404retry5s, sin request4/retry/fallback. Consumo
nuevo3iniciados/3headers/2completos; acumulado del tramo16/16/14. Cero Meli/Full,
otras mutaciones o nueva AMQP en esa lectura. Queue1s reparada/verificada;
HTTP4045s no demuestra ausencia ni topología global/admisión.

Preparación acotada de los cuatro buckets restantes5s/30s/2m/10m por declaraciones
compatibles secuenciales, no inferencia de ausencia: una conexión/canal/≤4RPC y
posterior verificación≤11GET separada. No declarar1s otra vez ni ejecutar prestart
general. [Propuesta restante](zelerdata-historico-amqp-retries-restantes-propuesta.md),
[informe1s congelado](zelerdata-historico-amqp-reparacion-informe.md) y ledger único.
Ese tramo aún no se ejecutó. Fuentes903 iguales al snapshot/image352: no nuevos
builds o suite general por herramientas privadas/documentación. Sin pull/deploy/
OAuth/piloto ni renovación de cuotas/cutoff/checkpoints/díaUTC/plazos; aceptación
continúa pendiente. Preservar cualquier cola compatible, nunca auto-delete.

### Resultado del tramo restante — no aceptación global

Root confirmó4/4 declaraciones compatibles5s/30s/2m/10m a00:47:41–47UTC,
una conexión/canal, TTL5000/30000/120000/600000 y retorno default aclaims.
Readback00:48:08–14UTC:11GET200 completos (cuatro metadata+bindings y tres
exchanges),0ready/unacked/consumers/bytesready por cada retry; operatorcaps reales
exactos preservados. Retry1s había pasado metadata/binding en la ventana anterior.
Los cinco buckets requeridos ya están disponibles y estructuralmente verificados.

La declaraciónAMQP volvió a registrar cleanup tool_error/waitererror,closeLocal
solicitado/remoteFalse: se conserva, no se repite ni certifica cierre remoto.
Proceso transitorio terminó; la lectura HTTP posterior sí cerró sin error.
Autoría de creación desconocida.0Meli/Full/publish/consume/ACK/policies u otras
mutaciones.27GET conocidos del tramo27headers/25cuerpos completos;consumosviejos
preservados. Fuentes903 y bits ejecutables iguales al snapshot/image352.

[Informe restante congelado](zelerdata-historico-amqp-retries-restantes-informe.md),
[propuesta ejecutada](zelerdata-historico-amqp-retries-restantes-propuesta.md) y
ledger único contienen hashes/límites/errores.24fakes1s y20fakesrestantesPASS,
calidad3PASS de cada entrega; no suite general/builds repetidos por OPSprivadas.
No nuevos pulls/despliegues/OAuth/piloto o renovación de cuotas/cutoff/checkpoints/
díaUTC/plazos. Registry14 sinFull/seisroutingkeys/datos/jobs preservados.

No equivaler las ventanas separadas a snapshot global fresco, no-loss/ingress,
publicación confirmada o timing real. Rollout seleccionado todavía requiere
capacidad fresca/identidades/rollback/consumidores/readiness y gates aplicables;
las dos imágenes VERIFIED source352 existentes siguen listas,no servidas, sin
rebuildAPI. Piloto conserva condiciones/saldoscanónicos/plazos: no fabricarlo ni
extenderlo por cambioUTC. La aceptación global permanece pendiente.

## Continuación del goal — 6 de octubre, UTC

**La aceptación global sigue pendiente.** El estado vigente está en
[handoff §10](zelerdata-historico-handoff.md#10-continuación-del-goal-gates-abiertos-sin-reinicios)
y los intentos/consumos únicos en [paralelo](zelerdata-historico-paralelo.md).
Las secciones previas son snapshots históricos, no instrucciones para repetirlos.

La corrección local nueva se limita a la admisión invocada por Gateway: seed
aditivo de hojas ausentes, whole-document CAS, validación fail closed de leases/
ledgers/counters, `last_linked_at` monotónico y piloto pausado seleccionado por
scope trusted. Preserva cutoff y todos los campos existentes; no inicia ventana
ni equipara cero prospectivo a saldo físico histórico. RED/GREEN documentados en
[el informe CUOTAS](zelerdata-historico-cuotas-legacy-implementacion-informe.md).
Solo Gateway necesita nueva imagen tras validación/publicación; helpers core de
worker/API mantienen AST, por lo que se usa el worker352 ya VERIFIED y no se
reconstruye la API.

Los cinco buckets están presentes en metadata fresca; dos probes temporales
se detuvieron antes de publicar por perfil no coincidente. Dos pares propios
retirados, errores SSL de cierre conservados. El próximo inspector observa el
perfil real con publisher/get/ACK imposibles; no cambia policies ni amplía el
piloto. El audit del plan terminó en cap1001 y reveló legacy: se prepara lectura
dirigida de presencia activa/forma y cuatro grupos nunca leídos, no otro scan
del archivo histórico.

Mientras ambos especialistas escriben herramientas privadas no se ejecuta la
suite general. Root preparó un runner Linux independiente, Mongo rs0 y Rabbit
locales autenticados, sin credenciales ambientales, solo imágenes por digest y
volúmenes propios. Tras entrega/cese habrá congelación, gates completos y
validación documental antes de cualquier publicación/build/rollout nuevo.
