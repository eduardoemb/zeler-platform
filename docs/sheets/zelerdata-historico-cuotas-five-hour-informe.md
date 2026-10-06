# CUOTAS — cinco horas explícitas y pausa posterior verificable

**ENTREGADO; NO SIGO MODIFICANDO.** Test/propuesta y GREEN sobre patch Root; canonical OPS no fue editado por child. Sin DB/red/producción/build/Git/general/agentes ni tareas AMQP. La aprobación humana real permite hasta5h desde recepción **2026-10-06T15:32:58Z**, techo **20:32:58Z**; preparación no reinicia reloj ni añade crédito/seller/EID/day/cutoff/Full.

## Contrato aplicado por Root

- Authority opt-in JSON `five_hour_extension_authorized:true` permite max_additional_seconds entero1..18000. Ausente/false conserva7200; otros tipos, bool duration,18001 o techo temporal mayor rechazan.
- Receipt latest añade `extension_duration_ceiling_seconds:18000` solo para opt-in verdadero. Receipt missing ceiling interpreta legacy7200; ceiling bool/tipo/valor impropio no amplía alcance.
- Techo latest se verifica en chain resume y repause; `_chain_parent` histórico y primera extensión legacy siguen7200. No reescribir padre/prepare ni inventar UUID/window/receipts.
- Mutación única execution_until, planPAUSED; samefullCAS/readback, scopes/budgets/counters/inicial/mantenimiento/sent y deadline absoluto. Resume cambia solo state. Metadata-only fence posterior requiere pausa/consumo reales y no crea saldo.

## Testigo de PAUSED anterior — sin timestamp fabricado

El consentimiento llegó antes de nueva captura freshpause. No se relaja stopped<=authorized universalmente:

`pre_authorization_paused_receipt`/SHA opcionales deben ser appliedpause genuino, mismo EID/policy, observed<=received y wholeplanSHA igual al freshsnapshot **antes de cambiar deadline**. Se exige received<=freshpause<=now, snapshotactualPAUSED/hashactual; si no hay testigo o difiere, STOP.

Latestreceipt lleva witnessPIN. Resume/repause validan testigo contra **latest.previousPlanSHA**, no contra CurrentPOSTfence; la pausa actual posterior sigue bind FULLcurrentplan independientemente. API pública para pausa del step es `extension_paused_receipt`/SHA; `step_paused_*` son nombres internos, no alias nuevo.

Root reportó preflight realPASS15:40:58: planSHA153a6... idéntico al testigo aplicado07:47:53.844043Z, PIN47ba2f0637d49f12b8f8cdcb370d91fd2b5b72120afe8504b613e4fcc51a1848. Bytes auténticos/contexto/operaciones son responsabilidad Root; child no consultó VM ni genera esa evidencia.

## RED/GREEN y límites

26 fakes offline (24 originales + dos guards finales autorizados por Root):
- `red.log/xml`:10FAIL/14PASS antes de patch Root, por7200 vigente y nuevo witnessAPI ausente. Fixture inicial post-fence usaba nombre interno; preservado, no confundirlo con fallo semántico.
- `red-api.log/xml`:10FAIL/14PASS con API pública corregida antes del patch.
- green.log/xml:24PASS,0.18s antes del guard final de binding.
- red-latest-witness.log/xml:1FAIL/1PASS; borrar el witnessPIN del latest receipt y re-pinar permitía CAS, aunque argv incluía testigo válido; mismatch ya rechazaba. Root corrigió require_binding=True únicamente en los dos paths latestresume.
- **green-final.log/xml:26PASS**,0.18s sobre canonical Root final. Latest latepause exige witnessPIN PRESENTE y exacto en el receipt, no solo argv.
- **legacy-final.log/xml:124PASS**,0.30s (cinco focos OPS existentes, no suite general); lote previo124PASS preservado.
- Ruff/formato/Mypy1 PASS en quality-final logs, configuración estándar/sin ignores.

Casos dry/apply pre/currentfreshpause, ceiling flag exacto, missing/false/bool/tipos,18001/day/deadline+1, witnessmissing/drift/future/PIN, latestreceipt tamperedceil, post-fence genuina repause, counters81/79/24preservados/refundrechazado y parentlegacy7200sinupgrade.

Fixtures temporales imitan instantes para aritmética y están rotuladas SYNTHETIC; **no son** artifact real de autorización ni PIN productivo. Socketconnect/connect_ex prohibidos/env whitelist sin URI/AMQP/secrets/autopluginsOFF/noconftest/importlib; noDB/puerto/HTTP. Logs O_EXCL0600 preservados en cache `/Users/eduardoramirez/.codex/cache/zelerdata-integracion-20261006-five-hour-tests`.

Root escribió/validó OPS helpers `_chain_duration_ceiling` y `_chain_pause_order`, kwargs/CLI y clocks. No runtimeproductcode/model/config cambiado por child. OPS-only no rebuild por esta unidad; build/deploy del worker afectado por otros fixes siguen operaciones distintas Root. Controles conjuntos/aplicación/lectura física/piloto/fuentes/calendar/nativeSheet/dosincrementales permanecen pendientes, no objetivo completo.

TestSHA256: `7b9afbbd8fed9574a37efec0d985b3036c199ce1dcb24af5ebd0e860512f6ecf`. InformeSHA por chat para evitar autorreferencia.

**ENTREGADO; NO SIGO MODIFICANDO.**
