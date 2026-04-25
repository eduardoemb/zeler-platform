# Bootstrap runtime wiring

The bootstrap package can run as a Cloud Run Job entrypoint without deploying from this repo.
Use `--dry-run` for packaging/argument validation; dry-run returns before reading env vars or
constructing Mongo, gateway, or RabbitMQ clients.

## Required environment

| Setting | Accepted env vars | Purpose |
|---|---|---|
| Mongo URI | `BOOTSTRAP_MONGO_URI` or `MONGO_URI` | MongoDB connection string for `bootstrap_jobs` and canonical collections. |
| Mongo DB | `BOOTSTRAP_MONGO_DB` or `MONGO_DB` | Database name, normally `zeler_platform`. |
| Gateway base URL | `BOOTSTRAP_GATEWAY_BASE_URL` or `GATEWAY_BASE_URL` | Internal gateway base URL. The runtime calls `/proxy/meli/*` under this base. |
| Gateway token | `BOOTSTRAP_GATEWAY_TOKEN`, `GATEWAY_TOKEN`, or `INTERNAL_GATEWAY_TOKEN` | Bearer token used to call the gateway. |
| RabbitMQ URL | `BOOTSTRAP_RABBITMQ_URL` or `RABBITMQ_URL` | AMQP URL for publishing bootstrap completion. |

Optional:

- `BOOTSTRAP_RABBITMQ_EXCHANGE` or `RABBITMQ_EVENTS_EXCHANGE` — defaults to `meli.events`.
- `BOOTSTRAP_GATEWAY_PATH_PREFIX` — defaults to `/proxy/meli`.
- `BOOTSTRAP_HTTP_TIMEOUT_SECONDS` — defaults to `30.0`.

## Invocation

```bash
python -m zeler_bootstrap --seller-id "$SELLER_ID" --job-id "$BOOTSTRAP_JOB_ID"
```

Safe packaging check:

```bash
python -m zeler_bootstrap --seller-id test --job-id test --dry-run
```

Missing configuration raises `RuntimeConfigError` with env var names only. Secret values and
connection strings are not included in `BootstrapRuntimeSettings.__repr__` or error messages.
