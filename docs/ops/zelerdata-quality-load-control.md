# ZelerData quality load control rollout

Scope: `zeler-platform-dev`, `platform-vm`, `us-central1-a`, pilot seller `82453304`. This runbook is a rollout plan, not deployment authorization. Production Mongo reads and writes run only from the approved VM or runtime container. Do not print connection values, publication IDs, OAuth material or raw documents.

## Before changing runtime

1. Record the exact running digests for `sheets-api` and `sheets-worker`, the `items` validator and the active item recovery job counts. Run the read-only capacity preflight from `docs/deploy.md`; require at least 5 GiB free on `/` before either image pull. Confirm Mongo mount, memory, health, restarts and OOM flags.
2. Build one verified image per service from the exact authorized `main` commit. Check Cloud Build source commit, success, repository and immutable digest. Keep compatible rollback digests available. The new worker writes `items.quality_probe`, so an older image that rejects this field is not a safe rollback target.
3. Stop only the `sheets-worker` service and wait for running item leases to finish or expire. This briefly pauses Sheets event consumption; the broker retains queued events. Do not stop the gateway, Mongo, unrelated module services or the message broker.

## Scoped rollout

1. From the VM context, compare the live `items` validator with the exact authorized commit's `infra/mongo/schemas/items.json` and save the prior validator. Place only that JSON file in a temporary `schemas/` directory and run `infra.mongo.apply_validators --schemas-dir <temporary schemas directory> --check`, then the same command without `--check` after scoped approval. The directory's sibling `indexes/` must be absent, so no other collection or index is touched. Check that only `items` reports applied or unchanged. Confirm the validator with the isolated Mongo test evidence; do not write a synthetic production item.
2. Deploy only `sheets-api` at the authorized immutable digest and stage the authorized `sheets-worker` image while the service remains stopped. Check API health. Keep the worker stopped until the old jobs are consolidated.
3. Run the new command from a one-shot container based on that worker image with runtime Mongo access and the same private network; do not start the worker process yet:

   ```bash
   docker compose -f infra/gce/docker-compose.yml run --rm --no-deps -T \
     --entrypoint .venv/bin/python sheets-worker \
     -m infra.operations.sheets_item_catalog_reconcile --seller-id 82453304
   ```

   It prints a fingerprint and aggregate counts only. Check the count and lease state against the read-only snapshot. With separately approved queue mutation, pass that exact fingerprint to `--execute --expected-fingerprint <fingerprint>`. A changed snapshot or active lease fails closed. The command marks overlapping old jobs as superseded and creates one job for IDs still unfinished; it does not delete jobs or claim freshness. If only one active job remains, do not execute.
4. Resume the Sheets worker. Verify the replacement job proceeds to a terminal state, `ZELERDATA_CALIDAD` shows `DATA_UNAVAILABLE` for a source without quality, an available quality example remains correct, and a manual formula refresh does not immediately cause a second quality probe for an unchanged item.

## Observation and rollback

Measure at 0, 30, 60 and 90 minutes: worker requests/minute, `/performance` 404/minute, active/failed item jobs and their offsets, gateway rate limits, DLQ depth, worker health/restarts/OOM, VM available memory and root/Mongo disk. Compare with the 26 September baseline of 6,606 Sheets worker requests in 40 minutes, including 681 performance 404s. A reduction without queue progress is not success. If errors rise or progress stalls, stop recovery and restore compatible API/worker images using the exact recorded digests; preserve the validator and all probe/job documents for diagnosis. Recommend a VM resize only after this observation shows sustained pressure with the repetitive work removed.
