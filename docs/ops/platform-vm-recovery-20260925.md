# Recuperación de platform-vm: 25 de septiembre de 2026

**Servicio recuperado; causa iniciadora todavía sin confirmar.** La parada y el
arranque autorizados devolvieron SSH, MongoDB, gateway, APIs y trabajadores.
La evidencia apunta principalmente a presión de memoria y carga del host. La
facturación estaba habilitada y el disco de sistema tenía espacio suficiente.

Verificación final: 26 de septiembre, 04:27 UTC; 25 de septiembre, 22:27 en
Monterrey. Es evidencia de esta ventana, no una garantía de salud futura ni una
prueba de nueva vinculación OAuth.

## Intervención ejecutada

- Proyecto `zeler-platform-dev`, VM `platform-vm`, zona `us-central1-a`.
- Se crearon y verificaron en estado `READY` los snapshots
  `platform-vm-pre-recovery-20260926` y
  `zeler-mongo-pre-recovery-20260926`, almacenados en `us-central1`.
  Conservan el estado de los discos previo a la intervención; no se pudo
  coordinar consistencia de aplicación con el guest bloqueado.
- Se omitió temporalmente el antiguo `startup-script` de aprovisionamiento.
  Después del arranque se restauró el contenido original y se comprobó su
  SHA-256: `fcea43eac2bb9d76dfc8ccf043f7955415ed5b6226f020e10edf4c8cc2516373`.
- La misma instancia conservó sus dos discos, IP estática y tipo `e2-medium`.
  No se cambiaron imágenes de servicios, capacidad, esquemas ni topología.
- La habilitación temporal de consola serial quedó retirada. No se ejecutaron
  limpieza Docker, replay de mensajes, Cloud Build ni despliegues de imágenes.

## Qué muestran los registros

Todas las horas siguientes son UTC.

| Momento | Evidencia |
| --- | --- |
| 25/09 23:35–23:38 | El agente reportó memoria usada del 84,1 % al 87,5 %. Último valor de memoria libre: 134.336.512 bytes, unos 128 MiB. Memoria libre y memoria disponible no son equivalentes. |
| 25/09 23:38 | Últimas métricas por proceso: MongoDB 1.513 MiB RSS, API Sheets 621 MiB, worker Sheets 303 MiB; también había otros servicios y procesos transitorios. RSS no permite sumar consumo exclusivo ni demostrar una fuga. |
| 25/09 23:38–23:43 | Las lecturas del disco raíz subieron hasta unos 10,6 GB/min; el disco de Mongo tuvo poca actividad. |
| 25/09 23:40 | Docker agotó comprobaciones de salud; el agente dejó de entregar registros. CPU elevada y fallos de servicios del sistema. |
| 26/09 00:31–00:41 | `systemd-networkd` registró timeout al configurar DHCPv4 y después `ens4: Failed`. Esto explica la posterior pérdida de conectividad del guest. |
| 26/09 04:19–04:21 | Parada y arranque completados; SSH recuperado. Mongo terminó la aplicación del oplog y pasó a primary con escrituras habilitadas. |
| 26/09 04:25 y 04:27 | Comprobaciones repetidas de salud, consumidores, memoria, espacio y presión de recursos correctas para la recuperación del host. |

La hipótesis principal es contención de memoria y CPU, seguida de lecturas
intensivas y degradación del sistema. No hay métricas PSI anteriores al bloqueo
ni registros que identifiquen el proceso iniciador. Tampoco apareció un OOM kill
en el journal recuperado; la interrupción de telemetría limita esa evidencia.
No se atribuye el incidente a una imagen concreta ni se afirma una fuga de memoria.
La documentación del kernel describe cómo la contención de CPU, memoria e I/O
puede degradar el sistema y cómo medirla mediante
[PSI](https://docs.kernel.org/accounting/psi.html).

La raíz tenía aproximadamente 69 % de espacio libre antes del fallo. El timer
de mantenimiento inició actividad después de la degradación; sus registros no
sustentan que fuera el detonante. La cuenta de facturación estaba abierta y el
proyecto tenía `billingEnabled=true`.

## Estado comprobado después de recuperar

| Componente | Resultado |
| --- | --- |
| Contenedores | 11 en ejecución; los 10 con healthcheck estaban healthy. Caddy se verificó mediante HTTPS. Todos con restart count 0 y OOMKilled false en esta observación. |
| Gateway y APIs | HTTP 200 en los cinco `/health`; gateway `/ready` confirmó Mongo, registro, RabbitMQ y scheduler. |
| MongoDB | Disco `/dev/sdb` montado en `/var/lib/zeler-mongo`, ping correcto, replica set `rs0`, writable primary y 75 colecciones accesibles. Recuperación del oplog completada. |
| Worker ZelerData | RabbitMQ, sync jobs poller, recuperación de fórmulas y refresh en estado `ok`. |
| Otros trabajadores | Repricer y Autoreply con RabbitMQ listo; bootstrap dispatcher con RabbitMQ y Mongo listos. |
| Cola de nuevas vinculaciones | `zeler.bootstrap.accounts`: 1 consumidor, 0 mensajes listos; su DLQ vacía. |
| Colas principales | Sheets events, Sheets claims, Repricer items y Autoreply events: 1 consumidor y 0 mensajes listos en cada una. La consulta pasiva no mide mensajes sin confirmar. |
| Memoria | 2.232 MiB disponibles de 3.913 MiB visibles al guest; sin swap. PSI de memoria a cero en las ventanas observadas. |
| Discos | Raíz: 36.132.495.360 bytes disponibles, 31 % usado; Mongo: 48.186.875.904 bytes disponibles, 4 % usado. Inodos usados: 4 % y 1 %, respectivamente. |
| Preflight | `docker-deploy-preflight.sh --dry-run`: correcto. No hubo descarga de imágenes. |

Estas comprobaciones establecen recuperación operativa y estabilidad durante
unos siete minutos desde el arranque. No equivalen a una auditoría completa de
integridad ni demuestran recepción de todos los eventos de Mercado Libre durante
la caída. La identidad de aplicación no pudo consultar `serverStatus`; ping,
primary, lecturas y registros de recuperación sí se verificaron.

## Pendientes concretos

1. **Prevenir otra saturación.** Evaluar ampliar memoria y CPU sostenida, además
   de alertas de memoria disponible, presión y disponibilidad. Una candidata es
   `e2-standard-2`, con 2 vCPU y 8 GB según la
   [tabla oficial E2](https://docs.cloud.google.com/compute/docs/general-purpose-machines#e2_machine_types).
   Requiere propuesta de coste, ventana y autorización propia. Ampliar capacidad
   es una mitigación; no demostraría ni corregiría por sí solo una fuga.
2. **Revisar eventos fallidos.** `zeler.sheets.events.dlq` tenía 196 mensajes,
   sin incremento entre 04:26 y 04:27. Hubo un registro `worker.message.dlq`
   a las 04:22 con clase `http_4xx` y HTTP 401; ese fallo de autorización requiere
   seguimiento. La antigüedad y relación del conjunto de mensajes con el
   incidente no están confirmadas. No se consumieron ni reencolaron mensajes.
   Su inspección con entrega/requeue tiene el alcance específico del
   [runbook de reconciliación](sheets-dlq-reconciliation.md).
3. **Verificar topología de errores.** Las consultas pasivas de
   `zeler.sheets.claims.dlq` y `zeler.repricer.items.dlq` devolvieron
   `ChannelNotFoundEntity`. Sus consumidores principales sí estaban activos.
   Se registró la discrepancia para investigar; no se crearon colas.
4. **Retomar la prueba de vinculación.** El dispatcher volvió a estar listo.
   Una nueva autorización OAuth y su bootstrap completo siguen siendo una
   comprobación separada y pendiente.

## Evidencia y continuidad

Los archivos saneados de métricas, journal, snapshots, identidad, verificaciones
y capacidad están en `/tmp/zeler-vm-recovery-20260926/` en el entorno del operador.
El respaldo privado del script original permanece con permisos 0600 y no forma
parte de este documento. El resumen anterior conserva los resultados necesarios
si desaparecen los archivos temporales. Los snapshots permanecen en GCP.

Se reutilizaron las imágenes que ya estaban ejecutándose. No hubo cambios de
código ni nuevos commits en `main`; esta recuperación no exige Cloud Build.
Referencia operativa: [despliegue y verificación de runtime](../deploy.md).
