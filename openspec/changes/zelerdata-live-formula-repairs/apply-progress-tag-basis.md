# Economic basis tag order — bounded implementation evidence

Implemented in enrichment.py, sheetseller_backfill.py and event_persistence.py,
with focused tests in test_enrichment_tag_basis.py. No production mutation,
migration, TTL change, API/schema change, build or commit performed by this unit.

Strict TDD: initial order/hash regression produced 5 failures and 9 passes;
shared matching then passed 14. A further fee-context canonicalization regression
failed on [b,a,a] versus [a,b], then passed after sorting/deduplication. Event
preservation coverage verifies the original hash, timestamp, status and raw tag
basis survive normal BSON normalization. Final new tests: 16 passing.

The focused new + existing event, backfill and layered basic acquisition suite
passed all 289 tests against the isolated development Mongo at port 27028.
Focused Ruff and mypy (4 files) passed. Final repository gates and independent
review belong to the parent executor; this is not live freshness acceptance.

Compatibility prefers retained semantic bases over order-sensitive legacy hashes.
Hash-only states get no guessed permutation compatibility. Other changed basis
fields and malformed tags remain nonmatching. Fee request contexts use the same
canonical tags; unrelated shipping_modes order remains unchanged.

Rollback boundary: revert these three production-file changes and this new test
as one review unit. New hashes include canonical tags but raw basis remains
persisted; no collection/schema migration or observation-date rewrite is needed.
Already invalidated or expired observations still require actual reacquisition.
