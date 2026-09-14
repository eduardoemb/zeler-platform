# Return UTC membership and truthful chunked readback

Status: implementation and focused verification complete; parent full gates pending.
Selected store: openspec. This is a bounded uncommitted implementation slice under
the parent apply attempt; no independent lock, commit, build or production write.

## Problem and contract

The May 14 source inventory contained four return candidates; all four canonical
claims already existed locally. One candidate was 3317 seconds before the UTC
interval, with matching aware search/detail creation instants. The existing UTC
readback correctly counted three, while source expectation incorrectly counted
four. Retrying the productive write could not resolve this discrepancy.

Post-detail classification now excludes only proven outside-window membership:
same identity, validated seller respondent, matching aware search/detail creation
instant, and canonical half-open UTC bounds. Full two-pass inventory and its
fingerprint retain all candidates. Missing/invalid/contradictory evidence fails
closed; final source revalidation still protects publication. No existing claim
is deleted, retimestamped or rewritten by this classification.

Large dry runs now sum measured per-window local counts rather than manufacturing
persisted/complete counts from expected cardinality. Unknown queries remain
unknown; duplicate expected IDs across disjoint windows invalidate certification.
Physical counters are per-recorder attempts. Aggregate source/read-model proofs
use their respective hashes and bind them to seller and ordered UTC scopes.

## Strict TDD evidence

| Behavior | RED evidence | GREEN evidence |
| --- | --- | --- |
| Four search candidates, three UTC members; boundary/identity proof | `/tmp/zeler-closure-release/may14-red.log` | New membership regressions |
| Actual Mongo readback and bounded outside counter | `/tmp/zeler-closure-release/may14-counter-red.log` | Three in-range rows, fourth retained, no markers/writes |
| Missing/complete/unavailable/overlapping chunk readbacks | `/tmp/zeler-closure-release/may14-chunk-red.log` (4 failures) | Measured counts and explicit uncertified overlap |
| Independent source/read-model hashes and scope binding | `/tmp/zeler-closure-release/may14-fingerprint-red.log` | Changing one proof changes only its aggregate; scope changes both |

The 18 new cases passed against an explicitly selected loopback Mongo at port
27028; tests use the standard `default_mongo_uri` fixture, require loopback and a
writable primary, create random test databases and drop them in finally blocks.
No production database is a local test target. Two existing gateway-retry tests
now assert the real empty-DB readback (0 persisted, 1 missing) and actual physical
costs (only the one owning interval hydrates returns/order). Retry +1 is retained.

All 393 focused regressions passed (375 existing plus 18 new); log:
`/tmp/zeler-closure-release/may14-focused-final.log`. Focused mypy, Ruff and formatting passed on the two product files and two test
files. Independent peer review passed all 18 new cases; report:
`/tmp/zeler-utc-chunk-independent-review.md`. Parent owns full repository gates
and affected runtime image verification.

## Delivery boundaries

No schema, HTTP, formula signature, UTC search inclusivity, guard, lease, writer
fencing, marker publication or Jun 23 migration contract changed. The chunked
fingerprint format changes diagnostic dry-run evidence only. Production runtime
remains unverified for this implementation until separately authorized delivery
and bounded May 14 plus original-range readback; do not infer production success
from these local results.

## Final cross-unit static review

The final UTC/readback diff retains the independently reviewed behavior with no
conflict from tag-basis or shared item-acquisition changes. Independent static
tag-basis review found no blocker: retained source basis establishes semantic
tag equality without rewriting the historical hash or observation time; unknown
tags and actual economic basis changes fail matching, and unrelated lists retain
their ordering semantics. This review ran no additional tests or database calls.

The earlier worker coverage finding is corrected in the final diff: the
rate-limit fixture permits projection and requires exactly the 15 accepted sibling
identities with fingerprints, while preserving pending/retry classification.
Parent owns execution of this late assertion change and final gate reconciliation.
