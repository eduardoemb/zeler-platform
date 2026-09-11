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

## ZelerData freshness alert

- Metric: `logging.googleapis.com/user/zelerdata_freshness_alarm`
- Source filter: `jsonPayload.event="zelerdata.freshness_alarm" AND severity>=ERROR`
- Labels: `read_model` and `reason`, both bounded server-owned values
- Policy: `zelerdata-freshness-alarm`
- Trigger: any freshness alarm in a 300s rolling window
- Channels: `zeler-ops-email` (ops@zeler.ai) and `zelerdata-ops-email`
  (laloramirez@zeler.ai), so both operators receive everything (Q26-b)

The Sheets worker emits the alarm when a read model the refresh loop owns stops
refreshing past its own marker window, or when the refresh loop itself fails
repeatedly (Q21-a). Emitting it is behind `ZELERDATA_FRESHNESS_ALERTS_ENABLED`
on the Sheets worker; the policy above is what turns the event into an e-mail.
Each `(seller, model, reason)` alerts at most once per hour, so a long outage
stays visible without becoming noise.

Apply order, using the placeholders for the channel ids returned by Cloud
Monitoring:

```bash
gcloud logging metrics create zelerdata_freshness_alarm \
  --project="$GCP_PROJECT" \
  --config-from-file=infra/monitoring/zelerdata_freshness_metric.yaml
```

Create both e-mail channels, substitute the returned ids for
`${NOTIFICATION_CHANNEL_ID}` and `${ZELERDATA_NOTIFICATION_CHANNEL_ID}`, confirm
the new channel with the code Google sends to laloramirez@zeler.ai, and only
then create the alert policy.
