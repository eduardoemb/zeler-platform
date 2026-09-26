# Proposal: ZelerData Buybox Load Control

## Intent

Keep missing catalog offers from failing otherwise useful buybox acquisition, and stop overlapping recovery requests from multiplying calls on the pilot VM.

## Scope

- Treat a 404 from the optional catalog offers listing as unavailable offer evidence; preserve a verified price-to-win observation and render unknown competition fields as `DATA_UNAVAILABLE`.
- Coalesce active buybox publication IDs across catalog and small requests for the same seller, including concurrent admission.
- Provide a fingerprinted, dry-run-first reconciliation of existing overlapping buybox jobs, preserving successful chunks and old job documents.
- Observe request rate, queue progress, DLQ and VM capacity before considering a resize.

## Boundaries

Other HTTP failures, malformed offers, ownership checks and source-version checks retain their current behavior. Formula names, columns, manual refresh and the 15-minute buybox snapshot freshness rule remain unchanged. Production queue mutation and image deployment require a new scoped approval.

## Rollback

Restore the prior verified Sheets API and worker digests if runtime behavior regresses. Preserve reconciled job and snapshot evidence; stop recovery before reverting a worker that would resume legacy overlap.

## Success criteria

- A catalog offers 404 completes the chunk while the competition count remains visibly unavailable.
- Active buybox jobs contain no duplicate publication coverage for the same seller after admission and guarded legacy reconciliation.
- Production worker health, queue progress and memory remain stable with fewer repeated catalog offers 404s.
