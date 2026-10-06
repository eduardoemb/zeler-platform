# Shipments: publicación durable por identidad — sólo local

**ENTREGADO; NO SIGO MODIFICANDO.** Trabajo local autorizado hasta
2026-10-06T21:31:13Z; ninguna operación productiva, build, Git, red, Mongo real,
agente ni suite general. Esto no amplía el piloto vencido ni sus presupuestos.

## Contrato implementado

`FormulaRecoveryQueue.initialize_shipment_cursor(job)->int` valida el binding
key/list/seller/model/authority y cursor entero no-bool, con ownership/lease.
Ausencia genuina inicializa offset0 por CAS **antes del primer RPC**. Null,
malformación, lease/list/key drift o rechazo del validator impiden el RPC.
Cursor existente/no-op no demuestra compatibilidad futura del validator: Root
debe inspeccionar metadata runtime antes de un eventual despliegue; no reparar
validators ni inventar schema/model/Core en este cambio.

`checkpoint_shipment_cursor(job, expected_offset, next_offset, session)->bool`
liga owner/state/lease, seller/model/list/key y offset anterior. Resource+readback+
cursor y final finish de la última unidad comparten transacción
**snapshot/majority**. CAS perdido revierte sólo la unidad actual; las anteriores
persisten. El job dict capturado no se muta para fingir avance antes del commit.

Los 100 IDs y key originales permanecen inmutables. Cursor absent no recupera
payload ni progreso de250 cargos pasados. No reset/refund/rekey/phaseflip,
créditos, lease artificial ni marker anual. Budget6/3IDs conserva2resources;
budget250/100IDs conserva83unidades y el RPC250 parcial no crea otra concluida.

Costtransient conserva campos independientes y deja offset sin avanzar/pending;
oldcache mantiene su synced_at y unavailable_fields, nunca costo cero/freshness
inventada. El contrato ordinario de ausencia opcional/errores400–403 conserva su
limitación previa: este cambio no certifica semánticas nuevas de costos.

## Ciclo ordinario, API y compatibilidad

Canonical refresh de COMPLETED con cursor concluido archiva metadata compacta
real (`offset`, `completed_at`, request key/seller/model) en
`shipment_cursor_history` y arranca ciclo nuevo0, sin cambiar key/list.
Failed parcial conserva offset y attempts; pending/running no se resetean.
H1 `reopen_terminal=False` permanece intocable. Legacy absent no se considera
concluido ni se genera archivo falso. El campo archive tampoco implica arreglar
runtime validators automáticamente.

API/formulas → `queue.enqueue` cambia comportamiento, y worker → `_shipments`
cambia publicación. **Imágenes potencialmente afectadas: sheets-api y
sheets-worker.** Futuro orden compatible API nueva primero, worker después;
ausencia legacy es compatible. API vieja + worker cursor nuevo puede reabrir
offsetlen sin reset y fingir renovación ceroGET. Rollback API3f7/worker antiguo
tras cursores sólo se considera CLOSED, no equivalencia ordinary activa ni
permiso para borrar cursores. No build/deploy ejecutado ni autorizado aquí.

## TDD y verificación

- RED inicial antes de fuentes: **10 FAIL, 0.60s**. Los positivos budget
  publicaban0; otros fallos exhibían cursor ausente y txn sin garantías explícitas.
- Lifecycle RED **3 FAIL/1 PASS, 0.41s** antes de modificar enqueue. Un primer
  fallo de harness sin `collection.database/with_transaction` se preservó
  separadamente y se corrigió en el test nuevo.
- GREEN nuevo **16 PASS**. Con101 regresiones offline: **117 PASS, 0.94s**.
- Sentinel antiguo `test_formula_recovery.py` de quota: **4 PASS/458 deselected,
  0.43s**. Tests shipments4860/5033 requieren `recovery_db` Mongo27028: **NO
  ejecutados**. Ningún fixture ni assertion antiguo editado.
- Ruff/formato y mypy de cuatro targets PASS, sin reducción/ignores/config nueva.

Comando enfocado: `.venv/bin/pytest` con el test nuevo, capacityQ/diagnostic y
gateway allocation fakes, `--noconftest -o addopts='' --import-mode=importlib -q`;
entorno limpio y sockets prohibidos. Logs privados O_EXCL en
`monitor-guard-20261006`: red-shipment-cursor/reopen-real y green-regressions117,
más calidad. No se ejecutó `test_shipment_cursor_publication_rs0.py`.

## rs0 preparado, pendiente Root

Cuatro casos reales preparados: persistencia2units+snapshot/majority;
validator rechazo0RPC; rollback publicación actual; resume sólo unidad3.
Exige `ZELER_RS0_TEST_URI` loopback, MONGO_URI ausente, PRIMARY/rs0/session,
DB única y limpieza propia. No son evidencia real hasta ejecución Root; ningún
SKIP se presentará como PASS. La carrera real de takeover/driver y compatibilidad
de validators runtime continúan como gates Root.
