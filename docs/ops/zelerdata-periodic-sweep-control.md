# ZelerData periodic sweep control rollout

Scope: `zeler-platform-dev`, `platform-vm`, `us-central1-a`, pilot seller `82453304`; only `sheets-worker` changes. Production Mongo reads and writes stay inside the VM/runtime container. Emit counts and statuses only, without identities, credentials, raw documents or upstream payloads.

## Preflight

1. Confirm the exact authorized `main` commit and a single VERIFIED Cloud Build for `sheets-worker`; record its immutable digest and the currently running worker digest as compatible rollback.
2. Confirm `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED` is absent or false in the live worker configuration. Preserve the enabled refresh and recovery settings for the pilot.
3. Run the VM capacity dry run; require at least 5 GiB free on `/` before a pull, and inspect the separate Mongo mount, available memory, inodes, Docker usage, service health, restarts and OOM flags. Do not clean Docker or mutate Mongo for this rollout.
4. Record active Sheets recovery jobs by model, state, offset, ID count and superseded status. The existing jobs continue after the worker restart; do not delete, reopen or consolidate them for this change.

## Deploy and verify

1. Back up Compose and change exactly one `sheets-worker` image reference to the verified `repo@sha256:` value. Run the selected-service digest preflight and provenance check, pull only that image, and recheck root capacity.
2. Recreate only `sheets-worker` using Compose's normal stop grace. Verify the running digest, container health, zero OOM/restarts, RabbitMQ/Mongo readiness, formula recovery and ZelerData refresh component status. Check the event queue and DLQ depth.
3. Verify a refresh cycle does not admit new inventory/catalog/shipments sweeps while order and question range refresh remains active. Formula-triggered recovery remains enabled by configuration and its existing API tests.
4. Observe at least two refresh cycles and the terminal state of every preexisting bulk job. Once no active bulk job remains, count gateway proxy calls by endpoint family and upstream status in a fixed five-minute window. Record memory, root/Mongo free space, queue depths, and any `429` alongside that rate. A low rate measured while work is paused is not sufficient; recovery must be healthy.
5. For the earlier failed buybox job, report three incomplete offsets separately. Use persisted observation counts and sanitized gateway status counts; the exact historical exception is unavailable because the job stores only `source_incomplete`. Preserve unknown competition fields as `DATA_UNAVAILABLE`.

## Rollback

If the worker loses readiness, range refresh fails or formula recovery regresses, restore the previously running immutable worker digest in the one Compose image line, run the selected-service preflight, recreate only `sheets-worker`, and verify digest, readiness, queue progress and capacity again. Reenabling full-seller periodic sweeps also restores the prior repeated load, so treat rollback as a short diagnostic state if that load recurs.
