# ZelerData AMQP — reparación única y verificación separada preparadas

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local del6octubreUTC:
**24 pruebas offline PASS**, cero skips; ruff, formato y mypy enfocados PASS
en tres fuentes privadas. **No producción ejecutada por AMQP.**

La autoridad recibida por root y la ausencia confirmada están en
[propuesta puntual](zelerdata-historico-amqp-reparacion-propuesta.md) y
[ledger](zelerdata-historico-paralelo.md). Esta entrega no renueva ventana,
cuota, díaUTC, cutoff/checkpoints ni permisos del piloto; Full sigue excluido.

## Quick path del coordinador

1. Verificar autoridad, identidades, hashes y recibos anteriores sin repetir pasivo.
2. Ejecutar **solo** `--repair-retry1s`; interpretar confirmación/efecto/cleanup.
3. Decidir separadamente si ejecutar `--verify-remaining`. **No encadenado automático.**
4. STOP ante conflicto/error/timeout/incertidumbre; jamás borrar/recrear para imponer
   parámetros. Conservar recurso compatible y datos concurrentes.

## Cuatro paths exclusivos

Privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-retry1s-repair-20261006`.
Directorio0700, fuentes0600; logs/recibos/cache propios confinados ahí.

| Path | Entrega |
| --- | --- |
| `<privado>/repair.py` | Dos CLI explícitas, default sin operación. |
| `<privado>/repair_supervisor.py` | Fuente/digest/oldworker, un exec por acción y output cerrado. |
| `<privado>/test_repair.py` | Once active, seis verify, siete supervisorfake:24≤24. |
| `docs/sheets/zelerdata-historico-amqp-reparacion-informe.md` | Este informe propio. |

Seis deliveries anteriores y sus informes conservan sus24 hashes. Sin modificaciones
a código servido, core, CUOTAS, documentos centrales, deps/lockfiles, otras colas,
policies/config/IAM, datos/Mongo/Meli, Git/builds, puertos o subagentes.

## Acción1: declarar exclusivamente retry1s

`--repair-retry1s` usa la URL existente del broker, una conexión propia no robusta
y un canal con publisher_confirmsFalse. Único RPC activo `Queue.Declare`:

```json
{"queue":"zeler.sheets.claims.retry.1s","passive":false,"durable":true,"exclusive":false,"auto_delete":false,"nowait":false,"arguments":{"x-message-ttl":1000,"x-dead-letter-exchange":"","x-dead-letter-routing-key":"zeler.sheets.claims"}}
```

No nueva comprobación pasiva, consumo/basic.get/ACK/NACK, publish, binding,
declaración de exchanges, delete/drain/purge o policy changes. El binding default
es consecuencia normal del broker; no se agrega routing key a `meli.events`.

Counters distinguen activeRPC iniciado, reply recibido y **confirmado**. Un OK
acredita estado compatible, no autoría: `created_by_us=null`,
`effect_status=confirmed_equivalent`. Otro actor pudo crear la cola equivalente.
Si el RPC fue iniciado y falla, `effect_status=unknown`; no se afirma que no hubo
efecto. Conflicto406/412, access403, error o timeout→STOP, sin retry/overwrite.

## Cleanup honesto, no cierre inventado

Reutiliza propietario del stream retenido antes del handshake; crea/retiene el
waiter antes de cerrar conexión y lo espera protegido con shield dentro de
**un deadline conjunto5s**. Siempre solicita cierre directo del writer propio,
incluso si el cierre de conexión falla; cancela/recupera el waiter propio pendiente.

- `local_close_requested`: solicitud local, no confirmación remota.
- `waiter_state`: `completed|cancelled|error|timeout|none`.
- `cleanup_error`: conserva fallo, aunque exista confirmación del RPC activo.
- `remote_close_confirmed=false` **siempre**.

Shield no convierte un futuro ya cancelado por la librería en éxito. Nunca se
convierten cancelación/errores genéricos en “limpio”. Un RPC confirmado puede quedar
STOP por cleanup; root decide siguiente acción, no se repite automáticamente.
Harddeadline termina únicamente el Python transitorio, nunca workerPID1.

## Acción2: trece GET pendientes, no snapshot global fresco

`--verify-remaining` es solo lectura: cinco buckets retry1s/5s/30s/2m/10m,
metadata+bindings(10GET), y tres exchanges canónicos(3GET). Mismo destino/auth,
normalización userinfo en memoria y guards de la entrega revisada congelada.

El clasificador local verifica `_queue`, `_bindings` y `_exchange` únicamente
para recursos realmente obtenidos. Cada retry exige su binding del exchange
default. **No invoca el classify global**, que necesita roots/events/claims/DLQ;
no inventa snapshots de esas colas ni completa evidencia sin GET.

Puede devolver `selected_structure_verified=true` para ese subset. Siempre:
`topology_verified=false`, publicación/timing/ingress/noLoss/admisiónfalse.
Los diez GET anteriores son evidencia fechada separada que root combina y limita;
esta operación no afirma verificación actual del inventario global.

Excepción de policy limitada al tuple exacto revisado de tres ints; policies/caps
**reales** se guardan por cada cola, no se simula ausencia en el resultado. Cambios,
unknowns, tipos, TTL/DLX, counts/body/bindings o HTTPerror→primer STOP, no retry.

## Presupuestos y secretos

| Acción | Límite |
| --- | --- |
| Repair |conn8s/canal4s/RPC4s/cleanupTOTAL5s/hard55/exec65/remoto120/root130+grupo5/total≤300s. |
| Verify |≤13GET/4srequest/60sread/64KiBbody/cleanup5/hard80/exec95/remoto150/root130+grupo5/total≤300s. |

Oldworker aprobado: `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
Solo un exec por acción explícita, source/hash/digest previamente comprobados.
Caller incluye inicio SSH tardío/cleanup dentro del total; no resubmit.
Mantener consumo Management previo13 y posterior separados; nunca reiniciar ledger.

Recibos cerrados: counters0..1(activa) o0..13(verify), null si progreso desconocido,
enums/argumentos/recursos/plantillas fixed. No URL/vhost/user/password, nombres
de policies, error strings, traceback, headers/body, hashes/longitudes de secretos
o stderr libre. Logs dependientes y stderr del CLI se suprimen sin imprimirlos.
Solo se hashean fuentes. No trasladar0Management de repair al historial global.

## RED/GREEN y relevo

| Evidencia privada | Resultado |
| --- | --- |
| `RED.log` | módulo repair ausente, antes de behavior. |
| `supervisor-RED.log`, `supervisor-RED-2.log` | siete errores por supervisor ausente; primer fixture confundió eventsDLX permitido con rootqueue prohibida; corregido test-only. |
| `GREEN-1.log` |22 PASS. |
| `conflict-RED.log` |24 tests, un fallo: generic ChannelClosed412 no estaba clasificado como conflicto. |
| `GREEN-2.log` |24 PASS tras leer solo código numérico, nunca replytext. |
| `final-unittest.log` |24 PASS/0skip,0.260s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` |PASS en tres fuentes, sin reducir checks. |
| `representative-*-no-env-stdout.json` /stderr |Ambas CLI exit2, counters0, JSON cerrado, stderr vacío. |
| `source-binding-receipt.json` |Embedding/helpers exactos,24 hashes anteriores intactos; AST host3.9 PASS, no runtimehost sondeado. |

Fakes/callbacks/MockTransport, sockets/DNS prohibidos, sin Docker real, producción,
suite general o nuevos builds. Tests prueban13GET positivo sin roots ficticios,
dualacción/noautoverify, argumentos, concurrencia equivalente, conflictos,
timeout/efecto incierto, waiter cancel/error no limpio y receipts negativos.

| Fuente privada | SHA256 final |
| --- | --- |
| `repair.py` | `8b34b81a495fd33b55eaae640289fc0eb703fdd63343f92081880c7715939165` |
| `repair_supervisor.py` | `472c23980198ba7b14f913bb14976a6df18c0c6bcfbf2b278f91e57053e6c3a2` |
| `test_repair.py` | `1591ff931d4cd2bb3b4e0f4a14d018126a6ddc00c34676c91dc8e8c70b3da034` |

Helper pasivo SHA `f66b207028b837dc629ad9bca4716ad17c1f08481fa4ee4f80546f9cbe2d6848`;
revisado SHA `816e2c4511bf6fff38a41b93d0092463337ddebd7ef1094824e74df085041202`;
canon66e995 intacto. Hash de este informe fuera en `delivery-receipt.json`.
Root único operador/ledger/Git, decide reparación/verificación/rollout posterior
según sus gates; el cambio de UTC no autoriza piloto ni resetea plazos.
**ENTREGADO; NO SIGO MODIFICANDO.**
