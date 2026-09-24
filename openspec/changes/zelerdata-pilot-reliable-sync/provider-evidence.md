# Provider Evidence: Historical Recovery

Source research date: 2026-09-15. The cited developer pages establish documented
semantics only; the separate bounded pilot probe below establishes only its
observed runtime behavior, not production coverage. The initial direct page
opens returned 403/503 and the search tool supplied indexed official text.

## Orders

The official orders page, updated 2026-06-24, documents a twelve-month creation
retention window, seller-search exclusion of cancelled orders, separate
`order.date_last_updated.from/to` filters, and date filtering at hour precision
rather than minutes/seconds/milliseconds. It shows offset/limit pagination.
[Source: orders](https://developers.mercadolibre.com.mx/gestiona-ventas).

The English page says seller ordering uses closing date, while buyer ordering
uses creation date. Do not assume seller `date_asc` means creation order or that
an unchanged total establishes a stable snapshot.
[Source: sales](https://developers.mercadolibre.com.mx/en_us/order-management).

Implementation implications, not additional provider guarantees:
- Query an hour-aligned superset and apply exact half-open chunk bounds locally;
  legitimate boundary-hour rows must not automatically become scope failures.
- Preserve the fixed calendar cutoff, including its minutes, rather than silently
  narrowing the requested history to match source filter precision.
- Revalidate known cancelled identities by detail, and record discovery exclusions.
  Local absence cannot establish that no cancelled history ever existed.
- Subdivide over-budget intervals only with coverage-preserving boundaries.
  The existing 10,000-result cap is local; no universal provider cap was verified.
- A saturated single hour needs an explicitly supported enumeration strategy,
  not infinitely repeated sub-hour filters which the provider ignores.

### Bounded pilot modification-filter observation (2026-09-24)

The approved Sheets worker used the bootstrap gateway identity for read-only
seller-scoped `/orders/search` requests with
`order.date_last_updated.from/to`, hour-aligned bounds, `offset=0` and
`limit=50`. A two-hour window returned zero rows; a separate 26-hour window
returned 11 rows and `paging.total=11`. All 11 had parseable aware modification
times inside the queried hour superset. The response reported the requested
offset and limit. No IDs, buyer fields, raw payloads, credentials or tokens
were printed. This confirms the filter and first-page shape for this pilot,
not shifted-page stability, old-order modification coverage, or a completed
traversal.

## Questions

The official scan guide explicitly includes `/questions/search`, requires scan
instead of offset for more than 1,000 results, and describes a five-minute
`scroll_id` lifetime. It describes terminal `null`, a default page size of 50,
and a maximum limit of 100. Its cursor wording is ambiguous; the bounded live
probe below resolves replacement and stopping behavior for this pilot traversal.
[Source: scan guide](https://developers.mercadolibre.com.mx/es_ar/como-empezar/items-y-busquedas).

The newer rate-limit FAQ warns against mixing pagination mechanisms and says
scroll consumption must fit its validity window. It also warns against combining
scroll IDs with offset/limit. That conflicts with interpreting the scan guide's
limit note as universally applicable to continuation requests; endpoint-specific
verification is still required.
[Source: rate-limit FAQ](https://developers.mercadolibre.com.mx/en_us/tools/rate-limit-429-error).

The questions guide documents seller search with `api_version=4`; banned
questions/answers have empty text. Empty text alone is therefore not an
acquisition failure.
[Source: questions](https://developers.mercadolibre.com.mx/en_us/tools/manage-questions-and-answers).

Design implication: enumerate and persist bounded search pages before slow detail
hydration, so detail calls do not consume the entire scroll lifetime. Resume
hydration from durable identities after expiry; a fresh verification scan still
needs its own valid cursor and membership evidence. Do not manufacture monthly
server-side filters, question retention guarantees, or snapshot consistency.

### Bounded pilot cursor observation (2026-09-24)

Inside the approved Sheets worker, the normal bootstrap gateway identity made
read-only seller-scoped `/questions/search` requests with `api_version=4` and
`search_type=scan`. One two-page probe used an initial limit of 1; the second
request omitted `limit`, supplied the returned `scroll_id`, and received one
different question with a different cursor. A fresh bounded pass used an
initial limit of 100 and then passed each returned cursor without `limit`:
pages contained 100, 100 and 31 unique IDs, matching the unchanged reported
total of 231. The cursor changed on both continuations and remained present
on the final page even after all 231 IDs had been seen. Therefore this observed
seller scan must stop at verified membership count, not wait for a null cursor.
The implemented adapter's exact initial limit of 50 was also probed: its first
two pages each contained 50 disjoint IDs, the reported total stayed 231, and
the cursor rotated when continuation omitted `limit`.
A second complete three-page scan found 231 unique IDs with valid UTC creation
dates: one in October 2025, 13 in February 2026, 74 in March, 54 in April,
35 in May, 27 in June, 15 in July, seven in August and five in September.
This describes the visible pilot sample only; months with zero results and
provider retention outside this sample are not independently certified.
A separate overrun eventually received HTTP 404; its precise terminal sequence
and cursor-expiry/restart behavior remain unproved. No cursor value, question
text, buyer data or token was printed, and no collection or runtime setting was
mutated. This is discovery evidence only: it does not prove twelve-month
retention, detail completeness or a reconciled questions interval.

Three further bounded read-only samples fetched a search row with the bootstrap
identity and its v4 detail with the Sheets identity. ID, seller, item and status
matched in all three. The detail `date_created` was 0.038, 0.624 and 0.055 ms
earlier than the search value after UTC normalization: the detail kept
millisecond precision while search kept finer fractions. Raw timestamp strings
also differed. The detail staging comparison now uses the common millisecond
instant while still rejecting a different millisecond; the original search
payload/hash and actual detail payload/hash remain separate receipts. This
sample does not prove every question detail or answer is available.

## Required Adapter Evidence

- Exact orders boundary inclusivity, hourly subdivision and saturated-hour handling.
- Question cursor expiry/restart behavior and terminal response beyond the
  verified total; continuation and count-stopping behavior were observed above.
- Retention and visibility exclusions per resource for this pilot's authority.
- Shifted pages, equal-count membership changes, duplicate IDs and late mutations.
- Sanitize evidence: no authorization values, cursor contents or raw buyer payloads.

The 2026-09-15 source research made no API call. The bounded pilot probe above
used the worker's configured gateway identity for read-only requests; it made
no scope change, quota increase, deployment or data write.

## Research disposition

Task 3.2g is complete as a documentation lane: the cited pages are primary
Mercado Libre developer documentation and claims are bounded to what they
document. The pilot probe resolves only observed question cursor replacement
and count-stopping behavior. Cursor expiry, per-resource retention and
saturated-hour behavior remain evidence for later adapter tasks; these unknowns
are not promoted to guarantees.
