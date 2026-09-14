# Apply progress: full-inventory formula read cost

Live CATALOGO and BUYBOX calls exceeded the unchanged 25-second API deadline
after base acquisition made all 1900 items available. A VM/API read-only probe
measured projection read 3.191s, complete source read 5.679s and complete
fingerprinting 2.819s. Catalog association resolution repeated the source pass.
CALIDAD does not have that duplicate pass; its observed timeouts are a separate
load/latency observation, not evidence of the same control-flow defect.

## Implementation boundary

- An invocation-local private inventory snapshot retains exactly the owned
  source documents validated against rows. Catalog association readers consume
  that same cut instead of rereading later sources and mixing observations.
- Existing tuple wrappers remain compatible. Explicit legacy supplied-inventory
  callers still revalidate against current source documents.
- Complete source fingerprints, timestamps, ownership, row cardinality and
  variation associations remain enforced. No cross-request state or cache.
- CATALOGO skips orders when no catalog rows or covered sales window can use
  them. Otherwise it reads only the longest covered interval and consumed line
  identities/quantities. Unproved windows remain DATA_UNAVAILABLE with recovery.
- No public formula, schema, acquisition, pacing, lease, TTL or deadline change.

## RED/GREEN and independent evidence

Baseline: 212 existing tests passed. Initial new regression selection: 7 failed,
7 passed before implementation. Final focused selection: 230 passed in 0.89s,
including 17 structural/concurrency tests and a real-Mongo nested-order case.
Tests prove one complete source pass, rejection of row/source races, consistent
captured associations after later replacement, fresh validation on the next
invocation, legacy revalidation and safe bounds/projections for sales.

Independent review passed 166 tests in 0.70s and independently checked actual
Mongo projections with three order identity/quantity shapes and cancelled-sale
exclusion. The resulting six covered sales counts remained 9.

Full repository suite: 4626 passed, 9 skipped in 268.59s. The additional actual
Mongo test was added after collection and passed in the final 230-test selection.
Eight protected Mongo tests run separately; the remaining full-suite skip is
the inapplicable Caddy required-keys case. Full Ruff check/format and mypy over
543 files pass. Mypy first found local variable-name collisions; renaming those
locals without behavior changes and rerunning focused tests/types resolved them.

All Mongo verification uses the isolated loopback replica at port 27028.
Product runtime timing and visible results remain required after exact-source
image delivery. This report is scoped implementation evidence, not full-change
SDD acceptance.
