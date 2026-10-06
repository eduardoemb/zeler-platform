# Questions: admisión incremental diferida y progreso durable

**ENTREGADO; NO SIGO MODIFICANDO.** Sólo dos tests nuevos y este informe fueron
editados por CUOTAS. Root conserva las fuentes, Git, controles conjuntos, builds
y producción. El objetivo integral y sus pruebas de cobertura siguen pendientes.

## TDD y calidad

| Lote nuevo | RED antes del patch Root | GREEN final conjunto |
| --- | --- | --- |
| Capacity, 6 fakes | 2 FAIL / 4 PASS, 0.57 s | 6 PASS |
| Q progress, 6 fakes | 2 FAIL / 4 PASS, 0.40 s | 6 PASS |

Con los 26 casos originales del guard y 12 de episodios: **50 PASS, 0.49 s**.
Ruff, formato y mypy de los dos nuevos targets PASS, sin ignores ni cambios de
configuración. Los 38 tests anteriores permanecen byte-exact:

- Guard26: `5f2323d90f2dc37053f80824a5b7c48a2ca3e5945e9d6359648cdf53e89341bd`
- Episodes12: `fb0beb61e83febf2296f4c7578e99ccb46f6c9856d20e07b504a68d86037c8d0`

Fuentes congeladas informadas por Root, no editadas por CUOTAS:

- History: `61ddc934263aef42679a97ac293c71470c2b83cf54932f0ff6c5f229d3dfe529`
- Guard: `7c18958a8f5cf1fb8796296688d16276389a476e96c7de3c4ee4b375485f5454`

SHA256 propios:

- `test_history_question_incremental_capacity.py`:
  `848efc3fa7c686ca119055d9026d62c99a068c17c384a2bed480fcdcc448445e`
- `test_zelerdata_pilot_monitor_question_progress.py`:
  `5f96384e9d2505a0e8124002fd05017e71a51b1a0727df1db5d82870c07c0882`

Logs privados O_EXCL en `monitor-guard-20261006`: `red-capacity-6.log`,
`red-Qprogress-6.log`, `green-capacity-Qprogress-final-50.log` y calidad final.
Las correcciones tooling fueron sólo formato/naming/import del constante Core;
el alias no exportado `history.PLAN_COLLECTION` no exigió tocar fuentes.

## Contrato preservado

- Catch exclusivamente de `RecoveryCapacityError` en el enqueue incremental Q.
- Retiene el resultado histórico y añade `incremental_state='pending'` y
  `incremental_reason='capacity'`; no watermark, job nuevo, reapertura ni live GET.
- Excepciones no-capacity, capacidad del worker histórico y Orders sin cambios.
- Cap4, jobs y fallo histórico preservados. Fakes interceptan workers/admisión;
  no prueban concurrencia Mongo ni runtime. No DB/red/credenciales ambientales.
- El guard exige binding Q y avance real discover/fetch/publication para admitir
  una firma CLEARED. No acepta capacity vigente genéricamente, ni oculta un
  nuevo fallo. Progreso no equivale a exactitud o cobertura.
- Sin origen92: origen90/PIN fijos, mismos presupuestos/cutoff/plazos y Full0.

## Caducidad — propuesta readonly, no ejecución

La ruta canónica `HistoryQuestionsWorker.process_one` llama
`queue.claim(history=True)` → `initialize_question_scan` → `fetch_and_stage`.
En `history_questions.py:365–372`, cursor con edad ≥300s provoca
`QuestionCursorExpiredError` **antes** de fetch/charge/GET. El worker termina
`source_cursor_expired`; claim incrementa attempts0→1 y finish deja failed,
libera el owner y conserva cooldown de 15 minutos. El head50/rev5/seq4 y sus
bytes no se reescriben. No requiere plan ACTIVE: debe mantenerse PAUSED/HISTORYOFF.

El claim actual no tiene target argument y hace cleanup `update_many`.
Root deberá comprobar un adapter de `queue.collection` que conjoin el `_id`
exacto en todos sus reads/writes, incluido cleanup, y un gateway anti-transport
que falle si se toca. No se creó ni ejecutó tal herramienta en este encargo.

Sólo tras el resultado genuino FAILED, pins wire-BSON frescos y autorización
Root: el método existente de readmisión archiva head+job íntegros y propone
pass3/rev6 con seq4 monotónica; conserva attempts1 y `available_at`/cooldown,
capacidad4→3→4, datos/receipts/counters/cutoff/until. Esta propuesta no autoriza
proveedor, nueva ventana, reset ni repetición del diagnóstico.

La fuente histórica afecta la imagen worker; el guard OPS no afecta imágenes.
Controles conjuntos y build/deploy, si corresponden, son responsabilidad Root.
