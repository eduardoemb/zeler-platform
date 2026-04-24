# Mongo restore runbook

## Prerequisites

- `gsutil` authenticated against the backup bucket
- Network reachability to the target MongoDB instance
- `mongorestore` installed from MongoDB Database Tools
- `MONGO_URI` exported for the target environment before starting

## Restore Procedure

1. Identify the backup object to restore from `gs://zeler-platform-backups/mongo/<date>/`.
2. Stream the archive directly into MongoDB:

```bash
gsutil cp gs://zeler-platform-backups/mongo/<date>/backup-<timestamp>.archive.gz - \
  | mongorestore --uri="$MONGO_URI" --archive --gzip --drop
```

3. Remember that `--drop` replaces existing collections before restore, so only run this against the intended target.

## Post-Restore: Re-apply Schema Validators

This step is CRITICAL. `mongorestore` brings back documents and indexes, but `collMod` validator metadata is not preserved in a way we can trust for this platform workflow.

From the monorepo root run:

```bash
uv run python -m infra.mongo.apply_validators
```

The `apply_validators` command must complete successfully before the restored database is considered ready for the gateway or modules.

## Verification

- Spot-check document counts for key collections such as `users`, `meli_accounts`, `items`, and `orders`.
- Verify critical indexes are present before opening traffic.
- Confirm the target MongoDB answers a health ping and that the gateway can reach it.

## Monthly Drill

Run a mandatory monthly dry-run restore into a scratch environment and record the date, operator, source object, and outcome in an ops log file such as `/var/log/zeler/mongo-restore-drills.log`.
