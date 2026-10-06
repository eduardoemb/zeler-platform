# CUOTAS: prórroga explícita del mismo piloto pausado

**ENTREGADO; NO SIGO MODIFICANDO. GREEN23 local; OPS/producción sólo Root.**
Writers exactos: nuevo `tests/test_zelerdata_history_pilot_extension.py` y este
informe. CanonicalOPS reservado Root, sin source/model/schema/runtime/config
changes, network/Mongo/resources/Git/build/agentes/suite general por CUOTAS.

## Nueva autoridad, no rollover ni presupuesto nuevo

Root recibió autorización humana adicional el **06:17:23UTC**, máximo2h.
Elección conservadora fijada: **2026-10-06T08:17:23Z** desde esa recepción,
SAME execution `868b413e20184befb7e8358e0051924f`, mismo díaUTC y quotas/counters
69charged/67sent. No90min nuevos, otro prepare/UUID ni reset de origen/ledger.
La ausencia de esta autoridad habría conservado STOP al vencimiento original.

Root creó authority JSON privado, SHA
`f71b683854e4c002933ed38df09a7356063280e6f71e56a91f7593ea4ffd1679`:
action authorize_extension/authorization_receivedTrue/seller/policy/execution,
authorized_at_utc/original_until_utc/approved_until_utc/max_additional_seconds7200,
prepare/pause hashes y user_evidence/no_new_credit/full_excludedTrue. Es evidencia
de autorización, **no** receipt Mongo aplicado; no false applied=True en authority.

## Contrato mínimo acordado antes de Root patch

API `control_pilot` agrega opcionalmente:

- `extension_authority: bytes|None`, `extension_authority_sha256: str|None`.
- `extension_receipt: bytes|None`, `extension_receipt_sha256: str|None`.
- Nueva acción **extend-paused**, preview default; apply confirmado/exclusive0600.

CLI propuesto: `--extension-authority-in/--extension-authority-sha256` y
`--extension-receipt-in/--extension-receipt-sha256`, además de flags/pins vigentes.
No credential args ni nueva operación de provider. Gate humano/Root permanece
externo al código: un SHA prueba bytes fijados, no inventa aprobación del usuario.

**Plan patch sólo `execution_until`.** No execution_extensions/campo nuevo:
lineage vive en el receipt externo fijado. Esto evita asumir validator productivo
permisivo o modificar modelo/schema. `models/operational.py` no define el plan
backfill y no autoriza agregarle properties; no inspeccioné/apliqué validators.

### extend-paused

1. Policy/authority/identity/eligible y PAUSED actuales; fuentes5 exactas, Full0.
   Applied prepare y applied pause pins válidos, mismo ID/day; pause hash
   completo = snapshot actual. Runtime/quiescence verificados por Root.
2. Authority SHA exacto, authorization_received/no_new_credit/full_excludedTrue;
   seller/policy/execution y prepare/pause hashes corresponden. Timestamps UTC
   válidos: authorized_at≤now<approved_until, nuevo until mayor al previo,
   ≤authorized_at+7200s y anterior a cambio de día UTC. Max segundos int estricto
   ≤7200, no bool. No permitir `now+2h` ni until caller que exceda el documento.
3. Canonical caps/counters preservados y aún con saldo; no aprovechar permiso
   temporal para exceder source ceilings/2500/500/300. Validar live lease/token
   sin expiry; no liberar ni renovar lease para poder extender.
4. Whole-doc CAS PAUSED snapshot, patch deadline **solamente**, no upsert;
   readback exacto de resultado. Drift de counter/field/lease → STOP sin retry.
5. Receipt applied incluye `previous_plan_sha256`, `resulting_plan_sha256`,
   prepared/pause/extension_authority hashes, previo/nuevo until y clock de
   autoridad. State **PAUSED**; extensión no activa. Preservar bytes afuera de VM.

### resume

Si `extension_receipt=None`, conservar **rama legacy exacta** y su techo90min:
ninguna relajación silenciosa. Rama nueva sólo acepta applied extension pinada,
identidad/seller/policy/preparepin/pausepin/authorityhash/UTC válidos, deadline
exacto de extensión y same-day. `extension.previous_plan_sha256` debe coincidir
con `pause.resulting_plan_sha256`; `extension.resulting_plan_sha256` con **plan
actual PAUSED**. No fabricar nueva pause ni usar el hash antiguo como si fuera
del plan extendido. Extensión preview no autoriza resume.

Sólo la restricción temporal original puede exceptuarse; caps/consumos/scopes,
Full0/lease/runtime/identity/cutoff/markers/credits permanecen. CAS resume cambia
**state solamente**. No clock synthetic/min(now,olddeadline), nuevo prepare ni
modificar oldreceipt para conseguir que `_resume` pase.

## RED real y propuesta

Privado `pilot-extension-20261006/red-external-lineage.log/xml`:
**11FAIL /0PASS**,0.16s, contra canonical actual sin kwargs/action de extensión.
Son RED de superficie/contrato faltante; los guards de rechazo se demostrarán
en GREEN tras implementación, no se presentan como validación existente.
`red.log/xml` inicial con campo de plan execution_extensions propuesto preservado;
Root eligió menor alcance externo, test actualizado antes de su patch.

Fakes BSON naiveUTC/dotted/CAS `$$ROOT==$literal`/matched_count fiel, snapshots
completos, sin sockets/envMongo. Casos: preview/apply sólo deadline; autoridad
false/ID distinto/no-new-creditfalse/Fullfalse/fecha+1seg; pin malo; livelease y
counter drift; resume pinned extension cambia sólostate; preview cannotresume.
Preservan untouched todos los campos incluyendo69/67, sourcecaps, cutoff/progress,
ledgers y token/lease previo. No recursos ni ejercicio productivo de prórroga.

Root fue notificado RED/contrato listo antes de modificar OPS. Root implementó
canonical y congeló el turno; informó58legacy/resume/extension PASS. Su capsfactor
reutiliza el cuerpo exacto; review dentro de OPS confirma branch legacy si no
extension, lineage externa, planpatch sólo deadline y resume state-only.
No hubo modificación de OPS ni de modelo/schema por CUOTAS.

Root pidió guards adicionales en **este mismo testfile**, sin ampliar recursos:
clock autoridad futuro, duration bool/>7200, olduntil distinto, parentpin errado,
pause no aplicada/pin corrupto/runtimeFalse y receipt de extensión re-pinado con
resultplanhash/previousplanhash/state inválidos; parser de nuevos flags explícitos.

| Recibo final privado | Resultado |
| --- | --- |
| final-green.log/xml, bytes finales | **23PASS /0skips**,0.16s |
| final-ruff.log / final-format.log | PASS, test asignado |
| final-mypy.log | PASS estricto estándar, test1 target |

Mypy inicial encontró cinco attr-defined por importar constantes indirectamente
desde OPS; se corrigió únicamente el import al Core canónico. Failing mypy.log
preservado, sin ignore/config/flags de reducción. Env/cache propios y sockets
bloqueados; no red/Mongo ni suite general. No source/test edit después del lote.

Root recibe cese antes de fullgates/apply; esta prueba no afirma runtime quiescente
ni aplica autorización/extend/resume productivos. No rebuild por operador stdin.

## Referencias leídas / límites

- `infra/operations/zelerdata_history_pilot.py:294-385`: resume90min/caps/lease;
  `:388-456`: full CAS/readback/receipt; `:116-176`: prepare no extensión.
- `tests/test_zelerdata_history_pilot.py:48-99`: fake/dotted/CAS/BSON anterior.
- `core/src/zeler_platform_core/models/operational.py`: sin modelo del plan.
- Informe previo CUOTAS aceptación: deadline vencido queda STOP **sin autoridad
  separada**; esa condición cambió por permiso humano nuevo, no por este reparto.

No imágenes/rebuild ni cambios de runtime producto necesarios para OPS stdin;
Root debe probar/aplicar el operador nuevo, conservar source/pins/ledger y gates.

## Hashes finales

Test: `d445d9820bed4119dfd37c788e6a3fe0e3eb47243ff987330482a20eb8d18d04`.
Hash de informe/RED/GREEN/logs en `pilot-extension-20261006/delivery-receipt.json`.
RED anterior y `red-delivery.json` inmutables, no se borran ni reemplazan por GREEN.

## Key Learnings:

1. Extender tiempo no extiende crédito ni cambia identidad del piloto.
2. Lineage externo con hashes evita nuevos fields y preserva el plan salvo deadline.
