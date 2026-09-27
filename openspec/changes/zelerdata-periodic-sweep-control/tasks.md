# Tasks: ZelerData Periodic Sweep Control

- [x] Record live terminal and active job counts, the 60-item incomplete-chunk evidence, and the high traffic before the change.
- [x] RED: prove the runtime factory schedules bulk sweeps by default despite no explicit bulk opt-in.
- [x] GREEN: select only bounded range refresh by default, with an explicit flag restoring all bulk sweeps; document the operator flag.
- [x] Run focused and full repository quality gates on an isolated test target.
- [ ] Build a verified Sheets worker image from the exact committed `main` source, deploy only that worker with compatible rollback, and observe existing jobs through terminal state.
- [ ] Record a post-backlog gateway request rate and the remaining incomplete-chunk classification; close only on measured evidence.
