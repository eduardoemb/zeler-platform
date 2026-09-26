# Verification: ZelerData Quality Load Control

## Local result, 26 September 2026

The implementation is locally verified. No production validator, queue or service was changed in this work unit.

- TDD red/green: an optional performance 404 initially kept the item chunk pending; the new validator initially rejected `quality_probe`; overlapping catalog and small-ID jobs initially duplicated coverage; a recent 404 initially displayed an old quality score. All corresponding tests now pass.
- Focused tests: complete `test_formula_recovery.py`, `test_sheetseller_backfill.py` and `test_formula_handlers_quality_calculator.py` passed. A further focused check verified that the worker probes again when the persisted one-hour wait expires, even if the item did not change. The legacy reconciliation tests used the isolated local Mongo replica set and verified dry run, stale fingerprint rejection, lease rejection, preserved old records and only unfinished IDs in the replacement job. Concurrent catalog admission retained unique active ID coverage.
- Full repository: `uv run pytest -q --tb=short` passed against the verified loopback test Mongo target using direct connection. Nine integration or environment tests were skipped by their existing guards; eight stock-time tests rejected the ambient URI as non-acceptance, and one Caddy contract test lacked required keys. No test failed.
- Root checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, direct-Meli lint and Mongo schema export check all passed. `git diff --check` passed. The operational CLI ran against an empty isolated Mongo database in its default dry-run mode and reported zero jobs without mutation.

## Runtime acceptance still required

The live VM has not received this code. Apply the `items` validator and deploy verified `sheets-api` and `sheets-worker` images only under the separate scoped authorizations in `docs/ops/zelerdata-quality-load-control.md`. Preview and separately authorize consolidation of the four legacy overlapping jobs. Observe 0/30/60/90 minute request rate, quality 404s, queue progress, DLQ, health, OOM and memory. Only then decide whether the 4 GB VM remains adequate. The separate `/products/{id}/items` 404 source was observed in the baseline and is outside this quality-specific correction; reassess its rate after this rollout.

Read-only snapshot at about 18:47 UTC: `platform-vm` was `RUNNING` as `e2-medium`; both Sheets containers were healthy, with zero restarts and no OOM flag. The running immutable identities were `sheets-api@sha256:99e20506138c059c43722857105a448ce4143379b2d340ac0c4518be8e7ac364` and `sheets-worker@sha256:28149428e4486f3133c54bd953cdb5753e8e799b709790dc82c89a9e5bb36826`. Available memory was 748,732,416 bytes, root free space 35,579,351,040 bytes, and Mongo disk free space 48,154,230,784 bytes; root and Mongo inode use were 4% and 1%. These samples are deployment preflight leads, not a sustained capacity result.
