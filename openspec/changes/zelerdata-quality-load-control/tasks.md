# Tasks

- [x] Reproduce optional quality 404 chunk retry and add a focused regression test.
- [x] Persist a per-item quality probe, export a strict Mongo validator and test with real isolated Mongo.
- [x] Filter due quality requests and coalesce catalog plus small explicit-ID jobs transactionally.
- [x] Add dry-run-first legacy job reconciliation with fingerprint, lease check and preserved evidence.
- [x] Pass full repository quality gates and focused concurrency checks.
- [ ] Obtain separate authorization for commit, Cloud Build, validator rollout, API/worker deployment and legacy queue reconciliation.
- [ ] Verify the pilot at 0/30/60/90 minutes on the approved VM before making a capacity recommendation.
