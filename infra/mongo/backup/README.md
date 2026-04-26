# Mongo backup cron

## Purpose

This directory contains the D13 backup pipeline for the on-prem `zeler-platform` MongoDB node. The cron job runs `mongodump`, streams the archive to GCS, and prunes aged backup objects according to the retention window.

## Install

1. Copy `mongodump_cron.sh` to `/usr/local/bin/mongodump_cron.sh`.
2. Mark it executable: `chmod +x /usr/local/bin/mongodump_cron.sh`.
3. Add the cron entry:

```cron
0 3 * * * /usr/local/bin/mongodump_cron.sh >> /var/log/mongodump.log 2>&1
```

## Environment

Required environment variables:

- `MONGO_URI` — must include `?replicaSet=rs0&directConnection=true`; script will exit 1 if `replicaSet=` is absent.
- `GCS_BUCKET`

Optional environment variables:

- `BACKUP_RETENTION_DAYS` (default: `30`)

Set the environment in root's crontab via an `EnvironmentFile=`-style wrapper or export the variables before invoking the script.

## Dependencies

- `mongodump` from MongoDB Database Tools / server tools
- `gsutil` authenticated with a service account that can write to GCS

## Dead-man's-switch

If you want an external heartbeat, append the following line at the very end of the deployed script only when `HEALTHCHECKS_URL` is configured:

```bash
curl -fsS -m 10 --retry 3 "${HEALTHCHECKS_URL:-}" || true
```

This is intentionally documented rather than included in the tracked script so the contract test stays focused on the backup behavior.

## GCS Bucket Requirement

The bucket `gs://zeler-platform-backups` must already exist. It is provisioned in P0.10 and is a dependency for this cron workflow.
