# Proposed one-record legacy returns migration

Status: awaiting explicit scope authorization. No migration has been performed.

The selected closure design explicitly says “No new recovery protocol, TTL
expansion, or migration” in
[design.md](../../openspec/changes/zelerdata-live-formula-repairs/design.md).
Existing reconciliation can repair productive returns, but cannot resolve one
legacy claim from 2026-06-23 that the canonical source excludes because it has no
authoritative item identity. Keeping that row in active claims blocks the
seller-wide returns guard, including the original Sheet date range.

## Concrete scope

For pilot seller 82453304, archive exactly the privately bound June 23 legacy
claim in a new audit collection, `sheets_devoluciones_claim_quarantine`, and
remove that exact unchanged row from active `claims` in the same MongoDB
transaction. Preserve the complete original BSON and its fingerprint, source
classification, operation identity and authorization evidence. Keep the existing
productive-only rules, guard and formula semantics unchanged. This operation
alone must not publish coverage or mark DEVOLUCIONES ready.

Implement and test a fixed-scope operator command and the collection schema/index;
apply that collection's schema/index only, then execute the one-row transaction
from the approved VM after fresh source and exact-row revalidation. No other
claim, date, seller, marker bypass, cleanup or runtime topology change is included.
Production delivery must use the existing exact-source, digest/provenance and
scoped rollback process. Final image identities depend on the tested implementation.

## Read-only evidence

The binding probe found exactly one matching legacy claim. Two canonical source
acquisitions produced the same inventory/exclusion and full source payload
fingerprints: eight calls total, no order calls. Claim endpoint identity, seller
respondent and explicit returns-to-claim identity matched. The original raw BSON
was unchanged across the observations. Replica-set/session capability is present;
the existing claims validator is present. The quarantine collection's validator
and indexes are absent and require the separately included scoped installation.

Private evidence is root-owned mode 0600 in the approved worker at
`/tmp/zeler-closure-quarantine-private/jun23-bound-review.json`; its
`write_authorized` value is false. It contains the exact private selector and
full-row hash; public reports omit claim identities and payloads. Fresh binding
is mandatory before execution. Source responses have update timestamps but no
claim version or return identity; these absent fields are not invented.

## Failure and rollback behavior

Abort without moving data on source drift, row changes, lease loss, different
classification, identity mismatch or transaction failure. Archive insertion and
active removal must commit together; preserve the archive indefinitely unless a
separate retention decision authorizes otherwise. Repeated execution must verify
an identical archive and never delete a newer productive row.

Data rollback restores the original only if its active ID is still absent, under
the existing lease and in a transaction with an audit receipt. Refuse to overwrite
a newer productive row. Restoring the legacy row intentionally blocks returns
readiness again. An application image rollback alone does not restore migrated data.

## Required verification

Strict RED/GREEN tests cover exact selection, original BSON preservation,
source/row drift, identity mismatch, transaction abort, lease loss, idempotency,
concurrent productive updates and safe restoration. Run repository quality gates,
schema export validation and independent SDD verification. After an authorized
migration, read back the archive and active absence; then run normal original-range
returns reconciliation and the agreed 35-case/90-minute certification. The migration
is not proof that formulas are already reliable.
