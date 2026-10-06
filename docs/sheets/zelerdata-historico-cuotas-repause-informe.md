# CUOTAS — reanudar después de una re-pausa real bajo la misma prórroga

**ENTREGADO; NO SIGO MODIFICANDO.** Solo tests/propuesta; canonical OPS permanece reservado Root y sin editar por este especialista. No producción, DB, network, Git/build, agentes ni suite general. No SDD ni reprepare/nuevo UUID/plazo/crédito.

## Hechos e incompatibilidad

`infra/operations/zelerdata_history_pilot.py:501-538` solo reconoce la primera reanudación: extensión.previous_plan_sha256 liga la pausa previa a autorizar y extensión.resulting_plan_sha256 liga el snapshot inmediatamente extendido. `_resume:294-350` delega esos checks y espera stopped<=authorized<=extensionObserved. Una pausa auténtica posterior, con cargos/counters avanzados, legítimamente cambia hash y ocurre después de authorized. **No** se resuelve falsificando receipt de extensión/pausa ni relajando current snapshot.

Root reporta SAMEexecution868b413e20184befb7e8358e0051924f, PAUSED75charged/73sent, maintenance19, initial56, until08:17:23Z/Full0. Esto es evidencia Root, no operación de este especialista.

Tercer artefacto exacto leído (sin datos/secretos):
`rollout-preflight-20261006/PILOT-RELAY-CLEANUP-STOP-PAUSE-1-END.json`
SHA `6c072b63ee0a622aca7aa690fac624687bbddd6c23f8a5ef42a3fd6919384ee1`.
Outer status pass, ended07:23:28.319145Z; reader status pass, no_refund_or_reset true, charged75/sent73/maintenance19. Identidad/hash/clock están realmente en **reader.receipt**, no en reader u outer: appliedpauseTrue/EID correcto/resulting_plan_sha256 `9dc6c523a701a5f86238a25dc414b4a40ce8981f2cb6f0728b13c120cdb5a886`, observed07:23:27.654508Z; reader.receipt_sha256 `560a6b46c6c67c3fe1424400469053fd4e31a3f35bdbfa7e5467c88090396e20`.

## Patch mínimo propuesto — Root writer

Añadir kwargs opcionales `original_paused_receipt`/`original_paused_receipt_sha256` y `consumption_receipt`/`consumption_receipt_sha256` a control_pilot; transportar a `_resume`/`_extended_resume_end`. CLI flags `--original-paused-receipt-in/--original-paused-receipt-sha256`, `--consumption-receipt-in/--consumption-receipt-sha256`; loader mismos límites existentes1MiB/symlink/pin, solo action resume. Sin schema/model/newplanfields, sin imagen afectada por este tool OPS.

**Defaults None:** mantener cuerpo legacy y primera reanudación extendida exactamente (incluida comparación extension.resulting_plan_sha256=currentplan). No reinterpretar sus receipts ni modificar sus tests23. Inputs parciales/nuevos sin extensión: rechazo, no fallback.

**Nueva rama re-pausa, solo con los cuatro inputs nuevos presentes:**

1. Preparado original aplicado/pinado, pausa original aplicada/pinada, extensión original aplicada/pinada, pausa actual aplicada/pinada y consumo externo pinado. Seller/policy/execution exactos. Ext preparedPIN=originalpreparePIN; ext pausedPIN=originalpausePIN; ext previousPlanSHA=originalpause.resultingPlanSHA. Ext resultingPlanSHA anterior conserva su SHA64 y receipt autorizado original (Root3a2...), **no** se sustituye por el plan actual9dc6 ni se fabrica nueva extensión. Pin autorizado original debe verificarse contra ledger Root, no aprobar archivo reconstruido.
2. Pausa **actual** siempre debe tener resultingPlanSHA==_plan_hash(currentplan), independientemente de extensión. StatePAUSED/scope5/eligible/runtime verified y límites actuales conservan gates existentes. AuthoritySHA64 original dentro de extensión y fechas/bound2h/sameUTCday/approvedUntil==plan.execution_until, sin renuevo.
3. Reusar checks originales de autorización con la **pausa original**, no la nueva: started<=originalPause<=authorized<=extensionObserved. Luego extensiónObserved<=currentPause<=now<approved; original/actual ejecución mismo día. No exigir currentPause<=authorized porque es la contradicción actual.
4. Consumo: verificar SHA bruto externo (el archivo exacto autorizado), outer status pass y reader status pass, reader.no_refund_or_reset is True (no truthiness). reader.receipt debe ser applied pause pinado con SHA computada mediante receipt_bytes(inner), seller/policy/EID correctos y resultingPlanSHA==currentPauseSHA==whole currentplanSHA. Clock interno extensionObserved<=consumptionInnerObserved<=currentPause<=now; outer ended no futuro y no antes de inner observado. Esta autoridad externa independiente **no** reemplaza currentpause, ni inventa campos de recibos viejos.
5. Valores enteros estrictos (no bool) de baseline real75/73/19 y actuales; current.execution_consumed>=baseline.charged, current.execution_sent>=baseline.sent, current.incremental_consumed>=baseline.maintenance. Sent<=charged y ejecución límite<=2500/charged<limit se mantienen. Todos límites actual<=originalprepare autorizado; initial por fuente<=800/150/250/300/500, total<=2000; maintenance<=500 y<=300/source; Full0 crédito, day actual/maintenance mismaUTC sin rollover nuevo.
6. **Además** bound saldo, no convertir remaining en caps: para cada fuente current `_summary.initial_remaining`<=extension.initial_remaining; current maintenance_remaining<=extension.maintenance_remaining y current maintenance_source_remaining[source]<=extension.maintenance_source_remaining[source], todos mapas exactos5/enteros y no rollover pendiente. `_resume_caps` original permanece; no reutilizarlo con extensión porque ese helper exige daily_rollover_pending True del prepare, mientras extensión contiene False. Rechazar counters sobre sus límites, malformados/desconocidos o saldo aumentado, sin clamp usado como autoridad.
7. Patch único `{state:active}` mediante whole-document CAS existente+readback. No updates a créditos/counters/checkpoints/range/cutoff/jobs/leases/extension_until. Cualquier drift: STOP y cero reintentos. Pausa no equivale a quiescencia, runtime controls Root siguen gate independiente.

## Prueba y límites

- Baseline inicial de charges/sent **no existe** en extensión vieja: no se infiere69/67 desde remaining. Se usa el receipt externo real75/73/19 que liga snapshot actual independiente. Source counters absolutos anteriores tampoco se reconstruyen desde jobs/progress; remaining impide saldo nuevo y CAS state-only preserva todo lo presente. El flag no_refund_or_reset del lector Root y sus SHA son evidencia adicional explícita, no matemática inventada de historia.
- Extensión result hash anterior no puede igualar snapshot avanzado: confiar en su digest original autorizado es condición del nuevo path. La prueba nueva no demuestra por sí sola firma humana, AMQP terminal, health ni aceptación; Root conserva ese ledger y gates.
- Fakes BSON/whole-docCAS reutilizan fixtures existentes sin editarlas, sockets denegados, env whitelisted sin URI/AMQP/credentials. No test con DB real ni shadow patch.

## RED entregado y controles

Logs O_EXCL en cache `extension-repause-20261006`:
- `red.log/xml`:18 FAIL originales; incluye rechazo real extension_receipt_lineage antes de añadir contrato y los nuevos kwargs/CLI inexistentes. No se afirma que esos18 sean28 regresiones runtime.
- `red-consumption.log/xml`:22 FAIL/1PASS, parentless repause failclosed.
- Final `red-delivery.log/xml`: **27 FAIL/1 PASS (28casos)**. Los27 son interfaz/flags nuevos aún ausentes; tests negativos requieren PilotControlError, no TypeError. Canonical sigue sin cambios. **GREEN comportamiento pendiente de patch Root.**
- `ruff-delivery.log`, `format-check-delivery.log`, `mypy-delivery.log`: PASS (un target, estándar/sin ignores).

Casos: dry/apply stateONLY75/73/19, missingparent, parent/current/ext PIN/identity/snapshot/applied/clocks; consumption PIN/missing/outer+readerPASS/no_refund/innerPIN/snapshot/future; charge/sent decrease; initial/daily/source refund/bool; livelease; CLI. Refund/counter fakes vuelven a ligar sus snapshots (mantienen baseline75/73/19) para que el check específico de crédito falle, no solo hash accidental. No nuevos casos marginales.

## Archivos y hash

Lecturas funcionales: canonical OPS + test extensión existente23 + un artefacto privado sanitizado. Writers únicamente este informe y `tests/test_zelerdata_history_pilot_extension_repause.py`.

Test SHA-256: `6ac43a657529a1895d18c8bc085da06038da58fc3aecb2327e35e3f426b0a0da`.
Informe hash por chat, sin autorreferencia. Root integra canonical y después puede dar turno GREEN enfocado; hasta entonces cese total.
