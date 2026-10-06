# CUOTAS: presencia activa y grupos pendientes sin replay del archivo

**ENTREGADO; NO SIGO MODIFICANDO. Local GREEN, no operación productiva.**
Solo cinco writers nuevos: privado `pilot-state-presence-20261006/`
(`state_presence.py`, `state_supervisor.py`, `test_state_presence.py`,
`test_presence_mongo.py`) y este informe. Sin source/shared/config/deps/locks,
Git/build/agentes/AMQP/Meli/suite general. Originales, informes y logs previos
preservados. Root conserva producción y creación/cleanup de infraestructura.

## Contrato preparado

Default inactivo **0 operaciones**. Flag nueva exacta **en ambos programas**:

```sh
python3 - --inspect-pilot-state-presence < state_supervisor.py
```

Supervisor stdlib host≥3.9; lector stdin Python3.11 dentro del API aprobado.
Un solo `sheets-api` running: ID/service/image/RepoDigest exactos, sin overlay
de `/app` ni Python `/usr/local/bin/lib`, hash del lector antes del único exec.
Sin forward de env, versión `-V`, sondas adicionales, retry ni fallback.

```text
us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417
```

Factory legítima `create_runtime_db` incluida en esa imagen. Proyecciones/helpers
de metadata reutilizados por embedding SHA-bound del reader original4206, sin
modificarlo ni ejecutar su audit de diez grupos. Reader/supervisor anteriores
EOF3f86/3ab0 intactos. Nueva validación/receipt específico de presencia, upper7.

## Siete comandos explícitos, orden cerrado

PRIMARY hello + seis aggregate. Cada aggregate maxTimeMS4000/allowDiskUse=false,
match→limit→proyección safe→único summary, batch2/firstBatch≤1/cursorID0.
No getMore/query crudo/count global ni `$out/$merge/$function`.

| Grupo / colección | Filtro y límite | Interpretación |
| --- | --- | --- |
| plan / sheets_history_backfill_plans | `_id="82453304"`,2 (cap1+1) | Presence/type, no balances inventados; duplicate STOP |
| recovery / sheets_formula_recovery_jobs | seller∈[string,int82453304], state∈[pending,running],2 | **Presencia**, no inventario ni scan de1001completed |
| migration / platform_migrations | `_id="sheets_sync_jobs_v2_activation_cutoff"`,2 | Fecha/cohort real o desconocida; duplicate STOP |
| sync / sheets_sync_jobs | seller∈V, state∈[pending,running],2 | Presencia y cohort before/after/mixed/unknown; no ocultar precohort |
| runs / sheets_devoluciones_runs | seller∈V,101 (cap100+1) | Inventario acotado; cap STOP/lower bound |
| operations / sheets_devoluciones_operations | seller∈V,101 (cap100+1) | Inventario acotado; cap STOP/lower bound |

ACTIVE0 indica ausencia **solo del filtro/momento**; ACTIVE1/2 indica presencia,
observed_lower_bound, total=null y total_known=false. No página adicional ni
claim de quiet global. ACTIVE2 **no** corta la lectura de grupos independientes.
Inventario101/duplicado/unsafe/cursor/error sí STOP inmediato.

## Metadata visible y límites

- Plan: summary canónico sanitizado más campos de allowlist con `present/type`,
  validación de tipo/no-negativo, value numérico o null y cardinalidad acotada.
  Missing es distinto de null/bool/string malformed; ausencia no se convierte0.
  Cutoff/bounds UTC, counters/source caps/daily, execution identity opaca32hex,
  fields/shape de ledgers, progress/checkpoints solo cardinalidad.
- Budget subobjetos y sus hojas conocidas, daily-policy leaves y placeholder
  Full se inspeccionan como metadata; no se selecciona Full ni se consulta Meli.
  No ledger nonce/source payload/claim/job/resource/owner values.
- Lease top-level y legacy envelope: fechas/live boolean o desconocido, no tokens
  ni owner. `valid` de field significa tipo/no-negativo, **no** autoridad de
  ejecución, validez lógica completa de policy ni permiso de upgrade.
- Nonempty ledger sin execution ID/policy identificable → unsafe_plan_shape,
  no counter0/grant nuevo. Aun ledger actual identificado sigue plan-level con
  identidad Root no acreditada: no promesa de atribución histórica.
- Jobs/runs/operations: enums, counts, attempts/fences/cohort/ranges/lease UTC,
  checkpoint/cardinality y coverage metadata; sin IDs negocio/datos/payload/raw
  checkpoints, tokens, nickname, URI o valores de env. Unknown permanece unknown.

`isolation_established=false`, `runtime_controls_verified=false`,
`execution_start_known=false`, `execution_enabled_derived=null` siempre.
No snapshot; fechas por grupo. No2500 libres, nuevo presupuesto, reset/refund,
prepare/OAuth ni start calculado until−90. Un read PASS solo prueba lectura.

## Límites y sanitización

Cuerpo50s +cleanup5; hard70/exec85/remote130/caller140+5/total≤300.
finally cierra client y preserva fallo de cleanup; counts started/completed
explícitos0..7. Handshake/monitorización y endSessions no se cuentan como reads.
Resultado compartido con main conserva counts incluso ante hard deadline.
Stdout/stderr/logging de factory/driver suprimidos; errores cerrados sin strings
libres. Output≤64KiB; output_cap descarta grupos, no inventa counts0.
Si exec inició sin receipt fiable: counts=null/known=false/upper7.

## RED/GREEN y motor real

| Evidencia privada O_EXCL / modo0600 | Resultado |
| --- | --- |
| red-fakes.log/xml, antes del comportamiento | 12 FAIL |
| green-fakes*.log/xml | Lotes intermedios preservados; primer11/12 detectó vocab claims_returns incompleto; siguiente11/12 detectó JSON del test con datetime |
| red-ledger.log/xml | 1 FAIL /11deselected, en el mismo caso null: gap de unknownledger detectado antes del guard |
| delivery-final-fakes.log/xml, bytes finales | **12 PASS /0 skips**,0.08s |
| delivery-final-real.log/xml, mismos cuatro casos | **4 PASS /0 skips**,0.80s |
| delivery-final-ruff/format/mypy.log | **PASS**, cuatro targets estrictos completos |

Un error mypy del harness (inferencia de dict de fixtures) se corrigió con
annotation explícita; failing delivery-mypy.log conservado. Sin ignores ni
reducción de scope/checks. No casos adicionales/marginales. Hash/embedding y
sintaxis host3.9 PASS; fakes cubren default0op, flag guard, un exec, bad binding,
closed receipt/unknown counts, cap/duplicates/cursor/deadline/error/cleanup.

Mongo7.0.43 PRIMARY de Root: receipt/Unix-context/ID64hex/owner-label/loopback/
dos volumes propios verificados antes de sockets; DB exacto
`zeler_goal_state_1c48c4c3c0`, sin MONGO_URI ambiental ni factory productiva.
Solo fixtures nuevas sintéticas y delete antes/después en las seis colecciones
asignadas. **Nueve colecciones físicas**, no diez: plan/ledger anteriores repetían
una. Tres intocables (`meli_accounts/module_registry/bootstrap_jobs`) hash-preserved,
corrección4→3 confirmada por Root; no cuarta colección inventada ni dropDB.

| Caso real final / receipt `run-20261006T024013237892-case-*.json` | Resultado del audit |
| --- | --- |
| 1001completed +2ACTIVE, plan missing y cohort real | PASS7/7 +6cursor0; presence2/totalnull, sigue resto |
| null total_consumed | STOP unsafe_plan_shape2/2 +1cursor0; present/null/invalid, no0 |
| seller/IDs foreign y marcador sensible | PASS7/7 +6cursor0, ausencia solo filtro; marcador ausente |
| runs101 | STOP count_cap_reached6/6 +5cursor0, lowerbound101/total_unknown |

Todos los snapshots de seis fixtures pre/post idénticos; tres intocables igual,
marker ausente, no getMore/docwrites del auditor, close y endSessions separado.
Fixture readback/fingerprint y CRUD de test son controles sintéticos separados,
no lecturas productivas ni parte del contador de siete del auditor.

## Hashes finales y cesión

| Artifact | SHA256 |
| --- | --- |
| state_presence.py | `8a776c1f011964a88ad34c88935db85ad778f36887c2e8635d4243fd4161fe4d` |
| state_supervisor.py | `062e21ba4f81c0d520ae677025a5409f0dcc524ac4a6b6714f1288f870bf0c7d` |
| test_state_presence.py | `4e4ad8e2edd407c2eba3907da51451ba2af3af041b9e42bead2c22eb1ccd2c2a` |
| test_presence_mongo.py | `85a3aa9da3e4eca617202820aee2c5d99e0d41ae181714c428cf79dd9479adf3` |

Hash de informe/recibos/logs y frozen anteriores en `delivery-receipt.json`.
No edición ejecutable tras lote final. Root recibe cese para verificación
independiente y cualquier operación autorizada; no afirmar aceptación/productive
state/OAuth/quiet por estos fixtures ni repetir el archive audit fallido.

## Key Learnings:

1. Dos activos acotados prueban presencia, no un total ni aislamiento global.
2. Missing y null deben separarse antes de seed; ledger no atribuido sigue WAIT.
3. Diez grupos originales equivalían a nueve colecciones físicas, con plan repetido.
