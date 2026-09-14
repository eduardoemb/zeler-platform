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

User-approved scope: recovery first; returns remains separate. Basic inventory
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
