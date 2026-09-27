# Tasks: ZelerData Periodic Sweep Control

- [x] Record live terminal and active job counts, the 60-item incomplete-chunk evidence, and the high traffic before the change.
- [x] RED: prove the runtime factory schedules bulk sweeps by default despite no explicit bulk opt-in.
- [x] GREEN: select only bounded range refresh by default, with an explicit flag restoring all bulk sweeps; document the operator flag.
- [x] Run focused and full repository quality gates on an isolated test target.
- [x] Build a verified Sheets worker image from the exact committed `main` source and deploy only that worker with compatible rollback.
- [x] Observe existing bulk jobs through terminal state and classify the three original incomplete buybox chunks.
- [x] RED/GREEN: prove and prevent legacy order backfill from reacquiring an exact, completed, marker-covered history interval.
- [ ] Roll out the order proof guard, reconcile already admitted redundant order jobs, then record a fixed five-minute gateway rate with the worker healthy.
