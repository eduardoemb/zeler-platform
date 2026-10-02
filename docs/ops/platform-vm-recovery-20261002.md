# Host y OAuth recuperados; aceptación íntegra de ZelerData pendiente

**La VM y OAuth están recuperados; las órdenes ya cubren el intervalo solicitado.
Persisten un bloqueo AMQP, cobertura pendiente de preguntas y limitaciones de
fuentes.** La corrección OAuth fue desplegada y verificada; la corrección del
consumidor está probada localmente, todavía sin publicar ni desplegar. No se
afirma integridad completa ni ausencia de pérdida de eventos durante la interrupción.

Todas las horas son UTC. Proyecto `zeler-platform-dev`, VM `platform-vm`, zona
`us-central1-a`. Las secciones separan la recuperación del host a las **05:34**
de las verificaciones funcionales posteriores al despliegue de las **15:16**,
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
| Preguntas | El ciclo de las **15:29** todavía terminó `source_rejected`; el intervalo solicitado sigue sin cobertura comprobada. |
| Hoja nativa | Se preservaron las **52 fórmulas**: 42 devolvieron valores/tablas, 5 `NA` y 5 `DATA_UNAVAILABLE`. Algunas tablas contienen columnas parcialmente no disponibles; 42 resultados no equivalen a integridad completa. |
| Claims actual | Dos GET acotados por el gateway normal: búsqueda **200** y un detalle **200**. El 403 histórico no demuestra un rechazo actual. La muestra no establece reconciliación completa ni disponibilidad de todos los detalles. |

Una comprobación posterior con los parámetros del worker recibió **200** en
cinco páginas de búsqueda de preguntas, con límite 50 y total reportado 226.
El primer detalle dentro de la cobertura devolvió **404** en la sexta petición:
la búsqueda enumera una pregunta cuyo detalle ya no está disponible. La auditoría
real de la VM entre **15:29:40 y 15:29:55** confirma una búsqueda de preguntas
desde `bootstrap` con **200** y un detalle desde `sheets` con **404**, sin exponer
identificadores. La corrección de recuperación de preguntas está probada
localmente: **7 RED** antes del cambio, **11 pruebas nuevas GREEN** y **462 GREEN**
en el archivo completo de recuperación; Ruff/formato/mypy focales correctos.
Todavía no está publicada ni desplegada y no amplía la cobertura comprobada.

Los cinco `NA` corresponden a `PAUSADAS`, `TIEMPOACTIVA`, `MEDIDAS`,
`DIASDESDEULTIMAVENTA` y `COSTOENVIOVENDEDOR`; son resultados contractuales cuya
causa depende de los datos, no prueba automática de fallo o ausencia global.
Los cinco `DATA_UNAVAILABLE` son `DEVOLUCIONES`, `CATALOGOTIEMPO`,
`TIEMPOSTOCKACTIVO`, `RETIROS` y `SEMANASCONSTOCK` (todos con prefijo `ZELERDATA_`).

`DEVOLUCIONES` solicita 8 de agosto–6 de septiembre, inclusivos, y no tiene prueba
conjunta fresca de reconciliación para ese rango. La propuesta de reconciliación
con presupuesto durable de cuota fue autorizada por separado:
máximo **832 llamadas**, tres ventanas entre **8 de agosto y 7 de septiembre
exclusivo**, con duración estimada de **65–80 minutos**. Su ejecución y aceptación
deben registrarse por separado; la autorización no establece que se haya recuperado.
Las otras cuatro fórmulas dependen de historia importada y carecen de markers
válidos; la aceptación histórica de fuentes ausentes no sustituye comprobar su
inventario actual ni autoriza fabricar datos.

## Bloqueo del consumidor y corrección local

Después del despliegue del gateway, la cola de eventos mantenía **81 mensajes
listos y 10 sin ACK**, con un consumidor; no había nuevos `processed_events` de
Sheets desde las **15:16:44**. Los logs del arranque mostraron **10 excepciones
de callback y 10 de tarea por HTTP 412**. La DLQ de eventos seguía en 189; la
DLQ de claims estaba vacía y su binding comprobado.

En `consumer.py`, el 412 escapaba desde el bloque `except HTTPStatusError`, sin
ACK ni NACK: las diez entregas ocupaban todo el prefetch aunque OAuth se
recuperara después. La conexión y suscripción podían seguir `ready`; el ciclo
de recuperación de 900 segundos no libera esas entregas.

La corrección local usa el mecanismo existente de reintento demorado para 412,
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
ocho skips de AMQP no se tomaron como aceptación. El worker corregido todavía
no está publicado ni desplegado.

**Prerequisito de topología todavía ausente:** producción respondió 404 para
`zeler.sheets.events.delay` y no tenía su binding desde `meli.events`.
Antes de un futuro despliegue se requiere autorización para declarar solamente
esa cola y binding según
[`delay_queues.json`](../../infra/rabbitmq/delay_queues.json): durable,
TTL 30.000 ms, DLX por defecto `""` y retorno a `zeler.sheets.events`.
No incluye topología de otros módulos. El TTL de cola limita a **30 segundos**
los TTL solicitados de 2 y 10 minutos; no se promete esa espera completa.

El reinicio acotado de **solo `sheets-worker`** fue autorizado y ejecutado:
arranque a las **15:52:45**, `healthy` a las **15:53:01**, mismo contenedor e imagen
`sha256:ad22631933a09dfd8bfc0ddd5119af64fad55ed9a30aabeb5aafbaa71fea876f`,
sin recreación, pull, OOM ni cambios manuales de datos/colas. Falta observar
progreso sostenido de entregas. No se han consumido ni reprocesado las DLQ.
También se autorizó commit/push y Cloud Build del worker, condicionados a todos
los gates correctos: **no incluye despliegue ni topología**.
El candidato comprende seis archivos: dos implementaciones, sus dos archivos de
pruebas y los dos documentos. La imagen del worker se conserva durante la
reconciliación autorizada; el build no autoriza sustituirla.

## Pendientes para aceptación

1. Verificar progreso después del reinicio autorizado; declarar topología solo
   con autorización separada. Comprobar backlog y completados, no solo health.
2. Con gates completados, publicar, construir y desplegar el worker conforme a
   sus autorizaciones; todavía no se declara listo para desplegar.
3. Demostrar cobertura durable de preguntas y resolver la reconciliación de
   devoluciones dentro del presupuesto autorizado; verificar las fuentes históricas.
4. Repetir la observación tras el settling de 900 segundos y comprobar las
   superficies afectadas, consumidores, DLQ y capacidad sin declarar pérdida cero.

El mecanismo de recuperación del host sigue el
[runbook de despliegue y runtime](../deploy.md). La corrección de OAuth no resuelve
por sí sola la causa de saturación del host; la evaluación de capacidad permanece
separada y no autoriza redimensionarlo.
