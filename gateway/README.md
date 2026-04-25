# Zeler Gateway

## Health checks

The gateway exposes separate liveness and readiness endpoints for Cloud Run and
external monitors:

- `GET /health` is a process-only liveness check. It returns HTTP 200 with
  `{"status":"alive"}` and does not call MongoDB or RabbitMQ.
- `GET /ready` is dependency-aware readiness. It returns HTTP 200 only when
  MongoDB and RabbitMQ are both reachable within their configured timeouts.

### Cloud Run probes

Use `/ready` for startup and readiness probes, and `/health` for liveness:

```yaml
startupProbe:
  httpGet:
    path: /ready
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 12
livenessProbe:
  httpGet:
    path: /health
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /ready
  periodSeconds: 10
```

Readiness timeout environment variables:

| Variable | Default | Description |
| --- | ---: | --- |
| `READY_MONGO_TIMEOUT_S` | `2` | MongoDB ping timeout in seconds. |
| `READY_RABBITMQ_TIMEOUT_S` | `2` | RabbitMQ readiness timeout in seconds. |

### CHANGELOG

- `/health` still returns HTTP 200, but its response body changed from
  `{"status":"ok"}` to `{"status":"alive"}`. Consumers that assert the body
  exactly must update their checks; status-code-only monitors remain compatible.
