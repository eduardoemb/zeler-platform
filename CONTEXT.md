# Zeler Platform

This glossary defines the shared language for the Zeler product system and its
active operational boundaries.

## Language

**ZelerData**:
The active Zeler product that makes seller information available in Google
Sheets through formulas backed by trusted platform data.
_Avoid_: SheetsellerApp, Sheets module when referring to the product

**Mercado Libre Source Data**:
Seller information returned by the official Mercado Libre APIs under their
current semantics. It is authoritative when a local ZelerData projection
disagrees with it.
_Avoid_: Legacy result, local value when referring to authoritative seller data

**ZelerData Read Model**:
A seller-scoped local projection of Mercado Libre source data used to answer
ZelerData formulas. It is usable only while its completeness and freshness are
demonstrated.
_Avoid_: Source of truth, cache without freshness evidence

**Recoverable Data**:
Mercado Libre source data absent from a ZelerData read model but still available
through a supported official API and eligible for durable local storage.
_Avoid_: Guessed data, reconstructed data without an authoritative source

**Purpose-Complete Data**:
All source fields required by an approved ZelerData formula or existing product
surface, including sensitive fields when that purpose requires them. It excludes
unneeded raw responses and data collected only for possible future use.
_Avoid_: Complete API payload, collect-everything data

**Authorized Data Lifecycle**:
The period in which purpose-complete data remains available to its linked seller
for an approved product purpose and any justified retention that follows. It ends
when deletion is required or the purpose no longer exists.
_Avoid_: Permanent retention, availability without authorization

**ZelerData Recovery**:
The controlled transfer of recoverable data from Mercado Libre into MongoDB so
the repaired ZelerData read model can serve future formula queries.
_Avoid_: Formula-time lookup, temporary fallback

**Complete Formula Result**:
A ZelerData result whose required source data covers the requested scope and is
demonstrably current. Missing optional fields may be represented as `NA` without
making the result incomplete.
_Avoid_: Partial result presented as complete, silently stale result

**Zeler Application**:
The unified product experienced by a user across the active visual interface and
the platform capabilities behind it. It is validated as one system.
_Avoid_: Frontend, backend, or platform when referring to the whole product

**Verified Consumer**:
A current Zeler product or external integration whose dependency on a contract
is demonstrated by repository or runtime evidence. Historical or hypothetical
dependents are not verified consumers.
_Avoid_: Potential consumer, assumed consumer

**ZelerData Refresh**:
The recurring, seller-scoped process that renews ZelerData read models so they stay productive without waiting for a formula query.
_Avoid_: Cache warmup, formula-time fetch

**Precalculated Formula Result**:
A ZelerData result computed during refresh and served from the read model instead of being produced during a Sheets call.
_Avoid_: Cached cell, stale copy

**Freshness Marker**:
The per-seller record that states which read-model interval is reconciled and how long that claim remains valid.
_Avoid_: Cache header, TTL record
