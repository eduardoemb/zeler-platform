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

On session resumption at 04:53 UTC, September 13, the verified worker build
`b8f1fc42-ade0-4093-a074-a3be3fed5504` from `145ba4f` was already active at
digest `sha256:25c2b64a80e70c518689f219740ca50434b62d3f1384264129568da266fb4674`.
Consumer/component readiness passed twice. Six internal read-only history
formula executions on three original examples returned without unavailable
cells or recovery requests. The original failing item's status and stock
observations matched its acquired source. See
`docs/zelerdata-live-formula-repairs.md` for the full deployment identity and
measurement limits. Google Sheets requested a fresh sign-in in Profile 19;
authenticated Sheet retest and final acceptance remain pending.

September 14 live follow-up: the original selected history cases executed in
Sheets and matched canonical state/price. An active observation aged beyond
15 minutes returned DATA_UNAVAILABLE and requested recovery. After the later
selected-item job completed at 15:48:07 UTC, the Sheet again returned active=7,
paused=NA and price history 255.65/paused with absent older prices NA. This
verifies the selected history expiry/recovery cycle. Whole-inventory stockout
coverage remains partial. Full measurements and limitations are recorded in
`docs/sheets/zelerdata-live-retest-20260914.md`.
