# Proposal: ZelerData Periodic Sweep Control

## Intent

Let the pilot's existing backlog finish without immediately scheduling another full-seller inventory or catalog pass. Keep automatic bounded range refresh and formula-triggered recovery available.

## Evidence

On 26 September 2026, the consolidated 937-ID buybox job reached terminal `failed` with three incomplete chunks. The 15-minute scheduled refresh then reopened a superseded 934-ID buybox job. An inventory job for roughly 1,900 items, a second item job, and an 875-product job were active at the same time. A full pass takes much longer than the refresh interval, so the scheduled loop cannot reach an idle call rate.

## Scope

- Keep `orders` and `questions` in the scheduled 15-minute range planner.
- Make full-seller inventory, catalog product, buybox, and shipment sweeps opt-in with one explicit runtime flag, default off.
- Keep formula-triggered recovery, event processing, existing jobs, queue admission, source validation, snapshot freshness, and visible `DATA_UNAVAILABLE` behavior.
- Observe terminal jobs and post-backlog gateway call rate before considering capacity changes.

## Rollback

Restore the previous verified Sheets worker image if range refresh or formula recovery regresses. The change adds no schema or queue mutation and does not delete existing jobs.
