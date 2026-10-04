# ZelerData: propuesta de publicación y piloto acotado

## Estado vigente — cierre local del 4 de octubre de 2026 UTC

**Calidad local y respaldo A–F PASS; rollout/piloto no ejecutados.** Cierre del
rescate publicado previamente en `357e055d5a26dd71f46bd1009c7aa62d6717108a` y remoto
confirmado. La fuente candidata actual añade cuatro archivos ejecutables a esa
base: operador/tests y fix cutoff BSON core/test gateway; **ya no es idéntica a
d78**, todavía debe publicarse a SHA exacto antes del build necesario.

| Gate | Estado medido / siguiente paso |
| --- | --- |
| Calidad actual | Linux **5,981 passed/9 skipped/393.71s, exit0**, 02:56:23.139478→03:02:59.525633 UTC; protected separado **8 passed/2.09s**, cubre ocho skips Mongo. Caddy intencional es el noveno. Ruff/formato/mypy655 y direct-Meli PASS; no sumar lotes. |
| BSON default real aislado | CLI CAS con `create_runtime_db()`/tz_awareFalse y admisión con constructor Motor gateway PASS; 29 OPS +17 gateway enfocadas. Sin OAuth/session/provider ni acción productiva. [Evidencia/controles](zelerdata-historico-control-piloto.md#5-evidencia-y-siguiente-gate). |
| Imágenes | API/worker d78 verificadas/cacheadas, comportamiento sin delta; no reconstruir por OPS/docs. Gateway requiere **un nuevo build** desde el SHA publicado exacto por su admisión OAuth corregida; d78 antiguo no contiene el fix. Build/procedencia pendiente, ninguna imagen nueva desplegada. |
| Runtime | Baseline cuatro servicios PASS03:07:00.996899→03:07:05.538659 UTC: HTTP200/dependencias OK/healthy/restart0/OOMfalse/digests anteriores, sin reparación/deploy. Fallo inicial era checker: gateway `/ready` devuelve `status="ready"`, no readybool; clasificado offline6fixtures/captura propia, histórico preservado. No incidente productivo demostrado; revalidar tras rollout. |
| Piloto | HOPEMOB82453304 solamente, cinco fuentes/90min/2,500 físicos/Full0; índices/registro/rollout/activación productiva pendientes. Interlock legacy y autoridad persistida obligatorios, sin alterar otras cuentas. |

Dos normalizaciones localizadas: cutoff BSON leído→UTC solo para cálculo y
execution_until→UTC solo en comparación de caps. Conservan cutoff persistido,
presupuesto/consumos/checkpoints/leases, deadline y CAS. Caller servido de admisión
solo OAuth gateway; no cambiar globalmente tz_aware ni atribuir el fix a API/worker.
Recibo final privado `zeler-pilot-gate-707d3daba082/verification-receipt.md`;
snapshot fuente completo/RO y cuatro hashes ejecutables intactos. La limpieza
local final eliminó solo fixtures propios, perfiles/contexto anteriores preservados.

Las secciones históricas siguientes conservan evidencia por su fecha; no prueban
estado actual ni sustituyen este cierre. Autorización sigue condicionada a gates.

## Autorización vigente — ampliación del 4 de octubre de 2026 UTC

Rescate B–F y rollout/piloto ya autorizados **condicionados a auditoría, respaldo recuperable, calidad y recuperación compatible**; [alcance canónico y estado](zelerdata-historico-rescate-candidatos-propuesta.md#autorización-vigente--ampliación-del-4-de-octubre-de-2026-utc).
**Auditoría corregida PASS: 41 miembros, exit 0**, única excepción expresa al no-retry; 2026-10-04 01:18:13.686340→01:18:37.608276 UTC, diez fixtures offline previos verdes. Estructura/conteos/metadata coincidentes; prelude 7.0.31/Tool100.16.0 excluido, sin Mongoqueries ni escrituras originales/Full.
B/C y **D fiel único autorizado PASS** 02:07:49→02:09:31.183384 UTC: nueva base fiel_v1, datos/metadata/índices/validadores/joins exactos a B, forense/parcial previa preservados; expiraciones intactas. Reader legacy solo repositorio/fail-closed, no HTTP ni cobertura productiva. **E PASS/aceptación02:11:08.854479 UTC**: dos objetos GCS exactos/gen0/readbackSHA/temporaryholdtrue, conservar hasta al menos2026-10-11 mismahora; **F PASS02:12:00.719913 UTC**: solo VM2416531264420713648/disco8831012956187399344 eliminados por identidad/ausencia/evidencia fuera; respaldo/holds preservados. A–F completos, rollout/piloto/Full0; global pendiente. Primer D fallido queda histórico, no borrado ni nuevo corte. Auditoría original exit 1/16 miembros por options omitido conservada histórica, no corrupción probada ni nuevo corte.
**Histórico02:12, no salud actual:** origen sano tras cleanup02:12:30.632597→02:12:34.210086 UTC: API/gateway/worker/bootstrap200ready/healthy/restarts0/OOMfalse; en ese instante fuentes runtime d78, sin nuevos builds. La candidata posterior incluye los fixes arriba; despliegue/piloto pendientes. Piloto autorizado: HOPEMOB82453304, cinco fuentes/90 min/2,500 GET físicos, **Full 0**, sin activación global.
**Calidad histórica previa a los cuatro cambios, supersedida por el cierre vigente:** full Linux 5,946 passed/9 skipped, 425.84 s, exit 0 (00:54:46.140710→01:01:54.421494 UTC); ocho broker integrados, ocho guards Mongo cubiertos por protected Linux 8 passed/2.08 s y un Caddy intencional. Ruff/formato/mypy verdes/653 fuentes, 1,053 hashes/modos intactos/OOM 0; no sumar lotes ni afirmar aceptación productiva. [Intentos históricos y evidencia](zelerdata-historico-rescate-candidatos-propuesta.md#autorización-vigente--ampliación-del-4-de-octubre-de-2026-utc).
Limpieza local histórica01:05:11.228918 UTC: solo seis contenedores/seis volúmenes/perfil propios; perfiles anteriores Stopped/contexto colima preservados. Las restricciones de permisos/mediciones anteriores se conservan históricas; no revocan la ampliación ni acreditan resultados. Selector publicado `dbf84928167c1ea66113d9005440e201eeb1566e`, runtime d78 sin cambio en esa fase anterior.

**Historial de publicación y cortes anteriores — 3 de octubre de 2026 UTC.**
Trabajo propio publicado entonces en `main`;
fuente de esa fase `d78ff4e57915ca5e81a5eb6f1976ec65f111824b`,
verificada contra el remoto. C1/C2 permanecen como historial en el
[recibo de publicación](zelerdata-historico-publicacion-20261002.md). El follow-up
de este recibo/propuesta es documental, no una fuente nueva de imágenes.
**Etapas 8A/8B históricas autorizadas y ejecutadas:** tres builds SUCCESS/procedencia C3
verificada e inspección runtime read-only; [recibo de builds/baseline](zelerdata-historico-builds-runtime-20261003.md).
**Goal vigente recibido el3octubre:** autoriza terminar el alcance de cinco
fuentes, publicar cambios propios, builds solo afectados, despliegue seleccionado,
una nueva ventana C tras ensayo aislado de pausa y pilotoHOPEMOB único limitado.
Autoriza hoja privada para **fórmulas existentes** y modo parcial **solo API normal**;
no adaptar add-on, nuevas fuentes ni Full. Autorización no es ejecución:
**último C documentado abortó; no backup/restore/deploy/piloto nuevos acreditados**.
Fuente d78 publicada/remoto confirmado, tree `54d96092dce1358579989c45d973bd6969f1a4d7`
idéntico al staged validado/worktree limpio al publicar. Exactamente tres builds
nuevos SUCCESS/procedencia verificada y destinos concretos en el
[recibo d78](zelerdata-historico-builds-runtime-20261003.md#publicación-d78-y-tres-builds-verificados).
Sin pull/deploy/piloto. Este cierre documental se publica por separado; su identidad se consulta en Git
y no cambia el código de la fuente d78. Checklist/preparación
§§8–9 en el [informe](zelerdata-historico-al-vincular-implementacion.md#preparación-de-aceptación-del-goal-oauth-api-normal-y-sheets-nativo).
**Estado histórico previo al rescate:** este cierre documental no cambia código de fuente d78.
Selector operativo del host corregido localmente: 38 pruebas enfocadas verdes.
**Control general anterior — histórico, sustituido por la ejecución del aviso vigente:** pytest terminó con exit 1, sin resumen completo, por Mongo local `127.0.0.1:27017` sin listener e interrupción (KeyboardInterrupt y KeyError de pytest_stash en teardown). No se inició Mongo ni se preparó otro entorno. Ruff y formato exit 0; mypy exit 0, 653 fuentes. Las 38 pruebas enfocadas y el smoke sintético de 41 miembros son válidos; no acreditan restore real. Los 12 fallos Bash/BSD anteriores son evidencia histórica, no un resultado repetido en esta ejecución.
Este cierre documental se publica por separado; su identidad se consulta en Git y no cambia el código de los servicios de la fuente d78.
[Rescate propuesto y única solicitud de auditoría](zelerdata-historico-rescate-candidatos-propuesta.md):
no ejecución de rescate ni nuevas imágenes runtime.
Runtime final asentado22:11:24–28 UTC conserva imágenes anteriores sanas/restart0/
OOMfalse, baseline13/6 y siete hashes idénticos/sin Full; sin hold desplegado ni
piloto activo. Eventos/claims0 ready/0 unacked/consumer1, DLQevents315 sin cambio/
claimsDLQ0; capacidad/dry-run0 en recibo, lectura final prefixGCS sin objetos.
**Nueva C autorizada falló** por `unexpected_dump_member` de
Tools 100.16.0, no por pausa/causa externa: único corte22:06:27.367903 UTC,
tres reanudados22:08:03–04/cuatro ready20022:08:30–34/baseline13/7 hashes exactos.
Sin archive/manifest válidos/GCS/restore/retry/otra ventana. Cleanup solo nuevo
target confirmado22:10:48.924702: VM6465909143569745603/disco 6372025565115631299
ausentes tras verificar IDs/attachment/autodelete; evidencia fuera, sin GCS creado/borrado; [detalle](zelerdata-historico-builds-runtime-20261003.md#nueva-c-autorizada-aborto-por-selector-origen-recuperado).

**Actualización local del goal:** controles de admisión/ejecución congelados; destino
futuro **14 scopes = baseline13 + mensajes, sin Full**, seis routing keys. C3/15 y
sus tres builds se conservan como historial, no son destino de este nuevo rollout.
SHA d78 publicado/tres builds verificados, contrato14 sin Full no desplegado. Ensayo real run5 **completo pasado**:
normal/deadline/guard, leases/job fence y Rabbit en Docker29.4.1. Único C del goal
iniciado21:09:57.466075 UTC **falló antes de dump/writers_stopped**: parser Python del host 3.10
rechazó RFC3339Nano (`command_failed`), aunque API cerró ordenadamente con sentinels
reales. Recuperados API/dispatcher; gateway/worker intactos; las cuatro readiness
HTTP 20021:10:53–58 UTC/baseline13/siete clientes exactos. **No segundo C permitido**.
Sin respaldo/restore consistente, deploy/piloto bloqueados. Fix parser local37+6
verde/prefijo30ecbeb verificado read-only Python del host 3.10 con timestamps auténticos
alrededor de 21:12. **Checks históricos de d78, no repetidos en esta fase:** último patch runtime/pacing validado: 74 passed/27.76 s incluye
12 cert×1000/dos workers/cuatro renovaciones/spacing estricto; estáticos651 finales
verdes. Capacidad anual3 passed/52.16 s tras último patch. Rootgate general **no verde**:
fragmento2860:13fail/2838pass/9 skip259.20 s; regresión propia verificador15→14
corregida/35purepassed0.24 s, otros12 verificados preexistentes en HEAD13972ec
(Bash3.2.57/BSDstat, sin pruebaLinux/Bash5). Ocho rs0 protegidos **8 passed2.20 s**
con MONGOunset/destino propio27030 verificado; guardMongo ya no skipped.
Persisten8 skipsbroker/1Caddy y12baselineMac; no control general del repositorio general verde.
No sumar lotes ni repetir prefijo válido. Publicación propia continúa
independiente de este bloqueo. [Detalle](zelerdata-historico-builds-runtime-20261003.md#único-c-del-goal-fallido-antes-del-dump).
Pacing corregido localmente: reserva/cobro durable/validación persistida antes
de pacing único; después guard UTC síncrono y RPC sin awaitMongo intermedio.
Guard persistido gateway tardío tras broker/KMS permanece. Vencimiento durante
espera conserva consumed1/HTTP 0, sin refund/reset; no confundir HTTP 0 con cobro0.
Ya se creó la hoja privada nativa bajo Cuenta Zeler, owner-only y
ocho pestañas/0 fórmulas; permanece inactiva, no prueba aceptación Sheets.
**Histórico, previo a nueva C:** abandono/limpieza autorizados ejecutados: VM190812944583158189 y
disco 9220450358313937325 eliminados, búsquedas por identidad vacías; evidencia
copiada fuera antes. PrefixGCS exacto sin objetos, respaldos previos/retención
intactos, sin deleteGCS. Guard completed/recoveryTRUE; origen disponible, baseline13
y siete clientes exactos. No nuevo C ni despliegue/piloto.

El descubrimiento Full sí se autorizó de forma separada y cerró con **7/10 GET
acumulados, sin referencia auténtica de retiro y parada por 429**. El usuario
cerró esa investigación: tres sin usar no autorizan continuar y no se propone
ni programa otra consulta. La reparación estrecha posterior **se completó**:
2026-10-03 19:12:42.007120 →19:12:49.687008 UTC, única diferencia search verificada
contra todo el manifest/registro, preimagen privada VM0600/hash y CAS de un único
scope. matched1/modified1: **14→13 scopes/6 keys**, cada otro campo y seis clientes
intactos. **Sin restart ni cambio de imágenes**; contrato local15 aún no desplegado.

**19:13:22→27 UTC: Sheets API200 ready:true/healthy**, Mongo/Rabbit/
registry_fingerprint_match OK y DLQready0/unacked0; gateway ready200 y worker200
ready:true/componentes OK. Los tres restart0/OOMfalse, digests/starttimes sin
cambio. Baseline13 compatible **confirmado**: C lo preservará y jamás restaurará14;
preimagen 14 forense, no backup baseline. No business/tokens/otros permisos escritos.

Bloqueo GCP17:03:40 (hora registrada después del fallo) y checkpoint público
17:04:59.014110 Sheets503/gateway200 quedan **históricos/superados**, no estado
actual. Evidencia exacta/preimagen/hashes en el
[recibo](zelerdata-historico-builds-runtime-20261003.md). Recuperar salud no es
validar piloto o Sheets nativo; no nuevos builds/recursos, backup/restore, deploy,
piloto ni consultas Full autorizados o ejecutados por esta reparación.
Ingress público Sheets `/health`200 ready:true, dependencias OK, confirmado a
19:14:19.109613 UTC (~90 s tras CAS); confianza SSH/cuatro hashes fuente intactos,
sin repetir suites. No prueba OAuth Sheets, fórmulas nativas ni aceptación piloto.

**C previo19:56: capacidadCOS aislada y tar.gz selectivo/whitelist-manifest autorizados.**
Mongo 7 oficial listo loopback 27018/rs0PRIMARY; Docker/datos/backup/tmp en ext4RW
persistente, tmp01777 corregido, sin cuenta de servicio/externalIP/tráfico saliente abierto. Destino antes de
corte25,588,756,480 bytes libres; tras aborto25,588,703,232, por encima del
requerido8,793,228,538(piso 5 GiB+working3,424,519,418). Ya no bloquea capacidad.

**Corte 19:56:36.104233 UTC abortado por error de nuestro procedimiento de pausa,
no bloqueo externo:** dispatcher TERM/manual stop; TERM al child
uvicornAPI causó auto-restart Docker19:56:38.581673 (`sh -c`/no exec,
`unless-stopped`), grace60 s agotado. `cut_failed/grace_exhausted`,
**valid_for_upload:false**. Dispatcher reanudado mismo contenedor19:57:38.268277
(~62.164 s); worker/gateway nunca pausados. API restart1, demás0, OOMfalse/imágenes
intactas. HTTP 200/componentes/consumidores a19:57:56→58 y19:59:42→44. Baseline13/6
y siete clientes exactos; no scopes/config/policy/hardkill/purge. Cuatro jobsCloudRun
us-central1 completos; SchedulerAPI deshabilitada, **no lista0** ni habilitación.

**No dump/archive/manifiesto/respaldo en GCS/restore**; prefixGCS exacto sin objetos,
backups previos/retención intactos/noholds. Watchdog completed:true, no nuevo corte
automático. El tar.gz292,965,492 bytes del directorio targetbackup es **imagen oficialMongo,
no respaldo**; evidencia privada/cache y antes/después capacidad/RAM en el recibo.
En ese C previo no hubo restoreDB ni eliminación. El goal posterior autorizó
abandono definitivo y **ya eliminó únicamente VM/disco temporales** con evidencia
fuera; no restauró ni borró Mongo/GCS productivo.
Antecedente del plan de pausa, supersedido por helper/ensayo local del goal:
manual Docker stopTERM/timeout=-1 exactID bajo supervisión
pendiente y childTERM verificado, sin hardkill/cambio restartpolicy; requiere
validación operacional y decisión de nueva ventana limitada, **no ejecutarlo ahora**.
[Detalle C](zelerdata-historico-builds-runtime-20261003.md#4-c-autorizado-corte-abortado-por-parada-manual-no-lograda-sin-respaldo).

## 1. Qué se puede autorizar por separado

| Etapa | Alcance propuesto | No queda incluido |
| --- | --- | --- |
| Publicación — ejecutada/verificada | Trabajo propio de histórico al vincular y cierres locales, con tests/reportes y propuestas; Conventional Commits, sin atribución IA. | Builds, deploys, pruebas reales, archivos ajenos. |
| Full — cerrado/pendiente | [Evidencia histórica](zelerdata-full-validacion-acotada.md): 7/10 GET, sin referencia, detenido por 429; RETIROS sigue no disponible sin mapeo. | Consultas restantes, retries, nueva búsqueda/programación, mapeo supuesto. |
| Inspección8B histórica; nueva C autorizada fallida | Ensayo real pasó, pausa/quiescencia/snapshots verificados; selector rechazó prelude Tools 100.16.0. Recuperación/salud22:11 y cleanup confirmados, sin archive/manifest válidos/GCS/restore; offline/rescate primero, otra ventana solo si evidencia insuficiente y permiso nuevo. | Repetir C automáticamente, extras arbitrarios, reparación ajena por drift, restore productivo. |
| Builds — ejecutados/verificados | Tres imágenes nuevas d78 SUCCESS/procedencia/digests verificados; loteC3 histórico separado. | Deploys, checkout local subido, otros servicios. |
| Despliegue — autorizado por goal, pendiente | Gateway, Sheets API/worker; solo tras respaldo y controles de admisión/autoridad/recuperación probados. | Restart amplio, otras APIs/workers, bootstrap no afectado. |
| Piloto — autorizado por goal, pendiente | HOPEMOB82453304; única ventana90 min/2,500GET, cinco fuentes/Full0; OAuth normal sin force. | Otros vendedores, reinicios anuales, ampliación automática. |
| Sheets nativo — hoja preparada, aceptación pendiente | Cuenta Zeler confirmada; hoja nueva privada owner-only/0 fórmulas. Activación de fórmulas existentes solo durante piloto. | Publicar/adaptar add-on, modificar hojas del usuario sin alcance. |

La autorización de publicación ya recibida no aprueba ninguna de las demás etapas. Si una etapa exige cambiar
su alcance, se presenta la diferencia y se espera autorización; no repetir ni
ampliar pruebas reales automáticamente.

## 2. Publicación verificada: fuente actual y conservación

**Publicación histórica d78:** `d78ff4e57915ca5e81a5eb6f1976ec65f111824b`, tree
`54d96092dce1358579989c45d973bd6969f1a4d7` idéntico al staged validado/remoto
confirmado/worktree limpio al publicar. Tres builds actuales en el recibo d78;
los antecedentes C1/C2/C3 siguientes conservan su propia evidencia histórica.

Checkout seleccionado en `main`. Base observada al preparar: commit externo
`124fd236fea600ead8c1436560a22b1909d7c3c8`, diagnóstico OAuth ajeno conservado.
**No es el commit fuente de esta entrega**. Usar el SHA completo de la entrega
publicada y verificada que registra el recibo de publicación, nunca esta base.
C3 `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` añadió únicamente corrección Full,
sus tres tests y dos reportes; los cuatro archivos ejecutables coinciden con
la validación ya realizada (5,820+8 y 28 focused). No se repitió la suite para
esta publicación; se comprobó equivalencia staged/commit/remoto y conservación.

Contenido propio publicado, conservando pruebas junto a su comportamiento:

1. **Histórico acotado y continuidad:** intención core/OAuth, coordinador, fuentes,
   parciales persistidos, convivencia con recovery, pacing, mantenimiento, packs
   antiguos y scope opcional del piloto; índices, registro y verificador de
   rollback; tests de esos comportamientos y documentación correspondiente.
2. **Consumo explícito de parciales:** API/handler existente, prueba autenticada
   9,999+1 y avisos/cobertura; sin cambiar totales, fórmula ni frontend.
3. **Evidencia y operación:** capacidad compartida y protección Full, informe,
   propuesta/probe; mantener tests junto al comportamiento cuando haya hunks
   dependientes. La partición real no debe dejar imports/tests rotos.

Para el envío autorizado, registrar inventario de archivos/hunks propios y
resultado de los checks ya completados; no abrir otra ronda general de perfección. Preservar todo lo ajeno; no usar stash/reset ni crear
rama/worktree. Stage explícito solo de esas unidades autorizadas,
verificar diff staged, publicar sin force y comprobar SHA remoto = HEAD local y
estado de checkout restante. Ningún dump, audio, token, credencial ni DB entra.
Review opt-in permanece `disabled/unmanaged`; no se fabrica un recibo.

## 3. Destino, imágenes y compatibilidad

Destino confirmado en la inspección histórica A/B: proyecto `zeler-platform-dev`,
VM `platform-vm`, zona `us-central1-a`, Docker Compose. Baseline inspeccionado
en A/B; el intento posterior de recuperación no alcanzó VM.

| Propietario | Cambio | Imagen que debe compararse/construirse si se autoriza |
| --- | --- | --- |
| Gateway | Admisión durable al OAuth/relink. | `gateway` |
| Sheets API | Progreso, tabla parcial opt-in y manifest. | `sheets-api` |
| Sheets worker | Autoridad, fuentes, recuperación periódica, renovación y scope de piloto. | `sheets-worker` |
| Operaciones | Verificador `infra/deploy/sheets_rollback.py`; índices/seed. | Herramientas/contratos por rollout separado, no otra imagen por costumbre. |

Drift de fuente/digests quedó verificado en A/B: las tres imágenes C3 construidas
no están desplegadas. Salud posterior a la reparación confirmada: API/gateway/
worker200; no hubo restart ni cambio de imágenes.
Builds desde repositorio conectado, SHA completo presente en `main`, una imagen
por build, `options.requestedVerifyOption: VERIFIED`; registrar build ID, fuente,
SUCCESS y `repo@sha256:...`. **No builds Docker locales.**

El contrato **histórico C3** exigía **15 scopes / 6 routing keys**;
fingerprint completo:
`bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
El nuevo goal exige **14 scopes = 13 + `GET /messages/packs/*`**, seis keys y
ningún scope Full, fingerprint
`453bf9eb6014d8055fe6cd372e98b1e2d0190a0241b519417fe5f5397e2c1525`.
Verificador canónico corregido14/6 no acredita compatibilidadC1 ni habilita rollback
clásico. Verificar fingerprint/manifest/seed de la nueva fuente exacta,
no usar este fingerprint histórico15 ni desplegar sus builds por costumbre.
No añadir permisos de envío/marcado como leído ni scope de detalle Full por
escribir una propuesta: el probe detiene una denegación.

## 4. Baseline, capacidad y respaldo antes del piloto

Inspección de lectura desde VM/VPC aprobados: raíz y Mongo (bytes e inodos), mount
Mongo, RAM disponible, uso Docker, salud, restart count y OOM; readiness gateway,
componentes/consumidores Sheets y backlog. Output seleccionado/sanitizado, nunca
`env`, cadena Mongo, headers o cuerpos de mensajes. `--dry-run` del preflight no
atestigua procedencia ni rollback. Medir ≥5 GiB libres en `/` antes de **cada**
pull, incluso rollback, y revalidar después. Mongo/RAM se miden aparte; no inventar
un umbral ni resize/prune. Limpieza requiere alcance explícito y no incluye volúmenes.

Baseline de la cuenta: identidad linked legítima/estado, plan y corte, presupuesto
consumido por fuente, intervalos exactos, certificados/hash/versiones, conteos y
pendientes. Conservar junio sano y otros intervalos independientes. Detectar
trabajo legacy activo/conflictivo: esperar/delimitarlo, no borrarlo ni coalescerlo
sin autorización. El presupuesto del plan no cuenta llamadas de otro worker.

### Respaldo propuesto y criterio obligatorio

- Autorizar una ventana de quiescencia de los **writers Sheets afectados** desde
  VM, con ACK/NACK y stop grace respetados; Rabbit conserva entregas, no purge.
  Confirmar que no haya otro escritor de las mismas colecciones antes de tomar
  respaldo lógico consistente. Si no puede garantizarse, detener esta etapa y
  proponer snapshot consistente aprobado; no asumir que un dump concurrente lo es.
- Alcance: hechos canónicos afectados (`orders`, `questions`, `shipments`, `claims`,
  devoluciones, `messages`), modelos/proyecciones consumidos, planes/pending,
  adquisiciones/receipts/ranges, recovery jobs/admission, runs/operaciones,
  certificados/cobertura/freshness e índices/validadores de ese conjunto. Generar
  inventario exacto del checkout y runtime antes del dump; incluir relaciones de
  prueba, no solo filas visibles. Capturar config Compose/registro por separado.
- OAuth, claves e identidades no se usan como material de restore del piloto.
  No imprimir/exportar tokens. Si un snapshot contiene secretos ajenos al alcance,
  protegerlos y restaurar únicamente namespaces aprobados, nunca cuentas/tokens.
- Crear desde contexto aprobado archivo protegido (`0600`) y destino privado
  cifrado **seleccionado/propuesto** en `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/`
  (`history.archive.gz` y `manifest.json`), con acceso mínimo existente, hash y
  manifiesto sin datos personales; no escritos. Propuesta de retención: siete días tras aceptación/rollback, luego
  borrado expresamente autorizado; no inventar un bucket ni configurar uno ahora.
- Destino histórico **creado bajo C y eliminado al abandonar el goal**, sin restore: VM
  `zelerdata-restore-aeefe993`, proyecto `zeler-platform-dev`/zona `us-central1-a`,
  e2-standard-2/8 GiB, disco 30 GiB, sin IP externa; Mongo rs0 loopback 27018/base
  `zelerdata_restore_aeefe993_20261003`, sin app/product worker conectado.
  Creación/costos originales cubiertos por C; restore no ejecutado; capacidad
  raízCOS fue superada por excepción target-only autorizada/Mongo validado;
  el único C posterior falló por parserNano antes del dump y se abandonó.
  No repetir C ni recrear destino automáticamente. Una nueva decisión de alcance
  deberá resolver respaldo consistente y destino, no usar la VM eliminada.
  Criterios conservados: conteos, hashes canónicos, índices/validadores, joins,
  certificados/lectores, y preservación en origen de un hecho posterior al corte.
  Un restore no se hace encima de producción para obtener esta evidencia.
- Reanudar solo writers autorizados, comprobar backlog y salud/capacidad después.
  Registrar corte/consistencia y resultado. Si restaura mal o no hay recuperación
  segura demostrada, **no iniciar el piloto**.

El ensayo sintético local anterior no sustituye este backup ni su validación.

## 5. Despliegue y rollback seleccionados

Guardar identidad inmutable **de contenedores ejecutados**, no solo tags de Compose,
y configuración previa. Conservar rollback recuperable que acepte scopes nuevos,
jobs `policy_authority`, datos/proofs y topología. Un worker antiguo que ignore
esa autoridad puede ejecutar jobs por otro camino: **no es rollback compatible**.

Orden propuesto, sujeto a verificación de compatibilidad exacta:

1. Registrar/atestiguar recuperación compatible con el contrato objetivo14/sin Full
   y frontera de autoridad. Antes de estado nuevo, fallback antiguo solo con ausencia
   o aislamiento demostrado; después, hold de admisión/ejecución pausada y forward
   recovery conservando jobs/datos/consumed/cutoff/checkpoints, no worker legacy.
2. Aplicar solo índices/registro aprobados desde VM y comprobar dependencias,
   sin aplicar validadores como supuesto health check. Nuevas colecciones internas
   no tienen validador core nuevo; verificar los canónicos reutilizados.
3. Desplegar API/worker compatibles con flag onboarding apagado. Worker entiende
   la autoridad antes de que se admita más trabajo; API registra permisos nuevos.
4. Desplegar gateway cuando el camino `accounts.linked` esté listo; comprobar
   `/ready`, dependencias y publicación, no únicamente `/health`.
5. Verificar digests, readiness de consumidores, operación/progreso y asentamiento;
   repetir salud y capacidad. No usar broad Compose restart.
6. Configurar solo piloto/plan autorizado y habilitar flag en worker como abajo.

Retirada: cerrar admisión histórica y pausar ejecución persistida del claim autorizado,
sin resetear su presupuesto ni estado. Desactivar onboarding mediante cambio/restart acotado autorizado y
esperar/graceful-stop de la unidad en ejecución; no borrar jobs/planes ni sus
hechos. Después, restaurar únicamente imágenes compatibles y config aprobada.
Si queda un job con lease, esperar vencimiento/protocolo, no forzar takeover.
La tabla partial API puede retirarse junto con opt-in/handler sin borrar filas.
No bajar scopes ni restaurar toda Mongo para que un rollback parezca verde.
Cualquier reparación de datos debe ser por alcance, comparar revisiones y preservar
OAuth/identidades/hechos posteriores; autorización separada, fail-closed mientras.

## 6. Piloto inicial: una cuenta, límites explícitos

Operación persistida canónica: [runbook prepare/pause/activate](zelerdata-historico-control-piloto.md),
dry-run predeterminado, recibo aplicado fijado por SHA y CAS del documento completo.
No reemplaza los gates de rollout ni acredita piloto activo; el plan legacy exige
OAuth auténtico antes de poder prepararse, sin admisión manual ni reset.

**Candidato:** vendedor `82453304`, solo si legítimamente linked y operador acepta
la cuenta. Relink normal, sin force, tokens copiados, limpieza para simular vacío
ni reemplazo de cutoff/checkpoints. No asumir Full aplicable.

Configuración del worker dentro del despliegue autorizado:

```text
ZELERDATA_HISTORY_ON_LINK_ENABLED=true
ZELERDATA_HISTORY_ON_LINK_SELLERS=82453304
```

La lista opcional cerca el claim real **antes de renovar/adquirir**; ausente activa
el comportamiento normal multicuenta. Vacía/wildcard/IDs no canónicos fallan startup.
Para este piloto no dejarla ausente. Mantener pacing compartido existente (default
180/min, verificar valor efectivo), no elevarlo ni atribuirle justicia universal.

Antes de habilitar, obtener plan por OAuth auténtico con flag apagado y, bajo
**autorización explícita desde VM**, restringir autoridad persistida a cinco fuentes
(Full excluido; investigación cerrada) y bajar límites remanentes. No reiniciar consumed,
corte, jobs, snapshots ni otras cuentas. Si el plan ya agotó una cuota, no elevarla
como "reset": declarar pendiente y pedir otro alcance.

**Interlock legacy antes del piloto:** baseline real de la API y worker corroboró
`ZELERDATA_FORMULA_RECOVERY_ENABLED=true` con cohorte única HOPEMOB82453304
(cohorte82); worker también `ZELERDATA_REFRESH_ENABLED=true`/misma cohorte,
API refresh no configurado. Cambiar únicamente recovery a **false API+worker**
y refresh a **false worker**, conservando allowlists y todos los demás campos,
configuración y cuentas. Son flags globales; si cambia la cohorte original, STOP:
no suprimir actividad ajena ni inventar un control per-seller. Junto con histórico
seller-only y límites persistidos, esto impide que lanes legacy agreguen tráfico
no acotado al ensayo. Flags OFF no prueban quiescence: drenar/verificar trabajos
en curso, sin borrar jobs ni tomar leases. No está aplicado por esta documentación.

| Fuente | GET iniciales adicionales máximos |
| --- | ---: |
| Órdenes/comisiones | 800 |
| Preguntas/respuestas | 150 |
| Envíos/costos dependientes | 250 |
| Mensajes | 300 |
| Reclamos/devoluciones | 500 |
| Full | **0**; investigación cerrada, sin consultas/retries/programación. |
| **Total inicial** | **2,000** |

Mantenimiento: máximo **500 GET adicionales** durante el ensayo, ≤300 por fuente;
autoridad diaria separada, límite remanente sin subir cuotas originales. Ejecutar
**90 minutos máximo dentro de un mismo día UTC**, y detener a 2,500 GET físicos
adicionales del coordinador piloto. Medir tráfico habitual ajeno por separado;
no imponerle este presupuesto ni detener otros productos. Si los smokes admiten
recovery legacy adicional, delimitar/autorizar su presupuesto antes de ejecutarlos,
no ocultarlo en estos counters. Si no es posible medir/limitar todos los intentos
atribuibles al ensayo, no activar. Concurrencia de claim: una
unidad de cuenta/lease; fuente rota, cada collector mantiene sus límites. No
prometer acabar el año con este presupuesto; el corte sigue 12 meses calendario,
la prueba acredita solo intervalos/conjuntos efectivamente completados.

Stop: auth no válida/denegación relevante, revocación/pausa, presupuesto o tiempo,
429 persistente, error canónico/certificado, modificación ajena de lease/scope,
regresión de cobertura sana, restart/OOM, readiness caída, disco bajo piso o
backlog/latencia viva deteriorados frente al baseline. No ampliar ventana, fuentes,
cuotas ni efectuar repairs automáticamente; preservar pendientes y evidencia.
Pausar el coordinador no autoriza parar otros productos/workers.

## 7. Aceptación y límites de evidencia

- Plan/progreso persisten, dos visitas no reabren año, llamadas físicas ≤ cuotas,
  canonical publication útil independiente y datos previos/otros sellers intactos.
- Sample del lector/handler/API normal, no solo repositorio privado. ORDENES con
  `allow_partial:true` devuelve adquiridos + aviso, nunca un total exacto. Default
  y agregados afectados continúan no disponibles; intervalo sano sigue disponible.
- Mensaje nuevo en pack antiguo conocido: verificar orden sin cambios, fuente,
  fecha/ID consistente y publicación al completar visita natural del cursor.
  Rotación requiere páginas porque la API no acredita orden incremental: no hay
  garantía de latencia. Si cuota/tiempo impide llegar al pack, declarar pendiente;
  no mover cursor para fabricar aceptación.
- Certificados poblados siguen válidos con renovaciones y hash consistente; renovar
  localmente no acredita cambios de fuente.
- Dos incrementales con **cambios reales** posteriores al corte (órdenes,
  respuestas/mensajes/devoluciones aplicables), detección→persistencia→lector.
  Dos ciclos vacíos no satisfacen el criterio; no fabricar compras/mensajes.
- Sheets: hoja temporal privada y rango autorizado, muestra acotada de fórmulas
  existentes en período sano y afectado. Firma del add-on no expone `allow_partial`:
  comprobar API opt-in aparte, **no afirmar consumo parcial nativo**. Publicación
  del add-on o nuevo acceso nativo requiere otro desarrollo/alcance autorizado.
  La [adaptación mínima propuesta](zelerdata-ordenes-parciales-complemento-propuesta.md)
  conserva la firma existente y default exacto con un opt-in final; **no está
  implementada ni disponible en Sheets**.
- Evidencia sanitizada: conteos/rangos/hash/tipos/status/budget/digest; no compradores,
  texto de mensajes, cuerpos, credenciales o cadenas de conexión.

Resultado final clasificado por fuente: completado local, bloqueo externo preciso,
validación productiva aprobada/no comprobada. No convertir 90 minutos, HTTP 200,
container running, una muestra correcta o tests verdes en cobertura anual.

## 8. Autorizaciones concretas listas para completar

**Textos históricos de permisos; no estado vigente.** Son permisos **independientes**. A/B se aprobaron y ejecutaron, con evidencia
en el [recibo](zelerdata-historico-builds-runtime-20261003.md); sus textos se
conservan como alcance histórico, no permiso de nuevos builds/inspecciones.
C fue autorizado, target/Mongo listos y un corte abortado sin dump/restore. El goal
posterior autoriza D/E condicionados a gates, **no ejecutados**. Los textos siguientes
conservan etapas previas; objetivo nuevo14/sin Full y fuente d78 ya publicada/builds
verificados, sin deploy. Fuente entonces: `d78ff4e57915ca5e81a5eb6f1976ec65f111824b`;
C3 `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` permanece histórica.
El recibo conserva C1/C2 y sus 36 hashes originales como históricos, y registra
la delta C3 de cuatro archivos validados; 32 permanecen iguales. Comprobar que
C3 continúa presente en `origin/main`; el follow-up del recibo es solo documental. No usar `main`
movible, base anterior ni checkout local como sustituto. Rechazar una expansión
no aprobada; los digests y el baseline se incorporan antes de pedir despliegue.

### A. Tres builds; no operación runtime

**Actual ejecutado/verificado:** exactamente tres builds d78 y refs/digests nuevos
en el [recibo d78](zelerdata-historico-builds-runtime-20261003.md#publicación-d78-y-tres-builds-verificados).
Destinos14/sin Full propuestos, **no pull/deploy/piloto**. No usar el texto C3
histórico siguiente para construir/desplegar otra fuente ni como rollback.

**Ejecutado/verificado histórico:** build IDs y tres digests inmutables de C3 en el
[recibo](zelerdata-historico-builds-runtime-20261003.md#1-tres-imágenes-success-con-procedencia-verificada).
No se descargaron ni desplegaron en VM; no construir otra imagen con este alcance.

**Texto autorizado histórico:**

> Autorizo exactamente tres Cloud Builds en `zeler-platform-dev`, región
> `us-central1`, desde el repositorio conectado
> `projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform`,
> al commit `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` presente en `main`. Una imagen por build:
> `gateway` (`gateway/Dockerfile`), `sheets-api`
> (`modules/sheets/Dockerfile.api`) y `sheets-worker`
> (`modules/sheets/Dockerfile.worker`), en el Artifact Registry existente
> `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform`.
> Exijo `options.requestedVerifyOption: VERIFIED`, SUCCESS, procedencia del
> repositorio/SHA exactos, build ID y digest inmutable de cada imagen. No autorizo
> imágenes adicionales, build local, despliegue, pull en VM, limpieza ni consultas
> reales a Mercado Libre. Si falla un build, reportar; no ampliar ni repetir una
> ejecución incierta automáticamente.

### B. Inspección read-only y drift; no backup ni repair

**Ejecutado histórico A/B:** baseline/digests/capacidad y bucket existente documentados en el
[recibo](zelerdata-historico-builds-runtime-20261003.md). API 503/fingerprintmismatch
ya presente; no se reparó ni reinició. El dry-run no descargó imágenes.
Gateway/ready 200 y worker/health 200 con componentes OK; no onboarding en
worker. API503 quedó sin reparar **en B**; la autorización posterior acotada
recuperó13/6 y salud200 sin restart, documentada al inicio/recibo.

**Texto autorizado histórico:**

> Autorizo una inspección de lectura de `platform-vm`, zona `us-central1-a`,
> proyecto `zeler-platform-dev`, desde el contexto VM/VPC permitido: capacidad,
> mount Mongo, memoria, Docker, salud/readiness/backlog y las identidades inmutables
> de gateway/Sheets API/worker en ejecución. Comparar fuente desplegada con
> `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` cuando haya procedencia verificable. Usar preflight
> `--dry-run` y salida sanitaria seleccionada. No autorizo downloads, atestiguación
> que descargue imágenes, backup, validator/index/registro, cleanup, restart,
> reparación ni consulta de Mongo productivo desde el asistente local.

La inspección identifica digests/fuentes anteriores/headroom. No existe
rollback de versión compatible atestiguado: API/worker anteriores carecen de
`policy_authority`; destino/Mongo listos bajo C, parada segura/corte pendiente.
Recuperación 13/salud confirmada; falta cerrar writers para C y alternativa de
recuperación segura para D/E. El baseline histórico14/503 no se acepta como
rollback de 15; registrar un digest no prueba compatibilidad.

### C. Respaldo consistente y restore aislado; no restauración productiva

**C autorizado: ventana única abortada; backup/restore no ejecutados.**
22 colecciones seleccionadas y writers/ausencias observados en el
[recibo](zelerdata-historico-builds-runtime-20261003.md#inventario-mínimo-exacto-22-namespaces),
no toda DB. Origen VM: `zeler_platform_prod`; 20 presentes/2 ausentes. No incluye
OAuth, `meli_accounts`, tokens, identidades ni secretos. Bucket privado verificado
`gs://zeler-platform-backups`, IAM sin públicos/cifrado Google-managed.
Objeto y manifest exactos, no creados; destino restore **VM creada bajo C**,
no cubierta por A/B. Gates/avance/bloqueo en el recibo.
**Alcance C de la propuesta previa (no transcripción literal del usuario):**

> Autorizo C exclusivamente para las 22 colecciones del inventario del recibo,
> desde contexto VM/VPC de `platform-vm`, corte/ventana de 15 minutos. Delimitar
> `sheets-worker`, `sheets-api` y `bootstrap-dispatcher`, impedir nuevos launches
> y comprobar que todos los jobs bootstrap ya iniciados terminaron. Mantener
> solamente admisión histórico linked/relinked del gateway detenida por control
> scoped verificado, sin tocar/restaurar OAuth ni parar todo el gateway. Atender
> stop grace explícito de 60 s para los tres servicios seleccionados y timeout
> externo ≥120 s; no asumir default 10 s seguro. Conservar ACK/NACK, leases, jobs y
> entregas Rabbit; no purge/hardkill/stop amplio. Si no se prueban fuentes/actores,
> hold scoped o quiescencia dentro de ventana, no iniciar dump ni autoampliar.
> Archivo de tránsito 0600 hacia
> `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/history.archive.gz`
> y manifiesto sanitizado/hash/inventario en
> `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/manifest.json`,
> usando acceso mínimo existente, sin cambiar IAM ni ejecutar cron/prune.
> Antes del dump, validar que herramientas y archivo seleccionan exclusivamente
> esas 22 colecciones; no exportar toda la base ni secretos como paso intermedio.

Formato selectivo/whitelist-manifest **autorizados, aún sin backup**:22namespaces,
20 BSON+metadata, dos ausencias, JSONcorte sanitizado/manifiestoSHApositivo; tar.gz
`history.archive.gz`, no Mongo native archive. Corte fallido `valid_for_upload:false`
no se sube; validar contents/restore con lector correspondiente, no cron full dump/prune.

> Continuación del alcance de la propuesta previa (no transcripción literal):
> Autorizo crear el destino aislado `zelerdata-restore-aeefe993`, proyecto
> `zeler-platform-dev`, zona `us-central1-a`, `e2-standard-2`/8 GiB RAM,
> disco 30 GiB, sin IP externa y acceso restringido. Los costos de esos recursos
> desde creación hasta eliminación aprobada forman parte de C, no A/B.
> Verificar aislamiento y pull/transfer de Mongo 7 por digest
> `mongo@sha256:43fddee7e532a920f3dfdee9e8f4834398c155c26bcb92d790cc1cd3c630fc40`,
> con capacidad previa, rs0 en loopback 27018 y base
> `zelerdata_restore_aeefe993_20261003`; sin apps/product workers/OAuth conectados.
> Restaurar únicamente ahí las colecciones aprobadas; comprobar conteos/hash,
> índices/validadores/joins/certificados/lectores, ausencia registrada y hechos
> posteriores intactos en origen. Retener objeto/manifest 7 días tras aceptación
> o rollback; eliminación de objeto/VM/disco necesita permiso separado.
> Con recuperación y salud13 ya confirmadas, capturar de nuevo el
> baseline privado exacto de `module_registry._id="sheets"`, 13 scopes/6 keys,
> antes del stop; conservarlo y comparar todos los campos/clientes tras reanudar.
> Startup de API anterior registra13: no restituir14 ni ampliar a15 con C.
> No autorizar por esta propuesta restauración automática del registro; cualquier
> otra escritura necesaria o hold no verificado exige delimitar/aprobar el delta.
> Reanudar solo writers autorizados y comprobar salud/backlog/capacidad contra
> el baseline compatible13 verificado; nunca usar preimagen forense14 para
> restituir registro. Sin gates propios de consistencia/aislamiento, no iniciar C. No autorizo restore sobre producción, OAuth/tokens en destino,
> modificación de scopes, índices productivos, limpieza, rollout, piloto ni Full.

Gates antes de ejecutar: atestiguar fuentes de todos los writers/bootstrap/jobs
activos, destino/red/IAM aislados y herramientas/Mongo/capacidad. Gateway actual
b835791 (73 archivos/core verificados) no escribe22 ni admite nuevo histórico:
con dispatcher detenido no hay admisión histórica que pausar; no crear control
ni config nuevo para C. Hold del gateway C3 pertenece a D/E. Jobs Cloud Run
bootstrap escriben orders/claims y derivados DEVOLUCIONES operations/freshness/
invalidation de certificados; supervisor/pollers del worker se pausan completos. Fuentes/jobs observados verificadas en
preparación; no equivalen a cutoff futuro. ExcepciónCOS/tar.gz ya autorizados;
Mongo/capacidad **estuvieron listos en esa fase histórica**; targetVM/disco ya
eliminados, no son un destino actual. El corte abortó por grace/parada de API, sin dump/restore;
repoll y stream de cero writers/pausas graceful siguen gates de otra ventana.
No sustituirlos con un dump concurrente. Capturar Compose/config seleccionado
por separado privado/cifrado (imágenes/deps/flags/scopes), **no exportar env ni
secretos**. Si otra necesidad amplía colecciones/writers/recursos, pedir ese delta.

#### Nueva C autorizada y ejecutada; falló sin respaldo

Causa propia parserNano corregida en helper SHA prefijo30ecbeb y comprobada con
timestamps auténticos en Python del host 3.10. Se autorizó preparar/recrear **únicamente**
`zelerdata-restore-aeefe993`, `zeler-platform-dev/us-central1-a`, e2-standard-2/8 GiB,
disco 30 GiB pd-balanced, sin cuenta de servicio ni IP externa; persistencia/aislamiento y excepciónCOS
solo para ese destino, no producción. Verificar helper exacto nuevo/ensayo sin
proveedores y Mongo 7 por digest ya identificado; no ampliar recursos.

Se autorizó **un único corte ≤15 min**, selección positiva22 colecciones y solamente
los dos objetos GCS de §8C (`history.archive.gz`/`manifest.json`), producidos/subidos
solo con consistencia comprobada. Reanudar writers/verificar origen **antes** del
restore aislado; validar restore/lectores y limpiar solo VM/disco, preservando GCS.
El corte22:06 falló al rechazar `dump/zeler_platform_prod/prelude.json`,51 bytes,
auxiliar ServerVersion/ToolVersion de mongodump 100.16.0; snapshots/stream/TTL/pausa
sí verificados. Recuperación antes de 15 min y salud200/13 scopes/siete hashes exactos;
sin archive/manifest válidos/GCS/restore ni retry/otra ventana. Cleanup nuevo target
confirmado22:10:48.924702: VM6465909143569745603/disco 6372025565115631299 ausentes,
evidencia fuera antes; no GCS creado/borrado. Esta C no habilita D/E automáticamente. Excluyó restore productivo,
OAuth/tokens/secretos, IAM/otros permisos, modificar datos productivos de negocio,
Full, builds nuevos, deploy y piloto.

**Corregir/probar offline ahora sí autorizado:** selector mínimo implementado
localmente; RED auténtico 1 passed/1 failed en fixture con prelude → GREEN: 38 pruebas.
Ruff/formato/mypy verdes, 653 fuentes. Pytest general incompleto por Mongo local ausente
e interrupción, sin resumen completo ni gate aprobado. Sin ejecución real 3.10 del selector.
La identidad de publicación se consulta en Git; fuentes runtime d78 intactas. Solo herramienta del host,
no nuevos builds. No comandos nube/datos reales descargados. **Rescate no
autorizado ni validado**:30 recibos privados verificados no son hashes deBSON,
ni existe restoretarget actual. [Propuesta completa de candidatos](zelerdata-historico-rescate-candidatos-propuesta.md)
con ruta/inventario/gaps y única solicitud siguiente: **auditoría solo lectura
dentro de la VM≤5 min**, sin consultas a Mongo/download/pack/GCS/resources/pausas. Solo después
valorar permiso separado para rescate/restore sin nueva pausa; otra ventana solo
si evidencia insuficiente. No declarar respaldo ni objetivo global terminado.

### D. Rollout autorizado por goal; ejecutar solo después de gates

**Plan anterior C3/15 supersedido por objetivo14/sin Full y controles locales**.
**Selección vigente:** respaldo A–F ya PASS. API/worker d78 verificados/cacheados
siguen candidatos, sin delta de comportamiento; gateway requiere imagen del fix
desde nueva publicación exacta/procedencia verificada, **aún pendiente**. No desplegar
su digest d78 como si incluyera la admisión corregida. Identidades d78 preservadas:
gateway anterior `sha256:2f94fcac5e12d986fc91e824e753c2096a82fe6d711d4292518ced63e0d98bef`,
API `sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417`,
worker `sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
Destinos ArtifactRegistry completos en el recibo d78; pull verificado no es deploy.
Faltan nuevo build gateway/procedencia y gates runtime/recuperación/índices/registro;
no iniciar rollout por tener imágenes disponibles o respaldo aceptado.
El texto anterior preservado abajo no es autorización para desplegar C3/15. Los
tres digests **C3 históricos del texto preservado, NO destino actual**, están
verificados en el [recibo](zelerdata-historico-builds-runtime-20261003.md#1-tres-imágenes-success-con-procedencia-verificada);
los digests API/worker anteriores no sirven sobre estado nuevo por ausencia de
`policy_authority`; 13/6 y salud compatibles ya confirmados, sin probar
compatibilidad con nuevo estado. Atestiguar una alternativa recuperable antes de presentar
D ejecutable; no llamar rollback de versión a las mismas imágenes nuevas.
Inventario exacto de índices/seed, config anterior y verificación también deben
quedar delimitados. El permiso A histórico ya se ejecutó; el nuevo goal sí cubre
builds afectados desde la nueva fuente publicada exacta, no reconstrucciones ajenas.

**Plantilla anterior C3/15 — histórico, no ejecutar ni usar como permiso vigente:**

> Autorizo rollout acotado en `platform-vm` del commit
> `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` a gateway=`sha256:04fb6f2728b0344364db68eb726203132dd986c004a69d6c38c1376fdbcaad9b`,
> Sheets API=`sha256:be5ecf91e729881c9016967b21c4ce720e40b4dc45fe9184fcece774216103d9` y
> worker=`sha256:6959f6d9921eec8a29da66cb997935971e809775759668bffb2ba7808e4f13d8`,
> cada uno en su repo Artifact Registry del recibo, con onboarding apagado.
> Aplicar únicamente los cuatro archivos índice C3
> `infra/mongo/indexes/sheets_history_backfill_plans.json`,
> `infra/mongo/indexes/sheets_history_receipts.json`,
> `infra/mongo/indexes/sheets_history_pending_records.json` y
> `infra/mongo/indexes/sheets_full_operations.json`, preservando índices existentes,
> registrando colecciones antes ausentes y rechazando conflictos sin repairs.
> Registro seleccionado Sheets de 15 scopes/6 routing keys (manifest/seed C3), sin
> afectar otros clientes ni aplicar validators como health check; fingerprint `bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
> El rollback acordado `<DIGESTS_ROLLBACK_Y_CONFIG>` debe aceptar `policy_authority`,
> cuotas/checkpoints y pruebas/datos persistidos, no solo arrancar. Respetar el
> orden API/worker compatibles antes de admisión gateway y readiness de
> `accounts.linked`; ≥5 GiB libres antes de cada pull y después. Reemplazar
> únicamente servicios seleccionados, verificar digests/readiness/comportamiento
> y repetir salud/capacidad tras asentamiento. Rollback solo compatible dentro de
> este alcance; no bajar scopes, borrar jobs, broad restart, prune de volúmenes ni
> restaurar toda Mongo. No autorizo activación piloto ni consultas Full.

Un worker previo que no entiende `policy_authority` **no** es rollback
compatible sobre estado nuevo; tener 13 scopes no acredita ni descarta por sí
solo el fallback condicional antes de crear ese estado. Si no existe imagen compatible recuperable, preparar y
pedir autorización para esa alternativa exacta antes del rollout; no construir
una cuarta imagen con el permiso A ni seleccionar un tag antiguo por conveniencia.
La propuesta histórica de **dos builds C1** queda supersedida, no como próximo
permiso necesario: C1 comparte onboarding con C3; la diferencia de cuatro archivos
es Full, excluido del piloto. No es rollback general de esa funcionalidad.
[Plan mínimo actualizado](zelerdata-historico-builds-runtime-20261003.md#alternativa-mínima-concreta-de-rollback-de-versión--propuesta-histórica-supersedida):
antes del piloto, candidato conjunto de tres imágenes previas solo con ausencia
demostrada de estado `policy_authority`/incompatible o lanes antiguas totalmente
aisladas; baseline13 sano ya confirmado no sustituye esa prueba. El planner17c30 no tiene guard de autoridad:
flag OFF no evita que vea planes nuevos. Gateway actual no admite histórico;
el control de admisión gatewayC3 es gateD/E, no impedimentoC actual. Sin
prueba de ausencia/aislamiento, forward incluso antes del piloto. Después, recuperación forward
con worker consciente de autoridad, preservando datos/jobs/checkpoints; sin
old worker, bajar a13, restore ciego ni borrar estado. Garantía postpiloto pendiente
antes de ejecutar D/E; no nuevos builds, recursos o acciones aprobados aquí.
Retirada del goal: hold de admisión histórica y ejecución persistida pausada,
sin borrar/reasignar autoridad ni presupuesto; flag onboarding off/restart estrecho del worker,
conservar los tres digests nuevos y jobs/hechos; **no es rollback de versión**
ni revierte una regresión del código nuevo. Requiere operación aprobada, no A/B.

### E. Piloto: una cuenta; Full excluido

> Tras aprobar baseline, respaldo/restore y rollback de las etapas anteriores,
> autorizo el piloto para vendedor `82453304` solo confirmado legítimamente
> linked. Relink normal si es necesario, sin force ni copiar tokens. Activar
> onboarding con `ZELERDATA_HISTORY_ON_LINK_SELLERS=82453304`, ajustar solo la
> autoridad del plan preservando cutoff/consumed/checkpoints y fuentes de §6:
> hasta 2,000 GET físicos iniciales adicionales y 500 de mantenimiento (máximo
> 300 por fuente), 90 minutos dentro del mismo día UTC; máximo total 2,500.
> No subir cuotas agotadas, habilitar Full, otros sellers ni legacy adicional sin
> presupuesto separado. Usar pacing compartido, verificar datos útiles/progreso,
> cobertura sana y dos ciclos con cambios reales existentes/consentidos; no
> fabricar transacciones. Detener al límite/condiciones de §6 mediante cambio
> acotado autorizado del worker; preservar jobs y evidencia, sin repairs.
> Alcance de plantilla previa: `<HOJA_TEMPORAL_Y_RANGOS>` y fórmulas actuales
> exactas; el opt-in parcial del complemento no está implementado ni incluido.

**Full permanece bloqueado externamente, sin bloquear las otras cinco fuentes.**
Su investigación actual está cerrada por decisión del usuario: no pedir ni
programar los tres GET sin usar, consulta adicional, UI/browser ni un nuevo
mapeo/probe en esta entrega. [El registro Full](zelerdata-full-validacion-acotada.md)
conserva las fases históricas, no permisos vigentes. El piloto autorizado en una
etapa futura excluirá Full y requerirá su propio alcance, sin resets o scopes
implícitos. No solicitar tokens ni declarar RETIROS/coverage disponibles.

## Referencias

- [Builds verificados y baseline runtime actual](zelerdata-historico-builds-runtime-20261003.md).

- [Informe y matriz local](zelerdata-historico-al-vincular-implementacion.md).
- [Especificación](zelerdata-historico-al-vincular-especificacion.md), §§10–12.
- [Runbook deployment](../deploy.md), [preflight](../../infra/gce/docker-deploy-preflight.sh).
- [Probe Full](zelerdata-full-validacion-acotada.md).
- [Opt-in parcial mínimo del complemento — solo propuesta](zelerdata-ordenes-parciales-complemento-propuesta.md).
