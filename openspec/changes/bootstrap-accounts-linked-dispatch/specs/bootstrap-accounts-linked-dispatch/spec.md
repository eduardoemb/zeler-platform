# Bootstrap account-link dispatch specification

## Requirements

### Requirement: Account-link events have a durable destination

The platform MUST bind a durable bootstrap queue to `meli.events` for
`accounts.linked` before relying on mandatory gateway publication.

#### Scenario: New account linked

- GIVEN the bootstrap consumer topology is ready
- WHEN OAuth stores a new active account and pending bootstrap job
- THEN the `accounts.linked` event is routed to the bootstrap queue
- AND the callback redirects to the success page

### Requirement: Pending bootstrap jobs dispatch once

The consumer MUST launch the configured Cloud Run Job using seller and job
arguments only for a matching pending job. Duplicate events MUST NOT launch a
second execution for a running or terminal job.

#### Scenario: First delivery

- GIVEN a pending bootstrap job for the event seller
- WHEN the consumer receives `accounts.linked`
- THEN it requests one Cloud Run execution with `--seller-id` and `--job-id`
- AND it records the dispatch decision before acknowledging the event

#### Scenario: Duplicate delivery

- GIVEN the job is running or terminal
- WHEN the same event is delivered again
- THEN the consumer acknowledges it without a new Cloud Run execution

### Requirement: Dispatch failures remain bounded and visible

The consumer MUST retry transient dispatch failures only within the configured
attempt budget. Invalid events and exhausted jobs MUST reach a durable
dead-letter or failed state. A failed dispatch MUST release its concurrency
slot, and a successful dispatch MUST release its slot after the API call.

#### Scenario: Cloud Run API unavailable

- GIVEN the API call fails for a pending job
- WHEN the consumer handles the event
- THEN the job remains eligible for bounded retry
- AND the message is not silently acknowledged

#### Scenario: Attempt budget exhausted

- GIVEN the job used its dispatch-attempt budget
- WHEN the event is delivered again
- THEN the job is marked failed and the message is dead-lettered or acknowledged
  only after that durable failure state is confirmed

### Requirement: Worker readiness reflects dependencies

The dispatcher worker MUST report healthy only while its RabbitMQ consumer and
Mongo connection are ready. A process that has merely started MUST NOT be
reported as ready.
