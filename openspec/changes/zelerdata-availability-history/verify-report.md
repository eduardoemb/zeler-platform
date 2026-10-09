# Verification: ZelerData Availability History

## Local result, 9 October 2026

Verified locally. No production database, validator, image or service was
touched.

- TDD red/green: the schema/index contract, the core model, the writer, the
  event and acquisition hooks, the read-time metrics and both handlers each
  failed first (missing file/module, no rows written, or the old
  `stock_time_metrics` gate) and pass now.
- The writer tests run against the loopback test Mongo with the exported
  strict validator applied: change-only rows, four concurrent copies of one
  observation writing a single row, older observations ignored, unknown stock
  or status ignored, one series per variation, and a malformed insert rejected.
- The handler tests run end to end in real Mongo: seller time zone, range
  clipped to now, `Sin histórico antes de <fecha hora>` / `Sin histórico`, ISO week
  headers, SKU and ID filters, other sellers' rows excluded, more than 1,000
  rows served, and `DATA_UNAVAILABLE` without recovery when the
  `item_status_states` heartbeat is not live.
- Tests that asserted the old `stock_time_metrics` contract for these two
  formulas were removed; four test fakes gained the `sort` / `insert_one` the
  Motor API already has, because every item observation now calls the writer.
- Full repository `uv run pytest`, before rebasing: 22 failures, the 12 known
  pre-existing ones (DLQ snapshot and deployment preflight) plus ten consumer
  test fakes without `insert_one`/`sort`, which were completed. After rebasing
  onto `main` (CATALOGOTIEMPO and the macOS bash 3.2 test fix): 6,892 passed,
  32 skipped, 0 failed. The shared test Mongo was OOM-killed twice during
  earlier runs and restarted with `docker start`; the final run needed no restart.
- Coverage messages use `%Y-%m-%d %H:%M` in the seller's zone, as
  `CATALOGOTIEMPO` does: with the date alone, a range starting that same day
  would still be uncovered without saying why.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`,
  `infra.lint.check_direct_meli`, the schema export check and `git diff --check`
  pass. The probe ran read-only against an empty local database.

## Runtime acceptance still required

1. Apply only the `sheets_item_availability_transitions` validator and its index
   from the approved runtime (`infra/mongo/apply_validators.py`), before the new
   images, so the first insert meets the strict validator.
2. Build and deploy `sheets-worker` and `sheets-api` from the integrated `main`
   commit under their own authorization.
3. Verify: the probe reports rows, distinct publications and a first/last
   `observed_at` after the next inventory sweep or item events; worker health and
   item event processing (no new DLQ entries from the writer);
   `ZELERDATA_TIEMPOSTOCKACTIVO` and `ZELERDATA_SEMANASCONSTOCK` for the pilot
   return rows, with `Sin histórico antes de <fecha hora>` for ranges before coverage.
