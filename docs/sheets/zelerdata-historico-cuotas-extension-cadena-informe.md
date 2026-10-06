# CUOTAS — encadenar una segunda prórroga explícita sin nuevo crédito

**ENTREGADO; NO SIGO MODIFICANDO.** Test/propuesta local solamente. Canonical OPS `infra/operations/zelerdata_history_pilot.py` permanece reservado Root y sin editar por child. No nueva aprobación recibida, apply, Mongo/red, producción, Git/build, agentes ni generales. Worker build de632a/sourcec1 ya verificado según Root: este followup OPS no requiere reconstruir imágenes runtime.

## Defecto actual y RED

`_extend_paused` exige previous_until<=originalprepare+90min y `_extended_resume_end`/`_extended_repause_end` repiten esa condición. El deadline actual08:17:23 es resultado de primera extensión, no del prepare90min. No puede tratarse como primer caso ni fabricarse prepare/pausa/extensión nuevos para franquear el gate.

Nuevo test `tests/test_zelerdata_history_pilot_extension_chain.py`:
-24 fakes offline, **23 FAIL /1 PASS** en `pilot-extension-chain-20261006/red-delivery.log/xml`.
-23 fallan por kwargs/CLI previous_extension_receipt aún ausentes; el caso sin padre rechaza correctamente la segunda extensión. No se afirma23 fallos semánticos ya ejecutados ni GREEN funcional.
-Ruff/formato/mypy1 PASS en logs delivery. Primeros errores de imports/typing preservados y corregidos sin reducir checks.

Todas autoridades nuevas en tests están rotuladas SYNTHETIC FUTURE APPROVAL; received2026-10-06T10:00Z/approved12:00Z son **fixtures, no permisos ni propuesta productiva actual**. Datos actuales81/79/24 permanecen y deadline real08:17 expirado no cambia.

## API aditiva propuesta para Root

Añadir a control_pilot/resume/extend-paused transporte opcional:
`previous_extension_receipt:bytes|None`, `previous_extension_receipt_sha256:str|None`.
Reutilizar `original_paused_receipt`/SHA para raíz de primera extensión y `consumption_receipt`/SHA existente para baseline actual. CLI `--previous-extension-receipt-in/--previous-extension-receipt-sha256`, mismo loader1MiB/symlink/PIN y dry-run default.

**None/default:** preservar exactamente las ramas actuales primera extensión/resume/repause y sus tests; inputs parciales o padre ausente no constituyen excepción al90min. La nueva rama chain se selecciona solo con previous raw+PIN completos. Canonical no debe mutarse antes del RED recibido.

## Validador de cadena — contratos precisos

Separar validación **histórica** del padre de autoridad **vigente** nueva. No reutilizar `_extended_repause_end` con now inventado: el padre ya puede estar vencido legítimamente.

1. Preparado original aplicado y PINb886 real (en producción), pausa raíz original aplicada/PIN y previous extensión aplicada/PIN3a2 real atestada por ledger Root. Seller/policy/EID coinciden; no snapshots/UUID nuevos. Previous.preparedPIN=originalpreparePIN; previous.pausedPIN=originalpausePIN; previous.previousPlanSHA=originalpause.resultingPlanSHA. AuthoritySHA64 y hashes64 válidos.
2. Raíz: started<previous.previous_until<=min(started+90min,finUTCday); pausa raíz<=previous_authorized<=previous_observed, previous_approved>previous.previous_until y<=previous_authorized+previous_duration<=2h; approvedDate=originalUTCday. El padre histórico conserva su fecha aunque now>previous_approved. No da autorización actual por sí mismo.
3. Pausa **actual** aplicada/PIN y resultingPlanSHA==_plan_hash(currentplan); PAUSED/scope5/eligible/authority existente/runtime_verified, sin livelease. Sameexecution/day/cutoff/range/quotas/fields. `previous.execution_until_utc == currentplan.execution_until == nueva_authority.original_until_utc`.
4. Nueva autoridad pinada, authorization_received is True, no_new_credit/full_excluded True, sameoriginalprepare/EID, currentpausePIN y nuevo campo **previous_extension_receipt_sha256** exactos. Debe corresponder a un mensaje humano futuro realmente recibido; no copiar la autoridad vieja ni tratar fixture como autorización.
5. Orden: previous_observed<=currentPause<=new_authorized_at<=now<new_approved_until. Newuntil>olduntil; max_additional_seconds entero estricto1..7200 (no bool), newuntil<=new_received+duration; todos pertenecen a originalUTCday. Fuera del día, futuroclock o nueva ventana ya vencida: STOP. Una concesión recibida antes del viejo vencimiento también queda acotada por su propio received, no se suman automáticamente2h al antiguo until.
6. Reusar caps del prepare; además current initial_remaining/maintenance_remaining/maintenance_source_remaining<=previousextensionremaining, exactmap5 y no daily rollover. Baseline independiente actual81charged/79sent/24maintenance, outer/reader PASS+no_refund+cleanup/innerpausePIN, snapshot correcto y clocks≤currentpause/newapproval. Current counters>=baseline y sent<=charged. No inferir69/67 de saldos ni mover budget/counters/leases/checkpoints/registry/data/jobs.
7. La mutación permanece **solo execution_until**, PAUSED, mismo whole-documentCAS y readback. Drift aborta; no retries ni autoprovider. Guardrails explícitos/runtime confirmaciones y receipt exclusivo ya existentes siguen intactos.

El resultado aplicado conserva actuales fields de lineage y añade `previous_extension_receipt_sha256`, `original_paused_receipt_sha256`. previous_planSHA corresponde a pausa actual; resultingPlanSHA al snapshot deadline-only; originalpreparePIN nunca cambia. Recibos viejos no se reescriben.

## Resume después de la nueva extensión

Primera reanudación del nuevo step usa su pausa **genuina previa al apply** y puente latest.previousPlanSHA→latest.resultingPlanSHA==currentplan; no necesita fabricar pausa postapply. Previous raw/PIN + original raíz siguen presentes para atestar lineage. Seleccionar esta rama antes de los gates actuales que fuerzan original_paused→repause/currenthash y90min, sin cambiar defaultsNone.

Latest.previous_until=previous.approved; latest.preparedPIN original; latest.pausedPIN pausa del nuevo step; latest.previous_extensionPIN coincide con padre; autoridad nueva/clocks/endBound coherentes. Resume cambia únicamente state. Si se exige baseline postapply independiente para futuras re-pausas, debe obtenerse genuinamente: no actualizar/copiar recibos anteriores en producción.

Para una tercera o mayor extensión, exigir ancestry completa autenticada por receipts/pins o un envelope de cadena incluido por el operador; nunca asumir que un previous_until>90min es por sí mismo historia autorizada. Este test cubre **dos extensiones**, no promete cadena arbitraria ni aprobación futura.

## Casos y límites

Dry/apply segundo step y resume puente; padre ausente/PIN/applied/clock/EID; pausa raíz/actualPIN; not_received; bool/>7200/futureclock/overday; changedEID/Fullscope; initial/daily/source/sent refunds con snapshots vueltos a ligar para que falle crédito y no hash accidental; consumptionPIN/livelease y CASdrift; parser flags.

Fakes de BSON/whole-documentCAS reutilizan archivo tests existente sin modificarlo. Socketconnect/connect_ex prohibidos, env whitelist sin URI/AMQP/secrets/autoplugins, --noconftest -oaddopts='' --import-mode=importlib. Sin Mongo/network/puertos/fixtureconftest/general/SDD. Logs privados nuevos O_EXCL preservados.

Lecturas: OPS+testextension+testrepause (3archivos); ningún private receipt real adicional leído. Contexto3a2/b886 es evidencia Root/ledger, no creado ni certificado por child. Contrato nuevo necesita GREEN Root y generales antes de publicar; ninguna operación ni imagen nueva autorizada por esta propuesta.

TestSHA256: `5d48eff8404685923a66f762a498d3eb8107f906dc33f4c1a5f5ed0fab1db508`. InformeSHA por chat para evitar autorreferencia.

**ENTREGADO; NO SIGO MODIFICANDO.**
