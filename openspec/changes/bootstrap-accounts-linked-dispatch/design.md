# Design: Dispatch bootstrap after account linking

## Flow

1. Gateway persists the active `meli_accounts` record and a valid pending
   `bootstrap_jobs` document, then publishes persistent `accounts.linked` with
   publisher confirms and mandatory routing.
2. A durable `zeler.bootstrap.accounts` queue is bound to `meli.events` with
   routing key `accounts.linked`. The VM `bootstrap-dispatcher` consumer owns
   this queue, with a dedicated dead-letter queue. The `bootstrap` module
   registry document declares the same routing key.
3. The consumer validates the event and delegates to `BootstrapDispatcher`.
   Only a pending job for the seller can be claimed; running, completed, and
   duplicate deliveries are acknowledged without a second execution.
4. `CloudRunJobsClient` calls `zeler-bootstrap:run` with container argument
   overrides `--seller-id` and `--job-id`, matching the deployed Job entrypoint.
   The VM service account needs `roles/run.jobsExecutorWithOverrides` on this Job.
5. The consumer acknowledges only after the dispatch decision is durable.
   A transient API failure requeues within the Mongo dispatch-attempt budget;
   exhausted or invalid events dead-letter without a tight retry loop.

## Decisions and boundaries

- Use a separate bootstrap worker because gateway remains the OAuth/API edge.
  The worker image contains only bootstrap and shared package dependencies.
- Declare the queue and binding idempotently at consumer startup and keep the
  canonical RabbitMQ definitions in sync. Start and verify the consumer before
  deploying the fixed gateway image.
- Keep one consumer process with prefetch one for the initial rollout. The
  dispatcher lock is released after the Cloud Run API call on both success and
  failure; its TTL remains a crash fallback.
- Keep the existing `bootstrap_jobs` state machine. Dispatch records running
  state, start time, and counters only when it claims a pending job. A job
  execution may start before the dispatcher receives the API response, so
  state changes use conditional writes.
- Use the existing health sidecar to report RabbitMQ consumer and Mongo
  readiness. Logs expose IDs and error classes, never credentials or event
  payloads.
- A pending job without a delivered event is an operational recovery case;
  the test seller's missing job/event is recovered once after rollout.

## Rollout and rollback

1. Verify the Cloud Run Job configuration, role and VM capacity.
2. Build and deploy the dispatcher image, scoped `bootstrap` registry routing
   key, and job-level IAM binding; verify the exact `accounts.linked` queue
   binding and worker readiness.
3. Deploy the verified gateway image by digest and verify health/readiness.
4. Recreate/publish the missing test-seller bootstrap trigger once from the
   approved VM context; verify a Cloud Run execution and terminal job state.
5. On failure, stop the new dispatcher, restore the prior gateway digest, and
   inspect/park only the affected bootstrap job. Preserve the durable queue and
   its messages for safe replay; do not broadly purge RabbitMQ or Mongo data.

Cloud Build and production mutations need their own explicit authorization.
