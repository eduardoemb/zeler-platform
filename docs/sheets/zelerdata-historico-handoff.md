# ZelerData: handoff del histórico al vincular

**Punto de entrada único para retomar. Cierre documental del 5 de octubre de 2026
UTC: objetivo global NO completado, sesión detenida por instrucción del usuario.**
No continuar ahora con despliegues, diagnósticos productivos, builds, OAuth ni
piloto. Las autorizaciones condicionales anteriores no anulan esta pausa. Este
archivo registra evidencia pasada; ninguna observación implica salud actual.

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

## 5. Gates bloqueantes y aceptación pendiente

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

## 6. Autoridad, presupuestos y ledger — pausa actual prevalece

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
