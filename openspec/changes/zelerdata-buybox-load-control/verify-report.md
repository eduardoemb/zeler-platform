# Verification: ZelerData Buybox Load Control

Status: local implementation verified; commit, build, production reconciliation and deployment pending separate authorization.

## Production evidence before this change

The quality/item rollout from `a5c38c4970bf1b3a0740b5ff2be6088ce79b996f` remained healthy for 90 minutes on `platform-vm`: Sheets API/worker, gateway and Mongo stayed healthy with zero restarts and OOM flags; final available memory was about 1.34 GB; Sheets DLQ stayed at 196. The replacement item job advanced from 0 to 140 of 1,900 IDs with zero failed chunks. Quality 404s fell from the 26 September baseline of 681 in 40 minutes (~17/min) to 37 in the last five minutes (~7.4/min), with no repeated quality path in that window and no upstream 429.

Residual buybox work remained substantial. At its peak, nine active buybox jobs held 8,368 IDs in aggregate for only 937 distinct publications; most failed chunks reported `source_rejected`. In the final five-minute window, the catalog offers listing returned 404 on 62 calls while price-to-win observations continued to succeed. Eight active buybox jobs still held 7,433 IDs in aggregate for the same 937 distinct publications. This is the target of the present change, not evidence that it has deployed.

## TDD and local checks

| Work unit | RED | GREEN | Refactor |
| --- | --- | --- | --- |
| Optional offers 404 | Existing `retained_404` and new `unavailable_404` expectations failed: job `failed` instead of `completed`. | Both pass; 503, malformed offers and identity checks still follow existing paths. | Ruff formatting passed. |
| Active buybox coalescing | Overlapping, concurrent and small requests created duplicate active IDs. | All three scenarios pass for item and buybox models against isolated Mongo. | Shared the existing seller admission transaction. |
| Legacy buybox reconciliation | New buybox wrapper import failed before implementation. | Preview/execute, live-lease refusal, changed-fingerprint refusal and preservation of an unrelated item job pass against isolated Mongo. | Shared the existing guarded transaction, with model-scoped fingerprint and replacement key. |

- `uv run pytest -q modules/sheets/tests/test_formula_recovery.py --tb=short`: passed.
- `uv run pytest -q --tb=short` with the verified loopback Mongo test target on port 27028: passed; nine environment skips, no failures.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, and `uv run python -m infra.lint.check_direct_meli .`: passed.
- Operator CLI dry-run and execute smoke against a disposable isolated Mongo database: passed; two old jobs preserved, one replacement with three distinct unfinished IDs; only aggregate values printed.
- No production buybox job or service was mutated for this change.

## Runtime gate and rollback

After an authorized commit and two VERIFIED Cloud Builds, record exact image digests and the current running rollback digests. Stop only Sheets worker; preview and reconcile the buybox jobs with a matching fingerprint and no active lease; deploy only Sheets API and worker. Verify formula `DATA_UNAVAILABLE` for unknown competition, job progress, offers 404 rate, DLQ, readiness, memory and disks at 0/30/60/90 minutes. Restore the prior compatible images if those checks regress, preserving job evidence.
