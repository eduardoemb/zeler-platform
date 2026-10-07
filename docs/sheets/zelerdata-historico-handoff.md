# ZelerData: handoff del histórico al vincular

## PENDIENTE DE RESOLVER — cierre expreso del 6 de octubre de 2026

**HOPEMOB quedó vinculada correctamente. La carga histórica completa y la
sincronización incremental de ZelerData NO quedaron terminadas ni aceptadas.**
El usuario pidió cerrar la sesión y dejar este pendiente explícito. Esta nota
no reanuda implementación, pruebas, builds, despliegues ni operaciones productivas.

| Pendiente | Estado al cierre / evidencia necesaria para resolverlo |
| --- | --- |
| Servir la corrección de avance durable de envíos | Código publicado en `415a9cff4df52d7ffee928ce0b42cf791090e58d` y ocho controles locales PASS; **no desplegado**. Faltan imágenes API/worker, compatibilidad de validator, rollback y rollout autorizado API→worker. |
| Completar y comprobar el histórico recuperable de las cinco fuentes | **NO acreditado**. Resolver pendientes de envíos, preguntas y reclamos/devoluciones y comprobar rangos, cobertura y lectura por fuente; no sustituirlos por tests verdes o salud del contenedor. |
| Resolver los bloqueos de adquisición conservando lo existente | Envíos consumió250/250; el arreglo no recupera payloads perdidos ni repone crédito. Reclamos conserva fallos de precondición404; preguntas conserva el archivo del pase previo y el nuevo pase pendiente. No dar por resueltos estos casos. |
| Demostrar dos ciclos incrementales con cambios empresariales reales | **NO acreditado**. Se necesitan cambios reales y evidencia de lectura; solicitudes de mantenimiento, timestamps, caché, dos passes o archivos de checkpoints no bastan. |

**Responsable de retomar:** coordinador, sólo ante nueva petición del usuario y
con el alcance autorizado de cada paso. El piloto quedó PAUSED/HISTORY OFF, con
su plazo vencido. Conservar datos, jobs, IDs, checkpoints, consumos y registro14;
Full sigue excluido. No reiniciar cuotas/plazos, trasladar cargos entre fases ni
repetir llamadas fallidas por interpretar esta nota como permiso.

OAuth, muestra nativa en Sheets y API parcial de órdenes mantienen sus resultados
positivos anteriores, pero **no cierran este pendiente**. El objetivo global de
ZelerData permanece incompleto. Detalles y evidencias históricas debajo.


> **Última evidencia operativa: 2026-10-06T20:32:52.806288Z; objetivo abierto.**
> Gateway `c905f4…`/source bc93, worker `be4fc0…`/source ed2715a, API3f7 preservada.
> Fix429 publicado, build VERIFIED y rollout cerrado PASS; 23 capas Compose.
> PAUSED, HISTORY/recovery/refresh OFF; 368 cargos/365 envíos,
> 340 iniciales/28 mantenimiento, Full=0. Plan completo SHA42a3… preservado.
> Plazo del piloto original20:32:58 UTC ya transcurrido; no fue prorrogado.
> Prórroga adicional20:42:58 sólo rollout cerrado, no adquisición ni más cuota.
> Shipments inicial250/250 agotado; Claims3 fallidas; Qp3 sin adquisición nueva.
> OAuth, muestra nativa y API parcial previas PASS dentro de sus alcances.
> Anual legible cinco fuentes y dos incrementales genuinos siguen NO acreditados.
> Ver [ledger único](zelerdata-historico-paralelo.md); no repetir pasos históricos.



**Punto de entrada único para retomar; objetivo global NO completado.** La pausa
del cierre inicial del 5 de octubre fue revocada por reanudación expresa; aplicar
la última entrada fechada del ledger, no estados previos de §11 o de la cronología.
No avanzar rollout/OAuth/piloto sin gates. Este archivo registra evidencia
fechada; ninguna observación pasada implica salud actual.

## 1. Objetivo y alcance pendiente

Al vincular por OAuth normal, adquirir y mantener histórico recuperable de hasta
12 meses calendario, con progreso independiente, datos útiles aunque falten casos
puntuales y lectores que no inventen cobertura. Cinco fuentes del piloto:
órdenes/comisiones, preguntas/respuestas, envíos/costos, mensajes y
reclamos/devoluciones. Publicaciones/items no constituyen una sexta fuente.

**Full excluido: 0 GET en el piloto.** Su mapeo auténtico sigue sin acreditarse;
la investigación cerrada no bloquea las otras cinco fuentes ni se reabre aquí.
`allow_partial` es solo API normal para ORDENES; no está disponible en Sheets.
No adaptar/publicar el complemento ni ampliar fórmulas/fuentes para cerrar el goal.

Aceptación aún pendiente: OAuth auténtico sin force → intención durable conservando
cutoff/progreso/consumos → ejecución acotada → publicación y lectores por fuente;
períodos certificados independientes, parcial por API normal, muestra nativa y
**dos incrementales con cambios reales** posteriores al cutoff. Renovaciones o
ciclos vacíos no sustituyen esos cambios. El smoke nativo limitado de §7 no prueba
el circuito anual, certificados ni piloto.

## 2. Estados y cronología — fechas UTC, pruebas no intercambiables

| Plano | Evidencia completada | Lo que NO acredita / estado pendiente |
| --- | --- | --- |
| Implementación local, validada 2026-10-05 (hora enfocada no fijada aquí) | Coordinación histórica y controles existentes; fix OAuth que busca seller+state elegible antes del fallback; guard opt-in de GET físicos normales/retries y espera controlada fenced. Evidencia local previa: mensaje de orden antigua sin cambios, API normal con 9,999 útiles+1 pendiente/default exacto y guard de totales, capacidad de 2 fuentes no vacías/certificados de 1,000 membresías. | No son controles servidos por las imágenes runtime antiguas. Guard normal no atribuye fuente/fase: gate de reparto pendiente. |
| Calidad local, 2026-10-05 | FULL **6,070 passed/9 skipped, pytest 396.55s, exit0**, 17:55:42→18:02:21. Protected **8 passed/2.16s** separado; ocho guards Mongo del full cubiertos, noveno Caddy intencional. Ruff/formato/mypy 658/direct-Meli PASS. FINAL2: 1,059 paths, 11 propios, hashes/modos ejecutables intactos. | Mongo real aislado/transporte mock: no provider, OAuth ni aceptación productiva. No repetir gates válidos por el handoff/doc-only ni sumar lotes. |
| Controles enfocados, 2026-10-05 local (hora no fijada aquí) | OAuth 29 PASS; guard 134 enfocadas/adyacentes PASS, incluidas 77 nuevas, 1 Mongo deselected solo en el lote enfocado y cubierto globalmente. CAS 14 casos Mongo real/default tz_awareFalse+transporte mock (último crédito/mezcla h1); CAS gateway no repetido en FINAL2 porque su fuente quedó intacta. | No publicación confirmada actual de Rabbit ni atribución normal por fase/fuente. WAIT conserva attempt 0–4 por más de 5 ciclos, mandatory-confirm antes de ACK/NACK ante fallo; sin refund/reset/headers o estados nuevos. Nuevo camino usa timedelta para wire 5s; no inferir 25s ni tiempos del publisher antiguo. |
| Publicación, 2026-10-05 | Dos commits de código y luego cierre doc-only publicados en main/remoto exacto; identidades §3. | La publicación de este handoff será otra unidad documental, identidad consultable por ruta; no un nuevo source build. |
| Builds, 2026-10-05 | Únicos gateway+worker desde cb63260: SUCCESS/VERIFIED, repositorio conectado/requestedVerifyOption VERIFIED/verificador canónico PASS; referencias §3. | **Sin pull VM ni despliegue nuevo.** API sin build nuevo. El polling posterior de procedencia no fue otra solicitud. |
| Despliegue histórico, 2026-10-04 | Rollout cerrado: cinco índices aditivos, registro14 sin Full, API/worker d78 y gateway b867 aplicados. | Ningún rollout de los dos builds cb63260; OAuth/piloto siguen cerrados. Última salud observada Oct5 está fechada en §4, no es salud ahora. |
| Respaldo/restauración, 2026-10-04 | A–F PASS: auditoría41 miembros, restore fiel aislado/comparación integral, dos objetos GCS aceptados 02:11:08.854479, destino propio eliminado 02:12:00.719913. | No restore productivo, otro corte autorizado disponible ni aceptación del producto. Evidencia del primer import fallido/forense preservada. |
| Función nativa, 2026-10-05 18:05:09 | `ZELERDATA_ORDENES` existente en hoja privada: 4×4 efectivos/16 celdas, sin errores, Mongo-only/recoveryOFF/token intacto. | Smoke independiente, no anual/certificados/piloto; otras seis fórmulas inactivas, revisión visual no realizada. |

El [informe de implementación](zelerdata-historico-al-vincular-implementacion.md)
y la [propuesta publicada](zelerdata-historico-publicacion-piloto-propuesta.md)
conservan el historial completo; sus secciones antiguas no sustituyen este estado.

## 3. Identidades de publicación, runtime servido y nuevos builds

Tres últimos commits **antes de escribir este handoff**:

| Commit completo | Unidad |
| --- | --- |
| `6a76df69fbeeaace7fb6e9a39d9f5a934e8c1c7b` | Cierre documental de builds verificados/gates retenidos; HEAD y remoto exactos. |
| `cb63260fcf9e628cfc6ca59783e85b86cfa7c9e2` | Guard físico/espera/tests/docs; fuente de ambos nuevos builds. |
| `e758938268ebe03399f21588da03886685e6ae28` | Selector OAuth: jobs failed históricos no ocultan succeeded/pending/running. |

Tree publicado cb63260: `de0eb6fc4e05db0ded5df6c583a8bb83d1c0203c`.
La verificación preservó los 1,059 paths/bytes/modos ejecutables del candidato;
las dos actualizaciones documentales se validaron separadamente. Checkout `main`
limpio, sin cambios propios ni ajenos, observado localmente **2026-10-05
18:22:04 UTC** antes de este archivo; es snapshot, no garantía de un checkout futuro.

| Imagen SERVIDA en última observación | Fuente completa / buildID | Referencia completa |
| --- | --- | --- |
| Gateway antiguo cerrado | `b867b27505b424871a92a59da459c45840cf8d8c`; `3a393853-4c2a-4044-81fd-050f0fc766a0` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:7054e427c15835608955cd23f694314aacccc798273cf2ac8e57b03f8c4a4b62` |
| Sheets API conservada | `d78ff4e57915ca5e81a5eb6f1976ec65f111824b`; `99bb01b9-8254-4151-a559-74ba18bfc259` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417` |
| Sheets worker antiguo cerrado | `d78ff4e57915ca5e81a5eb6f1976ec65f111824b`; `6be598c0-8c97-4a26-9823-31808e6264cb` | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e` |

Nuevas imágenes **CONSTRUIDAS/VERIFICADAS, NO SERVIDAS**, fuente común
`cb63260fcf9e628cfc6ca59783e85b86cfa7c9e2`:

Repositorio conectado verificado de ambos builds:
`projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform`.

| Servicio / buildID | Tiempos físicos 2026-10-05 UTC | Referencia completa |
| --- | --- | --- |
| Gateway `b47372a5-2425-446e-9e7f-9a93b99c9306` | 18:12:47.801050166→18:13:40.133706 | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:51cc3af99405ee45506de106e0e97422e0f39cffbabbe4a093be2ae719809b32` |
| Worker `6a1a3451-6b17-4283-a6ca-ba1748377ebb` | 18:12:47.721378013→18:14:07.516503 | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:215333453be50a6b55f31cbd0df6e7447952e8f624efdbfbe2732747740ef327` |

API d78 no tiene delta servido ni build automático. Handoff/doc-only no invalida
por sí mismo calidad ejecutable ni obliga a repetir builds. Para identificar la
publicación de **este archivo** sin autorreferencia, consultar después:

```bash
git log -1 --format=%H -- docs/sheets/zelerdata-historico-handoff.md
```

## 4. Última configuración observada — no revalidación actual

Lectura de **2026-10-05 17:24–17:25 UTC**: gateway/API/worker/bootstrap-dispatcher
readiness/dependencias sanas, restart0/OOMfalse y tres digests servidos de §3.
Capacidad entonces: raíz 34,572,402,688B, Mongo 47,455,887,360B, RAM disponible
1,139,802,112B. No son preflight de un futuro pull ni salud actual.

- Gateway `ZELERDATA_HISTORY_ON_LINK_ADMISSION_HOLD="true"` y
  `ZELERDATA_HISTORY_ON_LINK_ADMISSION_SELLERS="82453304"`.
- Worker `ZELERDATA_HISTORY_ON_LINK_ENABLED="false"`, selector histórico82 intacto.
- `ZELERDATA_FORMULA_RECOVERY_ENABLED="false"` en API y worker;
  `ZELERDATA_REFRESH_ENABLED="false"` en worker. Cohortes originales únicas82
  conservadas; no cambiar otras cuentas/campos. API no tenía refresh configurado.
- **Guard cb63260 NO instalado:** selector nuevo
  `ZELERDATA_HISTORY_PILOT_GET_BUDGET_SELLERS` no aplicado. Que la imagen exista
  no significa que limite ya eventos/retries en producción.
- Registro **14 = baseline13 + único `GET /messages/packs/*`, SIN Full**, seis
  routing keys; demás campos/seis clientes preservados. No reponer antiguos
  scopes13/Full14/contrato15 de notas Full ni reaplicar índices/registro.
  Fingerprints canónicos observados a 17:25 UTC: Sheets
  `205f9e4e48b94c605ea365cd66d980954ac2ea97f229790ad8eb75fb56848f26`,
  conjunto de siete clientes
  `08ff61bfd2734156539c8e1b940f127a730fd66d307954cd47dbcdd1a2c113d6`.
  Son referencias de esa evidencia, no salud actual ni autoridad de reparación.
- Plan legacy observado conserva cutoff `2026-09-24T05:36:28Z`/progreso; no
  prepare/activate del piloto. No inventar policy_version ni normalizar manualmente
  identidades: account seller numérico, plan seller string por contrato.

Base actual `/opt/zeler-platform/docker-compose.yml` más override cerrado actual
`/var/lib/zeler-platform/.history-rollout-20261004T022714Z/interlocked-override-b867b27.yml`,
SHA `b7b85d5628b5df6580c8c34544db5c4bb0350ec8cb3b04fcd43c5a6234919dd1`.
No operar base sola. Un override nuevo sería otro archivo exclusivo, todavía
**no creado/aplicado** por esta fase; preservar el actual.

Cloud Run bootstrap: lectura acotada **2026-10-05 17:45–17:46 UTC** del job exacto
`zeler-bootstrap`, proyecto `zeler-platform-dev`, región `us-central1`: 34 terminales,
0 no terminales/<100 sin truncación/GET Meli 0/sin mutación. No acredita ausencia de
jobs productivos ahora ni selección correcta del gateway antiguo. Drivers propios
previos terminaron y la revisión local de procesos no dejó operaciones propias
pendientes; no implica inspección de procesos/jobs remotos actuales.

## 5. Gates del handoff inicial — contexto histórico

Esta lista conserva los bloqueos iniciales del 5 de octubre. No es el estado
vigente ni revoca autorizaciones posteriores. Consultar §14 y la última entrada
del ledger para la pausa, límites y aceptación actuales.

1. **AMQP:** una ejecución productiva de lectura a 17:57 UTC terminó
   `management_http_404`, primer error STOP, sin retries/mutaciones de colas/Meli.
   Endpoint fallido y número de GET completados no quedaron capturados; máximo
   programado 23. **No concluir cola ausente, fallo auth ni causa conocida.** TTL,
   DLX, bindings y entrega confirmada actuales no acreditados. Workerready,
   configuración fuente o AMQPpassive no los prueban. Bloquea rollout del nuevo
   guard/OAuth/piloto; no bloqueó publicación/builds o smoke independiente.
2. **Reparto físico:** guard normal limita ejecución global, incluidos retries,
   sin atribuir fuente/fase. No prueba por sí solo cuotas iniciales/mantenimiento
   para todos los GET. Acreditar reparto original incluyendo tráfico normal antes
   de activar, sin ampliar presupuesto, inventar atribuciones ni resetear counters.
3. **Protecciones diferidas:** validar sobre runtime autorizado que los nuevos
   pins/selector82 estén realmente servidos y contadores/CAS normal+h1, ventanas,
   WAIT fenced/backoff, mandatory-confirm antes del ACK y NACK ante fallo se
   mantengan. Topología sana no prueba publisher-confirm exitoso ni tiempos de
   mensaje. Nuevo timedelta wire 5s es prueba local; no afirmar timings antiguos.
4. **Aceptación real:** OAuth humano legítimo, prepare paused/recibo fijado/activate
   CAS si gates completos, fuente por fuente y rangos independientes, parcialAPI
   normal y dos incrementales auténticos. Smoke 4×4 no sustituye estos criterios.

No tratar estos faltantes como objetivo completado ni activar para investigar.
El [operador canónico](../../infra/operations/zelerdata_history_pilot.py) es
conservador: defaultdry-run/CAS de documento completo/raceSTOP/no retry; no
borrado, takeover, reset o upgrade manual de plan legacy. API d78 no contiene el
nuevo CLI: solo fuente congelada por stdin en runtime Python3.11 legítimo, cuando
haya autorización/gates; no fingir un módulo instalado ni copiar credenciales.

## 6. Autoridad inicial y presupuestos — contexto histórico

La tabla describe permisos y STOP del handoff inicial, no la autorización más
reciente. El goal posterior concedió hasta cinco horas desde 15:32:58 UTC hasta
20:32:58 UTC del 6 de octubre, sin ampliar los presupuestos fuente/fase ni Full.
El STOP Mon5 y cierre de §14 prevalecen actualmente; esa prórroga no autoriza
repetir fallos de proveedor ni ampliar Shipments después de agotar250.

| Autoridad / ejecución histórica | Alcance y saldo de autoridad |
| --- | --- |
| Encargo local inicial, preparación 2 de octubre | Implementación/pruebas aisladas; no producción/build/commit implícitos. |
| Goal/ampliación condicional documentada 3–4 de octubre | Publicación propia, builds afectados/rollout seleccionado y piloto HOPEMOB; anexos 625f5903 y 89357a31, rutas §7. No activación global ni autorización irrestricta de recursos/colas/datos. |
| Auditoría corregida, 2026-10-04 | Única excepción expresa al no-retry, ≤5min/misma ruta y archivos: ejecutada PASS 41. No queda un ensayo/auditoría nueva por repetir. |
| Cortes backup consumidos, 2026-10-03 | C 21:09:57 falló parser antes de dump; nueva C 22:06:27 falló selector/prelude. Recuperación y luego rescate de esos candidatos A–F completados; no otro corte automático ni reutilización del permiso alternativo. |
| Restore fiel, 2026-10-04 | Tras import estricto fallido, usuario autorizó solo una restauración aislada fiel en base nueva/VM propia, bypass de validación solo import, ≤600s/sin retry; PASS y destino eliminado. No nuevo restore ni recursos ahora. |
| Full, investigación cerrada | **7 GET de 10 consumidos**, parada 429/sin referencia auténtica. Tres aritméticos sin usar **NO ejecutables/NO autorizados**; no pedir un FullID ni reabrir selección/investigación. |
| Builds propios de la última fase, 2026-10-05 | Ampliación condicional: solo imágenes afectadas. **2 solicitudes consumidas/2 SUCCESS VERIFIED**, gateway y worker de cb63260 (§3), sin resubmit; API sin nuevo build. No saldo para repetirlos por el traspaso ni permiso de builds nuevos durante este cierre. |
| AMQP, 2026-10-05 | **1 ejecución**, HTTP404/STOP; GET Management realizados desconocidos, ≤23 programados; GET Meli 0/no mutación. No permiso de retry automático ni una segunda lectura por cambiar labels. |
| Piloto | No iniciado. **2,500 es techo, NO saldo restante verificado**. Deducir disponibilidad futura de política/counters/ledger canónicos; no reset ni asumir2500 libres porque el piloto no arrancó. |
| Orden de cierre actual, 2026-10-05 | **SOLO documental/STOP.** Requiere que el usuario retome explícitamente antes de cualquier continuación productiva; las condiciones anteriores no disparan operaciones automáticas. |

**Propuestas no autorizadas por este cierre:** repetir el diagnóstico AMQP fallido,
consultas/rutas/permisos Full, publicar/adaptar el complemento, recursos/costos
adicionales, IAM/lifecycle, restauración productiva o limpieza fuera del alcance.
El rollout/piloto previo sí recibió aprobación **condicional**: sus gates siguen
pendientes y la orden actual de detenerse impide ejecutarlo ahora.

Cuotas originales, no aumentables por el handoff:

| Fuente | Inicial máximo |
| --- | ---: |
| Órdenes/comisiones | 800 |
| Preguntas/respuestas | 150 |
| Envíos/costos | 250 |
| Mensajes | 300 |
| Reclamos/devoluciones | 500 |
| Total inicial | **2,000** |
| Mantenimiento conjunto | **500, ≤300 por fuente** |
| Full | **0** |

Techo conjunto 2,500 intentos físicos adicionales/90min/mismo día UTC, incluidos
tráfico normal/eventos/reintentos atribuibles al ensayo. `prepare` inicia la
ventana; activate posterior no extiende deadline. Preservar cutoff, consumos,
checkpoints, proofs, leases y jobs; daily rollover es del worker natural, no un
reset del operador. **Rollover natural no amplía deadline ni saldo del piloto:**
STOP al cambiar día UTC o agotarse 90min/deadline. El techo global normal no
demuestra el reparto de esta tabla.
Una reanudación no autoriza IAM/lifecycle, nuevos destinos/costos, colas, Full,
publicación/adaptación del add-on o limpieza ajena; pedir solo expansión necesaria
si surge, nunca interpretarla por analogía.

## 7. Evidencia preservada, respaldo y hoja privada

Lectura local canónica:
[especificación](zelerdata-historico-al-vincular-especificacion.md),
[implementación](zelerdata-historico-al-vincular-implementacion.md),
[propuesta](zelerdata-historico-publicacion-piloto-propuesta.md),
[control de piloto](zelerdata-historico-control-piloto.md),
[rescate](zelerdata-historico-rescate-candidatos-propuesta.md),
[Full cerrado](zelerdata-full-validacion-acotada.md) y [deploy](../deploy.md).
El control tiene baseline histórico del 4; Full contiene scopes históricos
supersedidos. Aplicar estado de este handoff, no esos permisos/configs antiguos.

Índice privado (referencias, **no comandos productivos**; no abrir/volcar env,
credenciales ni BSON de negocio):

```text
ROOT=$HOME/Library/Caches/zeler-operations/rescue-corrected-20261004T011204Z
QUALITY=$HOME/.codex/cache/zeler-gates-20261005-609b781d04c0
$HOME/.codex/attachments/625f5903-332b-4de7-b60d-07f291c8ae38/pasted-text-1.txt
$HOME/.codex/attachments/89357a31-dacb-4c2c-a224-6ed83d8aff27/pasted-text-1.txt
$ROOT/own-publication-validated-candidate-20261005/publication-receipt.json
$ROOT/own-publication-validated-candidate-20261005/final-published-docs-receipt.json
$ROOT/own-publication-validated-candidate-20261005/two-verified-builds-and-held-runtime.json
$ROOT/gateway-physical-budget-build-20261005T181244Z/verified-terminal.json
$ROOT/sheets-worker-physical-budget-build-20261005T181244Z/verified-terminal.json
$QUALITY/final-quality-receipt.json
$QUALITY/cleanup-final-receipt.json
$ROOT/private-native-sheet-smoke-20261005-safe-receipt.json
$ROOT/pilot-amqp-delay-readonly-20261005T175704Z-start.json
$ROOT/pilot-amqp-delay-readonly-20261005T175704Z-stdout.log
$ROOT/pilot-amqp-delay-readonly-20261005T175704Z-stderr.log
$ROOT/pilot-amqp-delay-readonly-20261005T175704Z-end.json
$ROOT/corrected-rescue-final-evidence-index.json
$ROOT/pilot-physical-budget-runtime-controls-20261005/offline-pass-receipt.json
$ROOT/amqp-delay-readonly-controls-20261005/offline-pass-receipt.json
```

| Recibo | SHA256 |
| --- | --- |
| Dos builds/held-runtime | `0851faeb23821676a1d2cd67f372413097a6b43899645ebe3f6b192d61c9b9fd` |
| Gateway verificado | `3925d6b035dee6243ab9180662c354360470d9ba1e113c87c15b873b8ae4bbeb` |
| Worker verificado | `b3a4e5b250513be86a3f9d78e8ac18c4b5968fbccc7d4e76c5abaed28fac20ad` |
| Calidad final | `eb912f49babc4855a5ca60859ad298ef03ab227753aa733d2ae49b8624601899` |
| Limpieza local final | `439a0f361fa6c3d858ac9045f867883982bf146f8ec9b683ef568cee539631bf` |
| Smoke nativo seguro | `cb2c3ed59a7bd12081a4f251cf6e959a8ef34f41516fae5d83029c8a5c9a7053` |
| Índice rescate 462 archivos | `c0281c63d17cde2ee6030c5dba5ba045230fcf39e73b872574712614055327a9` |

Inventario de recursos VM **preservados según última evidencia**, sin consulta
nueva de presencia en este cierre; son leads para futura revisión autorizada,
**no garantía de existencia hoy ni autorización de cleanup**:

| Recurso | Ruta conservada |
| --- | --- |
| Candidatos originales del corte | `/var/lib/zeler-mongo/.zelerdata-c-new-20261003T214827Z` |
| Staging sellado del rescate | `/var/lib/zeler-mongo/.zelerdata-rescue-20261004T011918Z` |
| Manifiesto aceptado separado | `/var/lib/zeler-mongo/.zelerdata-rescue-accepted-20261004T021033Z/manifest.json` |
| Stage de operadores/override cerrado | `/var/lib/zeler-platform/.history-rollout-20261004T022714Z` |

Caches locales/recibos preservados; fixtures locales propios ya retirados Oct5.
No borrar esos stages/candidatos, credenciales/sesiones, backups o datos ajenos.

GCS, aceptación **2026-10-04 02:11:08.854479 UTC**: dos objetos únicamente,
gen0 al crear/readbackSHA/temporary_hold=true verificados en esa etapa:

| Objeto | Generación / bytes | SHA256 |
| --- | --- | --- |
| `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/history.archive.gz` | 1791079848266646 /17,219,602 | `a395bd910cc4b4b68d60bb68c2231d1658061831f995ac123657191223c5427f` |
| `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/manifest.json` | 1791079862363516 /16,778 | `12bc8b1f2533ff43a7deabbd7e6eff52d2475c78a23cd0a12a4087a877e9fdc3` |

**No liberar antes de 2026-10-11 02:11:08.854479 UTC** y tampoco automáticamente
al vencer mínimo: hold hasta liberación manual autorizada. No borrar backup,
staging original/forense, sobrescribir objetos ni cambiar IAM/lifecycle. Restore
fiel comparó todo el snapshot/datos/metadata/índices/validadores/joins; no confundir
el primer import fallido con el restore aceptado. F eliminó solo VM `zelerdata-restore-aeefe993`/ID2416531264420713648
y disco 8831012956187399344 por identidad, evidencia fuera; no recrearlos.

Limpieza local final PASS: 4 contenedores/6 volúmenes nombrados +1 configdb/perfil
propios; anteriores perfiles/contexto preservados y 32 evidencias intactas. No
prune ni limpieza adicional. Logs originales RED/fallos/parser/diagnóstico404 se
preservan; no reescribir el ledger con resultados de fixtures.

Hoja privada de Cuenta Zeler, Apps Script aún **no publicado**:
[hoja de prueba](https://docs.google.com/spreadsheets/d/1IzBEJ6fTs3-juTvWYv0P9dK_0gMpS5jo5y18KlsmitU/edit).
El usuario instaló archivos/configuró token en UserProperties; no copiarlo ni
revocarlo/rotarlo. `OrdenesSanas!A1:D4` contiene 4×4 efectivos nativos mediante
`ARRAY_CONSTRAIN(ZELERDATA_ORDENES("HOPEMOB","2026-09-01","2026-09-02","todos","","si"),4,4)`.
Sin errores/no datos pegados de API; recoveryOFF/Mongo-only/auditoría-contadores-uso
normales; otras seis fórmulas inactivas. Visual no revisada, solo metadata de
formato. No escribir más celdas, adaptar/publish add-on ni probar partial en Sheets
como sustituto del parcialAPI normal pendiente.

## 8. Continuación segura para el nuevo agente

**Primero trabajo local de lectura, no una llamada productiva.**

1. Leer este archivo, documentos §7, AGENTS/lessons y autoridad vigente. Confirmar
   checkout/ownership con `git status --short` y el historial por ruta de §3;
   preservar cambios ajenos, sesiones, evidencia y backups. Revisar ledger y SHA
   de artefactos; no repetir controles/builds válidos ni tratar caches como permisos.
2. Esperar que el usuario **retome explícitamente**. Esa reanudación no amplía
   presupuesto ni por sí sola concede retry del AMQP404 u operaciones nuevas.
   En pausa solo documental/local autorizado; no VM/cloud/browser/API productiva.
3. Revisar offline el reader fallido y etiquetas de endpoint/etapa/counts. Conservar
   original/rawSHA; antes de proponer nueva llamada, instrumentar diagnóstico seguro
   y reproducir con fixtures representativos (404/auth/path/truncación/primererror).
   No revelar URI/credenciales. **No se autorizó aquí modificar ni rerun ese helper.**
4. Cualquier repetición productiva del diagnóstico fallido exige excepción expresa
   al no-retry, destino/alcance/deadline/count definidos y offlineGREEN previo.
   Si vuelve a fallar: STOP, evidencia sanitizada/error exacto, sin otra llamada.
   No concluir ausencia ni pedir al usuario un ID Full para avanzar.
5. Tras reanudación/autorización aplicable y gates cerrados, preparar un plan
   seleccionado: target `platform-vm`/`zeler-platform-dev`/`us-central1-a`, identidad,
   capacidad fresca antes de cada pull, Compose base+nueva versión exclusiva del
   override (actual preservado), **worker primero y gateway después** con pins §3,
   HOLDtrue/guard82/history/recovery/refreshOFF. API/registro14/índices intactos.
   Todavía no existe/aplica ese nuevo override; nunca hacer broad Compose restart.
6. Recuperación compatible forward con pins nuevos/HOLD/plan paused/historyOFF,
   jobs/consumos/cutoff/proofs/leases conservados. **Gateway antiguo sin guard no
   es rollback postactivación; worker legacy tampoco sobre policy_authority.**
7. Solo posteriormente, con topología, reparto normal por fase/fuente, OAuth/budget,
   día/deadline/runtime verificados y recibo pinned, seguir prepare→activate CAS
   del [runbook](zelerdata-historico-control-piloto.md). OAuth/Google/2FA los realiza
   el humano legítimo cuando proceda; sin force/revocar/copiar tokens/admit manual.
   Activar solo rangos previamente acotados; contar intentos físicos y dos cambios
   auténticos. STOP ante 429/error/timeout/inconsistencia/budget/deadline o pérdida
   de aislamiento; no refund/reset/steal/expandir ni usar Full. Reportar faltantes
   concretos y mantener estado seguro, sin declarar el goal terminado.

Si no ocurren los dos cambios auténticos dentro de la ventana, registrar aceptación
pendiente; no fabricar eventos, escribir negocio ni extender los 90 minutos. El
usuario deberá decidir cualquier alcance adicional.

El siguiente agente debe entregar evidencia diferenciada por plano y saldos
canónicos, no promesas basadas en salud, tests o buildSUCCESS solamente.

## 9. Continuación del 5 de octubre — evidencia nueva, no cierre

El usuario reanudó trabajo local/coordinación y eligió integrar **directamente,
sin SDD**. Las entregas originales CUOTAS/AMQP se recibieron con cese de escritura;
la asignación, relevo y nueva lista cerrada de integración están en
[zelerdata-historico-paralelo.md](zelerdata-historico-paralelo.md).
El [informe de integración](zelerdata-historico-integracion-20261005.md) separa
contrato local, pruebas, publicación y gates productivos. No sustituye ni modifica
los resultados históricos anteriores ni reinicia datos, cuotas o plazos.

La única excepción AMQP recibida en esa conversación **ya se consumió**:
AMQP-REPEAT-1,20:02:28–20:02:46UTC, exit2 `management_configuration_invalid`;
reader iniciado, Management0GET/Meli0/mutaciones0, STOP antes de red. No segundo
intento, endpoint/credenciales alternos o reparación. La causa404 y topología/
publicación/TTL/entrega real siguen pendientes. **Producción está detenida**;
no avanzar builds/despliegue/piloto por pruebas locales. Los demás permisos
condicionales siguen vigentes en su alcance, no son autorización de otro retry.
Full permanece excluido y la aceptación de §1 sigue pendiente.


Calidad local final de esta continuación:6395PASS/20SKIP, protectedrs019PASS,
focused455PASS; ruff/formato/mypyglobal665/direct/schemaPASS sobre snapshot
congelado1072paths. Recursos de prueba propios retirados; previos preservados.
Solo gateway/Sheetsworker se afectan funcionalmente: las imágenes servidas no
incorporan estos cambios y no se construyeron/desplegaron en esta continuación.
Recomendar imágenes nuevas exactas de main cuando gates/autoridad permitan
continuar, sin rebuildAPI. Detalles de código/publicación/evidencia en el informe
vinculado, no prueba de aceptación productiva.

Código de esta continuación publicado: reader
`2c657015d5d64a6650811d378ebdae21cc0e6ed2` e integración directa
`9149d00b7d979fb4498a4c16ae6c3220172b566f`; remoto=HEAD/árbol limpio
verificados tras push. Código y bits ejecutables ligados al snapshot probado;
actualización posterior exclusivamente documental, identidad consultable por
`git log` de este archivo. Builds0/despliegues0/piloto0; no repetir el intento
AMQP consumido. La aceptación global de §1 sigue pendiente.

### Reanudación posterior a «Realizalo»

Dos imágenes nuevas necesarias desde main352f3bd6 construidas/verificadas,
no desplegadas: worker build4a4c14a8/digest69d9da8d y gatewaybuild86be40be/
digest866dca4e. Referencias completas/timestamps/procedencia/consumos en
[integración](zelerdata-historico-integracion-20261005.md). API intacta.
El fallo AMQP bloquea rollout/OAuth/piloto; no invalida builds independientes
previstos en la autorización histórica cuando hay delta probado.
Se solicitó solo nueva inspección estructural0red/0cambios de configuración
worker,60s/5min, aún sin autorización ni ejecución. Lectura AMQP-REPEAT-1
consumida/no reutilizable. No avanzar sin gates ni inferir cierre porbuildPASS.

### Inspección ampliada recibida y ejecutada

El usuario autorizó la inspección AMQP necesaria, incluso ampliada. Solo lectura,
no modificación del broker ni expansión de piloto. Tras preparación offline y
STOP en cada fallo, se identificó userinfo Management igual a broker; normalizar
en memoria sin cambiar destino permitió leer metadata. Gate Mongo instalado
compatible PASS con hello/listCollections, sin documentos/aplicación de schemas.

Ronda AMQP revisada: diez GET200 completos; request11 HTTP404 exacto en
`zeler.sheets.claims.retry.1s`, STOP sin retry/fallback. Acumulado de este tramo:
13 GET iniciados/13 respuestas/12 cuerpos completos, cero Meli/Full/mutaciones.
Límites operator reales conservados; no-loss/ingress/admisión siguen sin prueba.
La cola1s es requerida y no se autodeclara; HTTP404 solo no demuestra ausencia.
Root ejecutó la comprobación pasiva única a23:44:15–21UTC: broker404/not_found,
ausencia confirmada,1conexión/canal/RPC iniciados y completados,0Management/Meli/
mutaciones. Cleanup tool_error/owned_transport_closedFalse → STOP sin repetir.
El proceso transitorio terminó; no afirmar cierre limpio/server-side por eso.

[Ledger y asignación](zelerdata-historico-paralelo.md),
[integración actualizada](zelerdata-historico-integracion-20261005.md) y
[reparación condicional NO autorizada](zelerdata-historico-amqp-reparacion-propuesta.md).
Ausencia confirmada; aprobación solicitada solo para esa creación concreta,
todavía NO recibida/NO ejecutada. No re-pedir autoridad
condicional vigente. Sin pull/deploy/OAuth/piloto nuevo ni reset de cuotas,
checkpoint/cutoff/díaUTC/plazos; aceptación §1 todavía pendiente.

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


## 10. Continuación del goal: gates abiertos, sin reinicios

**Snapshot 2026-10-06T02:33:25.426754+00:00. No aceptación global ni nueva ventana piloto.**
Root continúa con autorización amplia para operaciones necesarias, cada una
acotada y registrada antes de ejecutarse. No autoriza Full, resets de datos/
quotas/checkpoints/cutoff/plazos, force OAuth ni eventos de negocio fabricados.
[Ledger único](zelerdata-historico-paralelo.md) conserva fechas, consumos, hashes,
propietarios y los STOP; lo siguiente es resumen, no otra autorización.

| Entrega / plano | Evidencia de esta continuación | Gate pendiente |
| --- | --- | --- |
| Reintentos AMQP | Una inspección fresca23GET pasó metadata/topología; buckets1s/5s/30s/2m/10m presentes. EventsDLQ315 conservados. | No demuestra entrega, timing, no-loss ni worker WAIT. |
| Demora temporal | Dos probes policy_invalid antes de publicar. Inspector posteriorPASS encontró exact3caps60s/1000/1GiB sinmessageTTLpolicy. Probe con ese perfil: publishconfirmado, vacío4.03s, nonce/DLXexpired8.03s/ACK/getempty y2DeleteOk; overallSTOPcleanupSSL. | La muestra transporta correctamente, pero no acredita cleanTCP, workerWAIT ni no-loss90min. No repetir para mejorar cierre. |
| Estado canónico | Auditoría7reads STOP recoverycap1001. Plan legacy único con cutoff2026-09-24T05:36:28Z; registry14 exact/sinFull/6routing. Bootstrap1succeeded/checkpoints7 y12failed preservados. | Lectura posterior7PASS confirmó campos canónicos genuinamenteMISSING y ACTIVErecovery/sync0 solo filtro/momento,8runs+1operation preservados. No saldo histórico2500 ni aislamiento global; faltan controles reales de productores. |
| Corrección de admisión | Core/Gateway locales: hojas ausentes + whole-doc CAS, leases/ledger corruptos fail closed, relink$max, pilot seed pausado por scope trusted. RED23+RED3;26GREEN,55adyacentes y3Mongo reales PASS. | Freeze905code y gates finales6421PASS/20SKIP+19protegidas/ruff/formato/mypy667/direct/schemaPASS; publicación propia pendiente. Counter nuevo0 es prospectivo, no prueba histórica ni prepare. |
| Imágenes | Procedencia actual de worker69d9/gateway866d source352 existente PASS;0solicitudes nuevas. Solo Gateway usa la admisión cambiada; AST de helpers worker/API se conserva. | **Nuevo Gateway** desde commit exacto en main tras gates. Worker352 existente se reutiliza; no rebuild API. |
| Runtime | Capacidad medida34.03GiB raíz/44.20GiB Mongo y0OOM/restarts en la inspección fechada; runtime aún antiguo7054/79f, API3f7. Caddy no tiene healthcheck Docker, no llamarlo unhealthy/healthy por ese campo. | Capacidad/proveniencia/render Compose completo/HOLD/rollback/readiness frescos antes del rollout elegido worker→Gateway; no restart amplio. |
| Superficies | App autenticada: seller activo, sin iniciar OAuth. Hoja nativa16celdas efectivas/error0 leídas como baseline existente. | Baseline puede ser cache; no adquisición/recalculo fresco ni piloto. OAuth legítimo sin force y aceptación5fuentes/dos cambios reales siguen pendientes. |

Detalles de la corrección: [propuesta legacy](zelerdata-historico-cuotas-legacy-propuesta.md)
y [informe TDD](zelerdata-historico-cuotas-legacy-implementacion-informe.md).
Los informes AMQP de [perfil propuesto](zelerdata-historico-amqp-probe-policy-propuesta.md)
y [variante congelada](zelerdata-historico-amqp-probe-policy-informe.md) son evidencia
local; el resultado real STOP del ledger manda sobre sus hipótesis.

Próximo orden: observar hechos faltantes sin publicar → integrar entregas y
congelar todos los escritores → gates finales en Linux aislado → publicar solo
trabajo propio → Cloud Build Gateway afectado → rollout seleccionado con gates →
OAuth/prepare/ejecución **solo con baselines y quiescencia acreditados** → aceptación
original. Si hay identidad/day/deadline previos, se conservan; no nuevo UUID ni
ventana artificial para superar un gate.


## 11. Publicación y única imagen nueva verificada

**2026-10-06T03:28:49.943072+00:00 — preparación concluida, producto aún no aceptado.**

- Código propio: `1c367664569e2f908298047a6bdc508bf304ab8f`.
- Evidencia/documentación: `a10e31496c408f9ab321196fc5ad27f2cc6a10b8`;
  main/remoto exactos y tree limpio observados antes del build. Solo26paths propios.
- Candidato1101paths/tar40f2645a, todos905codebytes/modos preservados hasta commit.
  Full6421PASS/20SKIP, protected19PASS, focused55PASS, ruff/formato/mypy667/
  direct-Meli/schemaPASS. Primerfull1FAIL porfakeNone/CAS se conserva; se corrigió
  solo `test_lifespan_rabbit.py`, sin debilitar el guard, y pasó el rerun completo.
- **Un solo Gateway**: build `121b3b08-3d3f-4b12-b40c-2a4f2ba7d590`,
  SUCCESS/VERIFIED, sourcea10e exacto del repositorio conectado, verificador canónico
  artifact/build/project/source/repo/digestPASS.
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:4f90ba7c48fd2258f35cb4b80a2ab3d8eb93d30786ce761d32a6b6a3475e8268`.
- Worker69d9/source352 ya VERIFIED se reutiliza; API3f7 no se reconstruye.
  Los helpers/constants core usados por ellos conservan AST.
- **0descargas VM,0despliegues,0OAuth,0prepare/piloto de esta continuación** al
  registrar este snapshot. Runtime observado aún7054/79f/3f7: no confundirlo con
  la imagen construida. Se requieren controles/render/capacidad frescos y un
  rollout cerrado worker→Gateway antes de activar nada.

Broker: muestra propia con perfil real confirmó nonce8.03s y retiro de2colas,
pero terminó STOPcleanupSSL. Se admite solamente como evidencia de esa muestra;
no cleanTCP, no pérdida90min ni rutaWAIT del worker. No repetir para mejorarclose.
La admisión del piloto requiere evaluación proporcional explícita de riesgos/
controles y aceptación original, no basta la salud ni este build.

OAuth: lectura del frontend encontró CTA oculto para cuentas activas y sin entrada
ML desde SheetsConfig; no se modificó frontend ni se revocó/copió token alguno.
Root deberá verificar el entrypoint normal desde el contexto autenticado real,
sin force, reasignación manual ni callback sintético. El plan legacy mantiene
cutoff/progress; campos canónicos genuinamente ausentes permiten únicamente seed
prospectivo pausado dentro de ese OAuth, no saldo histórico ni ventana renovada.


## 12. Continuación real: OAuth, primera ventana y STOP conservado

**Snapshot 2026-10-06T04:39:18Z; objetivo NO completado.** Detalles/consumos y cada
intento están en el [ledger único](zelerdata-historico-paralelo.md). Los snapshots
anteriores son históricos, no estado actual.

- Gateway `4f90ba7c48fd2258f35cb4b80a2ab3d8eb93d30786ce761d32a6b6a3475e8268`,
  fuente `a10e31496c408f9ab321196fc5ad27f2cc6a10b8`, build VERIFIED
  `121b3b08-3d3f-4b12-b40c-2a4f2ba7d590`, servido/asentado.
- Worker `69d9da8d5e57c93868844349c489b33d0bf743612e718616d282a7ff6fe64a79`,
  fuente `352f3bd6f42c89929bb37006c04385a9492d3031`, build VERIFIED previo
  `4a4c14a8-bb83-4aab-87f6-b1bb2be1389d`, reutilizado/servido. API3f7 sin rebuild.
- HOPEMOB real verificado en MercadoLibre; OAuth normal desde el enlace visible
  de Accounts, paísMéxico, sinforce/nuevosgrants/copia de tokens ni callbacks
  fabricados. App mostró «Cuenta MercadoLibre conectada». No frontend fix/build.
- Readback PRIMARY: plan PAUSED5/noFull, cutoffSep24/rango anual/progress.size4,
  caps800/150/250/300/500/total2000/daily500300; registry14/6/fingerprint704afe y
  bootstrap13 observables anteriores intactos. No afirmar digest retroactivo de
  contenido de checkpoints: la evidencia anterior era metadata/cardinalidad.
- Primera preparación y activación canónicas, recibos aplicados/fijados,
  hasta **05:52:57.845UTC del6Oct**, no90min adicionales desde activate. El
  monitor detectó ValueError de mensajes y pausó canónicamente al primer error.
  Estado final leído: **69 cargos/67 envíos, 56initial+13maintenance, Full0**.
  Los cargos sin envío no se reembolsan. Mensajes genuine changed0, no aceptación.
- Forward cerrado después del STOP: historiaOFF/HOLDtrue/recoveryrefreshOFF;
  worker/Gateway actuales, no downgrade ni otros servicios reiniciados. Settling
  PASS36:19UTC, rootfree35665088512,0pulls. API3f7/registro14/datos/jobs conservados.
- Causa demostrada con3RED BSON offline +2reads productivas sin provider: top
  sweep_end04:30:45.407000UTC vs checkpoint ISO04:30:45.407414UTC, mismo BSONms,
  mismo seller/source/start. CUOTAS corrige solo caller y entrega test/informe;
  strictcollector/checkpoint/consumos no se reescriben ni se resetean.
- Root agregó OPS `resume` con dos recibos fijados/stateONLY/samewindow/caps
  conservadores;47 enfocadas PASS. Todavía no gates finales conjuntos ni build/
  despliegue del fix o resume productivo. No iniciar suitegeneral antes de cese.

Composición actual seleccionada, en este orden (archivos anteriores preservados):

```text
/opt/zeler-platform/docker-compose.yml
/var/lib/zeler-platform/.history-rollout-20261004T022714Z/interlocked-override-b867b27.yml
/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314/closed-overlay.json
/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314/admission-overlay.json
/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314/history-overlay.json
/var/lib/zeler-platform/.history-closed-rollout-20261006T033918Z-a10e314/forward-close-overlay.json
```

Root sigue único productor/Git/build/config. No reprepare/otroUUID/extensión ni
repetición ciega del endpoint; después de fix/gates/worker compatible, considerar
solo saldo/plazo original restante con snapshotpause quiescente/recibos pinned.
Si vence, conservar pendientes y no crear otra ventana bajo esta autorización.
La aceptación5fuentes/certificados/APIpartial/nativa fresca/dos incrementales reales
sigue pendiente; readiness, órdenes12jobs reutilizados o cache16celdas no la sustituyen.


### Controles conjuntos de esta corrección, 2026-10-06T04:56:13.345519+00:00

Freeze1104/tar`76db7abc2647614cd9c13512af4a96c5f3e7f2207959b915b587d29b1e71d10b`: **full6446PASS/20SKIP**, protected19PASS, enfocadas109PASS; Ruff/formato/mypy669/direct-Meli/schemaPASS. Ocho exit0 y snapshotantes/despuésintacto;907codebytes+modos delcheckout coinciden. Full402.282s/protected5.666s. Colisión inicial de importtests en focusedLinux conservada; solo fixture independiente corregida, sin excluir controles ni cambiar runtimecode. Ambos especialistas habían cesado antes de suite.

Imagen afectada: **solo Sheets worker** por caller de mensajes; OPSresume via stdin, Gateway/API sin comportamiento servido afectado. Sourcebuild exactmain pendiente de publicar/verificar; no reconstruir imágenes no afectadas. El piloto siguePAUSED69/67/Full0 y hasta05:52:57.845UTC original; gates verdes no son despliegue, reanudación ni aceptación. Native reentrada mismafórmula16celdas no produjo rutaAPI observada en readlogacotado: no afirmar recálculo fresco.


## 13. WriteConflict corregido; ventana original vencida sin reanudación

**Snapshot 2026-10-06T06:01:00.511726+00:00; objetivo NO completado.**

La nueva claimsDLQ1/241bytes se atribuyó sin replay: código Mongo112,
WriteConflict/TransientTransactionError; stack del registro existente apuntó a
`acquire_devoluciones_operation`/freshness.update_one, dentro del txn y **antes**
del Gateway fetch. No era evidencia de HTTP500 ni schema121.

Root aplicó retry **DB-only**, máximo3 intentos totales de esa transacción abortada;
solo112+label y nuncaUnknownTransactionCommitResult. Firma/identidad/token y cuerpo
single-txn intactos. RED3FAIL/4PASS→7new+11existingPASS; conjunto final:
**6453PASS/20SKIP, protected19PASS, focused127PASS, Ruff/formato/mypy670/direct/schemaPASS**.
Tar1107/all908code `5e19ae784a67311c43a8668362cae3d5ebded1bc07616bbe82eaeeb14aaa92d6`,
sourceantes/despuésintacto; ambos especialistas cesaron antes de generales.

Publicado `412360169adc90dd04cd853337bcb895decde464` enmain, solo5paths propios;
ONECloudBuild `abd8a659-33d7-4521-9725-44c4af71c2e9` SUCCESS/VERIFIED/provenance
canónica PASS, repo exacto. Worker **servido/asentado**:
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:0df26cd905e49ae7e1d0185e967d1f0090491881aba237de86a3fa61a17610bc`.
Onlyworker image delta/ONEpull+recreate,60settle2components/0restartsOOM,
rootfree34375737344/Mongoseparate47457710080/RAM1888555008; Gateway4f90/API3f7
sin nuevos builds/restarts. Nueva imagen sobre closed7filecomposición; ruta exacta
pública Root en ledger/private`ACQUIRE112-DEPLOY-TARGET.json`. PriorCDccrollback
soloPAUSED/closed compatible, no restore/reset/counter/lease manipulation.

**Hasta05:52:57.845UTC original venció.** ReadonlyPRIMARY+oneplan a05:56:58.406655
confirmó PAUSED/mismoID/mismo until,69charged/67sent/56initial+13maintenance,
limit2500/5fuentes/Full0. No resume, relay delDLQ, nuevoUUID, reprepare, refund ni
prórroga aplicada. Solicitud específica de una sola prórroga hasta06:30UTC está
**pendiente, NO recibida**; la autorización general no cambia ese deadline.

La herramienta de transferencia originalONE fue preparada/TDD6PASS, defaultNOOP,
confirmación obligatoria antesACK, metadata/header/body originales, brokerambiguity
STOP sin repetir. **No ejecutada**. Exige gates actuales/pinned y deadline original;
no convertir flags o cierre local en proof remoto/atómico. Ver
[informe AMQP](zelerdata-historico-amqp-claims-one-informe.md) y
[propuesta/aplicación Core](zelerdata-historico-cuotas-transient-acquire-informe.md).

**Imágenes afectadas:** Worker para este piloto corregido; APIlector y dispatcher
no llaman el acquire. El **job ejecutor Bootstrap** sí lo usa y conserva el código
anterior: verificar su drift y construir imagen actual antes de una ejecución
futura necesaria. No reconstruir/desplegar dispatcher o iniciar/resetear los13jobs
protegidos para simular cobertura.

Pendiente aceptación original: cinco fuentes recuperables/certificados independientes,
API ORDERSpartialnormal (no Sheets), recálculo nativo fresco y dos incrementales
reales. Existing4×4cache/salud/6453tests/builds no sustituyen esos gates. Conservar
claimsDLQoriginal1 yeventsDLQ315; no replay ciego ni extensión implícita.


## 14. Mon5: worker desplegado, fallo remoto y cierre seguro

Esta sección y la cabecera prevalecen sobre estados operativos históricos de las
secciones anteriores. No prueba salud posterior a su fecha ni aceptación global.

- **Publicación y validación:** main/remote `c5378c99a81bb68933e5ea03ed76e1f095328030`,
  último checkout limpio confirmado 19:51:16 UTC. Ocho controles completos PASS:
  6,702 pruebas/20 skips, 19 protectores sin skips, 364 enfocadas; Ruff, formato,
  mypy (689 archivos), direct-Meli y schemas. Snapshot 1,140 paths preservado.
- **Único build nuevo:** Cloud Build `ff58fb55-5120-42e3-bc21-73ff927f5655`,
  SUCCESS/VERIFIED del commit exacto conectado a main. Worker
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:1681e6c34a2d328f860417decbc513121dc5cab482baec142d1000249bd2fc01`.
  Gateway y API no reconstruidos. Deploy acotado PASS 19:21:54.282373 UTC:
  una imagen/un pull, readiness inicial y +60 s, cero restarts/OOM; rollback7709
  conservado, sin cleanup, migración, validators ni cambios de scopes/topología.
- **Mon5 real:** resume 19:28:56.861152 UTC; STOP `fresh_source_failure`
  19:31:02.441020 y pausa 19:31:02.495475. PIN de pausa
  `3d994f3f3f575eeebd9771da311e3fb29e9478dfceb81abbcab10363352872b3`.
  La auditoría del intervalo registró 276 envíos: 270 HTTP200, cuatro HTTP404
  y dos HTTP429 remotos en RETURNS (19:30:37.960 y 19:30:44.700 UTC).
  El collector reintentó internamente después del primero: **la parada inmediata
  no se cumplió**. Warning tipado `safe_404_precondition_failure`: no ignorar
  la precondición ni certificar ausencia de devolución. Sin más proveedor tras
  reconocer los 429; leer metadata/logs del intento no constituye otro diagnóstico.
- **Consumo preservado:** 368 cargos/365 envíos; deuda previa de tres sin refund;
  inicial340 (O0/Q5/S250/M4/C81), mantenimiento28 (O14/Q3/S1/M4/C6), Full0.
  Shipments inicial250/250 agotado, pendientes cuatro unidades. Claims conserva
  tres unidades fallidas/cero completas; `ready_with_observations` no certifica
  cobertura. Q p3 aún pending con discovered/fetched/published0, sin readmit nuevo.
- **Quiescencia cerrada:** PASS 19:37:22.486967 UTC/92.204 s/SSH0.
  HISTORY OFF, 22 capas Compose, mismo worker1681/noPull/noDeps/downloads0;
  readiness inicial y +60 s, restarts0/OOMfalse. Gatewayc905/API3f7 intactos.
  Tres vistas iguales del plan PAUSED368/365/340/28/fence2/Full0 y plazo original;
  SHA `42a3dd0321d7520fe18ed8c35cf7bc1ddc77b02d371b905cd43ba4caa01216aa`.
  Libre raíz31,937,114,112 bytes; Mongo47,400,800,256; RAM disponible1,749,721,088.

**Trabajo pendiente, no autorización nueva:** CUOTAS tiene exclusivamente la
corrección local fail-fast de piloto429 y sus pruebas/informe, delimitados en
el ledger. No altera ordinary retries, cuotas, origen90, datos, deadlines o Full.
La cuota Shipments agotada no equivale a cobertura ni autoriza ampliación;
`allow_partial` aprobado sigue siendo sólo ORDENES. Faltan pruebas independientes
de histórico anual legible por las cinco fuentes y dos incrementos con cambios
reales. La muestra nativa y API parcial previas siguen PASS (véase §15); no
ampliar su alcance a certificación anual. Objetivo NO completado.


## 15. Corrección local del retry429 y auditoría de aceptación

CUOTAS entregó y cesó modificaciones. Seis archivos exclusivos verificados por
hash; helper de producto y ambos wrappers detienen la ejecución legitimada antes
del retry del collector. CAS sólo state PAUSED del EID/seller/controles capturados;
sin refund/reset. `remote_429` requiere metadata upstream1; local0 y metadata
incierta abortan conservadoramente sin fingir prueba remota. Ordinary sin piloto
conserva retries. RETURNS atraviesa la rama `SourceCallBudgetError` y después
convierte a WAIT, sin ventana failed ni `physical_budget_exceeded` artificial.
Esto cubre **429**, no todos los 5xx/timeouts; solicitudes ya en vuelo no se deshacen.

- TDD: 18 FAIL/1 PASS antes del cambio →124 PASS (23 nuevas/101 regresiones fake).
- Controles Root con todos los escritores congelados: **447 enfocadas PASS;
  6,725 generales PASS/20 SKIP; 19 protectores PASS/0 SKIP**. Ruff, formato,
  mypy692, direct-Meli y schemas PASS. Ocho recibos completos, recursos Colima
  propios y Mongo de prueba PRIMARY aislado, sin credenciales ambientales.
- Snapshot1,144 paths, SHA
  `27d4323c545f1e86455b5df78834f70b5c5aebec9d406e6464195a530c40da5e`;
  bytes/modos iguales antes/después. Sólo anotaciones de documentos centrales y
  lesson posteriores al freeze; ningún cambio ejecutable tras estos controles.
- Única imagen afectada: worker (consumer/onboarding/returns). Gateway/API readers
  no cambiaron; build/despliegue se registrarán separados, sin enable/resume.

| Requisito original | Evidencia conservada / resultado |
| --- | --- |
| OAuth humano normal HOPEMOB, sin force ni tokens copiados | PASS previo (§12), cuenta conectada legítimamente; no nueva sesión afirmada |
| Full excluido; cuotas/EID/cutoff/checkpoints/datos y registro14 preservados | Operaciones sin reset, quiescencia19:37 y plan Full0; no permisos ampliados |
| API normal parcial ORDENES y guard de otras fórmulas | PASS previo:28 órdenes adquiridas; no habilita parcial para otras fuentes ni Sheets |
| Muestra nativa en Sheet privada | PASS previo06:09:50 UTC: Apps Script completado0.667s, encabezados+3órdenes en4×4; no certificar cinco fuentes desde ella |
| Fuente por fuente: histórico recuperable anual, cobertura/readers independientes | NO acreditado: Qp3 sin adquisición, Claims3unidades fallidas, Ship250/250 con4pendientes; readyobs no es certificado |
| Dos ciclos incrementales con cambios empresariales reales posteriores al cutoff | NO acreditado:28sends no prueban cambio; dos passes del mismo scan son un ciclo, no dos. Faltan versiones/baselines reales y readback enlazado |
| Parada inmediata429 sin retries internos | Mon5 incumplió; fix local PASS/imagen servida, sin nuevo ensayo con proveedor por STOP |

No reentrar la fórmula ni repetir llamadas para reconstruir pruebas que ya están
logradas. Evidencia pasada mantiene su alcance fechado, no prueba salud actual.
Goal permanece abierto con los dos gates de aceptación principales anteriores.


## 16. Rollout cerrado del fix429, excepción consumida y plazo conservado

- Código publicado: `ed2715a1897f24c746cd2d97f79c14c31a072f1f`. Build único
  `4dec4719-200f-4bac-ba70-0aeb416949c6`, SUCCESS/VERIFIED, repositorio conectado,
  procedencia canónica verificada20:16:34.936016 UTC. Imagen worker
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:be4fc0c55e98c6c1979175e3285fec0bc16741d8e4f970a1e139ccaeb2298612`.
  Gateway/API no reconstruidos ni sustituidos.
- Primer rollout STOP20:19:28.810593 UTC/133.400s/SSH2: timeout del pull120s,
  antes de recrear. Hubo **una descarga iniciada**, no cero: el contador `downloads0`
  se incrementaba sólo tras el retorno exitoso. Inspección readonly20:20:41 PASS:
  target ausente, worker1681 sano/PAUSED, ninguna llamada nueva al proveedor.
  Metadata daemon acotada:3 registros seleccionados cancelados; no causa global
  de red/auth inferida ni logs/payloads crudos publicados.
- Usuario autorizó una única repetición pull240s/primera recreación cerrada; guard
  temporal local rechazó antes de START/SSH. Esa autorización aún no consumida.
  Luego autorizó10min adicionales hasta20:42:58 UTC **sólo para rollout cerrado**.
  No se cambió `execution_until` del piloto ni sus presupuestos/checkpoints.
- Excepción efectivamente ejecutada: PASS20:27:33.484874 UTC/112.394s/SSH0,
  un pull completado y primera recreación;23 capas, delta exclusivo de imagen.
  HISTORY/recovery/refresh OFF, gatewayc905/API3f7 intactos. Worker readiness2
  inicial y +60s, gateway dependencies2, healthy/restarts0/OOMfalse; grace60,
  outer120. Rollback1681/sourcec5378c9 local/retrievable conservado, sin cleanup.
  Tres vistas del plan completo iguales SHA
  `42a3dd0321d7520fe18ed8c35cf7bc1ddc77b02d371b905cd43ba4caa01216aa`:
  PAUSED368/365/340/28/fence2/Full0/hasta20:32:58. **0 nuevo Meli/0 resume**.
- Salud/capacidad final readonly PASS20:32:52.806288 UTC/11.034s/SSH0:
  actualworkerbe4/GWc905/API3f7 sanos,23 capas, montaje Mongo exacto, PRIMARY y
  mismo hash del plan; rollback1681 existe. Raíz31,382,970,368 bytes libres/
  6,139,643 inodos; Mongo47,447,777,280 bytes/3,276,150 inodos; RAM disponible
  1,811,509,248 de4,103,168,000 bytes. Docker22imágenes10.79GB/11containers;
  sin limpieza de imágenes/volúmenes. El primer observador de esta fase tuvo un
  NameError antes del cuerpo: stderr+orden de declaraciones y RED/GREEN offline
  prueban cero Docker/Mongo/Meli en ese intento; originales conservados.

La imagen servida coincide con el commit ejecutable autorizado. Anotaciones
posteriores de estos documentos no requieren rebuild. La salud/imagen correcta
no demuestran un nuevo 429 productivo, histórico anual ni cambios incrementales.
El plazo de adquisición transcurrió20:32:58 sin resume; no usar la prórroga cerrada
ni el saldo global aritmético para reanudar proveedor.

### Bloqueo adicional identificado: granularidad de Shipments

El código crea lotes de100 IDs, hace relación+detalle+costo por identidad y
publica sólo al terminar. **100×3=300 solicitudes supera el cap250**; un agotamiento
puede dejar recursos adquiridos sólo en RAM. Compatible con0completed/4pending,
no causa runtime única acreditada. CUOTAS entregó propuesta readonly, no fix:
conservar IDs/key originales, checkpoint estricto por identidad y persistencia
+CAS del cursor en una transacción bajo owner/state/lease/binding. Root debe
verificar modelo/schema antes de escribir. No seed del cursor desde contadores,
fechas o documentos actuales; no keys nuevas, refund, phase relabel ni más GET.
La solución futura no recupera por sí misma los payloads perdidos ni crédito250.

**Aceptación global sigue abierta:** anual legible cinco fuentes y dos ciclos con
cambios empresariales reales. Muestra nativa/API parcial/OAuth previos preservados;
ni este despliegue ni las6,725 pruebas reemplazan los gates faltantes.


## 17. Cursor durable de envíos — unidad local, sin rollout

Usuario autorizó45min locales20:46:13→21:31:13 y, posteriormente, tiempo necesario
para terminar controles/documentación. Esto no modifica el piloto vencido,
PAUSED/HISTORY OFF, sus250 créditos de envíos consumidos, Full0 ni los permisos
productivos. Runtime sigue siendo el registrado en §16; no inspección nueva.

CUOTAS entregó cinco archivos exclusivos y cesó. Queue y worker conservan los
100IDs/key originales, validan cursor/owner/state/lease/seller/model/list antes
RPC, inicializan únicamente ausencia genuina a0 y publican **una identidad +
cursor + readback** en transacción snapshot/majority. Un fallo/CAS perdido de la
siguiente unidad no borra la anterior. Costos transitorios conservan campos
independientes pero no concluyen unidad/costo ni renuevan la frescura del caché.
Nunca seed del cursor desde250 cargos, timestamps o documentos preexistentes.

Refresh ordinario legítimo de COMPLETED archiva su checkpoint real compacto y
abre un ciclo nuevo0; el parcial/failed no pierde offset ni attempts. H1 con
`reopen_terminal=False` y pending/running permanecen intactos. El archivo de un
checkpoint no prueba contenido empresarial cambiado ni dos incrementales reales.

### Evidencia local — clases separadas

- CUOTAS: RED10 antesfuentes y REDlifecycle3/1 antesenqueue;16new +101regresiones
  fake=117PASS, cuatro sentinels antiguos PASS y Ruff/formato/mypy4targetsPASS.
- Root: cuatro pruebas reales rs0 PASS y después23 protectores sin skips,
  incluidos snapshot/majority, budgetstop2units, validatorrechazo0RPC,
  rollbackunidadactual y reanudación sólo despuésdelcursor concluido.
- Root enfocadas940PASS y Ruff/formato/mypy694/direct-Meli/schema PASS.
  Snapshot1,147paths
  `dd56ef8cdb03f339a3a385eceaac1ecb7ecb3d4319af86c551e036271a5a6034`.
  Suite general del conjunto **6,741 PASS/24 SKIP,415.80s** (control418.574s).
  Ocho controles finales completos PASS. Cuatro skips nuevos de la suite general
  por rechazo del Mongo ambiental no sustituyen los cuatro positivos reales
  ejecutados aparte; protected23PASS/0SKIP. No reducción del alcance requerido.
- Primer control enfocado agotó600s por un harness previo de cancelación que
  esperaba una señal sin límite. Catalog/process/pacing no cambiaron por el fix
  de envíos; Root acotó la espera y separó cancelación manual de timer externo,
  sin quitar assertions. Un standalone40s y logs originales conservados.
- Siete assertions antiguas de rollback del lote completo fueron RED al cambiar
  la unidad durable; ahora exigen primer envío válido/costo/address preservados,
  cursor1, segundo fallido/prior sin alteración y retry sólo segundo. No relajar
  propiedad, lease, sourceproof, PII ni prohibición de marker histórico.
- El último control de la ventana45 acabó18.877s después del plazo debidoalrunner;
  quedó registrado, sin iniciar full hasta nueva autorización. No operación
  productiva, build, despliegue, sourceGET, reset o publicaciónGit todavía.

### Drift y gates futuros — no permiso de ejecutar

Se afectan **sheets-api** (enqueue/reopen) y **sheets-worker** (pub/cursor).
El runtime anterior be4/sourceed271 y API3f7 no contiene esta unidad. Una vez
publicada y validada, se requieren builds Cloud Build VERIFIED separados de
ambas imágenes afectadas; no reconstruir gateway ni otras imágenes.
Orden compatible futuro: API nueva primero y worker después, antesdehabilitar
la adquisición; API vieja+worker nuevo puede dejaroffsetlen trasreopen y fingir
una renovación sinGET. Rollback anterior sólocompatible **CLOSED**, no ordinary
activo ni borrado de cursores. Preparar rollback que entienda el nuevo contrato.

La colección recovery_jobs es raw de producto; el schema hipotético no existe
localmente. Eso no prueba ausencia de validator productivo. Antesdecualquier
rollout, inspeccionar metadata real de validator para cursor/history, proponer
aplicación separada sólo si necesaria; un matched no-op no demuestra compatibilidad.
No aplicar validators por inferencia ni por el grant local.

Este arreglo no recupera payloads perdidos ni reembolsaS250. Siguen pendientes
anual legiblecincofuentes ydosincrementales con cambios empresariales reales;
OAuth/muestra nativa/API parcial previos conservan su alcance aprobado.


**Cierre local validado:** source/lockfile/dependencias/modos coinciden con el
snapshot; sólo estos documentos/lessons anotados después. La unidad se publica
con código, tests, informe y fixtures de control actualizados. No build, deploy,
validator, proveedor o reinicio productivo desde esta autorización local.
Para servir la nueva unidad siguen pendientes imágenes API+worker y sus gates
separados; el piloto vencido/S250 agotado no se reabre por este resultado.
