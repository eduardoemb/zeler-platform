# DEVOLUCIONES Multiperiod Coverage Specification

## Purpose

Preserve every actually acquired, independently certified DEVOLUCIONES period
when another earlier or later period is acquired. A productive result requires
current source-backed certification of its entire requested interval, not merely
stored rows, completed acquisition work, or the earliest/latest retained dates.
This is a new capability specification; no main OpenSpec baseline is assumed.

An **acquisition receipt** records immutable authority and source acquisition.
A **certificate** records separately renewable, invalidatable read readiness for
an exact seller-scoped interval. A **proof vector** identifies every certificate
and dependency revision used for one read. All intervals are half-open UTC
`[start, end)`; June and August examples stand for independently acquired ranges,
not automatic certification of complete calendar months.

## Requirements

### Requirement: Additive historical certification

The system MUST preserve unrelated valid certificates and canonical facts when
admitting, acquiring, completing, failing, or cancelling another period. It MUST
support previously certified intervals both earlier and later than the latest
acquisition, without a fixed retained-history cap that silently removes readable
coverage. A new period MUST become certified only after its own proof succeeds.

#### Scenario: August follows certified June

- GIVEN June has a valid certificate and an authorized August acquisition exists
- WHEN August successfully finalizes
- THEN both June and August MUST be independently readable
- AND June's provenance MUST remain available without another June acquisition.

#### Scenario: Earlier and later periods are added

- GIVEN June and August are independently certified
- WHEN a genuinely acquired earlier period and a later period each finalize
- THEN all four periods MUST retain their independent proof identities
- AND no period MAY be evicted merely because it is no longer the latest.

#### Scenario: A disjoint acquisition does not finish

- GIVEN a valid June certificate
- WHEN a disjoint August acquisition is admitted and then fails or is cancelled
- THEN June MUST remain usable unless an actual conflicting fact change affects it
- AND August MUST NOT gain a certificate from admission or partial progress.

### Requirement: Source-backed certificate eligibility and provenance

Every certificate MUST identify the seller, exact bounds, genuine acquisition
provenance, current certification revision and validity. Completed quota runs
MUST retain their original authorization, release/source binding and receipts;
completion alone MUST NOT establish current read readiness. Run-backed
certification MUST require all expected acquisition windows to be complete and contiguous within
the certified bounds, together with complete, consistent claims and linked-order
readback. Other supported acquisition kinds MUST prove the same exact interval
completeness through their genuine provenance, not synthetic run receipts or
stored rows alone. New coverage MUST NOT include dates not actually acquired or
yet to occur.

#### Scenario: Complete acquisition is certified

- GIVEN a correctly bound run whose completed windows cover its exact interval
- WHEN joint claims/order readback proves the required source-backed facts
- THEN certification MUST retain a verifiable link to that run and its receipts
- AND the independently renewable read validity MUST NOT alter acquisition authority.

#### Scenario: Receipt or joint readback is insufficient

- GIVEN missing windows, mismatched source binding, foreign-seller receipts, or incomplete linked orders
- WHEN certification is attempted
- THEN no productive certificate MAY be published for the affected interval
- AND existing unrelated certificates MUST remain unchanged.

#### Scenario: Future bounds have not been acquired

- GIVEN a request extends beyond the latest actually acquired instant
- WHEN the system evaluates historical coverage
- THEN it MUST NOT infer that extension from a prior certificate or a calendar boundary
- AND the unacquired portion MUST remain unavailable.

### Requirement: Exact union coverage without inferred gaps

A read MUST be productive only when a finite set of independently valid
certificates covers every instant of the requested interval. Coverage MUST use
actual interval union, not a min/max envelope. Adjacent and overlapping intervals
MAY compose without discarding their separate provenance, validity or revisions.
Malformed, reversed or empty requested intervals MUST NOT produce false coverage.

#### Scenario: Disjoint periods are queried separately

- GIVEN valid June and August certificates with no July proof
- WHEN June and August are queried separately
- THEN each covered request MUST be eligible for a productive result.

#### Scenario: A request crosses an unacquired gap

- GIVEN valid June and August certificates separated by an uncertified gap
- WHEN a request spans both certificates and the gap
- THEN the whole request MUST fail closed with the established unavailable behavior
- AND the system MUST NOT return a partial result represented as complete.

#### Scenario: Adjacent boundaries compose exactly

- GIVEN valid certificates for `[a,b)` and `[b,c)`
- WHEN `[a,c)` is requested
- THEN the union MUST cover it without inventing an overlap or a gap at `b`
- AND a row exactly at `c` MUST remain outside the requested result.

#### Scenario: One proof expires within an otherwise covering union

- GIVEN a request needs two certificates and one is expired or invalidated
- WHEN coverage is evaluated
- THEN that proof MUST NOT certify any requested instant
- AND another independently valid proof MAY substitute only for the portion it actually covers.

#### Scenario: Invalid interval bounds are rejected

- GIVEN a request has malformed dates, an empty interval, or reversed bounds
- WHEN coverage is evaluated
- THEN the system MUST reject that request without constructing a productive proof vector.

### Requirement: Duplicate-free canonical results and unchanged formula contract

The existing DEVOLUCIONES formula signature, seller authorization and result
semantics MUST remain unchanged. Reads MUST evaluate the requested canonical
claims and linked orders without counting the same canonical entity repeatedly
because several selected proofs cover it. Legitimate distinct claims sharing an
order MUST NOT be collapsed merely to deduplicate certificate overlap.

#### Scenario: Overlapping certificates cover one claim

- GIVEN two valid certificates overlap a claim's membership interval
- WHEN a request uses both certificates
- THEN that claim MUST contribute exactly once under the existing formula semantics.

#### Scenario: Distinct claims share an order

- GIVEN two legitimate claims refer to the same canonical order
- WHEN both belong to a covered request
- THEN both claims MUST retain their established contributions
- AND proof composition MUST NOT multiply the order-dependent contribution beyond existing semantics.

#### Scenario: A foreign seller has covering proofs

- GIVEN only another seller has certificates covering the requested dates
- WHEN the active seller requests DEVOLUCIONES
- THEN those proofs MUST NOT satisfy the request or expose the other seller's facts.

### Requirement: Read snapshot vector integrity

Each productive read MUST bind its fact reads to the complete selected proof
vector and the relevant claims/order dependency state. After reading facts, the
system MUST revalidate every selected proof, including its identity, revision,
validity and compatibility state. A concurrent expiry, deletion, invalidation,
renewal revision or dependency change MUST prevent publication of a mixed snapshot;
a retry MAY succeed only after obtaining and validating a fresh complete vector.

#### Scenario: Stable multiperiod read completes

- GIVEN a covering proof vector and unchanged relevant canonical facts
- WHEN all selected proofs remain valid after fact reads
- THEN the result MAY be returned as productive using that validated vector.

#### Scenario: One selected proof changes during the read

- GIVEN a read selected June and August proofs
- WHEN either proof expires, is deleted, or changes revision before final revalidation
- THEN the result from the old vector MUST NOT be returned as productive
- AND a timestamp-only comparison MUST NOT substitute for full vector revalidation.

#### Scenario: Shared order changes between claim and order reads

- GIVEN selected claims depend on an order used by more than one period
- WHEN that order changes during the read
- THEN stale dependency certification MUST be rejected before returning a productive result.

### Requirement: Atomic fenced publication

Certificate publication, applicable canonical fact publication and acquisition
completion MUST preserve the existing transactional ownership, lease and fence
requirements. An expired or replaced owner MUST NOT publish or renew readiness.
Publication failure MUST NOT leave a certificate claiming facts or completion
that were rolled back. Disjoint successful publication MUST NOT replace unrelated
proofs through a seller-wide singleton update.

#### Scenario: Successful owner publishes one interval

- GIVEN the operation still owns its current lease and fence
- WHEN all certification checks succeed
- THEN the completed acquisition and its certificate MUST become visible consistently
- AND prior unrelated certificates MUST remain intact.

#### Scenario: Ownership changes before publication

- GIVEN an acquisition or renewal prepared a certificate under an earlier owner
- WHEN its lease expires or another owner takes over before commit
- THEN the earlier owner MUST fail to publish readiness
- AND it MUST NOT revive a proof invalidated by the new owner.

#### Scenario: Publication aborts after provisional changes

- GIVEN publication has begun changing facts, completion or certificate state
- WHEN a guard or storage failure aborts the operation
- THEN no partial productive certification MAY survive the failed operation.

### Requirement: Dependency-aware invalidation across all writers

Every claims/orders writer capable of changing DEVOLUCIONES facts MUST maintain
the certificate contract before multiperiod reads are activated. A relevant
mutation MUST withdraw affected readiness consistently with the fact change.
Affected proofs MUST be determined from claim membership and shared-order
dependencies, not order dates alone. Unknown impact MUST fail closed for all
potentially affected proofs. Unrelated valid certificates MUST NOT be permanently
discarded merely because another period is acquired or invalidated.

#### Scenario: A claim moves between membership intervals

- GIVEN a claim was certified in June and a mutation places it in August
- WHEN the mutation becomes visible
- THEN both the old and new potentially affected proofs MUST be invalidated or recertified consistently
- AND neither period MAY continue using a stale membership assertion.

#### Scenario: An old order supports claims in two later periods

- GIVEN a shared order's date lies outside June and August but its claims affect both
- WHEN a relevant order field changes
- THEN both dependent proofs MUST lose stale readiness regardless of the order's date.

#### Scenario: Mutation impact cannot be determined

- GIVEN a writer cannot establish the full set of affected certificates
- WHEN it applies a potentially relevant change
- THEN every potentially affected seller proof MUST fail closed
- AND recertification MUST require current joint evidence rather than clearing an invalidation flag alone.

#### Scenario: A proven unrelated period remains valid

- GIVEN a mutation's complete dependency set excludes a certified earlier period
- WHEN the mutation invalidates its actual dependents
- THEN the unrelated certificate MUST remain available and retain its provenance.

### Requirement: Independent expiration and evidence-preserving renewal

Each certificate MUST have independent read validity, separate from immutable
acquisition expiry. Renewal MAY recertify a previously acquired exact interval
only after validating its provenance, applicable complete acquisition proof
(including completed windows for run-backed certificates) and current joint facts
under current ownership and invalidation state. Renewal MUST NOT pretend
to be a new provider scan, extend historical bounds, rewrite original source
receipts, or restore invalidated readiness without the required evidence.

#### Scenario: June renews after acquisition authority expires

- GIVEN June's acquisition authority has expired but its immutable receipts remain valid
- WHEN a legitimate renewal proves current complete facts for that exact interval
- THEN June's read validity MAY be extended without granting new acquisition authority.

#### Scenario: August expiry is independent of June

- GIVEN valid June and expired August certificates
- WHEN a June-only request is evaluated
- THEN August's expiry MUST NOT make June unavailable
- AND an August request MUST remain unavailable until August is legitimately recertified.

#### Scenario: Renewal finds a missing dependency

- GIVEN a previously certified interval now lacks required linked-order facts
- WHEN renewal evaluates its current evidence
- THEN that interval MUST NOT receive extended validity
- AND its original acquisition provenance MUST remain preserved for diagnosis and recovery.

### Requirement: Bounded fair renewal and scalable retention

Coverage lookup, invalidation and renewal MUST support growth without an
unbounded seller proof array, unrestricted collection scans, silent truncation
or implicit eviction of older certificates. Renewal MUST use finite per-cycle
work and the existing authorized resource budgets. Every eligible retained proof
MUST receive fair opportunities independent of admission age. Activation MUST
have an explicit, verifiable capacity bound relating eligible proof count,
renewal throughput and validity horizon. This MUST NOT promise unlimited
certificates can all stay fresh within 30 minutes: insufficient capacity MUST
be reported as degraded readiness and MAY cause honest expiration, not fabricated
validity or dropped history.

#### Scenario: Newer admissions do not starve June

- GIVEN more eligible certificates than fit in one renewal cycle
- WHEN repeated bounded cycles run while newer certificates are admitted
- THEN June and every other eligible retained proof MUST still be visited fairly
- AND completing one page MUST NOT reset selection to newer certificates forever.

#### Scenario: Capacity cannot sustain the validity horizon

- GIVEN measured or configured renewal capacity cannot revisit all eligible proofs before expiry
- WHEN activation or ongoing health is evaluated
- THEN the capacity shortfall MUST be reported explicitly
- AND the system MUST NOT raise quota budgets, erase older proofs or extend validity without evidence to hide it.

### Requirement: Validated idempotent legacy migration

Migration MUST preserve canonical facts, genuine runs/windows and valid legacy
coverage. A legacy run-backed proof MAY become an independent certificate only
after its seller, bounds, source/authorization bindings, complete windows and
current joint readback are validated. Repeating or resuming migration MUST NOT
create duplicate certification identities or disturb already validated unrelated
proofs. Legacy one-shot provenance MUST NOT be converted into a fabricated
completed run; its existing safe read behavior MUST remain until a supported
provenance-preserving transition is explicitly available.

#### Scenario: Valid June proof migrates twice

- GIVEN June has a valid legacy proof backed by a genuine completed run
- WHEN migration validates it and the same migration is rerun
- THEN June MUST have one effective migrated identity with unchanged source binding
- AND its facts and any independently certified August interval MUST remain intact.

#### Scenario: Legacy marker has no valid backing proof

- GIVEN a marker is orphaned, foreign, incomplete or lacks supported provenance
- WHEN migration evaluates it
- THEN migration MUST NOT manufacture a completed run or certify its interval
- AND it MUST report the unsupported or invalid case without deleting historical facts.

#### Scenario: Migration is interrupted

- GIVEN some certificates have been safely migrated and others have not
- WHEN migration resumes after interruption
- THEN it MUST preserve completed validated work and continue idempotently
- AND unmigrated intervals MUST NOT be represented as already certified.

### Requirement: Mixed-version activation and conservative compatibility

Multiperiod read activation MUST require compatible certificate-maintaining
writers, renewers and readers across every relevant path, including quota,
one-shot, bootstrap, event and recovery paths. Incompatible writers MUST be
excluded or their effects fenced by a proven compatibility mechanism before
new proofs are readable. Additive schema support alone MUST NOT imply runtime
compatibility. Any legacy singleton view MUST represent only coverage its actual
reader can safely prove, never a synthetic union spanning gaps.

#### Scenario: An incompatible writer is still active

- GIVEN an old writer can mutate relevant facts without maintaining new certificates
- WHEN multiperiod activation is requested
- THEN activation MUST fail closed unless a tested compatibility barrier prevents stale reads from its writes.

#### Scenario: Partial rollout leaves an older reader

- GIVEN some components support independent proofs but an old reader uses one legacy marker
- WHEN the compatibility view is maintained
- THEN that reader MUST receive only genuinely certified legacy-compatible coverage
- AND it MUST NOT receive the min/max envelope of disjoint periods.

#### Scenario: Compatibility changes during a read

- GIVEN a read selected proofs while multiperiod mode was active
- WHEN a rollout or rollback changes the relevant compatibility state before read completion
- THEN the old snapshot MUST fail revalidation unless the same safety conditions remain provably satisfied.

### Requirement: Non-destructive rollback

Before an incompatible writer is restored, rollback MUST withdraw new-certificate
read authority and stop incompatible certificate publication through the tested
compatibility barrier. Rollback MUST preserve canonical data, acquisition
receipts and additive certificate history. An old runtime MAY offer only its
legacy certified interval, but MUST report the resulting loss of multiperiod
availability rather than claiming transparent preservation of that capability.

#### Scenario: Rollback to singleton runtime

- GIVEN June and August are certified in multiperiod mode
- WHEN rollback restores legacy-only code
- THEN new-proof reads MUST be disabled before incompatible writes are possible
- AND both periods' facts and receipts MUST remain stored even if only one is readable in legacy mode.

#### Scenario: Multiperiod mode resumes after legacy writes

- GIVEN rollback permitted legacy fact mutations while new proofs were unreadable
- WHEN multiperiod activation is attempted again
- THEN affected certificates MUST be revalidated under the current compatibility state
- AND retained historical certificate documents alone MUST NOT restore read authority.

### Requirement: Strict persistence and truthful operational status

Persistence contracts MUST reject malformed or inconsistent certificate state,
foreign provenance and unsupported certification fields. Necessary schema/index
changes MUST be additive and separately rolled out before dependent writes.
Operational status MUST distinguish actually certified intervals, gaps, expired
or invalidated proofs, renewal backlog/capacity and unsupported migration cases.
A healthy process or completed acquisition MUST NOT be reported as proof of
all-period readiness. Diagnostics MUST NOT expose secrets, raw provider payloads
or customer personal information.

#### Scenario: Invalid certificate data is submitted

- GIVEN invalid interval bounds, inconsistent provenance or unsupported certificate fields
- WHEN a writer attempts persistence
- THEN the contract MUST reject the invalid certificate rather than make it readable.

#### Scenario: Status reports disjoint coverage and backlog

- GIVEN valid June, expired August, an unacquired gap and pending renewal work
- WHEN an operator reads readiness status
- THEN it MUST distinguish each of those conditions
- AND it MUST NOT summarize them as a single healthy June-through-August interval.

### Requirement: Evidence-separated acceptance and authorization

Implementation acceptance MUST include failing regression evidence before the
behavioral change, focused tests, isolated Mongo transaction/race tests, required
root quality gates, schema export and applicable direct-Meli checks. Local checks
MUST NOT be described as production migration, deployment or native Sheet proof.
Live acceptance MUST remain separately authorized and show preserved June,
newly certified August, rejection of their unacquired gap and renewal beyond the
original 30-minute validity horizon with dependency readiness. This capability
MUST NOT silently authorize additional acquisitions, quota increases, validator
application, builds or deployments.

#### Scenario: Local tests pass before production authorization

- GIVEN implementation and isolated validation have succeeded
- WHEN results are reported before separate runtime authorization
- THEN the report MUST identify production migration and native acceptance as unperformed
- AND no source acquisition or deployment MAY be inferred from local success.

#### Scenario: Authorized live acceptance preserves independent periods

- GIVEN a separately approved migration/acquisition/rollout scope
- WHEN acceptance reads both certified periods, tests their gap, and observes renewal beyond 30 minutes
- THEN each claimed result MUST be backed by its actual runtime or native evidence
- AND unavailable or unperformed checks MUST remain explicit rather than being marked complete.
