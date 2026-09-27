# Tasks: ZelerData Periodic Sweep Control

- [x] Record live terminal and active job counts, the 60-item incomplete-chunk evidence, and the high traffic before the change.
- [x] RED: prove the runtime factory schedules bulk sweeps by default despite no explicit bulk opt-in.
- [x] GREEN: select only bounded range refresh by default, with an explicit flag restoring all bulk sweeps; document the operator flag.
- [x] Run focused and full repository quality gates on an isolated test target.
- [x] Build a verified Sheets worker image from the exact committed `main` source and deploy only that worker with compatible rollback.
- [x] Observe existing bulk jobs through terminal state and classify the three original incomplete buybox chunks.
- [x] RED/GREEN: prove and prevent legacy order backfill from reacquiring an exact, completed, marker-covered history interval.
- [x] Roll out the order proof guard and reconcile already admitted redundant order jobs with the worker drained.
- [x] RED/GREEN: reproduce a repeated question refresh when one stored identity is absent from a complete source scan; revalidate missing identities by detail and publish confirmed 404 removal atomically.
- [x] Roll out the question reconciliation correction and observe a successful question job and inventory completion.
- [x] Measure fixed five-minute idle and normal-cycle gateway rates after backlog; verify the next scheduled orders/questions jobs, queue, health and capacity.
