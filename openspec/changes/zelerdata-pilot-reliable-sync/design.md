# Design: ZelerData Pilot Reliable Sync

## Preserved Contract

Gateway→AMQP→guarded projections→read-only formulas→Apps Script remains the architecture. Preserve all 52 names/signatures/shapes, seller isolation, claims topology, idempotency/retry/DLQ, monotonic writes, field-specific freshness and independent available values. Receipt/fetch/persistence/visible timestamps require actual corresponding evidence; export append is not visibility.

Keep fixed UTC 12-calendar-month coverage, monthly intervals ≤90 days, retention-edge priority, modification-based overlap, and explicit unavailable history—not synthesized price/stock/quality/competition. Sheets refresh preserves formula text; existing configuration exposes progress/retry. Acceptance still requires representative positive/absent/filter/range cases, prior regressions, actual open/reopen Sheets behavior, returns resolution, full repository gates and 90-minute rounds 0/30/60. Shared pacing remains 180/min; builds, deployment and add-on publication require separate authorization.

## Range Acquisition Amendment

`formulas/recovery_worker.py` buffers entire ranges; the admission ledger is not acquisition progress.

| Option | Tradeoff | Decision |
| --- | --- | --- |
| Save offset only | Loses fetched details; mutable pages shift | Reject. |
| Reload all staged payloads | Retains unbounded publication transaction | Reject. |
| Durable receipts, bounded projection, separate proof | Additional operational collections | Choose; reuse queue ownership and guarded writers. |
| Twelve question searches | Repeats seller-wide enumeration | One shared scan, monthly subscriptions. |

### Durable Protocol

1. Claim the existing queue lease; create/reuse an acquisition generation. Head stores seller/resource/plan/job identity, fixed bounds, phase, cursor/page sequence, counts, failure/drift budgets and publication checkpoint. Every mutation transaction CASes head generation/sequence and `queue._owned`; expired owners cannot advance.
2. Persist validated search membership before fetching details. Save each scoped detail, unavailable-field receipt, source version/hash and original observation timestamp. Commit receipts plus checkpoint atomically; replay matches identity/hash, contradictory duplicates trigger drift. Never log cursors/payloads.
3. Yield after ≤50 search identities or ≤20 projected records, additionally ≤4 MiB/transaction and ≤1 MiB/receipt. Head stays ≤64 KiB. Oversize input becomes an explicit local-budget blocker, not lost data or provider limitation. Preserve fetched records across interruption.
4. Progress yield resets consecutive-attempt accounting only after durable progress; transient failures retain three-attempt limits. Local quota deferral preserves checkpoints without charging attempts. Expired cursor/drift starts a new enumeration pass, retains receipts, and exhausts a separate three-restart budget rather than looping indefinitely.
5. Acquisition failure alone withdraws nothing. Before first projection, subtract only the affected interval from existing proofs, retaining unaffected pieces; no remaining proof means stale. Project bounded batches through `SheetsEventPersistence`, retaining original observation times and newer concurrent events. Orders reacquire Devoluciones operation ownership with `invalidate_readiness=False`; commit guarded writes/checkpoint/operation release together.
6. Finalization checks membership, required fields and receipt-backed exclusions using indexed anti-joins. In one bounded transaction fence the owner, CAS the current marker, merge verified intervals and complete the job. Marker conflicts retry without overwriting concurrent authority. Partial publication never certifies totals.

### Source Semantics

Orders retain creation-range search, revalidate known-but-search-absent identities, and compare complete ID/version manifests across traversal passes. Neither empty pages nor equal totals prove completeness; changed membership/version restarts verification while preserving acquisition. The 10,000 limit is a local budget; oversized windows require subdivision, not a retention claim.

Questions use one internal `QuestionScanRecoveryRequest` per seller/fixed plan, with durable scan continuation; monthly ledger entries subscribe to its interval proofs. Do not invent date/modification filters. Fresh scans validate membership; detail receipts are partitioned locally by creation date. Retain separate interval proofs instead of expanding every request's acquisition.

Evidence describes the observation window, not an atomic provider snapshot. Freshness derives from receipts, never finalization time. Shipment discovery consumes order receipts later; items/claims require their own acquisition authority.

## Persistence And Rollout

Add `core/src/zeler_platform_core/models/sheets_history.py`, register models, and extend `core/src/zeler_platform_core/cli/export_schemas.py`. Export strict validators and `infra/mongo/indexes/` definitions for `sheets_history_acquisitions` and `sheets_history_receipts`.

Heads: unique seller/resource/plan/chunk-or-scan; receipts: unique acquisition/generation/pass/kind/resource-ID plus ordered acquisition/pass/page lookup. No TTL on active or retained receipts. Queue generation references are additive; existing jobs need no migration.

Authorize validators/indexes before enabling the checkpoint-aware worker. Rollback requires a checkpoint-compatible image; otherwise disable recovery/admission and drain owners before replacement. Preserve receipts/canonical history and incomplete-proof withdrawal; legacy workers must not claim new-format jobs.

## Ordered Implementation Units

| Unit | Exact RED harness/dependency |
| --- | --- |
| Next: receipt schemas | Isolated Mongo rejects malformed/state-invalid records; exports match; no activation. |
| Fenced receipt store | Lease expiry, duplicate/conflicting receipts, atomic checkpoint crash, byte limits; depends on schemas. |
| Queue continuation | Progress versus failure/quota accounting; depends on store. |
| Orders producer | Crash after page/detail, shifted offset/same-count drift; depends on continuation. |
| Bounded publisher | Newer event, operation loss, interval subtraction preserving unrelated reads, interrupted batch/no false totals; depends on receipts. |
| Shared questions scan | Cursor expiry, one scan/twelve subscriptions, divergent manifests; depends on publisher. |
| Cross-resource completion | Shipment manifests, claims/items authority, sustained lane fairness; separate units. |

Implementation/tests: `modules/sheets/src/zeler_sheets/`, `modules/sheets/tests/`. Threat matrix: N/A—no shell/subprocess/VCS/process-launch changes. Provider cursor validity, subdivision precision and actual retention require primary-source verification before their adapter units, not assumptions.
