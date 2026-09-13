## Exploration: zelerdata-live-formula-repairs

### Current State

The live audit executed 35 cases across 24 formulas. The requested repair scope is the 15 formulas with observed failures or incomplete results. A successful formula write and a queued recovery do not establish correct output. Existing historical data is not, by itself, proof of current completeness.

Confirmed shared causes in the current source:

- `ENVIOSMERCADOENVIOS` requires global `orders` and `shipments` productive markers before loading its 30-day orders. Shipment recovery accepts explicit shipment IDs only and cannot recreate the global shipment marker. The guard raises without those IDs, preventing the available recovery path from repairing the read. Orders must also prove the actual 30-day interval, not merely a live tail.
- `TIEMPOSINSTOCK`, `TIEMPOACTIVA`, and `PRECIOHISTORICO` require global stockout/status/price markers. These models are absent from `RECOVERABLE_MODELS`. Item persistence already maintains their observations; selected item recovery deliberately cannot publish global freshness. The reader and producer scopes do not match.
- `DEVOLUCIONES` requires a joint claims/orders proof with snapshot revalidation. Generic formula recovery does not implement this model. A dedicated lease/fingerprint-based acquisition and reconciliation path already exists in `devoluciones_reconciliation.py` and the operations reconcile CLI. Preserve that authority rather than declaring arbitrary claims productive.
- `catalog_sales_coverage` recognizes unioned retained interval proofs, but always requests the first 90 days of a missing long window. Once the first segment of the 365-day window is proven, it requests that segment again rather than the next uncovered gap. Stable gap planning is necessary for convergence.
- Catalog and quality readers accept only source-bound recent item rows. Inventory discovery and detail acquisition proceed in batches of 20 with a 15-minute reader horizon. Long sweeps can expire early batches before the last batch completes. This is a throughput/freshness hypothesis supported by observed shrinking coverage, not yet a proven implementation defect; measure batch timings and unavailable reasons before changing the validity contract.
- `normalize_sku(None)` currently produces `NONE`. `PRODUCTOSINVENTA` uses that helper and hardcodes its last-change column to `NA`, despite persisted status-history fields. Missing SKU normalization must happen before string conversion. A first observation is not automatically an actual status change.

Lessons L-007 and L-010 require enrichment before formula-row projection and distinct discovery/detail gateway identities. L-012 governs isolated Mongo regression tests. Engram tools were unavailable in this executor; local source and supplied live evidence are sufficient for this exploration. `openspec/config.yaml` and main OpenSpec specs are absent; the selected change remains the artifact authority.

### Affected Areas

- `modules/sheets/src/zeler_sheets/formulas/read_models.py` — proven interval gap selection, selected source-bound observations, SKU null normalization.
- `modules/sheets/src/zeler_sheets/formulas/handlers_item_shipping_catalog.py` — shipment interval and explicit-ID recovery; catalog partial output semantics.
- `modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py` — stockout and price history reads; catalog sales recovery convergence.
- `modules/sheets/src/zeler_sheets/formulas/handlers_returns_histories_withdrawals.py` — selected status evidence, joint returns recovery, neglected-publication source fields.
- `modules/sheets/src/zeler_sheets/formulas/handlers_orders_questions.py` — no-sale/answer absence and genuine last-change output.
- `modules/sheets/src/zeler_sheets/formulas/handlers_core.py` — inventory-code ambiguity by variation.
- `modules/sheets/src/zeler_sheets/formulas/recovery.py`, `recovery_worker.py`, and API admission — only if dedicated recovery types or durable scheduling must expand.
- `modules/sheets/src/zeler_sheets/event_persistence.py` and `devoluciones_reconciliation.py` — reuse existing observation/proof producers rather than inventing history or bypassing leases.
- `modules/sheets/tests/test_formula_recovery.py`, handler tests, and read-model tests — RED-first regression and complete recovery cycles.

### Approaches

1. **Repair reader/producer scope and recovery planning** — Keep global reconciliation as the strongest proof, add narrowly validated per-resource fallbacks where current producers already establish them, advance historical acquisition through real uncovered intervals, and reuse guarded returns reconciliation.
   - Pros: Uses existing gateway identity, lease, persistence, and source-fingerprint contracts; avoids unnecessary global scans for selected reads; makes missing data explicit.
   - Cons: Requires careful per-source proof design and live validation; some source resources can remain unavailable legitimately.
   - Effort: Medium to high across bounded work units.

2. **Reconcile all sources operationally without reader changes** — Run existing enrichment and reconciliation paths for the account and repeat formulas.
   - Pros: Can restore a short-lived positive control and distinguish acquisition failures from display bugs; particularly appropriate for the existing returns workflow.
   - Cons: Does not fix repeated expiration, shipment admission mismatch, catalog interval planning, or null-output defects.
   - Effort: Medium; useful verification support, insufficient as the complete repair.

3. **Remove freshness checks or increase TTL globally** — Serve all stored rows as current.
   - Pros: Superficially removes errors.
   - Cons: Misrepresents unknown inventory and stale mutable state; fabricates success for incomplete returns/history; invalidates existing safety tests.
   - Effort: Low but unacceptable.

### Recommendation

Use approach 1, supported by bounded operational reconciliation from approach 2. Preserve formula names and positional arguments unless ambiguity cannot be represented safely under the existing contract. Implement these independently verifiable work units:

1. **Output correctness:** missing SKU becomes internal empty identity and visible `NA`; absent answer/date and no-sale scalar become `NA`; last-change uses a documented real change field, retaining `NA` when only first-observed evidence exists. Test `None`, empty, zero, and literal valid SKUs separately. Ambiguous CODIGOML pairs must not silently choose a variation: establish an explicit deterministic ambiguity result or backwards-compatible optional variation selector with contract tests. Preserve vector order and duplicate input rows.
2. **Catalog interval convergence:** select the earliest uncovered gap from valid current plus retained proofs, bounded to 90 days and the requested horizon. Avoid moving acquisition keys unnecessarily while a proof cut is fixed. Regression: complete a 365-day request in successive chunks; preserve real gaps; do not trust stale/invalidated proofs; preserve shorter-window coverage while acquiring history.
3. **Shipment scope repair:** first establish the complete requested order interval, derive shipment identities, then resolve each required mutable shipment from recent owned evidence or enqueue explicit-ID recovery. Expose missing shipments rather than silently dropping them. Preserve closed/cancelled/status filters. Test an expired global marker with current individual shipment evidence and a pending-to-success cycle.
4. **Item-derived history scope repair:** for TIEMPOACTIVA, prove the selected item's current source and corresponding status state; trigger existing item recovery when stale. For selected PRECIOHISTORICO, retain genuine stored history while proving the current endpoint through item acquisition. For whole-inventory TIEMPOSINSTOCK, require current membership and individual stockout observations; return explicit partial coverage until the inventory is proven. Validate source/state identity and dates before using these fallbacks. Never infer unobserved historical transitions or intervals.
5. **Returns recovery:** exercise the existing focused reconciliation workflow for the known claim/window, preserving operation ownership and joint proof. If automatic formula recovery is necessary, integrate the same authority as a dedicated bounded job, not a generic claims read or independent freshness write. First test stale -> acquired/reconciled -> expected returned quantity, including concurrent changes invalidating the proof.
6. **Catalog/quality coverage:** first run the repaired demand pipeline and measure failures per source family. Preserve successful siblings and actual source-unavailable classifications. Add an accelerated-clock large-inventory regression before altering scheduling, so early batches cannot be mistaken for fresh at sweep completion. Do not widen freshness blindly; choose scheduler/refresh improvements from measured throughput. Keep CALCULADORA as the recovery regression control.

Affected contracts are formula missing-value and ambiguity semantics, scoped completeness/recovery intent, and potentially the durable recovery job model if new job types are introduced. Existing collection schemas and API arguments need no change for null rendering or interval gap selection. Any job-model expansion requires matching validators/schema export and rollout order; it is not an incidental code edit.

Live acceptance must repeat the same 24 primary and 11 supplemental cases in the supplied spreadsheet/profile 19, comparing output to sanitized production evidence from the VM. Record initial, after recovery, and after expiration results where applicable. Absent positive cases remain unverified rather than counted as successful fixes. No local code or passing test proves a deployed Sheets correction; compare intended and running image identities and retest the actual formula after deployment.

### Risks

- Historical status/price/stock records cannot reconstruct periods never observed; returning invented dates or durations would worsen correctness.
- Whole-inventory completeness may be impossible within the current acquisition budget without scheduling changes; partial output must remain explicit.
- Returning both codes for CODIGOML would alter scalar/vector spill shape; silently selecting one is also incorrect. Resolve this contract explicitly during design.
- Dedicated returns recovery intersects existing leases, fingerprints, and source quotas; broad generic recovery would bypass proven controls.
- Deployment requires an exact authorized main commit and immutable image provenance; build/deploy permission does not itself authorize a commit or merge.

### Ready for Proposal

Yes. The scope can be proposed as six bounded work units, with source-unavailable cases separated from confirmed output and recovery defects. No executable code was changed by this exploration.
