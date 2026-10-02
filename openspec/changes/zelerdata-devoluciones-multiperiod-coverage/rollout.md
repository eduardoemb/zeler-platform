# Roll out cumulative DEVOLUCIONES coverage safely

**Local implementation is not production activation.** Keep the existing June
proof available until genuine evidence has been migrated and every fact writer
is compatible. An August acquisition must add a certificate, never replace June
or certify the intervening gap. No rollout command in this document was executed
as part of implementation.

## Approval and ordering

1. Complete local root gates and optional independent SDD verification. Publish
   only with separate commit/push authorization. Build each affected image from
   the exact authorized commit on `main`, with connected-repository Cloud Build
   and `requestedVerifyOption: VERIFIED`; attest source, build ID and digest.
2. Obtain a scoped deployment proposal approval: project `zeler-platform-dev`, VM
   `platform-vm`, zone `us-central1-a`, specific services/digests, separately
   approved validators/indexes, migration/activation, verification and rollback.
   Build permission does not authorize any of these runtime mutations.
3. Measure root free bytes/inodes (at least 5 GiB before each image download),
   Mongo mount/free capacity and available memory. Record running immutable
   images, provenance, compatibility and retrievable rollback. Use the documented
   dry-run preflight; do not prune volumes or restart the whole Compose project.
4. Apply additive certificate/operation validators and indexes using the approved
   schema rollout in [deploy.md](../../../docs/deploy.md) **before activation**.
   The validator loader must preserve sibling `$expr`, not only `$jsonSchema`.
   Retain existing indexes; certificate history has no TTL eviction.
5. Deploy compatible Sheets API and worker images and update every bootstrap/job
   image that can write claims/orders. Account for already-running jobs before
   activation; stop/wait only under the approved scope. A confirmation flag is an
   operator assertion, not automatic proof that all deployed writers are current.
6. Run the read-only migration inspection below. Under separately approved write
   scope, migrate valid existing evidence, verify June preservation, then activate.
   Admission/acquisition of another period is a separate normal quota workflow,
   with its own bounded authorization; this change does not execute it.

Affected image sources: `modules/sheets/Dockerfile.api`,
`modules/sheets/Dockerfile.worker`, and `bootstrap/Dockerfile`. Shared core code is
packaged into images; inspect other image consumers before authorizing a rollout.
No gateway behavior change or global provider-budget increase is required.

## Approved-runtime commands

Run **only on the approved VM**, from `/opt/zeler-platform`, using the deployed
compatible worker's own environment. Never run production Mongo from a local
assistant, print environment files, or put credentials into command output.
Use the existing runtime Python (`.venv/bin/python` under `/app`).

Read-only candidate inspection (no lease or database writes):

```bash
sudo docker compose exec -T sheets-worker .venv/bin/python \
  -m infra.operations.devoluciones_certificate_migrate \
  --seller-id 82453304 --confirm-approved-runtime
```

Explicit approved migration, still in legacy read mode:

```bash
sudo docker compose exec -T sheets-worker .venv/bin/python \
  -m infra.operations.devoluciones_certificate_migrate \
  --seller-id 82453304 --confirm-approved-runtime --write
```

For an additional **existing genuine** completed quota acquisition, append
`--run-id <verified-run-id>` to inspection/migration. Each run must have its full
bound exact completed-window receipts and matching current canonical readback.
A completed-only run, orphan/expired unsupported singleton, row counts or a fake
source fingerprint are never enough. There is no quota-to-legacy fallback.
Expired acquisition authorization does not prohibit local recertification when
its complete immutable acquisition evidence and present facts still match.
Unsupported evidence remains unavailable; a new source scan needs separate
approval rather than fabricated history.

Activate only after compatible readers, writers, schemas and indexes are proven:

```bash
sudo docker compose exec -T sheets-worker .venv/bin/python \
  -m infra.operations.devoluciones_certificate_migrate \
  --seller-id 82453304 --confirm-approved-runtime --write --activate \
  --confirm-compatible-writers
```

This uses the existing seller operation lease and one transaction; it validates
all retained productive proofs and preserves any still-valid singleton coverage.
Interruption or a competing lease cannot partially publish/activate. Explicitly
withdrawn, unverifiable history can remain retained/unavailable without preventing
an independent valid period from being reactivated.

Read-only coverage and renewal readiness (sanitized metadata only):

```bash
sudo docker compose exec -T sheets-worker .venv/bin/python \
  -m infra.operations.zelerdata_read_model_status \
  --seller-id 82453304 --confirm-approved-runtime --devoluciones-coverage --readiness
```

The report separates gaps, expiry, invalid/reacquisition state, due backlog and
capacity. Unknown capacity is degraded, not assumed healthy. The ordinary status
command retains its existing 17-model contract unless this flag is selected.

## Acceptance: independent intervals, then durable renewal

| Gate | Required evidence |
|---|---|
| Preserve existing June | Genuine June 1 → June 11 exclusive proof and canonical data retained; separate native June formula remains available. Verify actual dates from current evidence, not this historical example alone. |
| Add August when authorized | Normal completed acquisition for August 8 → September 7 exclusive (August 8–September 6 inclusive), independent certificate and native formula output. No manual marker/data patches. |
| Do not infer missing data | Requests crossing the June/August gap remain `DATA_UNAVAILABLE`; adjacency can compose only when every point is genuinely certified. |
| Preserve output semantics | Existing formula arguments/columns/headers unchanged, overlap counts each canonical claim once, distinct claims sharing an order remain distinct. |
| Observe >30 minutes | Capture independent validity extension over the 30-minute proof horizon; no new source calls, acquisition authorization or acquisition fingerprint changes. Check at least two actual renewal cycles and actual elapsed scheduling interval. |
| Show sustainable capacity | Renewal attempts at most 20 certificates / 30 seconds, each proof at most 5 seconds; due index is used. Capacity is unknown until measured scheduling interval is at least 900 seconds. Revisit estimate must remain below 1,800 seconds with reserved margins; report overload/expiry honestly. |
| Settle service health | Recheck digests, healthy/readiness/consumers, restarts/OOM, root/Mongo/memory capacity and affected native formulas after the settling window. Startup or HTTP 200 alone is insufficient. |

The existing refresh loop owns renewal; no new timer or upstream scan is added.
Active proofs receive a bounded renewal opportunity before each due authorized
source window, including cycles whose later source attempt fails. A local renewal
error/timeout does not suppress the single authorized advancement attempt; its
ordinary lease/source gates still apply. Legacy due-window behavior is unchanged.
Older due work remains ahead of newer admissions. Retained periods are never
silently evicted. A batch deadline stops further I/O; outcome counts are unknown
if a timeout interrupts observation, and the existing operation lease expires
naturally (normally 120 seconds) if no cleanup budget remains. Do not treat this
as permission to extend validity blindly or rerun acquisition automatically.

## Conservative rollback

Before any incompatible writer returns, explicitly withdraw multiperiod authority:

```bash
sudo docker compose exec -T sheets-worker .venv/bin/python \
  -m infra.operations.devoluciones_certificate_migrate \
  --seller-id 82453304 --confirm-approved-runtime --write --rollback
```

The guarded transaction switches to legacy mode, advances the epoch and marks
certificates stale/needs reacquisition. Keep all canonical facts, certificates,
run/window receipts, additive validators and indexes. Roll back only approved
service images to the attested compatible prior digests. Never undo canonical
business facts or restore an old singleton as if it certified every interval.
Legacy availability may be narrower or unavailable; report that downgrade.
Rollback does not automatically select a certificate and synthesize a legacy
projection; it leaves the existing genuine singleton unchanged.

A legacy writer that increments an unacknowledged fence makes new reads fail
closed; the next compatible acquisition invalidates old certificates before
acknowledging the fence. That is a safety tripwire, not permission for mixed-version
activation. Reactivation requires the migration validator to recheck current facts
and genuine acquisition evidence, never just flip the mode bit.

## Writer compatibility inventory

| Entry | Shared transaction / proof handling |
|---|---|
| Quota finalizer and genuine joint one-shot | Existing operation guard; exact source-backed publication inside age/fence transaction. |
| Claim events, bootstrap, historical claims | `persist_claim_projection`; old/new membership and monotonic version checks. |
| Order events, history publication, recovery/historical order publication | `SheetsEventPersistence._persist_order`; all linked claim periods, retaining caller session. |
| Bootstrap OrdersStage and order identity/normalization repair | Existing `guarded_devoluciones_write` default before/after dependency guard. |
| Unknown relevance, explicit stale/failed state | Conservative shared invalidation; qualified known writes can recertify only exact proven pre/post transitions. |

See [apply-progress.md](apply-progress.md) for the detailed source/test inventory,
local evidence and intentionally unperformed production acceptance.
