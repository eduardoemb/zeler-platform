# Alertas y revisión de errores después de recuperar platform-vm

**Alertas de capacidad y disponibilidad activadas; los 196 mensajes de error
fueron inspeccionados y conservados.** Se corrigió el procesamiento de registros
del agente. La corrección de renovación de credenciales al arrancar quedó
publicada, construida y desplegada, con comprobaciones funcionales y de estabilidad.

Ventana inicial: 26 de septiembre de 2026, 04:30–04:53 UTC; 25 de septiembre,
22:30–22:53 en Monterrey. Proyecto `zeler-platform-dev`, VM `platform-vm`, zona
`us-central1-a`, instancia `7989018496556289195`. Cierre del despliegue:
26 de septiembre, 05:02 UTC; 25 de septiembre, 23:02 en Monterrey.

## Capacidad: decisión pendiente

La VM conserva `e2-medium`, con 4 GB nominales. A las 04:51 UTC tenía 2.100 MiB
disponibles de 3.913 MiB visibles. Raíz: 36.126.904.320 bytes libres, 31 % usado;
Mongo: 48.182.374.400 bytes libres, 4 % usado. Inodos usados: 4 % y 1 %.
Mongo seguía montado desde `/dev/sdb` en `/var/lib/zeler-mongo`.

Antes del incidente, la memoria usada alcanzó 87,5 % y aumentaron las lecturas
del disco raíz. Eso justifica evaluar más margen, pero no demuestra que ampliar
sea indispensable ni identifica el proceso iniciador. El estado recuperado
permite mantener el piloto bajo observación; no demuestra capacidad sostenida
para incorporar más vendedores.

La propuesta pendiente es `e2-standard-2`: 8 GB, 2 vCPU, unos USD 24,46/mes
adicionales de cómputo a 730 horas y tarifa de lista en `us-central1`.
No incluye impuestos, discos, IP ni descuentos. Requiere parada/arranque,
omitir temporalmente el antiguo script de aprovisionamiento y conservar su
contenido exacto. **No se autorizó ni ejecutó ese aumento.**
Referencias: [tipos E2](https://docs.cloud.google.com/compute/docs/general-purpose-machines#e2_machine_types)
y [precios de cómputo](https://cloud.google.com/products/compute/pricing/general-purpose).

## Alertas activadas

Todas las políticas siguientes están habilitadas y usan los dos canales
existentes de operadores: `4792700361586838315` y `11736862501462684654`.
La entrega a los buzones no se ha comprobado mediante un incidente de prueba.

| Política | Condición | ID en Cloud Monitoring |
| --- | --- | --- |
| `platform-vm-resource-pressure` | Memoria usada >80 % durante 3 min; CPU >90 % durante 5 min; o raíz >80 % durante 5 min | `1969862107457579041` |
| `platform-vm-memory-critical` | Memoria usada >90 % durante 1 min | `10257481840811512564` |
| `platform-vm-agent-silent` | El agente deja de reportar memoria durante 5 min | `10959973679266351991` |
| `zeler-platform-http-unavailable` | Gateway o Sheets fallan desde al menos dos ubicaciones durante 2 min | `4960200254003798828` |

Los checks HTTPS consultan cada minuto `gateway.zeler.ai/ready` y
`sheets.zeler.ai/health`, con validación TLS y timeout de 10 segundos:

- Gateway: `zeler-gateway-availability-w8bWKit3g5c`.
- Sheets: `zeler-sheets-availability-w8bWKit3hMI`.

A las 04:44 UTC ambos tenían resultados correctos desde Virginia, Oregón e Iowa.
Las políticas avisan; no reinician, limpian discos, amplían recursos ni
reprocesan mensajes automáticamente.

### Corrección del procesamiento de registros

El agente solo interpretaba el JSON externo de Docker. El evento real quedaba
dentro de `jsonPayload.log` como texto, sin severidad reconocida. Los filtros de
las métricas existentes `dlq_events_total` y `zelerdata_freshness_alarm` esperan
`jsonPayload.event` y severidad `ERROR`, por lo que ese formato impedía contar
los errores del worker.

Se aplicó la [configuración revisada](platform-vm-ops-agent-20260926.yaml) con
autorización expresa: interpreta ambas capas JSON, convierte `level` a
severidad y elimina cabeceras y URI de los registros de Caddy. Conserva los
receptores, nombres de pipelines y configuración de métricas existentes.

| Evidencia | Resultado |
| --- | --- |
| SHA-256 anterior | `f7c55232363a7c41cb73650f496306c541fab0f7ce20be4068f4f6f91a85f1e4` |
| SHA-256 instalado | `0adbcdbec15ee069c8fda852c9256e2bea9c2430ac8942e03db30f7b3c76059a` |
| Respaldo en VM | `/var/lib/zeler-platform/ops-agent-backups/config-before-20260926.yaml`, root, modo 0600 |
| Prueba previa con el motor y Fluent Bit instalados | El original falló la extracción de evento/severidad y la eliminación del marcador privado sintético; el candidato pasó ambas comprobaciones |
| Instalación, 04:49 UTC | Solo se reinició `google-cloud-ops-agent-fluent-bit.service`; el PID del recolector de métricas se conservó |
| Cloud Logging, 04:50 UTC | Eventos reales `http.request` y `proxy.call` en `jsonPayload.event`, severidad `INFO` |
| Cloud Monitoring, 04:49:50 UTC | Muestra nueva de memoria usada: 42,32 % |

La comprobación de las 04:53 UTC volvió a encontrar eventos estructurados y una
muestra nueva de memoria, esta vez 40,52 %. La consulta de esta ventana no
encontró eventos estructurados con severidad `ERROR` o superior.

No se generó un error falso para disparar correo. La severidad `ERROR` quedó
probada con datos sintéticos fuera del pipeline de producción. El respaldo
permite restaurar el archivo de configuración y reiniciar el mismo servicio si
la corrección falla; no fue necesario hacerlo.

Esta configuración documenta el ajuste aplicado a la VM. La plantilla antigua
`infra/gce/ops-agent-config.yaml` y su copia en el script de aprovisionamiento
requieren una actualización separada antes de reutilizarlas. No deben sobrescribir
este ajuste. La prueba de ese archivo simula el parser y no establece que el
motor real acepte su formato. Referencia del proveedor:
[configuración del Ops Agent](https://docs.cloud.google.com/monitoring/agent/ops-agent/configuration).

## Los 196 mensajes: resultado y límites

El usuario autorizó una excepción de una sola ejecución al
[runbook de inspección](sheets-dlq-reconciliation.md): hasta 196 mensajes,
con contenido solo en memoria, resumen saneado y devolución a la misma cola.
No se amplía la autorización del runbook para futuras ejecuciones.

La inspección se ejecutó como root dentro de `sheets-worker`, desde la VM,
con el lock canónico, salud del worker y cero consumidores en la DLQ.
Se obtuvieron 196 mensajes y se solicitaron 196 `nack(requeue=True)`; no hubo
resultado desconocido de envío. Después de cerrar la conexión, una consulta
pasiva a las 04:44:22 UTC confirmó **196 mensajes listos y cero consumidores**.
La consulta inmediata anterior había mostrado un conteo transitorio menor.
No hubo ack, replay, borrado, publicación ni escritura en Mongo.

Todos correspondían al vendedor piloto: 141 eventos de publicaciones y 55 de
envíos. **195 son anteriores a la caída; uno corresponde al arranque posterior.**
La distribución temporal va del 13 de agosto al 26 de septiembre; el mayor grupo
es el 1 de septiembre, con 94 mensajes.

| Correlación con registros conservados | Mensajes |
| --- | ---: |
| `RetryableItemAcquisitionError`: la precondición que protege contra cambios durante el enriquecimiento rechazó la escritura | 52 |
| `DuplicateKeyError`, índice `_id_` | 2 |
| `HTTPStatusError`, estado 401 después del arranque | 1 |
| Sin registro de causa correlacionable | 141 |

Estas clases describen fallos históricos, no autorizan disposición ni demuestran
que falten 196 ventas. Para los 141 sin registro no se puede atribuir una causa
exacta. Antes de cerrar o reprocesar cualquier mensaje, hace falta verificar
su resultado en los datos actuales y aplicar las reglas de reconciliación.

Los 52 registros incluyen `item changed during enrichment; retry from current
state`. El código usa una comparación con el documento leído antes de escribir;
los registros no identifican qué escritor cambió ese estado ni permiten excluir
un fallo de comparación. La etiqueta genérica `http_5xx` de esos eventos no es
evidencia de que Mercado Libre respondiera 5xx.

La inspección usó el worker desplegado con digest
`sha256:28149428e4486f3133c54bd953cdb5753e8e799b709790dc82c89a9e5bb36826`,
fuente `ac3e8ec6e518695807601a65872e1bfcce9e0246`, mientras el checkout estaba en
`85235300cfb6cd0661bf96b6bd63b94ba6eceb5b`. La excepción autorizada fue un
inspector temporal probado, no la ejecución del wrapper limitado a 24.

## El 401 del arranque y su corrección

El audit del gateway confirma `upstream_status=401`: Mercado Libre rechazó
la credencial usada a las 04:22 UTC. El gateway desplegado programaba su primera
renovación cinco minutos después de arrancar. La cuenta piloto se renovó a las
04:26:30 UTC y una lectura del mismo recurso, mediante la identidad normal del
worker y el gateway, devolvió HTTP 200. No se copiaron credenciales ni se evitó
OAuth.

El cambio en [el lifespan del gateway](../../gateway/src/zeler_gateway/app.py)
ejecuta una pasada de renovación antes de declarar readiness; conserva la
pasada periódica de cinco minutos. La
[prueba de ciclo de vida](../../gateway/tests/test_lifespan_rabbit.py) falló antes
del cambio y pasó después: primera renovación con readiness falso y renovación
periódica posterior con readiness verdadero. Los fallos de renovación conservan
el tratamiento existente; el cambio no garantiza que Mercado Libre siempre
acepte una credencial.

Verificación local:

- `uv run pytest gateway/tests/test_lifespan_rabbit.py`: 4 correctas.
- Suite completa contra Mongo local aislado: 5.483 correctas, 9 omitidas y un
  fallo por `MONGO_DB` heredado en una prueba que presupone que no está definido.
  Las cuatro pruebas de ese archivo pasaron al repetirlas sin esa variable.
  No se cambió la prueba ni se redujo la suite. Ocho omisiones corresponden a
  pruebas rs0 con un contrato de entorno distinto; una a Caddy sin claves requeridas.
- Ruff, formato, mypy de todo el repositorio y lint de acceso directo a Meli:
  correctos.

## Estado después de reparar las alertas

A las 04:51 UTC los 11 contenedores seguían ejecutándose, sin reinicios ni OOM
registrados; los diez con healthcheck estaban healthy. Gateway `/ready` y Sheets
`/health` respondían 200; el worker confirmó RabbitMQ, poller, recuperación de
fórmulas y refresh. El dispatcher confirmó RabbitMQ y Mongo. Ambos componentes
del Ops Agent seguían activos después del tiempo de estabilización.

## Despliegue del gateway y cierre

El usuario autorizó commit/push y Cloud Build, y posteriormente autorizó el
despliegue por separado. Se publicó el cambio en `main`, se construyó una sola
imagen desde el repositorio conectado y se verificó su procedencia.

| Identidad | Valor |
| --- | --- |
| Commit de la imagen | `26958853a4291ed0db053f2f014245402ecc1a9a` |
| Cloud Build | `97168067-0fdb-4bad-a756-6d4a2eebe078`, `SUCCESS`, `VERIFIED` |
| Imagen ejecutada | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:dad631e75edf098c59e8d573347bfb7b38384d713c32b35ebde7d7192a7462d1` |
| Rollback compatible y conservado | `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:a7534d634f455eb19a8ebbda7860c3145f1dff988125609478bc8cf90c2f9735` |
| Respaldo de Compose en VM | `/opt/zeler-platform/docker-compose.yml.pre-gateway-2695885` |

Se sustituyó exactamente una referencia de imagen y se recreó solo `gateway`
con `--no-deps`. El preflight verificó capacidad antes y después de descargar,
y procedencia del digest/build/commit antes de la recreación. Los otros diez
contenedores conservaron su identidad; no hubo limpieza Docker, ampliación de
VM, cambios de esquemas ni reprocesamiento de mensajes.

El nuevo contenedor arrancó a las 05:00:01 UTC. A las 05:00:07 ejecutó
`refresh.run` **antes de completar el arranque HTTP**: cero errores y cero
credenciales elegibles para renovar, pues seguían vigentes. Una lectura del
recurso que había dado 401, mediante la identidad Sheets y el gateway, respondió
HTTP 200. No se alteró la vigencia de las credenciales para fabricar una prueba.

La observación repetida a las 05:02:20 UTC confirmó:

- Gateway healthy, digest esperado, cero reinicios y `OOMKilled=false`.
- `/ready` 200: Mongo, registro, RabbitMQ y scheduler correctos. Sheets API,
  worker y bootstrap dispatcher también listos.
- 2.111 MiB de memoria disponible; raíz con 35.860.541.440 bytes libres; Mongo
  con 48.181.489.664 bytes libres y su montaje conservado. Inodos usados: 4 % y 1 %.
- Colas principales de Sheets y bootstrap: cero mensajes listos y un consumidor
  cada una. La DLQ seguía con 196 mensajes listos y cero consumidores; solo se
  consultó pasivamente, sin otra inspección de contenidos.
- Cloud Logging recibió eventos estructurados `http.request` y `proxy.call` de
  esta ventana, sin eventos estructurados ERROR en la consulta; las métricas del
  agente continuaron llegando.

No se necesitó rollback. El código del gateway desplegado coincide con el cambio
publicado; la actualización posterior de este informe solo documenta la entrega
y no requiere otra imagen.

## Seguimiento

La nueva vinculación OAuth sigue siendo una prueba pendiente. La inspección
actual no establece la integridad de todas las ventas ni resuelve la causa
iniciadora de la saturación. Evidencia saneada del operador:
`/tmp/zeler-vm-prevention-20260926/`; este informe conserva los resultados
principales si desaparecen esos archivos temporales.
