# zelerdata-pilot-reliable-sync Specification

## Purpose

Guarantee a trustworthy ZelerData pilot across the complete 52-formula catalog,
continuous source updates, recoverable 12-month history, and visible Sheets
refresh.

## Requirements

### Requirement: Complete Formula Acceptance

The system SHALL preserve all 52 public formula names, signatures, aliases, and
result shapes. Acceptance SHALL compare each formula against a maintained matrix
and reject self-caused defects, empty outputs presented as success, and indefinite
`PROCESSING`.

#### Scenario: Catalog is executed

- GIVEN representative pilot inputs for every formula
- WHEN the full catalog runs
- THEN each formula records expected result, observed result, freshness, and evidence
- AND formulas with legitimate API limits are explicitly distinguished from defects.

### Requirement: Immediate Event Flow

The system SHALL process received notifications without waiting for a five- or
fifteen-minute interval, then fetch, persist, project, and make data visible.

#### Scenario: Duplicate and late events converge

- GIVEN repeated, reordered, or transiently failed notifications
- WHEN events are consumed
- THEN results are idempotent, newer observations win, and unfinished persisted
  events recover without loss.

### Requirement: Reconcile Changes to Old Operations

The system SHALL periodically reconcile recent changes to old operations where
the resource supports modification searches, using bounded overlap and
deduplication.

#### Scenario: Old order is modified

- GIVEN an order created before the current fast window
- WHEN its status or shipment changes
- THEN local projections and visible formula data reflect the modification.

### Requirement: Recoverable 12-Month History

The system SHALL calculate a fixed 12-month calendar window and load recoverable
history in resumable, bounded intervals. Progress SHALL be durable and SHALL not
restart completed work.

#### Scenario: Backfill resumes

- GIVEN an interrupted monthly history job
- WHEN the worker restarts
- THEN it resumes safely, preserves acquired data, and records real coverage.

### Requirement: Honest Freshness and Partial Data

The system SHALL retain per-field/source freshness. It SHALL NOT renew an
unconsulted source, synthesize missing data, convert unknown values to zero, or
present incomplete economic totals as definitive.

#### Scenario: Secondary source fails

- GIVEN a primary value is valid and a secondary source fails
- WHEN the formula runs
- THEN independent valid fields remain usable with an explicit limitation.

### Requirement: Durable Recovery and No Starvation

The system SHALL preserve existing guarded recovery, retries, leases, quotas,
deduplication, and seller isolation. Heavy inventory work SHALL NOT permanently
starve events, active queries, or history.

#### Scenario: Large inventory is running

- GIVEN historical and inventory workloads are active
- WHEN a fresh notification or formula recovery arrives
- THEN admitted work progresses within its configured lane and capacity.

### Requirement: Visible Sheets Synchronization

The system SHALL provide a compatible Apps Script refresh mechanism and
`/sheets/config` visibility for last successful sync, coverage, progress, errors,
and non-duplicative retry. Formula cells SHALL update without manual editing.

#### Scenario: Spreadsheet reopens

- GIVEN data changed while the spreadsheet was closed
- WHEN the user reopens it
- THEN existing ZelerData cells refresh through the tested mechanism.

### Requirement: Finite Acceptance

Delivery SHALL require all 52 formulas, prior regressions, controlled recovery
tests, completed reconciled history, and a 90-minute observation with rounds at
zero, 30, and 60 minutes. Small event samples SHALL be reported as sample/max,
not representative percentiles.

#### Scenario: A fix invalidates evidence

- GIVEN a behavior affecting measured stability changes
- WHEN verification reruns
- THEN affected controls rerun and the 90-minute window restarts when applicable.
