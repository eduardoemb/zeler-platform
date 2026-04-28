# topics-routing-completeness Change Notes

## Deploy ordering

1. Regenerate RabbitMQ definitions locally with `uv run python -m infra.rabbitmq.amqp_setup`.
2. Import `infra/rabbitmq/definitions.json` into CloudAMQP via UI: RabbitMQ Manager → Overview → Import definitions.
3. Deploy the gateway service after the topology import is visible in CloudAMQP.
4. Deploy the repricer worker.
5. Deploy the fulldock worker.

## Ops handoff

- The CloudAMQP import is manual. An admin user must import the regenerated `definitions.json` before gateway code is promoted to production.
- Do not run the import from this change; only keep `infra/rabbitmq/definitions.json` commit-ready.

## Out of scope

- Backlog replay of `webhook_events` where `published_at: null` for `user-products-families`, `stock-locations`, or `price_suggestion`.
- Pre-existing autoreply topology gap for `questions.new` and `messages.new`.
- Data-driven webhook topic configuration refactor.
- SheetSeller consumer for `user-products-families`.
- Broader repricer resource-schema migration.
- Repricer consumer code for the dedicated `zeler.repricer.price_suggestion` queue.

## Post-archive follow-up todo

- Plan a rate-limited manual replay of backlogged `webhook_events` with `published_at: null` for the three newly routed topics.
