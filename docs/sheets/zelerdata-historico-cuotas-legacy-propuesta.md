# CUOTAS: admisión legacy preservando la historia existente

**ENTREGADO; NO SIGO MODIFICANDO. Propuesta local; no implementación ni producción.**
Único writer: este documento. Root conserva código/contratos/config/deps/locks,
documentos centrales, Git/build/runtime y el target sintético. Sin tests/agentes.

## 1. Evidencia y frontera del problema

Ledger Root `paralelo.md:1257-1279`: primer audit productivo terminó STOP
count_cap_reached, 7/7 reads, PRIMARY y cleanup cerrado. Plan único identificado,
legacy, cutoff **2026-09-24T05:36:28Z**; ausencia/tipo inválido de campos canónicos
todavía pueden compartir representación null/unknown. Saldo ejecutable desconocido.
Bootstrap13 incluye un succeeded/checkpoints7 protegido y doce failed conservados.
Recovery≥1001 observados NO demuestra ausencia de activos; sync/migration/runs/
operations no se leyeron. Esta propuesta no convierte esos desconocidos en0.

Defecto concreto: `core/src/zeler_platform_core/history_onboarding.py:53-77`
actualiza todo budget, total_consumed, state, sources, source_cursor y bounds con
`$set` cuando falta policy_version, aunque esos campos ya existan. Conserva cutoff
pero **no garantiza preservar counters ni metadatos legacy parcialmente migrados**.
El filtro `:54` tampoco incorpora snapshot/lease/cutoff; un concurrente puede añadir
consumos entre lectura y escritura. La corrección requiere CAS, no otra etiqueta.

Legacy real documentado (`modules/sheets/src/zeler_sheets/pilot_history_backfill.py`):

| Campo / significado | Referencia / tratamiento |
| --- | --- |
| cutoff/schema_version/seller_id | :52-76, seed inicial; nunca sustituir por fecha del OAuth nuevo |
| progress por recurso/chunk, queued/completed/failed/attempts | :174-181,245-265; resumen del estado de jobs, conservar entero |
| job attempts / dispatch_attempts | recovery.py:798-805; claims de job, **no** intentos GET físicos |
| request_key/chunk identity / history_plan_id | backfill.py:77,93-100,119-144; no recrear ni migrar keys por timestamp nuevo |
| coverage/certificates | backfill.py:105-146; completed solo no prueba cobertura; L-028 lessons:339-355 |

Este engine no escribe canonical budget/execution counters; no mapear
`progress.*.chunks[].attempts` a consumed ni sumar jobs/bootstrap attempts como
cuota. Contrastar presencia/tipo real de los campos canónicos antes de decidir
seed0; el audit anterior no leyó progress ni prueba inexistencia de otros ledgers.
No hay modelo de plan en `models/sheets_history.py`: sus clases :16,94,142 son
acquisition/range/receipt; no serializar un plan legacy con defaults de otro modelo.

## 2. Diseño mínimo cerrado recomendado

**A: seed aditivo dentro del OAuth legítimo + CAS; nunca patch manual de plan.**
No cambiar `_identity` del operador para aceptar legacy ni crear una acción upgrade.
La alternativa de `$set` completo/reset/import/refill queda descartada.

1. `admit_history_onboarding`: leer `_id/seller_id` canónicos y snapshot completo
   privado. Validar cutoff BSON date; normalizar UTC **solo para cálculo** como
   `:44-50`, preservar bytes/precisión del stored cutoff. Derivar bounds ausentes
   con `calendar_history_start`: **2025-09-24T05:36:28Z → cutoff de 2026-09-24**,
   no now−365 días ni nuevo cutoff de octubre. Bounds existentes se conservan;
   si contradictorios/malformed, WAIT antes de otorgar autoridad.
2. Construir `$set` exclusivamente para hojas **genuinamente ausentes**. No
   convertir null/False/string/object inválidos a ausencia. Si budget existe como
   mapping válido, agregar solo hojas faltantes; nunca reemplazar objeto/subobjeto.
   Preservar todos los consumed, limits, day/deadline/execution identity, charges,
   sent/work receipts, progress/checkpoints/collector cursors/watermarks/proofs,
   lease/fences y campos ajenos, incluidos contadores no usados por el piloto.
3. Seed0 únicamente de contador nuevo sin evidencia de cobranza durable previa
   para ese contador/fase; nunca derivarlo de ausencia en una proyección. Counter
   presente no negativo/int estricto se conserva, incluido nozero; bool/negativo,
   ledger con identidad/fuente/fase desconocida o counter ambiguo → WAIT sin cambio.
   Unknown metadata ajeno se preserva, no se convierte en crédito ni se interpreta
   arbitrariamente por nombre. Progress legacy no es prueba de consumed0.
4. Mantener defaults genéricos de sellers no seleccionados. Añadir un argumento
   opcional compatible **`pilot_seed=False`**, recibido exclusivamente del caller
   OAuth server-side cuando seller pertenece al setting validado ya existente
   `history_pilot_get_budget_sellers` (config.py:21-23,55-79); no nuevo env/header ni
   detección por path. `emit_accounts_linked` pasa True para ese scope, antes del
   bootstrap skip (events.py:51-72). Core no importa configuración de Gateway.
5. En pilot_seed, si ausentes: state=paused, sources=las cinco, total_budget=2000,
   budget caps800/150/250/300/500, daily policy500/300. No activar worker por OAuth.
   Las hojas existentes no se sobrescriben ni incrementan límites. Compatibilidad
   interna: el operador itera seis SOURCES (`pilot.py:162-169`); un slot budget de
   Full ausente puede existir **con límite0/consumed0**, pero Full nunca entra en
   sources ni recibe crédito. Si contiene consumo previo, conservarlo; no reset.
   Items no se convierte en una sexta fuente. No tocar SOURCES global para fingir
   que otros contratos dejaron de requerir ese placeholder.
6. **No seed execution_id/day/until/attempt_limit ni iniciar ventana.** Esos campos
   se crean por prepare autorizado, solo después de verificar nunca-preparado y
   baselines/ledger. Counter de ejecución existente se conserva, jamás se refunda.
   Daily day/counters existentes intactos; ausencia real solo inicialización de
   policy nueva, no cambio de día artificial. No duplicar el rollover del worker.
7. Legacy admission rechaza lease live (top-level lease_until/token y cualquier
   legacy lease envelope reconocido), token sin expiry y forma desconocida.
   No renovar/liberar leases para poder migrar. La presencia0 de una lectura no
   prueba quiescencia: Root debe congelar productores legacy antes de OAuth.
8. Commit lógico mediante **whole-document CAS**, precedente `pilot.py:301-307`:
   `_id/seller_id + policy_version absent + $expr $$ROOT == $literal(snapshot)`,
   `$set` del patch, upsert=False. Cambiar cutoff/lease/counter/campo añadido hace
   perder el CAS. Nada de replace, unset o ciclo de reintentos automáticos.
   CAS miss admite un readback acotado: si otro admission ya completó la misma
   policy/cutoff y contratos, éxito idempotente sin reescribir; de otro modo WAIT.
9. Re-link de policy ya existente: no seed/refill ni reactivar paused; conservar
   estado/consumos/plazos. Única mutación natural: last_linked_at del OAuth real,
   monotónica (max), sin false refresh. No migrar policy_version desconocida.
   Fresh insert conserva `$setOnInsert` legítimo (:35-40), no es un upsert manual.

**Prerequisito de carrera:** el callback legacy no posee plan lease y su update
final usa solo `_id` (backfill.py:262-265); CAS de admission no lo vuelve fenced.
No afirmar seguridad concurrente por CAS local únicamente: Root debe demostrar
quiescencia del refresh/callback viejo y de trabajo activo previo. No hace falta
resetearlo. Si no puede aislarlo, falta un guard de ownership del callback antes
de enqueue/update, a diseñar/autorizar aparte; no ocultarlo ampliando este fix.

## 3. Scope exacto de implementación y REDs propuestos

| Writer propuesto Root | Símbolo / entrega |
| --- | --- |
| core/src/zeler_platform_core/history_onboarding.py | admit_history_onboarding + builder/validator privado de seed/CAS; calendar_history_start reutilizado |
| core/tests/test_history_onboarding_admission.py (nuevo) | regressions unitarias de preservación y CAS (fakes que realmente modelen dotted paths/matched_count) |
| gateway/src/zeler_gateway/oauth/events.py | pasar pilot_seed desde scope trusted existente; preservar selector bootstrap |
| gateway/tests/test_history_admission_controls.py | BSON naive UTC, pilot seleccionado/otro seller/hold, no fill de valores malformed |
| gateway/tests/test_oauth_relink_bootstrap_history.py | legacy con budget parcial/nozero +13jobs, una succeeded; todo intacto salvo campos aditivos permitidos |
| modules/sheets/tests/test_history_onboarding.py | regresión compatible de admisión/worker y legacy race; solo tests, no worker behavior change |

REDs necesarios: (1) legacy cutoff Sep24 naive/aware, rango calendario y precisión;
(2) budget parcial/nozero/total/source_cursor/status/metadata ajeno preservados;
(3) nested missing vs null/bool/negativo/corrupto; (4) execução previa/day expirado
no modificación; (5) lease live/token malformed; (6) dos concurrentes/CAS takeover
durante lectura, añadir campo/cobrar/cambiar cutoff; (7) idempotencia/relink después
de consumo/paused; (8) pilot5/Full0/noexec/new vs ordinary default compatible;
(9) OAuth normal preserva los13 bootstrap jobs sin publish/replacement ni force;
(10) DB real sintética del CAS y readback, sin usar producción como prueba.

No cambiar funcionalmente selector protegido: events.py:57-72 y su test :111-138
ya prefieren pending/running/succeeded antes de terminales. No reabrir doce failed,
ni borrar checkpoints7/6 ni reemplazar succeeded. No confundir código verificado
con imagen actualmente desplegada: Root coteja build/source/runtime antes de OAuth.
Si el delta queda solo en admission/caller, **Gateway** es imagen runtime afectada;
no rebuild worker por mera importación de core si sus símbolos usados no cambian.

## 4. Próxima lectura dirigida propuesta, no ejecutada

VM/VPC/API approved oldpin3f7, create_runtime_db legítimo, default0op/stdin opt-in.
**Un exec, máximo7 comandos explícitos:** hello PRIMARY + seis aggregate. Cada
uno maxTimeMS4000, match→limit(cap+1)→projection server-safe→único summary,
batch2/firstBatch≤1/cursorID0/no getMore; no count global/query documentos crudos.

| Colección / nuevo propósito | Filtro / cap máximo observado |
| --- | --- |
| sheets_history_backfill_plans / missing vs malformed | _id="82453304"; cap1+1. Presence/type enums y cantidades/UTC conocidas; budget/day/charges/work/lease shape, progress/checkpoint cardinalidad, no sus valores |
| sheets_formula_recovery_jobs / presencia ACTIVA | seller_id∈[string,int82453304] **AND state∈[pending,running]**; cap1+1=2. No repetir scan de1001 completed/archive |
| platform_migrations / cohort | _id="sheets_sync_jobs_v2_activation_cutoff"; cap1+1. activation_cutoff datetime/presencia/validity |
| sheets_sync_jobs / pendiente o in-flight | seller∈V AND state∈[pending,running], cap1+1=2; cohort antes/después/desconocida respecto al cutoff leído, append/lease/fence metadata |
| sheets_devoluciones_runs / proof+trabajo existente | seller∈V; cap100+1. state/scope/bounds/expires/updated/counters/lease metadata; no run IDs/provider data |
| sheets_devoluciones_operations / conservación | seller∈V; cap100+1. state/scope/coverage_mode/epoch/fence/lease/UTC metadata; no owners/hashes con contenido/proofs/payload |

Por orden: plan-shape, active recovery, migration, sync, runs, operations.
Active cap2 demuestra presencia (lower bound) si hay filas, no total completo si
llega2; no es motivo para otra página. Cero filas demuestra ausencia **solo del
filtro y momento leído**, no de estados ajenos ni ausencia futura. Cohort missing
no se fabrica; guard false. No excluir sync antiguo para esconderlo: clasificar
precohort, conservar sus jobs y dejar clara su no-ejecutabilidad por :61-75.
Runs authorized/active pueden adquirir fuente (`devoluciones_runner.py:59-95`);
completed proof no autoriza un nuevo rango. Unknown shape/cap/error/drift→STOP.

Salida cerrada enums/bools/números/UTC, cantidad de reads/cierre/fechas por grupo;
sin credentials, URIs, tokens, nickname, raw checkpoints/businessIDs/leaseowners.
Plan ledger/source attribution permanece plan-level y requires Root identity;
sin baseline físico completo no autorizar2500. Mismos límites50s body/cleanup5/
hard70/exec85/remote130/caller140+5/total300; no fallback/retry. Herramienta nueva
solo tras asignación Root/TDD local+Mongo real: esta lectura es propuesta.

## 5. Continuar el goal sin reiniciarlo

Cerrar forma legacy y aislamiento → implementar/pasar RED/GREEN/CAS real →
Gateway afectado publicado/build VERIFIED/rollout seleccionado y gates AMQP/runtime
→ OAuth auténtico **sin force** con producers aislados → verificar seed/cutoff/
13jobs/registry14 intactos → prepare dry-run y primer prepare **solo si nunca
preparado confirmado**, activate con receipt y controls reales → aceptación5fuentes.
Si identidad/day/deadline previa existe o expiró, conservarla: no nuevo UUID,
ventana, reset/refund ni until−90 inventado. No callback directo para evitar OAuth.

Inicial≤2000 (800/150/250/300/500), mantenimiento≤500/≤300fuente y conjunto≤2500
intentos físicos adicionales, retries incluidos,90min/mismoUTC; saldos medidos,
no2500 libres. Fuentes independientes/12calendar recuperable, proofs períodos
independientes, API normal partial ORDENES, muestra Sheets nativa y dos cambios
incrementales auténticos siguen pendientes (`handoff.md:20-35,188-205`).
Full0/items nosexta/no ampliación del complemento; no declarar el goal completo
por seed, health, build, renewal vacío o pruebas sintéticas.

## Key Learnings:

1. Missing policy_version no permite reemplazar budget/counters legacy existentes.
2. Job attempts/progress no equivale al ledger de GET físicos.
3. CAS del plan y ausencia puntual de activos no sustituyen quiescencia de productores.
