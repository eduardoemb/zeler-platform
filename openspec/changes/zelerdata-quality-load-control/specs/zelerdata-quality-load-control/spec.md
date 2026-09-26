# ZelerData Quality Load Control

## Requirements

### Optional quality absence

When `/item/{id}/performance` or `/user-product/{id}/performance` returns 404 for an owned publication, the worker MUST preserve an honest quality gap and MUST NOT retry the whole acquisition chunk solely for that gap. A missing quality value MUST continue to render `DATA_UNAVAILABLE`.

### Source-specific recheck

After that 404, the platform MUST defer another quality probe for the same unchanged item until one hour after the recorded check. A changed source `last_updated` MUST make it eligible immediately. Rate limits, transport failures, server errors and other field failures MUST retain their existing retry paths.

### Bounded admission

Concurrent, repeated formula requests MUST NOT admit duplicate active item IDs for one seller. The platform MUST admit any uncovered IDs and MUST NOT treat one seller's jobs as coverage for another seller.

### Legacy reconciliation

The operator MUST see a dry-run fingerprint and counts before any queue mutation. Execution MUST reject a changed plan or active worker lease, preserve prior job documents and successful chunks, and create at most one bounded replacement job for unfinished unique IDs. It MUST not claim source completeness or erase error evidence.

### Operational acceptance

The rollout MUST apply the additive `items` validator before new writers, prove an authenticated quality formula still reports an unavailable source honestly, and observe request rate, 404 rate, queue jobs, memory and worker health for 90 minutes before recommending a VM size change.
