# Persist ZelerData recoveries before formula reuse

ZelerData formulas read only complete, trusted MongoDB projections. When
required data is still available from an official Mercado Libre API, ZelerData
recovers it asynchronously, stores only the normalized fields it needs, and
serves it on a later formula query; formula calculation never calls Mercado
Libre synchronously. This avoids duplicated API traffic, rate-limit pressure,
long-running cells, and results that change midway through one calculation.
