# Proposal: Repair ZelerData Formula Results and Recovery

## Intent

Repair 15 formula problems from the September 12 spreadsheet audit through legitimate recovery and explicit missing/ambiguous results. Confirmed handoff: revision 1; runtime findings require revalidation.

## Scope

### In Scope

- Normalize missing PREGUNTAS and DIASDESDEULTIMAVENTA values to `NA`.
- Populate PRODUCTOSINVENTA change dates from supported observations and normalize missing SKUs without losing valid rows.
- Prevent CODIGOML from silently choosing between conflicting variation inventory codes.
- Repair recovery for ENVIOSMERCADOENVIOS, TIEMPOSINSTOCK, TIEMPOACTIVA, PRECIOHISTORICO, and DEVOLUCIONES.
- Improve justified coverage for CALIDAD, CATALOGO, CATALOGOBUYBOX, CATALOGO_COMPLETO, OBTENER_CATALOGO, and PUBLICACIONESDESCUIDADAS.
- Prove repairs through TDD, repeated spreadsheet tests, and sanitized source comparisons.

### Out of Scope

- Fabricated historical intervals, blanket freshness bypasses, physical stock withdrawals, or unrelated products.
- Claiming a controlled positive fixture as a production-positive observation.
- Commits or branch/worktree administration without user authorization.

## Capabilities

September 14 closure authority: the user approved all 35 original cases,
including DEVOLUCIONES and source-gated historical metrics, simultaneous whole-
sheet recalculation, and 90 continuous production minutes after warm-up.
Where a real positive fixture is absent, controlled positive tests plus verified
production absence/coverage and explicit limitations are accepted. Existing
commit/push/build/deploy authority now includes the scoped gateway connection
repair in the approved plan. Broker mutations, capacity/cost changes and unrelated
service restarts remain outside this authority. This supersedes the earlier
recovery-first exclusion of returns for this closure, not historical integrity.

### New Capabilities

- `zelerdata-live-formula-results`: Missing/ambiguous results, observed values, bounded recovery, and live verification for existing formulas. No canonical OpenSpec capabilities exist.

### Modified Capabilities

None.

## Approach

Preserve public signatures and matrix shapes. Reproduce each cause using focused tests and independent discovery/detail clients. Reuse normalization and recovery components, acquire required enrichment before projection writes, and advance freshness only for successfully observed coverage. Preserve partial results with explicit unavailable cells. Define observed-date semantics before choosing a timestamp; current-state observation does not prove a historical transition.

## Affected Areas

| Area | Impact | Description |
| --- | --- | --- |
| `modules/sheets/src/zeler_sheets/formulas/` | Modified | Handlers, normalization, productivity checks, recovery |
| `modules/sheets/src/zeler_sheets/item_projection.py` | Conditional | Required observed fields |
| `modules/sheets/src/zeler_sheets/remaining_read_model_writers.py` | Conditional | Verified recovery projections |
| `modules/sheets/tests/` | Modified | Regression and recovery tests |
| `docs/` | Modified | Sanitized verification evidence |

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Upstream gaps or throttling persist | High | Bounded retries; distinguish unavailable from defects |
| False freshness or invented dates | Medium | Coverage-aware markers and provenance tests |
| Matrix/vector regression | Medium | Header, cardinality, and CALCULADORA controls |

## Rollback Plan

Keep changes independently reversible. Before deployment, record compatible running digests; restore only affected services if verification fails. No destructive migration is proposed.

## Dependencies

Build/deploy authorization remains valid; deployment requires an authorized commit on `main`, pending commit authorization. Follow Cloud Build provenance and deployment gates.

## Success Criteria

- [ ] Reproduced defects have failing-then-passing tests; required repository gates pass or pre-existing failures are identified.
- [ ] Live results match documented source semantics after recovery and recalculation.
- [ ] All 15 formula diagnoses record expected/actual results, source evidence, and remaining data limitations.
