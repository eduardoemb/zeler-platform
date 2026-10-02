# Host recuperado; sincronización ZelerData todavía pendiente

**La recuperación autorizada restableció la VM, MongoDB y los servicios HTTP.
No restableció todavía la adquisición de órdenes y preguntas del piloto.** Se
identificó un bloqueo anterior a la caída: un HTTP 429 al renovar OAuth dejó la
cuenta permanentemente fuera del proceso de renovación. La corrección está
probada localmente; publicación y Cloud Build fueron autorizados condicionados a
los gates. El despliegue aún requiere autorización separada. No se afirma integridad completa
ni ausencia de pérdida de eventos durante la interrupción.

Todas las horas son UTC. Proyecto `zeler-platform-dev`, VM `platform-vm`, zona
`us-central1-a`. Corte de comprobación posterior: **2 de octubre de 2026, 05:34**.

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

No hubo imágenes nuevas, Cloud Build, despliegue de código, limpieza Docker,
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

## Corrección local y aceptación pendiente

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
Estos resultados no certifican todavía la corrección en producción.

Siguiente secuencia:

1. Publicar el cambio autorizado, con los gates raíz completados.
2. Construir una nueva imagen **solo de gateway** desde el commit autorizado de
   `main`, con procedencia verificada. Pedir autorización separada para desplegar.
3. Tras el despliegue, verificar renovación OAuth normal exitosa y cuenta activa;
   no parchear estado, copiar tokens ni evitar OAuth.
4. Verificar jobs de órdenes/preguntas completados y cobertura reconciliada del
   intervalo interrumpido. Observar nuevos ciclos, consumers, DLQs y capacidad.
5. Confirmar resultados en la aplicación y una hoja nativa antes de declarar
   funcionamiento íntegro. Mantener explícitas las excepciones de datos/fuentes.

El mecanismo de recuperación del host sigue el
[runbook de despliegue y runtime](../deploy.md). La corrección de OAuth no resuelve
por sí sola la causa de saturación del host; la evaluación de capacidad permanece
separada y no autoriza redimensionarlo.
