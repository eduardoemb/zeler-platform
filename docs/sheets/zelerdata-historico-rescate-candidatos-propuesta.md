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

**Resultado actual:** auditoría terminada con exit 1, sin reintento:
driver 00:22:46.970145 → remoto 00:22:51.580957 → stop 00:22:58.447630 UTC.
Selector ejecutado realmente en Python del host 3.10: inventario pasó;
identidad de los 41 miembros/20 presentes, directorio, raíz 0700, mount persistente
y bind verificados; snapshot SHA `04ba58489709081a57cfe777b078e5b3322ac4297442080f1b94b140d74b1136`
coincidente. Se completaron exactamente 16 miembros, incluido el snapshot, hasta el BSON de
run_windows (8 registros);
su metadata falló `readonly_subcommand`. **La auditoría no pasó: B–F no ejecutables
por esa vía y candidatos no aceptados ni declarados corruptos.**

Diagnóstico único posterior, separado del intento y sin reanudar la auditoría:
metadata auténtica con claves collectionName/indexes/type/uuid, índice 1, 198 bytes;
Tools omite `options` cuando está vacío. El diagnóstico propio exigía `options:{}`
presente; RED sintético reprodujo el fallo al omitirlo. Corrección local del
procesador privado: siete pruebas sintéticas pasadas, SHA
`61b04f3ea4a2873b8cdc73218acc072077e8a84fdcf2bd44aa29350f95dbb021`;
acepta omisión solo si el hash del corte corresponde a opciones vacías y rechaza
omisión si se esperaban opciones no vacías. No prueba de contenido real ni nueva
auditoría ejecutada.

**No se ha demostrado que los candidatos sean inservibles.** Falló el diagnóstico
propio: «no aceptados» no activa automáticamente la alternativa de corte. No se
iniciará otro corte ni se creará destino bajo esa condición sin acreditarla.
La auditoría original quedó detenida; su no-reintento impide reanudarla con la
corrección bajo el alcance actual. Si resulta necesaria, identificar una única
ampliación concreta para reanudación acotada, no otro corte por costumbre.
Controles locales completados con los resultados finales de abajo. Respaldo recuperable,
restore real, despliegue y piloto pendientes. Evidencia privada:
`rescue-20261004T002229Z`, sin datos sensibles en estos informes.
**Controles locales finales verdes:** full Linux **5,946 passed/9 skipped, 425.84 s, exit 0**, 2026-10-04 00:54:46.140710→01:01:54.421494 UTC (helper 428.281 s). Los ocho tests broker pasaron integrados; ocho skips por guard ambiental Mongo quedan cubiertos por protected Linux **8 passed/2.08 s**; el noveno es Caddy sin requiredkeys, caso intencional. 1,053 hashes/modos intactos de fuente dbf, lock intacto, OOM 0; Ruff/formato/mypy verdes (653 fuentes). No sumar los lotes protegidos al total ni convertir calidad local en aceptación productiva.

**Intentos anteriores, históricos:** macOS 12 failed/5,926 passed/17 skipped (481.44 s), sin Mongoerrors; fallos baseline Bash3.2/BSDstat. Primer Linux 18 failed/5,928 passed/9 skipped (417.96 s), entorno incompleto: Node/Git ausentes y zombies State Z/PPid1 por PID1 Python sin init. Entorno efímero corregido con Node18.20.4/Git2.39.5 y `--init`; exactos 18 passed/3.70 s y protected ocho passed/2.08 s antes del full final. La repetición completa fue justificada por entorno invalidado, no por costumbre. Sin modificación de código ni nuevos builds. Limpieza local completada 2026-10-04 01:05:11.228918 UTC: únicamente seis contenedores/seis volúmenes/perfil propios; perfiles anteriores Stopped y contexto colima preservados. Índice de 41 evidencias SHA `29cbef2c2638e31d66aa62191f28d6f84cec44fbb942fcbcd39491ba9df1486f`; cleanup SHA `ca0b70e3112fae194b1dcff6f6dd49f4e18d8ccd50b0f7414050daa25b88ec02`. Evidencias privadas fuera del repositorio:
`/Users/eduardoramirez/.codex/cache/zeler-local-mongo-gate-cb6c288527f9/verification-receipt.md`
y `evidence-index.json`; sin credenciales en los recibos.
La publicación del selector (`dbf84928167c1ea66113d9005440e201eeb1566e`) no
cambia las fuentes runtime d78 ni exige nuevos builds por sí misma. Las mediciones,
restricciones de permiso y fallos anteriores se conservan abajo como **históricos**:
las frases «autorización futura», «única solicitud» o «no autorizado» describen su
momento anterior y quedan sustituidas por esta ampliación, no son gates nuevos.


**Los candidatos no son un respaldo aceptado ni se acredita que sean recuperables.**
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

## 1. Ubicación e inventario: comprobación limitada de auditoría fallida

Origen: `platform-vm`, proyecto `zeler-platform-dev`, zona `us-central1-a`.
Ruta registrada: `/var/lib/zeler-mongo/.zelerdata-c-new-20261003T214827Z`;
el bind Mongo la presenta como `/data/db/.zelerdata-c-new-20261003T214827Z`.
La auditoría de 00:22 revalidó directorio/mount/bind e inventario; no completó
los 41 miembros ni la comparación de contenido, y no acredita un respaldo. El
inventario detallado de bytes siguiente conserva su timestamp histórico.

| Payload positivo previsto | Inventario registrado 22:08:45.008384 UTC |
| --- | --- |
| BSON de 20 colecciones presentes |20 archivos,171,406,662 bytes. |
| Metadata de esas mismas 20 |20 archivos,50,994 bytes. |
| Snapshot del corte |`cut-snapshot.json`;41 miembros positivos en total. |
| Auxiliar excluido |`dump/zeler_platform_prod/prelude.json`,51 bytes; claves `ServerVersion`/`ToolVersion`. Tool 100.16.0 verificado, valor auténtico de ServerVersion **no capturado**. |
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

No hay archive/manifiesto aceptados ni objetos GCS/restore. La existencia actual del
directorio se revalidó en la auditoría limitada de 00:22, **no el contenido completo**. Hashes de recibos no son hashes de BSON, y una SHA
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
  pero no autentica el valor ServerVersion real no capturado. Verificarlo en el
  archivo candidato sin consultar Mongo ni inventarlo.

Prelude solo en ubicación exacta, regular/nlink 1,≤ 4096 bytes, JSON sin claves
duplicadas/solo ServerVersion y ToolVersion 100.16.0; ServerVersion numérico de tres
partes. El fixture 7.0.12 es **sintético**, no versión productiva acreditada.
Reutilizar módulo **publicado exacto** mediante import, no copiar otro validador
en línea ni relanzar el corte privado; scripts privados antiguos permanecen forenses,
sin editar. El selector se ejecutó realmente en Python del host 3.10 durante la
auditoría y pasó inventario; el decoder de metadata falló posteriormente por
options omitido. No confundir este resultado parcial con restore ni auditoría completa.

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
