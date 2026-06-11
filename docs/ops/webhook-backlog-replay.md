# Webhook backlog replay runbook

This runbook documents the safe operator workflow for the one-shot replay runner.
It is intentionally dry-run-first: do not execute replay, publish to RabbitMQ, or
mark MongoDB documents unless the business owner explicitly approves a specific
`--execute --run-id ...` command for one topic.

## Safety contract

- The runner is dry-run by default. `--execute` is required to publish and to
  record the approved replay outcome: main-exchange replay may mark global Mongo
  metadata, while Sheets-only freshness replay records ledger-only success.
- `--execute` also requires an operator-provided `--run-id`.
- `--execute` fails closed unless exactly one RabbitMQ gate source is provided:
  `--rabbit-management-export` or `--rabbit-management-url`.
- Allowed topics are `price_suggestion`, `user-products-families`, and Sheets
  freshness topics: `items`, `orders_v2`, `shipments`, `questions`, and
  `items_prices`. Fulldock is decommissioned, so `stock-locations` is not allowed.
- Default dedupe is `latest-per-resource`, which coalesces `price_suggestion`
  and Sheets freshness topics to the newest event per `(topic, user_id, resource)`.
- Active RabbitMQ gates are topic-specific: `price_suggestion` gates only on
  `zeler.repricer.items`.
- Sheets freshness replay publishes through exchange `zeler.sheets.replay` and
  gates on explicit proof of `zeler.sheets.replay -> zeler.sheets.events` binding
  source, routing key, and destination queue. Execute mode fails closed if binding
  data is missing or only old `meli.events -> zeler.sheets.events` bindings exist.
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

1. Recount target MongoDB documents with `published_at: null` for the allowed
   topics and compare with the baseline: `35 price_suggestion`,
   `5 user-products-families`.
2. Recount corrupt required fields and duplicates. Expected corrupt count is `0`.
3. Export RabbitMQ queue state and binding data for active queues plus DLQs:
     - `zeler.repricer.items`, `zeler.repricer.price_suggestion`
     - `zeler.sheets.events`, `zeler.sheets.user_products`
     - bindings proving `zeler.sheets.replay -> zeler.sheets.events` for
       `items.*`, `orders.*`, `shipments.*`, and `questions.*`
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

### Sheets freshness replay readiness gate

Sheets freshness topics (`items`, `orders_v2`, `shipments`, `questions`, and
`items_prices`) replay to the active Sheets queue `zeler.sheets.events` through
exchange `zeler.sheets.replay`, not the normal webhook exchange. The RabbitMQ
gate must prove all three parts before execute: source exchange
`zeler.sheets.replay`, destination queue `zeler.sheets.events`, and a binding key
that matches the topic route (`items.*`, `orders.*`, `shipments.*`, or
`questions.*`).

A sanitized export that only lists queue routing keys, or only old
`meli.events -> zeler.sheets.events` bindings, is not sufficient for execute.
Dry-run remains safe and can still produce the Mongo replay plan, but approved
execute must use an export/URL that includes binding source data.

### Fulldock stock-location queue note (archived)

Fulldock is decommissioned. Stock-location replay through Fulldock is not an
active capacity path and must remain blocked unless a future reactivation SDD
explicitly restores UI, registry scope, runtime, and RabbitMQ topology.

For the legacy readiness vocabulary, stock-locations remains `NO_GO`: do not
restore `GET /user-products/*/stock` or `PUT /items/*/stock_locations` scopes,
and require no recent gateway `out_of_scope` errors before any future
reactivation proposal even considers stock-location replay.
The archived gate also requires no `malformed_resource`, `missing_mapping`, or `resource_not_found` spike in the relevant worker logs.

### User-products-families no-go

`user-products-families` remains blocked even if an operator passes
`--allow-user-products-families`. The Sheets worker has no defined
`user_products.*` behavior or active consumer path, so replay cannot be made safe
by approval flags alone. Keep these events skipped in plans and abort forged
execution plans before any publish or Mongo mark.

### Stock-location replay readiness gate

`stock-locations` is retired with Fulldock and is not accepted by the replay CLI.
Do not compensate by replaying a smaller batch.

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

The runner publishes main-exchange replay, such as `price_suggestion`, through
exchange `meli.events`. For those main-exchange topics, MongoDB global publish
metadata may be marked only after publish confirmation: the update uses the
guard `{_id: <event>, published_at: None}` and records `replay_run_id`.

Sheets freshness replay uses an explicit internal publish path to exchange
`zeler.sheets.replay`; normal webhook message headers cannot override the
configured publisher exchange. Sheets-only freshness replay intentionally does
not mark global `webhook_events.published_at` or `webhook_events.replay_run_id`.
Its success record is ledger-only after publish confirmation.

Execution will not start without the RabbitMQ gate export/URL, and the same gate
source is re-read before every message.

## Stop conditions

Stop immediately on any of these:

- Queue ready count exceeds the approved cap.
- DLQ count grows above the approved delta.
- Required consumer is missing or unhealthy.
- Routing key does not match the expected topic route.
- Sheets replay binding source data is missing or does not prove
  `zeler.sheets.replay -> zeler.sheets.events`.
- Worker logs show requeue/DLQ, 429, or 5xx spikes.
- Stock-location logs show gateway `out_of_scope`, 403, 429 requeue spikes,
  unexpected `malformed_resource`, `missing_mapping`, or `resource_not_found`
  outcomes.
- Publish confirm fails after bounded retries.
- Main-exchange Mongo marking is ambiguous (`matched_count`/`modified_count` not
  exactly `1`). This does not apply to Sheets-only freshness replay, which has
  no global Mongo mark.
- Operator creates the abort file.

Abort command:

```bash
touch /tmp/webhook-replay/ABORT
```

For main-exchange replay, do not retry ambiguous documents until the ledger and
Mongo state are reconciled. For Sheets-only freshness replay, reconcile against
the ledger and publish evidence because there is no global Mongo mark.

## Post-check

1. For main-exchange replay, confirm successful ledger rows equal Mongo
   documents marked with the run ID.
2. For main-exchange replay, confirm coalesced/skipped documents remain
   `published_at: null`.
3. For Sheets-only freshness replay, confirm successful ledger rows for the
   approved run/topic count. Do not require global `webhook_events.published_at`
   or `webhook_events.replay_run_id`; those markers are intentionally unchanged.
4. Confirm unexpected DLQ growth is zero and queues return to normal ready/unacked
   levels.
5. Review any dedicated fanout queues that have no consumer before deciding on a
   follow-up drain/remediation plan.
6. Store sanitized plan and ledger artifacts with the incident/change record.

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
