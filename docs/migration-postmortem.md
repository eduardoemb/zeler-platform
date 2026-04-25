# Migration Post-Mortem

**Status**: DRAFT — not a completion record.
**Change**: `zeler-platform-greenfield`
**Phase**: 7 — Legacy Decommission

## Timeline

| Date | Event | Evidence | Operator |
|------|-------|----------|----------|
| TBD | P7.1 legacy repo freeze approved/executed | TBD | TBD |
| TBD | P7.2 zeler-core archive approved/executed | TBD | TBD |
| TBD | P7.3 legacy services stopped | TBD | TBD |
| TBD | P7.4 legacy DBs dropped after recovery window | TBD | TBD |
| TBD | P7.5 legacy Meli OAuth apps revoked | TBD | TBD |

## Final state checklist

- [ ] Five legacy product repositories are read-only/archived.
- [ ] `zeler-core` has final deprecation notice, migration guide, and final tag.
- [ ] Legacy Cloud Run services and VM workloads are stopped/deleted after zero-traffic verification.
- [ ] Legacy databases have final verified backups and are dropped after the recovery window.
- [ ] Legacy Meli OAuth apps are revoked and `zeler-platform` is the only active OAuth app.

## Safety notes

- P7.4 remains unchecked until the 30-day recovery window has elapsed.
- This document must not claim completion before destructive actions have human approval evidence.
- If any rollback occurs, record the trigger, restored service/repo/database, and customer impact.

## Problems encountered

TBD.

## Lessons learned

TBD.
