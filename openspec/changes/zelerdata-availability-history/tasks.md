# Tasks

- [x] Core model, exported validator and index for `sheets_item_availability_transitions`, with schema contract tests.
- [x] Change-only writer, idempotent under retries and reordering, tested against the validator in real Mongo.
- [x] Hook the writer into event persistence and acquired-item projection.
- [x] Read-time `TIEMPOSTOCKACTIVO` and `SEMANASCONSTOCK` with coverage messages, seller time zone and the observed-only gate.
- [x] Update formula docs and the time-metrics plan; record the rollout steps.
- [x] Focused tests, four root gates and schema export check.
- [ ] Integrate into `main`; production validator, index and image rollout stay with the main session under separate authorization.
