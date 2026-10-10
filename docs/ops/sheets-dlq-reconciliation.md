# Sheets DLQ reconciliation runbook

This runbook defines the only bounded production path for a Sheets DLQ Wave 2 snapshot; reading it or installing its files provides no execution consent.

## Purpose

The snapshot inspects at most 24 current Sheets DLQ messages and requests one `nack(requeue=True)` per delivery; it is not replay, a general consumer, a terminal disposition tool, a deployment instruction, or MongoDB work.

## Required authorization

An incident commander or designated production approver must record separate explicit consent before each execution.
The record identifies merge commit, deployed/source delta, queue `zeler.sheets.events.dlq`, limit `24`, and “bounded inspect + nack-requeue”; a prior consent never carries over.

## Approved runtime

Run only as `root` on GCE host `platform-vm`, from the installed host wrapper.
It executes only in `sheets-worker` with `docker compose exec --user 0:0`; never run it locally, in `sheets-api`, or elsewhere.

## Classification

Every DLQ message resolves to exactly one fail-closed class using the
descending evidence hierarchy `processed_events`, `sheets_devoluciones_operations`,
`webhook_events`, logs, broker, then approved external evidence. Operations
success is corroboration only, because the Sheets handler finishes the
operation before the append.

| Class | Meaning | Allowed approved transitions | Forbidden |
|---|---|---|---|
| `already_applied` | Active exact scoped key | `terminal_close_archive` only | replay, quarantine, purge, delete |
| `terminal_upstream_404` | Identity-matched sanitized 404 | `quarantine` then `terminal_close_archive` | replay, direct close/archive, purge, delete |
| `unknown_append_outcome` | No conclusive success/failure | `quarantine_manual_review` only | replay, close/archive, purge, delete |
| `replay_candidate` | Valid source, enabled export, stable key, negative append proof | `approved_dry_run` then individually approved `replay` | batch/global replay, quarantine, purge, delete |

An active key in `processed_event_claims` is **not** application evidence. That
collection holds short-lived delivery leases, so a live lease means another
delivery may still be running; only `processed_events` can classify a message as
`already_applied`. Never close, archive or replay a message because a lease
exists, and never derive `processed_events_active` from it.

## Bounded snapshot adapter runbook

The bounded snapshot adapter
(`infra/operations/sheets_dlq_snapshot_adapter.py`) is a one-shot, read-only
surface that snapshots up to `K = SNAPSHOT_CAP = 24` distinct current DLQ
messages while they remain unacked, then nacks them in ascending delivery-tag
order. It ships **inactive by default**: importing it or invoking `main`
without injected broker/runtime ports contacts no live broker, Mongo, or
subprocess. Its purpose is bounded, privacy-preserving classification and it
uses the canonical `classify_and_sanitize_one` taxonomy from this capability.
It grants no execution authorization.

## Preflight

- Authorization, lock, inherited AMQP URL, broker, passive inspection, zero consumers, `GET http://127.0.0.1:8080/health` (200/no redirects), and report/cleanup readiness must all pass before the first `get_one`.
- Any failed gate stops acquisition. Do not bypass a gate, alter the queue, or compensate with a second command.

The production authority runs inside `sheets-worker`, so it must use that container's loopback endpoint. The health server binds only to loopback; `http://sheets-worker:8080/health` resolves to the container network address and cannot reach that listener. This authority-local override does not change the archived `HttpSheetsWorkerRuntime` default, which remains the service-DNS URL for non-authority contexts.

Any unmet precondition rejects the run before any `basic.get`.

### Privacy boundary and residuals

Up to 24 raw messages may reside only in the bounded in-memory buffer while the
run is live. Raw payload bytes, ids, credentials, and URIs never enter logs,
files, stdout, HTTP bodies, Mongo documents, or Engram observations. Accepted
residuals the adapter minimizes but cannot eliminate are library/process
memory, crash dumps, external tracing/debuggers, and `/proc/<pid>/mem`
inspection. Payload fingerprints are omitted by default and only emitted when
`--payload-fingerprint-sha256` is explicitly enabled.

### Honest nack outcomes and abort

Each nack records exactly one of `requeue_requested`, `requeue_send_failed`, or
`outcome_unknown`. The adapter **never claims broker confirmation of requeue**.
On `requeue_send_failed` or `outcome_unknown` it closes the channel and issues
no further gets or nacks. SIGINT/SIGTERM trigger a best-effort channel close so
unacked messages auto-requeue; abrupt death (SIGKILL, OOM, segfault) cannot emit
a completion claim and relies on AMQP connection termination to requeue.

### Authorization separation

Design or documentation approval of this adapter **does not authorize
execution or RabbitMQ delivery/requeue**. The first authorized run uses
`K = 24` and `SNAPSHOT_CAP = 24`; any future adjustment of `K` or the cap is a
separate explicit operator decision. No worker pause, topology mutation,
publish, replay, purge, delete, quarantine, disposition, deploy, or production
run is performed by the adapter:

```bash
# Inert by default; live execution requires separately authorized injected
# broker/runtime ports and never runs without explicit operator authorization.
python -m infra.operations.sheets_dlq_snapshot_adapter --help
```

## Canonical command

After the separate explicit consent is recorded, run exactly this argument-free
command. Do not add flags, stdin, environment values, or a shell wrapper.

```bash
/opt/zeler-platform/sheets-dlq-snapshot-execute.sh
```

Direct Python invocation of `infra.operations.sheets_dlq_snapshot_runtime`, `infra.operations.sheets_dlq_snapshot_adapter`, or the execute module is forbidden in production.

## Safe placeholders

Operators never supply `<token>`, `<digest>`, `<AMQP URI>`, or `<lock path>`; do not print, copy, persist, or put them in argv.
Legacy `--authorization-token-file` and `SHEETS_DLQ_SNAPSHOT_AUTH_SHA256` are owner-only `compare_digest` inputs, not production paths.

## Token and digest

The wrapper creates a fresh 32-byte root-owned `0600` token file, binds its SHA-256 with a random run ID, queue, and limit, forwards only digest/file path, then deletes it on every exit path.

## Canonical lock

The hardcoded lock is `/var/lib/zeler-platform/sheets-dlq-snapshot/snapshot.lock`; startup creates its `root:root` `0700` directory and non-blocking contention fails closed before broker contact.

## RabbitMQ binding

`RABBITMQ_URL` is inherited only from the existing `sheets-worker` `env_file`, validated in-container, and never copied to argv, wrapper, or report.

## Limit

The fixed queue is `zeler.sheets.events.dlq`; the fixed maximum is 24 messages and one capture pass.

## Side effects

Every obtained delivery has one `nack(requeue=True)` attempt; `ack`, publish, purge, delete, quarantine, and terminal disposition are prohibited. Requeue can change delivery order and queue metrics; a failed or timed-out nack is unknown.

## Exit codes — Deterministic exits

| Exit | Reason code | Meaning |
|---:|---|---|
| 0 | `completed` | All requested requeues completed. |
| 2 | `usage` | Arguments or stdin were supplied. |
| 4 | `invalid_config` | Runtime configuration is unsafe. |
| 5 | `preflight_rejected` | Authorization rejected, lock/binding/health/consumer gate failed. |
| 6 | `message_error_or_cancelled` | Message result is unknown or execution was cancelled. |
| 7 | `close_error` | Channel or cleanup close failed. |
| 8 | `serialization_error` | Sanitized report could not serialize. |
| 70 | `sanitized_internal_error` | Internal failure without sensitive detail. |
| 75 | `token_cleanup_failed` | Successful subprocess token deletion failed. |

## Sanitized report

The module emits sanitized JSON to command stdout for the execution record: timestamp, safe revision, limit, counts, classifications,
preflight/close errors, lock/cleanup status, exit/reason codes; never payloads, headers, URI, credentials, tokens, digest, IDs, env, or traces.

## Cleanup

Success, exceptions, cancellation, `SIGTERM`, timeout, and open/close failures delete the token file, stop more gets, close the channel, release the lock, preserve the original nonzero exit, and retain unknown final state as `outcome_unknown`.

## Rollback

Remove the wrapper and `sheets-worker` bind mount, then recreate only `sheets-worker`; this restores no-execution state. Do not run a capture to test rollback.

## Stop conditions

Stop for missing consent, a preflight failure, live consumers, unhealthy worker, unknown nack outcome, cleanup error, signal, timeout,
or any request outside the fixed queue and limit.

## Retry prohibition — Blind-retry prohibition

No retry loop is permitted after nack failure, timeout, cancellation, or any nonzero result; each execution is independent and requires new consent.

## Remaining prohibitions

Do not use direct Python invocation, ad-hoc clients, recurring jobs, manual token/digest handling, ack, publish, replay, purge, delete,
quarantine, topology changes, MongoDB operations, deployment, or a generalized consumer.

## POINT_1_PASS checklist

- [ ] Wrapper, worker image, mount, and startup permissions match this runbook.
- [ ] Separate authorization exists for the reviewed execution evidence.
- [ ] Sanitized report and exit/reason map are retained without sensitive data.

Do not declare `POINT_1_PASS` in this cycle. `POINT_1_PASS` does not authorize
an execution; every production run still needs separate explicit consent.

## Dry-run plan (read-only)

Run the dry-run CLI against a capped, sanitized snapshot (local file only):

```bash
python -m infra.operations.sheets_dlq_reconcile \
  --snapshot /tmp/sheets-dlq/snapshot.json \
  --evidence /tmp/sheets-dlq/evidence.json
```

The emitted plan contains counts, hashed seller references, message
fingerprints, classifications, reason codes, and hashed evidence pointers only.
It must never include payloads, documents, raw bodies, credentials, URIs, or
OAuth data. Review it before requesting any approval.

## Bounded archive with a recorded reason (Q4-b, Q11-c)

`infra/operations/sheets_dlq_archive.py` decides the archive disposition and
`infra/operations/sheets_dlq_archive_runtime.py` executes it. The decided path
for the stuck queue is *archive with the reason recorded*, not replay.

Three reasons authorise an archive, checked in this order, and nothing else does:

| Reason | Evidence | Why it is safe |
|---|---|---|
| `resource_reread` | The platform read the message's Mercado Libre resource again at least 15 minutes after its `occurred_at`, and not in the future | The event envelope carries no data (`event_id`, `event_type`, `occurred_at`, `seller_id`, `resource`, `trace_id`, `schema_version`); the worker always re-reads the resource, so a later read already holds everything a replay could fetch |
| `window_reconciled` | `questions.*` only: the seller has a **reconciled** `questions` marker whose `reconciled_until` is at or after the message's `occurred_at` | Each question acquisition re-scans the whole marked window, so the message could only append older data |
| `age_exceeded` | The message is older than the retention bound (default 30 days) | The queue is not a data store; the read models do not depend on it, and the message is past any useful append window |

Anything else is retained and requeued.

### Read stamps behind `resource_reread`

Each event type has one stamp the platform writes only from a fresh Mercado
Libre read. Mercado Libre's own `last_updated` is never used. The run reads one
document per message by identity (or through the existing index), projecting
only the stamp.

| Event type | Read stamp | Written by |
|---|---|---|
| `items.updated`, `items.price_updated` | `items.last_meli_sync_at` | The event path and every item detail acquisition. A price event re-reads the whole publication |
| `shipments.updated` | `shipments.formula_observed_at` | Shipment recovery, right after the detail read. An event write keeps the previous value, which only understates |
| `orders.updated` | Latest `orders.items[].sale_fee_synced_at` | Every order write from `/orders/{id}`, in the same replace as the order. The bootstrap stores the order's own last change, never later than its read |
| `catalog_item_competition_status.updated` | Newest `sheets_catalog_competition_observations.observed_at` for the publication (index `seller_id, item_id, observed_at`) | The event path and buybox recovery, stamped before the `price_to_win` read |

Other event types (for example `questions.*`) have no read stamp and never use
this rule. The 15-minute margin covers Mercado Libre serving a change shortly
after its webhook and the event path stamping the read when it persists.

### Markers that do not authorise `window_reconciled`

A marker only counts when it proves that the message's resource was read after
the event. These do not, so they are not mapped:

* `item_formula_rows`: no current writer publishes a reconciled marker. The
  inventory sweep finishes without one; the marker some sellers still hold is a
  legacy reconciliation claim the refresh loop never renews.
* `shipments`: only an `observed_only` heartbeat exists.
* `catalog_buybox_snapshots`: a legacy date-range claim over stored snapshots,
  not a re-read of each publication.
* `orders`: the marker covers orders *created* inside its latest window (one
  hour for the fast sweep), and a formula-triggered window ends at the next UTC
  midnight, after the read. It would archive an update to any older order.
  Orders use `resource_reread` instead.

`questions` keeps the rule because its acquisitions re-scan the whole marked
window, but a formula-triggered window can also end after its read. No
question events have reached this DLQ; revisit the mapping if they do.

### Evidence rules

* An `observed_only` heartbeat is **not** coverage. It says the loop audited
  what it observed, never that an event that produced no observation is
  already applied, so it can never authorise an archive.
* Only the sellers named with `--seller-id` can authorise a removal, through
  either markers or read stamps. Absence of evidence is not evidence: a missing
  document, a missing or unparseable stamp, or a stamp inside the margin
  retains the message.
* A failed evidence read stops the run with `evidence_read_failed`; that
  message is requeued untouched.
* A seller with an enabled `sheets_exports` event export also gets one row per
  event in its events worksheet. No reason recovers that row (a replay would
  append current data, not the historical row). The report counts these sellers
  as `sellers_with_event_export`; review it before archiving.

Ordering is the safety property: the sanitized record is written **before** the
delivery is acked. If the write fails, the message is requeued and the run
stops, so a partial write can never remove history silently. Records carry only
`event_type`, hashed seller/resource/message references, `occurred_at`,
`reason_code`, `archived_at` and `schema_version`; raw payloads, idempotency
keys, seller ids and resource ids never leave the process. `sheets_dlq_archives`
has no validator or index under `infra/mongo/`.

### Dry run (read-only)

Run it first, as `root` on `platform-vm`, inside `sheets-worker`. It takes the
same path as the archive: it gets each message without ack, holds all of them,
decides each one and then requeues them in LIFO order, so the queue keeps its
order. It writes nothing and needs no confirmation:

```bash
cd /opt/zeler-platform && docker compose exec -T sheets-worker \
  /app/.venv/bin/python -m infra.operations.sheets_dlq_archive_runtime \
  --seller-id 82453304 --limit 500 --dry-run
```

It prints one sanitized JSON line with counts only: `scanned`, `would_archive`,
`by_reason`, `by_event_type`, `by_month`, `by_event_type_reason`,
`ready_before`, `ready_after`, `sellers_with_event_export` and
`stopped_reason`. It never prints payloads, ids or URIs. `ready_after` is read
on a fresh connection after the scan channel closes and should match
`ready_before`, apart from messages that arrived meanwhile. `--dry-run` refuses
the archive confirmations.

The snapshot planner `infra/operations/sheets_dlq_archive.py --snapshot` only
plans from a captured file and has no access to read stamps.

### Archive

After reviewing the dry run, execute with both confirmations from the same
runtime:

```bash
cd /opt/zeler-platform && docker compose exec -T sheets-worker \
  /app/.venv/bin/python -m infra.operations.sheets_dlq_archive_runtime \
  --seller-id 82453304 --limit 500 \
  --confirm-approved-runtime --confirm-archive
```

Without `--dry-run` or both confirmations the runtime refuses to run. The
report has the same counts, with `archived` instead of only `would_archive`.

The worker's optional per-cycle archive (`ZELERDATA_DLQ_ARCHIVE_ENABLED`) uses
the same decision without read stamps, so it archives only by
`window_reconciled` and `age_exceeded`.

## Approval workflow

1. Operator produces the sanitized dry-run plan.
2. For each `replay_candidate` to replay (or an allowed disposition), the
   business owner explicitly approves that exact plan digest, classification,
   action, message fingerprint, actor, and expiry.
3. The approval is recorded as an immutable ledger event.
4. Immediately before execution, the approval is re-validated: plan digest,
   classification, message fingerprint, action allowlist, and expiry. Any
   mismatch, change, or expiry fails closed.
5. Replay publish still requires passing the pre-publish duplicate check.

## Execute

Do not execute replay, purge, delete, archive/terminal-close, deploy, restart, or MongoDB/RabbitMQ mutation outside the canonical snapshot.
Replay follows the separate [`docs/ops/webhook-backlog-replay.md`](webhook-backlog-replay.md) runbook and needs an independent approved command.

## Rollback

On operator rollback:

- Stop publishing.
- Apply only the approved quarantine disposition to the remaining approved
  items via a bound, proven adapter. If no adapter is usable, fail closed and
  append nothing.
- Append one or more immutable rollback events.

## Stop conditions

- Snapshot exceeds the cap.
- Approval is expired, digest-mismatched, or its classification/action
  fingerprint no longer matches.
- Replay gate sees an active scoped key, prior replay-success event, or
  unreconciled replay reservation.
- Publisher confirm fails.
- Quarantine adapter is unavailable during rollback.
- Any ledger hash-chain link breaks (append-only integrity).

## Post-check

1. Confirm every decision and action has exactly one immutable ledger event.
2. Confirm the ledger has no update/delete path and sequence/hash-chain are
   intact.
3. Confirm no rows were duplicated in Google Sheets.
4. Store the sanitized plan and any ledger artifacts with the change record.

## Scope boundary

This change does not add UI routes, new admin scopes, A5 poller/reboot
persistence, topology changes, or runtime operations. It introduces no new
RabbitMQ topology and reuses no devoluciones/claims quarantine queue. The tool
ships inactive and dry-run-first; every schema/index application and runtime
action requires separate, explicit authorization.

## Explicit non-actions

- Do not execute during planning/apply.
- Do not publish to production RabbitMQ without explicit approval.
- Do not update production MongoDB except during an independently approved
  execute.
- Do not create indexes or validators from this tool.
- Do not deploy, restart, rebuild, or mutate VM/container topology.
- Do not launch shells or subprocesses from the CLI.

## Follow-up

The tool ships as an inert, dry-run-first planning surface. Wiring it to real
replay, quarantine, terminal-close/archive, or ledger persistence requires a
separate, fully authorized rollback-and-approval workflow before any live use.
