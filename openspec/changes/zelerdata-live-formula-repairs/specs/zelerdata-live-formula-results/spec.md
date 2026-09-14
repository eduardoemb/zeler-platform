# ZelerData Live Formula Results Specification

## Purpose

Define reliable results and recovery for the 15 formulas identified in the live audit, preserving public signatures, header options, matrix widths, and vector cardinality.

## Requirements

### Requirement: Explicit missing values

PREGUNTAS and DIASDESDEULTIMAVENTA MUST return literal `NA` for absent values and preserve valid zeroes and existing values.

#### Scenario: Unanswered question
- GIVEN a question without answer text or answer date
- WHEN PREGUNTAS returns its row
- THEN both absent fields are `NA`, with other fields unchanged.

#### Scenario: Sale lookup outcomes
- GIVEN pairs with no sales and with a sale today
- WHEN DIASDESDEULTIMAVENTA evaluates the vector
- THEN results are `NA` and numeric zero respectively, preserving order and repetition.

### Requirement: Honest product change dates

PRODUCTOSINVENTA MUST render valid `last_status_change_at` with `change_date_basis=observed_status_change` metadata. This evidence includes first paused observations and MUST NOT imply a reconstructed historical transition. Missing or invalid dates MUST yield `NA`; `status_started_at` and `first_observed_at` MUST NOT substitute for this field.

#### Scenario: Supported and missing timestamps
- GIVEN rows with proven transitions, observed baselines, and neither
- WHEN PRODUCTOSINVENTA returns dates
- THEN valid observed-change dates carry their observed basis, missing dates are `NA`, and baselines are not claimed as proven transitions.

### Requirement: Products without SKU

PRODUCTOSINVENTA MUST retain otherwise eligible publications lacking SKU, display `NA`, and use item-level sales exclusion for those publications. It MUST NOT manufacture `NONE` from missing values.

#### Scenario: Missing SKU sales filtering
- GIVEN two SKU-less publications, one sold within the requested period
- WHEN PRODUCTOSINVENTA evaluates that period
- THEN only the unsold publication appears, with SKU `NA`.

### Requirement: Explicit inventory-code ambiguity

CODIGOML MUST emit an `AMBIGUOUS_VARIATION` message in the affected output cell when a SKU/publication pair has conflicting inventory codes. Other vector cells MUST remain independently evaluable.

#### Scenario: Mixed vector
- GIVEN repeated ambiguous pairs and a uniquely resolved pair
- WHEN CODIGOML evaluates them
- THEN ambiguous cells report `AMBIGUOUS_VARIATION`, the unique cell returns its code, and order and repetitions remain unchanged.

#### Scenario: Duplicate equivalent codes
- GIVEN multiple matching variations sharing one inventory code
- WHEN CODIGOML evaluates their pair
- THEN it returns that unique code without ambiguity.

### Requirement: Coverage-aware recovery

ENVIOSMERCADOENVIOS, TIEMPOSINSTOCK, TIEMPOACTIVA, PRECIOHISTORICO, and DEVOLUCIONES MUST recover legitimately obtainable requested data. Freshness MUST represent successfully observed scope, never merely a completed job.

#### Scenario: Successful recovery
- GIVEN expired data and an available authoritative source
- WHEN recovery succeeds and the formula is recalculated
- THEN supported results replace temporary unavailability for the recovered scope.

#### Scenario: Incomplete recovery
- GIVEN unavailable source data or partially recovered coverage
- WHEN recovery finishes or retries
- THEN uncovered scope remains explicitly unavailable, retries stay bounded, and no historical interval is fabricated.

### Requirement: Independent partial coverage

CALIDAD, CATALOGO, CATALOGOBUYBOX, CATALOGO_COMPLETO, OBTENER_CATALOGO, and PUBLICACIONESDESCUIDADAS MUST expose supported fresh results without requiring unrelated records to succeed. Missing reasons or withdrawal quantities MUST NOT be invented.

#### Scenario: Mixed source availability
- GIVEN one recoverable record and another unavailable record
- WHEN recovery and recalculation complete
- THEN supported fields appear with their existing matrix contract, while unresolved cells or coverage remain explicit.

### Requirement: Repair evidence

Each reproduced defect MUST have regression evidence and a post-repair spreadsheet diagnosis. Live certification MUST distinguish absent positive fixtures from passing positive cases.

#### Scenario: Verification report
- GIVEN implemented repairs
- WHEN verification concludes
- THEN all 15 formulas have expected/actual evidence, deployed-version identification where applicable, and unresolved limitations; CALCULADORA remains a regression control.


## Added requirement: layered recovery

Original recovery-first scope (expanded by the closure requirements below). Basic inventory
acquisition fetches owned item batches of 20 plus necessary variation identities,
then existing histories/projections. Full enrichment remains the default for
explicit IDs. Preserve enrichment timestamps, invalidate changed bases using
existing states, retain CAS, and scope projection identity/status reads to IDs.

Three disjoint claim lanes use existing fields: inventory, explicit IDs, ranges.
Run one job per lane, including matching expired-lease cleanup. Share 180 requests
per minute with work-conserving 1:2:1 weights. HTTP deadlines start after quota
admission. Local quota exhaustion defers work without source-attempt consumption.

Reuse validated active admissions; reserve one of 20 slots for inventory. Use a
shared three-second admission deadline inside the existing 25-second formula
budget. Drain old occupancy naturally. Quality/calculator request missing base
and enrichment independently. No new public signatures, queue fields, migration,
or TTL expansion. Retain seller isolation and distinct discovery/detail clients.

Process integration requires lane lifecycle cancellation/failure tests; shell,
VCS and routing threat cases are N/A. Acceptance includes an accelerated 1900-item
mixed workload (including necessary variation calls and projection time), all
four quality gates with isolated Mongo, independent SDD verification, two live
base inventory cycles inside 15-minute freshness, and the 35-case Sheet retest.
Deploy worker then API only with exact-main provenance, capacity and compatible
rollback under applicable authorization. Quality/catalog failures remain explicit.

## Closure requirements approved September 14

### Requirement: Bounded broker connection ownership

Gateway readiness MUST use the installed aio_pika connection interface, reuse
its connected owned connection, and never accumulate connections from probes.
Concurrent probes MUST serialize creation; reconnecting robust connections MUST
not be replaced by probe-created connections. Failed/cancelled attempts and
shutdown MUST release owned resources. A failed initial broker connection MUST
allow later readiness recovery without a process restart. Responses remain
sanitized and keep existing HTTP/schema/deadline contracts.

#### Scenario: Repeated and concurrent readiness
- GIVEN the real connection interface has is_closed and connected but no is_open
- WHEN repeated or concurrent readiness probes run
- THEN connected probes create no new connections and a missing connection has
  at most one active creation attempt, with no leaked superseded resources.

#### Scenario: Disconnect, cancellation and recovery
- GIVEN a disconnect, initial failure, timeout or cancelled probe
- WHEN the broker becomes reachable or the process shuts down
- THEN readiness recovers through bounded owned work or remains truthfully 503,
  and shutdown/cancellation leaves no orphan connection attempts.

### Requirement: Thirty-five-case closure under whole-sheet load

All 35 original cases MUST be certified against complete output matrices and
source evidence, including returns and historical metrics. Recoverable gaps MUST
not be certified as legitimate absence. Controlled positives with verified live
absence/coverage MUST be distinguished from real positive production evidence.

#### Scenario: Inventory stays scheduled between Sheet rounds
- GIVEN the existing refresh supervisor is enabled for an allowed seller
- WHEN an inventory sweep completes and no Sheet request arrives
- THEN its existing inventory key is admitted again on a 30-second inventory-only
  cadence, active work coalesces, and broad six-model planning retains its
  900-second cadence. Admission failures remain isolated and shutdown drains
  owned work without a second scheduler or source acquisition in the planner.

#### Scenario: Ninety-minute certification
- GIVEN dependencies and initial source recovery are ready on exact deployed images
- WHEN all 35 formulas recalculate together at minutes 0, 30 and 60 of a 90-minute window
- THEN each round converges within three minutes with at most two additional
  recalculations 60 seconds apart, without persistent PROCESSING/service errors;
  API calls preserve their 25-second budget; dependencies/consumers stay ready;
  base sweeps finish within 15 minutes and minute samples show no expired base
  sources or projection discrepancies surviving the next sample; connections
  do not grow because of probes, and no unexpected restart/OOM or sustained
  queue growth occurs. A failure requires correction and a new complete window.

#### Scenario: Historical positive fixture absent
- GIVEN no authoritative positive event or full historical interval exists in production
- WHEN the formula is verified
- THEN controlled tests prove the positive behavior and production proves the
  absence/uncovered interval explicitly, without fabricating events or coverage.

### Requirement: Canonical UTC membership of return candidates

Focused return reconciliation MUST retain the complete authoritative two-pass
search inventory and determine requested membership from the hydrated claim's
aware canonical `date_created` in the existing half-open UTC interval. It MAY
classify an outside candidate only after same-claim identity, seller respondent
and inventory/detail creation-time agreement are proven. Outside candidates MUST
remain in inventory/exclusion fingerprints and a bounded exclusion counter;
they MUST NOT enter in-range expected IDs or writes. Source coverage, inclusive
search, budgets, final source revalidation and historical guards remain intact.

#### Scenario: Search includes a claim before the requested start
- GIVEN four productive source candidates and three persisted in-range claims,
  with the fourth already persisted and both source timestamps before UTC start
- WHEN focused reconciliation classifies the complete acquired inventory
- THEN all four inventory identities remain evidenced, three in-range identities
  form the exact read-model proof, and one outside-window exclusion is reported.

#### Scenario: Exact UTC interval boundaries
- GIVEN aware source timestamps at the start and at the exclusive end, including
  equivalent non-UTC offset representations
- WHEN membership is evaluated
- THEN the start claim is included and the end claim is explicitly excluded.

#### Scenario: Missing or contradictory outside-membership evidence
- GIVEN a missing, invalid, naive or changed hydrated timestamp, a contradictory
  inventory timestamp, or wrong claim/seller identity
- WHEN an outside-window classification would otherwise occur
- THEN reconciliation fails closed without excluding that unproven candidate or
  publishing a marker.

#### Scenario: Membership proof changes during final revalidation
- GIVEN a previously acquired outside candidate remains in full fingerprints
- WHEN its identity/date changes or it enters the requested window on revalidation
- THEN source/exclusion/counter drift prevents marker publication; no timestamp,
  count or membership is rewritten merely to make the proof pass.

### Requirement: Owned sharing of identical reads in flight

Concurrent formula requests MAY share identical item acquisition and fingerprint
work only while it remains in flight within the same application/database owner,
seller and exact identity set. Completed or failed work MUST NOT be cached.
Each request MUST independently enforce existing freshness, ownership and full
source-receipt checks, and MUST receive independently mutable returned documents.

#### Scenario: Concurrent full inventory reads
- GIVEN seven concurrent reads of the same realistic 1900-item source set
- WHEN acquisition overlaps
- THEN only one source acquisition/fingerprint pass occurs, each request gets
  its own rows, and different request times may produce different availability.

#### Scenario: Cancellation and isolation
- GIVEN shared work with multiple waiters
- WHEN one waiter cancels, the final waiter cancels, or the application shuts down
- THEN one cancellation preserves other waiters, while the final cancellation
  and shutdown drain owned work without orphan tasks or cached failures.
- AND different database owners, sellers and identity sets remain isolated, and
  the first request after completion reads the source again.

### Requirement: Truthful multi-window return evidence

Chunked read-only reconciliation MUST report measured local readback counts,
not substitute expected source cardinality for persisted/complete counts.
Unknown or failed local queries MUST remain uncertified. Expected identities
MUST not overlap disjoint canonical UTC slices; such overlap invalidates source
certification. Physical snapshot counters MUST represent each snapshot's own
charged attempts and sum to the run total.

#### Scenario: Available source with missing persisted claims
- GIVEN four source claims and only three complete local claims across a large
  requested range
- WHEN chunked dry-run evidence is emitted
- THEN it reports expected4/persisted3/complete3/missing1, preserving source
  availability without claiming completed persistence.

#### Scenario: Unknown readback or overlapping expected identities
- GIVEN a failed slice query or the same expected claim in disjoint UTC slices
- WHEN evidence is aggregated
- THEN missing knowledge is not replaced with zero or matching source counts,
  and inconsistent source membership is explicitly uncertified.


#### Scenario: Independent scoped fingerprints
- GIVEN unchanged source proofs and a changed read-model proof, or the converse
- WHEN multi-window evidence is aggregated
- THEN only the matching aggregate proof changes; both proofs remain bound to
  the seller and ordered UTC window identities, so a changed scope changes them.
