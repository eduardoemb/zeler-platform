# Apply progress: gateway readiness ownership (task 7.1)

Scope: gateway health dependency ownership and app lifecycle only. Selected checkout work units; no commit, build, deployment, production access, or settlement of the orchestrator's runtime attempt. This proves local behavior, not live broker recovery or full SDD acceptance.

The installed RobustConnection exposes is_closed and connected, not is_open. Readiness now reuses its connected owner, waits on its reconnect event, and serializes absent/closed creation. A connection_class factory retains the actual candidate before connect awaits. Failed/cancelled candidates are closed; the shared connection-scoped OwnedAmqpTransport also releases pre-handshake writers that aio-pika has not yet attached. Replacement of a closed owner aborts retained writers. Shutdown closes the same owner under the creation lock and prevents later probes. Startup initialization completes after a broker failure so later readiness probes can recover; cancellation still closes Mongo and the owned attempt.

Existing HTTP response shapes, starting semantics before initialization, dependency budgets, and aggregate max(dependency budgets) + 0.2 seconds remain. Failed creation cleanup is bounded to 0.1 seconds; retained transports abort in finally. Cancellation remains cancellation.

Strict TDD evidence:

- Existing readiness baseline: 16 passed; existing lifespan baseline: 4 passed.
- Network-free actual-interface ownership regression: 7 failed before implementation; then 7 passed. Initial harness needed correction because connect_robust binds its default class at definition time; the accidental localhost test attempt was terminated and replaced with a deterministic connector preserving that factory contract.
- Startup recovery/captured-factory regression: 2 failed, 2 passed before lifecycle repair.
- DNS failure cleanup: 1 failed before expanding to installed CONNECTION_EXCEPTIONS; then passed.
- Real installed aio-pika with an ephemeral silent localhost TCP broker: timeout and external cancellation both failed peer EOF before transport capture (2 failed in 0.58s); both passed after integration. Tests assert peer closure and no surviving tasks.
- Closed-owner retained-writer regression: 1 failed, 1 passed before replacement cleanup; then passed. The companion budget test measures operation 0.02 seconds plus cleanup 0.1 seconds inside the existing 0.2-second grace and checks task drain.
- Final gateway focused suite: 36 passed in 0.70s. Ruff check and format check passed; mypy passed all 6 changed Python files.
- Independent gateway peer review by recovery_design_review: 34 selected tests passed in 0.66s, no blocking finding.

Independent reciprocal scope: reviewed core runtime checks and Sheets claims_queue_state ownership changes; 16 tests in tests/test_broker_probe_ownership.py independently passed in 0.47s. Confirmed completion-based TTL, TCP/TLS delegation, per-connection writer pruning/abort, complete operation budget, separately bounded cleanup joined through cancellation, and passive queue declaration. No blocking finding. This is scoped review, not full runtime acceptance.

Reviewable units are dependency ownership, app lifecycle, and transport/cleanup regression coverage. Authored size is intentionally not compressed: tracked Python diff 191 additions / 67 deletions across four files, plus two new tests totaling 341 lines (532 added Python lines total). The orchestrator owns final full gates and task status.

Rollback boundary: gateway app/health behavior and its tests form one unit; it imports the shared core transport owner and must be released with a core version containing that helper. No schema, topology, registry, or product data changes. Reverting only the helper while retaining this gateway import is incompatible. A complete older gateway image restores its old leak behavior; production rollback suitability and live dependency checks remain the orchestrator's responsibility.
