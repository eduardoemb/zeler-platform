# Bootstrap runtime wiring

The bootstrap package can run as a Cloud Run Job entrypoint without deploying from this repo.
Use `--dry-run` for packaging/argument validation; dry-run returns before reading env vars or
constructing Mongo, gateway, or RabbitMQ clients.

## Required environment

| Setting | Accepted env vars | Purpose |
|---|---|---|
| Mongo URI | `BOOTSTRAP_MONGO_URI` or `MONGO_URI` | MongoDB connection string for `bootstrap_jobs` and canonical collections. |
| Mongo DB | `BOOTSTRAP_MONGO_DB` or `MONGO_DB` | Database name. Production uses `zeler_platform_prod`; local/dev may use `zeler_platform`. |
| Gateway base URL | `BOOTSTRAP_GATEWAY_BASE_URL` or `GATEWAY_BASE_URL` | Internal gateway base URL. The runtime calls `/proxy/meli/*` under this base. |
| Gateway module ID | `BOOTSTRAP_MODULE_ID` | Module ID used by `MeliGatewayAuth`; production default is `bootstrap`. |
| RabbitMQ URL | `BOOTSTRAP_RABBITMQ_URL` or `RABBITMQ_URL` | AMQP URL for publishing bootstrap completion. |

Optional:

- `BOOTSTRAP_RABBITMQ_EXCHANGE` or `RABBITMQ_EVENTS_EXCHANGE` — defaults to `meli.events`.
- `BOOTSTRAP_GATEWAY_PATH_PREFIX` — defaults to `/proxy/meli`.
- `BOOTSTRAP_HTTP_TIMEOUT_SECONDS` — defaults to `30.0`.
- `BOOTSTRAP_GATEWAY_TOKEN`, `GATEWAY_TOKEN`, or `INTERNAL_GATEWAY_TOKEN` — development-only
  legacy bearer token. It is not accepted in production; production mints seller-scoped JWTs.

## Production Cloud Run Job contract

`infra/cloudbuild/bootstrap-job.yaml` deploys `zeler-bootstrap` with Secret Manager bindings,
not plaintext connection strings:

```bash
--set-secrets=BOOTSTRAP_MONGO_URI=${_BOOTSTRAP_MONGO_URI_SECRET}:latest,BOOTSTRAP_RABBITMQ_URL=${_BOOTSTRAP_RABBITMQ_URL_SECRET}:latest
--update-env-vars=ZELER_ENV=prod,BOOTSTRAP_MONGO_DB=zeler_platform_prod,BOOTSTRAP_GATEWAY_BASE_URL=${_BOOTSTRAP_GATEWAY_BASE_URL},BOOTSTRAP_GATEWAY_PATH_PREFIX=/proxy/meli,BOOTSTRAP_MODULE_ID=bootstrap,BOOTSTRAP_RABBITMQ_EXCHANGE=meli.events
--service-account=${_BOOTSTRAP_RUNTIME_SERVICE_ACCOUNT}
--vpc-connector=${_BOOTSTRAP_VPC_CONNECTOR}
--vpc-egress=${_BOOTSTRAP_VPC_EGRESS}
```

Default production assumptions:

- Runtime service account: `zeler-bootstrap-runtime@${PROJECT_ID}.iam.gserviceaccount.com`.
- VPC egress: `private-ranges-only`, for private Mongo/internal paths while public gateway and
  CloudAMQP continue through normal public routing. Use `all-traffic` only when Cloud NAT/private
  routing is explicitly provided.
- Required IAM for the runtime service account:
  - `roles/secretmanager.secretAccessor` on the Mongo and RabbitMQ URL secrets.
  - `roles/vpcaccess.user` for the Serverless VPC Access connector.
  - `roles/cloudkms.signerVerifier` on the `platform-jwt` key for gateway JWT signing.

## Runtime gateway authentication

In production the bootstrap job does not receive `BOOTSTRAP_GATEWAY_TOKEN`. Instead,
`build_runtime_dependencies(settings, seller_id=...)` constructs `MeliGatewayAuth` with
`BOOTSTRAP_MODULE_ID=bootstrap`, mints a short-lived KMS-signed JWT for the target seller, and
sends that bearer token on each `/proxy/meli/*` request. If KMS signing fails, the gateway request
is not attempted and token material is not logged.

Rotate by adding a new Secret Manager version for the Mongo/RabbitMQ secret or rotating the KMS
key version according to the platform JWT key procedure, then redeploy the Cloud Run Job config.

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
