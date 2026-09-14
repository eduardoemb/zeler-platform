# Partial acquisition projection — bounded implementation

A local strict-TDD regression wrote ten synthetic canonical item sources through
two joined sub-batches; one sub-batch then raised an ordinary acquisition error.
Before correction the error propagated with zero receipts projected. The initial
harness validation typo was corrected before recording the actual behavioral RED
in /tmp/zeler-closure-release/partial-acquisition-projection-red.log.

The worker now retains that exception until its existing projection phase ends.
It still checks lease ownership, projects only stored seller-owned sources, and
rethrows before readiness/cursor completion. A projection error becomes the cause
of the original acquisition error. External cancellation does not run a new
cleanup phase or extend a deadline. Source observations are not renewed here.

Four focused cases pass: joined partial writes, lost lease, cancellation, and
projection failure preserving the primary error. Focused Ruff/mypy pass for the
two files. Production diff is +29/-18 including indentation; the new test is94
lines. Parent owns full gates and independent verification. No runtime writes,
commit, build or deployment performed by this unit.

Runtime read-only evidence is narrower: three identities whose discrepancy tokens
persisted through all16 historical monitor samples currently match full source
fingerprints, observations, row counts and owner in two immediate rereads. Their
base ages were165–171 seconds; enrichments1189–1190 seconds. This demonstrates
current repair, not the historical cause. The1872-item job later advanced from
140 to160; the current batch contains5 transient/performance_not_generated quality
states. Source-incomplete classification alone does not skip projection: it is
calculated after projection. The locally proven skip requires an exception before
the projection phase or loss of its lease.

Expanded verification completed:453 tests passed across recovery, HTTP deadlines,
layered queue/worker lifecycle and the new partial-acquisition regression, using
the isolated development Mongo on port27028. Log:
/tmp/zeler-partial-projection-focused.log. No failures remained in this unit.

Independent review found and corrected an obsolete assertion in the existing
Mongo concurrency test: its mocked projector previously allowed only success,
so a rate-limit branch raised a secondary assertion and still expected zero rows.
The test now permits ordinary partial projection and requires exactly15 rows for
the15 successful sibling identities, with source fingerprints present, while the
job remains pending with its original source-failure classification. This edit is
test-only. Parent will rerun that parametrized test after its active full suite;
no concurrent Mongo test was started for this adjustment. Ruff/format checks pass.
