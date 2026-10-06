# CUOTAS — continuación de Questions preservando versión original y cupo

**ENTREGADO; NO SIGO MODIFICANDO.** FASE2 local implementada en los nueve paths asignados, sin producción, DB real, red/puertos, Git, builds, agentes, Core/config/schema/index ni operador. Root valida Mongo real aislado y ocho gates del conjunto después del freeze. No nueva autorización, ventana ni cuota; ejecución productiva actual permanece PAUSED81/79/24, deadline08:17:23Z expirado.

## Quick path para integración Root

1. Cotejar nueve hashes finales y freeze completo antes de generales.
2. Validar archivo/codec/transactions/CAS sobre Mongo aislado y validators reales; fakes no prueban motor Mongo.
3. Resolver ajustes de tests antiguos que esperaban reinicio automático Questions y cotejar callgraph/images. Construcción/despliegue/runtime son gates distintos, exclusivos Root.
4. Cualquier operación futura requiere autoridad temporal realmente vigente y pins **wire BSON** frescos. Este código no permite utilizar ventana expirada ni concede ampliación.

Skills work-unit-commits/cognitive-doc-design reutilizados. Unidad entregable: readmisión explícita+preservación+materialización+tests+documentación juntos; Git pertenece Root, sin SDD.

## A — versión original + readmisión canónica

Nueva función pública de queue:

```python
await queue.readmit_question_cursor(
    request, opt_in=True, execution_id=execution_id,
    expected_plan_bson_sha256=wire_plan_pin,
    expected_head_sha256=wire_head_pin,
    expected_job_sha256=wire_job_pin,
)
```

Default no opt-in rechaza, `enqueue` original nunca reabre Questions. Solo request canónico QuestionScanRecoveryRequest, queue questions-only, allowed_sellers explícito y policy_authority exacta. Es **DB-only**, no provider call ni task automático de reinicio.

| Gate/efecto | Contrato implementado |
|---|---|
| Wire snapshot | Collection.with_options(CodecOptions(document_class=RawBSONDocument,tz_aware=True,tzinfo=UTC)).find_one; requiere RawBSONDocument, copia exacta bytes(.raw), no reconstrucción BSON.encode(dict). Decode separado solo para guards. |
| Pins | Tres SHA64 de wire bytes. `expected_plan_bson_sha256` NO es JSON canónico153a; old59dd/60d1 eran reencoded y **no** están acreditados como wire. RootwireprobeSTOP preservado; no repetición por especialista. |
| Plan | FULL wirePIN dentro callback, PAUSED/eligible/account_link_policy/Seller/policy/EID exactos, fuentes5, fixedrange/cutoff iguales, UTC day/until vigentes y hasta el mismo día, cuotas inicial<=800/150/250/300/500/Full0/2000total, ejecución<=2500 con residual, sent<=charged, mantenimiento policy<=500/300. No saldo ni contador creado/refund. |
| Job/head | FULL wirePINs, request/bindings exactos, terminal reason source_rejected/source_cursor_expired, attempts1..2 sin reset, lease ausente o vencido, última observación de cursor conocida/UTC/vencida>=300s y drift_restarts<3. |
| Concurrency | Guard de admisión seller incrementado en Tx y capacidad/slot reservados; plan FULLdocumentCAS + verdadero$inc de metadata `history_readmission_revision` (ausente→1; int strict sin bool/negativo/overflow). Root autorizó este único nuevo campo: no dirty-fence basado en noopset. |
| Archivo | Nueva colección sheets_history_checkpoint_versions mediante Core envelope Root. VersionID determinista, insert-only. Duplicado con mismo contenido/version/EID devuelve versión original sin renovar archived_at; SHA/bytes/metadata conflictiva aborta. No sobrescrituras ni deletion. |
| Pass prospectivo | Head/Job FULLdocumentCAS dentro misma Tx; sameIDs/gen/range/cutoff. Pass/revision/drift aumentan, `page_sequence` global no retrocede. Solo estado local de nueva pasada se inicializa; versión original completa permanece inmutable. Job pending mantiene attempts y extras originales; leases/token terminales vencidos se liberan; cooldown futuro no se adelanta. |
| Transaction | Archive + head + job + planfence + admisión UNA snapshot/majority Tx; error/conflicto hace rollback completo. Callback reevalúa queue.now/autoridad/pins en cada retry de driver, wait_for30s; ningún retry de proveedor. |

Solo metadata del plan revision aumenta. El modelo Core no autoriza políticas; el operador debe atestar proyecto/contexto/PRIMARY, nueva colección/validator/index, imagen/source y condiciones. Modeldump/blobs/snapshots **nunca** se loggean; salida de readmisión contiene únicamente state/version_id/pass_number/pin-format. No se cambió ningún checkpoint/data/job productivo.

## TTL y STOP de Questions

Antes de fetch con cursor, `fetch_and_stage` usa únicamente durable head.observed_until de última página: missing/future/clock inválido provoca HistoryConflict y cero GET; age>=300 provoca QuestionCursorExpiredError y cero GET. Job.updated_at renovable nunca rejuvenece cursor. El worker guarda reason preciso source_cursor_expired; reloj no verificable queda source_incomplete con blocker cerrado cursor_clock_unverifiable.

Questions `release(cursor_expired/source_drift)` ahora termina preservando head/receipts/attempts, sin llamar la rama que sustituye/resetearía el checkpoint. Source_drift no se readmite por este helper de expiry. Orders conserva lógica previa. Nuevas pasadas solo por readmisión opt-in archivada; verification mantiene globalpage_sequence y usa observación local para distinguir primera página del nuevo pass. No se implementó loop worker general.

`attempts` de retry interno se preserva al readmitir. La lógica ordinaria existente de successful progress/yield y sus resets de retry streak se mantuvo: **no** representa reembolso físico; counters del plan/gateway siguen autoridad y no se reinician. Debe revisarse separadamente si se desea cambiar esa convención.

## B — materializar scanv4 verificado, sin210 detailGET extra

1. Dos manifiestos **actuales, completos**: previous/currentpass, sameacquisition/generation/seller/model, source_total==discovered_count; ambos cardinalidad exacta<=10000, IDs únicos, fingerprints válidos y conjuntos/hashes idénticos; clocks de observación ordenados. Viejo partial150/source210 no pasa ni entrega certificate.
2. Parse ISO con datetime, UTC/BSONmilliseconds; soporte nanosegundos legítimos sin comparación lexical ni `$dateFromString` que descarte errores silenciosamente.
3. Payload in-range completo se valida con el canonical Question writer/schema y campos realmente utilizados por reader. Incluye identity/seller/date/item/from/text/status y, para ANSWERED, answer text/status/date válidos. **answer.status es requerido por schema actual**; no se sintetiza ACTIVE.
4. Materialización desde esos payloads crea detail receipts `source_version=questions.scan.v4.verified`, fingerprint/source/observed_at exactos y revalidación dentro Tx. No se finge lectura /questions/id. Missing fields → fallback solo esas identidades por gateway existente api_version4, batch<=20 y controles físicos tardíos intactos. Malformed/inconsistencia rechaza antes del transporte; missing nunca es campo fabricado.
5. Outside-range conserva membership/provenance del scan global y agrega exclusion fuera del intervalo, sin GET ni row publicada. source_total/discovered globales no se alteran. Hydrate/publisher/inventario/reader usan target in-range respaldado por ambos manifiestos; no exigen detailGET fuera del rango ni falso count global.
6. Publisher exige detalles correctos para todos targets y verifica inventario real/fields antes del marker. Proof del calendario exacto solo después de publicación completa; data/receipts sin certificado no bastan. Source drift/cambio concurrente STOP, no inferir igualdad ni borrar datos existentes para cuadrar counts.

La metadata Root comprobó source_total210/discovered150/fetched0 y150minimal/inrange. Eso **no** prueba que los210 payloads completos tengan todos los campos necesarios ni que el nuevo scan concluya dentro del residual. Fakes210 completos muestran ruta viable0additionaldetailGET, no realidad productiva. Enum/status/fields faltantes o cambios entre pases quedan sujetos a WAIT/fallback/cuota; no ampliar piloto.

## TDD y controles

Cache privado: `/Users/eduardoramirez/.codex/cache/zelerdata-integracion-20261005-8dafff186997/question-cursor-phase2-20261006`.

- red.log/red2.log: errores de colección por nombre de repository en fixture, preservados y separados de comportamiento.
- red3.log/xml:31FAIL/1PASS (32fakes) **antes** de fuentes modificadas.
- red-final.log/xml:36FAIL/1PASS (37fakes) antes de implementar, incluye wire/dict rechazo, snapshots/caps/CAS/concurrencia y materialización/TTL/drift/nanosegundos.
- GREEN intermedios preservados: ajustes fieles de fakes start_transaction/with_options/upserted_id y canonical answer.status, no reducción de assertions ni model checks.
- **final-green.log/xml:37PASS/0FAIL,8.11s**.
- **final-ruff.log, final-format.log, final-mypy.log:PASS**; ocho ejecutables, configuración estándar, sin reducción de scope ni ignores Mypy. Únicos noqa locales S106 justifican owners sintéticos no credenciales en fakes.

Fakes BSON/RawBSONDocument/dotpaths/FULLliteralCAS/transactions rollback con cambios externos persistentes; actual classes publisher/persistence/readermodel para pipeline210. Env whitelist sin MONGO_URI/AMQP/secrets, sockets prohibidos/autoplugins OFF/noconftest. Sin DB/puerto/Docker/gcloud/navegador ni suite general.

Pruebas clave: archivo bytes+extras/dupe/no overwrite; readmission actualexpiredwindow rechazado; exact37sourcebounds/day/quota/lease/revisioncaps; rollback por falla y drift de Plan/Job; TTL300/unknown/future+jobtimestamp renovado; globalSeq; Questionsdrift STOP; completo210→210persistidos/0detailGET/proofyear+camposreader; partialfields→solo1GET; oldpartial/hash/scope/corrupt answer→0GET/reject; global3→2published+1exclusion/0GET; ISO ns no descarte.

## Ajustes adyacentes reservados Root y cobertura pendiente

Tests Mongo existentes en `modules/sheets/tests/test_history_questions.py` que esperan `test_restart_preserves_receipts_and_rotates_manifest`, `test_expiry_or_duplicate_restarts_without_discarding_receipts`, `test_verification_detects_manifest_drift` deben reflejar STOP Question y head/attempts/receipts conservados (no expectedpass/drift reset). No fueron editados ni ejecutados por child. Continuation Orders tests mantienen expectativas previas. Root ejecuta reales aislados y finales con source congelado; no usar puerto27028 sin target verificado.

Runtime afectado esperado: Sheets histórico worker (TTL/scan/projection/publisher). Método readmission aditivo no tiene caller API servido nuevo; no frontend, gateway ni AppsScript cambiados. Core envelope/fence modelo/export pertenece Root y debe incluirse al comparar imágenes necesarias; empaquetar imports no prueba caller ni obliga rebuild general. Root debe confirmar bootstrap caller served/job y desplegar solo afectado con rollback compatible.

Acceptance aún pendiente: producción/rootdriver transactions/validator, scans realmente completos dentro caps, cinco fuentes12calendarmeses/proofs independientes, dos cambios auténticos postcutoff, API normal/nativeSheet; no declarar objetivo completo. Plazo/counters/EID/datos existentes no se reinician. Nueva autoridad temporal/productiva sería decisión explícita separada.

## Hashes SHA-256

- `modules/sheets/src/zeler_sheets/history_checkpoint_versions.py`: `bec607a16b1b4103e68045cffac5323ec7266db942493b3346cb93d9d9098d7e`
- `modules/sheets/src/zeler_sheets/history_questions.py`: `2207b2a52a47b71235c32817db8d55553e502cf8ea6e88ce7befe65d20d5e9a6`
- `modules/sheets/src/zeler_sheets/history_continuation.py`: `711213a66f13b4c824ee01fff66f223ccd78c766895ff28f6f650fa643d4f1f1`
- `modules/sheets/src/zeler_sheets/history_question_worker.py`: `06bf70f65cb2a136fc04f0df4c57121743981ebfe3ac74ce9ec24fc98fc72a4e`
- `modules/sheets/src/zeler_sheets/formulas/recovery.py`: `ec5b06d8fd815b2ced346cb0d42bb17a47f1066487b879dc72284077d8b458d9`
- `modules/sheets/src/zeler_sheets/history_question_publication.py`: `ee9de5523dbdad1b388e6a6db2a1cc79e53e7d777bcdd425af48efe06090fbda`
- `modules/sheets/tests/test_history_question_readmission.py`: `0b070cee4c9d52749a6022bce159ea41a0c8ed0b3f0b400ac515cdf03795a71d`
- `modules/sheets/tests/test_history_question_scan_materialization.py`: `c2b1d46e9ede128c6fecfefec4d5a9eff68473ea867905082bf1c77d780ea495`

Informe hash entregado por chat, sin autorreferencia. **ENTREGADO; NO SIGO MODIFICANDO.**
