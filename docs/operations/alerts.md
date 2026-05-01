# Alerts catalog

## Uptime checks

- `gateway-health` — checks `https://gateway.zeler.ai/health` every 30s.
- `repricer-health` — checks `https://repricer.zeler.ai/health` every 30s.
- `sheets-health` — checks `https://sheets.zeler.ai/health` every 30s.
- `publicador-health` — checks `https://publicador.zeler.ai/health` every 30s.
- `autoreply-health` — checks `https://autoreply.zeler.ai/health` every 30s.
- `fulldock-health` — checks `https://fulldock.zeler.ai/health` every 30s.

## DLQ alerts

- `dlq-events-spike` — fires when `dlq_events_total > 0` in a 60s rolling window.

## Viewing

Use Cloud Monitoring → Alerting for policies and Cloud Logging Metrics for
`logging.googleapis.com/user/dlq_events_total`.
