# Verification: ZelerData Buybox Load Control

Status: local implementation and pilot rollout verified through a 90-minute observation on 26 September 2026. The consolidated catalog jobs remain in progress.

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
- Production mutation followed a separately authorized rollout and is recorded below.

## Production rollout and 90-minute observation

- Commit `5587acb66f73d9a5e2e03610da2414eb7839b8ba` was pushed to `main`. Two separate VERIFIED Cloud Builds from the connected repository passed provenance verification: API build `88baf4ef-e7c5-4092-8ecf-7b54d1434070` produced `sheets-api@sha256:2d011315caad2ff05fb84fd07b7115a955daa905958dd5c21961f616c5b3ff64`; worker build `27fd9de7-45aa-46ac-b94a-cf9aeb0bd3ff` produced `sheets-worker@sha256:ebffdd44ce2e662ba547eb2794ac51e954e8f1c642753935305cae9f47f6e162`.
- Root disk preflight passed before both pulls and after them, with 32 GiB free after download. The previous running images were recorded and remain the compatible rollback targets: API `sha256:77e8fe83cdb52423f662cf4fe24acbbd83d1bdedc35896b86dec77e52b6de86d`; worker `sha256:dd7df6afcbbf7b7f0c4c10b7985220c486a093914a933b8c50dccf8c5a5243f3`. No Docker cleanup or VM resize was performed.
- Only `sheets-worker` was stopped. A backup of Compose was saved under `/opt/zeler-platform/rollout-5587acb-buybox/`; only the two Sheets image references changed. The VM provenance preflight bound both digests to the authorized commit. A drained preview for seller `82453304` found eight buybox jobs and 937 distinct unfinished publication IDs; execution accepted the exact preview fingerprint `3dd9997bebbe5f93f6454b37e4953dd53e452fab7fccf60b169777de0cc1821b`, preserved all eight old jobs as superseded evidence, and created one replacement. The independent item job was untouched.
- At 0 minutes the API and worker ran the selected digests, were healthy with zero restarts/OOM, and the worker reported RabbitMQ, sync jobs, formula recovery and ZelerData refresh `ok`. A newly acquired snapshot with verified price and unknown competition rendered `DATA_UNAVAILABLE` in the deployed formula handler. The buybox replacement started at 0/937 with zero failed chunks.
- At 30 minutes, buybox was 260/937 and the item job 480/1,900, both with zero failed chunks; the event queue was empty, DLQ 197 and available memory 1,215 MiB. A shifted five-minute gateway window had 64 offers 404 calls across 63 distinct routes; one route appeared twice. No upstream 429 was observed.
- At 60 minutes, buybox was 520/937 with one `source_incomplete` chunk and the item job 740/1,900 with none. All four inspected containers were healthy with zero restarts/OOM, worker components were `ok`, DLQ remained 197 and memory available was 1,152 MiB. The last five minutes had 35 offers 404 on 35 distinct routes and no upstream 429.
- At 90 minutes, buybox was 760/937 with three `source_incomplete` chunks and the item job 940/1,900 with none. All four inspected containers were healthy with zero restarts/OOM; API `/health` and gateway `/ready` returned 200, worker components were `ok`, the event queue was empty and DLQ remained 197. Available memory was 1,169 MiB, root space about 31 GiB and the separate Mongo disk about 45 GiB, with ample inodes. The final five minutes had 39 offers 404 on 38 distinct routes, one route repeated twice, and no upstream 429.

The three incomplete buybox chunks were offsets 380, 620 and 660. All 60 publications in those chunks had persisted backfill snapshots with price and buybox status; 29 had unknown competition. This is a residual completeness signal to investigate, not evidence of repeated catalog coverage. The replacement job was still running at the observation cutoff. Total gateway proxy traffic remained around 870 calls per five minutes while the one-time backlog was processing, so the 90-minute window proves removal of duplicate active coverage and repeated 404 routes, not a settled post-backlog call rate. No capacity increase is justified by this window; recheck after the jobs reach terminal state or if memory pressure becomes sustained.
