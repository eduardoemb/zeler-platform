# Apply progress: item acquisitions in flight

Scope: task 9.1 complete; task 9.2 implementation and focused checks complete,
independent review pending. Full gates, independent verification,
authorized delivery and the complete 90-minute acceptance window remain pending.
No commit, build, deployment or production mutation was performed by this unit.

## Evidence and implementation

Read-only VM profiling measured 1900 full canonical items totaling 18,672,549 BSON
bytes: source transfer 4.929 seconds and full fingerprint CPU 1.831 seconds.
Production projection aggregation measured 2873 rows totaling 12,792,679 bytes,
mean 4452.7 and maximum 5771 bytes. Isolated handler calls completed while live
whole-sheet calls exhausted the unchanged 25-second dispatch budget. These
measurements support repeated acquisition as a bottleneck, not a claim that all
remaining enrichment or inventory-expiry problems are solved.

An application-owned coordinator now shares only identical seller/identity-set
reads while acquisition is in flight. Database identity is enforced. Completion,
failure and final-waiter cancellation remove the flight; application shutdown
cancels and drains only owned tasks. No source TTL cache is retained. Each waiter
validates ownership, full source fingerprints, row counts and observation times
against its own request time and receives independent mutable documents.

Full canonical fingerprints are calculated before a private source evidence
view is constructed. This view retains exactly the fields used by catalog-product
association and buybox readers, including parent/variation product membership and
acquired promotional-price inputs. Item-history source reads are unchanged.
Changing an omitted source attribute still invalidates the complete fingerprint.
Rows remain complete; compact source views and rows are copied per waiter.

## TDD cycle evidence

| Slice | RED | GREEN | Refactor / triangulation |
| --- | --- | --- | --- |
| Concurrent acquisition | Real isolated Mongo, 1900 full sources: expected 1 acquisition, observed 7 before implementation (`/tmp/zeler-inflight-red.log`) | Seven concurrent reads share one read and exactly 1900 fingerprint calculations; 13-second simulated VM delay remains inside 25 seconds | Fixture expanded to 2873 projection rows, 12–14 MB, alongside 18–23 MB source BSON |
| Ownership and lifecycle | Missing coordinator interface failed freshness/cancellation/failure/owner tests before implementation (`/tmp/zeler-inflight-red-boundaries.log`) | Per-request future/expired timestamps remain unavailable; completed reads reacquire; distinct keys/owners remain separate; cancellation and failure drain | Both surviving-waiter success and last-waiter cancellation tested |
| Runtime wiring | Original test used an unavailable router shutdown helper; corrected to registered lifecycle callbacks. Replaying pre-change `build_app` then fails with undrained waiters (`/tmp/zeler-inflight-red-wiring-replay.log`) | Separate dispatchers within one app share; another app remains independent; shutdown only cancels that app's work | Real app factory and dispatcher wiring exercised |
| Compact source evidence | Test failed because bulky `attributes` remained in returned source evidence (`/tmp/zeler-inflight-red-compact.log`) | Price, parent/variation associations, source mutation isolation preserved; omitted-attribute change fails full receipt | Existing catalog, quality and API tests retained |

## Work unit evidence

- Safety net: 26 existing read-model tests passed before source edits.
- Focused command: `MONGO_URI=<verified-loopback-test-target> uv run pytest -o addopts='' -q modules/sheets/tests/test_item_read_acquisitions.py modules/sheets/tests/test_formula_read_models.py modules/sheets/tests/test_formula_handlers_item_shipping_catalog.py modules/sheets/tests/test_catalog_recovery_gaps.py modules/sheets/tests/test_formula_handlers_quality_calculator.py modules/sheets/tests/test_app_phase6.py modules/sheets/tests/test_formula_api.py`.
  Final result: **231 passed in 30.19 seconds**; output is `/tmp/zeler-inflight-final-focused.log`.
- Ruff and mypy: source coordinator, API/app wiring and new test file pass focused
  lint/type checks. Root owns final full-repository gates.
- Runtime harness: isolated loopback Mongo, verified writable primary, unique
  disposable test databases; production was only queried through the approved VM
  for aggregate profiling. Tests reject non-loopback targets.
- Rollback boundary: `formulas/read_models.py` coordinator/private evidence view,
  API dispatcher injection, `app.py` creation/shutdown hook and new
  `test_item_read_acquisitions.py`. No schema, quota, freshness or public contract
  changes. Revert this cohesive unit independently of returns/tag corrections.

## Local performance comparison

Each process retained returned sources as downstream association reads can do.
Payload contains 1900 synthetic full sources and 2873 synthetic projections
matching the measured BSON-size envelope. Times are local, not VM guarantees.

| Workload | Wall time | Peak RSS | Source reads |
| --- | ---: | ---: | ---: |
| Prior implementation, 7 full readers | 4.504 s | 1423.1 MiB | 7 |
| Shared compact evidence, 7 full readers | 1.528 s | 260.9 MiB | 1 |
| Shared compact evidence, 35 full readers (stress) | 6.070 s | 693.4 MiB | 1 |
| Shared compact evidence, 8 full + 27 distinct selections | 1.660 s | 301.7 MiB | 28 |

The first full-document-copy implementation was rejected after measuring
2344.4 MiB for 35 readers. The final compact view removes that duplication
without weakening the fingerprint or sharing mutable handler outputs.

Benchmark script: `/tmp/zeler-closure-release/benchmark-inflight.py`; sanitized
results `/tmp/zeler-inflight-benchmark-{realrows-baseline7,compact7,compact35,mixed35}.json`.
A live 35-case run, zero-stale inventory evidence and the full uninterrupted
90-minute window are still required. Local performance alone does not certify
production freshness or all formula values.

Independent root review: full-document fingerprint computation precedes compact
association views; the views retain every field consumed by catalog membership
and acquired-price readers. Request-local copies preserve mutation isolation.
Application/database ownership, in-flight eviction and shutdown remain explicit.
Root independently ran the in-flight and tag-basis tests against the verified
isolated Mongo target: 24 passed in 16.56 seconds. This is local evidence only;
whole-sheet live load, sustained inventory freshness and 90 minutes remain pending.
