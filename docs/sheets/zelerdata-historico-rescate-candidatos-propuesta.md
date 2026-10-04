# ZelerData: rescate condicionado de candidatos; siguiente paso solo lectura

## Autorización vigente — ampliación del 4 de octubre de 2026 UTC

El usuario autorizó auditoría de candidatos y **rescate B–F condicionado a que
pase**, sin nueva aprobación intermedia: sellado/paquete privado, mismo destino
`zelerdata-restore-aeefe993` (e2-standard-2, 8 GiB, disco 30 GiB, misma zona/proyecto,
sin IP externa ni cuenta de servicio), restore aislado y comparación contra corte;
solo después los dos objetos GCS definidos, sin sobrescritura y con conservación
mínima de siete días desde aceptación, y limpieza únicamente de VM/disco propios.
Revalidar capacidad/aislamiento actuales; ningún restore sobre producción.

**Alternativa autorizada una sola vez:** únicamente si candidatos inservibles,
después de identificar/corregir causa, ensayo sintético completo selección → paquete
→ reapertura → restore y preflight de parada/recuperación/herramientas/capacidad,
un corte adicional de máximo 15 minutos, mismas 22 colecciones. Si falla, recuperar
y detener nuevas operaciones productivas, sin cadena de intentos.

También se autoriza completar entorno y controles locales aislados. Rollout
acotado de gateway/API/worker, índices/registro requeridos y piloto HOPEMOB
82453304 de **cinco fuentes, 90 minutos y 2,500 GET físicos adicionales** quedan
autorizados **solo después de respaldo recuperable, calidad y recuperación compatible**.
Reparto: 2,000 iniciales (órdenes 800, preguntas 150, envíos 250, mensajes 300,
reclamos/devoluciones 500) + 500 mantenimiento, ≤300 por fuente; **Full 0**.
Preservar `policy_authority`, cutoff, consumos, jobs/checkpoints y otros vendedores;
no activar globalmente. No pedir permisos nuevamente por estas etapas incluidas.

### Auditoría corregida autorizada y ejecutada: PASS de alcance, no restore

El usuario autorizó **una única auditoría corregida ≤5 minutos** como excepción
expresa al no-reintento anterior, manteniendo destino/ruta/archivos/restricciones.
Antes de ejecutar, diez fixtures offline del comando pasaron; reproducción RED
original detuvo el diagnóstico tras 16 miembros por options omitido. Corrección,
clasificación de errores y parada sin retry verificadas sin repetir suites generales.

**PASS real: 41 miembros, exit 0**, driver 2026-10-04 01:18:13.686340→01:18:37.608276 UTC;
remoto `audit_passed` 01:18:37.523414 UTC. Conteos/estructura BSON/metadata de los
41 miembros coinciden con la instantánea y snapshot SHA
`04ba58489709081a57cfe777b078e5b3322ac4297442080f1b94b140d74b1136`.
Prelude autenticado declara ServerVersion **7.0.31**, ToolVersion **100.16.0** y
queda excluido. SHA stdout sanitizado
`8cc8b4c874ecf4081665b7a76a09104a0569fe4f56061d0ea1aaa8a09b867391`.
Evidencia privada `rescue-corrected-20261004T011204Z` (audit-start/end/stdout/stderr).
Sin consultas Mongo, modificación de originales, pausas, reinicios ni Full.

**La condición de auditoría para B–F está cumplida** y esas etapas siguen
previamente autorizadas; B/C y **D fiel real pasaron**. La base parcial del intento
anterior queda preservada; **E publicada/aceptada** a 02:11:08.854479 UTC.
Rollout/piloto sin ejecutar; el goal no está completado.
Auditoría de alcance no acredita hashes canónicos de datos ni restore recuperable:
respaldo, restauración aislada, rollout y piloto siguen pendientes de evidencia.
No nuevo corte: no hay candidatos inservibles acreditados. No vuelve a pedirse
permiso de auditoría ni de las etapas ya autorizadas.

### B ejecutado: paquete privado sellado, no respaldo aceptado

**PASS real, sin reintentos**, 2026-10-04 01:19:38.132670→01:19:56.032738 UTC.
Staging persistente privado:
`/var/lib/zeler-mongo/.zelerdata-rescue-20261004T011918Z/history.archive.gz`;
17,219,602 bytes, SHA
`a395bd910cc4b4b68d60bb68c2231d1658061831f995ac123657191223c5427f`.
Los 41 miembros exactos y sus SHA verificaron; originales sin cambios, sellado
0400, prelude y registro excluidos. Manifiesto en el mismo staging `manifest.json`;
compatibilidad con restaurador existente comprobada offline con cinco fixtures,
no ejecución de restore real.

Capacidad **antes** de empaquetar: raíz 36,646,793,216 bytes libres/6,233,565 inodos;
persistente 47,649,906,688 bytes/3,276,210 inodos; RAM disponible 1,837,596,672 bytes.
No son mediciones posteriores. Sin descarga de imagen en origen, pausa, dump,
consulta Mongo ni Full. **No GCS ni restore; paquete aún no aceptado como respaldo
recuperable.** C requiere capacidad/aislamiento actuales antes de preparar destino.

### C: secuencia de preparación, completada antes de D fiel

Creación 2026-10-04 01:22:37.968713→01:22:53.175733 UTC: VM
`zelerdata-restore-aeefe993`, ID **2416531264420713648**, e2-standard-2/8 GiB,
disco 30 GiB pd-balanced, COS121, sin cuenta de servicio ni IP externa. Hostkeys
atadas al ID y verificadas por serial GCP autenticado a 01:23:16.675325; archivo
knownhosts privado nuevo, confianza global intacta. No reutilizar identidad de
destinos anteriores eliminados.

Preflight detectó regla ACCEPT IPv6 previa que anulaba el aislamiento efectivo;
RED offline observado y tres pruebas GREEN del ajuste idempotente. Corrección
aplicada **solo a este destino**: primer DROP IPv6 en INPUT/OUTPUT/FORWARD;
primeras cadenas IPv4 propias IAP/metadata conservadas. Docker nativo 27.5.1,
API1.47/mínimo1.24; CLI existente SHA
`97390a21dc2ad4fcf3b2b5179bafd7cb691de6d098d6e44ea2a93e55c1f8d117`.
Se seleccionó esa CLI, sin imagen Docker29/DIND innecesaria.

**Antes de cargas:** Docker/backup en ext4 persistente, 27,109,044,224 bytes libres,
1,676,128 inodos, RAM disponible 7,930,634,240 bytes. Raíz COS readonly ~716 MB:
excepción de capacidad **exclusiva del destino**; no guardar imágenes, datos ni
archivos temporales grandes allí. Ninguna imagen ni archivo de negocio/paquete
cargados todavía; herramientas no listas, no restore acreditado.

Origen **post-pack**: raíz 36,645,949,440 bytes y persistente 47,461,027,840 bytes
libres; inodos 6,233,565/3,276,162; RAM disponible 1,850,228,736 bytes.
RepoDigest Mongo43fd y API anterior a9d33/source17c30 autenticados y verificados
actualmente, no sustituyen prueba de restore ni despliegan imágenes d78.

**Gate destino actualizado, alrededor de 01:28 UTC:** aislamiento IPv4 por primeras
cadenas restrictivas propias e IPv6 por tres primeros DROP verificado; prueba
externa IPv4 negativa acotada denegada (exit 1 y contador REJECT), sin conexión a
DB, consultas ni credenciales. Seis directorios images/mongo/backup/tmp/evidence/
operation y Docker graph en `/var` ext4 RW persistente; noexec esperado.
Pre-carga actual: 27,109,019,648 bytes libres/1,676,122 inodos/RAM disponible
7,923,462,144 bytes. `current-gates.json` preparado. Preparación del puente binario
con TDD antes de cargar; **aún sin imágenes ni datos/paquete cargados**.
Preflight inicial falló por nombre `.ApiVersion` incorrecto, corregido a
`APIVersion` de CLI27 (1.47/mínimo1.24); no bloqueo SSH ni bypass de confianza.

**Primera carga real, solo imagen Mongo:** transferencia 01:35:52.287175→
01:36:33.397108 UTC, 297,377,280 bytes, SHA
`eb11b10af119c8b1597d61408ad3e3809256b12ae73ec726792bc1d6352e6726`,
estados origen/destino 0; load terminado 01:36:57.819491 UTC con config faa77
verificada. Este archivo es la **imagen**, no el respaldo de negocio.
Destino post-carga: libres 25,917,300,736 bytes/1,669,715 inodos/RAM disponible
7,849,480,192 bytes. Puente de imagen API todavía en ejecución. Sin BSON en disco
local, GCS, deploy ni consultas Full.

**Cargas de dos imágenes PASS** a 01:37:47.633147 UTC; capacidad destino posterior:
25,169,907,712 bytes libres/1,654,538 inodos/RAM disponible 7,818,166,272 bytes.
Primer arranque de Mongo propio terminó exit 1 antes de mongod, OOM false:
entrypoint oficial bajó a UID999 y no pudo quitar sus archivos temporales porque
el bind `/tmp` propio tenía modo 0700/root. El exec de inicialización no se ejecutó
al no estar el contenedor running. **C detenida para corregir este error de setup
propio con fixture sintético de UID antes de tocar únicamente tmp del destino**;
ninguna transferencia BSON ni restore, ninguna inconsistencia de candidatos
acreditada ni nuevo corte/auditoría.

**Setup corregido y transferencia del paquete:** ocho mocks del comando corregido
GREEN antes de aplicar; Mongo 7.0.31 pasó PRIMARY, exclusivamente interno al
destino. Archive B de 17,219,602 bytes y manifest de 16,785 bytes transferidos
origen→destino con SHA exactos y ambos estados 0; sin archivo de negocio local.

**D se detuvo antes de extracción/mongorestore:** CLI27 de COS copiada en la
imagen API17c30 falló ABI DT_RELR (exit 127). Mongo destino solo contiene bases
internas; payload restaurado/evidencia de aceptación false. Preparación de
alternativa de herramienta: extraer únicamente CLI estática de artefacto público
Docker29 existente local (e6c31), **no cargar tercera imagen ni ejecutar DIND**.
No declarar restore realizado ni correspondencia canónica aprobada.

**Origen disponible durante preparación aislada:** lectura read-only
01:47:36.665509→01:47:43.592779 UTC, gateway/API/worker/dispatcher HTTP200,
ready/healthy/restarts0/OOMfalse con imágenes previas intactas y broker/componentes
ready. Recibo `original-runtime-during-isolated-preparation-readiness-stdout.log`;
sin pausa de origen, deploy ni Full.

**Herramienta operativa verificada:** solo CLI estática de 42,569,880 bytes extraída
del artefacto público local e6c31/config b402 (cadena de 16 layers), SHA
`d899b19dd3fa902c0e5700f3961099e0997fbb4838e50f32552adb5187643d92`.
Transferencia verificada y probe read-only dentro de la imagen API anterior PASS:
Client29.4.1 negoció API1.47 con Server27.5.1. Sin tercera imagen/load/download ni
DIND. Copia privada modo 0600, ejecución 0700 únicamente dentro del contenedor;
noexec de `/var` del host preservado. Mongo destino interno/payload false antes
de D. **Primer mongorestore y snapshot real en ejecución**, sin resultados
comunicados todavía; ningún restore anterior había comenzado. [L-031](../lessons/README.md#l-031--check-the-actual-operator-uid-and-cli-abi-before-isolated-restore)
registra UID/tmp/ABI y gate PRIMARY como lección durable, sin repetir suite general.

### Primer D fallido — histórico: Mongo aislado parcial, sin publicación

**mongorestore 100.16.0 terminó exit 1**, confirmado por Docker exec_die. Sin OOM:
`memory.events` oom0/kill0, peak 543,641,600 bytes. Base destino parcial;
`failed-D-snapshot-comparison.json` acredita diferencias de datos/índices/joins.
Órdenes 9,954, items 1,927, formula rows 2,912 y recovery jobs 4,328 tienen hashes
de documentos iguales al corte, **índices distintos**; preguntas 220/270,
envíos 1,000/2,444, receipts 6,000/29,653 y SKU 957/2,944, con otras colecciones
ausentes. Estas coincidencias parciales no hacen recuperable el respaldo.

**STOP: sin más escrituras de restore; E cerrada, GCS 0/deploy 0/piloto 0.**
El helper antiguo descartó stderr en DEVNULL, por lo que causa exacta aún no
capturada; no atribuir automáticamente corrupción de candidato ni sólo error
pre-extracción. Diagnóstico read-only del operador en curso: metadata Extended
JSON requiere `json_util`; el code9 previo fue del diagnóstico, no prueba de
inconsistencia de candidato. Paquete B sin cambios; no nuevo corte ni auditoría.

### D fiel autorizado: restore aislado y comparación exacta PASS

Intento fiel **único**, autorizado expresamente después del fallo anterior:
2026-10-04 02:07:49→02:09:31.183384 UTC (~102 segundos), nueva base aislada
`zelerdata_restore_aeefe993_20261003_fiel_v1`, sin borrar/modificar la base parcial
previa. Comando acotado GNU timeout 595 s TERM + 5 s KILL (máximo 600; RPC610),
preflight 24,496,943,104 bytes libres/1,654,242 inodos/RAM7,570,976,768 bytes.
Helper SHA `a20c0a097389f2eb6860158852aa921b694934c0fbe7367fcf282fb829f3e0f1`;
14 tests base + cinco acotados RED/GREEN previos. Bypass exclusivo de importación,
strict/error conservados; no normalizar contenido ni retirar guardas del producto.

**PASS: datos canónicos completos/metadata/índices/validadores/joins EXACTOS a B**;
forense antes/después intacto. Recibo privado `outside-faithful-restore-result.json`,
SHA `a90003bacf6dedd4a727a9fdbfb138f4b8529b0b532f2f8257755163c3ce7c5e`.
Un certificado y ocho freshness expirados **continúan expirados**, no renovados
para aparentar cobertura. Capacidad destino post-restore 24,189,657,088 bytes
libres/1,654,063 inodos/RAM disponible7,260,475,392 bytes.

**Reader de repositorio real PASS, alcance limitado:** imagen legacy17c30;
una orden/raw hash/fecha iguales, guard exacto `formula_data_unavailable`;
un certificado de devoluciones expirado/guard exacto `formula_data_unavailable`
y doubleread false. Ajuste mecánico únicamente de constante target del reader
(privado SHA prefijo a33bc/sufijo3e46). **No HTTP autenticado, fórmulas nativas ni
cobertura productiva acreditados por este reader.**
En ese momento E aún preparaba el manifiesto y los dos objetos autorizados;
posteriormente E pasó y se publicó el respaldo según el recibo siguiente. Sin Full, nuevo corte, deploy ni piloto.

### E PASS: respaldo publicado con integridad y retención mínima

Aceptación real **2026-10-04 02:11:08.854479 UTC**. Solamente dos objetos acordados,
ambos con precondición generación 0, estado 0, readback SHA exacto y
`temporary_hold=true`, metadata verificada:

| Objeto | Generación | Bytes | SHA256 |
| --- | --- | ---: | --- |
| `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/history.archive.gz` | 1791079848266646 | 17,219,602 | `a395bd910cc4b4b68d60bb68c2231d1658061831f995ac123657191223c5427f` |
| `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/manifest.json` | 1791079862363516 | 16,778 | `12bc8b1f2533ff43a7deabbd7e6eff52d2475c78a23cd0a12a4087a877e9fdc3` |

Manifiesto aceptado nuevo en origen, verificado contra JSON privado:
`/var/lib/zeler-mongo/.zelerdata-rescue-accepted-20261004T021033Z/manifest.json`;
no sobrescribe el manifiesto B original con `restore_proven=false`.
**No liberar antes de 2026-10-11 02:11:08.854479 UTC**. Hold indefinido hasta
liberación manual autorizada, sin autodelete ni cambios IAM/lifecycle generales.
FD stream sin datos de negocio en disco local. Respaldo recuperable acreditado
por D fiel y E, **no aceptación del producto, deploy ni piloto**.

Disponibilidad de origen 02:10:56→02:11:01 UTC: API/gateway/worker/bootstrap HTTP200,
ready/healthy/restarts0/OOMfalse; raíz36,641,300,480 bytes libres/6,233,562 inodos;
Mongo47,460,438,016 bytes/3,276,160 inodos; RAM disponible1,669,926,912 bytes.
Limpieza del destino propio posteriormente completada por F, con evidencia fuera;
ver recibo final inmediatamente abajo. Sin nuevos builds, deploy, piloto,
Full ni otro corte.

### F PASS: destino temporal eliminado, evidencia y respaldo conservados

Limpieza real **2026-10-04 02:12:00.719913 UTC**: únicamente VM
**2416531264420713648** y disco **8831012956187399344**, con IDs/users/attachment/
autodelete verificados antes; ambos ausentes en listas posteriores. Evidencia
preservada fuera antes de borrar. Índice privado final de **462 archivos**:
`corrected-rescue-final-evidence-index.json`, SHA
`c0281c63d17cde2ee6030c5dba5ba045230fcf39e73b872574712614055327a9`.
GCS y holds conservados; no borrar backup ni staging original/forense.
**A–F de rescate completos; rollout/piloto 0, Full 0 y goal global pendiente.**
Salud original posterior a limpieza **02:12:30.632597→02:12:34.210086 UTC**:
API/gateway/worker/bootstrap HTTP200/ready/healthy/restarts0/OOMfalse. Raíz
36,641,173,504 bytes libres/6,233,562 inodos; Mongo47,460,425,728 bytes/3,276,160
inodos; RAM disponible1,804,509,184 bytes. Recibo posterior preservado fuera del
índice original de 462 archivos; no inventar SHA de índice ampliado. Fuentes
service gateway/core/modules/bootstrap/pyproject/uv.lock idénticas a d78 según
comparación read-only con main02:12; no nuevos builds por fixes operativos.

### Auditoría original fallida — histórico, no repetición automática

Driver 00:22:46.970145→00:22:58.447630 UTC, exit 1: inventario/directorio/mount/bind
pasaron en Python del host 3.10; 16 miembros completados, incluido snapshot, hasta
BSON run_windows (8 registros). Metadata falló `readonly_subcommand`: diagnóstico
propio exigía options explícito que Tools omite cuando vacío. No corrupción
probada; siete fixtures del procesador privado pasaron después de RED, SHA
`61b04f3ea4a2873b8cdc73218acc072077e8a84fdcf2bd44aa29350f95dbb021`.
La reanudación no estaba autorizada entonces; posteriormente la excepción expresa
permitió el único intento corregido descrito arriba. Recibos históricos
`rescue-20261004T002229Z` preservados, sin datos sensibles publicados.

**Controles locales finales verdes:** full Linux **5,946 passed/9 skipped, 425.84 s, exit 0**, 2026-10-04 00:54:46.140710→01:01:54.421494 UTC (helper 428.281 s). Los ocho tests broker pasaron integrados; ocho skips por guard ambiental Mongo quedan cubiertos por protected Linux **8 passed/2.08 s**; el noveno es Caddy sin requiredkeys, caso intencional. 1,053 hashes/modos intactos de fuente dbf, lock intacto, OOM 0; Ruff/formato/mypy verdes (653 fuentes). No sumar los lotes protegidos al total ni convertir calidad local en aceptación productiva.

**Intentos anteriores, históricos:** macOS 12 failed/5,926 passed/17 skipped (481.44 s), sin Mongoerrors; fallos baseline Bash3.2/BSDstat. Primer Linux 18 failed/5,928 passed/9 skipped (417.96 s), entorno incompleto: Node/Git ausentes y zombies State Z/PPid1 por PID1 Python sin init. Entorno efímero corregido con Node18.20.4/Git2.39.5 y `--init`; exactos 18 passed/3.70 s y protected ocho passed/2.08 s antes del full final. La repetición completa fue justificada por entorno invalidado, no por costumbre. Sin modificación de código ni nuevos builds. Limpieza local completada 2026-10-04 01:05:11.228918 UTC: únicamente seis contenedores/seis volúmenes/perfil propios; perfiles anteriores Stopped y contexto colima preservados. Índice de 41 evidencias SHA `29cbef2c2638e31d66aa62191f28d6f84cec44fbb942fcbcd39491ba9df1486f`; cleanup SHA `ca0b70e3112fae194b1dcff6f6dd49f4e18d8ccd50b0f7414050daa25b88ec02`. Evidencias privadas fuera del repositorio:
`/Users/eduardoramirez/.codex/cache/zeler-local-mongo-gate-cb6c288527f9/verification-receipt.md`
y `evidence-index.json`; sin credenciales en los recibos.
La publicación del selector (`dbf84928167c1ea66113d9005440e201eeb1566e`) no
cambia las fuentes runtime d78 ni exige nuevos builds por sí misma. Las mediciones,
restricciones de permiso y fallos anteriores se conservan abajo como **históricos**:
las frases «autorización futura», «única solicitud» o «no autorizado» describen su
momento anterior y quedan sustituidas por esta ampliación, no son gates nuevos.


**Estado previo — histórico:** antes del rescate, los candidatos no eran un respaldo aceptado ni se acreditaba que fueran recuperables. El resultado actual es D fiel/E PASS, arriba.
La corrección mínima del selector está implementada y probada localmente.
RED auténtico previo: 1 passed/1 failed por `unexpected_dump_member` en el fixture
con prelude; el caso normal de 41 miembros sin prelude pasó. **GREEN: 38 pruebas**.
**Control general anterior — histórico, sustituido por la ejecución del aviso vigente:** pytest terminó con exit 1, sin resumen completo, por Mongo local `127.0.0.1:27017` sin listener e interrupción (KeyboardInterrupt y KeyError de pytest_stash en teardown). No se inició Mongo ni se preparó otro entorno. Ruff y formato exit 0; mypy exit 0, 653 fuentes. Las 38 pruebas enfocadas y el smoke sintético de 41 miembros son válidos; no acreditan restore real. Los 12 fallos Bash/BSD anteriores son evidencia histórica, no un resultado repetido en esta ejecución.
Este cierre documental se publica por separado; su identidad se consulta en Git y no cambia el código de los servicios de la fuente d78.
Solo herramienta operativa del host con biblioteca estándar, sin cambios en las
fuentes runtime de servicios respecto de d78 ni necesidad de nuevos builds.
Los términos del plan son: **snapshot**, instantánea del corte; **BSON**, archivos
binarios de datos Mongo; **metadata**, índices/esquemas asociados; **pack**, paquete
tar.gz; **restore**, restauración exclusivamente aislada.
**Solicitud original — histórica, sustituida por ampliación vigente:** en aquel
momento solo se proponía auditoría §5 y no se habían recibido permisos de rescate,
GCS, recursos ni restore. La ampliación superior los autoriza bajo condiciones;
objetivo global, deploy y piloto siguen sin aceptación. Full continúa excluido y
no se propone otro corte por costumbre.

## 1. Ubicación e inventario: auditoría corregida de archivos completada

Origen: `platform-vm`, proyecto `zeler-platform-dev`, zona `us-central1-a`.
Ruta registrada: `/var/lib/zeler-mongo/.zelerdata-c-new-20261003T214827Z`;
el bind Mongo la presenta como `/data/db/.zelerdata-c-new-20261003T214827Z`.
La auditoría corregida de 01:18 revalidó directorio/mount/bind y los 41 miembros,
con estructura/conteos/metadata coincidentes; aún no acredita comparación canónica
de datos ni restore recuperable. El
inventario detallado de bytes siguiente conserva su timestamp histórico.

| Payload positivo previsto | Inventario registrado 22:08:45.008384 UTC |
| --- | --- |
| BSON de 20 colecciones presentes |20 archivos,171,406,662 bytes. |
| Metadata de esas mismas 20 |20 archivos,50,994 bytes. |
| Snapshot del corte |`cut-snapshot.json`;41 miembros positivos en total. |
| Auxiliar excluido |`dump/zeler_platform_prod/prelude.json`,51 bytes; claves `ServerVersion`/`ToolVersion`. Tool 100.16.0 y ServerVersion 7.0.31 verificados en auditoría corregida; el valor de ServerVersion no se capturó en el corte original. |
| Ausencias explícitas |`sheets_full_operations`, `sheets_history_pending_records`; no inventar BSON ni borrar una colección creada después. |

Selección exacta 22, sin comodines:

| Grupo | Colecciones |
| --- | --- |
| Hechos canónicos |`orders`, `questions`, `shipments`, `claims`, `messages`, `items`. |
| Proyecciones órdenes/SKU |`sheets_item_formula_rows`, `sheets_item_sku_index`. |
| Histórico |`sheets_history_backfill_plans`, `sheets_history_acquisitions`, `sheets_history_receipts`, `sheets_history_order_ranges`, `sheets_history_pending_records`. |
| Recovery/admisión |`sheets_formula_recovery_jobs`, `sheets_formula_recovery_admission`. |
| DEVOLUCIONES |`sheets_devoluciones_operations`, `sheets_devoluciones_runs`, `sheets_devoluciones_run_windows`, `sheets_devoluciones_certificates`. |
| Freshness |`sheets_read_model_freshness`. |
| Full: solo archivos ya seleccionados, nunca adquisición |`sheets_full_operations`, `sheets_full_withdrawals`. |

Excluir OAuth, `meli_accounts`, tokens, identidades, secretos, cualquier otra
colección y preimagen forense del registro 14. No exportar toda la base como intermediario.

## 2. Qué demuestra la evidencia disponible y qué falta

Esta sección preserva evidencia/faltantes **anteriores al rescate**, no sustituye
los resultados actuales D fiel/E/F descritos arriba.

Auditoría **local** de 30 recibos SHA verificados, índice
`a049329a9222a0ce2ac99868ee84d558984c7c6b82385a435053475447a66290`.
Resumen privado `history-selector-offline-20261003T225326Z/available-evidence-audit.json`;
recibos originales `c-new-20261003T214827Z`. No se descargaron BSON reales.

| Acreditado históricamente | Límite / verificación aún necesaria |
| --- | --- |
| Corte 22:06:27.367903→snapshot final 22:08:03.094015 UTC; tres actores detenidos, snapshots exactos antes/después iguales, TTL 0, stream con 0 escrituras, gates tardíos jobs 0. |No demuestra por sí solo que cada BSON/metadata corresponda al snapshot. |
| Diagnóstico: mongodump 100.16.0 generó prelude auxiliar no previsto; error propio `unexpected_dump_member`, no de pausa. |Corregir selector no acredita integridad/contenido ni justifica aceptar extras arbitrarios. |
| Snapshot incluye hashes canónicos/metadata, esquemas y evidencia de joins; pause journal/resume-state/guard-result y cloud-gates preservados fuera del target. |Faltan hashes baseline por archivo BSON, validación estructural/conteos de archivos actuales, comparación datos canónicos del dump y metadata contra corte y restore. |
| Recuperación 22:08; salud asentada 22:11:24–28/13 scopes / 6 claves/siete hashes exactos. |Salud/capacidad son históricas, no actuales ni aceptación de lectores. |
| VM destino 6465909143569745603/disco 6372025565115631299 eliminados 22:10:48.924702 UTC. |No existe destino de restore ni conexión Mongo aislada acreditada actualmente. |

**Estado anterior al rescate — histórico:** no había archive/manifiesto aceptados
ni objetos GCS/restore; D fiel/E/F posteriores completaron ese alcance. La existencia actual del
directorio/41 miembros se revalidaron en auditoría corregida de 01:18, **no hashes canónicos de datos ni restore**. Hashes de recibos no son hashes de BSON, y una SHA
calculada hoy no prueba por sí sola que el archivo no cambió desde el corte.

## 3. Selector canónico: reutilización obligatoria, no certificación

Reutilizar [módulo canónico](../../infra/operations/zelerdata_history_archive.py)
(biblioteca estándar/Python del host 3.10), no editar/reanudar scripts privados antiguos del corte.
**No está instalado en la VM actual**: para la auditoría, cargar bytes exactos del
módulo publicado vía STDIN, verificar SHA e importar **en memoria**, sin instalación,
copia a disco ni pycache. No sustituirlo por validador duplicado en línea:

- `select_backup_files(base_dir, present)` selecciona únicamente pares positivos
  BSON/metadata y snapshot; el prelude opcional se valida acotado y **se excluye**.
- `expected_member_names(present)` define el conjunto exacto; la tupla seleccionada
  **ya incluye cut-snapshot**, no agregarlo por segunda vez al adaptador del empaquetado.
- `validate_archive_members(archive, present)` exige miembros positivos exactos,
  sin duplicados, symlinks/hardlinks, extras ni faltantes.
- La forma del prelude exige exactamente ServerVersion/ToolVersion y Tool 100.16.0,
  pero el helper solo valida su forma. La auditoría corrigió ese pendiente:
  archivo auténtico declara 7.0.31, sin consultar Mongo ni inventarlo.

Prelude solo en ubicación exacta, regular/nlink 1,≤ 4096 bytes, JSON sin claves
duplicadas/solo ServerVersion y ToolVersion 100.16.0; ServerVersion numérico de tres
partes. El fixture 7.0.12 es **sintético**, no la versión 7.0.31 declarada por el prelude auténtico.
Reutilizar módulo **publicado exacto** mediante import, no copiar otro validador
en línea ni relanzar el corte privado; scripts privados antiguos permanecen forenses,
sin editar. El selector se ejecutó realmente en Python del host 3.10. El primer diagnóstico
falló por options omitido; la auditoría corregida pasó los 41 miembros, sin que
eso equivalga a comparación canónica de datos o restore.

Hashes locales congelados, no SHA de publicación anticipada:

- Helper `e86612a00bf720d329409a5f9fcc6c7f71936af3bee750e4a4ab6a34770fe380`.
- Tests `35c49b133b01cd2dd65cf1d0cf72beba343f238d4a3bf07b89bb3de28a0aa726`.

Estas funciones no certifican BSON, SHA por archivo, consistencia, capacidad ni
restore; los archivos pueden cambiar después de seleccionarlos. Pruebas locales
no sustituyen auditoría actual ni contenido real. El control general quedó
incompleto por el entorno en la ejecución anterior; el aviso vigente comunica
los controles actuales. La identidad de publicación se consulta en Git.
Smoke independiente del operador: selección de 41 miembros → tar.gz → reapertura
exacta, con prelude y registro excluidos; **solo datos sintéticos**, sin restore real.

## 4. Plan completo: B–F autorizados condicionados a auditoría

| Etapa autorizada y condicionada | Gate y operación necesaria |
| --- | --- |
| A. Auditoría actual (§5) |Solo lectura dentro de la VM de candidatos y evidencia; si falla, parar sin reintentos. No pausa ni nuevas consultas a Mongo. |
| B. Sellar/empaquetar tras auditoría |Revalidar archivos/recursos/capacidad actuales; seleccionar/copiar a staging privado sellado sin alterar originales ni datos de negocio. Comparar SHA antes/después de copia/pack y metadata/snapshot. tar.gz con los 41 miembros positivos y manifiesto sanitizado; sin incluir toda la base ni secretos. Sistema de archivos y RAM de origen históricos no son permiso ni capacidad suficiente actual. |
| C. Preparar aislado/transferir tras auditoría |Crear solo misma clase de destino `zelerdata-restore-aeefe993`, misma zona/proyecto, e2-standard-2/8 GiB/disco 30 GiB pd-balanced, sin cuenta de servicio ni IP externa, SSH por IAP estricto/red VPC/tráfico saliente aislado; mismos recursos/costos delimitados en §8C de la propuesta general, sin inventar precios actuales. Persistencia de Docker/datos/backup/tmp; `mongo@sha256:43fddee7e532a920f3dfdee9e8f4834398c155c26bcb92d790cc1cd3c630fc40`, loopback 27018/rs0/base `zelerdata_restore_aeefe993_20261003`. Revalidar capacidad/imágenes/mount/inodos/RAM actuales de origen/destino: piso 5 GiB más margen de empaquetado/desempaquetado, excepción COS solo para el destino; medida antigua no basta. Transferir artefacto sellado origen→destino mediante stream por IAP acotado, **sin datos del paquete en disco local ni transferencia de credenciales**; verificar sellos/SHA al recibir. Sin descargas de imágenes ni cambios en producción; sin aplicación, workers ni OAuth ni nuevos Cloud Builds. No es parte de auditoría actual. |
| D. Restore/comparación ANTES de publicar backup |En rs0 aislado comparar hashes canónicos de datos, metadata/índices/validadores/esquemas y joins exactos contra snapshot del corte. Reconciliar conteos/ausencias/gaps; certificados/rangos/lectores normales preservan fail-closed y períodos independientes, sin renovar inventando evidencia. HTTP 200/mongorestore con salida 0 no bastan. Origen/hechos posteriores intactos; **nunca restore productivo**. Si contenido/snapshot no coincide, abortar SIN publicar respaldo en GCS ni declarar recuperable. |
| E. GCS solo tras restore coincidente |Publicar solamente `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/history.archive.gz` y `manifest.json`, **después** de acreditar contenido/restore contra corte; precondición generación 0, sin sobrescritura. Verificar SHA/generación, retención/holds mínimo 7 días **desde aceptación** conforme autorización; no IAM/lifecycle/prune ni borrar backups existentes. Sin correspondencia demostrada no subir ni llamar backup al candidato. |
| F. Cierre/backout |Si se acepta restore o se abandona definitivamente, limpiar únicamente VM/disco temporales con identidad/evidencia fuera; preservar GCS según retención aprobada. Ante error, parar, no reintentar ni recrear recursos/cortar producción automáticamente. |

Si no puede acreditarse que contenido/metadata corresponden al corte, **abortar
el rescate sin declarar backup recuperable**. La única ventana alternativa de
máximo 15 minutos ya está autorizada exclusivamente bajo las condiciones del aviso
vigente. Rollout y piloto también están autorizados, pero no ejecutables hasta
acreditar respaldo, controles y recuperación compatible; Full sigue excluido.

<a id="5-única-solicitud-actual-auditoría-solo-lectura-de-candidatos"></a>

## 5. Alcance de auditoría autorizado; propuesta original preservada

Texto de alcance propuesto anteriormente y ahora autorizado por la ampliación;
no constituye prueba de resultado. Las exclusiones se refieren a la auditoría A,
no revocan B–F ni rollout/piloto condicionados del aviso vigente:

> Autorizo **una auditoría solo lectura, máximo 5 minutos**, dentro del contexto VM/VPC
> de `platform-vm`, proyecto `zeler-platform-dev`, zona `us-central1-a`, de la ruta
> `/var/lib/zeler-mongo/.zelerdata-c-new-20261003T214827Z` y su bind registrado.
> Comprobar ubicación/mount/owners y ausencia de links/extras dentro del dump;
> excluir archivos operativos de la raíz que estén fuera del payload. Comparar
> inventario actual contra el registrado: 41 archivos positivos y únicamente
> prelude opcional acotado, con validación del snapshot.
> Cargar bytes exactos del selector canónico publicado vía STDIN, SHA verificado e
> import en memoria: sin instalar/copiar a disco/pycache ni validator duplicado.
> Verificar estructura/conteos BSON,
> tamaños/SHA256 de cada archivo, forma metadata, snapshot y su igualdad con evidencia
> privada preservada; validar prelude/tool shape sin inventar ServerVersion.
> Emitir solo nombres/conteos/tamaños/hashes/códigos sanitizados, jamás documentos,
> PII, cuerpos, tokens ni contenido BSON. Sin consultas a Mongo ni descargar datos de
> negocio a local. Sin escribir archive/manifiesto, copiar/sellar archivos, upload,
> recursos, pausas, restart, cambios de permisos/IAM ni Full. Sin reintentos; parar al
> primer error/inconsistencia o al límite. Reportar lo acreditado y lo pendiente.
> Esta auditoría **no acredita hash canónico de backup ni restore** y no autoriza
> rescate/empaquetado/GCS/restore, otra ventana productiva, builds, deploy o piloto.

## Referencias

- [Nueva C fallida, recuperación/cleanup y evidencia](zelerdata-historico-builds-runtime-20261003.md#nueva-c-autorizada-aborto-por-selector-origen-recuperado).
- [Informe de implementación y gates](zelerdata-historico-al-vincular-implementacion.md).
- [Propuesta general; fuentes/rollback/piloto pendientes](zelerdata-historico-publicacion-piloto-propuesta.md).
- [Pruebas del selector](../../tests/test_zelerdata_history_archive.py).
