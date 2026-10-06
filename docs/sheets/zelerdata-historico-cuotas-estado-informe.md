# CUOTAS: lector canónico de estado del piloto

**ENTREGADO; NO SIGO MODIFICANDO. Preparación local, no lectura productiva.**
Solo los cuatro paths asignados: tres privados en
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/pilot-state-audit-20261006/`
(`state_audit.py`, `state_supervisor.py`, `test_state_audit.py`) y este informe.
Root conserva producción/Git/build/shared/config/deps/lock/old reports y helpers.
Sin agentes, realDB, Docker/gcloud, AMQP, Meli, código central o suite general.

## Alcance y ejecución preparada

Default CLI inactivo, cero operaciones. Únicamente stdin con
`--inspect-pilot-state`; lector Python3.11, supervisor stdlib/gramática3.9.
Supervisor exige un `sheets-api` running, ID64hex, identity/service/image y
RepoDigest exacto del API conservado:

```text
us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417
```

Inspecciona mounts solo en memoria para bloquear overlays de código `/app` y
Python `/usr/local/bin/lib`; nunca imprime paths, env ni mount details. Fuente
embebida/hash ligados antes de **un solo exec** API; no `-V`, probes, fallback ni
retry. Reutiliza factory `create_runtime_db` incluida en imagen; no transmite
credenciales ni usa Mongo local. Payload por stdin, sin instalación/rebuildAPI.

Máximo11 comandos Mongo **explícitos**: PRIMARY hello y estos diez aggregates:

| Orden | Colección exacta / grupo | Filtro / cap |
| --- | --- | --- |
| 2 | meli_accounts / account | seller_id∈["82453304",82453304],1+1 |
| 3 | sheets_history_backfill_plans / plan | _id=S OR seller_id∈V,1+1 |
| 4 | sheets_history_backfill_plans / ledger | _id=S,1+1 |
| 5 | module_registry / registry | _id="sheets",1+1 |
| 6 | bootstrap_jobs / bootstrap | seller_id∈V,1000+1 |
| 7 | sheets_formula_recovery_jobs / recovery | seller_id∈V,1000+1 |
| 8 | sheets_sync_jobs / sync | seller_id∈V,1000+1 |
| 9 | platform_migrations / migration | _id="sheets_sync_jobs_v2_activation_cutoff",1+1 |
| 10 | sheets_devoluciones_runs / runs | seller_id∈V,100+1 |
| 11 | sheets_devoluciones_operations / operations | seller_id∈V,100+1 |

Cada aggregate usa match→limit(cap+1)→proyección segura→group/resumen compacto,
maxTimeMS4000, allowDiskUse=false, batch1 y cursorID0. No getMore, count global,
`$out/$merge/$function`, escritura/upsert/lease claims, businessdata ni Root.env.
Cap alcanzado conserva observed/lower bound y total_known=false/truncated=true;
STOP, no interpretar el subconjunto como ausencia ni total global.

## Datos visibles y límites de interpretación

- Account: enum de estado, fechas y boolean de binding presente, sin ownerID,
  nickname, scopes, ciphertext/nonce/KMS/token ni last_error.
- Plan: policy/autoridad/identidad booleanas, estado/eligible/five-source scope,
  cutoff/rango, fechas/lease, execution_id32hex **no credencial**, day/deadline/caps
  y consumos, budgets iniciales/daily. Campos faltantes/corruptos numéricos no se
  sustituyen por0; saldos desconocidos quedan null.
- Ledger: h1 charged/sent y work_sent por fuente/fase del ID validado, sin claves
  arbitrarias. Work se proyecta en servidor solo source/phase/credit/sent de hasta
 2501 receipts y **se resume en servidor**, no se transporta la lista de nonces.
  Se conservan contador/shape/cap/invalids y totales null ante invalidez.
  No event/resource/claim/job identities/owners.
- Registry: counts14/6 y booleans de sets conocidos/sinFull. Fingerprint del
  subconjunto seguro derivado, no scopes raw, secrets ni promesa de todos los
  campos/clientes. Drift se reporta; no seed/repair.
- Jobs/runs/operations: estados/readmodel/policy_authority enum, leases, counts,
  attempts/fences, cohort dates/activation cutoff, history version/generation/
  pass/checkpoint_revision; checkpoints/dag solo presencia/cardinalidad. No IDs
  negocio, arrays de entidades, checkpoint values/payload/spreadsheet/leaseowners.
  Operations incluye scope/coverage metadata; no modificación de coverage.

Cada grupo lleva observed_utc. Plan y ledger comparan el mismo subconjunto seguro
determinístico; diferencia → STOP plan_subset_drift. **No snapshot transaccional**
ni proof de integridad/coverage por esas dos lecturas. Registro/status/count no
prueban OAuth auténtico, release de leases, source recoverability o aceptación.

Saldo aritmético = mínimos de ceilings existentes menos consumos reales. Saldo
ejecutable0 solo por día/deadline cerrados demostrados; si falta información o
flags externos queda null. No nueva ventana, rollover aplicado por script,
refund charged−sent ni2500 gratis. No campo/start fabricated ni until−90.
`runtime_controls_verified=false`, `execution_start_known=false` y habilitación
derivada nunca true desde esta lectura API. Ledger es **plan-level**, con identidad
del ledger Root aún no acreditada. Root debe cotejar sus flags reales antes de usar
estos resultados para OAuth/prepare/activate; no se asumen riesgos ausentes.

## Deadlines, STOP y salida

Cuerpo50s, finally close máximo5s; alarma hard70s del proceso transitorio, exec85s,
supervisor130s, callerRoot140s +cleanup de grupo5s, total≤300s. No exec si queda
menos de85s. PRIMARY requerido antes de aggregates; primer error/cursor/cap/drift
STOP sin continuar consultas ni ejecutar otro lector. Los counts contabilizan
comandos explícitos, no handshakes/monitorización del driver.

Recibos cerrados≤64KiB, enteros estrictos, enums/bools/números/UTC solamente.
Sink de stdout/stderr y logging durante factory/read/close, códigos fijos sin
exceptionstr/URI. Supervisor descarta stderr/rechaza receipt extra o inconsistente.
Si exec inició sin receipt fiable: known=false/counts=null/upper_bound11, no cero
inventado; antes de iniciar exec son0 conocidos. Cleanup failure se conserva,
no confirma cierre remoto ni autoriza retry.

## TDD y calidad

Fakes de DB command y Docker callback, sin socket/red/puerto/DB/SDK remoto.
Network sockets bloqueados, entorno hijo whitelisted, uv offline/no-sync y .venv
intacto. Casos cubren:11lecturas/proyecciones, PRIMARY/cursor/error/duplicado,
cap jobs/work, drift, ausencia/expiry/priorUTC/countersmissing, registrydrift,
stdout/CLI/deadline/cleanup y supervisor source/pin/mount/receipt/oneexec.

| Recibo local | Resultado |
| --- | --- |
| red.log / red.xml, stubs y colección correcta | 20 FAIL / 3 PASS, exit1 |
| red28.log / red28.xml, antes de behavior | 23 FAIL / 5 PASS, exit1 |
| green.log / green.xml | 28 PASS, exit0 |
| delivery2-tests.log / delivery2-tests.xml | **28 PASS / 0 SKIP**,0.082s,exit0 |
| delivery2-ruff.log | PASS,exit0, tres privados |
| delivery2-format.log | PASS,exit0, tres privados |
| delivery2-mypy.log | **Mypy estándar pyproject PASS**,exit0, tres privados/cache propio |
| AST supervisor Python3.9 + embedding/hash | PASS; no ejecución real3.9 |

Sin nuevos casos tras28GREEN. Durante cierre de entrega se compactó workledger
en servidor y se completaron los campos de metadata ya asignados; se repitieron
los mismos28 casos y calidad. También se acotó la envoltura final del supervisor
a64KiB conservando counts conocidos incluso si retira inspection por tamaño.
Error local de edición/parsing en esa reducción
se corrigió antes de congelar; ninguna operación productiva fue iniciada.
Finales `delivery-*.log` se crearon por ruta absoluta **O_EXCL/0600**; REDs y
helpers anteriores preservados. Lint usó solo excepciones operativas autorizadas
S603/S607/BLE001 para vectores fijos y sanitización; **sin ignores/config/flags
Mypy ni reducción del alcance**. Assert guards productivos son condicionales,
no se relajan checks por tests.

**Límite de evidencia:** fakes verifican estructura/counters/closed output, no
ejecución de las expresiones por un Mongo real. Root valida fuente/pipeline antes
del único uso aprobado; un error real detiene y conserva receipt, no fallback ni
repetición ciega. No equivale a un PASS canónico actualmente observado.

## Hashes finales y cese

| Path relativo al directorio privado | SHA256 |
| --- | --- |
| state_audit.py | 4206e9f8cdee51e4879785cab7bfd0299d452750562ca03570b5d1c414174a5b |
| state_supervisor.py | 638438e23c264b0a6d7eef2542efd4ef0aa73089a00a31ad6592abd41d0150e1 |
| test_state_audit.py | 91b56088d7cb813c0adea4190e771ce9e74e3c61d1ce837400978c2246f200dc |
| Este informe | SHA final por chat/receipt, sin autorreferencia circular. |

Los cuatro hashes previos de metadata f5f48d/7abb8e/d90a2c/informe9306d6 se
cotejaron intactos. Único cambio propio en el checkout: este informe; central
paralelo/informe AMQP y demás trabajo ajeno preservados. Sin código central,
Git mutante, producción, resets, nuevas autoridades ni agentes.

**ENTREGADO; NO SIGO MODIFICANDO.** Ownership de los cuatro paths devuelto a Root.
Root conserva la responsabilidad del ledger/ejecución y de todos los gates reales.

## Key Learnings:

1. Campos ausentes no implican crédito libre; saldo aritmético y habilitación
   ejecutable son pruebas distintas.
2. Metadata de plan y ledger comparada no constituye snapshot ni prueba de OAuth.
