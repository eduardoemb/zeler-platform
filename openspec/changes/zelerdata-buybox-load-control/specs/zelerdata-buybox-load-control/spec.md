# ZelerData Buybox Load Control Specification

## Requirements

### Requirement: Optional catalog offers absence

The worker MUST retain a verified buybox observation when the catalog offers listing returns 404, MUST leave unverified competition fields unavailable, and MUST complete the chunk when no other required acquisition fails.

#### Scenario: Offers listing not found

- GIVEN a seller-owned catalog publication and a valid price-to-win response
- WHEN the catalog offers listing returns 404
- THEN the buybox snapshot retains the verified price and status
- AND unknown competitor count and sole-competitor state render as `DATA_UNAVAILABLE`
- AND the chunk does not fail solely because of that 404

#### Scenario: Required or transient source failure

- GIVEN the same publication
- WHEN price-to-win fails, the offers listing returns a server error, or a source identity is inconsistent
- THEN existing retry or failure behavior remains in force

### Requirement: Unique active buybox coverage

The queue MUST admit only buybox publication IDs not already present in active jobs for the same seller and read model, including concurrent catalog and small requests.

#### Scenario: Overlapping catalog requests

- GIVEN an active buybox job covering a set of publication IDs
- WHEN a new catalog request overlaps that set
- THEN the queue persists only the uncovered IDs
- AND a request from another seller remains independent

#### Scenario: Concurrent requests

- GIVEN concurrent overlapping buybox requests
- WHEN admission completes
- THEN each publication ID appears in at most one active job for that seller and read model

### Requirement: Guarded legacy reconciliation

The operator MUST preview old active buybox jobs and execute only against the exact preview fingerprint after active leases drain. The operation MUST preserve successful chunks and old job evidence.

#### Scenario: Matching drained snapshot

- GIVEN multiple overlapping active buybox jobs with valid checkpoints and no active lease
- WHEN the operator executes using the preview fingerprint
- THEN old jobs are marked superseded without deletion
- AND one replacement contains each unfinished ID at most once, excluding IDs completed successfully elsewhere

#### Scenario: Changed or leased snapshot

- GIVEN a changed fingerprint, invalid checkpoint, or active lease
- WHEN reconciliation is requested
- THEN it refuses mutation
