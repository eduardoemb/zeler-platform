# CUOTAS: integración real del lector con Mongo7 sintético

**ENTREGADO; NO SIGO MODIFICANDO. EOF local GREEN; no autorización de producción.**
Únicos writers: este informe y el nuevo `test_state_pipeline_mongo.py` privado en
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/local-state-pipeline-verify-20261006/`.
Lector, supervisor, 28 fakes e informes anteriores permanecen intactos.

## Target y aislamiento

Root creó y confirmó `resource-ready.json`; el harness cotejó perfil/contexto
propio, owner32hex, container64hex/label, Unix Docker, PRIMARY, Mongo7.0.43,
binding loopback y los dos volumes propios antes de usar sockets Mongo.
DB **único**: `zeler_goal_state_1c48c4c3c0`, derivado/cotejado con el receipt.
No usa `MONGO_URI` ambiental ni la factory productiva; suministra un runtime local
explícito al lector congelado. Root conserva creación/cleanup de infraestructura.

Solo fixtures sintéticas creadas aquí, sin backups ni datos reales. Root autorizó
insert/delete entre los cuatro casos en los namespaces del lector: diez queries
de resumen sobre **nueve colecciones distintas** (plan y ledger repiten colección).
No dropDB, namespace ajeno, puertos nuevos, producción, cloud, AMQP/Meli,
Git/build/agentes, cambios centrales ni suite general.

## RED preservado: `real2.log` / `real2.xml`

| Caso | Resultado | Reads explícitos started/completed | Cursor / preservación |
| --- | --- | --- | --- |
| DB vacío | PASS | 11/11 | Diez cursorID0, diez grupos vacíos; no saldo inventado |
| Policy actual, registry14 sin Full, bootstrap protegido, ledgers | RED | 2/2 | Primer resumen account: cursor no agotado; STOP |
| Legacy con consumos17/checkpoint existente/bootstrap failed | RED | 2/2 | Mismo STOP antes de llegar al plan |
| Bootstrap1001 + contador boolean inválido | RED | 2/2 | Mismo STOP; cap y contador todavía no comprobados en motor |

**1 PASS / 3 FAIL**, 0 skips. Los cuatro fingerprints BSON pre/post son iguales;
el marcador sintético de campos sensibles nunca aparece en la salida.
No getMore ni mutaciones documentales del auditor. `close()` observado en todos.
Cada consulta emitida conservó maxTimeMS4000, allowDiskUse=false y whitelist.
Recibos `run-20261006T015724598045-case-{empty,current,legacy,cap}.json` preservan
counts, cursorIDs, violations y metadata sanitizada, sin contenido de fixtures.

El primer `red-real.log/xml` fue **RED del harness**, no del lector: PyMongo envía
`endSessions` al close. El monitor ahora lo contabiliza aparte como cleanup
protocolar, manteniendo detección de todo otro comando. Además, PyMongo suprime
excepciones de callbacks: violations se almacenan y se exigen vacías en el test.
Ese lote inicial y `case-empty.json` se conservan, sin sobrescritura.

## Causa y cambio mínimo propuesto a Root

Mongo7 retorna cursorID no cero cuando el resultado contiene un resumen y
`batchSize=1`: una página llena no demuestra EOF. El guard correcto del lector
(`state_audit.py:786-791`) hace STOP; el comando usa batch1 en `:886-891`.
Los fakes no modelaron esta semántica. No es un fallo de PRIMARY ni de transporte.

**Propuesta de la etapa RED, no aplicada al original:** batchSize2 para observar EOF;
el pipeline sigue generando como máximo **un resumen**. Conservar obligatorios
firstBatch≤1, cursorID0, máximo11 reads, no getMore/retry y STOP ante incertidumbre.
Actualizar el contrato/fake/documentación que exige1 y el hash embebido del
supervisor; después repetir únicamente estos mismos cuatro escenarios.
No modificar ni aplicar validators como arreglo de este problema.

Ese RED original impedía declarar demostradas las expresiones con filas de plan/work/jobs,
el estado legacy o el cap. Mongo aceptó los pipelines en vacío, pero eso **no**
prueba evaluación sobre datos ni habilita el audit productivo, OAuth o prepare.
No se tocó el lector congelado para ocultar el fallo.

## Continuación EOF expresamente autorizada por Root

Nueva variante SHA-bound, sin modificar el original; detalle y ownership en
`zelerdata-historico-cuotas-estado-eof-informe.md`. El harness solo cambió la
selección/hash del reader y el batch esperado; guard del hash original permanece.
Se repitieron **los mismos cuatro escenarios**, no casos adicionales.

`real-eof.log/xml`: **4 PASS / 0 skips**, 0.48s. Los recibos
`run-20261006T020116439144-case-*.json` observan:

- Empty/current/legacy: 11/11 reads, diez cursorID0, sin command violations.
- Cap: STOP esperado count_cap_reached, 6/6 reads y cinco cursorID0; observed1001,
  truncated=true/total_known=false. Contador boolean inválido no se hace número.
- Current prueba sobre filas las expresiones reales work/ledger/counters/jobs,
  las dos projections determinísticas de plan y el registro14 sin Full.
- Legacy conserva/reportó consumos17 y checkpoint presente sin convertirlo
  en policy actual. Ambos snapshots de fixtures, y los otros dos casos, iguales.
- Los cuatro: no getMore/docwrites/leak; close y un endSessions protocolar
  separado de los reads. runtime_controls/start siguen false, enabled null.

Mongo7 real demostrado para estos fixtures; no validator real, snapshot
productivo, OAuth, bootstrap live ni aceptación del piloto demostrados.

## Calidad y entrega

`delivery-ruff.log`, `delivery-format.log`, `delivery-mypy.log`: PASS estándar sobre
el único Python nuevo, sin ignores/config/flags que reduzcan mypy.
Logs escritos O_EXCL, paths absolutos y modo0600; ambos lotes RED conservados.
SHA256 harness baseline RED: `2ca4a60cd0a3800239911f0e532dc9731ec0788121b5d7ff09ac129046362d5a`.
SHA256 harness EOF final: `31dea3314822414752381d2c4e378bb44159486fd3edea72a6b2bdc7579d39d6`.
Lector original RED: `4206e9f8cdee51e4879785cab7bfd0299d452750562ca03570b5d1c414174a5b`.
Lector EOF GREEN: `3f86e2320829915f8b86137337268b42523a164403dd7ff20e6b60af1bff1b55`.
Receipt Root: `4583d5b9a5490c4046edeb87bcd536803667eb33e6557a6f592c2e0f2e11dcf6`.
`delivery-receipt.json` conserva hashes baseline RED/frozen; receipt final de
variante y ambos informes en `pilot-state-audit-eof-20261006/delivery-receipt.json`.
`delivery-{ruff,format,mypy}.log` de esa variante incluye también harness final:
PASS, mypy4 targets completos. Sin edición ejecutable después de ese lote.
Root recibe cese para validación independiente; no inferir salud/datos productivos.

## Key Learnings:

1. batchSize igual al número de resultados no demuestra cursor agotado.
2. Fakes PASS no sustituyen la evaluación real de expresiones Mongo sobre filas.
3. CommandListener requiere registrar violations; excepciones del callback no
   propagan al caller. `endSessions` debe separarse de las lecturas explícitas.
