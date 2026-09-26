# ZelerData buybox load control rollout

Scope: `zeler-platform-dev`, `platform-vm`, `us-central1-a`, pilot seller `82453304`. This is a procedure, not deployment authorization. Production Mongo access stays inside the VM or runtime container. Emit aggregate counts and fingerprints only; never print publication IDs, credentials or raw documents.

## Preconditions

1. Confirm the exact authorized `main` commit and separate VERIFIED Cloud Build images for `sheets-api` and `sheets-worker`. Record their immutable digests and the previous running digests as rollback targets. Confirm the worker runtime has `MONGO_URI` and `MONGO_DB` set without printing either value.
2. Run the VM's `docker-deploy-preflight.sh --dry-run`. Require at least 5 GiB free on `/` before each pull and recheck afterward. Check Mongo mount/free space, available memory, service health, restarts and OOM flags. Preserve both rollback images; no Docker cleanup is in scope.
3. Record active `catalog_buybox_snapshots` job counts, offsets, failed chunk counts and total versus unique publication IDs for the pilot. Record Sheets gateway request and `/products/{id}/items` 404 rates, DLQ depth and memory.

## Narrow rollout

1. Stop only `sheets-worker`, allowing its current lease to finish or expire. The broker retains events. Do not stop Mongo, gateway, RabbitMQ or other product services.
2. Replace only the `sheets-api` and `sheets-worker` Compose image references with the authorized immutable digests. Use `REQUIRE_DIGEST_BINDING=1` with `DIGEST_BINDING_SERVICES=sheets-api,sheets-worker` and verify both images resolve to the authorized commit. Recreate only `sheets-api`; leave the worker stopped.
3. From a one-shot container based on the new worker image and its existing runtime environment/network, preview buybox consolidation:

   ```bash
   docker compose -f /opt/zeler-platform/docker-compose.yml run --rm --no-deps -T \
     --entrypoint /app/.venv/bin/python sheets-worker \
     -m infra.operations.sheets_item_catalog_reconcile \
     --seller-id 82453304 --read-model catalog_buybox_snapshots
   ```

   The output must show only a fingerprint and aggregate counts. Compare the active-job count and unique unfinished IDs with the read-only snapshot. The tool rejects invalid checkpoints and active leases. If fewer than two overlapping jobs remain, skip execution.
4. With separately approved queue mutation, repeat the command with `--execute --expected-fingerprint <exact preview fingerprint>`. A changed snapshot fails closed. The transaction marks old jobs superseded, preserves successful chunks and creates one replacement for unfinished IDs; it never deletes jobs.
5. Recreate only `sheets-worker`. Verify its running digest, Docker health and internal consumer/component readiness. Confirm buybox snapshots keep valid price-to-win fields while unknown offer counts render `DATA_UNAVAILABLE`. Confirm the replacement job advances without new failed chunks.

## Observe and revert

At 0, 30, 60 and 90 minutes compare Sheets requests/minute, catalog offers 404/minute, active and failed buybox jobs/offsets, gateway 429s, DLQ depth, memory and root/Mongo space. A lower 404 rate without queue progress is insufficient. Do not recommend a VM resize unless sustained pressure remains after duplicate work is removed.

If health, formula behavior or queue progress regresses, stop recovery and restore the compatible previous API/worker digests one service at a time. Keep superseded jobs and snapshots for diagnosis. Recheck readiness, image identity, DLQ and capacity after rollback.
