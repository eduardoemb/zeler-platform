# ZelerData — asegurar los reintentos restantes

**AUTORIZADO EN EL MISMO MECANISMO / NO EJECUTADO.** La autorización del usuario
para resolver lo necesario se limita aquí a los buckets requeridos por el contrato
actual. No es una reparación general del broker ni una ampliación del piloto.

## Estado y motivo

Retry1s quedó declarado de forma compatible y su metadata/binding dieron HTTP200.
La verificación posterior se detuvo en HTTP404 de retry5s. No se infiere ausencia
de ese 404 ni se repite la misma lectura sin cambio de estado.
El cleanup de la conexión AMQP anterior falló; el proceso terminó y el fallo se
conserva. No declarar un cierre remoto limpio ni repetir retry1s.

## Alcance exacto

Una conexión propia, un canal y hasta cuatro declaraciones activas secuenciales:

| Cola | `x-message-ttl` |
| --- | --- |
| `zeler.sheets.claims.retry.5s` | 5000 |
| `zeler.sheets.claims.retry.30s` | 30000 |
| `zeler.sheets.claims.retry.2m` | 120000 |
| `zeler.sheets.claims.retry.10m` | 600000 |

Todas: durable=true, exclusive/auto_delete/nowait=false; DLX default vacío y
dead-letter-routing-key `zeler.sheets.claims`. Una declaración comprueba
equivalencia o crea el recurso compatible: no acredita quién lo creó.
No modificar argumentos de una cola distinta ni borrar/recrear ante conflicto.

Sin otros recursos, policies, exchanges, routing keys, flags, datos, jobs,
validators, índices, IAM, capacidad, consumo, publish, ACK o mensajes de prueba.
No ejecutar el operador general prestart ni nueva comprobación pasiva.

## Límites, evidencia y recuperación

TDD offline, hashes/identidad/digest y cese de escritura antes de Root producción.
Connect8s/canal4s/RPC4s cada uno/cleanup total5s; hard55/exec65/remoto120,
caller130+grupo5 y máximo300s. Primer conflicto/error/timeout → STOP sin retry;
conservar declaraciones parciales confirmadas y efecto desconocido cuando aplique.

Root decide separadamente la verificación de solo lectura: hasta once GET para
cuatro metadata+bindings y tres exchanges,4s/request,60s/read,64KiB/body,
cleanup5/hard80/exec95/remoto150/caller130+5/300 total. Conserva los16 GET previos:
máximo conocido del tramo27, no reinicio de consumos. Subset verificado no es
topología global fresca, publicación, timing ni admisión segura.

No borrar automáticamente buckets creados, aunque aparenten vacíos: podrían
recibir trabajo concurrente. Mantenerlos compatibles con worker antiguo/nuevo y
la adquisición cerrada si queda cualquier gate pendiente. No refund/reset,
replay manual o alteración de checkpoints/cutoff/díaUTC/plazos.

Registro14 sin Full y seis routing keys intactos; Meli/Full0 en esta reparación.
Imágenes existentes no se reconstruyen por herramientas privadas/documentación.

[Ledger único](zelerdata-historico-paralelo.md),
[reparación de retry1s](zelerdata-historico-amqp-reparacion-propuesta.md).
