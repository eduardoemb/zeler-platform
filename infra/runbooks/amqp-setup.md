# RabbitMQ event bus setup

Generate the topology import file:

```bash
uv run python -m infra.rabbitmq.amqp_setup --output infra/rabbitmq/definitions.json
```

Import it into the target vhost with `rabbitmqadmin import infra/rabbitmq/definitions.json`.

The topology is idempotent: a durable topic exchange `meli.events`, module queues, per-queue DLXs/DLQs, and retry delay queues are declared with stable names.

Operational notes:

- Alert when any `*.dlq` depth is greater than 100.
- Drain DLQs manually after inspecting the poison message and fixing the consumer.
- Replay stored webhook events with `python -m zeler_gateway.cli.replay_events --topic <topic> --limit <N>`.
