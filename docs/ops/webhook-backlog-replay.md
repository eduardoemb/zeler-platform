# Webhook backlog replay runbook

This runbook documents the safe operator workflow for the one-shot replay runner.
It is intentionally dry-run-first: do not execute replay, publish to RabbitMQ, or
mark MongoDB documents unless the business owner explicitly approves a specific
`--execute --run-id ...` command for one topic.

## Safety contract

- The runner is dry-run by default. `--execute` is required to publish and mark.
- `--execute` also requires an operator-provided `--run-id`.
- `--execute` fails closed unless exactly one RabbitMQ gate source is provided:
  `--rabbit-management-export` or `--rabbit-management-url`.
- Allowed topics are only `price_suggestion`, `stock-locations`, and
  `user-products-families`.
- Default dedupe is `latest-per-resource`, which coalesces `price_suggestion` and
  `stock-locations` to the newest event per `(topic, user_id, resource)`.
- Active RabbitMQ gates are topic-specific: `price_suggestion` gates only on
  `zeler.repricer.items`; `stock-locations` gates only on
  `zeler.fulldock.events`. Legacy dedicated queues are remediation-only and do
  not block replay when the active path is healthy.
- `user-products-families` is a no-go. There is no defined Sheets
  `user_products.*` handler/consumer path, and `--allow-user-products-families`
  cannot convert undefined behavior into functional replay safety.
- Concurrency is fixed at `1`; rate must be `<= 1` message/second.
- RabbitMQ gates are evaluated before execution and re-checked before each
  message; if a gate flips unhealthy, replay aborts before the next publish.
- Do not print env files, connection strings, RabbitMQ credentials, raw webhook
  bodies, tokens, or customer payloads.

## VM/Docker context

Run the one-shot job from `platform-vm` on the compose network. The command shape
is:

```bash
docker run --rm \
  --network zeler-platform_platform_default \
  --env-file /opt/zeler-platform/env/gateway.env \
  <gateway-image> \
  python -m zeler_gateway.cli.replay_events \
  --topics price_suggestion \
  --plan-path /tmp/webhook-replay/price-plan.json \
  --failure-ledger-path /tmp/webhook-replay/price-ledger.jsonl \
  --rabbit-management-export /tmp/webhook-replay/rabbit-export.json \
  --abort-file /tmp/webhook-replay/ABORT
```

Replace `<gateway-image>` with the already approved gateway image/tag used by the
VM deployment. Do not deploy, restart, or rebuild as part of replay planning.

## Preflight (read-only)

1. Recount target MongoDB documents with `published_at: null` for the three
   allowed topics and compare with the baseline: `35 price_suggestion`,
   `53 stock-locations`, `5 user-products-families`.
2. Recount corrupt required fields and duplicates. Expected corrupt count is `0`.
3. Export RabbitMQ queue state for active and fanout queues plus DLQs:
    - `zeler.repricer.items`, `zeler.repricer.price_suggestion`
    - `zeler.fulldock.events`, `zeler.fulldock.stock_locations`
    - `zeler.sheets.events`, `zeler.sheets.user_products`
4. Confirm required active consumers, routing keys, and recent logs have no
    `worker.message.requeued`, `worker.message.dlq`, 429, or 5xx spikes.
5. Keep all preflight commands read-only. Do not purge queues.

### Price-suggestion replay readiness gate

`price_suggestion` replays through the active repricer queue
`zeler.repricer.items`, which must have a `price_suggestion.*` or
`price_suggestion.updated` binding and at least one healthy consumer. The older
dedicated queue `zeler.repricer.price_suggestion` may still appear in RabbitMQ
exports; if it has ready messages and `0` consumers, treat it as an
inspect/report-first remediation item only.

Do not purge, delete, requeue, bind, unbind, publish, replay, deploy, build, or
otherwise mutate RabbitMQ/topology from the gate report. Capture a sanitized
export, verify `zeler.repricer.items` is healthy, and get explicit operator
approval for the exact follow-up remediation command.

### Fulldock stock-location queue note

`zeler.fulldock.events` is the active Fulldock consumer queue and is expected to
bind `items.*`, `shipments.*`, and `stock_locations.*`. The dedicated
`zeler.fulldock.stock_locations` queue may exist from earlier fanout topology;
if it has ready messages and `0` consumers, treat it as an operator remediation
item, not as replay capacity.

`zeler.fulldock.stock_locations` may contain fanout copies and has no consumer;
handling requires explicit approval for the inspect/drain/purge/rebind decision,
not automatic replay gating.

Do not purge, delete, requeue, bind, unbind, publish, replay, deploy, build,
move, or otherwise mutate that queue during dry-run planning. Before any
approved cleanup, capture a sanitized management export, confirm the active
`zeler.fulldock.events` consumer is healthy, confirm DLQs are bound, and get
explicit approval for the exact queue operation/run ID.

### User-products-families no-go

`user-products-families` remains blocked even if an operator passes
`--allow-user-products-families`. The Sheets worker has no defined
`user_products.*` behavior or active consumer path, so replay cannot be made safe
by approval flags alone. Keep these events skipped in plans and abort forged
execution plans before any publish or Mongo mark.

### Stock-location replay readiness gate

stock-locations remains `NO_GO` until all stock-location readiness checks pass.
The gate is intentionally stricter than the generic RabbitMQ gate because these
events use `/user-products/{id}/stock` resources and can create wrong writes or
feedback loops if the Fulldock worker is stale.

Required checks before an operator may approve stock-location replay:

- Focused Fulldock tests for manifest scope, parser, mapping/no-op behavior,
  drift-only writes, and 403/404/429 handling have passed with `uv run pytest`.
- The active module registry for `fulldock` includes both
  `GET /user-products/*/stock` and `PUT /items/*/stock_locations`.
- Read-only gateway/audit/log review shows no recent gateway `out_of_scope` for
  `/user-products/{id}/stock` after the registry refresh.
- Fulldock history/logs show no `malformed_resource`, `missing_mapping`, or `resource_not_found` spike for stock-location traffic.
- Fulldock logs and RabbitMQ exports show no DLQ growth, 403 stop condition, or
  429 requeue spikes while the active `zeler.fulldock.events` consumer is bound
  to `stock_locations.*`.
- A sanitized dry-run plan still uses `latest-per-resource` coalescing and does
  not print raw payloads, credentials, or customer data.

If any check fails, keep stock-location replay blocked and name the failed gate
in the change/incident notes. Do not compensate by replaying a smaller batch.

## Dry-run plan

Run one topic at a time. Example:

```bash
python -m zeler_gateway.cli.replay_events \
  --topics price_suggestion \
  --limit price_suggestion=35 \
  --plan-path /tmp/webhook-replay/price-plan.json \
  --failure-ledger-path /tmp/webhook-replay/price-ledger.jsonl \
  --rabbit-management-export /tmp/webhook-replay/rabbit-export.json
```

Review the sanitized plan. It must contain selected/skipped counts, event IDs,
routing keys, and idempotency keys only. It must not contain `raw_body`, tokens,
connection strings, source IPs, or credentials.

## Execute (only after explicit approval)

Execute later, one topic at a time, with an approved run ID:

```bash
python -m zeler_gateway.cli.replay_events \
  --execute \
  --run-id ops-YYYYMMDD-topic \
  --topics price_suggestion \
  --limit price_suggestion=35 \
  --rate-per-sec 1 \
  --plan-path /tmp/webhook-replay/price-plan.json \
  --failure-ledger-path /tmp/webhook-replay/price-ledger.jsonl \
  --rabbit-management-export /tmp/webhook-replay/rabbit-export.json \
  --abort-file /tmp/webhook-replay/ABORT
```

The runner publishes through exchange `meli.events` and marks MongoDB only after
publish confirmation. It updates with the guard
`{_id: <event>, published_at: None}` and records `replay_run_id`.
Execution will not start without the RabbitMQ gate export/URL, and the same gate
source is re-read before every message.

## Stop conditions

Stop immediately on any of these:

- Queue ready count exceeds the approved cap.
- DLQ count grows above the approved delta.
- Required consumer is missing or unhealthy.
- Routing key does not match the expected topic route.
- Worker logs show requeue/DLQ, 429, or 5xx spikes.
- Stock-location logs show gateway `out_of_scope`, 403, 429 requeue spikes,
  unexpected `malformed_resource`, `missing_mapping`, or `resource_not_found`
  outcomes.
- Publish confirm fails after bounded retries.
- Mongo marking is ambiguous (`matched_count`/`modified_count` not exactly `1`).
- Operator creates the abort file.

Abort command:

```bash
touch /tmp/webhook-replay/ABORT
```

Do not retry ambiguous documents until the ledger and Mongo state are reconciled.

## Post-check

1. Confirm successful ledger rows equal Mongo documents marked with the run ID.
2. Confirm coalesced/skipped documents remain `published_at: null`.
3. Confirm unexpected DLQ growth is zero and queues return to normal ready/unacked
   levels.
4. Review any dedicated fanout queues that have no consumer before deciding on a
   follow-up drain/remediation plan.
5. Store sanitized plan and ledger artifacts with the incident/change record.

## Explicit non-actions

- Do not execute replay during planning/apply.
- Do not publish to production RabbitMQ without explicit approval.
- Do not update production MongoDB except during approved execute.
- Do not create indexes or validators from this runner.
- Do not deploy, restart, rebuild, or mutate VM/container topology for replay.

## Follow-up

- The replay path currently reuses the existing gateway publisher. A future
  hardening pass should extract a dedicated replay publisher that keeps one
  RabbitMQ connection/channel open for the full run while preserving publisher
  confirms.
