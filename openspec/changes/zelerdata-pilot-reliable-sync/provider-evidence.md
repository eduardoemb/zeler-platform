# Provider Evidence: Historical Recovery

Research date: 2026-09-15. This is documentation evidence, not a live API probe
or production coverage claim. Direct page opens returned 403/503; the search
tool returned indexed text from the official developer pages. These sources
establish documented semantics only, not live pilot behavior; reverify ambiguous
adapter semantics before activation.

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

## Questions

The official scan guide explicitly includes `/questions/search`, requires scan
instead of offset for more than 1,000 results, and describes a five-minute
`scroll_id` lifetime. It describes terminal `null`, a default page size of 50,
and a maximum limit of 100. Its instruction to update the parameter while using
the same scroll ID is ambiguous; confirm the response/token contract before
coding cursor replacement rules.
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

## Required Adapter Evidence

- Exact orders boundary inclusivity, hourly subdivision and saturated-hour handling.
- Question continuation parameters, terminal response and expiry/restart behavior.
- Retention and visibility exclusions per resource for this pilot's authority.
- Shifted pages, equal-count membership changes, duplicate IDs and late mutations.
- Sanitize evidence: no authorization values, cursor contents or raw buyer payloads.

No API call, token access, scope change, quota increase or deployment was performed.

## Research disposition

Task 3.2g is complete as a documentation lane: the cited pages are primary
Mercado Libre developer documentation and claims are bounded to what they
document. Live cursor expiry, exact continuation-token behavior, per-resource
retention, and saturated-hour behavior remain runtime evidence for later adapter
tasks; these unknowns are not promoted to guarantees.
