# Proposal: Dispatch bootstrap after account linking

## Intent

Finish the automatic path from a successful Mercado Libre OAuth callback to a
seller bootstrap execution. The gateway currently writes an active account and
a bootstrap job, but `accounts.linked` has no RabbitMQ route or running consumer.

## Scope

- Add a durable `accounts.linked` queue and a dedicated VM consumer that calls
  the existing bootstrap dispatcher, with a matching bootstrap registry key.
- Send the Cloud Run Job the required seller and job arguments.
- Make dispatch retry and locking bounded, observable, and safe for duplicate
  deliveries.
- Add Compose, environment-template, and deployment guidance for the consumer.
- Recover the already-linked test seller only after runtime rollout approval.

This change does not alter Sheets formulas, seller OAuth consent, Mercado Libre
tokens, or the Cloud Run bootstrap stage logic.

## Success criteria

- OAuth publishes `accounts.linked` to a durable route and redirects after the
  account and bootstrap job have been stored.
- A consumer dispatches one Cloud Run execution for a pending job; duplicate
  deliveries do not launch another execution.
- Transient dispatch failures retry within a finite budget and leave a visible
  failure state when exhausted.
- The deployed worker reports consumer and Mongo readiness, and a controlled
  seller execution reaches a terminal state.

## Rollout boundary

Local implementation and verification do not authorize Cloud Build, IAM, RabbitMQ
topology mutation, VM deployment, or a production bootstrap execution. The
runtime proposal must identify exact images, the job-level executor role, queue
creation, rollback, and the test seller recovery action.
