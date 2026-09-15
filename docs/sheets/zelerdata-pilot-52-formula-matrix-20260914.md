# ZelerData Pilot 52-Formula Matrix — 2026-09-14

Estado: matriz de cobertura de las 52 fórmulas activas para el piloto.
Los resultados observados y la evidencia de producción son PENDING hasta
que se ejecuten las 52 fórmulas en las imágenes desplegadas con entradas
representativas del vendedor piloto `82453304`. `PENDING` no se convierte
en aceptación sin evidencia directa.

Las columnas de propósito, recursos, frescura y cobertura se derivan del
contrato activo del backend y del add-on. Los casos de prueba existen en
los archivos de tests de handlers y en la prueba de cobertura de matriz
(`test_pilot_formula_matrix_coverage.py`).

## Resumen por área

| Área | Fórmulas | Recursos principales | Política de frescura | Cobertura histórica |
| --- | --- | --- | --- | --- |
| Stock/history status | 37 | items, stock observations | current/basic + observed history | retained observations only |
| Catalog competition | 5 | items, orders, catalog product, buybox | current + rolling sales windows | bounded sales windows |
| Sales and orders | 2 | orders + items | historical requested range | API retention (12 months documented) |
| Questions and answers | 2 | questions | historical retained by API | API retention (7 months documented) |
| Economic calculation | 1 | items, listing fees, shipping, promo | <=15m for requested economic inputs | current observations |
| Listing quality | 1 | items, quality/performance | <=15m for requested quality | current observations |
| Returns/claims | 1 | claims + orders + returns (joint proof) | historical requested range | API retention (verified per range) |
| Shipping operations | 1 | orders + shipments | last 30 days/current | API retention (30-day window) |
| Price/status history | 1 | items/status observations | retained observations only | Zeler-observed history |
| Full withdrawals | 1 | withdrawal read model | historical requested range | legacy/source-gated import |

## Matriz detallada

Cada fila debe actualizarse con resultado observado, evidencia y defectos
pendientes antes de la aceptación. Ver el documento completo en
`openspec/changes/zelerdata-pilot-reliable-sync/formula-matrix.md`.
