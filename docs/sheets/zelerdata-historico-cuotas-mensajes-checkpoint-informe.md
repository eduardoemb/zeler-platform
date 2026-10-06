# CUOTAS: continuación del checkpoint de mensajes tras BSON

**ENTREGADO; NO SIGO MODIFICANDO. Fix local, no replay ni producción.**
Tres writers exactos: `modules/sheets/src/zeler_sheets/history_onboarding.py`, nuevo
`modules/sheets/tests/test_history_messages_checkpoint_resume.py` y este informe.
`onboarding_sources.py` solo leído/intacto; Core/Gateway/config/deps/locks/central
docs/Git/build/runtime y tareas AMQP reservados Root. Sin agentes/suite general.

## Causa reproducida y evidencia productiva separada

El sweep ya conserva `sweep_start/sweep_end`; **movingend no era el defecto**.
También el collector usa checkpoint.target_ids si existe (`onboarding_sources.py:212`):
recalcular targets desde orders no provoca por sí solo el mismatch.

BSON conserva datetime a milisegundos; el checkpoint mantiene su identity ISO
original con microsegundos. Worker usa tz_aware=True (`consumer.py:1531`), así
que no atribuí el fallo a pérdida de timezone. Al retomar, el caller entregaba
sweep_end truncado y `_state:85-92` rechazaba su ISO distinto del checkpoint.end.

Root aportó **POST-STOP-CHECKPOINT-SHAPE-1**,04:39:18UTC/PRIMARY/2reads/0writes:
seller/source correctos, start exacto,40targets/pending0; sweep_end
`2026-10-06T04:30:45.407000+00:00` vs checkpoint.end inmutable
`2026-10-06T04:30:45.407414+00:00`: igualdad falsa, mismo milisegundo BSON.
Es el mismo mecanismo del RED local. Esa lectura la hizo Root, no CUOTAS.
La observación previa de ValueError sola no bastaba para atribuir causa.

## Delta mínimo

`history_onboarding.py:108-124` recupera el datetime aware original de cada bound
ISO del checkpoint, **solo si coincide con el bound durable a precisión BSON**.
El caller periódico `:769-782` entrega esos originales al collector. No modifica
checkpoint.start/end ni sweep_start/end almacenados; no cambia clock/cutoff,
ventana, targets congelados, pending, estado inicial, ownership o h1 budgets.
Un cambio real de rango, seller/source distintos o bound inválido sigue ValueError
antes de transporte. `_state` y su comparación exacta permanecen intactos.

No borra pending ni reinicia offset0, sweep o el inventario. Los siguientes GET
se cobran por la autoridad existente de cada intento; el fix no agrega retry,
refund, crédito, recobro de páginas ya adquiridas ni actualización de deadline.
La equivalencia de milisegundos valida la relación con el storage; el checkpoint
original conserva la precisión que BSON no representa, no se extiende al now nuevo.

## TDD y controles

Solo fakes locales y roundtrip BSON real **en memoria**, sin servidor Mongo.
Sockets bloqueados y ambiente del runner whitelisted, sin MONGO/AMQP/Rabbit URLs.
Siete casos: restart con micros+offset100, inventario cambiado/targets congelados,
cuatro identidades/rangos alterados rechazados, policy WAIT sin perder pending.

| Log privado `messages-checkpoint-resume-20261006/` | Evidencia |
| --- | --- |
| red.log/xml inicial | 3FAIL/4PASS; dos identity mismatch y un fallo de interfaz del fake |
| green.log/xml intermedio | Fake sin fetch_resource público:3AttributeError; conservado |
| green2.log/xml | 6PASS/1FAIL: fixture no incluía type_index0 original del collector |
| red-faithful.log/xml | **3 identity mismatch FAIL /4PASS**,0.10s, contra blob original SHA-bound reconstruido en memoria |
| final-green.log/xml | **7PASS /0skips**,0.32s, bytes finales |
| final-ruff/format/mypy.log | **PASS estándar**, dos targets completos, sin ignores/reducir checks |

Se corrigió solo el fake para exponer fetch_resource→una llamada once sin retry,
y type_index0 que `_state` ya crea. RED fiel usa exactamente el blob original
SHA`a68908bfb0e7b3dc26996e3154d337c4d4402709d4f6be8f2dadd065cc9dabdf`,
reconstruido verificablemente **sin escribir/revertir source**; por ello los tres
fallos son del código original con la misma fixture final. No RED artificial de
comportamiento nuevo ni debilitamiento de identidad para hacer pasar el test.
O_EXCL/log0600, caches propias/offline/no-sync/noconftest; logs fallidos intactos.

Secuencia física fake:0,50 → restart →100,150,151 filas; no replay de página0.
Pending/offset/rango/collector inicial conservados en WAIT. Los tests prueban
ausencia de cambios a campos de cuota/ID/plazos por este fix, **no** consumo ni
transporte real; las garantías de cobro real siguen en PlanBudgetGateway/Gateway.

## Preservación y límites operativos

Root confirmó cierre forward04:36:19 con historyOFF/HOLDtrue, PAUSED,
69charged/67sent,56initial/13maintenance, Full0; ningún refund de diferencia2.
Execution ID/día/cutoff y **hasta05:52:57.845UTC original** permanecen; no reprepare,
otra ventana, reinicio de cuotas, patch productivo del checkpoint ni replay.
Root únicamente decidirá publicación/build afectado/rollout y resume canónico
compatible bajo los gates vigentes; no lo ejecutó este especialista.

El símbolo cambiado pertenece al **Sheets worker**. No requiere Gateway/API
rebuild por este delta; Root verifica source/image/compatibilidad y controles
conjuntos después del cese. Que el arreglo esté GREEN no reabre producción ni
completa aceptación de cinco fuentes/dos cambios reales/lectores nativos.

## Hashes de entrega

| Archivo | SHA256 |
| --- | --- |
| history_onboarding.py final | `2b7a69437fbf4589e8dff60a26fa5fd95d8b8ec01f00a657ab61abf3561cc6e9` |
| test_history_messages_checkpoint_resume.py | `5cb5773cc0669e479791d5b6e972e1750260bd34a8c9696fe73eaa16205b1153` |
| onboarding_sources.py intacto | `096e09defd6a1476251871a40230c77f36bd26f54b567e646cd66de24480fcb4` |

Hash de este informe/logs en `delivery-receipt.json` privado. No modificación
ejecutable tras GREEN/quality; Root recibe propiedad solo después de este cese.

## Key Learnings:

1. Un datetime BSON pierde microsegundos aunque mantenga timezone correcto.
2. El checkpoint ISO conserva la identidad del intervalo original; no reescribirlo
   para ocultar un mismatch del caller.
