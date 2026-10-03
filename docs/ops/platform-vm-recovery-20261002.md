# Host y OAuth Mercado Libre recuperados; aceptación íntegra de ZelerData pendiente

> **Registro histórico con corte a las 16:50 UTC del 2 de octubre de 2026.**
> Los estados y pendientes de recuperación descritos corresponden a ese corte,
> no a una comprobación de salud actual. La implementación y activación
> posterior de DEVOLUCIONES multiperíodo se documentan en el
> [reporte de rollout](devoluciones-multiperiod-rollout-20261002.md).
> La nota de validación para publicación al final es posterior a este corte.

**La VM, OAuth Mercado Libre y el worker corregido están recuperados; órdenes y
preguntas tienen prueba durable del intervalo de interrupción.** La observación
posterior a 900 segundos confirmó la estabilidad de los contenedores, la cola
de eventos sin entregas pendientes y otro ciclo de preguntas completado.
Persisten el rechazo Google OAuth y límites de cobertura histórica. Este corte
llega hasta las **16:50** del 2 de octubre: no afirma recuperación íntegra ni
ausencia de pérdida de eventos.

Todas las horas son UTC. Proyecto `zeler-platform-dev`, VM `platform-vm`, zona
`us-central1-a`. Las secciones separan la recuperación del host a las **05:34**
de los despliegues del gateway a las **15:16** y del worker a las **16:14**,
el 2 de octubre de 2026.

## Interrupción e hipótesis

Los checks de disponibilidad registraron fallos desde el **30 de septiembre,
08:24**, confirmados desde cinco regiones. La VM figuraba `RUNNING`, pero SSH
mediante IAP no alcanzaba el puerto 22 y gateway/Sheets HTTPS agotaban el timeout.

| Telemetría anterior al corte | Medición |
|---|---:|
| Memoria usada, último valor | 86,49 % |
| Memoria usada, máximo observado | 90,3 % |
| Disco raíz usado | 29,55 % |
| Disco Mongo usado | 3,21 % |

La presión de memoria es una hipótesis compatible con estas mediciones y con el
[incidente previo](platform-vm-recovery-20260925.md), **no una causa demostrada**.
Los datos de capacidad anteriores al corte no establecen el estado del guest
durante toda la interrupción; tampoco identifican una fuga o proceso iniciador.

## Intervención autorizada

1. Se crearon y verificaron `READY` los snapshots
   `platform-vm-pre-recovery-20261002` y
   `zeler-mongo-pre-recovery-20261002`. Conservan ambos discos antes de la
   intervención; con el guest bloqueado no se coordinó consistencia de aplicación.
2. Se respaldó de forma privada y omitió temporalmente el `startup-script` de
   aprovisionamiento. Después se restauró su contenido exacto y se verificó
   SHA-256 `fcea43eac2bb9d76dfc8ccf043f7955415ed5b6226f020e10edf4c8cc2516373`.
   No se sustituyó por la copia distinta del repositorio.
3. Parada a las **05:27:43** y arranque a las **05:28:13** del 2 de octubre.
   Se conservaron la misma instancia, IP, tipo `e2-medium` y discos:
   `platform-vm` (`persistent-disk-0`) y `zeler-mongo-data` (`mongo-data`).

Durante esta recuperación del host no hubo imágenes nuevas, Cloud Build,
despliegue de código, limpieza Docker,
ampliación de recursos, cambios de esquema ni manipulación de credenciales.
Se preservó la configuración corregida del Ops Agent, SHA-256
`0adbcdbec15ee069c8fda852c9256e2bea9c2430ac8942e03db30f7b3c76059a`.

## Estado del host a las 05:34

| Comprobación | Resultado |
|---|---|
| Contenedores | 11 en ejecución; los 10 con healthcheck, `healthy`. |
| HTTPS | Gateway, Sheets, Repricer, Publicador y Autoreply `/health`: 200; gateway `/ready`: 200. |
| MongoDB | Writable PRIMARY; disco `/dev/sdb` montado en `/var/lib/zeler-mongo`. |
| Espacio libre raíz | 37.131.726.848 bytes. |
| Espacio libre Mongo | 48.141.529.088 bytes, en montaje separado. |
| Memoria disponible | 2.202 MiB en la observación, unos cinco minutos después del arranque del runtime. |
| Sheets AMQP | Dos consumidores, uno de eventos y otro de claims. |
| DLQ eventos Sheets | 189 mensajes listos, cero consumidores; no se consumieron ni reprocesaron. |
| DLQ claims Sheets | Cero mensajes listos. |

Esta ventana demuestra recuperación operativa del host, no estabilidad sostenida.
Una cola vacía o un `/health` correcto no demuestran cobertura de datos del piloto.

## Bloqueo funcional confirmado

La cuenta piloto estaba en `status=error` desde el **30 de septiembre, 07:00:07**,
antes de la caída del host. Su acceso expiró a las **07:10:07**; la última
renovación registrada fue a las **01:10:07**. El diagnóstico almacenado coincidía
exactamente con `Meli refresh failed with status 429`, sin necesidad de leer o
copiar tokens.

El proceso anterior cambiaba la cuenta a `error` ante ese fallo, pero las
siguientes pasadas seleccionaban solo `active` y `refresh_pending`. Después de
recuperar la VM, cuatro nuevos jobs de órdenes/preguntas —rangos de una hora y
siete días— terminaron con `source_rejected`, un intento y HTTP **412**. El gateway
rechaza una cuenta no activa antes de llamar a Mercado Libre. Los markers de
órdenes/preguntas seguían en el **30 de septiembre, 06:47**; los heartbeats de otros
modelos no prueban que se haya adquirido fuente nueva.

## Corrección OAuth desplegada

El cambio acotado en
[`refresh_worker.py`](../../gateway/src/zeler_gateway/tokens/refresh_worker.py):

- Mantiene los fallos HTTP 429/500–599 y de transporte elegibles para la siguiente
  pasada normal de cinco minutos, sin declarar activas credenciales vencidas.
- Recupera errores históricos solo cuando su diagnóstico coincide exactamente
  con el generado para 429/5xx; no reabre errores desconocidos, pausas o revocaciones.
- Revalida elegibilidad y expiración al adquirir el lock. Conserva el tratamiento
  de `invalid_grant` y de errores no transitorios; no cambia schemas ni scopes.

TDD: 12 fallos observados antes de la corrección; después,
[`test_refresh_worker.py`](../../gateway/tests/test_refresh_worker.py) pasó sus
**37 pruebas**, incluidas las de Mongo aislado con validators. Las cuatro pruebas
de lifespan y Ruff/formato/mypy focal también pasaron.

Validación raíz final en Linux aislado, con Mongo replica set y RabbitMQ de
prueba (sin datos de producción), Node y dependencias del lockfile:

- `uv run pytest`: **5.553 passed, 9 skipped**, 250,25 s. Ocho skips eran las
  pruebas rs0 que rechazan `MONGO_URI` ambiental; ejecutadas después sin esa
  variable y con `ZELER_RS0_TEST_URI` aislado: **8 passed**, 1,94 s. El skip
  restante corresponde a Caddy, sin claves requeridas aplicables.
- `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy .`:
  correctos; formato y mypy cubrieron **620 archivos**.
- `uv run python -m infra.lint.check_direct_meli .`: correcto.

La ejecución previa en macOS produjo 5.533 passed, 12 failed y 17 skipped:
los doce fallos estaban en scripts operativos sin modificar, por Bash 3.2 y
BSD `stat` incompatibles con opciones GNU. El primer runner Linux carecía de
Node; se repitió la suite completa con esa dependencia, sin excluir pruebas.
Estos gates corresponden a la corrección OAuth, no al cambio posterior del consumidor.

El gateway autorizado se desplegó a las **15:16:44** y quedó `healthy` a las
**15:16:53**, desde el commit
`b835791193506f0d32b3350e7606c8d644019114`, con digest inmutable verificado.
Digest: `sha256:8b6551451509040aed607c086f8b94ad9ce586ffee8b5ba5c9a420844337ba50`.
La renovación normal dejó la cuenta piloto `active`, renovada a las **15:16:44**
y con expiración a las **21:16**. No se copiaron tokens ni se parcheó el estado.

A las **15:45:12**, los 11 contenedores seguían en ejecución, los 10 con
healthcheck estaban sanos y todos tenían cero reinicios y `OOMKilled=false`.
Espacio libre: raíz **36.898.500.608 bytes**, Mongo **48.129.765.376 bytes**;
memoria disponible **1.458 MiB**. El preflight de capacidad volvió a pasar.
CI de ese commit gateway también terminó correctamente (`test` y `lint`).

## Verificación funcional posterior

| Superficie | Evidencia y límite |
|---|---|
| Órdenes | Cobertura durable comprobada para **30 de septiembre, 07:00 → 2 de octubre, 15:17**; no solo heartbeat nuevo. |
| Preguntas | Readbacks de las **16:30:17** y **16:32:46.731**, sin inferir cobertura desde un claim vivo: el intervalo **30 de septiembre, 07:00 → 2 de octubre, 15:17** sigue cubierto durablemente, con 224 filas comprobadas. Tres jobs completados en un intento; ninguno pendiente, en ejecución o fallido en el conjunto posterior al arranque. |
| Hoja nativa | Se preservaron las **52 fórmulas**: 42 devolvieron valores/tablas, 5 `NA` y 5 `DATA_UNAVAILABLE`. Algunas tablas contienen columnas parcialmente no disponibles; 42 resultados no equivalen a integridad completa. |
| Claims actual | Dos GET acotados por el gateway normal: búsqueda **200** y un detalle **200**. El 403 histórico no demuestra un rechazo actual. La muestra no establece reconciliación completa ni disponibilidad de todos los detalles. |

Una comprobación posterior con los parámetros del worker recibió **200** en
cinco páginas de búsqueda de preguntas, con límite 50 y total reportado 226.
El primer detalle dentro de la cobertura devolvió **404** en la sexta petición:
la búsqueda enumera una pregunta cuyo detalle ya no está disponible. La auditoría
real de la VM entre **15:29:40 y 15:29:55** confirma una búsqueda de preguntas
desde `bootstrap` con **200** y un detalle desde `sheets` con **404**, sin exponer
identificadores. La corrección de recuperación de preguntas está probada
con TDD: **7 RED** antes del cambio, **11 pruebas nuevas GREEN** y **462 GREEN**
en el archivo completo de recuperación; Ruff/formato/mypy focales correctos.
Se publicó y desplegó junto con la corrección del consumidor, descrita abajo.
La cobertura de la tabla proviene del readback posterior, no de estas pruebas.

Los jobs iniciales de una hora y siete días terminaron a las **16:16:22.535** y
**16:17:48.602**, respectivamente; ambos intervalos propios quedaron cubiertos.
A las **16:30:17**, el marker retenía cobertura desde **24 de octubre de 2025**
hasta **2 de octubre, 16:15:03.222**. El siguiente ciclo de una hora, iniciado
**16:30:04**, terminó a las **16:31:22.138**, también en un intento y con prueba
durable propia; el marker avanzó hasta **16:30:04.494**. El readback de las
**16:32:46.731** volvió a confirmar el intervalo de interrupción. La auditoría
acotada contó **15 búsquedas 200, 672 detalles 200 (224 × 3), 6 detalles 404 y
ningún otro estado HTTP**. Los 404 fueron tratados sin convertirlos en un fallo
permanente del recorrido; no se exponen identidades ni respuestas del proveedor.

Los cinco `NA` corresponden a `PAUSADAS`, `TIEMPOACTIVA`, `MEDIDAS`,
`DIASDESDEULTIMAVENTA` y `COSTOENVIOVENDEDOR`; son resultados contractuales cuya
causa depende de los datos, no prueba automática de fallo o ausencia global.
Los cinco `DATA_UNAVAILABLE` son `DEVOLUCIONES`, `CATALOGOTIEMPO`,
`TIEMPOSTOCKACTIVO`, `RETIROS` y `SEMANASCONSTOCK` (todos con prefijo `ZELERDATA_`).

### DEVOLUCIONES: conservar y acumular cobertura

La fórmula nativa solicita **8 de agosto–6 de septiembre inclusive**. El usuario
aprobó una reconciliación acotada —un dry-run y un run de tres ventanas,
máximo 832 llamadas físicas—, pero solo se ejecutó el **dry-run único**:
**16 llamadas** (6 búsquedas/páginas, 7 detalles de devoluciones y 3 órdenes),
3 esperados, 3 persistidos, 3 completos y 0 faltantes; salida correcta.
**No se admitió ni ejecutó el run productivo de agosto.**

Después del reinicio, el worker renovó una prueba vigente para
**1 de junio → 11 de junio exclusivo**, ligada a un run completado. El lector,
el finalizador y el renovador actuales dependen de un único marcador conjunto.
La comprobación de su lógica en el runtime confirmó que sustituirlo por agosto
haría perder la disponibilidad comprobada de junio, aunque sus filas y el run
anterior permanecieran guardados. Se detuvo la escritura; no se declaró una
unión que cubriera el hueco no adquirido.

El usuario aclaró y autorizó el resultado requerido: **acumular coberturas para
cualquier período anterior o posterior, conservando las ya comprobadas**, y
permitió posponer ese cambio hasta recuperar la operación. No debe ofrecerse
como una elección entre perder junio o recuperar agosto. El diseño seguro
necesita pruebas por intervalo con procedencia, validez, invalidación y control
de concurrencia; un `run.completed` por sí solo no demuestra vigencia actual.
El cambio multiperíodo **no está implementado ni se ha iniciado SDD**. La
reconciliación de agosto permanece detenida para preservar junio.

Las otras cuatro fórmulas no disponibles dependen de historia importada y
carecen de markers válidos; esto no autoriza fabricar datos ni declarar
completos períodos que no fueron adquiridos.

### Google OAuth: fallo todavía sin causa confirmada

El worker recibió **HTTP 400 durante la renovación Google**, antes del append.
No hay evidencia de `invalid_grant`; no se debe atribuirle ese diagnóstico.
La configuración requerida está presente, coincide entre API y worker y no
contiene placeholders conocidos, pero esa igualdad no demuestra que Google
acepte las credenciales. El diagnóstico acotado se implementó con TDD y quedó
sin publicar en dos archivos:
[`google_oauth_refresh_diagnostic.py`](../../infra/operations/google_oauth_refresh_diagnostic.py)
y [`test_google_oauth_refresh_diagnostic.py`](../../tests/test_google_oauth_refresh_diagnostic.py).
Hash SHA-256 del módulo usado en las primeras dos invocaciones:
`cd0521f8050b5e231a1fa33d4f39f9ae8ea2b3a09317d419578e4ff3fad9a6b8`.

La invocación única autorizada a las **16:30:57** terminó con código de proceso
**2**, `precondition_refused`, HTTP `null` y sin código de proveedor:
**no hizo un POST a Google ni escribió tokens**. Un readback a las **16:32**
mostró que solo había cambiado `metadata.updated_at`, de **16:15:36.410** a
**16:28:57.536**, por actividad normal del worker. El HTTP 400 esperado y la
expiración del 30 de septiembre no habían cambiado. Esta negativa de seguridad
no diagnostica la causa del rechazo Google. No se reintentó automáticamente.

El usuario autorizó por separado una nueva invocación única con precondiciones
actuales. Ejecutada a las **16:34**, realizó **un POST a Google** y terminó con
HTTP **400**, `oauth_category=other`, `result=refresh_failed`, `status=error` y
código de proceso **1**. El almacenamiento normal registró el error mediante
`mark_error`; no se obtuvieron credenciales nuevas ni se cambiaron client secret,
permisos o configuración OAuth. La primera invocación conserva su resultado:
fue rechazada antes de llamar al proveedor y no consumió un POST.

`other` **no identifica la causa**: puede representar un código no incluido en
la lista de categorías permitidas, una respuesta no JSON o un campo ausente.
No demuestra `invalid_client`, `deleted_client` ni `invalid_grant`.

Se corrigió localmente la clasificación con TDD: seis códigos documentados
adicionales y etiquetas fijas para respuesta no JSON, error ausente, tipo
incorrecto y código desconocido. Se conservaron los cuatro campos de salida,
las precondiciones y el máximo de un POST por invocación. Hash verificado:
`aa00f845d6d25f15a3728cdb4959ed9824f69ea125ed5f5baecc277daa73a938`.

El usuario autorizó explícitamente una **última ejecución** después de repetir
todos los controles. A las **16:48**, con metadatos recién leídos, hizo un POST
y devolvió HTTP **400**, `oauth_category=unknown_error_code`,
`result=refresh_failed`, `status=error`, proceso **1**. Esta clasificación indica
un campo de error textual fuera de la lista permitida, pero **no identifica la
causa**. No se reinterpretó retrospectivamente el `other` anterior.

Se detuvieron los intentos conforme al límite del usuario: tres invocaciones,
**dos POST en total**, sin acceso renovado. Solo se utilizó el almacenamiento
normal del estado de error; no se cambió cliente OAuth, secretos ni permisos.
No se imprimieron valores de entorno, respuestas completas ni tokens.
Las versiones habilitadas en Secret Manager y la coincidencia de formato y
proyecto del client ID no prueban que el cliente siga activo ante Google.

Verificación local del diagnóstico, independiente de la imagen worker ya desplegada:

- Primera versión: 32 pruebas focales y 5.599 generales correctas, más ocho rs0.
- Clasificador ampliado: **16 RED → 39 nuevas + 7 de almacenamiento GREEN**.
- Runner Linux final con Node y `tini -s`: **5.613 passed, 9 skipped** en 252,86 s;
  las ocho pruebas rs0 protegidas corrieron después con entorno aislado:
  **8 passed** en 1,82 s. Solo permanece el caso Caddy no aplicable.
- Ruff check, formato y mypy completos (**622 archivos**) y lint de acceso
  directo a Meli: correctos.
- El runner anterior carecía de Node y subreaper: produjo 14 fallos asociados a
  Node y dos de limpieza de procesos. Se corrigió el entorno y se repitió toda
  la suite; esos fallos no se ocultaron excluyendo pruebas.

Estos resultados no equivalen a aceptación Google ni a un despliegue del nuevo
instrumento: el módulo y sus pruebas siguen sin commit en este corte.

Se retiraron los tres contenedores de prueba creados para esta validación y se
detuvo su perfil Colima aislado. Se preservó el perfil predeterminado; la
limpieza no incluyó contenedores, volúmenes ni datos de producción.

## Bloqueo del consumidor y corrección desplegada

Después del despliegue del gateway, la cola de eventos mantenía **81 mensajes
listos y 10 sin ACK**, con un consumidor; no había nuevos `processed_events` de
Sheets desde las **15:16:44**. Los logs del arranque mostraron **10 excepciones
de callback y 10 de tarea por HTTP 412**. La DLQ de eventos seguía en 189; la
DLQ de claims estaba vacía y su binding comprobado.

En `consumer.py`, el 412 escapaba desde el bloque `except HTTPStatusError`, sin
ACK ni NACK: las diez entregas ocupaban todo el prefetch aunque OAuth se
recuperara después. La conexión y suscripción podían seguir `ready`; el ciclo
de recuperación de 900 segundos no libera esas entregas.

La corrección desplegada usa el mecanismo existente de reintento demorado para 412,
incrementa el contador, conserva el presupuesto de cinco intentos y confirma la
publicación antes del ACK. Si publicar falla, conserva el original mediante
requeue. Los HTTP no clasificados terminan explícitamente en DLQ en vez de
escapar; se preserva la clasificación existente de los demás códigos.

TDD observado: **10 RED** antes del cambio, **32 GREEN** en el archivo enfocado
y **56 GREEN** con regresiones de consumidores. Ruff/formato/mypy focales y
`git diff --check` pasaron. Los gates raíz Linux finales, con ambas correcciones
del worker y Mongo/RabbitMQ aislados, terminaron con **5.574 passed, 9 skipped**
en 254,67 s. Ocho skips protegidos de rs0 se ejecutaron después con su variable
específica: **8 passed** en 1,95 s; solo queda el caso Caddy no aplicable.
Ruff, formato, mypy completo de 620 archivos y lint de acceso directo a Meli
pasaron. Una ejecución previa sin broker disponible se repitió completa; sus
ocho skips de AMQP no se tomaron como aceptación. CI del commit del worker
también pasó: `test` 37030166145 y `lint` 37030166243.

### Topología y despliegue acotados autorizados

La cola `zeler.sheets.events.delay` y su binding desde `meli.events` faltaban.
Con autorización separada se declararon exclusivamente ambos, conforme a
[`delay_queues.json`](../../infra/rabbitmq/delay_queues.json): durable,
TTL 30.000 ms, DLX por defecto `""` y retorno a `zeler.sheets.events`.
El broker agregó `x-queue-type=classic`: una comparación literal inicial dio
una falsa alarma; se corrigió la verificación por lectura, **sin repetir PUT**.
El TTL de cola limita a 30 segundos los TTL solicitados de 2 y 10 minutos;
no se promete esa espera completa. No se alteró topología de otros módulos.

Antes del despliegue, el reinicio autorizado de solo `sheets-worker` reutilizó
contenedor e imagen: arranque **15:52:45**, `healthy` **15:53:01**, sin pull ni OOM.
La DLQ de eventos pasó de 189 a 281 tras ese reinicio del código anterior;
una descarga del backlog hacia DLQ no equivale a procesarlo correctamente.
No se consumieron ni reprocesaron esas DLQ.

Luego se autorizó y ejecutó **solo el despliegue del worker corregido**:

| Evidencia | Identidad verificada |
|---|---|
| Commit publicado en `main` | `320b373c4afe40b05357897b2e715c59913b4bc5` |
| Cloud Build | `f059c54d-d98a-44ca-a05a-9d75874987e0`, `SUCCESS` |
| Imagen `sheets-worker` | `sha256:689bef61d82c3002b4409f4e65e3ccc507f71cc877d8c187b1ff72fe9e6c2d6e` |
| Runtime | Arranque **16:14:55.109968779**; `healthy` **16:15:11**; cero reinicios, `OOMKilled=false`. |
| Respaldo Compose | `/opt/zeler-platform/docker-compose.yml.pre-sheets-worker-320b373` |
| Mapa de procedencia acotado | `image_to_commit.sheets-worker-320b373.json` |

Se verificaron fuente y procedencia de la nueva imagen y del rollback:
`sha256:ad22631933a09dfd8bfc0ddd5119af64fad55ed9a30aabeb5aafbaa71fea876f`,
commit `5ceb3c0ab7828c675d200ee41e172abba3bcfd89`, build
`c04d448d-3b40-4e06-a8bb-fb017ed3972e`. El delta de comportamiento del worker
comprende las dos correcciones descritas; no hay migración de datos ni cambio
de contrato que impida ese rollback, aunque restauraría ambos defectos.

Capacidad observada: raíz libre **35 → 34 GiB** antes/después del pull; Mongo
**48,13 GB** y memoria disponible aproximadamente **1,45 GB** antes. La primera
lectura posterior mostró eventos **0 listos / 0 sin ACK / 1 consumidor**, DLQ de
eventos **285**, claims y su DLQ **0**. Estos conteos son un corte operativo,
no una demostración de pérdida cero ni autorización para drenar la DLQ.

### Observación después del settling

A las **16:32**, más de 900 segundos después del despliegue:

| Comprobación | Resultado |
|---|---|
| Contenedores | 11 en ejecución; los 10 con healthcheck, sanos; cero reinicios y cero OOM. |
| Raíz libre | 36.395.327.488 bytes. |
| Mongo libre | 48.133.931.008 bytes en montaje separado. |
| Memoria disponible | 1.583.020 kB. |
| Eventos Sheets | 0 listos, 0 sin ACK, 1 consumidor; DLQ 286. |
| Claims y DLQ claims | 0 mensajes. |

La DLQ de eventos pasó de 285 a 286: cola principal vacía no significa que todos
los eventos hayan terminado con éxito. No se consumió ni reprocesó la DLQ.
La verificación de preguntas a las **16:32:46.731** complementa el estado del
host con evidencia funcional de un nuevo ciclo completado; no prueba por sí
sola el append Google ni la totalidad de fórmulas históricas.

## Pendientes al corte de las 16:50 UTC

1. Revisar el estado y configuración del cliente OAuth en Google Cloud para
   resolver el rechazo 400, sin atribuir una causa al código desconocido.
   Se agotó el último intento autorizado: no encadenar más pruebas ni cambiar
   credenciales a ciegas. Verificar el append real después de la reparación
   adecuada y de su autorización operativa.
2. Implementar la cobertura acumulativa multiperíodo de DEVOLUCIONES mediante
   el proceso de diseño y verificación correspondiente; conservar junio y no
   ejecutar la sustitución de agosto. Probar ambos intervalos y rechazar huecos.
3. Comprobar las fuentes históricas de las cuatro fórmulas restantes y repetir
   la aceptación nativa afectada. No convertir ausencia de prueba en éxito.
4. Mantener separada la evidencia de eventos completados y eventos en DLQ;
   cualquier inspección que consuma o reprocesamiento requiere su alcance y
   autorización propios. El settling completado no demuestra pérdida cero.

El mecanismo de recuperación del host sigue el
[runbook de despliegue y runtime](../deploy.md). La corrección de OAuth no resuelve
por sí sola la causa de saturación del host; la evaluación de capacidad permanece
separada y no autoriza redimensionarlo.

## Nota posterior: validación para publicación — 2 de octubre de 2026

El diagnóstico conserva sin cambios el SHA-256
`aa00f845d6d25f15a3728cdb4959ed9824f69ea125ed5f5baecc277daa73a938`.
La evidencia completa posterior del
[reporte multiperíodo](devoluciones-multiperiod-rollout-20261002.md)
incluye ese diagnóstico local: **5.701 passed, 9 skipped**, más **8 passed**
rs0 por separado; Ruff check/formato, mypy de **627 archivos**, exportación
de esquemas y lint de acceso directo a Meli correctos. No se atribuyen esas
pruebas locales al artefacto limpio publicado de aquella entrega.

Antes de publicar los archivos pendientes se repitieron **46 pruebas focales**
del diagnóstico y almacenamiento, además de Ruff check/formato y mypy focales:
todos correctos. Esta comprobación corresponde al diagnóstico sin cambios;
el desarrollo concurrente de histórico al vincular queda fuera de esta
publicación y no se presenta como validado por esos resultados. No se hizo
ninguna llamada productiva a Google, build ni despliegue para esta validación.
