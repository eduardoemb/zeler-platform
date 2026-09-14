# Apply progress: layered basic acquisition

Task 6.1 implementation is complete in the selected checkout; the orchestrator
owns the cumulative task checkboxes and independent verification. Earlier units
remain recorded in the existing apply-progress files and are not superseded.
No commit, build, deployment, production write, or VCS administration was done.

## Implementation

`run_item_detail_enrichment` adds `base_only=False`. Basic acquisition retains
canonical ownership, variation SKU resolution, source-order protection and the
complete-document CAS. It skips shipping, price quote, promotion and quality
requests even when their full-mode flags are enabled. Full acquisition remains
the default. Existing enrichment observations retain their original dates;
changed shipping, fee, promotion or quality references become `basis_mismatch`.
Untracked quality with an existing observation also gains an invalid state when
its reference changes. Promotion references include currency as well as price.

Selected projections constrain order-line identity and status-state reads to
the requested IDs; unfiltered callers retain their original account-wide scope.
Quality fetches use the paced HTTP helper so local quota waits do not consume
the five-second source deadline. Helper TDD evidence belongs to task 6.2.

## TDD cycle evidence

| Behavior | Safety net / RED | GREEN / triangulation / refactor |
| --- | --- | --- |
| Basic mode, observations and scoped reads | 182 existing backfill tests passed; new suite: 4 failed, 1 passed before code | 5 passed; changed/unchanged source and filtered/unfiltered projections |
| All projection references, untracked quality | Untracked-quality missing state failed; corrected incomplete fixed-fee test fixture | 8 passed, retaining matching references and invalidating changed references |
| Promotion currency | 1 failed, 1 passed before currency guard | ARS retained, USD invalidated |
| Repeated unchanged acquisition | Second fetch after 16 minutes failed with `items_updated=0` before the guard fix | Reacquisition updates the base observation through CAS while shipping enrichment retains its old date |
| Existing CAS and Mongo projection | Real isolated Mongo, successful acquisition and concurrent same-timestamp write | 2 passed; current write preserved on retryable conflict |

## Work unit evidence

| Evidence | Result |
| --- | --- |
| Focused command | `MONGO_URI=<verified isolated loopback rs0> uv run pytest modules/sheets/tests/test_layered_basic_acquisition.py modules/sheets/tests/test_sheetseller_backfill.py -o addopts='' -q`: **195 passed in 0.59s** |
| Runtime harness | The two Mongo cases run the real acquisition/CAS and successful formula projection against a unique disposable database on the verified port 27028 replica set; no production data |
| Static checks | Ruff check and format passed for both files; mypy passed for both source files; `git diff --check` passed |
| Rollback boundary | Remove only the base-mode/enrichment guard and selected-read additions in `sheetseller_backfill.py` with the new focused tests; revert the quality helper integration separately with task 6.2 |

Authored executable/test scope: 111 additions + 36 deletions in backfill and
261 new test lines (408 total before this evidence). The pacing integration is
a separate review boundary from basic acquisition and scoped dependency reads.
No code or evidence was compressed to satisfy a review budget. Full repository
gates, live freshness, two inventory cycles and the 35-case Sheet retest remain
owned by the orchestrator; these local tests do not establish production health.

The repeat-cycle regression caught the legacy equality comparison excluding
`last_meli_sync_at`. Basic acquisition now always executes its existing guarded
write after a successful fetch, including unchanged source values. Full-mode
unchanged behavior remains preserved. Review the pacing-helper integration as
a separate unit; the total assigned code/test scope exceeds 400 authored lines.
