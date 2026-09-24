# Decision proposal: freshness scope and measured acquisition capacity

The read-only Mongo snapshot at2026-09-14 21:42:15 UTC shows that the full35-case
freshness obligation exceeds the selected180 physical requests/minute budget,
even after optimistic resource sharing. This is a resource-demand calculation,
not a benchmark or evidence that raising the rate would be safe.

## Conservative calculation

| Resource acquired once per15-minute cut | Calls |
|---|---:|
| Base detail for1900 publications, batches20 |95|
| Enumeration, optimistic full pages100 |19|
| Eligible item-specific price-to-win |936|
| Distinct catalog product definitions |881|
| Distinct product offers, optimistically shared |735|
| Distinct quality resources with all possible USER_PRODUCT sharing |1567|
| **Total before calculator costs, history, retries and extra calls** |**4233**|

The census counted938 catalog-true publications, but2 have no valid product
association. This proposal excludes those2 unresolved cases, using936 and4233
rather than the script's4235. Their exclusion from the lower bound does not declare
them complete or remove them from the product obligation.

At180/min,4233 calls require at least23.52 minutes, versus2700 calls available in
15 minutes. Maintaining this optimistic workload within15 minutes would require
at least282.2 calls/min before calculator acquisition, history, retries, variation
SKU calls, pagination shortfalls, latency, CPU and projection overhead.282.2 is a
necessary arithmetic floor, not a recommended safe configured rate. The current
learned quality routing yields1672 distinct resources; even with offer sharing,
that alternative floor is4338 calls,24.1 minutes at180/min.

The1567 quality figure is deliberately optimistic. It assumes all canonical
USER_PRODUCT relationships can acquire and share a correctly bound performance
response. That is not verified upstream. Likewise offers are deduplicated by
product for this calculation although current recovery fetches them per item.
The proposal gives both optimizations credit before concluding that neither
purpose-specific acquisition nor deduplication alone can satisfy this workload.

## Missing quality is not proven absence

Of1900 canonical sources,441 contain identity-matching quality projections
(46 ITEM,395 USER_PRODUCT);1459 have no recognized/matching quality projection
and no observed_at. Independently,1869 quality states are basis_mismatch. These
categories overlap; the census did not output their intersection. Only11 quality
observations are younger than15 minutes;430 are expired. A matching identity or
fresh timestamp alone does not establish usable quality when basis_mismatch is
present.

Neither1459 missing projections nor1869 basis mismatches proves a404 or legitimate
source absence. The census made no MercadoLibre calls and collected no per-item
fresh source-disposition evidence. It cannot distinguish never acquired, failed,
invalidated, malformed, or not-yet-generated results. Earlier five transient
performance_not_generated observations apply only to that earlier sampled batch.
No zero, authoritative absence or complete current quality claim is justified.

All1900 source documents exist, but420 base observations are expired; the three
calculator items each have expired basis-mismatch shipping/fee/fixed-fee states.
This census uses a consistent projected-field Mongo snapshot, not full source
fingerprint/row receipt validation or proof of current positive upstream data.

## Next action and decision boundary

Continue the already-authorized read-only capacity investigation: distinguish the
selected operator budget from upstream/gateway limits, inspect actual resource
sharing and existing sanitized timing/call metrics, and prepare a concrete
capacity proposal. This investigation does not require another permission request
and does not authorize a rate change or new recovery protocol.

Preserve all 35 original cases and their current freshness requirements while
preparing that proposal. Any necessary increase in the selected acquisition
budget, change to per-layer freshness, smaller current cohort, or new recovery
protocol must be specified and explicitly authorized before implementation.
The arithmetic floor does not justify declaring any particular higher rate safe.

If the selected 180/minute budget must remain fixed, the currently verified
individual-resource routes and full freshness workload are incompatible even
with the optimistic sharing counted above. Do not drop cases, renew timestamps
without acquisition, weaken source receipts, or relabel unavailable quality as
complete. A longer interval is not guaranteed sufficient by the 23.52-minute
floor; actual overhead and upstream availability remain unresolved.

Evidence is retained in `/tmp/zeler-closure-release/second-field-census.jsonl`,
`census-field-demand.py` and `full35-minimum-demand.md`. This document records
read-only evidence and a decision boundary, not runtime acceptance or permission
to change capacity.

## Pilot catalog freshness readback, 2026-09-24

A fresh, read-only count inside the approved Sheets-worker container found 879
distinct catalog products required by the pilot's current items and variations.
Of these, 877 had a structurally valid stored snapshot; 33 were observed within
15 minutes, 876 within four hours, one was older than four hours and two had no
valid stored snapshot. The count did not renew a timestamp or query MercadoLibre.

This strengthens the proposed decision boundary: under the existing 15-minute
rule, most product rows must remain unavailable even though recently acquired
source payloads are stored. A four-hour cache rule would make up to 876 rows
eligible at this instant, with the other three requiring refresh or a separate
source-disposition check. It would not establish current upstream completeness
or fix a missing source.
Any such cache policy must preserve acquisition times and visible cached-state
metadata. The change still needs explicit product-policy authorization and
runtime formula acceptance before it can be called complete.

Decision on 2026-09-24: the user explicitly authorized the proposed four-hour
catalog-product cache boundary. The local reader now accepts verified product
snapshots younger than four hours and exposes cached acquisition timestamps in
formula response metadata. It retains the 15-minute source-404 disposition
check, requests recovery at the four-hour boundary, and does not treat cached
rows as current completeness. This decision affects product snapshots used by
`ZELERDATA_OBTENER_CATALOGO` and `ZELERDATA_CATALOGO_COMPLETO`; it does not
relax item inventory, buybox, quality or order freshness. Deployment and live
formula acceptance remain separate evidence.
