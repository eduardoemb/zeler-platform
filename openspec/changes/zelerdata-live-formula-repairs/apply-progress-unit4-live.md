# Live recovery writer correction

The first deployed repair exposed a missing connection in the actual worker:
`_acquire_item_batch` enriched canonical items and rebuilt formula rows, but did
not record status, price, or stock observations. At 03:49 UTC, a freshly acquired
MLM1939453749 still had September 10 status evidence. The strict reader correctly
rejected this mismatch. The earlier Mongo test exercised real writers separately
and therefore did not prove the production acquisition chain.

RED: `test_real_item_recovery_projects_history_at_actual_acquisition` executes
the actual worker acquisition with a transport fixture and real isolated Mongo.
It failed because `last_observed_at` remained three days behind `last_meli_sync_at`.

GREEN: project acquired item histories before rebuilding formula rows, using the
stored source time and existing guarded status/price/stock writers. Preserve the
original status start, do not certify global inventory, and label observations
`current_observed`. Check the recovery lease before each projection.

Tests cover active and paused results through formula dispatch, price observations,
unchanged state starts, foreign ownership, and newer status evidence. Final gates:
4,543 passed / 9 skipped in 174.50s; the eight protected Mongo cases passed
separately, leaving only the existing Caddy skip. Ruff check/format and mypy pass
across 533 files. The initial retry omitted a default database; after correcting
the URI and restarting the local container stopped during session interruption,
the complete suite was rerun successfully. No production database was used.
