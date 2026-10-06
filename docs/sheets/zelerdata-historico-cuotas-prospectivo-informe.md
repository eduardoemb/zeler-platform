# Diagnóstico prospectivo y origen autenticado del monitor

**Estado: ENTREGADO; NO SIGO MODIFICANDO. RED/GREEN y calidad enfocada PASS.**
No se ejecutó producción ni se diagnosticó retrospectivamente la causa del run
fallido. El objetivo integral continúa pendiente.

## Propiedad y límites

CUOTAS escribe exclusivamente estos archivos nuevos:

- `modules/sheets/tests/test_devoluciones_onboarding_diagnostic.py`
- `tests/test_zelerdata_pilot_monitor_origin_episodes.py`
- Este informe.

Root conserva `devoluciones_runner.py`, `zelerdata_pilot_monitor_guard.py`,
Git, controles conjuntos, builds y toda operación productiva. Los 26 casos
anteriores del guard permanecen sin editar. Sin cambios de Core, schemas,
campos Mongo, scopes, routing, créditos, cutoff, execution ID ni deadline.

## RED antes de comportamiento

| Entrega | Casos | Resultado observado | Defecto reproducido |
| --- | ---: | --- | --- |
| Diagnostic | 8 | 6 FAIL / 2 PASS, 0.46 s | Falta warning sanitizado; WAIT y presupuesto conservan su razón sin warning. |
| Episodios | 12 | 6 FAIL / 6 PASS, 0.36 s | Origen90 no admitido; faltan counters cerrados, progreso superior y binding del PIN anterior. |

Logs privados O_EXCL: `red-diagnostic-8.log`, `red-episodes-12.log`, en
`monitor-guard-20261006`. No se aplicó ningún parche a las fuentes Root.

## GREEN sobre fuentes congeladas

Tras la congelación explícita Root, los **8 + 12 + 26 anteriores = 46 casos
PASS**, último lote 0.49 s. Ruff y formato PASS; mypy PASS en los dos targets,
sin ignores ni cambios de configuración. El hash de los 26 tests anteriores
permanece `5f2323d90f2dc37053f80824a5b7c48a2ca3e5945e9d6359648cdf53e89341bd`.

Fuentes congeladas informadas por Root:

- Runner: `578a0c320a13a0b55ab7e385ce3f95ec844ed606f17af7b6a50273796c369405`
- Guard: `edd58f9f5c13e69440d0241a3225c811656039d0ef8112f1892a47de021ed093`

SHA256 de las entregas ejecutables propias:

- Diagnostic: `1838ca98cfa99eb8c86d7b02a0135d186bf1c9bab1d9ad9e66a5913ee7cc4f11`
- Episodios: `fb0beb61e83febf2296f4c7578e99ccb46f6c9856d20e07b504a68d86037c8d0`

Logs finales: `green-prospectivo-final-46.log`, `ruff-prospectivo-final.log`,
`format-prospectivo-final.log`, `mypy-prospectivo-final.log`. El primer fallo
tooling de imports y del alias no exportado `runner.RUNS_COLLECTION` quedó
preservado; se corrigieron exclusivamente imports de los tests usando la
constante canónica Core, sin modificar comportamiento ni reducir controles.

## Contratos exigidos

### Warning prospectivo

Evento fijo `sheets.devoluciones_onboarding_source_proof_unavailable`, con
`_private_focused_devoluciones_diagnostic(error)` existente:

- `failure_class` cerrado; stage/family sólo cuando son enums tipados.
- `projection_reason` enum o `projection_unknown`; no copiar strings arbitrarios.
- Sin texto de excepción, traceback, payload, IDs, tokens ni `exc_info`.
- Best-effort: un fallo del logger no sustituye la excepción original.
- Misma razón, resultado, ausencia de proof y número de ejecuciones; ningún retry
  adicional. `HistoryPolicyWaitError` y presupuesto no se reclasifican como source.

Los tests interceptan todas las fronteras mediante mocks en RAM. No hay proveedor,
Mongo real, puertos ni credenciales ambientales. Los markers sensibles son
sintéticos y se exige que no aparezcan en el evento.

### Origen90 por episodio

Sólo se añade el origen autenticado **90 charged / 87 sent / 65 initial /
25 maintenance**, además del origen83 existente. Gap3, mismo execution ID,
día UTC y límite **2026-10-06T20:32:58Z**; nunca origen arbitrario ni por tick.

Root autentica los recibos fuera de la función pura. Para origen90,
`previous.origin_receipt_sha256` debe coincidir con el PIN fijo del origen.
No se reconstruyen snapshots83 perdidos ni se absorben incidencias recientes.

- `claims_failed_units` 1/2 sigue visible como histórico, no resuelto.
- Crecimiento, incluso con reason idéntico, produce `fresh_source_failure`.
- Descenso frente al origen o previous es STOP; bool no equivale a cero.
- `claims_completed_units` es monotónico y puede demostrar progreso, nunca
  exactitud, cobertura de calendario ni aceptación de ventanas fallidas.

## Siguiente control — responsabilidad Root

Controles conjuntos y, cuando correspondan, publicación/build/deploy separados.
Los tests no demuestran runtime ni autorizan
reabrir runs, repetir 404 o ejecutar proveedor. La observabilidad futura del
runner afectaría únicamente la imagen worker; el guard OPS no afecta imágenes.
