# Monitoring

## DLQ log-based metric

- Metric: `logging.googleapis.com/user/dlq_events_total`
- Source filter: `jsonPayload.event="worker.message.dlq" AND severity>=ERROR`
- Label: `seller_id` extracted from `jsonPayload.seller_id`

## DLQ alert

- Policy: `dlq-events-spike`
- Trigger: count greater than zero in a 60s rolling window
- Notification channel placeholder: `projects/${GCP_PROJECT}/notificationChannels/ops-email`

Before applying the alert in a real project, create the Ops email notification channel
ahead of time and bind it to the stable resource name
`projects/${GCP_PROJECT}/notificationChannels/ops-email` (or update the IaC to the
operator-approved channel id before promotion).
