# ZelerData AMQP — cuatro retries restantes y verificación separada

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local del 6 octubre UTC:
20 pruebas fake PASS, cero skips; ruff, formato y mypy en tres fuentes PASS.
**Este especialista no ejecutó producción.** Solo el coordinador decide y opera.

## Alcance y propiedad

Cuatro paths exclusivos, sin editar fuentes ni informes anteriores:

1. `<privado>/ensure_retries.py` — acciones explícitas independientes.
2. `<privado>/ensure_supervisor.py` — identidad/hash, un exec, recibos cerrados.
3. `<privado>/test_ensure_retries.py` — 9 active, 5 verify, 6 supervisor:20.
4. `docs/sheets/zelerdata-historico-amqp-retries-restantes-informe.md` — este informe.

`<privado>` es `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-retries-restantes-20261006`;
directorio0700 y fuentes0600. Logs/caches/recibos propios, salvo el desvío declarado abajo.
La autoridad, cronología y presupuestos pertenecen al [ledger del coordinador](zelerdata-historico-paralelo.md).
La [entrega1s congelada](zelerdata-historico-amqp-reparacion-informe.md) se conserva íntegra.

Según la comunicación del coordinador,1s ya obtuvo declaración equivalente y
metadata/binding correctos; después metadata5s devolvió HTTP404 y se hizo STOP.
Este informe **no convierte HTTP404 en prueba de ausencia**, ni reproduce diagnósticos.
Se prepara asegurar equivalencia de los cuatro buckets canónicos restantes,
no declarar1s otra vez ni tocar recursos ajenos. FechaUTC nueva no reinicia ventana,
registro de14 permisos sin Full, cuota, cutoff, checkpoints, trabajos o plazos.

## Acción explícita activa

`--ensure-remaining-retries`: una conexión propia **no robusta**, un canal
`publisher_confirms=false`, máximo cuatro `Queue.Declare` secuenciales y fijos:

| Cola | x-message-ttl |
| --- | ---: |
| zeler.sheets.claims.retry.5s | 5000 |
| zeler.sheets.claims.retry.30s | 30000 |
| zeler.sheets.claims.retry.2m | 120000 |
| zeler.sheets.claims.retry.10m | 600000 |

En todos: `passive=false`, `durable=true`, `exclusive=false`, `auto_delete=false`,
`nowait=false`, argumentos **exactamente** TTL de tabla,
`x-dead-letter-exchange=""`, `x-dead-letter-routing-key="zeler.sheets.claims"`.
No nombres/flags/argumentos aportados por operador. No nuevo passivecheck.

Preserva recurso compatible concurrente. OK significa **equivalencia confirmada**,
no que lo creamos: `created_by_us=null` siempre, global y por bucket.
Counters started/reply_received/confirmed por bucket0..1 y agregados0..4;
conexión/canal0..1. Confirmaciones parciales se conservan. Progreso desconocido
se expresa `null`, jamás0 inventado. Efecto no confirmado queda `unknown`.

STOP al primer406/412/conflicto,403/acceso, error o timeout: no retries,
no overwrite/borrar/recrear, ni operaciones posteriores. No consume/basic.get/
ACK/NACK/publish/bind/delete/purge, otras colas/exchanges/policies/config/IAM,
Mongo/Meli ni Full. **No verificación encadenada automáticamente.**

## Cleanup honesto

Reutiliza sin cambios el helper congelado de propiedad de stream y cleanup de1s:
waiter retenido antes del cierre, espera shielded bajo un único deadline5s,
cierre directo del writer propio incluso si connection.close falla.
`local_close_requested` es solicitud local; `waiter_state` distingue
`none|completed|cancelled|error|timeout`; `cleanup_error` preserva error/cancelación.
`remote_close_confirmed=false` siempre. No se fabrica cierre remoto ni se oculta
el fallo real previo. Cuatro RPC confirmados pueden quedar STOP por cleanup.
Harddeadline termina solo el Python transitorio, nunca workerPID1.

## Acción explícita de lectura independiente

Solo tras decisión separada de Root: `--verify-remaining-retries`.
Máximo **11 GET**: metadata+bindings de los cuatro buckets de tabla(8),
y los tres exchanges canónicos(3), secuenciales, sin retry ni fallback.
Mismo destino/auth runtime; normalización userinfo únicamente en memoria con
guards congelados. No config/envwrite ni credenciales alternativas.

Reusa fuente repairSHA8b34… y guards reviewed/canon. Adaptación AST cerrada:
lista fija de cuatro nombres; único `max_requests`13→11; enum de acción actualizado.
TTL/DLX, defaultbinding obligatorio, exchanges, shapes/counts/64KiBbody y
policy tuple exacto siguen canónicos. Excepción de review exclusivamente
`{expires:2419200000,max-length:10000,max-length-bytes:1073741824}` con tipos int
exactos; flags de policy/operator y caps **reales** permanecen en el recibo.
Cambio/unknown/TTL/DLX/binding/body/HTTPerror: primer STOP.

Solo puede acreditar `selected_structure_verified` del subset obtenido.
Siempre `topology_verified=false`, publication/timing/ingress/noLoss/pilotadmissionfalse.
No inventa roots ni snapshot global fresco; Root combina evidencia fechada previa.
Generic `tool_error` está incluido en códigos cerrados del nuevo supervisor:
preflight0requests o progreso desconocido `null` con STOP. Entrega anterior intacta.

## Supervisor y presupuestos

Worker aprobado, único contenedor running/identidad exacta y digest:
`sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
SourceSHA exacta y **un solo exec por acción**, sin forwarding de variables.
Host supervisor stdlib/AST3.9; worker `/app/.venv/bin/python3.11`.
No se sondeó versión/runtime real del host.

| Acción | Límite |
| --- | --- |
| Active |conn8s/canal4s/cadaRPC4s/cleanupTOTAL5s/hard55/exec65/remoto120/root130+grupo5/total≤300s. |
| Verify |11GET/4srequest/60sread/64KiBbody/cleanup5/hard80/exec95/remoto150/root130+grupo5/total≤300s. |

Root informó16 Management iniciados previamente; esta extensión necesaria≤11
supone techo agregado27, **no reinicio**. Sin ampliar el presupuesto Meli ni piloto.
DefaultCLI no lee env ni abre transportes. Outputs solo JSON de fields/enums/listas
cerradas, nombres canónicos, flags/counters/caps públicos seguros. Sin URL/host/vhost/
usuario/password/envvalues/bodyraw/header/errorstr/traceback/stderr libre.

## Evidencia offline y hashes

- `RED.log`: import de ensure_retries ausente, antes del behavior.
- `supervisor-RED.log`:14 PASS +6 errores por supervisor ausente, antes del supervisor.
- `GREEN-1.log`:20 PASS inicial.
- `partial-order-RED.log`:1 error/20, fake ajustado a JSON real `sort_keys=true`.
  Orden lexical de claves no es orden de RPC; fix recorre mapping fijo de buckets.
- `ruff-first.log`, `ruff-fix.log`, `ruff-formatted.log`, `mypy-first.log`:
  fallos originales preservados; tipos/layout/noqa específicos corregidos sin reducir gates.
- `final-unittest.log`:20 PASS/0skip,0.454s.
- `final-ruff.log`, `final-format.log`, `final-mypy.log`:PASS, tres fuentes.
- Representativos stdin de ambas CLI sin env:exit2, counters0, JSONsafe, stderr vacío;
  stdout/stderr propios preservados. No transporte iniciado.
- `source-binding-receipt.json`:embedding exacto, AST3.9, **28 hashes previos intactos**.
- Sin suitegeneral, sockets de aplicación/puertos/DNS real, Docker real, Mongo,
  producción, Git mutante, builds, dependencias, compartidos o agentes adicionales.

| Fuente | SHA256 |
| --- | --- |
| ensure_retries.py | `23b3a537e28b904de3f8dc141fa7556f5bf76e1858c53faee7098ec29049d3a1` |
| ensure_supervisor.py | `f108d0580a8cc7d63c666ef2d1ae9c2a02a0b5de3c502616e1cd35178a43ad72` |
| test_ensure_retries.py | `7ccc19a5102a5e950b1e2899901e282c9f692609263b43f13c3dd0f995097f19` |

Frozen repair:`8b34b81a495fd33b55eaae640289fc0eb703fdd63343f92081880c7715939165`;
reviewed:`816e2c4511bf6fff38a41b93d0092463337ddebd7ef1094824e74df085041202`;
canon:`66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
Los cuatro hashes finales (incluido este informe) están en `delivery-receipt.json`.

## Desvío de path local declarado

La primera redirección GREEN creó/escribió por error
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/GREEN-1.log`,
fuera del subdirectorio asignado. No sabemos si existía antes ni si sobrescribió
contenido previo: **no se afirma preservación del contenido anterior desconocido**.
Desde detectar el desvío no se borró, movió ni reescribió; se copió únicamente al
directorio de esta entrega y se comunicó a Root.2969bytes, SHA256
`385a2ef4820a8867ee9edaa7426f06293d9a0a091368e88d2c1758080db6885e`.
El recibo registra esta incertidumbre; Root revisará metadata/nombre por separado.

## Limitaciones y entrega

GREEN acredita preparación local, no reparación/cleanup remoto ni entrega TTL/DLX
end-to-end. No demuestra ingreso futuro acotado/no pérdida ni activa piloto.
Propiedad de los cuatro archivos devuelta; **ENTREGADO; NO SIGO MODIFICANDO**.
