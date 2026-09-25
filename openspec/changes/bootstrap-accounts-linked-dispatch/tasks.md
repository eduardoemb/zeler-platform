# Tasks: Dispatch bootstrap after account linking

- [x] Prove the existing Cloud Run argument mismatch and successful-dispatch
      lock leak with failing focused tests.
- [x] Add the queue/binding to canonical topology and a focused contract test.
- [x] Implement the consumer, bounded retry/dead-letter handling, and readiness
      with focused tests using real AMQP message semantics where practical.
- [x] Fix Cloud Run argument overrides and dispatcher claim/release behavior.
- [x] Add dispatcher image configuration, Compose service, env template, and rollout
      documentation; validate Dockerfile and Compose contracts without a local
      Docker build.
- [x] Run focused tests, the four root quality gates, topology checks, and
      independent SDD verification.
- [ ] Prepare separate Cloud Build and deployment proposals with exact commit,
      image digests, IAM scope, rollback, and one-seller recovery evidence.
