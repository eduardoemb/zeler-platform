# CUOTAS: retry DB-only del acquire abortado por WriteConflict

**ENTREGADO; NO SIGO MODIFICANDO. Propuesta GREEN shadow; Core real no editado.**
Dos writers exactos: nuevo `core/tests/test_devoluciones_acquire_transient.py`
y este informe. Lectura limitada a función Core, tests existentes, nuevo test y
caller Sheets. Sin otros archivos funcionales, network/DB/prod/Git/build/agentes,
suite general, schema changes, broker replay/dequeue/ACK/body o provider calls.

## Hecho y alcance

Root extrajo del **mismo** registro productivo: code112/WriteConflict y
TransientTransactionError, `consumer._handle_message:552 → handle:1218 →
devoluciones_readiness.acquire_devoluciones_operation:137`, freshness.update_one
dentro de transacción **antes** del Gateway fetch. No121/auth/HTTP probado.
DLQ1 y PAUSED69/67 permanecen. Esta evidencia es de Root, no una repetición aquí.

El caller genera operation_id y attempt_token una vez (`consumer.py:1218-1225`).
`devoluciones_readiness.py:124-220` contiene marker/readiness/lease en una sola
transacción; el WriteConflict temprano sale sin retry. Al abortar, los cambios
parciales no se comprometen. El retry debe repetir esa **unidad completa**, no
solamente freshness.update_one, ni el consumer/Meli/publish fuera de ella.

## Patch exacto mínimo propuesto a Root

En **el mismo archivo Core**, importar `OperationFailure`; renombrar el cuerpo
actual intacto a `_acquire_devoluciones_operation_once` y mantener el nombre/API
público como wrapper, con la **misma firma explícita/defaults y mismos kwargs**:

```python
for attempt in range(3):
    try:
        return await _acquire_devoluciones_operation_once(
            db=db,
            seller_id=seller_id,
            scope=scope,
            operation_id=operation_id,
            attempt_token=attempt_token,
            source_fingerprint=source_fingerprint,
            invalidate_readiness=invalidate_readiness,
            require_coverage_compatible=require_coverage_compatible,
        )
    except OperationFailure as error:
        if (
            attempt == 2
            or error.code != 112
            or not error.has_error_label("TransientTransactionError")
            or error.has_error_label("UnknownTransactionCommitResult")
        ):
            raise
        await asyncio.sleep(0)  # yield/cancellation; no unbounded backoff loop
raise AssertionError("unreachable bounded transaction retry")
```

Tres **intentos totales**, no3retries extra. Cada `_once` abre y termina su sesión/
transaction antes del siguiente; excepción sólo112+label y sin commit incierto.
No `with_transaction` automático que también repita commit, kwargs nuevos,
callbacks de negocio, nuevo token/UUID/opID ni writes fuera del txn.
Conservar `$$NOW`, lease120s y todos los guards/coverage/takeover del cuerpo
original. Fence/epoch/checkpoint se vuelven a leer del último estado comprometido;
no incrementarlos por número de intento ni reparar/resetearlos manualmente.

El `operations.update_one` posterior ya envuelve errores en lease conflict
(`:209-219`): **no ampliar ese catch ni desenvolver causas en este primer fix**,
según alcance Root. No retry de121/auth/no-label/UnknownTransactionCommitResult
ni reconocimiento optimista de commit incierto. Cancelación sigue propagando.

## TDD fiel y límites

Fake transaction mantiene un working snapshot separado; writes parciales se
descartan al abort y se publican sólo al commit. Unknown commit simula estado
que **ya pudo comprometerse** y después error: exige un único intento.
Sólo dos colecciones permitidas, sin plans/quotas/provider/cert reset; sockets
bloqueados/runner env whitelisted sin MONGO/AMQP/secret, cache privada/offline.

| Recibo privado `devoluciones-acquire-transient-20261006/` | Resultado |
| --- | --- |
| red.log/xml, función Core actual | **3FAIL /4PASS**,0.16s |
| green-shadow.log/xml intermedio |3FAIL/4PASS: binding del módulo pytest no correspondía; preservado |
| green-shadow2.log/xml, mismo test/fixtures | **7PASS**,0.03s |
| ruff.log / format.log / mypy.log | PASS estándar, test nuevo, sin ignores/reducir checks |

GREEN inyecta wrapper **solo en el módulo de test ya colectado**. Comprueba que
`core.acquire_devoluciones_operation` continúa idéntico al original; no cambia
source ni módulo global Core. Por tanto es validación de propuesta, **no**
comportamiento aplicado. Root debe ejecutar GREEN/quality sobre su patch real.

Casos: uno/dos abort112 recuperan en2/3; tres aborts agotan y propagan112;
112sinlabel/121+label/13+label no retry; commit112conUnknownTransactionCommitResult
no retry. Recuperados: único commit/fence7→8/epoch9/checkpoint intacto y mismo
operation_id/attempt_token; marker vuelve a leerse en cada txn, lease sólo la
normal del éxito. Abort3 deja documentos completos idénticos al baseline.
No assertion de recuperación de DLQ ni cuotas físicas productivas desde fakes.

## Imágenes, integración y ventanas

**Caller verificado:** Sheets worker (`consumer.py:1218`), por lo que esa imagen
está afectada. Root indicó usos bootstrap/OPS/publicación histórica; su callgraph
servido debe determinar si algún API/job requiere rebuild. No construir Gateway
o todos los servicios por mera inclusión de Core; no afirmar aquí que API está
afectado o no sin esa evidencia. No tuve permiso de leer otras rutas para cerrarlo.

Root conserva publicación/builds/gates/prod y toda recuperación del mensaje DLQ.
Este fix no reautoriza resume. ID/consumos/Full0/PAUSED, checkpoints/certificados y
**deadline original05:52:57.845UTC** se preservan; ningún reprepare, otra ventana,
lease artificial o replay productivo. Root decidirá continuar sólo si sus gates
se cumplen a tiempo, nunca extender por tests/builds. Fuente actual sigue RED.

## Hashes y cese

| Artifact | SHA256 |
| --- | --- |
| test_devoluciones_acquire_transient.py | `dc22282377640137d882502f5fb2858b4379dcf9b1f235356b1c13ec0c9f185a` |
| Core leído/intacto | `d75d6f0230b893240021d4db8701863d1765a6ac5f74e2ed87721eea1eff9620` |

Hash de informe/logs y detalle RED/shadow en `delivery-receipt.json` privado.
No source/fixture edit después de los controles. Ambos writers cesan ahora.

## Key Learnings:

1. Un WriteConflict abortado puede repetirse como unidad DB, no como negocio/Meli.
2. UnknownTransactionCommitResult nunca se convierte en permiso de repetir el acquire.
