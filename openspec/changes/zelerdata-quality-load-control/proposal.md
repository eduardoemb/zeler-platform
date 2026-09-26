# Proposal: ZelerData Quality Load Control

## Intent

Keep optional publication quality acquisition from repeatedly loading Mercado Libre and the small platform VM when performance data has not been generated.

## Scope

- Persist one source-specific probe per publication after `/performance` returns 404; recheck after one hour or when the source publication changes.
- Keep quality visibly unavailable while the source has not supplied it. Continue to retry rate limits, server errors and other transient required-field failures.
- Complete item batches despite an optional quality 404.
- Admit only item IDs not already covered by active recovery jobs for the same seller.
- Provide a guarded, dry-run-first reconciliation for overlapping legacy item jobs without deleting their evidence.
- Validate the pilot under a 90-minute observation window before deciding whether the VM needs more memory.

## Boundaries

The existing formula names and shapes, manual formula refresh, source-specific freshness, seller scope, shared 180/min pacing and event topology remain unchanged. No global cache TTL or unverified availability claim is added. Production validator changes, service deployment and queue reconciliation require separately scoped approval.
