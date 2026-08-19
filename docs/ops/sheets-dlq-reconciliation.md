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
