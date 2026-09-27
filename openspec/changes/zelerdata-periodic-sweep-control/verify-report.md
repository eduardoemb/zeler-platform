# Verification: ZelerData Periodic Sweep Control

Status: local behavior correction verified; production rollout remains in progress. Do not treat this report as proof of a settled live call rate until the post-backlog measurement is recorded.

## Production evidence before rollout

On 26 September 2026, the consolidated 937-publication buybox recovery reached terminal `failed` at offset 937 with failed offsets 380, 620 and 660. A previously superseded 934-publication buybox job subsequently reopened and advanced. At 23:42 UTC, the gateway logged 862 `proxy.call` events in five minutes, while bulk acquisition remained active. On 27 September at about 00:04 UTC, the pilot also had a 1,900-item job, a separately reopened 1,896-item inventory job, an 875-product job and the 934-item buybox job active. This demonstrates that active-ID coalescing alone cannot produce an idle baseline: the scheduled refresh admits another full pass after terminal cooldown.

A later fixed five-minute window contained 791 Sheets gateway calls: 493 other source calls, 91 item details, 88 performance, 79 price-to-win and 40 offers. The six bootstrap calls in that window were separate. These measurements are pre-rollout, active-backlog baselines, not a settled rate.

The failed offsets covered 60 buybox publications. All 60 had persisted price and status snapshots, but only 52 had a new competition observation after the consolidated job began: 16/20 at offset 380, 16/20 at 620 and 20/20 at 660. The eight without a new observation were the last four positions in each of the first two chunks. The historical job records only `source_incomplete`, so the exact per-item exception cannot be recovered. Correlated gateway windows contained successful price-to-win calls, offers 200/404, and one offers 206 near offset 660; time proximity does not establish which response caused the chunk failure. Unknown competition remains visibly unavailable.

## Local behavior evidence

- RED: the new default-factory test failed because the old factory selected all six models instead of only `orders` and `questions`.
- GREEN: 62 focused refresh and inventory-cadence tests passed after wiring the default range-only planner and explicit bulk opt-in.
- Full `uv run pytest -q --tb=short --disable-warnings` passed against a verified isolated local Mongo replica set with a named test database; nine environment/contract cases were skipped. An earlier suite invocation used the same isolated server without a default database name, causing unrelated fixture configuration errors; focused examples passed after correcting the test URI and the full suite was rerun.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, and the direct-Meli lint passed.
- `git diff --check` passed; unrelated pilot task edits and `.codegraph/` remain outside this change.

## Rollout and post-backlog observation

Pending exact commit, VERIFIED worker image digest, running rollback digest, health and post-backlog call-rate evidence.
