# ZelerData: builds verificados y baseline runtime — 3 de octubre de 2026

**A y B autorizados y ejecutados:** tres Cloud Builds de la fuente exacta C3
`aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d` y una inspección read-only de
`platform-vm`. **Durante A/B no se desplegó, descargó imagen en VM, hizo backup/restore,
modificó registro/índices, reinició servicio ni activó piloto.**
La reparación estrecha de registro posterior se detalla abajo. Este reporte y
su actualización de propuesta permanecen locales. El goal posterior autoriza
publicación propia verificada, todavía sin nuevo commit/push registrado aquí. Full está cerrado: no consumir ni programar los tres GET sin usar.

## Goal vigente: autorización amplia, aceptación todavía pendiente

El nuevo goal autoriza cierre acotado de las cinco fuentes/Full0: ensayo de pausa
fuera de producción, una nueva ventana C≤15min cuando pase, despliegue seleccionado
tras respaldo/seguridad y pilotoHOPEMOB≤90min/2,500GET. La evidencia previa sigue
vigente donde no se invalide; **C fallido abajo no se convierte en backup/restore
exitoso ni nueva ejecución por recibir permiso**. No se acredita nuevo deploy/piloto.
Hoja privada/fórmulas actuales y API normal parcial se verificarán por separado:
[checklist y preparación](zelerdata-historico-al-vincular-implementacion.md#preparación-de-aceptación-del-goal-oauth-api-normal-y-sheets-nativo).
La limpieza del goal permite eliminar únicamente la VM/disco temporales después
de restore validado o abandono definitivo, con identidad/evidencia preservadas;
no GCS/productivo. Abandono autorizado y limpieza ya ejecutados: targetVM/disco
eliminados por identidad con evidencia fuera, detalle abajo; sin borradoGCS.

### Actualización del goal; ensayo completo y C fallido, sin rollout

Controles de admisión/ejecución congelados: hold histórico en gateway, claim,
deadline, pausa y presupuesto físico persistidos; recuperación forward conserva
autoridad/checkpoints/cuotas con admisión cerrada/ejecución pausada. Objetivo nuevo:
**14 scopes = baseline13 + `GET /messages/packs/*`, seis keys y ningún scope Full**.
Fingerprint objetivo `453bf9eb6014d8055fe6cd372e98b1e2d0190a0241b519417fe5f5397e2c1525`;
verificador canónico corregido no acredita compatibilidadC1 ni permite rollback clásico.
C3/15 y builds de §1 son históricos, no destino automático del nuevo goal. Fuente
nueva sin SHA publicado; ningún build/deploy/piloto nuevo acreditado.

Gateway36/coordinador59/core18/queue2 y lote99(incluye parcial10k) verdes;
Ruff/format/mypy651, direct-Meli y schema-export finales **verdes tras patchruntime
final**. Último lote74passed/27.76s incluye12cert×1000/dos workers/cuatro
renovaciones y spacing estricto; capacidad anual3passed/52.16s tras patchfinal.
Staged-gitleaks limpio. **Rootgate general no verde**: fragmento2860nodes tuvo
13failed/2838passed/9skipped259.20s. Una regresión propia era verificador15 frente
a manifest14: corregidos helper y testdeploymentpreflight, 35purehelper/provenance
passed0.24s. Otros12 preexistentes verificados en HEAD13972ec:12failed/2.20s,
mismas funcionesAST/tres scripts byteidénticos, Bash3.2.57/BSDstat incompatibles
(`read -t0.01`, `stat -c`, emptyarray/nounset); sin Bash5 instalado ni pruebaLinux.
Ocho stockrs0 protegidos **8passed/2.20s**, envMONGOunset y ZELER_RS0_TEST_URI
literal verificado propio27030/rs0; no guardMongo skipped. Restan8skipsbroker/1Caddy
y12baselineMac, no rootgate general verde ni pruebaLinux. Evidencia privada
`cache/checks/shell-baseline-verification.json`/`shell-baseline-pytest-baseline.log`.
No sumar lotes superpuestos ni repetir prefijo válido; recuperación/OOM de Mongo
local de prueba no acredita falla productiva. No corregir12 fallos ajenos como scope creep.

RED previo de capacidad compartida falló spacing(15.96s): awaitMongo entre pacing
y RPC agrupaba envíos. Fix local fetch/request/claims: **reserva/cobro durable y
validación persistida → pacing único → guard síncrono UTCdeadline/día → RPC**, sin
awaitMongo entre pacer/send. Gateway mantiene guard persistido tardío tras broker/KMS.
Reserva vencida esperando conserva consumed1 conservador pero HTTP0, sin refund/reset;
no afirmar cobro0. [Lecciones L-029/L-030](../lessons/README.md); ningún build/deploy
nuevo acreditado por estos checks.
Ensayo real fresh5: pausa3 sin auto-restart/reanuda3/guard complete pasó; helper
congelado acepta finalizaciónAPI solo por logs complete de PID/generación y no
deja RPC stop pendientes. Run5 real **completo pasado**, Docker29.4.1: normal,
deadline y guard; job fence1/attempt1/lease y Rabbit unacked1→guard recovery.

Readiness fresca alrededor de20:59 UTC: gateway/API/worker/dispatcher y dependencias
listos, baseline13. [HojaTEMP nativa privada](https://docs.google.com/spreadsheets/d/1IzBEJ6fTs3-juTvWYv0P9dK_0gMpS5jo5y18KlsmitU/edit?ouid=110356598393864429185)
creada bajo Cuenta Zeler; perfil110356598393864429185/propietario único verificados,
ocho pestañas/0 fórmulas, sin customfunction calls. Evidencia privada
`private-sheet-preparation.json`; permanece inactiva hasta piloto. No acredita
OAuth/add-on funcional ni parcialAPI: [checklist](zelerdata-historico-al-vincular-implementacion.md#preparación-de-aceptación-del-goal-oauth-api-normal-y-sheets-nativo).

### Único C del goal: fallido antes del dump

| Hecho | Evidencia UTC del3octubre; no prueba de respaldo |
| --- | --- |
| Inicio/código | 21:09:57.466075Z; **command_failed**, antes de dump y antes de writers_stopped. |
| Causa propia | Parser de finalizaciónAPI del helper canónico bajo Python3.10 del host no acepta timestamps DockerRFC3339Nano (StartedAt8 dígitos/sentinels9). No fallo de salida graceful: logs reales21:10:02.451003870Z complete y21:10:02.451807973Z finished/PID7 presentes. |
| Recuperación | API21:10:02.907969955Z y dispatcher21:10:03.322185068Z; gateway/worker conservan identidad y StartedAt. Cuatro HTTP200/ready21:10:53–58, baseline13/seis keys y hashes exactos de siete clientes; sin restituirFull. |
| No ocurrió | Sin dump/archive/manifiesto/GCSbackup/restore ni nuevos builds/deploy/piloto. **No segundo C permitido** ni retry automático. |
| Corrección local | Parser conserva precisiónNano exacta/Python3.10; 37+6 pruebas verdes, helper prefijoSHA30ecbeb. HostPython3.10 verificado read-only alrededor de21:12 con timestamps auténticos/proofTRUE (`fixed-parser-host310.jsonl`); rechecks estáticos finales verdes. Ningún otro ensayo/corte. |
| Abandono/limpieza ejecutados | VMID190812944583158189 y diskID9220450358313937325 eliminados bajo autorización; filtros de instances/disks ambos[] en `cleanup-result.json`. Journals normal/deadline/guard real y capacidad copiados fuera antes. Sin borradosGCS ni otros recursos. |
| Última medida target antes de limpieza | Libres18,066,452,480bytes; inodos1,585,304; RAM disponible6,983,139,328bytes. No destino aún activo ni restore ejecutado. |
| Estado final origen | `source-final-after-abort`: archive/dump/manifestFALSE, guardcompleted/recoveryTRUE; raíz36,674,703,360bytes libres, Mongo47,803,904,000bytes. Baseline13 y hashes de siete clientes exactos, sin restituirFull. |
| Colas tras asentamiento alrededor de21:12 | Live events ready0/unacked0/consumer1; claims ready0/unacked0/consumer1. EventsDLQ315 **preexistentes**, claimsDLQ0; no purge. Observación puntual, no garantía futura. PrefixGCS exacto sin objetos; backups previos/retención intactos y ningún delete. |

**Despliegue y piloto bloqueados porque no existe respaldo consistente restaurado**.
Publicación de código/pruebas propios continúa independiente; no convertir el fix
local o ensayo verde en permiso de otro C. La hoja privada permanece inactiva;
Full7/10 histórico cerrado y tres sin usar nunca autorizan nuevas consultas.

## Reparación histórica de registro: disponibilidad recuperada sin restart

Acceso GCP recuperado; reparación autorizada **ejecutada y verificada desde VM**.
Operación **2026-10-03 19:12:42.007120 → 19:12:49.687008 UTC**.
A **19:12:45.832873 UTC**, las tres imágenes anteriores seguían sin cambio y
el registro Sheets completo, excluyendo únicamente
`GET /stock/fulfillment/operations/search`, coincidía con el manifest desplegado:
**13 scopes/6 routing keys**, fingerprint
`98cd1f6c9eba470251fdfc5e120b635e4928f9defd28af7cfff0510a63f2c96a`.
No se encontró otra diferencia.

| Evidencia estrecha | Resultado verificado |
| --- | --- |
| Preimagen antes de escribir | VM `/var/tmp/zelerdata-sheets-scope-before-removal-20261003T191242Z.bson`, owner root/mode0600; hash verificado antes del CAS. |
| BSON previo / SHA256 | `9b6079bd04f0979d6fc64d7c53cea0936daf29597bb06d693385a3c420fd3eae` |
| CAS a19:12:49.007260 UTC | Único `$pull` de `allowed_meli_scopes`, matched1/modified1: solo search, **14→13 scopes**, routing keys6 intactas. |
| BSON posterior / SHA256 | `5835d17343c33286f5d0261c724aacf159e5cd786d5e7befb3bfb07348c72c95` |
| Conservación | Cada otro campo de Sheets y los otros seis clientes exactos intactos; sin replace_one/timestamp/otra escritura. |

**Salud posterior, 19:13:22 → 19:13:27 UTC:**

- Sheets API: **200 ready:true**, Docker healthy, Mongo/Rabbit/
  `registry_fingerprint_match` OK; DLQ ready=0/unacked=0.
- Gateway `/ready`: **200**, Mongo/registry/Rabbit/repricer_scheduler OK.
- Worker: **200 ready:true**, Rabbit/sync_jobs_poller/formula_recovery/refresh OK.
- Los tres: restart count0/OOMfalse; digests y horas de inicio intactos.
  **Sin restart, image swap, business writes, tokens u otros permisos modificados.**

Baseline compatible13/6 **confirmado**, no solo objetivo. C preservará ese estado,
nunca restituirá14. La preimagen14 es **evidencia forense**, no baseline de backup
ni instrucción de reversión: restaurarla recrearía mismatch. No hubo nuevos builds,
recursos, backup/restore, despliegue o piloto; Full sigue0/cerrado. Estos health
checks no prueban escritura nativa Sheets ni estabilidad del piloto no iniciado.
Evidencia local seleccionada: `/tmp/zeler-sheets-scope-removal-20261003.log` y
log de salud posterior conservado por el operador.
C se autorizó posteriormente: preparación parcial y bloqueo real en §4; no
confundir ese avance con el alcance de la reparación.

**Ingress público confirmado a19:14:19.109613 UTC**, aproximadamente90s después
del CAS: HTTPS Sheets `/health`200 ready:true, Mongo/Rabbit/registry/DLQ OK,
sin restart. Confianza SSH y cuatro hashes fuente validados intactos; sin repetir
suites. No prueba OAuth Sheets, fórmulas nativas ni aceptación del piloto.

### Antecedentes de autenticación y disponibilidad; superados

Bloqueo registrado por root **17:03:40 UTC**, después del comando fallido (no su
hora de inicio): `problem refreshing current auth tokens: Reauthentication failed.
cannot prompt during non-interactive execution`. Ese primer intento no alcanzó
SSH/Mongo ni creó preimagen/escritura; no hubo retry o cambio de identidad/trust.
Los tres hashes locales de confianza SSH quedaron intactos.
A **17:04:59.014110 UTC**, dos GET HTTPS legítimos/sin retries, sin VM/Meli/
credenciales/mutación: Sheets `/health`503 ready:false/mismatch, Mongo/Rabbit OK,
DLQ0/0; gateway `/ready`200/dependencias OK. Worker entonces no verificado.
Ese checkpoint, `/tmp/zeler-sheets-availability-public-health-20261003.json`,
queda histórico, no resultado tras reparación ni prueba de scopes actuales.
El alcance acotado autorizado se completó después mediante comparación total,
preimagen0600/hash, CAS solo scope y salud sin restart descritos arriba.

## 1. Tres imágenes SUCCESS con procedencia verificada

Ventana de builds: **2026-10-03 05:07:03 → 05:08:28 UTC**. Una imagen por build,
`options.requestedVerifyOption: VERIFIED`, fuente C3 exacta presente en `main`;
`origin/main` verificado como `13972ec68c1951b2ca18b1e05d0dd65a7fe8e4b5`
contiene C3, no sustituye su SHA fuente exacto.
Repositorio conectado:
`projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform`.
Artifact Registry: `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform`.

| Servicio / Dockerfile | Build ID SUCCESS | Digest inmutable verificado |
| --- | --- | --- |
| `gateway` / `gateway/Dockerfile` | `fcb23a3a-6fcf-47b3-9b4b-c06ffa65a921` | `sha256:04fb6f2728b0344364db68eb726203132dd986c004a69d6c38c1376fdbcaad9b` |
| `sheets-api` / `modules/sheets/Dockerfile.api` | `c3d908e2-b56c-44fd-baff-a27b131b9a11` | `sha256:be5ecf91e729881c9016967b21c4ce720e40b4dc45fe9184fcece774216103d9` |
| `sheets-worker` / `modules/sheets/Dockerfile.worker` | `b38557b0-d890-4c12-8a9e-f24ea59f1e4d` | `sha256:6959f6d9921eec8a29da66cb997935971e809775759668bffb2ba7808e4f13d8` |

Referencias de despliegue candidatas, **no ejecutadas**:

- `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:04fb6f2728b0344364db68eb726203132dd986c004a69d6c38c1376fdbcaad9b`
- `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:be5ecf91e729881c9016967b21c4ce720e40b4dc45fe9184fcece774216103d9`
- `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:6959f6d9921eec8a29da66cb997935971e809775759668bffb2ba7808e4f13d8`

El verificador canónico `infra.deploy.provenance_check verify-image` confirmó
SUCCESS, repositorio/revisión C3 y sujeto/digest de las tres imágenes. No se
confunden tags con autoridad ni se subió un checkout local. Build SUCCESS no
prueba runtime ni autoriza el despliegue.

## 2. Imágenes en ejecución y drift medido

Inspección **2026-10-03 05:08:37 UTC**, GCP `zeler-platform-dev`, VM
`platform-vm`, zona `us-central1-a`. Identidades de las imágenes ejecutadas:

| Servicio | Digest realmente ejecutado | Fuente/procedencia observada | Salud de baseline |
| --- | --- | --- | --- |
| Gateway | `sha256:8b6551451509040aed607c086f8b94ad9ce586ffee8b5ba5c9a420844337ba50` | Verificada: `b835791193506f0d32b3350e7606c8d644019114` | Healthy; `/ready` 200, `status=ready`, Mongo/registry/Rabbit/repricer_scheduler OK. |
| Sheets API | `sha256:a9d33c3fcb428bb8502feba4b7a05084a08eeb4fa097069c6de40daafae1f72b` | Verificada: `17c30f46d25e1309b0df0003821b9674915854ef` | **Unhealthy, 503: `registry_fingerprint_mismatch`**. |
| Sheets worker | `sha256:b0925d9251d1b34080435caa6f6f2224ce32e5842fbac626fc45224bb1a8bb66` | Verificada: `17c30f46d25e1309b0df0003821b9674915854ef`; build `906c1f5c-b41a-4788-8035-53c99348d09e`. | Healthy; `/health` 200, ready:true; Rabbit/sync_jobs_poller/formula_recovery/zelerdata_refresh OK; history_onboarding ausente. |

Los tres contenedores tienen **restart count 0 / OOM false**. Registro observado en A/B:
**14 scopes / 6 routing keys** por el permiso search Full previamente autorizado;
contrato local C3: 15 scopes/6 keys, **no desplegado**. La API ya devolvía 503 antes
de cualquier despliegue nuevo; no se presenta esa condición como regresión de
los builds ni como rollback sano. Mongo/Rabbit checks de la API: OK; DLQ **ready=0/unacked=0** según esa inspección; no se midió
consumers=0. Cola vacía no prueba readiness/consumo.

Procedencia/readiness comprobadas a **05:10:57 UTC**; metadata final de lectura
**05:13:42 UTC**: drift de los tres servicios frente a C3
verificado por digest y fuente. Manifest de la API anterior: **13 scopes / 6 keys**,
fingerprint `98cd1f6c9eba470251fdfc5e120b635e4928f9defd28af7cfff0510a63f2c96a`;
registro runtime 14/6, única diferencia extra
`GET /stock/fulfillment/operations/search`, ningún scope faltante. Eso explica
el 503 `registry_fingerprint_mismatch`; no se reparó **durante A/B**. API/worker ejecutados carecen
de `policy_authority` según código runtime/source verificados, no son autoridad
de rollback para jobs nuevos. No se dedujo fuente de tags o container healthy. **Las imágenes actuales no se aceptan
por defecto como rollback compatible**: API unhealthy en ese baseline histórico
y workers previos que no
entienden `policy_authority` no bastan para el nuevo contrato.

## 3. Capacidad y destino de respaldo observado

| Medición de lectura | Resultado |
| --- | --- |
| `/` | **34.147 GiB libres**, 6,233,521 inodos libres. |
| Mongo | **44.828 GiB libres**, 3,276,291 inodos libres; ext4 en `/dev/sdb`, mount Mongo confirmado. |
| RAM | MemAvailable **1.11 GiB**; total **4.10 GB** informado; sin swap. |
| Docker | **5.792 GB** utilizados, 12 imágenes/11 activas. |
| Preflight `--dry-run` | Aprobado, **sin downloads**; no atestigua rollback/procedencia. |

No hubo cleanup ni resize. Antes de cada pull futuro, incluso rollback, revalidar
mínimo 5 GiB libres en raíz y headroom de las imágenes seleccionadas; Mongo/RAM se
miden aparte, sin inventar un umbral o convertir estas mediciones en permiso de
operación. Repetir después del download/despliegue autorizado.

**Bucket existente verificado:** `gs://zeler-platform-backups`, `US-CENTRAL1`,
STANDARD, uniform bucket-level access activo y soft-delete de 7 días, sin CMEK
explícito, **cifrado predeterminado Google-managed**. Lectura IAM del bucket y proyecto: sin `allUsers`/`allAuthenticatedUsers`
(cinco bindings en bucket); no se cambió IAM. UBLA por sí sola no
habría probado privacidad: se comprobó además esa ausencia de permisos públicos.

**Objetos exactos propuestos para C, no escritos:**

- `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/history.archive.gz`
- `gs://zeler-platform-backups/mongo/zelerdata-history-aeefe993-20261003T050702Z/manifest.json`

Archivo de tránsito 0600, manifiesto sanitizado/hash/inventario, permisos mínimos
existentes. Propuesta de retención: siete días tras aceptación/rollback; borrado
requiere permiso separado, no activar cron de prune ni modificar lifecycle.

No ejecutar el cron existente como atajo: incluye borrado de objetos viejos y un
dump concurrente sin demostrar consistencia. El objeto real del cron usa
`mongo/YYYYMMDD/backup-HHMMSS.archive.gz`; el destino se identifica por nombre
exacto en la aprobación futura, no por un ejemplo genérico ni un comodín.

### Metadata final 05:13:42 UTC y límites de operación

Mongo **rs0 writable PRIMARY**. 22 namespaces exactos: 20 presentes/2 ausentes;
ningún job con `policy_authority` (count 0), **no prueba rollback compatible**.
Conteos estimados de lectura: orders: 9,953; questions: 271; shipments: 2,443; claims: 44;
messages: 40; items: 1,927; proyección item: 2,912; índice SKU: 2,944; receipts: 29,653;
recovery jobs: 4,192. No filas/cuerpos/PII exportados. Índices/validator hashes
capturados en evidencia privada, no aplicados.

Drift de índices: plan existente solo `_id`, faltan
`uniq_sheets_history_plan_seller`/`onboarding_due`; receipts sin
`history_receipt_seller_scope`; pending records y Full operations aún ausentes.
**D propuesto** contempla únicamente cuatro archivos C3:

- `infra/mongo/indexes/sheets_history_backfill_plans.json`
- `infra/mongo/indexes/sheets_history_receipts.json`
- `infra/mongo/indexes/sheets_history_pending_records.json`
- `infra/mongo/indexes/sheets_full_operations.json`

Su aplicación/creación requiere autorización D e inspección de conflictos,
preserva índices existentes/colecciones y no incluye validators como health
check ni reparación automática del drift. Selected preflight con
`REQUIRE_DIGEST_BINDING=1` y servicios `gateway,sheets-api,sheets-worker`,
`--dry-run`: PASS, referencias pinned; sin download ni evidence write.
Procedencia real de running images se verificó aparte, no por ese dry-run.

Cloud Run `zeler-bootstrap`: últimas 10 ejecuciones observadas tienen
completionTime y runningCount 0 (más reciente 2026-09-25). Es consulta **acotada**,
no prueba global de cero jobs activos ni quiescencia futura. Revalidar/drainar
antes de C, incluido cualquier escritor no visto en ese límite. Trust SSH
config y ambos knownhosts conservan hashes, sin cambios.

## 4. C autorizado: corte abortado por parada manual no lograda; sin respaldo

**Estado vigente: abortado por error de nuestro procedimiento de pausa; C no
completado.** No es limitación externa: se envió TERM al child, no una parada
manual Docker que suprima el auto-restart; falló quiescencia y abortó seguro.
La excepción de capacidad **solo para la VM aislada COS** y la envoltura tar.gz
selectiva/whitelist-manifest se autorizaron después del bloqueo inicial19:31:49.
No cambia la regla de producción. Mongo7 quedó listo en el destino; no es restore.

| Destino C preparado | Evidencia observada |
| --- | --- |
| VM | `zelerdata-restore-aeefe993`, ID `190812944583158189`, `zeler-platform-dev`/`us-central1-a`; privada `10.128.0.3`, sin IP externa ni service account. |
| Recursos históricos | e2-standard-2/8GiB,30GiB pd-balanced; COS `cos-stable-121-18867-624-2`, Docker27.5.1 preinstalado. Activos en esa fase; VM/disco ya eliminados al abandono del goal. |
| Aislamiento | Host ingress SSH/IAP restringido, egress host bloqueado excepto loopback/establecidas/metadata/DHCP; sin apps/workers/OAuth. Trust nuevo atestiguado por serial GCP en knownhosts dedicado. Los dos resets de setup anteriores fueron solo del destino. |
| Mongo listo | Imagen oficial `mongo@sha256:43fddee7e532a920f3dfdee9e8f4834398c155c26bcb92d790cc1cd3c630fc40`, identidad config verificada; loopback27018/rs0 **PRIMARY**. Sin base de restore/datos de negocio. |
| Filesystems | Docker, Mongo, backup y temporales en `/dev/sda1` ext4 **RW persistente**, no rootRO ni tmpfs. Bind de temporales mode01777 corrigió salida inicial de Mongo, sin OOM. |

Capacidad destino **19:55:20 UTC, antes del corte**:25,588,756,480bytes libres,
1,669,597inodos libres, MemAvailable7,795,429,376bytes.
Después del aborto **19:59:33 UTC**:25,588,703,232bytes libres,
1,669,596inodos libres, MemAvailable7,798,353,920bytes. Cumple piso5GiB más
working-set3,424,519,418bytes = **8,793,228,538bytes requeridos**.
**La capacidad dejó de ser el bloqueo vigente.** No se hizo build/reemplazoOS.

### Resultado de la única ventana; abortada, inválida para upload

- Corte inició **19:56:36.104233 UTC**. Dispatcher detenido manualmente por TERM.
- TERM al child uvicorn de Sheets API produjo **auto-restart Docker a
  19:56:38.581673 UTC**: shell `sh -c` sin exec y política `unless-stopped`.
  No quedó parada de API verificada; grace60s expiró: **`cut_failed`,
  `grace_exhausted`, `valid_for_upload:false`**.
- Dispatcher reanudado en el mismo contenedor a**19:57:38.268277 UTC**, ~62.164s
  desde inicio. API running/ready; worker y gateway **nunca se pausaron**.
  Sin hardkill, purge ni cambio de config/restart policy.
- **No dump, archive, manifiesto de backup, objeto GCS ni restore.**
  El prefix GCS exacto fue verificado sin objetos a19:59UTC; backups previos y
  retención intactos, no se aplicaron holds. Watchdog `completed:true` cierra
  recuperación automática de esta ventana; **no segundo corte automático**.

Baseline Sheets13/6/BSON
`5835d17343c33286f5d0261c724aacf159e5cd786d5e7befb3bfb07348c72c95`
y siete clientes exactos confirmados tras corte; preimagen13 privada fuera del
payload. Once contenedores originales running:10healthchecks healthy/Caddy
running; API **restart1**, restantes restart0, todos OOMfalse/imágenes sin cambio.
Readiness API/gateway/worker200 a19:57:56→58 y tras asentamiento19:59:42→44,
incluidas comprobaciones de consumidores worker. Dispatcher también200 ready:true (Rabbit/Mongo OK). No prueba de restore/piloto.

| Capacidad fuente | Raíz libre / inodos | MongoFS libre / inodos | RAM disponible |
| --- | --- | --- | --- |
| Preparación19:43:37 UTC, no instante exacto del corte | 36,683,689,984bytes /6,233,519 | 48,136,732,672bytes /3,276,291 | 1,196,188kB |
| Tras aborto19:58:53 UTC | 36,682,416,128bytes /6,233,565 | 48,136,511,488bytes /3,276,285 | 1,675,476kB |

Evidencia privada persistida:15archivos originales y suplemento, con
`stage-c-result.json` en
`/Users/eduardoramirez/Library/Caches/zeler-operations/c-20261003/evidence/`,
SHA256 del recibo
`ed2a9ee255f1f40d668a651d5f9afddfb58caa3636bc9f966ce4a8dbea7c46e5`.
No copiar logs raw/PII al repo. Los292,965,492bytes en directorio backup del
target son **tar.gz de la imagen oficial Mongo**, no respaldo de negocio.

Target conservaba únicamente administración/config/Mongo local sin restoreDB.
La condición autorizada de eliminación después de restore exitoso/evidenciado
**no se cumplió en esa fase**: VM/disco entonces no eliminados, costo activo.
La autorización posterior del goal permite limpieza al completar restore o
abandonar definitivamente: solo targetVM/disco identificados, evidencia fuera,
no GCS/productivo. Ese abandono **ya se ejecutó** bajo el goal, identidades y
verificación de ausencia en la actualización actual; no queda este target activo.

### Siguiente paso mínimo propuesto; no nueva ejecución

Validar operacionalmente una parada Docker **manual**, exactcontainerID,
TERM/timeout=-1 bajo supervisión pendiente, seguida de TERM verificado al child;
no hardkill ni cambios de restart policy. Es propuesta para evitar que Docker
trate child exit como crash; **no comportamiento ya probado ni autorización de
otro corte**. Requiere validación operativa acotada y decisión de nueva ventana
limitada, con watchdog/stop-grace/no escritores comprobados. Si no se consigue,
abortar sin dump/upload. No builds, deploys, piloto, Full ni commit/push.
Referencias operativas: [Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/)
y [restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/);
DockerServer29.4.1 y CLI con --signal/--timeout verificados; **no prueban** la
ruta pendingmanualstop en el daemon productivo. Evidencia suplementaria privada
conservada sin alterar SHA del recibo original.
Ensayos locales acotados snapshot6/cut8fixtures no sustituyen esa verificación
runtime; no se repitió la suite general.

### Procedencia y ausencia de jobs durante preparación; no prueba de corte

Inventario fuente19:24:41, baseline19:25:09 y comprobación adicional19:26:53 UTC:
los nueve árboles Python/hash y core completo coinciden con sus fuentes;
se muestran prefijos de commits identificados, no nuevos commits fuente de build.

| Actor | Archivos .py / fuente verificada |
| --- | --- |
| Gateway | 73 / `b835791` |
| Sheets API y worker | 120 cada uno / `17c30` |
| Bootstrap dispatcher | 127 / `6d8ad764` |
| Autoreply worker / Repricer worker | 38 / 40, `13d422a` |
| Autoreply API / Repricer API / Publicador API | 37 / 39 / 48, `d2e4c38` |

Cloud Run job **`zeler-bootstrap` solamente**:34ejecuciones inventariadas, todas
finales; no afirmación sobre todos los jobs/regiones. MongoJobs14 por estado:
2succeeded/12failed. La afirmación previa Schedulerus-central1:0 se corrige: **API Scheduler
deshabilitada**, comprobado por enabledservices, sin habilitarla ni inferir lista
vacía. Reconcile service/timer loaded/inactive.
22namespaces:20presentes/2ausentes (`pending_records`/`full_operations` con nombres
completos del inventario), sin TTL. `currentOp` Mongo sobre la DB observada a
19:30UTC:0 operaciones; **no garantiza un corte futuro ni quiescencia continua**.
Producción al cierre19:33:43UTC: `/`36,684,775,424bytes libres y
Mongo48,137,003,008bytes libres; MemAvailable1,290,816kB medido en preparación.
Sin limpieza/resize. Baseline BSON5835d…13/6 y hashes de siete clientes exactos
intactos; once contenedores originales conservan image IDs/StartedAt/restart0/
OOMfalse: nueve apps y Mongo healthy, Caddy running sin healthcheck.
Mount destino19:33:42UTC: `/` en `/dev/dm-0`, ext2 **ro,relatime**; Docker
`/dev/sda1[/var/lib/docker]`, ext4 **rw**. En esa primera preparación aún no se había cargado ni restaurado; estado
posterior de Mongo/corte arriba.

**Formato selectivo autorizado, diseño aún sin backup producido:**22namespaces
positivos,20BSON+metadata correspondientes, JSON sanitizado del corte y manifiesto
SHA/whitelist, dos ausencias explícitas. Envoltura **tar.gz** con pathname acordado
`history.archive.gz`, **no native archive Mongo**. Admitir exclusivamente payload
positivo aprobado; verificar hashes/inventario y usar lector de restore correcto,
sin todaDB/OAuth/secretos ni preimagen de registro. La ventana fallida no genera
backup válido; corte `valid_for_upload:false` **no se sube**. Nunca cron fulldump/prune.

**Repoll global posterior:** cuatro jobs Cloud Run de us-central1 inventariados,
todas sus ejecuciones completas; no asumir quiescencia continua por esa lectura.
Pausas graceful/stream cero escritores durante una nueva ventana siguen pendientes.

### Inventario mínimo exacto: 22 namespaces

Origen observado desde VM: base `zeler_platform_prod`; **20 colecciones presentes,
2 ausentes** (`sheets_history_pending_records`, `sheets_full_operations`). Capturar
conteos, índices/validadores y estado de ausencia a ese corte. Ausente no significa
no requerida, no autoriza borrar una colección creada después ni afirmar que
se restauraron datos inexistentes.

| Grupo | Colecciones seleccionadas, sin comodines |
| --- | --- |
| Hechos canónicos | `orders`, `questions`, `shipments`, `claims`, `messages`, `items`. |
| Proyección de órdenes/SKU | `sheets_item_formula_rows`, `sheets_item_sku_index`. |
| Histórico | `sheets_history_backfill_plans`, `sheets_history_acquisitions`, `sheets_history_receipts`, `sheets_history_order_ranges`, `sheets_history_pending_records`. |
| Recovery/admisión | `sheets_formula_recovery_jobs`, `sheets_formula_recovery_admission`. |
| DEVOLUCIONES | `sheets_devoluciones_operations`, `sheets_devoluciones_runs`, `sheets_devoluciones_run_windows`, `sheets_devoluciones_certificates`. |
| Freshness | `sheets_read_model_freshness`. |
| Full | `sheets_full_operations`, `sheets_full_withdrawals`. |

`items` y ambas proyecciones son necesarias para joins/SKU de la tabla ORDENES;
no restaurar solo sus filas y llamar legible el producto. Este mínimo no es
copia de toda la base. Validar antes del dump las herramientas/proyección y el
contenido del archivo: exclusivamente estas 22 colecciones, sin exportar toda
la base como paso intermedio. **Excluir OAuth, `meli_accounts`, tokens, identidades, secretos**;
no reutilizar cuentas/token de producción en restore. Compose/config seleccionado
se conserva por separado privado/cifrado: imágenes, dependencias, flags aprobados y
scopes/routing. No exportar archivos env/cadenas/tokens ni configuración completa
que pueda contener secretos bajo la apariencia de un manifiesto.

### Writers concretos y gate de consistencia

Mapeo estático de escritores de estas 22 colecciones:

| Actor a delimitar en C | Alcance; resultado actual arriba |
| --- | --- |
| `sheets-worker` | Pausar todos sus pollers/consumidores con ACK/NACK y parada graceful; preservar leases/jobs y entregas Rabbit. |
| `sheets-api` | Pausar admission/recovery y publicación de pendientes parciales del conjunto seleccionado. |
| `bootstrap-dispatcher` / jobs Cloud Run bootstrap | Detener lanzamientos y esperar jobs iniciados: escriben orders/claims y derivados DEVOLUCIONES operations/freshness/invalidation de certificados. Repoll antes del corte. |
| Gateway actual b835791 | Árbol73/core verificados: no escribe las22colecciones ni admite histórico nuevo. No hay admisión histórica que pausar para C con dispatcher detenido; no crear control/config ni parar gateway. Hold de admisión del gateway C3 es gate de D/E, no de este baseline. |

No se encontró escritor directo de ese conjunto en los otros cinco servicios
activos de producto según mapa estático; **no es permiso para pararlos** ni prueba
absoluta de quiescencia runtime. Fuente desplegada de esos actores fue verificada durante preparación. Los jobs
observados terminaron; revalidar/drainar cualquier nuevo job justo antes del corte. La ausencia de
esos jobs no se supone porque el dispatcher esté detenido. Si falta esa prueba de cierre de writers/jobs, C no puede asegurar consistencia
y no empieza el dump. Al
retomar C hacen falta pausas graceful y repoll Cloud Run/stream de cero writers
durante la ventana real: inventario/currentOp puntuales no cierran esos gates.

**Ventana C autorizada: máximo15 minutos**, delimitando corte y reanudación. Docker
actual informa StopTimeout:null (default 10s); no se declara suficiente para
cleanup del worker. Override futuro explícito de stop grace 60s para los tres
servicios seleccionados (p.ej. stop timeout aprobado), timeout externo SSH≥120s;
es propuesta bajo C, no configuración ya cambiada ni prueba de que terminará en 60s.
Verificar salida/ACK/NACK/cero escritores antes del dump. Si un job sigue activo,
vence ventana/grace o no hay quiescencia, detener esta etapa sin dump inconsistente,
hardkill/purge, ampliación automática ni afirmar backup listo. Reanudar únicamente actores autorizados y verificar baseline/salud/capacidad.

**Baseline C actualizado: 13 scopes/6 keys compatible y salud confirmados.**
La propuesta anterior de restituir14 tras restart está **supersedida**: recrearía
mismatch/503. Código17c30 ejecuta register_startup→register_module→replace_one y
registra su manifest13/6. Capturar snapshot privado vigente13/6 antes del corte C;
la preimagen forense14 no sirve como baseline. Mantener13 al reanudar sin ampliar
a15 ni restaurar cuentas/OAuth, comparando todo el registro y demás clientes:
que scopes coincidan no autoriza otras sobrescrituras de startup. C no concede
escrituras de registro ni restauración automática. Si hace falta otra escritura
u hold no verificado, delimitar y aprobar ese delta; no SIGSTOP. La reparación
estrecha concluyó sin restart; C después abrió un corte abortado por grace/parada
de API. Capacidad destino y Mongo listos; backup/restore/consistencia no demostrados.

El destino existió bajo C y Mongo/capacidad se verificaron; backup/restore y
consistencia nunca se completaron. El único C del goal posterior falló y
VM/disco ya se eliminaron al abandono: no hay destino aún disponible ni segundo
C permitido. No es permiso para nuevas modificaciones productivas.
Hash/conteos, índices/validadores,joins,cobertura/certificados/lectores y
preservación en origen de hechos posteriores al corte acreditan el restore;
no basta `mongorestore` exit 0. No ejecutar restore de aceptación sobre producción.

## 5. Rollout bloqueado por rollback de versión; retirada operativa distinta

**Propuesta histórica C3/15, supersedida:** los tres digests C3 construidos/verificados de §1.
Son compatibles por fuente local con el contrato de 15 scopes/6 keys/fingerprint
`bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d` y separación
`policy_authority`, **no prueba de estabilidad productiva**. Deben verificarse
tras cualquier despliegue autorizado, con onboarding inicialmente apagado. El
goal actual requiere nueva fuente/builds de contrato14/sinFull; aún sin SHA/digests
publicados. No aplicar el contrato15 ni reutilizar esos tres builds como destino actual.

**Rollback de versión seguro no identificado/atestiguado.** Gateway anterior
se conserva con identidad verificada, pero el conjunto previo no es compatible:
API/worker sin `policy_authority`; API13/6 ya está sana, pero eso no prueba
compatibilidad con estado nuevo. No tratar las mismas
tres imágenes nuevas como rollback de versión. D **permanece bloqueado** hasta
seleccionar y autorizar/atestiguar una alternativa segura y recuperable con ese
contrato, incluida su procedencia y comportamiento/registro. Si requiere build
extra, pedir permiso específico: A ya terminó, no cubre una cuarta imagen.

**Retirada operativa propuesta, NO rollback de versión:** desactivar onboarding
mediante cambio/restart estrecho del worker autorizado, esperar la unidad activa
con su stop grace, conservar los tres digests C3 nuevos y jobs/hechos/checkpoints.
Sirve para detener adquisición piloto sin ejecutar legacy por otra autoridad;
no deshace una regresión del código nuevo. No bajar scopes a 13, borrar jobs,
restaurar toda Mongo o usar una imagen antigua para fabricar compatibilidad.
Esta retirada también es mutación y no se ejecutó con A/B.

### Alternativa mínima concreta de rollback de versión — propuesta histórica supersedida

La propuesta anterior de dos builds API/worker desde C1
`4216e18b62da289c1e67acd1ac8d6db4ba0c9217` se conserva como antecedente,
**no se recomienda ejecutarla ni es el siguiente permiso necesario**. Comparación
local C1/C3: manifest/recovery/recovery_worker/history_onboarding son idénticos;
la diferencia ejecutable está en cuatro archivos de Full (collector y tres tests),
no en una reversión más amplia de onboarding.
C1 comparte onboarding con C3: no retira una regresión general de onboarding.
Con Full 0, reconstruir C1 no aporta esa reversión y sí omite el fix inventory_id.
No se construyeron esos candidatos ni existen sus digests nuevos.

**Plan mínimo antes del piloto, condicionado a prueba de ausencia/aislamiento:**
conservar los tres digests previos verificados de §2 como conjunto candidato,
configuración privada y baseline compatible13/6 confirmado tras reparación.
Solo considerarlos para retirada **antes de crear/admitir estado nuevo**, si se
comprueba ausencia de planes/jobs/runs/proofs con `policy_authority` y otros datos
nuevos incompatibles, o aislamiento completo demostrado de las lanes antiguas.
El count histórico de cero jobs no demuestra esas condiciones. El planner 17c30
puede ver planes nuevos sin guard de autoridad, **incluso con flag onboarding OFF**;
el gateway actual no admite histórico, pero el gateway C3 sí requiere delimitar
esa admisión como gate D/E;
ni flag OFF ni worker healthy bastan para usarlo. Full seguirá 0; no reactivar su
adquisición legacy. La compatibilidad de schemas, registro, colas/consumidores y
configuración debe atestiguarse antes de presentar D ejecutable. Los tres digests
previos son candidatos condicionales, no rollback seguro ya validado. Si esas
condiciones no se prueban, recuperación forward incluso antes del piloto.

**Después de admitir estado del piloto: recuperación hacia delante.** Detener
admisión/onboarding mediante hold explícito y flag OFF por operación estrecha
autorizada, conservar jobs/hechos,
cuotas/cutoff/checkpoints/proofs y el worker consciente de `policy_authority`.
No ejecutar el worker 17c30 ni bajar registro a13 sobre planes nuevos, no hacer
restore ciego de Mongo ni borrar estado para aparentar rollback. Ante una regresión
de código, preparar corrección forward y su build/rollout con permiso separado;
si se exige rollback de versión postpiloto, falta identificar y demostrar una
alternativa que excluya esa regresión y respete el nuevo estado. **D/E siguen
bloqueados por esa garantía antes de operar**, no por falta de los dos builds C1.
Este plan histórico no amplía permisos. El goal posterior sí autoriza únicamente
sus imágenes/operaciones seleccionadas, condicionado a gates; ninguna ejecutada
por esta actualización documental. Hold de admisión y pausa persistida de ejecución
son controles locales nuevos, no disponibilidad productiva acreditada.

## 6. Piloto E sigue separado

Solo HOPEMOB 82453304 legítimamente linked, cinco fuentes/**Full 0**, hasta 2,000
GET iniciales + 500 mantenimiento (≤300 por fuente), 90 minutos dentro de un día
UTC; preserve cutoff/consumed/checkpoints y períodos sanos, dos cambios reales
con lectura normal. API parcial debe conservar aviso; smoke nativo exacto aparte,
opt-in parcial del complemento sigue sin implementar/disponible en Sheets.

C está autorizado y bloqueado tras corte abortado: backup/restore no realizados;
D/E están autorizados por goal, pero no ejecutables hasta ensayo completo, respaldo
restaurable, fuente/digests nuevos y recuperación compatible; E además exige rollout
sano. A/B por sí solos no autorizaban reparar API, aplicar scopes/índices,
backup, restore, pull, deploy, activación ni Full. Investigación Full cerrada,
ninguna consulta restante ni programación.

## Referencias

El [recibo histórico C1/C3](zelerdata-historico-publicacion-20261002.md) indica
"sin builds" respecto del alcance de esas publicaciones anteriores. **Este
recibo A/B registra el estado actual: tres builds ya ejecutados/verificados.**
No se modifica el recibo histórico ni se confunden esas fases.

- [Fuente y publicación C3](zelerdata-historico-publicacion-20261002.md).
- [Informe local](zelerdata-historico-al-vincular-implementacion.md).
- [Full cerrado](zelerdata-full-validacion-acotada.md).
- [Build/procedencia/preflight](../deploy.md).
- [Cron backup](../../infra/mongo/backup/README.md) y
  [restore histórico](../../infra/runbooks/mongo-restore.md).
