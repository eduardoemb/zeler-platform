# ZelerData: live formula retest, September 14, 2026

Authority: `openspec/changes/zelerdata-live-formula-repairs/` and the user's
instruction to continue the existing formula tests and repairs. Target:
spreadsheet `1NUYbJUgYEc6SumZ_IwOWXj_d9MC4grGO5c2XRrAM858`, tab `gpt`,
sheet ID `1904231986`, seller `82453304`. Historical input dates remain
August 15–September 11. This report records observations, not full acceptance.

## Executed scope

At 14:46 UTC, refreshed and independently read all 35 original cases (24 primary
formulas plus 11 supplementary cases). Only their anchor formulas were rewritten;
an additional trailing space in the account argument forces a new Sheets
calculation and is removed by the existing account resolver. Inputs, output
layout, formatting and other tabs were preserved. Existing extra formulas at
`A33021` and `A33361` were outside this 35-case set and were left unchanged.

Original anchor cells:
`A101`, `A121`, `A141`, `A201`, `A4201`, `A4211`, `A4301`, `A8401`,
`A8451`, `A8501`, `A9001`, `A13001`, `A17001`, `A21001`, `A25001`,
`A29001`, `A33001`, `A33011`, `A33401`, `A34001`, `A34501`, `A35001`,
`A35501`, `A36001`, `A40001`, `A40011`, `A40101`, `A40201`, `A41001`,
`A45001`, `A49001`, `A49011`, `A49101`, `A49111`, `A49201`.

Chrome Profile 19 initially provided authenticated visual access. Native Sheets
cell reads/writes provided independent formula and result verification. The
history controls were visually inspected at normal zoom. After a later session
interruption Chrome was no longer discoverable. A 15:47 UTC connector read
briefly returned `NAME` / unknown-function errors for three controls; the next
read recognized the functions again without a source change or deployment.
Do not classify that transient observation as an API regression.

## Observations before expiry

| Formula / case | Observed result and limits |
| --- | --- |
| CALCULADORA | Both selected controls returned prices 172.28 / 477.95 and total costs 24.12 / 134.51. The ID-vector control returned rows instead of a whole-formula error. |
| TIEMPOACTIVA | Active control returned 7; paused control returned NA. VM canonical state independently supports 7 calendar days. |
| PRECIOHISTORICO | Paused control returned 255.65, paused, then NA for absent older entries. VM price history independently matched the price and state. |
| PREGUNTAS / PREGUNTASKPI | Two questions, one answered and one pending; pending answer/date now NA. Noon cutoff returned only the header. KPI remained 2 / 1 / 1 / 0, average 3672 minutes. |
| CODIGOML / PUBLICACIONES | Scalar ambiguity explicit; vector returned AMBIGUOUS_VARIATION twice, then TPGP38465. Publication control still exposes distinct inventory codes. |
| DIASDESDEULTIMAVENTA | Sold control returned 11; no-sale control returned NA. |
| PRODUCTOSINVENTA | 2,823 data rows, 19 missing SKUs rendered NA, zero NONE values. After recalculation 1,376 dates were present; all 2,823 date/absence results matched stored source projections at 14:52:56 UTC. |
| SUPERMERCADO, MEDIDAS, MEDIDASGENERAL | Existing negative controls returned Normal or NA; no positive supermarket/dimensions fixture was created. These are not positive-branch acceptance. |
| CATALOGOSINVINCULAR | Header-only result; a positive suggestion fixture remains unavailable. |
| PUBLICACIONESDESCUIDADAS | 19 data rows; withdrawal quantity/reason remain NA. Selection and operational completeness are not certified. |

The first product-date comparison found five differences: the Sheet had NA and
the source had observations acquired at 14:47–14:48, after the initial Sheet
execution. Recalculation resolved them; no data was patched. A later 15:47
comparison against the retained 14:52 output found one newly acquired source
date at 15:07. These are separate snapshots, not an atomic comparison.

## Coverage and recovery

The following are bounded Sheet snapshots around 14:47–14:50 UTC, not current
inventory guarantees. Row counts include headers where applicable.

| Formula | First read | After requested recovery / recalculation |
| --- | --- | --- |
| CALIDAD | 1,967 rows; 24 numeric scores | 2,019 rows; 33 numeric scores; 1,985 rows with unavailable fields |
| ENVIOSMERCADOENVIOS | 83 rows; 328 unavailable cells | Same incomplete output; 81 distinct shipments identified by the runtime reader |
| CATALOGO | 14 rows; 84 unavailable cells | 26 rows; 134 unavailable cells |
| CATALOGOBUYBOX | 14 rows; 117 unavailable cells | 26 rows; 159 unavailable cells |
| CATALOGO_COMPLETO | 126 rows; 100 unavailable data rows | 165 rows; 99 unavailable data rows |
| OBTENER_CATALOGO | 125 rows; 100 unavailable rows | 164 rows; 99 unavailable rows |
| TIEMPOSINSTOCK | 84 data rows plus header and incomplete-coverage row | 120 data rows plus header and incomplete-coverage row |

All 24 numeric quality scores in the first read matched the source. All 84
initial stockout durations/statuses matched stored observations. Larger later
results were not relabeled complete. Catalog membership and the recovered subset
changed during acquisition; an increased unavailable-cell count alone is not a
regression. Stock-time metrics, catalog-time metrics and full withdrawals each
still had zero stored positive fixtures. DEVOLUCIONES continued to fail its joint
claims/orders proof; the prior historical remediation blocker remains open.

At 14:54:29 UTC, an operator probe admitted the exact 81 missing shipment IDs
through `FormulaRecoveryQueue.enqueue`, with the existing seller allowlist,
capacity, identity and transaction guards. It used a 10-second diagnostic timeout,
not the API helper's one-second limit. The earlier Sheet requests had not left a
recent shipment job; the reason is not established. Do not present this assisted
admission as proof that normal API admission worked. No raw shipment documents,
freshness markers or credentials were patched.

The shipment job completed on its first attempt at 15:00:22 UTC. A selected-item
job requested from the Sheet after expiry completed on its first attempt at
14:59:05 UTC. These completion records alone do not prove the user-visible
post-recovery result. The next session resumed after both freshness windows had
elapsed; subsequent reads again requested recovery.

At 15:48:07 UTC the selected-item job completed again on its first attempt.
The subsequent Sheet recalc returned 7 for the active control, NA for the paused
control and the expected price-history row, with zero unavailable cells in those
three results. A 15:49 VM read confirmed the active source was 55 seconds old.
This closes the selected history expiry-to-recovery-to-visible-result check;
it does not prove inventory-wide recovery or unattended Sheet recalculation.
The normal Sheet path also reopened the shipment job at 15:48:09, confirming
admission in that later attempt. At 15:51 it was still pending with zero attempts.
It subsequently ran at 15:52:07 and completed on its first attempt at 15:54:02.
The next Sheet recalculation returned five open shipments plus the header, with
zero DATA_UNAVAILABLE cells. All five displayed `ready_to_ship`, quantity one,
an absent shipment date rendered NA and `xd_drop_off`. This is successful visible
recovery for the tested order window, after a roughly six-minute queue/run delay.
All five rows were compared with their canonical orders and shipments: paid
orders, quantity one, matching SKU, matching `meli_pack_id`, matching
`ready_to_ship` status and `xd_drop_off` logistics. The corresponding shipment
observations were acquired at 15:54:00–15:54:02 UTC; all had `printed` substatus.
The Sheet diagnosis for ENVIOSMERCADOENVIOS was updated to case verified.

At 14:54 the active history source was 946 seconds old: the internal reader
rejected it, and `A33001` returned an explicit update-requested response after
recalculation. This proves expiry rejection and queue admission; the subsequent
visible recovery verification passed as described above.

The inventory sweep begun at 14:38:35 had processed only 200 / 1,900 identities
by 14:52 and 600 / 1,900 by 15:47. Its enumeration was already outside the
15-minute reader horizon. This is measured incomplete recovery; no TTL, global
freshness marker, queue capacity or scheduler setting was changed to hide it.

## Runtime and remaining work

Worker remained `145ba4f` at digest
`sha256:25c2b64a80e70c518689f219740ca50434b62d3f1384264129568da266fb4674`;
API remained `1df949f` at digest
`sha256:3b972a4bde3549f72a5c318c1f91c5cbb56d87e0d576d5ba56a3f8b5cd3eca6e`.
Both had healthy containers, zero restarts/OOM, healthy worker components and
healthy API dependencies during the 14:47–14:54 observations. No new image,
deployment, restart, schema rollout or cleanup occurred in this retest.

Remaining: reliable admission and recovery latency under load,
whole-inventory throughput/freshness, catalog source gaps, authoritative
DEVOLUCIONES remediation and independent final SDD verification. The overall
formula repair change is not complete. Runtime/source differences do not call
for rebuilding the already-deployed history fix.

The Sheet diagnosis at `C11:C34` and `E11:F34` was updated with these case-level
results and their measurement windows, preserving the initial expected/source
column, formulas and formatting. Baseline statuses are reproduced in the prior
September 12 report; the Sheet's current diagnoses no longer claim the original
null-rendering/history defects are still unchanged.

VM scripts: `/tmp/zeler-sheet-proof.py` (read-only source comparisons),
`/tmp/zeler-recovery-status-20260914.py` (read-only status), and
`/tmp/zeler-shipment-proof-final-20260914.py` (five shipment source checks).
The separate
`/tmp/zeler-shipment-admission-20260914.py` (already executed mutation; do not
repeat as a status check). Temporary local files may disappear between sessions;
this report is the durable record of the sanitized results.
