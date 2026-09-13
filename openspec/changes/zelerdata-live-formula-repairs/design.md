# Design: ZelerData Live Formula Repairs

## Technical Approach

Implement output correctness, scoped recovery, and existing returns reconciliation. Preserve signatures, widths, headers, seller isolation, and vector cardinality. No new recovery protocol, TTL expansion, or migration.

## Architecture Decisions

| Option | Tradeoff | Decision |
| --- | --- | --- |
| Normalize absence before string conversion | Prevents synthetic `NONE`; requires sales matching tests | Use empty internal SKU and visible `NA`; preserve real literal SKU strings and zeroes. |
| Choose first conflicting inventory code | Simple but silently wrong | Return `AMBIGUOUS_VARIATION` in that cell; identical duplicate codes resolve normally. |
| Treat observation baseline as historical transition | Misstates provenance | Render valid `last_status_change_at` as observed status evidence with `change_date_basis=observed_status_change`; otherwise `NA`. |
| Remove global freshness guards | Hides missing coverage | Retain strongest global proof; permit only validated per-resource fallback. |
| Repeat first historical recovery chunk | Never converges for long windows | Recover the earliest unproven gap, bounded to 90 days. |
| Add generic returns recovery | Duplicates joint-proof authority | Reuse existing focused reconciliation with leases and fingerprints. |

## Data Flow

Formula → validated scope → proven rows plus explicit gaps → existing recovery intent → worker acquisition/enrichment → persisted observations → recalculated formula.

### Group 1: Output correctness

PREGUNTAS normalizes absent answer/date. DIASDESDEULTIMAVENTA emits `NA` for no sale, preserving zero. PRODUCTOSINVENTA uses `_order_items`/`_item_quantity` for item-level sales exclusion without SKU; retain `_unit_totals` matching otherwise. Test shared normalization callers. Existing `last_status_change_at` includes first paused observations: render it with observed-basis metadata, never as reconstructed history, and never substitute `status_started_at` or `first_observed_at`. No production rewrite for rendering.

CODIGOML groups candidates by requested SKU/publication and counts distinct nonempty inventory codes. Zero codes yields `NA`; one yields the code; multiple yield `AMBIGUOUS_VARIATION`. Evaluate each vector element independently.

PUBLICACIONESDESCUIDADAS retains paused/full selection and withdrawal helpers. Missing reason/quantity is legitimate `NA`; never infer recommendations from paused duration alone.

### Group 2: Recovery and coverage

Catalog sales planning reuses validated current/retained interval proofs. Merge overlapping coverage, select the first gap inside the requested window, and cap its end at the next proof or 90 days. Preserve the established read cut and avoid equivalent moving requests while acquisition is pending.

ENVIOS first proves its actual 30-day order interval, then derives shipment IDs. Resolve recent owned shipment status evidence or request explicit-ID recovery. Missing required shipments remain visible; cancelled/closed filtering must not silently remove unresolved shipments.

For TIEMPOACTIVA and selected PRECIOHISTORICO, reuse current item acquisition and verify the corresponding status/history observation belongs to that source before reading. For whole-inventory TIEMPOSINSTOCK, require verified membership plus per-item stock observations and expose uncovered membership. Existing item recovery maintains observations; completion alone establishes no global proof.

Catalog/quality continue preserving independently successful rows. Measure source failures and sweep duration before scheduler changes; add an accelerated-clock regression if early batches expire during traversal. Do not extend TTL to satisfy a test. Unresolved throughput remains an explicit limitation.

Buybox validates fresh participation per resource inside the existing joined batch. Expired item dependencies reuse leased acquisition once, then revalidate ownership, freshness and participation. Failed siblings remain explicit; verified sibling snapshots survive. No global freshness marker is published.

### Group 3: DEVOLUCIONES

Use the existing focused operation in `infra/operations/zelerdata_read_model_reconcile.py` for the selected seller/window. Acquire source claims and associated orders, verify returned quantity and joint fingerprint, then publish through its existing lease authority. Recalculate the known claim fixture. No generic queue model or validator expansion.

## File Changes

Paths below are relative to `modules/sheets/`.

| File | Action | Description |
| --- | --- | --- |
| `src/zeler_sheets/formulas/read_models.py` | Modify | SKU normalization, proof-gap planner, validated resource resolution. |
| `src/zeler_sheets/formulas/handlers_core.py` | Modify | Code ambiguity. |
| `src/zeler_sheets/formulas/handlers_orders_questions.py` | Modify | Missing values, sales exclusion, transition date. |
| `src/zeler_sheets/formulas/handlers_item_shipping_catalog.py` | Modify | Shipment scope and gaps. |
| `src/zeler_sheets/formulas/handlers_remaining_phase4.py` | Modify | Stockout/history scoped reads. |
| `src/zeler_sheets/formulas/handlers_returns_histories_withdrawals.py` | Modify | Status fallback and supported withdrawal fields. |
| `tests/test_formula_*.py` | Modify | Focused regression and recovery evidence. |

## Interfaces / Contracts

No public signature changes. Additional internal metadata may describe partial coverage; no new persisted fields. Preserve existing recovery request types and source ownership checks.

## Testing Strategy

| Layer | Evidence |
| --- | --- |
| Unit | RED-first absence/zero, ambiguity/vector, SKU-less sales, genuine timestamps, interval gaps. |
| Integration | Isolated Mongo; stale → acquired → usable; wrong-owner and incomplete-source rejection; retained coverage and real gaps. |
| Live | Same 15 diagnoses plus CALCULADORA control; expected/actual/source evidence before and after recovery, and after expiry where relevant. |

## Threat Matrix

N/A — no new routing, shell, subprocess, VCS automation, executable classification, or process integration. Existing operational commands retain their documented controls.

## Migration / Rollout

No migration required. Identify affected images after implementation; exact authorized main commit, verified Cloud Build provenance, scoped deployment, compatible rollback, and spreadsheet recertification remain required. Operational returns reconciliation is separately recorded as a bounded data repair.

## Open Questions

None blocking. Measure source availability and acquisition throughput live.
